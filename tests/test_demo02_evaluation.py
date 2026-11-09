"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify Demo02 evaluation, compact progress, model metadata and Langfuse traces.
"""

from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_evals import evaluate, langfuse_tracking
from agent_evals.config import ROOT
from agent_evals.dataset import load_cases
from demo02 import evaluate as demo_cli, evaluation, model


def _response(value):
    """Build a provider envelope without accessing an external service.

    Args:
        value: Structured object or raw model text.

    Returns:
        Synthetic completed Responses envelope with usage.
    """
    return {"raw_output": value if isinstance(value, str) else json.dumps(value),
            "response_status": "completed", "response_id": "fixture-response",
            "usage": {"input": 10, "output": 5, "total": 15}}


@pytest.fixture
def setup_run(monkeypatch):
    """Prepare six real cases and external-service mocks for the shared CLI."""
    cases = load_cases(ROOT / evaluation.TASK.default_dataset,
                       ROOT / evaluation.TASK.default_rules, "development", 6, evaluation.TASK)
    originals = {c["id"]: c for c in json.loads(
        (ROOT / "data/datasets/express-order-v1.json").read_text())}
    settings = SimpleNamespace(model="configured-demo02-model", region="fixture-region",
                               sleep_seconds=3, timeout_seconds=120, max_output_tokens=2048)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(evaluate, "load_settings", Mock(return_value=settings))
    monkeypatch.setattr(evaluate, "create_client", Mock(return_value=client))
    sleep = Mock()
    monkeypatch.setattr(model.time, "sleep", sleep)
    # time is a shared Python module: this mock also detects accidental runner sleeps.
    return SimpleNamespace(cases=cases, originals=originals, settings=settings, sleep=sleep)


def _tracking(monkeypatch, fail_update=False, fail_flush=False):
    """Mock publication while exercising real task callbacks and evaluators.

    Args:
        monkeypatch: Pytest patch helper.
        fail_update: Whether observation updates fail after model execution.
        fail_flush: Whether final publication flush fails.

    Returns:
        Mock SDK client and an ordered list of generation metadata and updates.
    """
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.setenv(key, "fixture-placeholder")
    tracking = Mock()
    tracking.auth_check.return_value = True
    tracking.create_dataset_item.side_effect = lambda **data: SimpleNamespace(**data)
    generations = []

    @contextmanager
    def observation(**kwargs):
        """Record each real graph step's observation and validated outcome."""
        generation = Mock()
        if fail_update:
            generation.update.side_effect = RuntimeError("PRIVATE_MUST_NOT_LEAK")
        generations.append((kwargs, generation))
        yield generation

    def experiment(**kwargs):
        """Execute the shared SDK task boundary serially with real evaluators."""
        assert kwargs["max_concurrency"] == 1
        assert kwargs["metadata"]["model"] == "configured-demo02-model"
        items = []
        for item in kwargs["data"]:
            output = kwargs["task"](item=item)
            scores = kwargs["evaluators"][0](output=output)
            items.append(SimpleNamespace(output=output, evaluations=scores))
        tracking.experiment_items = items
        return SimpleNamespace(item_results=items, experiment_url="https://example.com/demo02")

    tracking.get_current_trace_id.return_value = "fixture-trace-id"
    tracking.start_as_current_observation.side_effect = observation
    tracking.run_experiment.side_effect = experiment
    if fail_flush:
        tracking.flush.side_effect = RuntimeError("PRIVATE_MUST_NOT_LEAK")
    monkeypatch.setattr(langfuse_tracking, "Langfuse", Mock(return_value=tracking))
    return tracking, generations


@pytest.mark.parametrize("publish", [False, True])
def test_end_to_end_runner_continues_after_failures_and_tracks_steps(
        monkeypatch, tmp_path, capsys, setup_run, publish):
    """Check scoring, KO counts, source isolation, model metadata and tracing."""
    fixture = setup_run
    cases, originals = fixture.cases, fixture.originals
    responses = []
    for index, case in enumerate(cases):
        extraction = originals[case["metadata"]["source_case_id"]]["input"]["request"]
        expected = case["expected_output"]["expected_offer_id"]
        if index == 2:
            responses.append(_response("invalid JSON"))
        elif index == 3:
            responses.append(RuntimeError("PRIVATE_MUST_NOT_LEAK"))
        elif index == 5:
            # Wrong extracted deadline, yet the expected offer is still selected.
            wrong = dict(extraction, latest_delivery_date="2099-01-01")
            responses.extend([_response(wrong), _response({"selected_offer_id": expected})])
        else:
            responses.append(_response(extraction))
            if index == 4:
                responses.append(RuntimeError("PRIVATE_MUST_NOT_LEAK"))
            else:
                selected = next(o["offer_id"] for o in case["input"]["offers"]
                                if o["offer_id"] != expected) if index == 1 else expected
                responses.append(_response({"selected_offer_id": selected}))
    invoke = Mock(side_effect=responses)
    monkeypatch.setattr(model, "invoke_model", invoke)
    tracking, generations = _tracking(monkeypatch) if publish else (None, [])
    args = ["--experiment-name", "Demo02 fixture", "--split", "development", "--limit", "6",
            "--output-dir", str(tmp_path)]
    if not publish:
        args.append("--no-langfuse")
    assert demo_cli.main(args) == 2
    captured = capsys.readouterr()
    assert "AGENT EVALS" in captured.out and "Prepare agent execution pipeline ... OK" in captured.out
    assert "OK=2" in captured.err and "KO=4" in captured.err
    before, after = captured.out.split("Completed: OK=2 KO=4", 1)
    assert all(case["id"] not in before for case in cases)
    assert all(case["id"] in after for case in cases[1:5])
    assert "[1/6]" not in captured.out
    run = next(tmp_path.iterdir())
    records = [json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()]
    summary = json.loads((run / "summary.json").read_text())
    metadata = json.loads((run / "metadata.json").read_text())
    assert [r["status"] for r in records] == [
        "correct", "incorrect", "invalid_output", "api_error", "api_error", "correct"]
    assert [r["score"] for r in records] == [1, 0, None, None, None, 1]
    assert [r["case_success"] for r in records] == [1, 0, 0, 0, 0, 1]
    assert [r["extra_scores"]["extraction_correct"] for r in records] == [1, 1, 0, None, 1, 0]
    assert summary["extra_score_summary"] == {
        "extraction_correct": {"scored_count": 5, "correct_count": 3, "accuracy": 0.6}}
    assert f"extraction_correct: 3/5 correct; failed: {cases[2]['id']}, {cases[5]['id']}" in captured.out
    assert summary["accuracy"] == 2 / 3 and summary["success_rate_all_attempts"] == 2 / 6
    assert summary["ok_count"] == 2 and summary["ko_count"] == 4
    assert [r["case_id"] for r in summary["ko_cases"]] == [c["id"] for c in cases[1:5]]
    assert summary["model"] == metadata["model"] == fixture.settings.model
    assert all(r["metadata"]["model"] == fixture.settings.model for r in records)
    assert records[0]["usage"] == {"input": 20, "output": 10, "total": 30}
    assert records[4]["extracted_request"] == originals[cases[4]["metadata"]["source_case_id"]]["input"]["request"]
    artifacts = metadata["task_artifact_sha256"]
    assert {"demo02/agent.py", "demo02/evaluation.py", "demo02/prompts/extract_request.md"} <= artifacts.keys()
    assert all(artifacts.values())
    assert invoke.call_count == 10 and fixture.sleep.call_count == 9
    assert all(c.args == (3,) for c in fixture.sleep.call_args_list)
    payloads = [call.args[-1] for call in invoke.call_args_list]
    assert [p for p in payloads if isinstance(p, str)] == [c["input"]["request"] for c in cases]
    assert "expected_offer_id" not in json.dumps(payloads) and "scenario" not in json.dumps(payloads)
    assert "PRIVATE_MUST_NOT_LEAK" not in (run / "results.jsonl").read_text() + captured.out
    if publish:
        assert summary["publication"] == "submitted_unverified"
        assert len(generations) == 10  # No third wrapper generation per case.
        assert [g[0]["name"] for g in generations].count("demo02-extract_request") == 6
        assert [g[0]["name"] for g in generations].count("demo02-select_offer") == 4
        for kwargs, generation in generations:
            assert kwargs["as_type"] == "generation" and kwargs["model"] == fixture.settings.model
            assert generation.update.call_count == 1
        assert generations[4][1].update.call_args.kwargs["level"] == "ERROR"
        assert generations[5][1].update.call_args.kwargs["status_message"] == "api_error"
        tracking.flush.assert_called_once()
        assert all(r["trace_id"] == "fixture-trace-id" for r in records)
        published = [{e.name: e.value for e in item.evaluations} for item in tracking.experiment_items]
        assert [s["case_success"] for s in published] == [1, 0, 0, 0, 0, 1]
        assert [s.get("extraction_correct") for s in published] == [1, 1, 0, None, 1, 0]
        assert "extraction_correct" not in published[3]
        assert tracking.create_dataset.call_args.kwargs["name"].startswith("demo02-express-order-development-")
    else:
        assert summary["publication"] == "disabled"


@pytest.mark.parametrize("failure", ["update", "flush"])
def test_publication_failures_preserve_valid_answers(monkeypatch, tmp_path, setup_run, failure):
    """Do not lose model outputs or claim publication success after trace errors."""
    case = setup_run.cases[0]
    expected = {"selected_offer_id": case["expected_output"]["expected_offer_id"]}
    monkeypatch.setattr(model, "invoke_model", Mock(side_effect=[
        _response(setup_run.originals[case["metadata"]["source_case_id"]]["input"]["request"]), _response(expected)]))
    _tracking(monkeypatch, fail_update=failure == "update", fail_flush=failure == "flush")
    assert demo_cli.main(["--experiment-name", "Failure check", "--split", "development",
                          "--limit", "1", "--output-dir", str(tmp_path)]) == 1
    run = next(tmp_path.iterdir())
    result = json.loads((run / "results.jsonl").read_text())
    summary = json.loads((run / "summary.json").read_text())
    assert result["output"] == expected and result["status"] == "correct"
    assert summary["publication"] == "failed" and summary["run_error"] is not None
    assert "PRIVATE_MUST_NOT_LEAK" not in json.dumps(result) + json.dumps(summary)


def test_agent_internal_failure_is_not_a_provider_or_evaluator_error(monkeypatch, setup_run):
    """Keep graph processing failures distinct from model/API failures."""
    case = setup_run.cases[0]
    monkeypatch.setattr(model, "invoke_model", Mock(return_value={}))
    invoke = evaluation.create_invoker(client=object(), settings=setup_run.settings, rules="rules")
    result = evaluate.evaluate_case(case, invoke, evaluation.TASK)
    assert result["status"] == "agent_error" and result["score"] is None
    assert result["error"]["stage"] == "extract_request"


def test_demo02_dry_run_and_required_name(capsys):
    """Validate all NL cases without credentials, model calls or uploads."""
    assert demo_cli.main(["--experiment-name", "Offline", "--split", "all", "--dry-run"]) == 0
    assert "Validated 300 cases" in capsys.readouterr().out
    with pytest.raises(SystemExit) as missing:
        demo_cli.main(["--dry-run"])
    assert missing.value.code == 2


def _v1_case() -> dict:
    """Return the first Demo02 v1 record, whose reference has only the offer ID."""
    return json.loads((ROOT / "data/datasets/demo02-express-order-v1.json").read_text())[0]


def test_validate_case_accepts_v1_and_v2_references():
    """Both dataset versions validate; v2 adds the reference extraction."""
    v2_cases = load_cases(ROOT / evaluation.TASK.default_dataset, ROOT / evaluation.TASK.default_rules,
                          "all", None, evaluation.TASK)
    assert len(v2_cases) == 300
    assert all(set(c["expected_output"]) == {"expected_offer_id", "expected_request"} for c in v2_cases)
    evaluation.validate_case(_v1_case())


@pytest.mark.parametrize("bad_request", [
    None,
    {"part_id": "PART-052", "delivery_location": "Vienna"},
    {"part_id": "PART-052", "delivery_location": "Vienna", "latest_delivery_date": "6 August 2027"},
    {"part_id": "", "delivery_location": "Vienna", "latest_delivery_date": "2027-08-06"},
    {"part_id": "PART-052", "delivery_location": "Vienna", "latest_delivery_date": "2027-08-06", "x": 1},
])
def test_validate_case_rejects_malformed_reference_requests(bad_request):
    """A v2 reference extraction must satisfy the extraction output contract."""
    case = _v1_case()
    case["expected_output"]["expected_request"] = bad_request
    with pytest.raises(ValueError):
        evaluation.validate_case(case)


def test_validate_case_rejects_unknown_reference_fields():
    """Only the v1 and v2 reference shapes are accepted."""
    case = _v1_case()
    case["expected_output"]["scenario"] = "leak"
    with pytest.raises(ValueError, match="Reference"):
        evaluation.validate_case(case)



def _result_with_extraction(status: str, extracted=None) -> dict:
    """Build a minimal result whose first step has the given status."""
    return {"steps": [{"stage": "extract_request", "status": status}], "extracted_request": extracted}


def test_score_extraction_covers_every_outcome():
    """Extraction is 1 on an exact match, 0 on a wrong or invalid step, None otherwise."""
    case = load_cases(ROOT / evaluation.TASK.default_dataset, ROOT / evaluation.TASK.default_rules,
                      "all", 1, evaluation.TASK)[0]
    reference = case["expected_output"]["expected_request"]
    score = evaluation.score_extraction
    assert score(case, _result_with_extraction("completed", dict(reference))) == {"extraction_correct": 1}
    wrong = dict(reference, delivery_location="Elsewhere")
    assert score(case, _result_with_extraction("completed", wrong)) == {"extraction_correct": 0}
    assert score(case, _result_with_extraction("invalid_output")) == {"extraction_correct": 0}
    for status in ("api_error", "internal_error"):
        assert score(case, _result_with_extraction(status)) == {"extraction_correct": None}
    assert score(case, {"steps": []}) == {"extraction_correct": None}
    assert score(_v1_case(), _result_with_extraction("completed", dict(reference))) == {
        "extraction_correct": None}
