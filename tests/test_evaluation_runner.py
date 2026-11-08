"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Verify offline OCI evaluation, pacing and Langfuse publication mapping.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from agent_evals.config import ConfigurationError, ROOT, Settings, load_settings
from agent_evals.evaluate import evaluate_case, load_cases, main, parse_selection, run_cases, summarize
from agent_evals import langfuse_tracking, oci_model

DATASET = ROOT / "data/datasets/express-order-v1.json"
RULES = ROOT / "rules/offer-selection.md"


@pytest.fixture
def cases():
    """Return three validated development cases for network-free checks."""
    return load_cases(DATASET, RULES, "development", 3)


@pytest.fixture
def settings():
    """Return synthetic settings that never reference actual credentials."""
    return Settings("us-chicago-1", "test-model", "test-project", Path("/tmp/test-oci-config"),
                    "TEST", 2, 120, 2048)


def _response(identifier, status="completed"):
    return {"raw_output": json.dumps({"selected_offer_id": identifier}),
            "response_status": status, "response_id": "response-test", "usage": {"input": 100, "output": 10}}


def test_signed_client_uses_oci_profile_and_disables_hidden_retries(monkeypatch, settings):
    """Verify OCI signing integration without reading a real private key."""
    auth = httpx.Auth()
    auth_factory = Mock(return_value=auth)
    monkeypatch.setattr(oci_model, "SingleAttemptUserPrincipalAuth", auth_factory)
    with oci_model.create_client(settings) as client:
        assert str(client.base_url).startswith("https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/")
        assert client.api_key == "not-used" and client.project == "test-project"
        assert client.max_retries == 0 and client._client.auth is auth
    auth_factory.assert_called_once_with(config_file="/tmp/test-oci-config", profile_name="TEST")


def test_model_request_contains_only_task_input_and_rules(cases, settings):
    """Ensure the reference label and scenario never enter the model request."""
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        output_text='{"selected_offer_id": "example"}', status="completed", id="response-test",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20, total_tokens=120),
    )
    result = oci_model.invoke_model(client, settings, "RULE TEXT", cases[0]["input"])
    args = client.responses.create.call_args.kwargs
    assert args["model"] == "test-model" and args["store"] is False
    assert json.loads(args["input"]) == cases[0]["input"]
    assert "RULE TEXT" in args["instructions"]
    assert "expected_offer_id" not in args["input"] and "scenario" not in args["input"]
    assert result["usage"] == {"input": 100, "output": 20, "total": 120}


def test_auth_helper_cannot_retry_a_401(monkeypatch):
    """Ensure Oracle's auth retry cannot bypass the runner's pacing."""
    requests = []

    def auth_flow(self, request):
        requests.append(request)
        response = yield request
        if response.status_code == 401:
            requests.append(request)
            yield request

    monkeypatch.setattr(oci_model.OciUserPrincipalAuth, "auth_flow", auth_flow)
    auth = object.__new__(oci_model.SingleAttemptUserPrincipalAuth)
    flow = auth.auth_flow(httpx.Request("POST", "https://example.com/responses"))
    next(flow)
    with pytest.raises(StopIteration):
        flow.send(httpx.Response(401))
    assert len(requests) == 1


@pytest.mark.parametrize("text", [
    "not JSON", '```json\n{"selected_offer_id":"A"}\n```', "[]", "null",
    '{"selected_offer_id": 5}', '{"selected_offer_id": "unknown"}',
    '{"selected_offer_id":"A","extra":1}',
    '{"selected_offer_id":"A","selected_offer_id":"B"}',
])
def test_invalid_selection_responses(text, cases):
    """Reject malformed JSON, extra/duplicate fields and unknown identifiers."""
    with pytest.raises(ValueError):
        parse_selection(text, cases[0]["input"])


def test_scoring_distinguishes_incorrect_invalid_and_provider_failure(cases):
    """Score valid wrong answers and keep malformed/provider outcomes unscored."""
    case = cases[0]
    expected = case["expected_output"]["expected_offer_id"]
    wrong = next(o["offer_id"] for o in case["input"]["offers"] if o["offer_id"] != expected)
    assert evaluate_case(case, lambda task: _response(expected))["score"] == 1
    incorrect = evaluate_case(case, lambda task: _response(wrong))
    assert incorrect["status"] == "incorrect" and incorrect["score"] == 0
    for response in [_response("unknown"), _response(expected, "incomplete")]:
        invalid = evaluate_case(case, lambda task: response)
        assert invalid["status"] == "invalid_output" and invalid["score"] is None
    invoke = Mock(side_effect=RuntimeError("FAKE_SECRET_MUST_NOT_LEAK"))
    failed = evaluate_case(case, invoke)
    assert failed["status"] == "api_error" and failed["score"] is None
    assert "FAKE_SECRET" not in json.dumps(failed)


def test_nested_dns_failure_is_reported_without_raw_error_text(cases):
    """Identify the DNS root cause hidden by the provider's connection error."""
    from openai import APIConnectionError

    dns_error = socket.gaierror(-2, "FAKE_SECRET_MUST_NOT_LEAK")
    transport_error = httpx.ConnectError("private host")
    transport_error.__cause__ = dns_error
    api_error = APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    api_error.__cause__ = transport_error
    result = evaluate_case(cases[0], Mock(side_effect=api_error))
    assert result["error"]["reason"] == "DNS resolution failed"
    assert result["error"]["cause_type"] == "gaierror"
    assert "FAKE_SECRET" not in json.dumps(result)
    assert "private host" not in json.dumps(result)


def test_sequential_pause_after_success_and_failure_and_persistence(monkeypatch, tmp_path, cases):
    """Check full inter-call pauses after failures and durable case outputs."""
    events = []
    monkeypatch.setattr("agent_evals.evaluate.time.sleep", lambda seconds: events.append(("sleep", seconds)))
    responses = iter([_response(cases[0]["expected_output"]["expected_offer_id"]),
                      RuntimeError("private error"), _response("unknown")])

    def invoke(task):
        events.append(("call", task))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    output = tmp_path / "run"
    summary = run_cases(cases, invoke, 3.5, output, {"run_id": "test"})
    assert [e[0] for e in events] == ["call", "sleep", "call", "sleep", "call"]
    assert [e[1] for e in events if e[0] == "sleep"] == [3.5, 3.5]
    assert summary["selection_accuracy"] == 1 and summary["success_rate_all_attempts"] == 1 / 3
    assert summary["valid_scored_count"] == 1 and summary["attempted_count"] == 3
    stored = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    assert [r["status"] for r in stored] == ["correct", "api_error", "invalid_output"]
    assert json.loads((output / "summary.json").read_text()) == summary


def test_all_failures_have_no_valid_accuracy():
    """Report null accuracy when no model output can be scored."""
    summary = summarize([{"status": "api_error"}, {"status": "invalid_output"}], 3)
    assert summary["selection_accuracy"] is None
    assert summary["success_rate_all_attempts"] == 0 and summary["unattempted_count"] == 1


@pytest.mark.parametrize("arguments", [[], ["--experiment-name", ""], ["--experiment-name", "   "]])
def test_experiment_name_is_required_before_execution(arguments):
    """Reject missing or blank experiment names even during offline validation."""
    with pytest.raises(SystemExit) as error:
        main(arguments + ["--dry-run"])
    assert error.value.code == 2


def test_run_name_alias_remains_supported():
    """Keep existing commands usable while requiring an explicit name."""
    assert main(["--run-name", "Compatibility check", "--dry-run", "--limit", "1"]) == 0


def test_case_selection_dry_run_and_provenance(tmp_path, capsys):
    """Check split counts, offline execution and mismatched rule rejection."""
    assert len(load_cases(DATASET, RULES, "evaluation", None)) == 80
    assert len(load_cases(DATASET, RULES, "all", None)) == 100
    assert main(["--experiment-name", "validation", "--dry-run", "--split", "all"]) == 0
    assert "100 cases" in capsys.readouterr().out
    with pytest.raises(ValueError, match="positive"):
        load_cases(DATASET, RULES, "evaluation", 0)
    rules = tmp_path / "rules.md"
    rules.write_text("different rules")
    with pytest.raises(ValueError, match="Rule contents"):
        load_cases(DATASET, rules, "all", None)


def test_settings_load_dotenv_and_preserve_overrides(monkeypatch, tmp_path):
    """Load the actual variable names while keeping secrets out of settings."""
    for key in ["OCI_REGION", "OCI_MODEL", "OCI_PROJECT_ID", "EVAL_SLEEP_SECONDS",
                "OCI_TIMEOUT_SECONDS", "OCI_MAX_OUTPUT_TOKENS"]:
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("OCI_REGION=us-chicago-1\nOCI_MODEL=test\nOCI_PROJECT_ID=project\nEVAL_SLEEP_SECONDS=4\n")
    monkeypatch.setenv("OCI_MODEL", "override")
    settings = load_settings(env)
    assert settings.model == "override" and settings.sleep_seconds == 4
    assert load_settings(env, 0).sleep_seconds == 0
    for bad in [-1, float("nan"), float("inf")]:
        with pytest.raises(ConfigurationError):
            load_settings(env, bad)
    monkeypatch.delenv("OCI_PROJECT_ID")
    with pytest.raises(ConfigurationError, match="OCI_PROJECT_ID"):
        load_settings(tmp_path / "absent.env")


def test_langfuse_upload_ids_and_evaluations(monkeypatch, cases):
    """Check deterministic uploads and separate scores for invalid outcomes."""
    for key in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.setenv(key, "test-placeholder")
    client = Mock()
    client.auth_check.return_value = True
    monkeypatch.setattr(langfuse_tracking, "Langfuse", Mock(return_value=client))
    langfuse_tracking.prepare_experiment(cases, "a" * 64, "development")
    first_ids = [c.kwargs["id"] for c in client.create_dataset_item.call_args_list]
    assert len(first_ids) == len(set(first_ids)) == 3
    assert client.create_dataset_item.call_args_list[0].kwargs["input"] == cases[0]["input"]
    assert client.create_dataset_item.call_args_list[0].kwargs["expected_output"] == cases[0]["expected_output"]
    client.create_dataset_item.reset_mock()
    langfuse_tracking.prepare_experiment(cases, "a" * 64, "development")
    assert first_ids == [c.kwargs["id"] for c in client.create_dataset_item.call_args_list]
    expected = cases[0]["expected_output"]
    output = {"status": "correct", "selected_offer_id": expected["expected_offer_id"]}
    assert {e.name: e.value for e in langfuse_tracking.selection_evaluator(output=output, expected_output=expected)}["selection_correct"] == 1
    output["status"] = "invalid_output"
    assert "selection_correct" not in {e.name for e in langfuse_tracking.selection_evaluator(output=output, expected_output=expected)}


def test_langfuse_experiment_is_sequential_and_flush_failure_is_reported(monkeypatch, tmp_path, cases):
    """Preserve local results if final Langfuse publication fails."""
    case = cases[0]
    client = Mock()
    generation = Mock()

    @contextmanager
    def observation(**kwargs):
        yield generation

    def experiment(**kwargs):
        assert kwargs["name"] == "My named experiment"
        assert kwargs["run_name"] == "test"
        assert kwargs["max_concurrency"] == 1
        result = kwargs["task"](item=SimpleNamespace(metadata={"case_id": case["id"]}))
        evaluations = kwargs["evaluators"][0](output=result, expected_output=case["expected_output"])
        return SimpleNamespace(experiment_url="https://example.com/experiment",
                               item_results=[SimpleNamespace(output=result, evaluations=evaluations)])

    client.start_as_current_observation.side_effect = observation
    client.run_experiment.side_effect = experiment
    client.flush.side_effect = RuntimeError("private error")
    metadata = {"run_id": "test", "run_name": "test", "experiment_name": "My named experiment",
                "model": "test-model", "instructions": "rules",
                "max_output_tokens": 2048, "dataset_name": "test-dataset"}
    summary = run_cases([case], lambda task: _response(case["expected_output"]["expected_offer_id"]),
                        0, tmp_path / "run", metadata, client, [object()])
    assert summary["publication"] == "failed" and summary["run_error"] == "LangfuseFlushError"
    assert summary["attempted_count"] == 1 and (tmp_path / "run/results.jsonl").exists()
    assert "private error" not in json.dumps(summary)
