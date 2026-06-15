from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_rsi.io import read_json, write_json
from harness_rsi.paths import DECISIONS, HARNESS, LEARNINGS


def promote(proposal_path: Path) -> Path:
    proposal = read_json(proposal_path)
    config = read_json(HARNESS)
    patch = proposal.get("config_patch", {})

    if prompt_append := patch.get("prompt_append"):
        config["prompt"] = f"{config['prompt']} {prompt_append}".strip()

    if learning := proposal.get("learning"):
        with LEARNINGS.open("a") as handle:
            handle.write(f"\n## {proposal['id']}\n\n{learning}\n")

    proposal["status"] = "promoted"
    proposal["decided_at"] = datetime.now(timezone.utc).isoformat()
    write_json(proposal_path, proposal)
    write_json(HARNESS, config)

    decision_path = DECISIONS / f"{proposal['id']}-promoted.json"
    write_json(decision_path, proposal)
    return decision_path


def reject(proposal_path: Path, reason: str) -> Path:
    proposal = read_json(proposal_path)
    proposal["status"] = "rejected"
    proposal["rejection_reason"] = reason
    proposal["decided_at"] = datetime.now(timezone.utc).isoformat()
    write_json(proposal_path, proposal)

    decision_path = DECISIONS / f"{proposal['id']}-rejected.json"
    write_json(decision_path, proposal)
    return decision_path
