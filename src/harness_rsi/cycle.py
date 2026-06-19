from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import digest_payload, gate_candidate, harness_path, run_benchmark
from harness_rsi.improve import propose_patch
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import CYCLES, DECISIONS
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
    composite_decision = read_json(composite_gate)
    summary.update(
        {
            "suite_version": composite_decision.get("suite_version"),
            "suite_digest": composite_decision.get("suite_digest"),
            "coverage_digest": composite_decision.get("coverage_digest"),
            "heldout_evaluator_digests": composite_decision.get("heldout_evaluator_digests"),
            "regression_evaluator_digests": composite_decision.get(
                "regression_evaluator_digests"
            ),
        }
    )
    summary["steps"].append(
        {
            "name": "composite_gate",
            "gate": str(composite_gate),
            "decision": composite_decision["decision"],
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
        rejection = write_cycle_rejection(summary=summary, composite_gate=composite_gate)
        summary["decision_artifact"] = str(rejection)

    path = CYCLES / f"{cycle_id}.json"
    write_json(path, summary)
    return path


def write_composite_gate(*, heldout_gate: Path, regression_gate: Path, decision: str) -> Path:
    heldout = read_json(heldout_gate)
    regression = read_json(regression_gate)
    validate_composite_gate_inputs(heldout, regression, decision)
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
            "suite_version": heldout.get("suite_version"),
            "suite_digest": heldout.get("suite_digest"),
            "coverage_digest": heldout.get("coverage_digest"),
            "current_coverage_digest": heldout.get("current_coverage_digest"),
            "coverage_policy_digest": heldout.get("coverage_policy_digest"),
            "split": "heldout+regression",
            "baseline_run": heldout.get("baseline_run"),
            "candidate_run": heldout.get("candidate_run"),
            "pass_rate_delta": heldout.get("pass_rate_delta"),
            "candidate_harness_digest": heldout.get("candidate_harness_digest"),
            "heldout_evaluator_digests": heldout.get("evaluator_digests", []),
            "regression_evaluator_digests": regression.get("evaluator_digests", []),
            "heldout_gate": str(heldout_gate),
            "regression_gate": str(regression_gate),
            "heldout_gate_digest": digest_payload(heldout),
            "regression_gate_digest": digest_payload(regression),
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


def validate_composite_gate_inputs(
    heldout: dict[str, Any],
    regression: dict[str, Any],
    decision: str,
) -> None:
    if heldout.get("split") != "heldout":
        raise RuntimeError("Cannot compose gates unless the first gate is the heldout split.")
    if regression.get("split") != "regression":
        raise RuntimeError("Cannot compose gates unless the second gate is the regression split.")
    for field, label in (
        ("candidate_harness", "candidate harnesses"),
        ("baseline_harness", "baseline harnesses"),
        ("candidate_harness_digest", "candidate behavior digests"),
        ("benchmark", "benchmarks"),
        ("model", "models"),
        ("suite_version", "benchmark suite versions"),
        ("suite_digest", "benchmark suite digests"),
        ("coverage_digest", "coverage digests"),
        ("current_coverage_digest", "current coverage digests"),
        ("coverage_policy_digest", "coverage policy digests"),
    ):
        if heldout.get(field) != regression.get(field):
            raise RuntimeError(f"Cannot compose gates for different {label}.")
    if decision == "promote" and (
        heldout.get("decision") != "promote" or regression.get("decision") != "promote"
    ):
        raise RuntimeError("Cannot promote from a composite gate unless both component gates promote.")


def write_cycle_rejection(*, summary: dict[str, Any], composite_gate: Path) -> Path:
    path = DECISIONS / f"{summary['id']}-rejected.json"
    composite = read_json(composite_gate)
    write_json(
        path,
        {
            "id": summary["id"],
            "decision": "reject",
            "parent": summary["parent"],
            "candidate": summary["candidate"],
            "benchmark": summary["benchmark"],
            "suite_version": composite.get("suite_version"),
            "suite_digest": composite.get("suite_digest"),
            "coverage_digest": composite.get("coverage_digest"),
            "rejection_reason": summary.get("rejection_reason"),
            "proposal": find_step_value(summary, "propose_patch", "proposal"),
            "heldout_gate": composite.get("heldout_gate"),
            "regression_gate": composite.get("regression_gate"),
            "composite_gate": str(composite_gate),
            "score_deltas": {
                "heldout_pass_rate_delta": composite.get("heldout_pass_rate_delta"),
                "regression_pass_rate_delta": composite.get("regression_pass_rate_delta"),
            },
            "metric_deltas": {
                "heldout": read_json(Path(composite["heldout_gate"])).get("metric_deltas", {}),
                "regression": read_json(Path(composite["regression_gate"])).get("metric_deltas", {}),
            },
            "evaluator_digests": {
                "heldout": composite.get("heldout_evaluator_digests", []),
                "regression": composite.get("regression_evaluator_digests", []),
            },
            "steps": summary["steps"],
        },
    )
    return path


def find_step_value(summary: dict[str, Any], step_name: str, key: str) -> Any:
    for step in summary.get("steps", []):
        if step.get("name") == step_name:
            return step.get(key)
    return None
