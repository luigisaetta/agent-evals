"""
Author: L. Saetta
Date last modified: 2026-11-10
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
from agent_evals.task import SHARED_SCORE_NAMES, EvaluationTask, load_task


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
        if response.get("execution_error"):
            error = response["execution_error"]
            result["error"] = error
            result["status"] = error["kind"] if error["kind"] in {
                "api_error", "invalid_output",
            } else "agent_error"
            return _finish_result(result, case, task, started)
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
    return _finish_result(result, case, task, started)


def _extra_scores(case: dict, result: dict, task: EvaluationTask) -> dict:
    """Compute optional task-specific binary scores without changing the case status.

    Args:
        case: Validated dataset case with its reference.
        result: Case result after status classification.
        task: Task descriptor, possibly without an extra-score callback.

    Returns:
        Metric names mapped to 0, 1 or None (not applicable).

    Raises:
        ValueError: If the callback returns an invalid name or value.
    """
    if task.extra_scores is None:
        return {}
    scores = task.extra_scores(case, result)
    if not isinstance(scores, dict):
        raise ValueError("Extra scores must be a dictionary")
    for name, value in scores.items():
        if (not isinstance(name, str) or not name.strip() or name in SHARED_SCORE_NAMES
                or name == task.metric_name):
            raise ValueError("Invalid or conflicting extra-score name")
        if value is not None and (isinstance(value, bool) or value not in (0, 1)):
            raise ValueError("Extra scores must be 0, 1 or None")
    return scores


def _finish_result(result: dict, case: dict, task: EvaluationTask, started: float) -> dict:
    """Add case success, optional extra scores and latency to a classified result.

    Args:
        result: Case result whose status is final.
        case: Validated dataset case with its reference.
        task: Task descriptor.
        started: perf_counter value taken before invocation.

    Returns:
        The same result, completed in place.
    """
    result["case_success"] = int(result["status"] == "correct")
    try:
        result["extra_scores"] = _extra_scores(case, result, task)
    except Exception as error:
        result["extra_scores"] = {}
        result["extra_score_error"] = {"type": type(error).__name__}
    result["latency_seconds"] = round(time.perf_counter() - started, 6)
    return result


def summarize_extra_scores(results: list[dict]) -> dict:
    """Aggregate each extra metric over the cases where it applies.

    Args:
        results: Persisted case results.

    Returns:
        For each metric: scored cases, cases equal to 1, and their ratio.
    """
    totals = {}
    for result in results:
        for name, value in (result.get("extra_scores") or {}).items():
            if value is not None:
                entry = totals.setdefault(name, {"scored_count": 0, "correct_count": 0})
                entry["scored_count"] += 1
                entry["correct_count"] += value
    return {name: entry | {"accuracy": entry["correct_count"] / entry["scored_count"]}
            for name, entry in sorted(totals.items())}


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
              metadata: dict, task_definition: EvaluationTask, tracking=None, hosted_items=None,
              compact_progress: bool = False) -> dict:
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
        compact_progress: Update OK/KO counters instead of printing each case.

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
    ok_count = 0
    if compact_progress:
        progress.set_postfix(OK=0, KO=0)

    def task(*, item, **kwargs):
        """Execute one SDK or local item with pacing and durable output.

        Args:
            item: Local case dictionary or hosted Langfuse dataset item.
            **kwargs: Additional experiment SDK context.

        Returns:
            Scored case result for the Langfuse evaluator.
        """
        nonlocal ok_count, publication, run_error
        case = by_id[item.metadata["case_id"]] if tracking else item
        if results and task_definition.create_invoker is None:
            time.sleep(sleep_seconds)
        observation = tracking.start_as_current_observation(
            name=f"oci-{task_definition.name}", as_type="generation", model=metadata["model"],
            input={"instructions": metadata["instructions"], "input": case["input"]},
            model_parameters={"max_output_tokens": metadata["max_output_tokens"]},
            metadata={"model_interface": metadata.get("model_interface", "responses")},
        ) if tracking and task_definition.create_invoker is None else nullcontext()
        with observation as generation:
            result = evaluate_case(case, invoke, task_definition)
            if tracking:
                try:
                    trace_id = tracking.get_current_trace_id()
                except Exception:
                    trace_id = None
                result["trace_id"] = trace_id if isinstance(trace_id, str) else None
            result["metadata"] = result["metadata"] | {
                "model": metadata.get("model"), "task_name": task_definition.name,
                "model_interface": metadata.get("model_interface", "responses"),
            }
            # Save locally before any trace update that could fail.
            with (output_dir / "results.jsonl").open("a") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            results.append(result)
            if result.get("publication_errors"):
                publication = "failed"
                run_error = "LangfuseObservationError"
            ok_count += int(result["status"] == "correct")
            if compact_progress:
                progress.set_postfix(OK=ok_count, KO=len(results) - ok_count, refresh=False)
            progress.update(1)
            http_status = (result["error"] or {}).get("http_status")
            detail = f" (HTTP {http_status})" if http_status else ""
            if result["status"] == "api_error" and not http_status:
                detail = f" ({result['error'].get('type', 'APIError')}: {result['error'].get('reason', 'Request failed')})"
            if not compact_progress:
                tqdm.write(f"[{len(results)}/{len(cases)}] {case['id']}: {result['status']}{detail}")
            if generation:
                generation.update(
                    output=result["raw_output"], usage_details=result["usage"],
                    level="ERROR" if result["status"] in {"api_error", "invalid_output", "evaluator_error", "agent_error"} else "DEFAULT",
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
                not SHARED_SCORE_NAMES.issubset({e.name for e in item.evaluations})
                or (isinstance(item.output, dict) and item.output.get("score") is not None
                    and task_definition.metric_name not in {e.name for e in item.evaluations})
                for item in experiment.item_results
            ):
                run_error = "LangfuseExperimentItemError"
                publication = "failed"
            else:
                if publication != "failed":
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
            "model": metadata.get("model"), "ok_count": ok_count,
            "model_interface": metadata.get("model_interface", "responses"),
            "ko_count": len(results) - ok_count,
            "ko_cases": [{"case_id": r["case_id"], "status": r["status"], "error": r["error"]}
                         for r in results if r["status"] != "correct"],
            "extra_score_summary": summarize_extra_scores(results),
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if compact_progress:
            print(f"Completed: OK={ok_count} KO={len(results) - ok_count}")
            print("KO case IDs:" if summary["ko_cases"] else "KO case IDs: none")
            for failure in summary["ko_cases"]:
                stage = (failure["error"] or {}).get("stage")
                detail = f", stage={stage}" if stage else ""
                print(f"  {failure['case_id']}: {failure['status']}{detail}")
            for name, entry in summary["extra_score_summary"].items():
                failed = [r["case_id"] for r in results if (r.get("extra_scores") or {}).get(name) == 0]
                print(f"{name}: {entry['correct_count']}/{entry['scored_count']} correct"
                      + (f"; failed: {', '.join(failed)}" if failed else ""))
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
    parser.add_argument("--compact-progress", action="store_true",
                        help="Show live OK/KO counts and log KO IDs only at the end.")
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
                "model_interface": getattr(settings, "model_interface", "responses"),
                "model_name": getattr(settings, "model_name", "") or settings.model,
                "sleep_seconds": settings.sleep_seconds, "timeout_seconds": settings.timeout_seconds,
                "max_output_tokens": settings.max_output_tokens, "automatic_retries": 0,
                "sdk_versions": {n: version(n) for n in ("openai", "oci-genai-auth", "langfuse")},
                "code_sha256": {str(p.relative_to(Path(__file__).parent)): file_hash(p)
                                for p in Path(__file__).parent.rglob("*.py")},
                "task_source_sha256": task_source_hashes(task_definition),
                "task_artifact_sha256": {str(p): file_hash(ROOT / p)
                                         for p in task_definition.source_files},
            }
            if task_definition.create_invoker is not None:
                metadata["sdk_versions"]["langgraph"] = version("langgraph")
            if metadata["model_interface"] == "langchain_oci":
                metadata["sdk_versions"].update({
                    name: version(name) for name in ("langchain-oci", "langchain-core", "oci")
                })
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
            next_step = 9 if tracking else 5
            if task_definition.create_invoker:
                with initialization_step(next_step, "Prepare agent execution pipeline"):
                    invoke = task_definition.create_invoker(
                        client=client, settings=settings, rules=rules, tracking=tracking,
                    )
                next_step += 1
            else:
                def invoke(task_input: dict) -> dict:
                    """Invoke one task through the selected shared model interface."""
                    return invoke_model(client, settings, instructions, task_input)
            print(f"[{next_step}] Initialization complete; starting evaluation ... OK", flush=True)
            summary = run_cases(
                cases, invoke,
                settings.sleep_seconds, args.output_dir / run_id, metadata,
                task_definition, tracking, items, args.compact_progress,
            )
        print(json.dumps(summary, indent=2))
        print(f"Local results: {args.output_dir / run_id}")
        if summary["run_error"] or summary["publication"] == "failed":
            return 1
        return 2 if any(summary["status_counts"].get(s, 0)
                        for s in ("api_error", "invalid_output", "evaluator_error", "agent_error")) else 0
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
