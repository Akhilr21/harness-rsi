from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import gate_candidate, harness_path, run_benchmark
from harness_rsi.improve import propose_patch
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import CYCLES
from harness_rsi.versions import create_candidate_version, promote_candidate_version


def run_experiment_cycle(
    *,
    parent: str,
    candidate: str,
    benchmark: str,
    model: str | None,
    reasoning_effort: str,
    mock: bool,
    min_heldout_delta: float,
    max_regression_drop: float,
    promote: bool,
) -> Path:
    cycle_id = datetime.now(timezone.utc).strftime("cycle-%Y%m%dT%H%M%S%fZ")
    summary: dict[str, Any] = {
        "id": cycle_id,
        "parent": parent,
        "candidate": candidate,
        "benchmark": benchmark,
        "mock": mock,
        "status": "started",
        "steps": [],
    }

    train_run = run_benchmark(
        benchmark=benchmark,
        split="train",
        harness=parent,
        model=model,
        mock=mock,
    )
    summary["steps"].append({"name": "train_parent", "run": str(train_run.run_dir)})

    proposal = propose_patch(
        run_dir=train_run.run_dir,
        model=model,
        reasoning_effort=reasoning_effort,
        mock=mock,
        config_path=harness_path(parent),
    )
    summary["steps"].append({"name": "propose_patch", "proposal": str(proposal)})

    candidate_path = create_candidate_version(
        parent=parent,
        candidate=candidate,
        proposal_path=proposal,
    )
    summary["steps"].append({"name": "create_candidate", "harness": str(candidate_path)})

    heldout_parent = run_benchmark(
        benchmark=benchmark,
        split="heldout",
        harness=parent,
        model=model,
        mock=mock,
    )
    heldout_candidate = run_benchmark(
        benchmark=benchmark,
        split="heldout",
        harness=candidate,
        model=model,
        mock=mock,
    )
    heldout_gate = gate_candidate(
        baseline_run=heldout_parent.run_dir,
        candidate_run=heldout_candidate.run_dir,
        min_pass_rate_delta=min_heldout_delta,
        max_allowed_drop=0,
    )
    heldout_decision = read_json(heldout_gate)
    summary["steps"].append(
        {
            "name": "heldout_gate",
            "baseline_run": str(heldout_parent.run_dir),
            "candidate_run": str(heldout_candidate.run_dir),
            "gate": str(heldout_gate),
            "decision": heldout_decision["decision"],
        }
    )

    regression_parent = run_benchmark(
        benchmark=benchmark,
        split="regression",
        harness=parent,
        model=model,
        mock=mock,
    )
    regression_candidate = run_benchmark(
        benchmark=benchmark,
        split="regression",
        harness=candidate,
        model=model,
        mock=mock,
    )
    regression_gate = gate_candidate(
        baseline_run=regression_parent.run_dir,
        candidate_run=regression_candidate.run_dir,
        min_pass_rate_delta=0,
        max_allowed_drop=max_regression_drop,
    )
    regression_decision = read_json(regression_gate)
    summary["steps"].append(
        {
            "name": "regression_gate",
            "baseline_run": str(regression_parent.run_dir),
            "candidate_run": str(regression_candidate.run_dir),
            "gate": str(regression_gate),
            "decision": regression_decision["decision"],
        }
    )

    should_promote = (
        promote
        and heldout_decision["decision"] == "promote"
        and regression_decision["decision"] == "promote"
    )
    composite_gate = write_composite_gate(
        heldout_gate=heldout_gate,
        regression_gate=regression_gate,
        decision="promote" if should_promote else "reject",
    )
    summary["steps"].append(
        {
            "name": "composite_gate",
            "gate": str(composite_gate),
            "decision": read_json(composite_gate)["decision"],
        }
    )
    if should_promote:
        promoted = promote_candidate_version(candidate=candidate, gate_path=composite_gate)
        summary["status"] = "promoted"
        summary["promoted_harness"] = str(promoted)
    else:
        summary["status"] = "rejected"
        summary["rejection_reason"] = (
            "promotion disabled"
            if not promote
            else "heldout or regression gate rejected candidate"
        )

    path = CYCLES / f"{cycle_id}.json"
    write_json(path, summary)
    return path


def write_composite_gate(*, heldout_gate: Path, regression_gate: Path, decision: str) -> Path:
    heldout = read_json(heldout_gate)
    regression = read_json(regression_gate)
    if heldout.get("candidate_harness") != regression.get("candidate_harness"):
        raise RuntimeError("Cannot compose gates for different candidate harnesses.")
    if heldout.get("baseline_harness") != regression.get("baseline_harness"):
        raise RuntimeError("Cannot compose gates for different baseline harnesses.")
    if heldout.get("candidate_harness_digest") != regression.get("candidate_harness_digest"):
        raise RuntimeError("Cannot compose gates for different candidate behavior digests.")
    decided_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = heldout_gate.parent / f"{heldout['candidate_harness']}-{decided_at}-composite-gate.json"
    write_json(
        path,
        {
            "decision": decision,
            "baseline_harness": heldout["baseline_harness"],
            "candidate_harness": heldout["candidate_harness"],
            "model": heldout.get("model"),
            "benchmark": heldout.get("benchmark"),
            "split": "heldout+regression",
            "baseline_run": heldout.get("baseline_run"),
            "candidate_run": heldout.get("candidate_run"),
            "pass_rate_delta": heldout.get("pass_rate_delta"),
            "candidate_harness_digest": heldout.get("candidate_harness_digest"),
            "heldout_gate": str(heldout_gate),
            "regression_gate": str(regression_gate),
            "heldout_baseline_run": heldout.get("baseline_run"),
            "heldout_candidate_run": heldout.get("candidate_run"),
            "regression_baseline_run": regression.get("baseline_run"),
            "regression_candidate_run": regression.get("candidate_run"),
            "heldout_decision": heldout.get("decision"),
            "regression_decision": regression.get("decision"),
            "heldout_pass_rate_delta": heldout.get("pass_rate_delta"),
            "regression_pass_rate_delta": regression.get("pass_rate_delta"),
            "rationale": (
                "Heldout and regression gates both passed."
                if decision == "promote"
                else "Heldout or regression gate rejected candidate, or promotion disabled."
            ),
        },
    )
    return path
