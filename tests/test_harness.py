from __future__ import annotations

import os
from pathlib import Path

from harness_rsi.cli import main


def test_mock_loop(tmp_path: Path) -> None:
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        assert main(["init"]) == 0
        assert main(["run", "--mock"]) == 0
        assert main(["improve", "--mock"]) == 0
        proposals = sorted((tmp_path / ".rsi" / "proposals").glob("*.json"))
        assert proposals
        assert main(["promote", str(proposals[-1])]) == 0
        learnings = tmp_path / ".rsi" / "memory" / "learnings.md"
        assert "evaluator target" in learnings.read_text()
    finally:
        os.chdir(cwd)
