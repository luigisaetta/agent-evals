"""
Author: L. Saetta
Date last modified: 2026-11-10
License: MIT
Description: Verify shared model interfaces using real adapters and mocked OCI transport.
"""

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import oci
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from requests.exceptions import SSLError, Timeout

from agent_evals import evaluate, langchain_model, langfuse_tracking, oci_model
from agent_evals.config import ROOT, ConfigurationError, Settings, load_settings
from agent_evals.dataset import load_cases
from agent_evals.errors import describe_api_error
from demo01.evaluation import TASK as DEMO01
from demo02.agent import AgentExecutionError, OfferSelectionAgent
from demo02.evaluation import TASK as DEMO02
from demo02.model import PacedResponses


@pytest.fixture
def settings():
    """Return native-chat settings without live credentials."""
    return Settings(
        "us-chicago-1",
        "cohere.command-a-03-2025",
        "",
        Path("/tmp/test-config"),
        "TEST",
        0,
        30,
        256,
        "langchain_oci",
        "test-compartment",
    )


@pytest.fixture
def native_client(monkeypatch):
    """Mock only the OCI SDK, leaving LangChain request/response mapping real."""
    config = {"region": "us-chicago-1"}
    monkeypatch.setattr(oci.config, "from_file", Mock(return_value=config))
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(
        oci.generative_ai_inference, "GenerativeAiInferenceClient", factory
    )
    return client, factory


def native_response(text, finish="COMPLETE", usage=True):
    """Build a Cohere-shaped response for the real LangChain provider.

    Args:
        text: Raw generated text.
        finish: Native Cohere finish reason.
        usage: Whether native usage information is available.

    Returns:
        An OCI-shaped response with synthetic safe metadata.
    """
    tokens = (
        SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        if usage
        else None
    )
    return SimpleNamespace(
        data=SimpleNamespace(
            model_id="cohere.command-a-03-2025",
            model_version="test",
            chat_response=SimpleNamespace(
                text=text, finish_reason=finish, usage=tokens
            ),
        ),
        request_id="oci-request-id",
        headers={"content-length": "100"},
    )


def test_settings_default_and_backend_requirements(monkeypatch, tmp_path):
    """Select the interface explicitly and require only its own OCI resource."""
    for key in (
        "OCI_MODEL_INTERFACE",
        "OCI_MODEL_NAME",
        "OCI_PROJECT_ID",
        "OCI_COMPARTMENT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OCI_REGION", "us-chicago-1")
    monkeypatch.setenv("OCI_MODEL", "openai.gpt-oss-20b")
    monkeypatch.setenv("OCI_PROJECT_ID", "project")
    env = tmp_path / "absent.env"
    assert load_settings(env).model_interface == "responses"
    monkeypatch.setenv("OCI_MODEL_INTERFACE", "langchain_oci")
    monkeypatch.delenv("OCI_PROJECT_ID")
    with pytest.raises(ConfigurationError, match="OCI_COMPARTMENT_ID"):
        load_settings(env)
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "compartment")
    assert load_settings(env).project_id == ""
    monkeypatch.setenv("OCI_MODEL_INTERFACE", "auto")
    with pytest.raises(ConfigurationError, match="OCI_MODEL_INTERFACE"):
        load_settings(env)


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"model_interface": "responses", "project_id": "project"}, "does not support"),
        ({"model": "cohere.embed-v4.0"}, "registry"),
        ({"model": "cohere.command-a-reasoning"}, "registry"),
        ({"model_interface": "auto"}, "OCI_MODEL_INTERFACE"),
        ({"compartment_id": ""}, "OCI_COMPARTMENT_ID"),
        ({"model": "ocid1.generativeaiendpoint.oc1.test"}, "OCI_MODEL_NAME"),
        ({"model_name": "cohere.command-a-03-2025"}, "only allowed"),
    ],
)
def test_incompatible_configuration_never_initializes_client(
    settings, native_client, changes, error
):
    """Fail closed before reading credentials or making service calls."""
    with pytest.raises(ConfigurationError, match=error):
        oci_model.create_client(replace(settings, **changes))
    oci.config.from_file.assert_not_called()
    native_client[1].assert_not_called()


def test_dedicated_endpoint_requires_verified_underlying_model(settings, native_client):
    """Use the explicit model identity to select a dedicated endpoint's provider."""
    dedicated = replace(
        settings, model="ocid1.generativeaiendpoint.oc1.test", model_name=settings.model
    )
    with oci_model.create_client(dedicated) as adapter:
        assert adapter.model.model_id == dedicated.model
        assert adapter.model.provider == "cohere"


def test_native_adapter_uses_real_provider_and_preserves_contract(
    settings, native_client
):
    """Check signing settings, native parameters, prompt isolation, usage and closure."""
    client, factory = native_client
    client.chat.return_value = native_response('{"selected_offer_id":"A"}')
    payload = {"request": "Only task input", "offers": [{"offer_id": "A"}]}
    with oci_model.create_client(settings) as adapter:
        result = oci_model.invoke_model(
            adapter, settings, "Exact instructions", payload
        )
    oci.config.from_file.assert_called_once_with("/tmp/test-config", "TEST")
    kwargs = factory.call_args.kwargs
    assert kwargs["timeout"] == 30
    assert isinstance(kwargs["retry_strategy"], oci.retry.NoneRetryStrategy)
    assert kwargs["service_endpoint"].endswith("us-chicago-1.oci.oraclecloud.com")
    request = client.chat.call_args.args[0]
    assert request.compartment_id == settings.compartment_id
    assert request.serving_mode.model_id == settings.model
    assert request.chat_request.max_tokens == 256
    assert request.chat_request.message == json.dumps(payload, ensure_ascii=False)
    assert request.chat_request.chat_history[0].message == "Exact instructions"
    assert request.chat_request.api_format == "COHERE"
    assert isinstance(
        client.chat.call_args.kwargs["retry_strategy"], oci.retry.NoneRetryStrategy
    )
    assert result == {
        "raw_output": '{"selected_offer_id":"A"}',
        "response_status": "completed",
        "response_id": "oci-request-id",
        "usage": {"input": 10, "output": 5, "total": 15},
    }
    client.base_client.session.close.assert_called_once()


@pytest.mark.parametrize(
    "reason, status",
    [
        ("COMPLETE", "completed"),
        ("stop", "completed"),
        ("MAX_TOKENS", "incomplete"),
        ("length", "incomplete"),
        ("ERROR_TOXIC", "blocked"),
        ("TOOL_CALL", "failed"),
        (None, "unknown"),
        ("UNKNOWN_ENUM_VALUE", "unknown"),
    ],
)
def test_finish_reasons_are_not_blindly_treated_as_success(reason, status):
    """Reject truncated or unknown finishes even if the text is valid JSON."""
    message = AIMessage(
        content='{"selected_offer_id":"A"}', response_metadata={"finish_reason": reason}
    )
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    normalized = langchain_model.normalize_response(result)
    assert normalized["response_status"] == status
    assert normalized["response_id"] is None and normalized["usage"] == {}


def test_missing_usage_is_not_reported_as_zero(settings, native_client):
    """Keep absent token counts absent through the real LangChain conversion."""
    native_client[0].chat.return_value = native_response("{}", usage=False)
    with oci_model.create_client(settings) as client:
        assert client.invoke("instructions", {})["usage"] == {}


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_provider_errors_are_never_repaired_or_retried(
    settings, native_client, monkeypatch, status
):
    """A parameter or service error must cause exactly one SDK call and close."""
    client = native_client[0]
    repair = Mock(return_value=True)
    monkeypatch.setattr(
        "langchain_oci.chat_models.oci_generative_ai.adjust_request_for_param_error",
        repair,
    )
    client.chat.side_effect = oci.exceptions.ServiceError(
        status,
        "unsupported_value",
        {},
        "PRIVATE_PROVIDER_MESSAGE",
    )
    with pytest.raises(oci.exceptions.ServiceError):
        with oci_model.create_client(settings) as adapter:
            adapter.invoke("instructions", {})
    client.chat.assert_called_once()
    repair.assert_not_called()
    client.base_client.session.close.assert_called_once()
    safe = describe_api_error(client.chat.side_effect)
    assert safe["http_status"] == status
    assert "PRIVATE_PROVIDER_MESSAGE" not in json.dumps(safe)


@pytest.mark.parametrize(
    "model_id",
    [
        "meta.llama-3.3-70b-instruct",
        "meta.llama-4-scout-17b-16e-instruct",
    ],
)
def test_meta_registry_entry_maps_to_native_generic_chat(
    settings, native_client, model_id
):
    """Verify the registered Meta model with the real generic request/response mapping."""
    settings = replace(settings, model=model_id)
    message = SimpleNamespace(content=[SimpleNamespace(text="{}")], tool_calls=None)
    native_client[0].chat.return_value = SimpleNamespace(
        data=SimpleNamespace(
            model_id=settings.model,
            model_version="test",
            chat_response=SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")],
                time_created="test",
            ),
        ),
        request_id="meta-request",
        headers={"content-length": "2"},
    )
    with oci_model.create_client(settings) as adapter:
        result = adapter.invoke("instructions", {"request": "task data"})
    request = native_client[0].chat.call_args.args[0]
    assert request.serving_mode.model_id == model_id
    assert request.chat_request.api_format == "GENERIC"
    assert request.chat_request.messages[0].role == "SYSTEM"
    assert request.chat_request.max_tokens == settings.max_output_tokens
    assert (
        result["response_status"] == "completed"
        and result["response_id"] == "meta-request"
    )


def test_adapter_initialization_failure_closes_owned_session(
    settings, native_client, monkeypatch
):
    """Release the SDK session when LangChain rejects its initialization settings."""
    monkeypatch.setattr(
        langchain_model,
        "SingleAttemptChatOCIGenAI",
        Mock(side_effect=ValueError("test")),
    )
    with pytest.raises(ValueError):
        oci_model.create_client(settings)
    native_client[0].base_client.session.close.assert_called_once()


@pytest.mark.parametrize(
    "error, reason",
    [
        (Timeout("private"), "Request timed out"),
        (SSLError("private"), "TLS certificate or handshake failed"),
    ],
)
def test_native_transport_errors_are_safe(error, reason):
    """Classify requests-based OCI failures without printing provider text."""
    assert describe_api_error(error)["reason"] == reason


@pytest.mark.parametrize("finish", ["COMPLETE", "MAX_TOKENS"])
def test_demo02_graph_uses_native_backend_and_stops_after_bad_extraction(
    settings,
    native_client,
    monkeypatch,
    finish,
):
    """Run the unchanged graph through real LangChain conversion and mocked OCI."""
    case = load_cases(
        ROOT / DEMO02.default_dataset,
        ROOT / DEMO02.default_rules,
        "development",
        1,
        DEMO02,
    )[0]
    expected = case["expected_output"]
    client = native_client[0]
    client.chat.side_effect = [
        native_response(json.dumps(expected["expected_request"]), finish),
        native_response(
            json.dumps({"selected_offer_id": expected["expected_offer_id"]})
        ),
    ]
    sleep = Mock()
    monkeypatch.setattr("demo02.model.time.sleep", sleep)
    with oci_model.create_client(settings) as adapter:
        agent = OfferSelectionAgent(
            PacedResponses(adapter, settings), "selection rules"
        )
        if finish == "COMPLETE":
            assert agent.invoke(**case["input"]) == {
                "selected_offer_id": expected["expected_offer_id"]
            }
            assert client.chat.call_count == 2
            sleep.assert_called_once_with(0)
            second = json.loads(
                client.chat.call_args_list[1].args[0].chat_request.message
            )
            assert second == {
                "request": expected["expected_request"],
                "offers": case["input"]["offers"],
            }
        else:
            with pytest.raises(AgentExecutionError) as failure:
                agent.invoke(**case["input"])
            assert failure.value.error["kind"] == "invalid_output"
            client.chat.assert_called_once()
            sleep.assert_not_called()


@pytest.mark.parametrize("task", [DEMO01, DEMO02], ids=["demo01", "demo02"])
def test_both_demo_runners_record_backend_and_generation_metadata(
    settings,
    native_client,
    monkeypatch,
    tmp_path,
    task,
):
    """Exercise native model dispatch, evaluation and publication mapping together."""
    case = load_cases(
        ROOT / task.default_dataset, ROOT / task.default_rules, "development", 1, task
    )[0]
    outputs = [{"selected_offer_id": case["expected_output"]["expected_offer_id"]}]
    if task is DEMO02:
        outputs.insert(0, case["expected_output"]["expected_request"])
    native_client[0].chat.side_effect = [
        native_response(json.dumps(value)) for value in outputs
    ]
    monkeypatch.setattr(evaluate, "load_settings", Mock(return_value=settings))
    tracking = Mock()
    generations = []

    @contextmanager
    def observe(**kwargs):
        generations.append(kwargs)
        yield Mock()

    tracking.start_as_current_observation.side_effect = observe
    tracking.get_current_trace_id.return_value = "synthetic-trace"
    hosted = SimpleNamespace(metadata={"case_id": case["id"]})

    def run_experiment(**kwargs):
        output = kwargs["task"](item=hosted)
        assert output["status"] == "correct"
        names = {"valid_output", "execution_status", "case_success", task.metric_name}
        item = SimpleNamespace(
            output=output, evaluations=[SimpleNamespace(name=n) for n in names]
        )
        return SimpleNamespace(
            experiment_url="https://example.com/test", item_results=[item]
        )

    tracking.run_experiment.side_effect = run_experiment
    monkeypatch.setattr(
        langfuse_tracking,
        "prepare_experiment",
        Mock(return_value=(tracking, [hosted], "synthetic-dataset")),
    )
    module = "demo01.evaluation" if task is DEMO01 else "demo02.evaluation"
    assert (
        evaluate.main(
            [
                "--task",
                module,
                "--split",
                "development",
                "--limit",
                "1",
                "--experiment-name",
                "native-test",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    run = next(tmp_path.iterdir())
    for name in ("metadata.json", "summary.json", "results.jsonl"):
        value = json.loads((run / name).read_text())
        metadata = value["metadata"] if name == "results.jsonl" else value
        assert metadata["model_interface"] == "langchain_oci"
    assert len(generations) == len(outputs)
    assert all(g["metadata"]["model_interface"] == "langchain_oci" for g in generations)
    metadata = json.loads((run / "metadata.json").read_text())
    assert metadata["sdk_versions"]["langchain-oci"] == "0.4.0"
    assert (
        tracking.run_experiment.call_args.kwargs["metadata"]["model_interface"]
        == "langchain_oci"
    )


def test_invalid_backend_fails_before_any_publication(
    settings, native_client, monkeypatch, tmp_path
):
    """Reject unsupported model/interface combinations before Langfuse setup."""
    monkeypatch.setattr(
        evaluate,
        "load_settings",
        Mock(
            return_value=replace(
                settings,
                model_interface="responses",
                project_id="project",
            )
        ),
    )
    publish = Mock()
    monkeypatch.setattr(langfuse_tracking, "prepare_experiment", publish)
    assert (
        evaluate.main(
            [
                "--task",
                "demo02.evaluation",
                "--limit",
                "1",
                "--experiment-name",
                "invalid",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    publish.assert_not_called()
    native_client[1].assert_not_called()
