"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Invoke the Demo02 LangGraph agent on one dataset input case.
"""

import argparse
import json
from pathlib import Path
import sys

from agent_evals.config import ROOT, load_settings
from agent_evals.oci_model import create_client
from demo02.agent import AgentExecutionError, OfferSelectionAgent
from demo02.model import PacedResponses


def _save_details(path: Path | None, details: dict) -> None:
    """Write optional local step details without affecting the stdout answer.

    Args:
        path: Explicit destination, preferably under ignored data/runs/.
        details: Graph state or safe failure and step records.
    """
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run a selected dataset request and its six offers through the agent.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero on success, one on setup failure, two on agent-stage failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/datasets/demo02-express-order-v2.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "rules/offer-selection.md")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--sleep-seconds", type=float)
    parser.add_argument("--details-file", type=Path)
    args = parser.parse_args(argv)
    try:
        cases = json.loads(args.dataset.read_text())
        matches = [case for case in cases if case["id"] == args.case_id]
        if len(matches) != 1:
            raise ValueError("Case ID must identify exactly one dataset record")
        task_input = matches[0]["input"]
        if not isinstance(task_input, dict) or set(task_input) != {"request", "offers"}:
            raise ValueError("Case input must contain only request and offers")
        settings = load_settings(args.env_file, args.sleep_seconds)
        rules = args.rules.read_text()
        with create_client(settings) as client:
            agent = OfferSelectionAgent(PacedResponses(client, settings), rules)
            state = agent.run(task_input["request"], task_input["offers"])
        _save_details(args.details_file, state)
        print(json.dumps(state["output"], ensure_ascii=False))
        return 0
    except AgentExecutionError as error:
        _save_details(args.details_file, {"error": error.error, "steps": error.steps})
        print(json.dumps({"error": error.error}), file=sys.stderr)
        return 2
    except Exception as error:
        # Do not print raw provider/configuration exceptions or credential paths.
        print(f"Demo02 setup failed ({type(error).__name__}). Check input and configuration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
