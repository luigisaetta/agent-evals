"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Launch Demo02 evaluation with shared CLI and compact progress output.
"""

import sys

from agent_evals.evaluate import main as evaluate_main


def main(argv: list[str] | None = None) -> int:
    """Run the Demo02 adapter using the common evaluation CLI.

    Args:
        argv: Optional CLI arguments; defaults to process arguments.

    Returns:
        Shared evaluator exit code for completion or setup/execution failures.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--task" or arg.startswith("--task=") for arg in arguments):
        raise SystemExit("Demo02 uses its own task adapter; use the shared CLI to select another task.")
    return evaluate_main(["--task", "demo02.evaluation", "--compact-progress", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
