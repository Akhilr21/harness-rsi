from __future__ import annotations

from pathlib import Path


ROOT = Path(".rsi")
HARNESS = ROOT / "harness.json"
TASKS = ROOT / "tasks"
MEMORY = ROOT / "memory"
LEARNINGS = MEMORY / "learnings.md"
RUNS = ROOT / "runs"
PROPOSALS = ROOT / "proposals"
DECISIONS = ROOT / "decisions"


def ensure_dirs() -> None:
    for path in (TASKS, MEMORY, RUNS, PROPOSALS, DECISIONS):
        path.mkdir(parents=True, exist_ok=True)
