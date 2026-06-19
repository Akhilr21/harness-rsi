from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import digest_payload, gate_candidate, harness_path, run_benchmark
from harness_rsi.improve import propose_patch
from harness_rsi.io import read_json, read_jsonl, write_json
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

    split_audit = write_split_isolation_audit(
        cycle_id=cycle_id,
        proposal_path=proposal,
        train_run=train_run.run_dir,
        heldout_parent_run=heldout_parent.run_dir,
        heldout_candidate_run=heldout_candidate.run_dir,
        regression_parent_run=regression_parent.run_dir,
        regression_candidate_run=regression_candidate.run_dir,
        heldout_gate=heldout_gate,
        regression_gate=regression_gate,
    )
    split_audit_report = read_json(split_audit)
    summary["steps"].append(
        {
            "name": "split_isolation_audit",
            "audit": str(split_audit),
            "status": split_audit_report["status"],
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
        split_isolation_audit=split_audit,
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


def run_experiment_stability(
    *,
    parent: str,
    candidate_prefix: str,
    cycles: int,
    benchmark: str,
    model: str | None,
    reasoning_effort: str,
    mock: bool,
    min_heldout_delta: float,
    max_regression_drop: float,
    promote: bool,
    first_candidate_index: int | None = None,
) -> Path:
    if cycles < 1:
        raise RuntimeError("cycles must be greater than or equal to 1.")
    if not candidate_prefix:
        raise RuntimeError("candidate_prefix must be non-empty.")
    next_index = (
        first_candidate_index
        if first_candidate_index is not None
        else candidate_index_after_parent(parent, candidate_prefix)
    )
    if next_index < 0:
        raise RuntimeError("first_candidate_index must be greater than or equal to 0.")

    stability_id = datetime.now(timezone.utc).strftime("stability-%Y%m%dT%H%M%S%fZ")
    current_parent = parent
    cycle_summaries = []
    for ordinal in range(1, cycles + 1):
        candidate = f"{candidate_prefix}{next_index}"
        cycle_path = run_experiment_cycle(
            parent=current_parent,
            candidate=candidate,
            benchmark=benchmark,
            model=model,
            reasoning_effort=reasoning_effort,
            mock=mock,
            min_heldout_delta=min_heldout_delta,
            max_regression_drop=max_regression_drop,
            promote=promote,
        )
        cycle_summary = summarize_cycle_for_stability(
            cycle_path=cycle_path,
            ordinal=ordinal,
            parent=current_parent,
            candidate=candidate,
        )
        cycle_summaries.append(cycle_summary)
        if cycle_summary["cycle_status"] == "promoted":
            current_parent = candidate
        next_index += 1

    totals = summarize_stability_totals(cycle_summaries)
    rollup = summarize_stability_rollup(cycle_summaries, totals)
    failures = find_stability_failures(cycle_summaries, rollup)
    validation_status = "pass" if len(cycle_summaries) == cycles and not failures else "fail"
    if promote:
        promotion_status = "pass" if totals["promoted"] == cycles else "partial"
    else:
        promotion_status = "not_requested"
    report = {
        "id": stability_id,
        "kind": "local_cycle_stability",
        "parent_start": parent,
        "final_parent": current_parent,
        "candidate_prefix": candidate_prefix,
        "first_candidate_index": (
            first_candidate_index
            if first_candidate_index is not None
            else candidate_index_after_parent(parent, candidate_prefix)
        ),
        "requested_cycles": cycles,
        "completed_cycles": len(cycle_summaries),
        "benchmark": benchmark,
        "mock": mock,
        "promote": promote,
        "min_heldout_delta": min_heldout_delta,
        "max_regression_drop": max_regression_drop,
        "validation_status": validation_status,
        "promotion_status": promotion_status,
        "status": (
            "pass"
            if validation_status == "pass"
            and (promotion_status in {"pass", "not_requested"})
            else "review"
        ),
        "gate_contract": summarize_stability_gate_contract(cycle_summaries),
        "rollup": rollup,
        "failures": failures,
        "totals": totals,
        "cycles": cycle_summaries,
    }
    report["stability_digest"] = digest_payload(report)
    path = CYCLES / f"{stability_id}.json"
    write_json(path, report)
    return path


def candidate_index_after_parent(parent: str, candidate_prefix: str) -> int:
    if parent.startswith(candidate_prefix):
        suffix = parent[len(candidate_prefix) :]
        if suffix.isdigit():
            return int(suffix) + 1
    return 1


def summarize_cycle_for_stability(
    *,
    cycle_path: Path,
    ordinal: int,
    parent: str,
    candidate: str,
) -> dict[str, Any]:
    cycle = read_json(cycle_path)
    heldout_step = find_step(cycle, "heldout_gate")
    regression_step = find_step(cycle, "regression_gate")
    composite_step = find_step(cycle, "composite_gate")
    split_step = find_step(cycle, "split_isolation_audit")
    heldout_gate = read_json(Path(heldout_step["gate"]))
    regression_gate = read_json(Path(regression_step["gate"]))
    split_audit = read_json(Path(split_step["audit"]))
    heldout = summarize_gate_for_stability(
        gate=heldout_gate,
        gate_path=Path(heldout_step["gate"]),
    )
    regression = summarize_gate_for_stability(
        gate=regression_gate,
        gate_path=Path(regression_step["gate"]),
    )
    split_isolation = {
        "audit": split_step["audit"],
        "status": split_audit.get("status"),
        "violations": len(split_audit.get("violations", [])),
        "split_isolation_digest": split_audit.get("split_isolation_digest"),
    }
    validation_passed = (
        heldout_gate.get("decision") == "promote"
        and regression_gate.get("decision") == "promote"
        and split_audit.get("status") == "pass"
    )
    failure_counts = {
        "environment": heldout["environment_failures"] + regression["environment_failures"],
        "coverage": heldout["coverage_failures"] + regression["coverage_failures"],
        "waiver_review": (
            heldout["waiver_review_failures"] + regression["waiver_review_failures"]
        ),
        "efficiency": heldout["efficiency_failures"] + regression["efficiency_failures"],
        "split_isolation": split_isolation["violations"],
    }
    return {
        "ordinal": ordinal,
        "cycle_id": cycle["id"],
        "cycle_path": str(cycle_path),
        "parent": parent,
        "candidate": candidate,
        "cycle_status": cycle["status"],
        "validation_passed": validation_passed,
        "promoted_harness": cycle.get("promoted_harness"),
        "decision_artifact": cycle.get("decision_artifact"),
        "suite_version": cycle.get("suite_version"),
        "suite_digest": cycle.get("suite_digest"),
        "coverage_digest": cycle.get("coverage_digest"),
        "decisions": {
            "heldout": heldout_gate.get("decision"),
            "regression": regression_gate.get("decision"),
            "composite": read_json(Path(composite_step["gate"])).get("decision"),
        },
        "failure_counts": failure_counts,
        "heldout": heldout,
        "regression": regression,
        "split_isolation": split_isolation,
        "composite_gate": composite_step["gate"],
    }


def find_step(cycle: dict[str, Any], name: str) -> dict[str, Any]:
    for step in cycle.get("steps", []):
        if step.get("name") == name:
            return step
    raise RuntimeError(f"Cycle {cycle.get('id')} is missing step {name}.")


def summarize_gate_for_stability(*, gate: dict[str, Any], gate_path: Path) -> dict[str, Any]:
    waiver_review = gate.get("waiver_review") or {}
    return {
        "gate": str(gate_path),
        "decision": gate.get("decision"),
        "pass_rate_delta": gate.get("pass_rate_delta"),
        "attempt_delta": gate.get("metric_deltas", {}).get("attempts"),
        "tool_call_delta": gate.get("metric_deltas", {}).get("tool_calls"),
        "duration_ms_delta": gate.get("metric_deltas", {}).get("duration_ms"),
        "cost_usd_delta": gate.get("metric_deltas", {}).get("cost_usd"),
        "environment_failures": len(gate.get("environment_failures", [])),
        "coverage_failures": len(gate.get("coverage_failures", [])),
        "waiver_review_failures": len(gate.get("waiver_review_failures", [])),
        "efficiency_failures": len(gate.get("efficiency_failures", [])),
        "coverage_policy_digest": gate.get("coverage_policy_digest"),
        "waiver_review_policy": gate.get("waiver_review_policy"),
        "waiver_review_as_of": waiver_review.get("as_of"),
        "waiver_review_due_count": waiver_review.get("review_due_count"),
        "active_missing_waivers": waiver_review.get("active_missing_count"),
        "efficiency_thresholds": gate.get("efficiency_thresholds"),
    }


def summarize_stability_totals(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "promoted": sum(1 for cycle in cycles if cycle["cycle_status"] == "promoted"),
        "rejected": sum(1 for cycle in cycles if cycle["cycle_status"] == "rejected"),
        "validation_failures": sum(1 for cycle in cycles if not cycle["validation_passed"]),
        "heldout_gate_rejects": count_gate_rejects(cycles, "heldout"),
        "regression_gate_rejects": count_gate_rejects(cycles, "regression"),
        "split_isolation_failures": sum(
            1 for cycle in cycles if cycle["split_isolation"]["status"] != "pass"
        ),
        "environment_failures": sum_gate_count(cycles, "environment_failures"),
        "coverage_failures": sum_gate_count(cycles, "coverage_failures"),
        "waiver_review_failures": sum_gate_count(cycles, "waiver_review_failures"),
        "efficiency_failures": sum_gate_count(cycles, "efficiency_failures"),
    }


def summarize_stability_gate_contract(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    if not cycles:
        return {}
    first = cycles[0]
    return {
        "coverage_required": bool(first["coverage_digest"]),
        "split_isolation_required": True,
        "heldout": {
            "coverage_policy_digest": first["heldout"].get("coverage_policy_digest"),
            "efficiency_thresholds": first["heldout"].get("efficiency_thresholds"),
            "waiver_review_policy": first["heldout"].get("waiver_review_policy"),
        },
        "regression": {
            "coverage_policy_digest": first["regression"].get("coverage_policy_digest"),
            "efficiency_thresholds": first["regression"].get("efficiency_thresholds"),
            "waiver_review_policy": first["regression"].get("waiver_review_policy"),
        },
    }


def summarize_stability_rollup(
    cycles: list[dict[str, Any]],
    totals: dict[str, int],
) -> dict[str, Any]:
    total_failures = (
        totals["validation_failures"]
        + totals["environment_failures"]
        + totals["coverage_failures"]
        + totals["waiver_review_failures"]
        + totals["efficiency_failures"]
        + totals["split_isolation_failures"]
    )
    return {
        "all_cycles_passed": all(cycle["validation_passed"] for cycle in cycles),
        "suite_digest_stable": one_unique_value(cycle.get("suite_digest") for cycle in cycles),
        "coverage_digest_stable": one_unique_value(
            cycle.get("coverage_digest") for cycle in cycles
        ),
        "coverage_policy_digest_stable": one_unique_value(
            gate.get("coverage_policy_digest")
            for cycle in cycles
            for gate in (cycle["heldout"], cycle["regression"])
        ),
        "waiver_review_policy_stable": one_unique_value(
            digest_payload(gate.get("waiver_review_policy"))
            for cycle in cycles
            for gate in (cycle["heldout"], cycle["regression"])
        ),
        "total_failures": total_failures,
    }


def one_unique_value(values: Any) -> bool:
    unique = {value for value in values if value is not None}
    return len(unique) <= 1


def find_stability_failures(
    cycles: list[dict[str, Any]],
    rollup: dict[str, Any],
) -> list[dict[str, Any]]:
    failures = []
    for cycle in cycles:
        if cycle["validation_passed"]:
            continue
        failures.append(
            {
                "type": "cycle_validation_failed",
                "cycle_id": cycle["cycle_id"],
                "candidate": cycle["candidate"],
                "decisions": cycle["decisions"],
                "failure_counts": cycle["failure_counts"],
            }
        )
    for key in (
        "suite_digest_stable",
        "coverage_digest_stable",
        "coverage_policy_digest_stable",
        "waiver_review_policy_stable",
    ):
        if not rollup.get(key):
            failures.append({"type": key, "status": "failed"})
    return failures


def count_gate_rejects(cycles: list[dict[str, Any]], split: str) -> int:
    return sum(1 for cycle in cycles if cycle[split]["decision"] != "promote")


def sum_gate_count(cycles: list[dict[str, Any]], field: str) -> int:
    return sum(cycle["heldout"][field] + cycle["regression"][field] for cycle in cycles)


def write_split_isolation_audit(
    *,
    cycle_id: str,
    proposal_path: Path,
    train_run: Path,
    heldout_parent_run: Path,
    heldout_candidate_run: Path,
    regression_parent_run: Path,
    regression_candidate_run: Path,
    heldout_gate: Path | None = None,
    regression_gate: Path | None = None,
) -> Path:
    audit = build_split_isolation_audit(
        proposal_path=proposal_path,
        train_run=train_run,
        heldout_parent_run=heldout_parent_run,
        heldout_candidate_run=heldout_candidate_run,
        regression_parent_run=regression_parent_run,
        regression_candidate_run=regression_candidate_run,
        heldout_gate=heldout_gate,
        regression_gate=regression_gate,
    )
    path = CYCLES / f"{cycle_id}-split-isolation.json"
    write_json(path, audit)
    if audit["status"] != "pass":
        raise RuntimeError(f"Split isolation audit failed: {path}")
    return path


def build_split_isolation_audit(
    *,
    proposal_path: Path,
    train_run: Path,
    heldout_parent_run: Path,
    heldout_candidate_run: Path,
    regression_parent_run: Path,
    regression_candidate_run: Path,
    heldout_gate: Path | None = None,
    regression_gate: Path | None = None,
) -> dict[str, Any]:
    proposal = read_json(proposal_path)
    train = run_split_identity(train_run)
    heldout_parent = run_split_identity(heldout_parent_run)
    heldout_candidate = run_split_identity(heldout_candidate_run)
    regression_parent = run_split_identity(regression_parent_run)
    regression_candidate = run_split_identity(regression_candidate_run)
    proposal_evidence = proposal.get("evidence") if isinstance(proposal.get("evidence"), dict) else {}
    proposal_evidence_task_ids = sorted(
        str(item.get("task_id"))
        for item in proposal_evidence.get("results", [])
        if item.get("task_id")
    )
    heldout_task_ids = sorted(set(heldout_parent["task_ids"]) | set(heldout_candidate["task_ids"]))
    regression_task_ids = sorted(
        set(regression_parent["task_ids"]) | set(regression_candidate["task_ids"])
    )
    forbidden_references = forbidden_validation_references(
        heldout_parent,
        heldout_candidate,
        regression_parent,
        regression_candidate,
        heldout_gate=heldout_gate,
        regression_gate=regression_gate,
    )
    leaked_references = find_forbidden_references(proposal, forbidden_references)
    checks = [
        split_check(
            "proposal_source_matches_train_run",
            proposal.get("source_run") == train["run_id"],
            {
                "proposal_source_run": proposal.get("source_run"),
                "train_run": train["run_id"],
            },
        ),
        split_check(
            "proposal_source_split_is_train",
            train["split"] == "train",
            {"source_split": train["split"]},
        ),
        split_check(
            "proposal_embedded_evidence_is_train",
            not proposal_evidence or proposal_evidence.get("metadata", {}).get("split") == "train",
            {"embedded_split": proposal_evidence.get("metadata", {}).get("split")},
        ),
        split_check(
            "proposal_embedded_task_ids_subset_of_train",
            set(proposal_evidence_task_ids).issubset(set(train["task_ids"])),
            {
                "embedded_task_ids": proposal_evidence_task_ids,
                "train_task_ids": train["task_ids"],
            },
        ),
        split_check(
            "proposal_has_no_validation_references",
            not leaked_references,
            {"leaked_references": leaked_references},
        ),
        split_check(
            "train_disjoint_from_heldout_validation",
            set(train["task_ids"]).isdisjoint(heldout_task_ids),
            {"overlap": sorted(set(train["task_ids"]) & set(heldout_task_ids))},
        ),
        split_check(
            "train_disjoint_from_regression_validation",
            set(train["task_ids"]).isdisjoint(regression_task_ids),
            {"overlap": sorted(set(train["task_ids"]) & set(regression_task_ids))},
        ),
        split_check(
            "heldout_parent_candidate_task_ids_match",
            heldout_parent["task_ids"] == heldout_candidate["task_ids"],
            {
                "parent_task_ids": heldout_parent["task_ids"],
                "candidate_task_ids": heldout_candidate["task_ids"],
            },
        ),
        split_check(
            "regression_parent_candidate_task_ids_match",
            regression_parent["task_ids"] == regression_candidate["task_ids"],
            {
                "parent_task_ids": regression_parent["task_ids"],
                "candidate_task_ids": regression_candidate["task_ids"],
            },
        ),
        split_check(
            "train_trace_task_ids_subset_of_train_tasks",
            set(train["trace_task_ids"]).issubset(set(train["task_ids"])),
            {
                "trace_task_ids": train["trace_task_ids"],
                "train_task_ids": train["task_ids"],
            },
        ),
        split_check(
            "heldout_trace_task_ids_subset_of_heldout_tasks",
            set(heldout_parent["trace_task_ids"]).issubset(set(heldout_parent["task_ids"]))
            and set(heldout_candidate["trace_task_ids"]).issubset(
                set(heldout_candidate["task_ids"])
            ),
            {
                "parent_trace_task_ids": heldout_parent["trace_task_ids"],
                "candidate_trace_task_ids": heldout_candidate["trace_task_ids"],
            },
        ),
        split_check(
            "regression_trace_task_ids_subset_of_regression_tasks",
            set(regression_parent["trace_task_ids"]).issubset(set(regression_parent["task_ids"]))
            and set(regression_candidate["trace_task_ids"]).issubset(
                set(regression_candidate["task_ids"])
            ),
            {
                "parent_trace_task_ids": regression_parent["trace_task_ids"],
                "candidate_trace_task_ids": regression_candidate["trace_task_ids"],
            },
        ),
        split_check(
            "validation_splits_are_not_train",
            heldout_parent["split"] == heldout_candidate["split"] == "heldout"
            and regression_parent["split"] == regression_candidate["split"] == "regression",
            {
                "heldout_parent_split": heldout_parent["split"],
                "heldout_candidate_split": heldout_candidate["split"],
                "regression_parent_split": regression_parent["split"],
                "regression_candidate_split": regression_candidate["split"],
            },
        ),
    ]
    violations = [check for check in checks if not check["passed"]]
    audit = {
        "status": "fail" if violations else "pass",
        "proposal": str(proposal_path),
        "proposal_source_run": proposal.get("source_run"),
        "proposal_source_split": train["split"],
        "proposal_embedded_evidence_present": bool(proposal_evidence),
        "proposal_embedded_task_ids": proposal_evidence_task_ids,
        "forbidden_validation_references": forbidden_references,
        "leaked_validation_references": leaked_references,
        "train": train,
        "validation": {
            "heldout": {
                "parent": heldout_parent,
                "candidate": heldout_candidate,
                "task_ids": heldout_task_ids,
            },
            "regression": {
                "parent": regression_parent,
                "candidate": regression_candidate,
                "task_ids": regression_task_ids,
            },
        },
        "checks": checks,
        "violations": violations,
    }
    audit["split_isolation_digest"] = split_isolation_digest(audit)
    return audit


def run_split_identity(run_dir: Path) -> dict[str, Any]:
    results = read_json(run_dir / "results.json")
    trace = read_jsonl(run_dir / "trace.jsonl")
    metadata = results.get("metadata", {})
    return {
        "run_id": results.get("run_id", run_dir.name),
        "path": str(run_dir),
        "benchmark": metadata.get("benchmark"),
        "split": metadata.get("split"),
        "harness": metadata.get("harness"),
        "task_digest": results.get("task_digest"),
        "task_ids": sorted(str(item["task_id"]) for item in results.get("results", [])),
        "trace_task_ids": sorted({str(item["task_id"]) for item in trace if item.get("task_id")}),
    }


def split_check(name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": passed, "details": details}


def forbidden_validation_references(
    heldout_parent: dict[str, Any],
    heldout_candidate: dict[str, Any],
    regression_parent: dict[str, Any],
    regression_candidate: dict[str, Any],
    *,
    heldout_gate: Path | None,
    regression_gate: Path | None,
) -> list[str]:
    references = set()
    for run in (heldout_parent, heldout_candidate, regression_parent, regression_candidate):
        references.add(str(run["run_id"]))
        references.add(str(run["path"]))
        references.add(f"{run['path']}/trace.jsonl")
        references.update(str(task_id) for task_id in run["task_ids"])
    for gate in (heldout_gate, regression_gate):
        if gate:
            references.add(str(gate))
    return sorted(reference for reference in references if reference)


def find_forbidden_references(payload: Any, forbidden: list[str]) -> list[str]:
    found: set[str] = set()
    scan_payload_forbidden_references(payload, forbidden, found)
    return sorted(found)


def scan_payload_forbidden_references(payload: Any, forbidden: list[str], found: set[str]) -> None:
    if isinstance(payload, dict):
        for value in payload.values():
            scan_payload_forbidden_references(value, forbidden, found)
        return
    if isinstance(payload, list):
        for value in payload:
            scan_payload_forbidden_references(value, forbidden, found)
        return
    if isinstance(payload, str):
        for reference in forbidden:
            if reference in payload:
                found.add(reference)


def split_isolation_digest(audit: dict[str, Any]) -> str:
    return digest_payload({key: value for key, value in audit.items() if key != "split_isolation_digest"})


def write_composite_gate(
    *,
    heldout_gate: Path,
    regression_gate: Path,
    decision: str,
    split_isolation_audit: Path | None = None,
) -> Path:
    heldout = read_json(heldout_gate)
    regression = read_json(regression_gate)
    split_audit = read_json(split_isolation_audit) if split_isolation_audit else None
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
            "waiver_review_policy": heldout.get("waiver_review_policy"),
            "waiver_review": heldout.get("waiver_review"),
            "split": "heldout+regression",
            "baseline_run": heldout.get("baseline_run"),
            "candidate_run": heldout.get("candidate_run"),
            "pass_rate_delta": heldout.get("pass_rate_delta"),
            "candidate_harness_digest": heldout.get("candidate_harness_digest"),
            "heldout_evaluator_digests": heldout.get("evaluator_digests", []),
            "regression_evaluator_digests": regression.get("evaluator_digests", []),
            "heldout_gate": str(heldout_gate),
            "regression_gate": str(regression_gate),
            "split_isolation_audit": str(split_isolation_audit) if split_isolation_audit else None,
            "split_isolation_digest": (
                split_isolation_digest(split_audit) if split_audit else None
            ),
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
            "heldout_waiver_review": heldout.get("waiver_review"),
            "regression_waiver_review": regression.get("waiver_review"),
            "heldout_waiver_review_failures": heldout.get("waiver_review_failures", []),
            "regression_waiver_review_failures": regression.get("waiver_review_failures", []),
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
        ("waiver_review_policy", "waiver review policies"),
        ("waiver_review", "waiver review evidence"),
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
            "split_isolation_audit": composite.get("split_isolation_audit"),
            "split_isolation_digest": composite.get("split_isolation_digest"),
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
