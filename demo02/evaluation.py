"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Adapt the Demo02 graph to shared evaluation and per-step Langfuse tracing.
"""

from contextlib import ExitStack, contextmanager
import json
from pathlib import Path

from agent_evals.config import ROOT, Settings
from agent_evals.task import EvaluationTask
from agent_evals.tasks.offer_selection import build_instructions, parse_output, score_output
from demo02.agent import AgentExecutionError, OfferSelectionAgent
from demo02.contracts import parse_request, validate_agent_input
from demo02.model import PacedResponses


def validate_case(case: dict) -> None:
    """Validate NL inputs and reference membership without computing the winner.

    Accepts the v1 reference (expected_offer_id only) and the v2 reference, which
    adds expected_request with the structured request the extraction step should produce.

    Args:
        case: Dataset envelope containing input and a stored reference.

    Raises:
        ValueError: If the input or reference does not match the demo contract.
    """
    task_input = case["input"]
    if not isinstance(task_input, dict) or set(task_input) != {"request", "offers"}:
        raise ValueError("Demo02 input must contain request and offers")
    validate_agent_input(task_input["request"], task_input["offers"])
    expected = case["expected_output"]
    if (not isinstance(expected, dict)
            or set(expected) not in ({"expected_offer_id"}, {"expected_offer_id", "expected_request"})
            or not isinstance(expected["expected_offer_id"], str)
            or expected["expected_offer_id"] not in {o["offer_id"] for o in task_input["offers"]}):
        raise ValueError("Reference must identify one of the supplied offers")
    if "expected_request" in expected:
        # Dataset v2 also stores the reference extraction; apply the extraction contract to it.
        if not isinstance(expected["expected_request"], dict):
            raise ValueError("Reference request must be a JSON object")
        parse_request(json.dumps(expected["expected_request"]))


def create_invoker(*, client, settings: Settings, rules: str, tracking=None):
    """Prepare one graph and paced transport for an entire sequential experiment.

    Args:
        client: Initialized signed OCI Responses client.
        settings: Environment-derived model, pacing and request settings.
        rules: Shared natural-language selection rules.
        tracking: Optional Langfuse client; null disables external tracing.

    Returns:
        Callable accepting task input only and returning a shared result envelope.
    """
    publication_errors = []

    @contextmanager
    def observe_step(stage, instructions, payload, record):
        """Trace an actual model step, including its validated outcome.

        Args:
            stage: Graph node name.
            instructions: Instructions actually sent to this node.
            payload: Only the input supplied to this node.
            record: Mutable record populated before the context exits.

        Yields:
            Control to model execution and output validation.
        """
        stack = ExitStack()
        generation = None
        try:
            generation = stack.enter_context(tracking.start_as_current_observation(
                name=f"demo02-{stage}", as_type="generation", model=settings.model,
                input={"instructions": instructions, "input": payload},
                metadata={"demo": "demo02", "stage": stage, "model": settings.model},
                model_parameters={"max_output_tokens": settings.max_output_tokens},
            ))
        except Exception as failure:
            publication_errors.append(type(failure).__name__)
        try:
            yield
        finally:
            try:
                if generation is not None:
                    generation.update(
                        output=record.get("raw_output"), usage_details=record.get("usage", {}),
                        level="DEFAULT" if record["status"] == "completed" else "ERROR",
                        status_message=record["status"],
                        metadata={"demo": "demo02", "stage": stage, "model": settings.model,
                                  "response_id": record.get("response_id"), "error": record.get("error")},
                    )
            except Exception as failure:
                publication_errors.append(type(failure).__name__)
            finally:
                try:
                    stack.close()
                except Exception as failure:
                    publication_errors.append(type(failure).__name__)

    agent = OfferSelectionAgent(
        PacedResponses(client, settings), rules,
        step_observer=observe_step if tracking is not None else None,
    )

    def invoke(task_input: dict) -> dict:
        """Execute the graph without ever receiving an expected answer.

        Args:
            task_input: NL request and six original structured offers.

        Returns:
            Final-response envelope with intermediate records and any safe error.
        """
        publication_errors.clear()
        try:
            state = agent.run(task_input["request"], task_input["offers"])
            steps, error = state["steps"], None
            extracted = state["extracted_request"]
            raw_output = json.dumps(state["output"], ensure_ascii=False)
        except AgentExecutionError as failure:
            steps, error = failure.steps, failure.error
            extracted = None
            if steps and steps[0]["status"] == "completed":
                extracted = json.loads(steps[0]["raw_output"])
            raw_output = steps[-1].get("raw_output") if steps else None
        return {
            "raw_output": raw_output, "response_status": "failed" if error else "completed",
            "response_id": steps[-1].get("response_id") if steps else None,
            "usage": {key: sum(step.get("usage", {}).get(key, 0) for step in steps)
                      for key in ("input", "output", "total")},
            "steps": steps, "extracted_request": extracted, "execution_error": error,
            "publication_errors": list(publication_errors),
        }

    return invoke


TASK = EvaluationTask(
    name="demo02-offer-selection",
    title="Demo02 | Natural-language Express Order | LangGraph",
    default_dataset=Path("data/datasets/demo02-express-order-v2.json"),
    default_rules=Path("rules/offer-selection.md"),
    rules_manifest_key="rules/offer-selection.md",
    dataset_namespace="demo02-express-order",
    metric_name="selection_correct",
    validate_case=validate_case,
    build_instructions=build_instructions,
    parse_output=parse_output,
    score_output=score_output,
    create_invoker=create_invoker,
    source_files=tuple(sorted(p.relative_to(ROOT) for p in (ROOT / "demo02").glob("*.py")))
    + (Path("demo02/prompts/extract_request.md"),),
)
