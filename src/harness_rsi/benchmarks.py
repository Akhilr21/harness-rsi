from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import BENCHMARKS, GATES, HARNESSES

SOURCE_BENCHMARKS = Path("benchmarks")
PACKAGE_BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"
REQUIRED_SPLITS = ("train", "heldout", "regression")


@dataclass(frozen=True)
class BenchmarkRun:
    benchmark: str
    split: str
    harness: str
    run_dir: Path


DEFAULT_SYNTHETIC_BENCHMARK: dict[str, list[dict[str, Any]]] = {
    "train": [
        {
            "id": "kw_extract_objective",
            "environment": "knowledge_work",
            "instruction": "Extract the phrase harness-level RSI from this request.",
            "eval": {"type": "contains", "expected": "harness-level RSI"},
        },
        {
            "id": "coding_failure_signal",
            "environment": "coding_micro",
            "instruction": "A test log says AssertionError: expected 2 got 3. Return the error signal.",
            "eval": {"type": "contains", "expected": "expected 2 got 3"},
        },
        {
            "id": "data_asset_schema",
            "environment": "data_ops",
            "instruction": "Return exactly csv for a comma-separated tabular data asset.",
            "eval": {"type": "exact", "expected": "csv"},
        },
        {
            "id": "tool_policy_disabled",
            "environment": "tool_use",
            "instruction": "Return exactly no-shell when shell access is disabled.",
            "eval": {"type": "exact", "expected": "no-shell"},
        },
    ],
    "heldout": [
        {
            "id": "kw_next_action",
            "environment": "knowledge_work",
            "instruction": "Name the required gate for promoting Hn+1 over Hn.",
            "eval": {"type": "contains", "expected": "heldout"},
        },
        {
            "id": "coding_patch_target",
            "environment": "coding_micro",
            "instruction": "Return the file extension for a Python source patch.",
            "eval": {"type": "exact", "expected": ".py"},
        },
        {
            "id": "customer_support_policy",
            "environment": "customer_support",
            "instruction": "A customer asks for a refund. Return the policy artifact name.",
            "eval": {"type": "contains", "expected": "policy"},
        },
        {
            "id": "world_model_state",
            "environment": "world_model",
            "instruction": "For a simulated world, return the phrase state consistency.",
            "eval": {"type": "contains", "expected": "state consistency"},
        },
    ],
    "regression": [
        {
            "id": "regression_exact_math",
            "environment": "mechanics",
            "instruction": "Return exactly 4.",
            "eval": {"type": "exact", "expected": "4"},
        },
        {
            "id": "regression_trace_word",
            "environment": "mechanics",
            "instruction": "Return a sentence containing trace capture.",
            "eval": {"type": "contains", "expected": "trace capture"},
        },
        {
            "id": "regression_regex_version",
            "environment": "mechanics",
            "instruction": "Return H12.",
            "eval": {"type": "regex", "expected": "^H\\d+$"},
        },
    ],
}


def benchmark_dir(name: str) -> Path:
    return BENCHMARKS / name


def harness_path(name: str) -> Path:
    if name.endswith(".json"):
        return Path(name)
    return HARNESSES / f"{name}.json"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def init_benchmark(name: str = "synthetic", profile: str | None = None) -> Path:
    if profile is None and source_benchmark_path(name).exists():
        profile = name
    if profile and profile != "synthetic":
        return init_source_benchmark(name=name, profile=profile)

    root = benchmark_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    for split, rows in DEFAULT_SYNTHETIC_BENCHMARK.items():
        write_jsonl(root / f"{split}.jsonl", rows)

    h0 = harness_path("H0")
    if not h0.exists():
        write_json(h0, DEFAULT_HARNESS | {"id": "H0", "parent": None})

    manifest = {
        "name": name,
        "splits": sorted(DEFAULT_SYNTHETIC_BENCHMARK),
        "environments": sorted(
            {
                task["environment"]
                for split in DEFAULT_SYNTHETIC_BENCHMARK.values()
                for task in split
            }
        ),
        "baseline_harness": "H0",
    }
    write_json(root / "manifest.json", manifest)
    return root


def init_source_benchmark(*, name: str, profile: str) -> Path:
    source = source_benchmark_path(profile)
    sources = source / "sources"
    if not sources.exists():
        raise RuntimeError(f"Benchmark source profile not found: {source}")

    source_manifest = read_json(source / "manifest.json") if (source / "manifest.json").exists() else {}
    suite_version = str(source_manifest.get("suite_version", profile))
    root = benchmark_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    split_rows: dict[str, list[dict[str, Any]]] = {}
    for split in REQUIRED_SPLITS:
        split_rows[split] = read_source_split(
            sources / split,
            split,
            profile=profile,
            suite_version=suite_version,
        )
        write_jsonl(root / f"{split}.jsonl", split_rows[split])

    h0 = harness_path("H0")
    if not h0.exists():
        write_json(h0, DEFAULT_HARNESS | {"id": "H0", "parent": None})

    gate_policy = read_json(source / "gate_policy.json") if (source / "gate_policy.json").exists() else {}
    manifest = dict(source_manifest)
    manifest.update(
        {
            "name": name,
            "profile": profile,
            "suite_version": suite_version,
            "source_path": str(source),
            "splits": list(REQUIRED_SPLITS),
            "split_counts": {split: len(rows) for split, rows in split_rows.items()},
            "environments": sorted(
                {
                    task.get("environment", "default")
                    for rows in split_rows.values()
                    for task in rows
                }
            ),
            "families": sorted(
                {task["family"] for rows in split_rows.values() for task in rows if "family" in task}
            ),
            "baseline_harness": manifest.get("baseline_harness", "H0"),
        }
    )
    manifest["suite_digest"] = suite_digest(manifest, split_rows, gate_policy)
    write_json(root / "manifest.json", manifest)
    if gate_policy:
        write_json(root / "gate_policy.json", gate_policy)
    write_coverage_report(name)
    return root


def source_benchmark_path(profile: str) -> Path:
    local = SOURCE_BENCHMARKS / profile
    if local.exists():
        return local
    return PACKAGE_BENCHMARKS / profile


def read_source_split(
    split_dir: Path,
    split: str,
    *,
    profile: str,
    suite_version: str,
) -> list[dict[str, Any]]:
    if not split_dir.exists():
        raise RuntimeError(f"Benchmark source split not found: {split_dir}")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(split_dir.glob("*.jsonl")):
        for row in read_jsonl_with_path(path):
            task_id = row.get("id")
            if not task_id:
                raise RuntimeError(f"Task in {path} is missing id.")
            if task_id in seen_ids:
                raise RuntimeError(f"Duplicate task id {task_id} in {split} split.")
            if "instruction" not in row or "eval" not in row:
                raise RuntimeError(f"Task {task_id} in {path} needs instruction and eval.")
            row.setdefault("environment", "default")
            row.setdefault("split", split)
            row.setdefault("suite_version", suite_version)
            row.setdefault("source", f"{profile}/{path.relative_to(source_benchmark_path(profile))}")
            row["evaluator_digest"] = evaluator_digest(row["eval"])
            seen_ids.add(task_id)
            rows.append(row)
    if not rows:
        raise RuntimeError(f"Benchmark source split has no tasks: {split_dir}")
    return rows


def evaluator_digest(evaluator: dict[str, Any]) -> str:
    return digest_payload(evaluator)


def digest_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def suite_digest(
    manifest: dict[str, Any],
    split_rows: dict[str, list[dict[str, Any]]],
    gate_policy: dict[str, Any],
) -> str:
    stable_manifest = {
        key: value
        for key, value in manifest.items()
        if key not in {"source_path", "suite_digest"}
    }
    return digest_payload(
        {
            "manifest": stable_manifest,
            "splits": {split: split_rows[split] for split in REQUIRED_SPLITS},
            "gate_policy": gate_policy,
        }
    )


def benchmark_metadata(benchmark: str) -> dict[str, Any]:
    manifest_path = benchmark_dir(benchmark) / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = read_json(manifest_path)
    metadata = {
        "suite_version": manifest.get("suite_version"),
        "suite_digest": manifest.get("suite_digest"),
        "coverage_digest": read_coverage_digest(benchmark),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def read_coverage_digest(benchmark: str) -> str | None:
    path = benchmark_dir(benchmark) / "coverage.json"
    if not path.exists():
        return None
    return read_json(path).get("coverage_digest")


def read_jsonl_with_path(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid JSONL at {path}:{line_number}: {error}") from error
    return rows


def run_benchmark(
    *,
    benchmark: str,
    split: str,
    harness: str,
    model: str | None,
    mock: bool,
) -> BenchmarkRun:
    tasks_path = benchmark_dir(benchmark) / f"{split}.jsonl"
    config_path = harness_path(harness)
    if not tasks_path.exists():
        raise RuntimeError(f"Benchmark split not found: {tasks_path}")
    if not config_path.exists():
        raise RuntimeError(f"Harness not found: {config_path}")

    run_dir = run_suite(
        tasks_path=tasks_path,
        config_path=config_path,
        model_override=model,
        mock=mock,
        metadata={
            "benchmark": benchmark,
            "split": split,
            "harness": harness,
            **benchmark_metadata(benchmark),
        },
    )
    return BenchmarkRun(benchmark=benchmark, split=split, harness=harness, run_dir=run_dir)


def compare_runs(baseline_run: Path, candidate_run: Path) -> dict[str, Any]:
    baseline = read_json(baseline_run / "results.json")
    candidate = read_json(candidate_run / "results.json")
    baseline_config = read_json(baseline_run / "harness.snapshot.json")
    candidate_config = read_json(candidate_run / "harness.snapshot.json")
    baseline_metadata = baseline.get("metadata", {})
    candidate_metadata = candidate.get("metadata", {})
    baseline_task_ids = [item["task_id"] for item in baseline["results"]]
    candidate_task_ids = [item["task_id"] for item in candidate["results"]]
    if baseline_config.get("model") != candidate_config.get("model"):
        raise RuntimeError(
            "Cannot compare runs with different models: "
            f"{baseline_config.get('model')} != {candidate_config.get('model')}"
        )
    if baseline_metadata.get("benchmark") != candidate_metadata.get("benchmark"):
        raise RuntimeError("Cannot compare runs from different benchmarks.")
    if baseline_metadata.get("split") != candidate_metadata.get("split"):
        raise RuntimeError("Cannot compare runs from different splits.")
    if baseline_metadata.get("suite_digest") != candidate_metadata.get("suite_digest"):
        raise RuntimeError("Cannot compare runs from different benchmark suite digests.")
    if baseline_task_ids != candidate_task_ids:
        raise RuntimeError("Cannot compare runs with different task IDs or task order.")
    if baseline.get("task_digest") != candidate.get("task_digest"):
        raise RuntimeError("Cannot compare runs with different task or evaluator definitions.")

    per_task = []
    for baseline_item, candidate_item in zip(baseline["results"], candidate["results"], strict=True):
        per_task.append(
            {
                "task_id": baseline_item["task_id"],
                "environment": baseline_item.get("environment", "default"),
                "family": baseline_item.get("family"),
                "evaluator_digest": baseline_item.get("evaluator_digest"),
                "baseline_passed": baseline_item["passed"],
                "candidate_passed": candidate_item["passed"],
                "delta": int(candidate_item["passed"]) - int(baseline_item["passed"]),
            }
        )

    return {
        "baseline_run": baseline_run.name,
        "candidate_run": candidate_run.name,
        "model": baseline_config.get("model"),
        "baseline_harness": baseline_metadata.get("harness"),
        "candidate_harness": candidate_metadata.get("harness"),
        "baseline_harness_digest": baseline.get("harness_behavior_digest"),
        "candidate_harness_digest": candidate.get("harness_behavior_digest"),
        "benchmark": candidate_metadata.get("benchmark"),
        "split": candidate_metadata.get("split"),
        "suite_version": candidate_metadata.get("suite_version"),
        "suite_digest": candidate_metadata.get("suite_digest"),
        "coverage_digest": candidate_metadata.get("coverage_digest"),
        "evaluator_digests": candidate.get("evaluator_digests", []),
        "baseline_pass_rate": baseline["pass_rate"],
        "candidate_pass_rate": candidate["pass_rate"],
        "pass_rate_delta": candidate["pass_rate"] - baseline["pass_rate"],
        "baseline_passed": baseline["passed"],
        "candidate_passed": candidate["passed"],
        "task_count": candidate["tasks"],
        "baseline_attempts": baseline.get("attempts"),
        "candidate_attempts": candidate.get("attempts"),
        "attempt_delta": none_safe_delta(candidate.get("attempts"), baseline.get("attempts")),
        "baseline_tool_calls": baseline.get("tool_calls"),
        "candidate_tool_calls": candidate.get("tool_calls"),
        "tool_call_delta": none_safe_delta(candidate.get("tool_calls"), baseline.get("tool_calls")),
        "baseline_duration_ms": baseline.get("duration_ms"),
        "candidate_duration_ms": candidate.get("duration_ms"),
        "duration_ms_delta": none_safe_delta(
            candidate.get("duration_ms"), baseline.get("duration_ms")
        ),
        "baseline_usage": baseline.get("usage", {}),
        "candidate_usage": candidate.get("usage", {}),
        "baseline_metrics": baseline.get("metrics", {}),
        "candidate_metrics": candidate.get("metrics", {}),
        "metric_deltas": compare_metric_deltas(
            baseline.get("metrics", {}),
            candidate.get("metrics", {}),
        ),
        "environment_scores": compare_environment_metrics(
            baseline.get("per_environment", {}),
            candidate.get("per_environment", {}),
        ),
        "per_environment": compare_environment_metrics(
            baseline.get("per_environment", {}),
            candidate.get("per_environment", {}),
        ),
        "per_task": per_task,
    }


def gate_candidate(
    *,
    baseline_run: Path,
    candidate_run: Path,
    min_pass_rate_delta: float,
    max_allowed_drop: float,
    max_environment_drop: float | None = None,
) -> Path:
    comparison = compare_runs(baseline_run, candidate_run)
    policy = load_gate_policy(comparison["benchmark"], comparison["split"])
    thresholds = resolve_gate_thresholds(
        split=comparison["split"],
        policy=policy,
        min_pass_rate_delta=min_pass_rate_delta,
        max_allowed_drop=max_allowed_drop,
        max_environment_drop=max_environment_drop,
    )
    delta = comparison["pass_rate_delta"]
    environment_failures = find_environment_failures(
        comparison["environment_scores"],
        thresholds["max_environment_drop"],
        thresholds["protected_environments"],
    )
    coverage_evidence = coverage_gate_evidence(comparison["benchmark"])
    coverage_failures = coverage_evidence["coverage_failures"]
    passed = (
        delta >= thresholds["min_delta"]
        and not environment_failures
        and not coverage_failures
    )
    decision = {
        **comparison,
        "requested_min_pass_rate_delta": min_pass_rate_delta,
        "requested_max_allowed_drop": max_allowed_drop,
        "min_pass_rate_delta": thresholds["min_pass_rate_delta"],
        "max_allowed_drop": thresholds["max_allowed_drop"],
        "max_environment_drop": thresholds["max_environment_drop"],
        "effective_min_delta": thresholds["min_delta"],
        "protected_environments": thresholds["protected_environments"],
        "environment_failures": environment_failures,
        **coverage_evidence,
        "decision": "promote" if passed else "reject",
        "rationale": (
            "Candidate met pass-rate gate."
            if passed
            else "Candidate failed pass-rate, regression, environment, or coverage gate."
        ),
    }
    decided_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = GATES / f"{candidate_run.name}-{decided_at}-gate.json"
    write_json(path, decision)
    return path


def load_gate_policy(benchmark: str, split: str) -> dict[str, Any]:
    path = benchmark_dir(benchmark) / "gate_policy.json"
    if not path.exists():
        return {}
    policy = read_json(path)
    split_policy = policy.get(split, {})
    if not isinstance(split_policy, dict):
        raise RuntimeError(f"Gate policy for split {split} must be an object.")
    return split_policy


def resolve_gate_thresholds(
    *,
    split: str,
    policy: dict[str, Any],
    min_pass_rate_delta: float,
    max_allowed_drop: float,
    max_environment_drop: float | None,
) -> dict[str, Any]:
    policy_min = float(policy.get("min_pass_rate_delta", min_pass_rate_delta))
    policy_drop = float(policy.get("max_allowed_drop", max_allowed_drop))
    policy_environment_drop = policy.get("max_environment_drop", max_environment_drop)
    if policy_environment_drop is not None:
        policy_environment_drop = float(policy_environment_drop)

    min_delta = policy_min if policy_min > 0 else -policy_drop
    if split == "regression" and policy_min == 0:
        min_delta = -policy_drop

    protected = policy.get("protected_environments", [])
    if protected == "all":
        protected_environments: list[str] | str = "all"
    else:
        protected_environments = [str(item) for item in protected]
    return {
        "min_delta": min_delta,
        "min_pass_rate_delta": policy_min,
        "max_allowed_drop": policy_drop,
        "max_environment_drop": policy_environment_drop,
        "protected_environments": protected_environments,
    }


def find_environment_failures(
    environment_scores: dict[str, dict[str, Any]],
    max_environment_drop: float | None,
    protected_environments: list[str] | str,
) -> list[dict[str, Any]]:
    if max_environment_drop is None:
        return []
    failures = []
    protected = set(environment_scores) if protected_environments == "all" else set(protected_environments)
    for environment, score in environment_scores.items():
        if protected and environment not in protected:
            continue
        delta = score.get("pass_rate_delta", 0)
        if delta < -max_environment_drop:
            failures.append(
                {
                    "environment": environment,
                    "pass_rate_delta": delta,
                    "max_environment_drop": max_environment_drop,
                }
            )
    return failures


def find_coverage_failures(benchmark: str) -> list[dict[str, Any]]:
    return coverage_gate_evidence(benchmark)["coverage_failures"]


def coverage_gate_evidence(benchmark: str) -> dict[str, Any]:
    if not benchmark_dir(benchmark).exists():
        return empty_coverage_evidence()
    report = build_coverage_report(benchmark)
    failures = (
        report.get("missing_required_cells", [])
        if report.get("coverage_policy", {}).get("fail_on_missing_required")
        else []
    )
    return {
        "coverage_policy_digest": report.get("coverage_policy_digest"),
        "coverage_failures": failures,
        "missing_required_cells": report.get("missing_required_cells", []),
        "waived_missing_cells": report.get("waived_missing_cells", []),
        "unclassified_missing_count": len(report.get("unclassified_missing_cells", [])),
    }


def empty_coverage_evidence() -> dict[str, Any]:
    return {
        "coverage_policy_digest": None,
        "coverage_failures": [],
        "missing_required_cells": [],
        "waived_missing_cells": [],
        "unclassified_missing_count": 0,
    }


def write_coverage_report(benchmark: str) -> Path:
    report = build_coverage_report(benchmark)
    path = benchmark_dir(benchmark) / "coverage.json"
    write_json(path, report)
    return path


def build_coverage_report(benchmark: str) -> dict[str, Any]:
    root = benchmark_dir(benchmark)
    if not root.exists():
        raise RuntimeError(f"Benchmark not found: {root}")
    manifest = read_json(root / "manifest.json") if (root / "manifest.json").exists() else {}
    split_rows = {split: read_jsonl_with_path(root / f"{split}.jsonl") for split in REQUIRED_SPLITS}
    environments = sorted(
        {task.get("environment", "default") for rows in split_rows.values() for task in rows}
    )
    families = sorted({task.get("family", "unlabeled") for rows in split_rows.values() for task in rows})
    matrix = build_environment_family_matrix(split_rows, environments, families)
    environment_split_counts = build_split_counts(split_rows, "environment", environments)
    family_split_counts = build_split_counts(split_rows, "family", families)
    missing_environment_splits = missing_split_cells(environment_split_counts)
    missing_family_splits = missing_split_cells(family_split_counts)
    coverage_policy = normalize_coverage_policy(manifest.get("coverage_policy", {}))
    required_cells = evaluate_policy_cells(
        coverage_policy["required"],
        matrix,
        status_when_missing="missing_required",
        status_when_covered="covered_required",
    )
    waived_cells = evaluate_policy_cells(
        coverage_policy["waivers"],
        matrix,
        status_when_missing="waived_missing",
        status_when_covered="waived_covered",
    )
    missing_required_cells = [cell for cell in required_cells if cell["status"] == "missing_required"]
    waived_missing_cells = [cell for cell in waived_cells if cell["status"] == "waived_missing"]
    classified_missing = {
        cell_identity(cell)
        for cell in [*missing_required_cells, *waived_missing_cells]
    }
    unclassified_missing_cells = [
        cell
        for cell in missing_environment_family_split_cells(matrix)
        if cell_identity(cell) not in classified_missing
    ]
    evaluator_digests = sorted(
        {
            task.get("evaluator_digest") or evaluator_digest(task.get("eval", {}))
            for rows in split_rows.values()
            for task in rows
        }
    )
    report = {
        "benchmark": benchmark,
        "suite_version": manifest.get("suite_version"),
        "suite_digest": manifest.get("suite_digest"),
        "task_count": sum(len(rows) for rows in split_rows.values()),
        "split_counts": {split: len(rows) for split, rows in split_rows.items()},
        "environments": environments,
        "families": families,
        "environment_split_counts": environment_split_counts,
        "family_split_counts": family_split_counts,
        "environment_family_matrix": matrix,
        "missing_environment_splits": missing_environment_splits,
        "missing_family_splits": missing_family_splits,
        "coverage_policy": coverage_policy,
        "coverage_policy_digest": digest_payload(coverage_policy),
        "required_cells": required_cells,
        "waived_cells": waived_cells,
        "missing_required_cells": missing_required_cells,
        "waived_missing_cells": waived_missing_cells,
        "unclassified_missing_cells": unclassified_missing_cells,
        "evaluator_digests": evaluator_digests,
    }
    report["coverage_digest"] = digest_payload(report)
    return report


def normalize_coverage_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if not policy:
        return {"fail_on_missing_required": False, "required": [], "waivers": []}
    if not isinstance(policy, dict):
        raise RuntimeError("coverage_policy must be an object.")
    required = policy.get("required", [])
    waivers = policy.get("waivers", [])
    if not isinstance(required, list):
        raise RuntimeError("coverage_policy.required must be a list.")
    if not isinstance(waivers, list):
        raise RuntimeError("coverage_policy.waivers must be a list.")
    return {
        "fail_on_missing_required": bool(policy.get("fail_on_missing_required", True)),
        "required": [normalize_policy_cell(cell, "required") for cell in required],
        "waivers": [normalize_policy_cell(cell, "waiver") for cell in waivers],
    }


def normalize_policy_cell(cell: Any, label: str) -> dict[str, Any]:
    if not isinstance(cell, dict):
        raise RuntimeError(f"coverage_policy {label} cells must be objects.")
    missing = [key for key in ("environment", "family", "split") if not cell.get(key)]
    if missing:
        raise RuntimeError(
            f"coverage_policy {label} cell is missing required keys: {', '.join(missing)}."
        )
    split = str(cell["split"])
    if split not in REQUIRED_SPLITS:
        raise RuntimeError(f"coverage_policy {label} cell has unknown split: {split}.")
    return {
        "environment": str(cell["environment"]),
        "family": str(cell["family"]),
        "split": split,
        "reason": str(cell.get("reason", "")),
    }


def evaluate_policy_cells(
    cells: list[dict[str, Any]],
    matrix: dict[str, dict[str, dict[str, int]]],
    *,
    status_when_missing: str,
    status_when_covered: str,
) -> list[dict[str, Any]]:
    evaluated = []
    for cell in cells:
        count = (
            matrix.get(cell["environment"], {})
            .get(cell["family"], {})
            .get(cell["split"], 0)
        )
        evaluated.append(
            {
                **cell,
                "count": count,
                "status": status_when_covered if count > 0 else status_when_missing,
            }
        )
    return evaluated


def missing_environment_family_split_cells(
    matrix: dict[str, dict[str, dict[str, int]]],
) -> list[dict[str, Any]]:
    missing = []
    for environment, families in matrix.items():
        for family, split_counts in families.items():
            for split, count in split_counts.items():
                if count == 0:
                    missing.append(
                        {
                            "environment": environment,
                            "family": family,
                            "split": split,
                            "count": count,
                            "status": "unclassified_missing",
                        }
                    )
    return missing


def cell_identity(cell: dict[str, Any]) -> tuple[str, str, str]:
    return (str(cell["environment"]), str(cell["family"]), str(cell["split"]))


def build_environment_family_matrix(
    split_rows: dict[str, list[dict[str, Any]]],
    environments: list[str],
    families: list[str],
) -> dict[str, dict[str, dict[str, int]]]:
    matrix = {
        environment: {
            family: {split: 0 for split in REQUIRED_SPLITS}
            for family in families
        }
        for environment in environments
    }
    for split, rows in split_rows.items():
        for task in rows:
            environment = task.get("environment", "default")
            family = task.get("family", "unlabeled")
            matrix[environment][family][split] += 1
    return matrix


def build_split_counts(
    split_rows: dict[str, list[dict[str, Any]]],
    key: str,
    values: list[str],
) -> dict[str, dict[str, int]]:
    counts = {value: {split: 0 for split in REQUIRED_SPLITS} for value in values}
    for split, rows in split_rows.items():
        for task in rows:
            counts[task.get(key, "unlabeled")][split] += 1
    return counts


def missing_split_cells(split_counts: dict[str, dict[str, int]]) -> list[dict[str, str]]:
    missing = []
    for name, counts in split_counts.items():
        for split, count in counts.items():
            if count == 0:
                missing.append({"name": name, "split": split})
    return missing


def none_safe_delta(candidate: float | int | None, baseline: float | int | None) -> float | int | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def compare_environment_metrics(
    baseline: dict[str, dict[str, Any]], candidate: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    comparison = {}
    for environment in sorted(set(baseline) | set(candidate)):
        baseline_entry = baseline.get(environment, {})
        candidate_entry = candidate.get(environment, {})
        comparison[environment] = {
            "baseline_tasks": baseline_entry.get("tasks", 0),
            "candidate_tasks": candidate_entry.get("tasks", 0),
            "baseline_passed": baseline_entry.get("passed", 0),
            "candidate_passed": candidate_entry.get("passed", 0),
            "task_count": candidate_entry.get("tasks", baseline_entry.get("tasks", 0)),
            "baseline_pass_rate": baseline_entry.get("pass_rate", 0),
            "candidate_pass_rate": candidate_entry.get("pass_rate", 0),
            "pass_rate_delta": candidate_entry.get("pass_rate", 0)
            - baseline_entry.get("pass_rate", 0),
            "baseline_attempts": baseline_entry.get("attempts", 0),
            "candidate_attempts": candidate_entry.get("attempts", 0),
            "attempt_delta": candidate_entry.get("attempts", 0)
            - baseline_entry.get("attempts", 0),
            "baseline_tool_calls": baseline_entry.get("tool_calls", 0),
            "candidate_tool_calls": candidate_entry.get("tool_calls", 0),
            "tool_call_delta": candidate_entry.get("tool_calls", 0)
            - baseline_entry.get("tool_calls", 0),
        }
    return comparison


def compare_metric_deltas(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, float | int | None]:
    return {
        "attempts": none_safe_delta(candidate.get("attempts"), baseline.get("attempts")),
        "tool_calls": none_safe_delta(candidate.get("tool_calls"), baseline.get("tool_calls")),
        "duration_ms": none_safe_delta(candidate.get("duration_ms"), baseline.get("duration_ms")),
        "cost_usd": none_safe_delta(candidate.get("cost_usd"), baseline.get("cost_usd")),
    }
