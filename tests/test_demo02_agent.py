"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify the real two-node LangGraph using mocked OCI Responses calls.
"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_evals.config import ROOT
from agent_evals.tasks.offer_selection import build_instructions
from demo02.agent import AgentExecutionError, OfferSelectionAgent
from demo02 import model, run_agent


@pytest.fixture
def case_pair():
    """Return matching natural-language and structured source cases."""
    derived = json.loads((ROOT / "data/datasets/demo02-express-order-v1.json").read_text())[0]
    source = next(case for case in json.loads((ROOT / "data/datasets/express-order-v1.json").read_text())
                  if case["id"] == derived["id"])
    return derived, source


def _response(value, status="completed"):
    """Create a shared transport envelope for a synthetic model response.

    Args:
        value: JSON-serializable object or raw response text.
        status: Model completion status.

    Returns:
        Responses result used by both graph nodes.
    """
    return {"raw_output": value if isinstance(value, str) else json.dumps(value),
            "response_status": status, "response_id": "fixture-response",
            "usage": {"input": 100, "output": 20, "total": 120}}


def _agent(responses):
    """Build the actual compiled agent with a scripted model callable.

    Args:
        responses: Responses or exceptions returned in call order.

    Returns:
        Compiled agent wrapper and its model mock.
    """
    call = Mock(side_effect=responses)
    return OfferSelectionAgent(call, (ROOT / "rules/offer-selection.md").read_text()), call


def test_two_model_calls_use_real_graph_and_reuse_demo01(case_pair):
    """Check graph stages, isolated extraction input, unchanged offers and final ID."""
    case, source = case_pair
    expected = {"selected_offer_id": case["expected_output"]["expected_offer_id"]}
    agent, call = _agent([_response(source["input"]["request"]), _response(expected)])
    offers = deepcopy(case["input"]["offers"])
    result = agent.run(case["input"]["request"], offers)
    assert {"extract_request", "select_offer"}.issubset(agent.graph.get_graph().nodes)
    assert result["output"] == expected and result["extracted_request"] == source["input"]["request"]
    assert [step["stage"] for step in result["steps"]] == ["extract_request", "select_offer"]
    assert all(step["status"] == "completed" for step in result["steps"])
    assert call.call_count == 2
    first, second = call.call_args_list
    assert first.args[1] == case["input"]["request"] and isinstance(first.args[1], str)
    assert second.args[1] == source["input"]
    assert second.args[0] == build_instructions((ROOT / "rules/offer-selection.md").read_text())
    assert offers == case["input"]["offers"]
    for invocation in call.call_args_list:
        assert "expected_offer_id" not in json.dumps(invocation.args)
        assert "expected_output" not in json.dumps(invocation.args)
        assert "scenario" not in json.dumps(invocation.args)


@pytest.mark.parametrize("bad", [
    "not JSON", "[]", '{"part_id":"PART-001"}',
    '{"part_id":"PART-001","part_id":"PART-002","delivery_location":"Rome","latest_delivery_date":"2027-03-01"}',
    {"part_id": None, "delivery_location": "Rome", "latest_delivery_date": "2027-03-01"},
    {"part_id": "PART-001", "delivery_location": "", "latest_delivery_date": "2027-03-01"},
    {"part_id": "PART-001", "delivery_location": "Rome", "latest_delivery_date": "2027-02-30"},
    {"part_id": "PART-001", "delivery_location": "Rome", "latest_delivery_date": "03/01/2027"},
    {"part_id": "PART-001", "delivery_location": "Rome", "latest_delivery_date": "2027-03-01", "extra": 1},
])
def test_invalid_extraction_stops_before_selection(case_pair, bad):
    """Fail the intermediate contract and never execute the second LLM call."""
    case, _ = case_pair
    agent, call = _agent([_response(bad)])
    with pytest.raises(AgentExecutionError) as caught:
        agent.invoke(case["input"]["request"], case["input"]["offers"])
    assert call.call_count == 1
    assert caught.value.error["stage"] == "extract_request"
    assert caught.value.error["kind"] == "invalid_output"
    assert len(caught.value.steps) == 1


def test_incomplete_extraction_is_not_accepted(case_pair):
    """Reject even parseable extraction JSON when generation did not complete."""
    case, source = case_pair
    agent, call = _agent([_response(source["input"]["request"], "incomplete")])
    with pytest.raises(AgentExecutionError) as caught:
        agent.invoke(case["input"]["request"], case["input"]["offers"])
    assert caught.value.error["kind"] == "invalid_output" and call.call_count == 1


@pytest.mark.parametrize("stage", ["extract_request", "select_offer"])
def test_provider_errors_are_stage_specific_and_safe(case_pair, stage):
    """Return safe provider diagnostics and preserve only attempted step records."""
    case, source = case_pair
    responses = [] if stage == "extract_request" else [_response(source["input"]["request"])]
    responses.append(RuntimeError("FAKE_SECRET_MUST_NOT_LEAK"))
    agent, call = _agent(responses)
    with pytest.raises(AgentExecutionError) as caught:
        agent.invoke(case["input"]["request"], case["input"]["offers"])
    assert caught.value.error["stage"] == stage and caught.value.error["kind"] == "api_error"
    assert call.call_count == (1 if stage == "extract_request" else 2)
    assert "FAKE_SECRET" not in str(caught.value)
    assert "FAKE_SECRET" not in json.dumps(caught.value.error)


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_invalid_selection_does_not_produce_an_answer(case_pair, status):
    """Reject unknown selected IDs and incomplete second responses."""
    case, source = case_pair
    agent, call = _agent([_response(source["input"]["request"]),
                          _response({"selected_offer_id": "unknown"}, status)])
    with pytest.raises(AgentExecutionError) as caught:
        agent.invoke(case["input"]["request"], case["input"]["offers"])
    assert caught.value.error["stage"] == "select_offer" and call.call_count == 2


@pytest.mark.parametrize("bad_request", ["", "   ", None, {"part_id": "PART-001"}])
def test_invalid_input_does_not_call_the_model(case_pair, bad_request):
    """Reject invalid request input before starting extraction."""
    case, _ = case_pair
    agent, call = _agent([])
    with pytest.raises(AgentExecutionError) as caught:
        agent.invoke(bad_request, case["input"]["offers"])
    assert caught.value.error == {"stage": "input", "kind": "invalid_input"}
    call.assert_not_called()


def test_invalid_offers_are_rejected_before_extraction(case_pair):
    """Reject insufficient candidates, duplicate IDs, invalid dates and costs."""
    case, _ = case_pair
    invalid = [case["input"]["offers"][:5]]
    for changes in ({"delivery_date": "2027-02-30"}, {"total_cost_eur": -1},
                    {"total_cost_eur": True}, {"total_cost_eur": "10.00"},
                    {"supplier_id": ""}, {"offer_id": case["input"]["offers"][1]["offer_id"]}):
        offers = deepcopy(case["input"]["offers"])
        offers[0].update(changes)
        invalid.append(offers)
    for offers in invalid:
        agent, call = _agent([])
        with pytest.raises(AgentExecutionError):
            agent.invoke(case["input"]["request"], offers)
        call.assert_not_called()


def test_repeated_invocation_cannot_reuse_previous_output(case_pair):
    """Keep graph calls independent when a later extraction fails."""
    case, source = case_pair
    expected = {"selected_offer_id": case["expected_output"]["expected_offer_id"]}
    agent, call = _agent([_response(source["input"]["request"]), _response(expected), _response("bad")])
    assert agent.invoke(case["input"]["request"], case["input"]["offers"]) == expected
    with pytest.raises(AgentExecutionError):
        agent.invoke(case["input"]["request"], case["input"]["offers"])
    assert call.call_count == 3


def test_both_steps_use_same_responses_model_and_pacing(monkeypatch, case_pair):
    """Run the graph through the shared Responses transport with a mocked SDK."""
    case, source = case_pair
    expected = {"selected_offer_id": case["expected_output"]["expected_offer_id"]}
    client = Mock()
    client.responses.create.side_effect = [
        SimpleNamespace(output_text=json.dumps(value), status="completed", id=f"step-{index}", usage=None)
        for index, value in enumerate([source["input"]["request"], expected], 1)
    ]
    settings = SimpleNamespace(model="env-selected-model", max_output_tokens=2048, sleep_seconds=3)
    sleep = Mock()
    monkeypatch.setattr(model.time, "sleep", sleep)
    agent = OfferSelectionAgent(model.PacedResponses(client, settings), "SOURCE RULES")
    assert agent.invoke(case["input"]["request"], case["input"]["offers"]) == expected
    sleep.assert_called_once_with(3)
    assert client.responses.create.call_count == 2
    calls = client.responses.create.call_args_list
    assert all(c.kwargs["model"] == "env-selected-model" and c.kwargs["store"] is False for c in calls)
    assert json.loads(calls[0].kwargs["input"]) == case["input"]["request"]
    assert json.loads(calls[1].kwargs["input"]) == source["input"]


def test_pacing_applies_after_failed_invocation(monkeypatch):
    """Do not skip the inter-call delay after a provider failure."""
    settings = SimpleNamespace(sleep_seconds=4)
    invoke = Mock(side_effect=[RuntimeError("failure"), _response({})])
    monkeypatch.setattr(model, "invoke_model", invoke)
    sleep = Mock()
    monkeypatch.setattr(model.time, "sleep", sleep)
    call = model.PacedResponses(object(), settings)
    with pytest.raises(RuntimeError):
        call("instructions", "first")
    call("instructions", "second")
    sleep.assert_called_once_with(4)


def test_cli_uses_only_case_input_and_prints_demo01_output(monkeypatch, tmp_path, case_pair, capsys):
    """Verify the dataset CLI passes no reference and saves optional local details."""
    case, source = case_pair
    expected = {"selected_offer_id": case["expected_output"]["expected_offer_id"]}
    client = Mock()
    client.responses.create.side_effect = [
        SimpleNamespace(output_text=json.dumps(value), status="completed", id="response", usage=None)
        for value in [source["input"]["request"], expected]
    ]
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(run_agent, "create_client", Mock(return_value=client))
    monkeypatch.setattr(run_agent, "load_settings", Mock(return_value=SimpleNamespace(
        model="fixture-model", max_output_tokens=2048, sleep_seconds=0)))
    details = tmp_path / "details.json"
    v1_dataset = ROOT / "data/datasets/demo02-express-order-v1.json"
    assert run_agent.main(["--case-id", case["id"], "--dataset", str(v1_dataset),
                           "--details-file", str(details)]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    state = json.loads(details.read_text())
    assert state["output"] == expected and len(state["steps"]) == 2
    assert "expected_output" not in state
