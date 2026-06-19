from __future__ import annotations

from pathlib import Path


ROOT = Path(".rsi")
HARNESS = ROOT / "harness.json"
HARNESSES = ROOT / "harnesses"
BENCHMARKS = ROOT / "benchmarks"
TASKS = ROOT / "tasks"
MEMORY = ROOT / "memory"
LEARNINGS = MEMORY / "learnings.md"
RUNS = ROOT / "runs"
PROPOSALS = ROOT / "proposals"
DECISIONS = ROOT / "decisions"
GATES = ROOT / "gates"
CYCLES = ROOT / "cycles"


def ensure_dirs() -> None:
    for path in (
        HARNESSES,
        BENCHMARKS,
        TASKS,
        MEMORY,
        RUNS,
        PROPOSALS,
        DECISIONS,
        GATES,
        CYCLES,
    ):
        path.mkdir(parents=True, exist_ok=True)
