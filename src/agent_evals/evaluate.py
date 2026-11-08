"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Run sequential OCI offer evaluations with optional Langfuse tracking.
"""

import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import socket
import ssl
import time
from uuid import uuid4

from tqdm import tqdm
import httpx

from agent_evals.config import ConfigurationError, ROOT, load_settings
from agent_evals.oci_model import build_instructions, create_client, invoke_model
from agent_evals.selection import select_best_offer


def file_hash(path: Path) -> str:
    """Compute a source artifact hash.

    Args:
        path: File to hash.

    Returns:
        Hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(dataset_path: Path, rules_path: Path, split: str, limit: int | None) -> list[dict]:
    """Validate the dataset and select cases before making external calls.

    Args:
        dataset_path: Dataset JSON file.
        rules_path: Rules file whose provenance must match the dataset manifest.
        split: Evaluation, development, or all cases.
        limit: Optional positive maximum number of cases.

    Returns:
        Selected validated cases in their stored order.

    Raises:
        ValueError: If schema, labels, provenance, or selection are invalid.
    """
    if split not in {"evaluation", "development", "all"}:
        raise ValueError("Unknown dataset split")
    if limit is not None and limit <= 0:
        raise ValueError("Case limit must be positive")
    manifest = json.loads(dataset_path.with_suffix(".manifest.json").read_text())
    if manifest["dataset_sha256"] != file_hash(dataset_path):
        raise ValueError("Dataset hash differs from its manifest")
    if manifest["source_sha256"]["rules/offer-selection.md"] != file_hash(rules_path):
        raise ValueError("Rule contents differ from the dataset's reference rules")
    cases = json.loads(dataset_path.read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must be a non-empty array")
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "input", "expected_output", "metadata"}:
            raise ValueError("Invalid dataset case fields")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in identifiers:
            raise ValueError("Case identifiers must be unique non-empty strings")
        identifiers.add(case_id)
        if set(case["input"]) != {"request", "offers"} or len(case["input"]["offers"]) != 6:
            raise ValueError(f"Invalid six-offer task input: {case_id}")
        if case["metadata"].get("split") not in {"development", "evaluation"}:
            raise ValueError(f"Missing or invalid split: {case_id}")
        if case["metadata"].get("rules_version") != manifest["rules_version"]:
            raise ValueError(f"Rules version mismatch: {case_id}")
        if case["expected_output"] != {"expected_offer_id": select_best_offer(case["input"])}:
            raise ValueError(f"Reference output disagrees with oracle: {case_id}")
    selected = [c for c in cases if split == "all" or c["metadata"]["split"] == split]
    if not selected:
        raise ValueError("No cases selected")
    return selected[:limit] if limit is not None else selected


def parse_selection(raw_output: str, task_input: dict) -> str:
    """Parse a strict selection response and validate its offer identifier.

    Args:
        raw_output: Model text expected to contain only a JSON object.
        task_input: Original offers used to validate the returned identifier.

    Returns:
        Selected offer identifier.

    Raises:
        ValueError: If JSON, output fields or offer identifier are invalid.
    """
    def unique_fields(pairs):
        """Reject duplicate output keys instead of accepting the last value.

        Args:
            pairs: JSON object key-value pairs.

        Returns:
            Object with unique keys.

        Raises:
            ValueError: If a key appears more than once.
        """
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate output fields")
            result[key] = value
        return result

    if not isinstance(raw_output, str):
        raise ValueError("Model output must be text")
    result = json.loads(raw_output, object_pairs_hook=unique_fields)
    if not isinstance(result, dict) or set(result) != {"selected_offer_id"}:
        raise ValueError("Expected exactly one selected_offer_id field")
    selected = result["selected_offer_id"]
    if not isinstance(selected, str) or selected not in {o["offer_id"] for o in task_input["offers"]}:
        raise ValueError("Selected offer ID is not present in the input")
    return selected


def describe_api_error(error: Exception) -> dict:
    """Describe provider failures without exposing raw exception messages.

    Args:
        error: Provider exception, possibly wrapping a transport failure.

    Returns:
        Safe exception types, HTTP status and a readable failure category.
    """
    status_code = getattr(error, "status_code", None)
    current = error
    seen = set()
    reason = None
    cause_type = type(error).__name__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        cause_type = type(current).__name__
        for exception_type, category in (
            (socket.gaierror, "DNS resolution failed"),
            (ssl.SSLError, "TLS certificate or handshake failed"),
            (httpx.TimeoutException, "Request timed out"),
            (TimeoutError, "Request timed out"),
            (httpx.ProxyError, "Proxy connection failed"),
            (ConnectionRefusedError, "Connection refused"),
        ):
            if isinstance(current, exception_type):
                reason = category
        current = current.__cause__ or current.__context__
    return {
        "type": type(error).__name__,
        "http_status": status_code if isinstance(status_code, int) else None,
        "cause_type": cause_type,
        "reason": reason or cause_type,
    }


def evaluate_case(case: dict, invoke) -> dict:
    """Invoke and score one case without exposing reference answers to the model.

    Args:
        case: Validated dataset case, including the separate reference answer.
        invoke: Callable receiving only the task input and returning response data.

    Returns:
        Per-case result with status, optional score and safe error classification.
    """
    started = time.perf_counter()
    result = {
        "case_id": case["id"], "metadata": case["metadata"],
        "expected_offer_id": case["expected_output"]["expected_offer_id"],
        "selected_offer_id": None, "status": "api_error", "score": None,
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
            selected = parse_selection(response["raw_output"], case["input"])
        except (ValueError, TypeError, KeyError):
            result["status"] = "invalid_output"
            result["error"] = {"type": "InvalidModelOutput"}
        else:
            result["selected_offer_id"] = selected
            result["score"] = int(selected == result["expected_offer_id"])
            result["status"] = "correct" if result["score"] else "incorrect"
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
        "selection_accuracy": counts["correct"] / valid if valid else None,
        "success_rate_all_attempts": counts["correct"] / len(results) if results else None,
    }


def run_cases(cases: list[dict], invoke, sleep_seconds: float, output_dir: Path,
              metadata: dict, tracking=None, hosted_items=None) -> dict:
    """Execute sequentially, persist each result, and optionally track an experiment.

    Args:
        cases: Selected cases in execution order.
        invoke: Callable invoking the model using task input only.
        sleep_seconds: Full pause between successive attempts.
        output_dir: Unique run directory for metadata, JSONL and summary.
        metadata: Safe experiment metadata, without credentials.
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
    progress = tqdm(total=len(cases), desc="Evaluating offers", unit="case", dynamic_ncols=True)

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
            name="oci-offer-selection", as_type="generation", model=metadata["model"],
            input={"instructions": metadata["instructions"], "input": case["input"]},
            model_parameters={"max_output_tokens": metadata["max_output_tokens"]},
        ) if tracking else nullcontext()
        with observation as generation:
            result = evaluate_case(case, invoke)
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
                    level="ERROR" if result["status"] in {"api_error", "invalid_output"} else "DEFAULT",
                    status_message=result["status"],
                )
        return result

    try:
        if tracking:
            from agent_evals.langfuse_tracking import selection_evaluator

            experiment = tracking.run_experiment(
                name=metadata["experiment_name"], run_name=metadata["run_name"],
                data=hosted_items, task=task, evaluators=[selection_evaluator],
                max_concurrency=1,
                metadata={k: str(v) for k, v in metadata.items() if k != "instructions"},
            )
            experiment_url = experiment.experiment_url
            if len(experiment.item_results) != len(cases) or any(
                not {"valid_output", "execution_status"}.issubset({e.name for e in item.evaluations})
                or (isinstance(item.output, dict) and item.output.get("score") is not None
                    and "selection_correct" not in {e.name for e in item.evaluations})
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
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    """Run validation or the configured OCI evaluation from the command line.

    Args:
        argv: Optional CLI arguments, defaulting to the process arguments.

    Returns:
        Exit code: 0 for completion, 1 for setup/publication failure, 2 for invalid
        outputs or provider errors. Valid incorrect selections alone do not fail
        the command because no experiment acceptance threshold is defined yet.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/datasets/express-order-v1.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "rules/offer-selection.md")
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
        cases = load_cases(args.dataset, args.rules, args.split, args.limit)
        if args.dry_run:
            print(f"Validated {len(cases)} cases with six offers; no external calls made.")
            return 0
        settings = load_settings(args.env_file, args.sleep_seconds)
        rules = args.rules.read_text()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        metadata = {
            "run_id": run_id, "experiment_name": args.experiment_name,
            "run_name": f"{args.experiment_name}-{run_id}",
            "dataset_sha256": file_hash(args.dataset), "rules_sha256": file_hash(args.rules),
            "prompt_sha256": hashlib.sha256(build_instructions(rules).encode()).hexdigest(),
            "instructions": build_instructions(rules), "rules_version": "1.1", "dataset_version": "1.0",
            "model": settings.model, "region": settings.region, "split": args.split,
            "sleep_seconds": settings.sleep_seconds, "timeout_seconds": settings.timeout_seconds,
            "max_output_tokens": settings.max_output_tokens, "automatic_retries": 0,
            "sdk_versions": {n: version(n) for n in ("openai", "oci-genai-auth", "langfuse")},
            "code_sha256": {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")},
        }
        # Build the signing client before publishing any dataset records.
        with create_client(settings) as client:
            tracking, items = None, None
            if not args.no_langfuse:
                from agent_evals.langfuse_tracking import prepare_experiment

                tracking, items, name = prepare_experiment(cases, metadata["dataset_sha256"], args.split)
                metadata["dataset_name"] = name
            summary = run_cases(
                cases, lambda task: invoke_model(client, settings, rules, task),
                settings.sleep_seconds, args.output_dir / run_id, metadata, tracking, items,
            )
        print(json.dumps(summary, indent=2))
        print(f"Local results: {args.output_dir / run_id}")
        if summary["run_error"] or summary["publication"] == "failed":
            return 1
        return 2 if any(summary["status_counts"].get(s, 0) for s in ("api_error", "invalid_output")) else 0
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
