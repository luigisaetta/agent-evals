"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Run NL request extraction and reused offer selection through LangGraph.
"""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import time
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_evals.errors import describe_api_error
from agent_evals.tasks.offer_selection import build_instructions, parse_output, validate_input
from demo02.contracts import parse_request, validate_agent_input

ModelCall = Callable[[str, object], dict]


class AgentInput(TypedDict):
    """Carry the NL request and the six original supplier offers.

    Attributes:
        request: English delivery request.
        offers: Structured JSON supplier offers.
    """

    request: str
    offers: list[dict]


class AgentState(AgentInput, total=False):
    """Carry intermediate results and safe errors across graph nodes.

    Attributes:
        extracted_request: Validated structured request from step one.
        output: Final Demo01-compatible answer, or null after an error.
        error: Stage-specific failure description, or null on success.
        steps: Response metadata and diagnostics for executed model steps.
    """

    extracted_request: dict | None
    output: dict | None
    error: dict | None
    steps: list[dict]


class AgentExecutionError(RuntimeError):
    """Report a failed graph stage without exposing provider exception text.

    Attributes:
        error: Safe stage, failure kind and diagnostic fields.
        steps: Records for steps that were actually attempted.
    """

    def __init__(self, error: dict, steps: list[dict]):
        """Store failure diagnostics and construct a safe exception message.

        Args:
            error: Stage-specific safe error description.
            steps: Executed-step records, including available raw model outputs.
        """
        self.error = error
        self.steps = steps
        super().__init__(f"{error['stage']} failed: {error['kind']}")


def _run_step(name: str, call_model: ModelCall, instructions: str,
              payload: object, parser: Callable[[str], dict], observer: Callable | None = None) -> tuple:
    """Execute one model call and validate its completed response.

    Args:
        name: Graph stage name.
        call_model: Shared Responses callable, with pacing handled externally.
        instructions: Instructions for this stage.
        payload: Only the data required by this stage.
        parser: Stage-specific output parser.
        observer: Optional context factory receiving stage, prompt, input and
            the mutable step record; it observes validated outcomes as well.

    Returns:
        Parsed object or null, step record, and safe error object or null.
    """
    started = time.perf_counter()
    record = {"stage": name, "status": "api_error", "raw_output": None,
              "response_id": None, "usage": {}}
    with observer(name, instructions, payload, record) if observer else nullcontext():
        parsed, error = None, None
        try:
            response = call_model(instructions, payload)
        except Exception as failure:
            error = {"stage": name, "kind": "api_error", **describe_api_error(failure)}
        else:
            try:
                record.update({
                    "raw_output": response["raw_output"], "response_id": response.get("response_id"),
                    "usage": response.get("usage", {}), "response_status": response["response_status"],
                })
                if response["response_status"] != "completed":
                    raise ValueError("Model response did not complete")
                parsed = parser(response["raw_output"])
                record["status"] = "completed"
            except ValueError:
                record["status"] = "invalid_output"
                error = {"stage": name, "kind": "invalid_output", "type": "InvalidStepOutput"}
            except Exception as failure:
                record["status"] = "internal_error"
                error = {"stage": name, "kind": "internal_error", "type": type(failure).__name__}
        record["latency_seconds"] = round(time.perf_counter() - started, 6)
        if error:
            record["error"] = error
    return parsed, record, error


def build_graph(call_model: ModelCall, selection_rules: str,
                extraction_instructions: str | None = None,
                step_observer: Callable | None = None):
    """Compile the two-node graph with an explicit extraction-error exit.

    Args:
        call_model: Callable issuing one OCI Responses request per invocation.
        selection_rules: Existing Demo01 natural-language selection rules.
        extraction_instructions: Optional override of the extraction prompt file.
        step_observer: Optional context factory observing each validated step.

    Returns:
        Compiled LangGraph with extraction followed by conditional selection.
    """
    extraction_prompt = extraction_instructions if extraction_instructions is not None else (
        Path(__file__).parent / "prompts/extract_request.md"
    ).read_text()
    selection_prompt = build_instructions(selection_rules)

    def extract_request(state: AgentState) -> dict:
        """Extract the structured request using the first model call.

        Args:
            state: Graph input containing the NL request and candidate offers.

        Returns:
            Validated request or a failure, plus the first step record.
        """
        # Also protect callers invoking the compiled graph directly.
        try:
            validate_agent_input(state["request"], state["offers"])
        except (ValueError, KeyError, TypeError):
            return {"extracted_request": None, "output": None, "steps": [],
                    "error": {"stage": "input", "kind": "invalid_input"}}
        parsed, record, error = _run_step(
            "extract_request", call_model, extraction_prompt, state["request"], parse_request, step_observer,
        )
        return {"extracted_request": parsed, "output": None, "error": error, "steps": [record]}

    def select_offer(state: AgentState) -> dict:
        """Reuse Demo01 request/offer handling for the second model call.

        Args:
            state: Successful extracted request and original structured offers.

        Returns:
            Final selected_offer_id or a failure, with both step records.
        """
        task_input = {"request": state["extracted_request"], "offers": state["offers"]}
        try:
            validate_input(task_input)
        except ValueError:
            return {"output": None, "error": {"stage": "select_offer", "kind": "invalid_input"}}
        parsed, record, error = _run_step(
            "select_offer", call_model, selection_prompt, task_input,
            lambda text: parse_output(text, task_input), step_observer,
        )
        return {"output": parsed if error is None else None, "error": error,
                "steps": state["steps"] + [record]}

    def after_extraction(state: AgentState) -> Literal["select_offer", "stop"]:
        """Route only validated extractions to offer selection.

        Args:
            state: Output of the extraction node.

        Returns:
            The selection route on success, otherwise the terminal route.
        """
        return "stop" if state["error"] is not None else "select_offer"

    builder = StateGraph(AgentState, input_schema=AgentInput)
    builder.add_node("extract_request", extract_request)
    builder.add_node("select_offer", select_offer)
    builder.add_edge(START, "extract_request")
    builder.add_conditional_edges("extract_request", after_extraction,
                                  {"select_offer": "select_offer", "stop": END})
    builder.add_edge("select_offer", END)
    return builder.compile()


class OfferSelectionAgent:
    """Expose a small callable interface over the compiled two-step graph."""

    def __init__(self, call_model: ModelCall, selection_rules: str,
                 step_observer: Callable | None = None):
        """Compile the graph once for use with one or more input cases.

        Args:
            call_model: Usually a PacedResponses instance using the .env model.
            selection_rules: Unchanged Demo01 offer-selection rules.
            step_observer: Optional context factory for per-step observability.
        """
        self.graph = build_graph(call_model, selection_rules, step_observer=step_observer)

    def run(self, request: str, offers: list[dict]) -> AgentState:
        """Execute both stages and retain intermediate details for inspection.

        Args:
            request: Natural-language delivery request.
            offers: Six structured supplier offers.

        Returns:
            Successful graph state containing the extracted request and answer.

        Raises:
            AgentExecutionError: If input validation or either graph stage fails.
        """
        state = self.graph.invoke({"request": request, "offers": deepcopy(offers)})
        if state.get("error") is not None:
            raise AgentExecutionError(state["error"], state["steps"])
        return state

    def invoke(self, request: str, offers: list[dict]) -> dict:
        """Return the same successful output contract as Demo01.

        Args:
            request: English delivery request.
            offers: Six original structured offers.

        Returns:
            Exactly an object containing selected_offer_id.

        Raises:
            AgentExecutionError: If either stage fails; no answer is fabricated.
        """
        return self.run(request, offers)["output"]
