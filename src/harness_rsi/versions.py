from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import coverage_gate_evidence, digest_payload, harness_path
from harness_rsi.harness import harness_behavior_digest
from harness_rsi.io import read_json, write_json


def create_candidate_version(
    *,
    parent: str,
    candidate: str,
    proposal_path: Path,
    overwrite: bool = False,
) -> Path:
    parent_path = harness_path(parent)
    candidate_path = harness_path(candidate)
    if not parent_path.exists():
        raise RuntimeError(f"Parent harness not found: {parent_path}")
    if candidate_path.exists() and not overwrite:
        raise RuntimeError(f"Candidate harness already exists: {candidate_path}")

    proposal = read_json(proposal_path)
    parent_config = read_json(parent_path)
    config = apply_config_patch(parent_config, proposal.get("config_patch", {}))
    config.update(
        {
            "id": candidate,
            "parent": parent,
            "status": "candidate",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_from_proposal": proposal.get("id") or proposal_path.stem,
            "lineage": {
                "parent": parent,
                "proposal": str(proposal_path),
            },
        }
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(candidate_path, config)
    return candidate_path


def promote_candidate_version(*, candidate: str, gate_path: Path) -> Path:
    candidate_path = harness_path(candidate)
    if not candidate_path.exists():
        raise RuntimeError(f"Candidate harness not found: {candidate_path}")

    config = read_json(candidate_path)
    gate = read_json(gate_path)
    if gate.get("decision") != "promote":
        raise RuntimeError("Cannot promote harness from a rejected gate.")
    if config.get("status") == "promoted":
        raise RuntimeError(f"Harness {candidate} is already promoted.")
    if config.get("status") != "candidate":
        raise RuntimeError(f"Harness {candidate} is not a candidate.")
    if config.get("id") != candidate:
        raise RuntimeError(
            f"Harness file {candidate_path} declares id {config.get('id')}, not {candidate}."
        )
    if gate.get("baseline_harness") != config.get("parent"):
        raise RuntimeError(
            "Gate baseline "
            f"{gate.get('baseline_harness')} does not match parent {config.get('parent')}."
        )
    if gate.get("candidate_harness") != candidate:
        raise RuntimeError(
            f"Gate candidate {gate.get('candidate_harness')} does not match {candidate}."
        )
    if gate.get("model") and gate.get("model") != config.get("model"):
        raise RuntimeError(
            f"Gate model {gate.get('model')} does not match harness model {config.get('model')}."
        )
    candidate_digest = gate.get("candidate_harness_digest")
    if not candidate_digest:
        raise RuntimeError("Gate is missing candidate harness digest.")
    if candidate_digest != harness_behavior_digest(config):
        raise RuntimeError("Gate candidate digest does not match current candidate harness.")
    validate_promotion_gate_contract(gate)

    lineage = deepcopy(config.get("lineage", {}))
    lineage.update(
        {
            "gate": str(gate_path),
            "baseline_run": gate.get("baseline_run"),
            "candidate_run": gate.get("candidate_run"),
            "benchmark": gate.get("benchmark"),
            "split": gate.get("split"),
            "suite_version": gate.get("suite_version"),
            "suite_digest": gate.get("suite_digest"),
            "coverage_digest": gate.get("coverage_digest"),
            "current_coverage_digest": gate.get("current_coverage_digest"),
            "coverage_policy_digest": gate.get("coverage_policy_digest"),
            "waiver_review_policy": gate.get("waiver_review_policy"),
            "waiver_review": gate.get("waiver_review"),
            "evaluator_digests": gate.get("evaluator_digests"),
            "heldout_evaluator_digests": gate.get("heldout_evaluator_digests"),
            "regression_evaluator_digests": gate.get("regression_evaluator_digests"),
            "pass_rate_delta": gate.get("pass_rate_delta"),
            "heldout_gate": gate.get("heldout_gate"),
            "regression_gate": gate.get("regression_gate"),
            "split_isolation_audit": gate.get("split_isolation_audit"),
            "split_isolation_digest": gate.get("split_isolation_digest"),
            "heldout_gate_digest": gate.get("heldout_gate_digest"),
            "regression_gate_digest": gate.get("regression_gate_digest"),
            "heldout_baseline_run": gate.get("heldout_baseline_run"),
            "heldout_candidate_run": gate.get("heldout_candidate_run"),
            "regression_baseline_run": gate.get("regression_baseline_run"),
            "regression_candidate_run": gate.get("regression_candidate_run"),
            "heldout_pass_rate_delta": gate.get("heldout_pass_rate_delta"),
            "regression_pass_rate_delta": gate.get("regression_pass_rate_delta"),
        }
    )
    config.update(
        {
            "status": "promoted",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "promoted_from_gate": gate_path.name,
            "lineage": lineage,
        }
    )
    write_json(candidate_path, config)
    return candidate_path


def validate_promotion_gate_contract(gate: dict[str, Any]) -> None:
    if gate.get("split") != "heldout+regression":
        raise RuntimeError("Promotion requires a composite heldout+regression gate.")
    required_fields = [
        "heldout_gate",
        "regression_gate",
        "split_isolation_audit",
        "split_isolation_digest",
        "heldout_gate_digest",
        "regression_gate_digest",
        "heldout_baseline_run",
        "heldout_candidate_run",
        "regression_baseline_run",
        "regression_candidate_run",
        "heldout_decision",
        "regression_decision",
    ]
    missing = [field for field in required_fields if not gate.get(field)]
    if missing:
        raise RuntimeError(
            "Composite promotion gate is missing required evidence fields: "
            f"{', '.join(missing)}."
        )
    if gate.get("heldout_decision") != "promote" or gate.get("regression_decision") != "promote":
        raise RuntimeError("Composite promotion gate requires heldout and regression promotion.")
    validate_split_isolation_audit(gate)
    validate_child_gate_digest(gate, "heldout_gate", "heldout_gate_digest")
    validate_child_gate_digest(gate, "regression_gate", "regression_gate_digest")
    validate_promotion_coverage_current(gate)


def validate_split_isolation_audit(gate: dict[str, Any]) -> None:
    audit_path = Path(str(gate["split_isolation_audit"]))
    if not audit_path.exists():
        raise RuntimeError(f"Composite promotion gate split isolation audit not found: {audit_path}.")
    audit = read_json(audit_path)
    if audit.get("status") != "pass":
        raise RuntimeError("Composite promotion gate requires a passing split isolation audit.")
    current_digest = digest_payload(
        {key: value for key, value in audit.items() if key != "split_isolation_digest"}
    )
    if current_digest != gate["split_isolation_digest"]:
        raise RuntimeError("Composite promotion gate split isolation audit digest mismatch.")


def validate_child_gate_digest(gate: dict[str, Any], path_field: str, digest_field: str) -> None:
    child_path = Path(str(gate[path_field]))
    if not child_path.exists():
        raise RuntimeError(f"Composite promotion gate child gate not found: {child_path}.")
    current_digest = digest_payload(read_json(child_path))
    if current_digest != gate[digest_field]:
        raise RuntimeError(
            f"Composite promotion gate child digest mismatch for {path_field}."
        )


def validate_promotion_coverage_current(gate: dict[str, Any]) -> None:
    benchmark = gate.get("benchmark")
    coverage_digest = gate.get("coverage_digest")
    if not benchmark or not coverage_digest:
        return
    evidence = coverage_gate_evidence(
        str(benchmark),
        expected_coverage_digest=str(coverage_digest),
        waiver_review_policy=gate.get("waiver_review_policy"),
    )
    coverage_drift = [
        failure
        for failure in evidence.get("coverage_failures", [])
        if failure.get("type") == "coverage_digest_mismatch"
    ]
    if coverage_drift:
        raise RuntimeError("Composite promotion gate coverage digest is stale.")
    if evidence.get("waiver_review_failures"):
        raise RuntimeError("Composite promotion gate waiver review policy is failing.")


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
                "status": config.get("status"),
                "model": config.get("model"),
                "path": str(path),
                "created_at": config.get("created_at"),
            }
        )
    return versions
