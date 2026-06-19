from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import harness_path
from harness_rsi.io import read_json, write_json


def create_candidate_version(
    *,
    parent: str,
    candidate: str,
    proposal_path: Path,
    gate_path: Path,
    overwrite: bool = False,
) -> Path:
    parent_path = harness_path(parent)
    candidate_path = harness_path(candidate)
    if not parent_path.exists():
        raise RuntimeError(f"Parent harness not found: {parent_path}")
    if candidate_path.exists() and not overwrite:
        raise RuntimeError(f"Candidate harness already exists: {candidate_path}")

    proposal = read_json(proposal_path)
    gate = read_json(gate_path)
    if gate.get("decision") != "promote":
        raise RuntimeError("Cannot create candidate harness from a rejected gate.")
    if gate.get("baseline_harness") != parent:
        raise RuntimeError(
            f"Gate baseline {gate.get('baseline_harness')} does not match parent {parent}."
        )
    if gate.get("candidate_harness") not in {candidate, None}:
        raise RuntimeError(
            f"Gate candidate {gate.get('candidate_harness')} does not match {candidate}."
        )

    parent_config = read_json(parent_path)
    config = apply_config_patch(parent_config, proposal.get("config_patch", {}))
    config.update(
        {
            "id": candidate,
            "parent": parent,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_from_proposal": proposal.get("id") or proposal_path.stem,
            "created_from_gate": gate_path.name,
            "lineage": {
                "parent": parent,
                "proposal": str(proposal_path),
                "gate": str(gate_path),
                "baseline_run": gate.get("baseline_run"),
                "candidate_run": gate.get("candidate_run"),
                "benchmark": gate.get("benchmark"),
                "split": gate.get("split"),
                "pass_rate_delta": gate.get("pass_rate_delta"),
            },
        }
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(candidate_path, config)
    return candidate_path


def apply_config_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    next_config = deepcopy(config)
    if "model" in patch and patch["model"] != config.get("model"):
        raise RuntimeError("Harness promotion cannot change the model.")
    if prompt_append := patch.get("prompt_append"):
        next_config["prompt"] = f"{next_config['prompt']} {prompt_append}".strip()
    for key in ("max_retries", "reasoning_effort"):
        if key in patch:
            next_config[key] = patch[key]
    if tools_patch := patch.get("tools"):
        tools = deepcopy(next_config.get("tools", {}))
        tools.update(tools_patch)
        next_config["tools"] = tools
    return next_config


def list_harness_versions() -> list[dict[str, Any]]:
    versions = []
    root = harness_path("H0").parent
    if not root.exists():
        return versions
    for path in sorted(root.glob("*.json")):
        config = read_json(path)
        versions.append(
            {
                "name": path.stem,
                "declared_id": config.get("id", path.stem),
                "id_matches_filename": config.get("id", path.stem) == path.stem,
                "parent": config.get("parent"),
                "model": config.get("model"),
                "path": str(path),
                "created_at": config.get("created_at"),
            }
        )
    return versions
