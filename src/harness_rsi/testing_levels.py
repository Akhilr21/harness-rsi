from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.adapter_importers import import_review_output, source_profile_output
from harness_rsi.benchmarks import (
    REQUIRED_SPLITS,
    benchmark_dir,
    build_adapter_report,
    build_coverage_report,
    digest_payload,
    read_jsonl_with_path,
    source_benchmark_path,
)
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import CYCLES, GATES, PROPOSALS, RUNS


LEVEL_DEFINITIONS = [
    {
        "id": "L0",
        "name": "Source and import provenance",
        "requirement": "Source profile or import-review artifacts identify where benchmark rows came from.",
    },
    {
        "id": "L1",
        "name": "Benchmark materialized",
        "requirement": "Manifest and train, heldout, and regression task splits exist in the local eval environment.",
    },
    {
        "id": "L2",
        "name": "Run evidence",
        "requirement": "Train, heldout, and regression runs exist with results, traces, and harness snapshots.",
    },
    {
        "id": "L3",
        "name": "Gate evidence",
        "requirement": "Heldout and regression gates compare Hn and Hn+1 under the fixed-model contract.",
    },
    {
        "id": "L4",
        "name": "Cycle and composite proof",
        "requirement": "A cycle links train proposal evidence, split isolation, child gates, and composite decision.",
    },
    {
        "id": "L5",
        "name": "Repeated-cycle stability",
        "requirement": "A stability report summarizes repeated Hn to Hn+1 attempts.",
    },
]


def write_testing_levels_report(benchmark: str) -> Path:
    report = build_testing_levels_report(benchmark)
    path = benchmark_dir(benchmark) / "testing_levels.json"
    write_json(path, report)
    return path


def build_testing_levels_report(benchmark: str) -> dict[str, Any]:
    root = benchmark_dir(benchmark)
    if not root.exists():
        raise RuntimeError(f"Benchmark not found: {root}")
    levels = [
        source_provenance_level(benchmark),
        materialized_level(root),
        run_evidence_level(benchmark),
        gate_evidence_level(benchmark),
        cycle_composite_level(benchmark),
        stability_level(benchmark),
    ]
    summary = summarize_levels(levels)
    report = {
        "benchmark": benchmark,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "report_only": True,
        "promotion_semantics_changed": False,
        "promotion_evidence": False,
        "levels": levels,
        "summary": summary,
        "external_adapter_boundary": external_adapter_boundary(benchmark, root),
        "frontier_model_boundary": frontier_model_boundary(benchmark),
        "world_model_boundary": world_model_boundary(root),
    }
    report["testing_levels_digest"] = digest_payload(
        {
            "benchmark": benchmark,
            "levels": levels,
            "summary": summary,
            "external_adapter_boundary": report["external_adapter_boundary"],
            "frontier_model_boundary": report["frontier_model_boundary"],
            "world_model_boundary": report["world_model_boundary"],
            "read_only": True,
            "promotion_semantics_changed": False,
        }
    )
    return report


def source_provenance_level(benchmark: str) -> dict[str, Any]:
    definition = level_definition("L0")
    evidence = []
    missing = []
    observations = []
    source = source_profile_output(benchmark)
    review = import_review_output(benchmark)
    resolved_source = source_benchmark_path(benchmark)

    if source.exists():
        evidence.append({"type": "source_profile", "path": str(source)})
        import_report = source / "import_report.json"
        manifest = source / "manifest.json"
        if import_report.exists():
            report = read_json(import_report)
            evidence.append(
                {
                    "type": "import_report",
                    "path": str(import_report),
                    "status": report.get("status"),
                    "rejected_row_count": report.get("rejected_row_count"),
                    "import_report_digest": report.get("import_report_digest"),
                }
            )
        if manifest.exists():
            manifest_payload = read_json(manifest)
            evidence.append(
                {
                    "type": "source_manifest",
                    "path": str(manifest),
                    "suite_version": manifest_payload.get("suite_version"),
                    "suite_digest": manifest_payload.get("suite_digest"),
                }
            )
    elif resolved_source.exists():
        evidence.append({"type": "packaged_source_profile", "path": str(resolved_source)})
    else:
        missing.append("source profile or packaged benchmark source")

    if review.exists():
        review_report = review / "import_review.json"
        evidence.append({"type": "import_review", "path": str(review_report)})
        observations.append("Review-only import artifact exists.")

    status = "pass" if evidence and not missing else "missing"
    return level(definition, status=status, evidence=evidence, missing=missing, observations=observations)


def materialized_level(root: Path) -> dict[str, Any]:
    definition = level_definition("L1")
    manifest_path = root / "manifest.json"
    missing = []
    evidence: list[dict[str, Any]] = []
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        evidence.append(
            {
                "type": "manifest",
                "path": str(manifest_path),
                "suite_version": manifest.get("suite_version"),
                "suite_digest": manifest.get("suite_digest"),
            }
        )
    else:
        missing.append("manifest.json")

    split_counts = {}
    for split in REQUIRED_SPLITS:
        split_path = root / f"{split}.jsonl"
        if not split_path.exists():
            missing.append(f"{split}.jsonl")
            split_counts[split] = 0
            continue
        rows = read_jsonl_with_path(split_path)
        split_counts[split] = len(rows)
        if rows:
            evidence.append(
                {"type": "split", "split": split, "path": str(split_path), "tasks": len(rows)}
            )
        else:
            missing.append(f"{split}.jsonl has no tasks")

    coverage_path = root / "coverage.json"
    if coverage_path.exists():
        stored = read_json(coverage_path)
        current = build_coverage_report(str(root.name))
        evidence.append(
            {
                "type": "coverage_report",
                "path": str(coverage_path),
                "coverage_digest": stored.get("coverage_digest"),
                "current_coverage_digest": current.get("coverage_digest"),
                "coverage_policy_digest": current.get("coverage_policy_digest"),
            }
        )
        if stored.get("coverage_digest") != current.get("coverage_digest"):
            missing.append("fresh coverage digest must match stored coverage.json")

    status = "pass" if not missing else "missing"
    return level(
        definition,
        status=status,
        evidence=evidence,
        missing=missing,
        observations=[f"split_counts={split_counts}"],
    )


def run_evidence_level(benchmark: str) -> dict[str, Any]:
    definition = level_definition("L2")
    runs_by_split = {split: runs_for(benchmark=benchmark, split=split) for split in REQUIRED_SPLITS}
    evidence = []
    missing = []
    for split in REQUIRED_SPLITS:
        runs = runs_by_split[split]
        if not runs:
            missing.append(f"{split} run")
            continue
        evidence.append(runs[-1])
    train_run_ids = {run["run_id"] for run in runs_by_split["train"]}
    proposal = latest_proposal_for_runs(train_run_ids)
    if proposal:
        evidence.append(proposal)
    else:
        missing.append("proposal sourced from train run")
    status = "pass" if not missing else ("review" if evidence else "missing")
    return level(
        definition,
        status=status,
        evidence=evidence,
        missing=missing,
        observations=[
            f"{split}_runs={len(runs_by_split[split])}" for split in REQUIRED_SPLITS
        ],
    )


def gate_evidence_level(benchmark: str) -> dict[str, Any]:
    definition = level_definition("L3")
    evidence = []
    missing = []
    observations = []
    review_needed = False
    for split in ("heldout", "regression"):
        gates = gates_for(benchmark=benchmark, split=split)
        if not gates:
            missing.append(f"{split} gate")
            observations.append(f"{split}_gates=0")
            continue
        latest = gates[-1]
        evidence.append(gate_evidence(latest))
        observations.extend(
            [
                f"{split}_decision={latest.get('decision')}",
                f"{split}_pass_rate_delta={latest.get('pass_rate_delta')}",
                f"{split}_environment_failures={len(latest.get('environment_failures', []))}",
                f"{split}_coverage_failures={len(latest.get('coverage_failures', []))}",
                f"{split}_efficiency_failures={len(latest.get('efficiency_failures', []))}",
            ]
        )
        if latest.get("decision") != "promote":
            review_needed = True
            missing.append(f"{split} gate decision is {latest.get('decision')}")
    status = "pass" if not missing and not review_needed else ("review" if evidence else "missing")
    return level(definition, status=status, evidence=evidence, missing=missing, observations=observations)


def cycle_composite_level(benchmark: str) -> dict[str, Any]:
    definition = level_definition("L4")
    cycles = cycles_for(benchmark)
    composite_gates = gates_for(benchmark=benchmark, split="heldout+regression")
    if not cycles and not composite_gates:
        return level(
            definition,
            status="missing",
            evidence=[],
            missing=["cycle summary", "composite gate", "split-isolation audit"],
            observations=["No cycle or composite gate found."],
        )

    evidence = []
    missing = []
    observations = []
    if cycles:
        latest_cycle = cycles[-1]
        evidence.append(
            {
                "type": "cycle",
                "path": latest_cycle["path"],
                "id": latest_cycle.get("id"),
                "status": latest_cycle.get("status"),
                "decision_artifact": latest_cycle.get("decision_artifact"),
            }
        )
        observations.append(f"cycle_status={latest_cycle.get('status')}")
    else:
        missing.append("cycle summary")

    if composite_gates:
        latest_gate = composite_gates[-1]
        evidence.append(gate_evidence(latest_gate))
        split_audit = latest_gate.get("split_isolation_audit")
        split_audit_status = None
        split_audit_exists = False
        if split_audit:
            split_audit_path = Path(str(split_audit))
            split_audit_exists = split_audit_path.exists()
            if split_audit_exists:
                split_audit_status = read_json(split_audit_path).get("status")
        observations.extend(
            [
                f"composite_decision={latest_gate.get('decision')}",
                f"heldout_decision={latest_gate.get('heldout_decision')}",
                f"regression_decision={latest_gate.get('regression_decision')}",
                f"split_isolation_audit_exists={split_audit_exists}",
                f"split_isolation_status={split_audit_status}",
            ]
        )
        if latest_gate.get("decision") != "promote":
            missing.append(f"composite gate decision is {latest_gate.get('decision')}")
        if split_audit_status != "pass":
            missing.append("passing split-isolation audit")
    else:
        missing.extend(["composite gate", "split-isolation audit"])

    status = "pass" if not missing else "review"
    return level(definition, status=status, evidence=evidence, missing=missing, observations=observations)


def stability_level(benchmark: str) -> dict[str, Any]:
    definition = level_definition("L5")
    reports = stability_reports_for(benchmark)
    if not reports:
        return level(
            definition,
            status="missing",
            evidence=[],
            missing=["stability report"],
            observations=["Run `experiment stability` to test repeated Hn to Hn+1 attempts."],
        )
    latest = reports[-1]
    status = "pass" if latest.get("status") == "pass" else "review"
    missing = [] if status == "pass" else [f"stability status is {latest.get('status')}"]
    observations = [
        f"validation_status={latest.get('validation_status')}",
        f"promotion_status={latest.get('promotion_status')}",
        f"completed_cycles={latest.get('completed_cycles')}",
        f"total_failures={latest.get('rollup', {}).get('total_failures')}",
    ]
    return level(
        definition,
        status=status,
        evidence=[
            {
                "type": "stability_report",
                "path": latest["path"],
                "id": latest.get("id"),
                "stability_digest": latest.get("stability_digest"),
            }
        ],
        missing=missing,
        observations=observations,
    )


def external_adapter_boundary(benchmark: str, root: Path) -> dict[str, Any]:
    report = build_adapter_report(benchmark)
    task_count = int(report.get("external_adapter_task_count", 0))
    report_path = root / "adapter_report.json"
    if task_count == 0:
        return {
            "status": "not_applicable",
            "external_adapter_task_count": 0,
            "note": "Benchmark has no external adapter tasks.",
        }
    status = "pass" if report_path.exists() and report.get("status") == "pass" else "review"
    return {
        "status": status,
        "external_adapter_task_count": task_count,
        "adapter_report_path": str(report_path) if report_path.exists() else None,
        "adapter_report_digest": report.get("adapter_report_digest"),
        "kind_counts": report.get("kind_counts", {}),
        "metadata_failure_count": len(report.get("metadata_failures", [])),
        "read_only": report.get("read_only"),
        "note": "External adapter evidence is provenance-only until consumed by run/gate artifacts.",
    }


def frontier_model_boundary(benchmark: str) -> dict[str, Any]:
    runs = runs_for(benchmark=benchmark)
    models = sorted({str(run.get("model")) for run in runs if run.get("model")})
    usage_sources = sorted({str(run.get("usage_source")) for run in runs if run.get("usage_source")})
    missing_cost = sum(1 for run in runs if run.get("cost_usd") is None)
    return {
        "fixed_model_required": True,
        "observed_models": models,
        "usage_sources": usage_sources,
        "runs_missing_cost_usd": missing_cost,
        "note": (
            "Harness-level improvement claims require Hn and Hn+1 to use the same "
            "pinned model; provider/cost metrics remain review-only when usage is not collected."
        ),
    }


def world_model_boundary(root: Path) -> dict[str, Any]:
    split_counts = {}
    static_count = 0
    families: set[str] = set()
    for split in REQUIRED_SPLITS:
        path = root / f"{split}.jsonl"
        if not path.exists():
            split_counts[split] = 0
            continue
        rows = read_jsonl_with_path(path)
        count = sum(1 for row in rows if row.get("environment") == "world_model_static")
        split_counts[split] = count
        static_count += count
        families.update(
            str(row.get("family"))
            for row in rows
            if row.get("environment") == "world_model_static" and row.get("family")
        )
    status = "static_trace_only" if static_count else "none"
    return {
        "status": status,
        "static_world_model_task_count": static_count,
        "split_counts": split_counts,
        "families": sorted(families),
        "live_simulator_adapter_present": False,
        "note": (
            "Decart/Oasis-style coverage is currently static trace pressure only; "
            "live simulator adapters need separate replay, reset, intervention, and digest contracts."
            if static_count
            else "No static or live world-model tasks detected for this benchmark."
        ),
    }


def summarize_levels(levels: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for item in levels:
        status = str(item["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    blocking = [item["id"] for item in levels if item["status"] in {"missing", "review"}]
    return {
        "level_count": len(levels),
        "status_counts": {status: status_counts[status] for status in sorted(status_counts)},
        "blocking_levels": blocking,
        "promotion_ready": not blocking,
    }


def level_definition(level_id: str) -> dict[str, str]:
    for item in LEVEL_DEFINITIONS:
        if item["id"] == level_id:
            return item
    raise RuntimeError(f"Unknown testing level: {level_id}")


def level(
    definition: dict[str, str],
    *,
    status: str,
    evidence: list[dict[str, Any]],
    missing: list[str],
    observations: list[str],
) -> dict[str, Any]:
    return {
        **definition,
        "status": status,
        "evidence": evidence,
        "missing": missing,
        "observations": observations,
    }


def runs_for(benchmark: str, split: str | None = None) -> list[dict[str, Any]]:
    if not RUNS.exists():
        return []
    runs = []
    for run_dir in sorted(path for path in RUNS.iterdir() if path.is_dir()):
        results_path = run_dir / "results.json"
        snapshot_path = run_dir / "harness.snapshot.json"
        trace_path = run_dir / "trace.jsonl"
        if not results_path.exists():
            continue
        results = read_json(results_path)
        metadata = results.get("metadata", {})
        if metadata.get("benchmark") != benchmark:
            continue
        if split and metadata.get("split") != split:
            continue
        snapshot = read_json(snapshot_path) if snapshot_path.exists() else {}
        usage = results.get("usage", {})
        missing_files = [
            path.name
            for path in (results_path, snapshot_path, trace_path)
            if not path.exists()
        ]
        runs.append(
            {
                "type": "run",
                "path": str(run_dir),
                "run_id": results.get("run_id", run_dir.name),
                "split": metadata.get("split"),
                "harness": metadata.get("harness"),
                "model": snapshot.get("model"),
                "task_digest": results.get("task_digest"),
                "harness_behavior_digest": results.get("harness_behavior_digest"),
                "usage_source": usage.get("source"),
                "cost_usd": results.get("metrics", {}).get("cost_usd"),
                "missing_files": missing_files,
            }
        )
    return runs


def latest_proposal_for_runs(run_ids: set[Any]) -> dict[str, Any] | None:
    if not PROPOSALS.exists():
        return None
    proposals = []
    for path in sorted(PROPOSALS.glob("*.json")):
        proposal = read_json(path)
        if proposal.get("source_run") not in run_ids:
            continue
        proposals.append(
            {
                "type": "proposal",
                "path": str(path),
                "id": proposal.get("id"),
                "source_run": proposal.get("source_run"),
                "expected_metric": proposal.get("expected_metric"),
            }
        )
    return proposals[-1] if proposals else None


def gates_for(benchmark: str, split: str) -> list[dict[str, Any]]:
    if not GATES.exists():
        return []
    gates = []
    for path in sorted(GATES.glob("*.json")):
        gate = read_json(path)
        if gate.get("benchmark") != benchmark or gate.get("split") != split:
            continue
        gates.append({"path": str(path), **gate})
    return gates


def gate_evidence(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "gate",
        "path": gate.get("path"),
        "decision": gate.get("decision"),
        "split": gate.get("split"),
        "baseline_harness": gate.get("baseline_harness"),
        "candidate_harness": gate.get("candidate_harness"),
        "model": gate.get("model"),
        "suite_digest": gate.get("suite_digest"),
        "coverage_digest": gate.get("coverage_digest"),
    }


def cycles_for(benchmark: str) -> list[dict[str, Any]]:
    if not CYCLES.exists():
        return []
    cycles = []
    for path in sorted(CYCLES.glob("cycle-*.json")):
        payload = read_json(path)
        if payload.get("benchmark") != benchmark:
            continue
        cycles.append({"path": str(path), **payload})
    return cycles


def stability_reports_for(benchmark: str) -> list[dict[str, Any]]:
    if not CYCLES.exists():
        return []
    reports = []
    for path in sorted(CYCLES.glob("stability-*.json")):
        report = read_json(path)
        if report.get("kind") != "local_cycle_stability":
            continue
        if report.get("benchmark") != benchmark:
            continue
        reports.append({"path": str(path), **report})
    return reports
