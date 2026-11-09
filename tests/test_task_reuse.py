"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify the shared evaluation pipeline with a non-procurement task.
"""

from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_evals import evaluate, langfuse_tracking
from agent_evals.dataset import load_cases
from agent_evals.task import EvaluationTask, load_task


def validate_priority_case(case: dict) -> None:
    """Validate text-classification fixtures without offer fields.

    Args:
        case: Text input and a stored priority reference.

    Raises:
        ValueError: If text or reference label is invalid.
    """
    if not isinstance(case["input"], str) or not case["input"].strip():
        raise ValueError("Input must be non-empty text")
    if case["expected_output"].get("label") not in {"urgent", "routine"}:
        raise ValueError("Reference must be a known priority")


def priority_instructions(rules: str) -> str:
    """Build a prompt for the independent classification task.

    Args:
        rules: Natural-language priority rules.

    Returns:
        Final classification instructions.
    """
    return 'Classify the text. Return JSON with a label of urgent or routine.\n' + rules


def parse_priority(raw_output: str, task_input: str) -> dict:
    """Parse priority labels without knowing any supplier or part fields.

    Args:
        raw_output: Model response text.
        task_input: Original text, unused by this output contract.

    Returns:
        Validated label object.

    Raises:
        ValueError: If the response is not a supported label object.
    """
    result = json.loads(raw_output)
    if (not isinstance(result, dict) or set(result) != {"label"}
            or result["label"] not in {"urgent", "routine"}):
        raise ValueError("Invalid priority output")
    return result


def score_priority(output: dict, expected_output: dict) -> int:
    """Compare the parsed and reference label objects.

    Args:
        output: Parsed label.
        expected_output: Expected label.

    Returns:
        Binary classification correctness.
    """
    return int(output == expected_output)


@pytest.fixture
def priority_task(tmp_path):
    """Create a different task, three-case dataset, rule file and manifest."""
    dataset = tmp_path / "priorities.json"
    rules = tmp_path / "priority.txt"
    rules.write_text("Production outages are urgent; reports are routine.")
    cases = [
        {"id": "P1", "input": "Production stopped", "expected_output": {"label": "urgent"}},
        {"id": "P2", "input": "Monthly report", "expected_output": {"label": "routine"}},
        {"id": "P3", "input": "Line outage", "expected_output": {"label": "urgent"}},
    ]
    for case in cases:
        case["metadata"] = {"split": "evaluation", "rules_version": "9", "dataset_version": "2.3"}
    dataset.write_text(json.dumps(cases))
    manifest = {
        "dataset_version": "2.3", "rules_version": "9",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "source_sha256": {"rules/priority.txt": hashlib.sha256(rules.read_bytes()).hexdigest()},
    }
    dataset.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    return EvaluationTask(
        name="priority", title="Message Priority", default_dataset=dataset, default_rules=rules,
        rules_manifest_key="rules/priority.txt", dataset_namespace="priority-v2",
        metric_name="priority_correct", validate_case=validate_priority_case,
        build_instructions=priority_instructions, parse_output=parse_priority,
        score_output=score_priority, version="3.0",
    )


def _response(label):
    """Build a synthetic Responses result for a classification label.

    Args:
        label: Value to include in the raw output object.

    Returns:
        Provider-independent result envelope.
    """
    return {"raw_output": json.dumps({"label": label}), "response_status": "completed",
            "response_id": "fixture-response", "usage": {}}


def test_other_task_uses_same_loader_engine_pacing_and_result_files(priority_task, tmp_path, monkeypatch):
    """Run a three-case text task through the unchanged shared engine."""
    task = priority_task
    cases = load_cases(task.default_dataset, task.default_rules, "all", None, task)
    invoke = Mock(side_effect=[_response("urgent"), _response("urgent"), _response("unknown")])
    sleep = Mock()
    monkeypatch.setattr(evaluate.time, "sleep", sleep)
    summary = evaluate.run_cases(cases, invoke, 2, tmp_path / "run", {"run_id": "priority"}, task)
    assert summary["accuracy"] == 0.5 and summary["success_rate_all_attempts"] == 1 / 3
    assert summary["status_counts"] == {"correct": 1, "incorrect": 1, "invalid_output": 1}
    assert summary["metric_name"] == "priority_correct" and summary["task_version"] == "3.0"
    assert sleep.call_count == 2
    assert [c.args[0] for c in invoke.call_args_list] == [c["input"] for c in cases]
    records = [json.loads(line) for line in (tmp_path / "run/results.jsonl").read_text().splitlines()]
    assert records[0]["output"] == {"label": "urgent"}
    assert records[1]["expected_output"] == {"label": "routine"}
    assert "selected_offer_id" not in records[0] and "expected_offer_id" not in records[0]
    assert summary["result_schema_version"] == 2


@pytest.mark.parametrize("scorer", [Mock(side_effect=RuntimeError("private error")), lambda a, b: 0.5])
def test_scorer_failure_is_not_a_model_or_api_failure(priority_task, scorer):
    """Separate adapter bugs or unsupported fractional scores from model failures."""
    task = replace(priority_task, score_output=scorer)
    case = load_cases(task.default_dataset, task.default_rules, "all", 1, task)[0]
    result = evaluate.evaluate_case(case, lambda data: _response("urgent"), task)
    assert result["status"] == "evaluator_error" and result["score"] is None
    assert result["output_valid"] and "private error" not in json.dumps(result)
    scores = langfuse_tracking.make_evaluator(task.metric_name)(output=result)
    assert {s.name: s.value for s in scores} == {
        "valid_output": 1, "execution_status": "evaluator_error", "case_success": 0,
    }


@pytest.mark.parametrize("with_langfuse", [False, True])
def test_custom_task_cli_provider_and_langfuse_are_domain_independent(priority_task, monkeypatch, tmp_path, with_langfuse):
    """Select another module via CLI and verify prompt, versions and hosted scores."""
    task = priority_task
    module = ModuleType("fixture_priority_task")
    module.TASK = task
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert load_task(module.__name__) is task
    settings = SimpleNamespace(model="fixture-model", region="fixture-region", sleep_seconds=0,
                               timeout_seconds=10, max_output_tokens=100)
    monkeypatch.setattr(evaluate, "load_settings", Mock(return_value=settings))
    monkeypatch.setattr(evaluate, "create_client", Mock(return_value=nullcontext(object())))
    labels = iter(["urgent", "routine", "urgent"])
    invocations = []

    def invoke(client, settings, instructions, task_input):
        """Record only the prompt and text sent through the provider boundary.

        Args:
            client: Mock provider client.
            settings: Mock provider settings.
            instructions: Task-specific final prompt.
            task_input: Text input without its reference answer.

        Returns:
            Synthetic provider response.
        """
        invocations.append((instructions, task_input))
        return _response(next(labels))

    monkeypatch.setattr(evaluate, "invoke_model", invoke)
    hosted = Mock()
    if with_langfuse:
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
            monkeypatch.setenv(key, "fixture-value")
        hosted.auth_check.return_value = True
        hosted.create_dataset_item.side_effect = lambda **item: SimpleNamespace(**item)
        hosted.start_as_current_observation.side_effect = lambda **kwargs: nullcontext(Mock())
        monkeypatch.setattr(langfuse_tracking, "Langfuse", Mock(return_value=hosted))

        def experiment(**kwargs):
            """Exercise the real runner task and evaluator using mock SDK items.

            Args:
                **kwargs: Actual arguments supplied by the shared runner.

            Returns:
                SDK-compatible experiment result.
            """
            assert kwargs["max_concurrency"] == 1 and kwargs["name"] == "Priority baseline"
            items = []
            for item in kwargs["data"]:
                result = kwargs["task"](item=item)
                scores = kwargs["evaluators"][0](output=result, expected_output=item.expected_output)
                assert {s.name: s.value for s in scores}["priority_correct"] == 1
                items.append(SimpleNamespace(output=result, evaluations=scores))
            return SimpleNamespace(item_results=items, experiment_url="https://example.com/priority")

        hosted.run_experiment.side_effect = experiment

    arguments = ["--task", module.__name__, "--experiment-name", "Priority baseline",
                 "--output-dir", str(tmp_path / "results")]
    if not with_langfuse:
        arguments.append("--no-langfuse")
    assert evaluate.main(arguments) == 0
    assert len(invocations) == 3
    assert all(instructions.startswith("Classify the text.") and isinstance(data, str)
               for instructions, data in invocations)
    run_dir = next((tmp_path / "results").iterdir())
    metadata = json.loads((run_dir / "metadata.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    assert metadata["rules_version"] == "9" and metadata["dataset_version"] == "2.3"
    assert metadata["task_name"] == "priority" and metadata["metric_name"] == "priority_correct"
    assert all(metadata["task_source_sha256"].values())
    assert summary["accuracy"] == 1 and summary["task_name"] == "priority"
    if with_langfuse:
        name = hosted.create_dataset.call_args.kwargs["name"]
        assert name.startswith("priority-v2-evaluation-")
        assert hosted.create_dataset.call_args.kwargs["metadata"]["rules_version"] == "9"
        hosted.flush.assert_called_once()


def test_invalid_task_module_is_rejected(monkeypatch):
    """Reject unknown modules and modules without the explicit task contract."""
    with pytest.raises(ValueError, match="Cannot import"):
        load_task("no_such_evaluation_task")
    module = ModuleType("invalid_task_fixture")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ValueError, match="must export TASK"):
        load_task(module.__name__)


def _length_score(case: dict, result: dict) -> dict:
    """Score an illustrative intermediate property; not applicable to invalid outputs."""
    if not result["output_valid"]:
        return {"short_input": None}
    return {"short_input": int(len(case["input"]) < 15)}


def test_extra_scores_are_stored_summarized_and_published(priority_task, tmp_path):
    """Extra scores sit beside the status, are aggregated and skip non-applicable cases."""
    task = replace(priority_task, extra_scores=_length_score)
    cases = load_cases(task.default_dataset, task.default_rules, "all", None, task)
    invoke = Mock(side_effect=[_response("urgent"), _response("urgent"), _response("unknown")])
    summary = evaluate.run_cases(cases, invoke, 0, tmp_path / "run", {"run_id": "extra"}, task)
    records = [json.loads(line) for line in (tmp_path / "run/results.jsonl").read_text().splitlines()]
    assert [r["status"] for r in records] == ["correct", "incorrect", "invalid_output"]
    assert [r["case_success"] for r in records] == [1, 0, 0]
    assert [r["extra_scores"] for r in records] == [
        {"short_input": 0}, {"short_input": 1}, {"short_input": None}]
    assert summary["extra_score_summary"] == {
        "short_input": {"scored_count": 2, "correct_count": 1, "accuracy": 0.5}}
    published = [{s.name: s.value for s in langfuse_tracking.make_evaluator(task.metric_name)(output=r)}
                 for r in records]
    assert [p["case_success"] for p in published] == [1, 0, 0]
    assert [p.get("short_input") for p in published] == [0, 1, None]
    assert "short_input" not in published[2]


@pytest.mark.parametrize("callback", [
    Mock(side_effect=RuntimeError("private error")),
    lambda case, result: {"short_input": 0.5},
    lambda case, result: {"case_success": 1},
    lambda case, result: {"priority_correct": 1},
    lambda case, result: ["not", "a", "dict"],
])
def test_invalid_extra_scores_never_change_the_status(priority_task, callback):
    """A failing or invalid extra-score callback is recorded but leaves the result intact."""
    task = replace(priority_task, extra_scores=callback)
    case = load_cases(task.default_dataset, task.default_rules, "all", 1, task)[0]
    result = evaluate.evaluate_case(case, lambda data: _response("urgent"), task)
    assert result["status"] == "correct" and result["score"] == 1 and result["case_success"] == 1
    assert result["extra_scores"] == {} and "type" in result["extra_score_error"]
    assert "private error" not in json.dumps(result)


def test_shared_score_names_are_reserved(priority_task, monkeypatch):
    """A task metric may not reuse a shared score name, including case_success."""
    module = ModuleType("fixture_case_success_task")
    module.TASK = replace(priority_task, metric_name="case_success")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(ValueError, match="conflicts"):
        load_task(module.__name__)
