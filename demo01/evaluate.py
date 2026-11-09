"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Launch Demo01 through the common evaluation command-line interface.
"""

import sys

from agent_evals.evaluate import main as evaluate_main


def main(argv: list[str] | None = None) -> int:
    """Select the Demo01 adapter and forward common evaluation options.

    Args:
        argv: Optional arguments; defaults to process arguments. An explicit
            --task override remains supported for legacy launcher compatibility.

    Returns:
        The shared evaluator's exit code.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    return evaluate_main(["--task", "demo01.evaluation", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
