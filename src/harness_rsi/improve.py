from __future__ import annotations

import hashlib
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
    source_split = results.get("metadata", {}).get("split")
    if source_split and source_split != "train":
        raise RuntimeError(
            f"Proposal generation requires a train split run; got {source_split}."
        )
    learnings = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    proposal_id = datetime.now(timezone.utc).strftime("proposal-%Y%m%dT%H%M%S%fZ")
    evidence_manifest = proposal_evidence_manifest(run_dir, results, trace)

    if mock:
        proposal: dict[str, Any] = {
            "id": proposal_id,
            "source_run": run_dir.name,
            "source_split": source_split,
            "status": "proposed",
            "summary": "Mock proposal: add a learning about checking expected output first.",
            "learning": "Before answering, identify the evaluator target and make sure the response contains it.",
            "config_patch": {
                "prompt_append": " Before finalizing, check the answer against the evaluator target."
            },
            "evidence": results,
            "evidence_manifest": evidence_manifest,
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
        evidence_manifest["prompt_digest"] = digest_text(prompt)
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
                "source_split": source_split,
                "status": "proposed",
                "evidence_manifest": evidence_manifest,
            }
        )

    path = PROPOSALS / f"{proposal_id}.json"
    write_json(path, proposal)
    return path


def proposal_evidence_manifest(
    run_dir: Path,
    results: dict[str, Any],
    trace: str,
) -> dict[str, Any]:
    input_path = run_dir / "input.json"
    metadata = results.get("metadata", {})
    return {
        "source_run": results.get("run_id", run_dir.name),
        "source_split": metadata.get("split"),
        "source_run_path": str(run_dir),
        "task_ids": [str(item["task_id"]) for item in results.get("results", [])],
        "trace_task_ids": trace_task_ids(trace),
        "task_digest": results.get("task_digest"),
        "results_digest": digest_payload(results),
        "trace_digest": digest_text(trace),
        "input_digest": digest_text(input_path.read_text()) if input_path.exists() else None,
    }


def trace_task_ids(trace: str) -> list[str]:
    task_ids = set()
    for line in trace.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("task_id"):
            task_ids.add(str(event["task_id"]))
    return sorted(task_ids)


def digest_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
