"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify Demo01 entry-point relocation and compatibility with shared imports.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent_evals.config import ROOT
from agent_evals.tasks import offer_selection
from demo01 import evaluate, evaluation


def test_legacy_imports_are_identical_to_canonical_demo01_objects():
    """Keep Demo02 imports on the exact moved callbacks without duplication."""
    for name in offer_selection.__all__:
        assert getattr(offer_selection, name) is getattr(evaluation, name)


def test_demo01_entry_point_selects_canonical_adapter(monkeypatch):
    """Preserve CLI options and exit codes through the thin demo wrapper."""
    calls = []

    def run(arguments):
        """Capture options rather than invoking external services."""
        calls.append(arguments)
        return 2

    monkeypatch.setattr(evaluate, "evaluate_main", run)
    assert evaluate.main(["--experiment-name", "Name with spaces", "--limit", "1"]) == 2
    assert calls == [["--task", "demo01.evaluation", "--experiment-name",
                      "Name with spaces", "--limit", "1"]]


@pytest.mark.parametrize("launcher", ["demo01/run_experiment.sh", "run_experiment.sh"])
def test_launchers_resolve_root_and_preserve_arguments_and_exit_code(tmp_path, launcher):
    """Execute from another directory with fake Conda; never contact providers."""
    executable = tmp_path / "conda"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:], "
        "'pythonpath': os.environ['PYTHONPATH']}))\n"
        "sys.exit(2)\n"
    )
    executable.chmod(0o755)
    environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(ROOT / launcher), "Name with spaces", "--limit", "1"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    captured = json.loads(result.stdout)
    assert Path(captured["cwd"]) == ROOT
    assert captured["args"] == ["run", "--no-capture-output", "-n", "agent-evals",
                                "python", "-m", "demo01.evaluate", "--experiment-name",
                                "Name with spaces", "--limit", "1"]
    assert captured["pythonpath"].split(":")[:2] == [str(ROOT / "src"), str(ROOT)]
