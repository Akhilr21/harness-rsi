from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.io import read_json, write_json
from harness_rsi.model import call_model
from harness_rsi.paths import HARNESS, LEARNINGS, PROPOSALS


def latest_run(runs_dir: Path) -> Path:
    runs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    if not runs:
        raise RuntimeError("No runs found. Run `harness-rsi run` first.")
    return runs[-1]


def propose_patch(
    *,
    run_dir: Path,
    model: str | None,
    reasoning_effort: str,
    mock: bool,
    config_path: Path = HARNESS,
) -> Path:
    config = read_json(config_path)
    proposal_model = model or config["model"]
    results = read_json(run_dir / "results.json")
    trace = (run_dir / "trace.jsonl").read_text()
    learnings = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    proposal_id = datetime.now(timezone.utc).strftime("proposal-%Y%m%dT%H%M%S%fZ")

    if mock:
        proposal: dict[str, Any] = {
            "id": proposal_id,
            "source_run": run_dir.name,
            "status": "proposed",
            "summary": "Mock proposal: add a learning about checking expected output first.",
            "learning": "Before answering, identify the evaluator target and make sure the response contains it.",
            "config_patch": {
                "prompt_append": " Before finalizing, check the answer against the evaluator target."
            },
            "evidence": results,
        }
    else:
        prompt = f"""
You are improving a model harness, not changing the model.

Current harness:
{config}

Promoted learnings:
{learnings}

Run results:
{results}

Trace JSONL:
{trace}

Propose exactly one small harness improvement. Return JSON with:
id, summary, learning, config_patch, risks, expected_metric.
Do not propose changing the model.
"""
        text = call_model(model=proposal_model, prompt=prompt, reasoning_effort=reasoning_effort)
        try:
            proposal = json.loads(text)
            if not isinstance(proposal, dict):
                raise ValueError("proposal must be a JSON object")
        except (json.JSONDecodeError, ValueError):
            proposal = {"raw_model_output": text}
        proposal.update(
            {
                "id": proposal_id,
                "source_run": run_dir.name,
                "status": "proposed",
            }
        )

    path = PROPOSALS / f"{proposal_id}.json"
    write_json(path, proposal)
    return path
