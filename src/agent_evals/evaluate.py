"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Run reusable sequential OCI evaluations with task-specific adapters.
"""

import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import inspect
import json
from pathlib import Path
import time
from uuid import uuid4

from tqdm import tqdm

from agent_evals.config import ConfigurationError, ROOT, load_settings
from agent_evals.console import initialization_step, show_banner
from agent_evals.dataset import file_hash, load_cases
from agent_evals.errors import describe_api_error
from agent_evals.oci_model import create_client, invoke_model
from agent_evals.task import EvaluationTask, load_task


def task_source_hashes(task: EvaluationTask) -> dict:
    """Hash source files implementing the selected task, including custom modules.

    Args:
        task: Task descriptor containing the domain callbacks.

    Returns:
        Callback-to-source hashes, with null for callbacks without a source file.
    """
    hashes = {}
    for name in ("validate_case", "build_instructions", "parse_output", "score_output"):
        try:
            source = inspect.getsourcefile(getattr(task, name))
        except TypeError:
            source = None
        hashes[name] = file_hash(Path(source)) if source and Path(source).is_file() else None
    return hashes


def evaluate_case(case: dict, invoke, task: EvaluationTask) -> dict:
    """Invoke and score one case without exposing reference answers to the model.

    Args:
        case: Validated dataset case, including the separate reference answer.
        invoke: Callable receiving only the task input and returning response data.
        task: Domain output parser and binary scorer.

    Returns:
        Per-case result with status, optional score and safe error classification.
    """
    started = time.perf_counter()
    result = {
        "case_id": case["id"], "metadata": case["metadata"],
        "expected_output": case["expected_output"],
        "output": None, "output_valid": False, "status": "api_error", "score": None,
        "raw_output": None, "usage": {}, "error": None,
    }
    try:
        response = invoke(case["input"])
    except Exception as error:
        result["error"] = describe_api_error(error)
    else:
        result.update(response)
        try:
            if response["response_status"] != "completed":
                raise ValueError("Response did not complete")
            output = task.parse_output(response["raw_output"], case["input"])
            json.dumps(output, allow_nan=False)
        except ValueError:
            result["status"] = "invalid_output"
            result["error"] = {"type": "InvalidModelOutput"}
        except Exception as error:
            result["status"] = "evaluator_error"
            result["error"] = {"type": type(error).__name__}
        else:
            result["output"] = output
            result["output_valid"] = True
            try:
                score = task.score_output(output, case["expected_output"])
                if not isinstance(score, (int, float)) or score not in (0, 1):
                    raise ValueError("Task scorer must return binary correctness")
                result["score"] = int(score)
                result["status"] = "correct" if score else "incorrect"
            except Exception as error:
                result["status"] = "evaluator_error"
                result["error"] = {"type": type(error).__name__}
    result["latency_seconds"] = round(time.perf_counter() - started, 6)
    return result


def summarize(results: list[dict], selected_count: int) -> dict:
    """Aggregate metrics with explicit denominators and failure counts.

    Args:
        results: Persisted case results.
        selected_count: Number of cases selected before execution.

    Returns:
        Attempt counts, status counts, accuracy and overall success rate.
    """
    counts = Counter(r["status"] for r in results)
    valid = counts["correct"] + counts["incorrect"]
    return {
        "selected_count": selected_count, "attempted_count": len(results),
        "unattempted_count": selected_count - len(results), "valid_scored_count": valid,
        "status_counts": dict(counts),
        "accuracy": counts["correct"] / valid if valid else None,
        "success_rate_all_attempts": counts["correct"] / len(results) if results else None,
    }


def run_cases(cases: list[dict], invoke, sleep_seconds: float, output_dir: Path,
              metadata: dict, task_definition: EvaluationTask, tracking=None, hosted_items=None) -> dict:
    """Execute sequentially, persist each result, and optionally track an experiment.

    Args:
        cases: Selected cases in execution order.
        invoke: Callable invoking the model using task input only.
        sleep_seconds: Full pause between successive attempts.
        output_dir: Unique run directory for metadata, JSONL and summary.
        metadata: Safe experiment metadata, without credentials.
        task_definition: Domain-specific parsing, scoring and metric settings.
        tracking: Optional initialized Langfuse client.
        hosted_items: Uploaded Langfuse items corresponding to the cases.

    Returns:
        Summary including local metrics and publication submission state.
    """
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results = []
    by_id = {c["id"]: c for c in cases}
    summary = {}
    publication = "disabled" if tracking is None else "pending"
    run_error = None
    experiment_url = None
    progress = tqdm(total=len(cases), desc="Evaluating cases", unit="case", dynamic_ncols=True)

    def task(*, item, **kwargs):
        """Execute one SDK or local item with pacing and durable output.

        Args:
            item: Local case dictionary or hosted Langfuse dataset item.
            **kwargs: Additional experiment SDK context.

        Returns:
            Scored case result for the Langfuse evaluator.
        """
        case = by_id[item.metadata["case_id"]] if tracking else item
        if results:
            time.sleep(sleep_seconds)
        observation = tracking.start_as_current_observation(
            name=f"oci-{task_definition.name}", as_type="generation", model=metadata["model"],
            input={"instructions": metadata["instructions"], "input": case["input"]},
            model_parameters={"max_output_tokens": metadata["max_output_tokens"]},
        ) if tracking else nullcontext()
        with observation as generation:
            result = evaluate_case(case, invoke, task_definition)
            # Save locally before any trace update that could fail.
            with (output_dir / "results.jsonl").open("a") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            results.append(result)
            progress.update(1)
            http_status = (result["error"] or {}).get("http_status")
            detail = f" (HTTP {http_status})" if http_status else ""
            if result["status"] == "api_error" and not http_status:
                detail = f" ({result['error']['type']}: {result['error']['reason']})"
            tqdm.write(f"[{len(results)}/{len(cases)}] {case['id']}: {result['status']}{detail}")
            if generation:
                generation.update(
                    output=result["raw_output"], usage_details=result["usage"],
                    level="ERROR" if result["status"] in {"api_error", "invalid_output", "evaluator_error"} else "DEFAULT",
                    status_message=result["status"],
                )
        return result

    try:
        if tracking:
            from agent_evals.langfuse_tracking import make_evaluator

            experiment = tracking.run_experiment(
                name=metadata["experiment_name"], run_name=metadata["run_name"],
                data=hosted_items, task=task, evaluators=[make_evaluator(task_definition.metric_name)],
                max_concurrency=1,
                metadata={k: str(v) for k, v in metadata.items() if k != "instructions"},
            )
            experiment_url = experiment.experiment_url
            if len(experiment.item_results) != len(cases) or any(
                not {"valid_output", "execution_status"}.issubset({e.name for e in item.evaluations})
                or (isinstance(item.output, dict) and item.output.get("score") is not None
                    and task_definition.metric_name not in {e.name for e in item.evaluations})
                for item in experiment.item_results
            ):
                run_error = "LangfuseExperimentItemError"
                publication = "failed"
            else:
                publication = "submitted_unverified"
        else:
            for case in cases:
                task(item=case)
        if len(results) != len(cases):
            run_error = "IncompleteExperiment"
    except Exception as error:
        run_error = type(error).__name__
        if tracking:
            publication = "failed"
    finally:
        progress.close()
        if tracking:
            try:
                tracking.flush()
            except Exception:
                publication = "failed"
                run_error = run_error or "LangfuseFlushError"
        summary = summarize(results, len(cases)) | {
            "run_id": metadata["run_id"], "publication": publication,
            "run_error": run_error, "experiment_url": experiment_url,
            "result_schema_version": 2, "task_name": task_definition.name,
            "task_version": task_definition.version, "metric_name": task_definition.metric_name,
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    """Run validation or a task-selected OCI evaluation from the command line.

    Args:
        argv: Optional CLI arguments, defaulting to the process arguments.

    Returns:
        Exit code: 0 for completion, 1 for setup/publication failure, 2 for invalid
        outputs, evaluator failures or provider errors. Valid incorrect answers alone do not fail
        the command because no experiment acceptance threshold is defined yet.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="agent_evals.tasks.offer_selection",
                        help="Trusted Python module exporting an EvaluationTask named TASK.")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--split", choices=["evaluation", "development", "all"], default="evaluation")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep-seconds", type=float)
    parser.add_argument(
        "--experiment-name", "--run-name", dest="experiment_name", required=True,
        help="Experiment name used in Langfuse (--run-name is an alias).",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/runs")
    parser.add_argument("--no-langfuse", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.experiment_name.strip():
        parser.error("--experiment-name must not be blank")
    try:
        task_definition = load_task(args.task)
        show_banner(task_definition.title)
        dataset_path = args.dataset or ROOT / task_definition.default_dataset
        rules_path = args.rules or ROOT / task_definition.default_rules
        with initialization_step(1, "Load dataset and verify structure and hashes"):
            cases = load_cases(dataset_path, rules_path, args.split, args.limit, task_definition)
        if args.dry_run:
            print(f"Validated {len(cases)} cases for {task_definition.title}; no external calls made.")
            return 0
        with initialization_step(2, "Load environment settings"):
            settings = load_settings(args.env_file, args.sleep_seconds)
        with initialization_step(3, "Read rules and prepare run metadata"):
            rules = rules_path.read_text()
            manifest = json.loads(dataset_path.with_suffix(".manifest.json").read_text())
            instructions = task_definition.build_instructions(rules)
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
            metadata = {
                "run_id": run_id, "experiment_name": args.experiment_name,
                "run_name": f"{args.experiment_name}-{run_id}",
                "dataset_sha256": file_hash(dataset_path), "rules_sha256": file_hash(rules_path),
                "prompt_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                "instructions": instructions, "rules_version": manifest["rules_version"],
                "dataset_version": manifest["dataset_version"], "result_schema_version": 2,
                "task_name": task_definition.name, "task_module": args.task,
                "task_version": task_definition.version, "metric_name": task_definition.metric_name,
                "model": settings.model, "region": settings.region, "split": args.split,
                "sleep_seconds": settings.sleep_seconds, "timeout_seconds": settings.timeout_seconds,
                "max_output_tokens": settings.max_output_tokens, "automatic_retries": 0,
                "sdk_versions": {n: version(n) for n in ("openai", "oci-genai-auth", "langfuse")},
                "code_sha256": {str(p.relative_to(Path(__file__).parent)): file_hash(p)
                                for p in Path(__file__).parent.rglob("*.py")},
                "task_source_sha256": task_source_hashes(task_definition),
            }
        # Build the signing client before publishing any dataset records.
        with initialization_step(4, "Initialize OCI IAM signing client"):
            client = create_client(settings)
        with client:
            tracking, items = None, None
            if not args.no_langfuse:
                from agent_evals.langfuse_tracking import prepare_experiment

                tracking, items, name = prepare_experiment(
                    cases, metadata["dataset_sha256"], args.split, task_definition,
                    manifest["dataset_version"], manifest["rules_version"],
                )
                metadata["dataset_name"] = name
            print(f"[{9 if tracking else 5}] Initialization complete; starting evaluation ... OK", flush=True)
            summary = run_cases(
                cases, lambda task: invoke_model(client, settings, instructions, task),
                settings.sleep_seconds, args.output_dir / run_id, metadata,
                task_definition, tracking, items,
            )
        print(json.dumps(summary, indent=2))
        print(f"Local results: {args.output_dir / run_id}")
        if summary["run_error"] or summary["publication"] == "failed":
            return 1
        return 2 if any(summary["status_counts"].get(s, 0)
                        for s in ("api_error", "invalid_output", "evaluator_error")) else 0
    except ConfigurationError as error:
        print(f"Evaluation setup failed: {error}")
        return 1
    except (ValueError, OSError, KeyError) as error:
        # Configuration errors generated here contain variable names, not values.
        print(f"Evaluation setup failed ({type(error).__name__}). Check configuration and dataset provenance.")
        return 1
    except Exception as error:
        print(f"Evaluation setup failed ({type(error).__name__}); no successful run is claimed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
