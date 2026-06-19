from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import BENCHMARKS, GATES, HARNESSES

SOURCE_BENCHMARKS = Path("benchmarks")
PACKAGE_BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"
REQUIRED_SPLITS = ("train", "heldout", "regression")
ADAPTER_KINDS = {"terminal", "swe_patch", "tool_agent_user"}
ADAPTER_REQUIRED_KEYS = {
    "name",
    "kind",
    "external_id",
    "fixture_version",
    "source_url",
    "mode",
}


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
    validate_external_adapter_metadata(split_rows)
    for split in REQUIRED_SPLITS:
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


def validate_external_adapter_metadata(split_rows: dict[str, list[dict[str, Any]]]) -> None:
    failures = find_external_adapter_metadata_failures(split_rows)
    if failures:
        formatted = "; ".join(
            f"{failure['task_id']}:{failure['field']}:{failure['status']}"
            for failure in failures
        )
        raise RuntimeError(f"External adapter metadata is invalid: {formatted}.")


def find_external_adapter_metadata_failures(
    split_rows: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for split, rows in split_rows.items():
        for row in rows:
            task_id = str(row.get("id", "<missing-id>"))
            adapter = row.get("external_adapter")
            if adapter is None:
                continue
            if not isinstance(adapter, dict):
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "external_adapter",
                        "status": "must_be_object",
                    }
                )
                continue
            unknown = sorted(set(adapter) - ADAPTER_REQUIRED_KEYS)
            if unknown:
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "external_adapter",
                        "status": f"unknown_keys:{','.join(unknown)}",
                    }
                )
            for key in sorted(ADAPTER_REQUIRED_KEYS):
                if not str(adapter.get(key, "")).strip():
                    failures.append(
                        {
                            "task_id": task_id,
                            "split": split,
                            "field": key,
                            "status": "missing",
                        }
                    )
            if adapter.get("mode") and adapter.get("mode") != "read_only":
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "mode",
                        "status": "must_be_read_only",
                    }
                )
            if adapter.get("kind") and adapter.get("kind") not in ADAPTER_KINDS:
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "kind",
                        "status": f"unknown_kind:{adapter.get('kind')}",
                    }
                )
            if row.get("split") != split:
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "split",
                        "status": "task_split_mismatch",
                    }
                )
            if not row.get("source"):
                failures.append(
                    {
                        "task_id": task_id,
                        "split": split,
                        "field": "source",
                        "status": "missing",
                    }
                )
    return failures


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
    if (
        baseline_metadata.get("coverage_digest")
        and candidate_metadata.get("coverage_digest")
        and baseline_metadata.get("coverage_digest") != candidate_metadata.get("coverage_digest")
    ):
        raise RuntimeError("Cannot compare runs from different coverage digests.")
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
    coverage_evidence = coverage_gate_evidence(
        comparison["benchmark"],
        expected_coverage_digest=comparison.get("coverage_digest"),
        waiver_review_policy=thresholds["waiver_review_policy"],
    )
    coverage_failures = coverage_evidence["coverage_failures"]
    waiver_review_failures = coverage_evidence["waiver_review_failures"]
    efficiency_failures = find_efficiency_failures(
        comparison["metric_deltas"],
        thresholds["efficiency_thresholds"],
    )
    passed = (
        delta >= thresholds["min_delta"]
        and not environment_failures
        and not coverage_failures
        and not waiver_review_failures
        and not efficiency_failures
    )
    decision = {
        **comparison,
        "requested_min_pass_rate_delta": min_pass_rate_delta,
        "requested_max_allowed_drop": max_allowed_drop,
        "min_pass_rate_delta": thresholds["min_pass_rate_delta"],
        "max_allowed_drop": thresholds["max_allowed_drop"],
        "max_environment_drop": thresholds["max_environment_drop"],
        "efficiency_thresholds": thresholds["efficiency_thresholds"],
        "waiver_review_policy": thresholds["waiver_review_policy"],
        "effective_min_delta": thresholds["min_delta"],
        "protected_environments": thresholds["protected_environments"],
        "environment_failures": environment_failures,
        "efficiency_failures": efficiency_failures,
        **coverage_evidence,
        "decision": "promote" if passed else "reject",
        "rationale": (
            "Candidate met pass-rate gate."
            if passed
            else (
                "Candidate failed pass-rate, regression, environment, coverage, "
                "waiver review, or efficiency gate."
            )
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
    efficiency_thresholds = resolve_efficiency_thresholds(policy)
    waiver_review_policy = resolve_waiver_review_policy(policy)

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
        "efficiency_thresholds": efficiency_thresholds,
        "waiver_review_policy": waiver_review_policy,
        "protected_environments": protected_environments,
    }


def resolve_efficiency_thresholds(policy: dict[str, Any]) -> dict[str, float | None]:
    return {
        "attempts": optional_float(policy.get("max_attempt_delta")),
        "tool_calls": optional_float(policy.get("max_tool_call_delta")),
        "duration_ms": optional_float(policy.get("max_duration_ms_delta")),
        "cost_usd": optional_float(policy.get("max_cost_usd_delta")),
    }


def resolve_waiver_review_policy(policy: dict[str, Any]) -> dict[str, Any]:
    fail_on_overdue = bool(policy.get("fail_on_overdue_waivers", False))
    review_as_of = policy.get("waiver_review_as_of")
    if review_as_of is not None:
        review_as_of = str(review_as_of)
        validate_iso_date(review_as_of, "gate_policy waiver_review_as_of")
    if fail_on_overdue and review_as_of is None:
        raise RuntimeError(
            "gate_policy waiver_review_as_of must be set when "
            "fail_on_overdue_waivers is enabled."
        )
    due_within_days = int(policy.get("waiver_due_within_days", 30))
    if due_within_days < 0:
        raise RuntimeError("waiver_due_within_days must be greater than or equal to 0.")
    return {
        "fail_on_overdue_waivers": fail_on_overdue,
        "waiver_review_as_of": review_as_of,
        "waiver_due_within_days": due_within_days,
    }


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


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


def find_efficiency_failures(
    metric_deltas: dict[str, float | int | None],
    thresholds: dict[str, float | None],
) -> list[dict[str, Any]]:
    failures = []
    for metric, max_delta in thresholds.items():
        if max_delta is None:
            continue
        delta = metric_deltas.get(metric)
        if delta is None:
            failures.append(
                {
                    "metric": metric,
                    "max_delta": max_delta,
                    "delta": None,
                    "status": "metric_unavailable",
                }
            )
            continue
        if delta > max_delta:
            failures.append(
                {
                    "metric": metric,
                    "max_delta": max_delta,
                    "delta": delta,
                    "status": "efficiency_regression",
                }
            )
    return failures


def find_coverage_failures(benchmark: str) -> list[dict[str, Any]]:
    return coverage_gate_evidence(benchmark)["coverage_failures"]


def coverage_gate_evidence(
    benchmark: str,
    expected_coverage_digest: str | None = None,
    waiver_review_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not benchmark_dir(benchmark).exists():
        return empty_coverage_evidence()
    report = build_coverage_report(benchmark)
    failures = (
        report.get("missing_required_cells", [])
        if report.get("coverage_policy", {}).get("fail_on_missing_required")
        else []
    )
    current_coverage_digest = report.get("coverage_digest")
    if expected_coverage_digest and current_coverage_digest != expected_coverage_digest:
        failures = [
            *failures,
            {
                "type": "coverage_digest_mismatch",
                "expected_coverage_digest": expected_coverage_digest,
                "current_coverage_digest": current_coverage_digest,
                "status": "coverage_drift",
            },
        ]
    waiver_review_policy = resolve_waiver_review_policy(waiver_review_policy or {})
    waiver_review = None
    waiver_review_failures: list[dict[str, Any]] = []
    if should_build_waiver_review(waiver_review_policy):
        waiver_report = build_waiver_report(
            benchmark,
            as_of=waiver_review_policy["waiver_review_as_of"],
            due_within_days=waiver_review_policy["waiver_due_within_days"],
        )
        waiver_review = summarize_waiver_review(waiver_report)
        waiver_review_failures = find_waiver_review_failures(
            waiver_report,
            waiver_review_policy,
        )
    return {
        "current_coverage_digest": current_coverage_digest,
        "coverage_policy_digest": report.get("coverage_policy_digest"),
        "coverage_failures": failures,
        "waiver_review": waiver_review,
        "waiver_review_failures": waiver_review_failures,
        "missing_required_cells": report.get("missing_required_cells", []),
        "waived_missing_cells": report.get("waived_missing_cells", []),
        "unclassified_missing_count": len(report.get("unclassified_missing_cells", [])),
    }


def empty_coverage_evidence() -> dict[str, Any]:
    return {
        "current_coverage_digest": None,
        "coverage_policy_digest": None,
        "coverage_failures": [],
        "waiver_review": None,
        "waiver_review_failures": [],
        "missing_required_cells": [],
        "waived_missing_cells": [],
        "unclassified_missing_count": 0,
    }


def should_build_waiver_review(policy: dict[str, Any]) -> bool:
    return bool(
        policy["fail_on_overdue_waivers"]
        or policy["waiver_review_as_of"]
        or policy["waiver_due_within_days"] != 30
    )


def summarize_waiver_review(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "as_of": report["as_of"],
        "due_within_days": report["due_within_days"],
        "waiver_count": report["waiver_count"],
        "active_missing_count": report["active_missing_count"],
        "retire_candidate_count": report["retire_candidate_count"],
        "review_status_counts": report["review_status_counts"],
        "review_due_count": report["review_due_count"],
        "next_review_by": report["next_review_by"],
        "coverage_digest_matches_stored": report["coverage_digest_matches_stored"],
        "waiver_lifecycle_digest": report["waiver_lifecycle_digest"],
    }


def find_waiver_review_failures(
    report: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    if not policy["fail_on_overdue_waivers"]:
        return []
    failures = []
    for waiver in report["waivers"]:
        if waiver["review_state"] != "overdue":
            continue
        if waiver["lifecycle_state"] != "active_missing":
            continue
        failures.append(
            {
                "environment": waiver["environment"],
                "family": waiver["family"],
                "split": waiver["split"],
                "identity": waiver["identity"],
                "owner": waiver["owner"],
                "tracking_ref": waiver["tracking_ref"],
                "review_by": waiver["review_by"],
                "review_state": waiver["review_state"],
                "lifecycle_state": waiver["lifecycle_state"],
                "status": "overdue_waiver",
            }
        )
    return failures


def write_coverage_report(benchmark: str) -> Path:
    report = build_coverage_report(benchmark)
    path = benchmark_dir(benchmark) / "coverage.json"
    write_json(path, report)
    return path


def write_waiver_report(
    benchmark: str,
    *,
    as_of: str | None = None,
    due_within_days: int = 30,
) -> Path:
    report = build_waiver_report(
        benchmark,
        as_of=as_of,
        due_within_days=due_within_days,
    )
    path = benchmark_dir(benchmark) / "waiver_lifecycle.json"
    write_json(path, report)
    return path


def write_adapter_report(benchmark: str) -> Path:
    report = build_adapter_report(benchmark)
    path = benchmark_dir(benchmark) / "adapter_report.json"
    write_json(path, report)
    return path


def build_adapter_report(benchmark: str) -> dict[str, Any]:
    root = benchmark_dir(benchmark)
    if not root.exists():
        raise RuntimeError(f"Benchmark not found: {root}")
    manifest = read_json(root / "manifest.json") if (root / "manifest.json").exists() else {}
    split_rows = {split: read_jsonl_with_path(root / f"{split}.jsonl") for split in REQUIRED_SPLITS}
    failures = find_external_adapter_metadata_failures(split_rows)
    tasks = [
        adapter_task_summary(row, split)
        for split, rows in split_rows.items()
        for row in rows
        if row.get("external_adapter")
    ]
    adapters = group_adapter_tasks(tasks)
    report = {
        "benchmark": benchmark,
        "suite_version": manifest.get("suite_version"),
        "suite_digest": manifest.get("suite_digest"),
        "coverage_digest": read_coverage_digest(benchmark),
        "task_count": sum(len(rows) for rows in split_rows.values()),
        "external_adapter_task_count": len(tasks),
        "adapter_task_count": len(tasks),
        "kind_counts": count_adapter_field(tasks, "kind"),
        "split_counts": count_task_field(tasks, "split"),
        "fixture_versions": {
            name: adapters[name]["fixture_versions"] for name in sorted(adapters)
        },
        "status": "pass" if tasks and not failures else ("empty" if not tasks else "fail"),
        "read_only": bool(tasks) and not failures,
        "gate_semantics_changed": False,
        "adapters": adapters,
        "tasks": tasks,
        "metadata_failures": failures,
        "failures": failures,
    }
    report["adapter_report_digest"] = digest_payload(report)
    return report


def adapter_task_summary(row: dict[str, Any], split: str) -> dict[str, Any]:
    adapter = row["external_adapter"]
    return {
        "id": row["id"],
        "split": split,
        "environment": row.get("environment", "default"),
        "family": row.get("family", "unlabeled"),
        "source": row.get("source"),
        "evaluator_digest": row.get("evaluator_digest"),
        "adapter": {
            "name": adapter.get("name"),
            "kind": adapter.get("kind"),
            "external_id": adapter.get("external_id"),
            "fixture_version": adapter.get("fixture_version"),
            "source_url": adapter.get("source_url"),
            "mode": adapter.get("mode"),
        },
    }


def group_adapter_tasks(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for task in tasks:
        adapter = task["adapter"]
        name = str(adapter["name"])
        group = groups.setdefault(
            name,
            {
                "task_count": 0,
                "kind": adapter.get("kind"),
                "mode": adapter.get("mode"),
                "split_counts": {split: 0 for split in REQUIRED_SPLITS},
                "environments": set(),
                "families": set(),
                "fixture_versions": set(),
                "source_urls": set(),
                "external_ids": [],
            },
        )
        group["task_count"] += 1
        group["split_counts"][task["split"]] += 1
        group["environments"].add(task["environment"])
        group["families"].add(task["family"])
        group["fixture_versions"].add(adapter.get("fixture_version"))
        group["source_urls"].add(adapter.get("source_url"))
        group["external_ids"].append(adapter.get("external_id"))
    normalized = {}
    for name in sorted(groups):
        group = groups[name]
        normalized[name] = {
            **group,
            "environments": sorted(group["environments"]),
            "families": sorted(group["families"]),
            "fixture_versions": sorted(
                str(item) for item in group["fixture_versions"] if item is not None
            ),
            "source_urls": sorted(
                str(item) for item in group["source_urls"] if item is not None
            ),
            "external_ids": sorted(
                str(item) for item in group["external_ids"] if item is not None
            ),
        }
    return normalized


def count_adapter_field(tasks: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        key = str(task["adapter"].get(field))
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def count_task_field(tasks: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        key = str(task.get(field))
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def build_waiver_report(
    benchmark: str,
    *,
    as_of: str | None = None,
    due_within_days: int = 30,
) -> dict[str, Any]:
    if due_within_days < 0:
        raise RuntimeError("due_within_days must be greater than or equal to 0.")
    coverage = build_coverage_report(benchmark)
    review_as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    validate_review_date(review_as_of)
    stored_coverage_digest = read_coverage_digest(benchmark)
    waivers = [
        annotate_waiver_lifecycle(
            cell,
            as_of=review_as_of,
            due_within_days=due_within_days,
        )
        for cell in coverage.get("waived_cells", [])
    ]
    review_status_counts = {
        status: count_matching(waivers, "review_state", status)
        for status in ("overdue", "due_soon", "scheduled")
    }
    report = {
        "benchmark": benchmark,
        "suite_version": coverage.get("suite_version"),
        "suite_digest": coverage.get("suite_digest"),
        "coverage_digest": coverage.get("coverage_digest"),
        "stored_coverage_digest": stored_coverage_digest,
        "coverage_digest_matches_stored": coverage.get("coverage_digest") == stored_coverage_digest,
        "coverage_policy_digest": coverage.get("coverage_policy_digest"),
        "as_of": review_as_of,
        "due_within_days": due_within_days,
        "waiver_count": len(waivers),
        "waived_missing_count": count_matching(waivers, "status", "waived_missing"),
        "waived_covered_count": count_matching(waivers, "status", "waived_covered"),
        "active_missing_count": count_matching(waivers, "lifecycle_state", "active_missing"),
        "retire_candidate_count": count_matching(waivers, "lifecycle_state", "retire_candidate"),
        "review_status_counts": review_status_counts,
        "review_due_count": review_status_counts["overdue"] + review_status_counts["due_soon"],
        "next_review_by": next_review_date(waivers),
        "by_owner": group_waivers(waivers, "owner"),
        "by_review_date": group_waivers(waivers, "review_by"),
        "waivers": waivers,
    }
    report["waiver_lifecycle_digest"] = digest_payload(report)
    return report


def annotate_waiver_lifecycle(
    cell: dict[str, Any],
    *,
    as_of: str,
    due_within_days: int,
) -> dict[str, Any]:
    as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    review_date = datetime.strptime(str(cell["review_by"]), "%Y-%m-%d").date()
    if review_date < as_of_date:
        review_state = "overdue"
    elif review_date <= as_of_date + timedelta(days=due_within_days):
        review_state = "due_soon"
    else:
        review_state = "scheduled"
    lifecycle_state = (
        "retire_candidate"
        if cell.get("status") == "waived_covered"
        else "active_missing"
    )
    return {
        **cell,
        "identity": cell_identity_string(cell),
        "review_state": review_state,
        "lifecycle_state": lifecycle_state,
    }


def count_matching(items: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for item in items if item.get(key) == value)


def next_review_date(waivers: list[dict[str, Any]]) -> str | None:
    dates = sorted(str(waiver["review_by"]) for waiver in waivers)
    return dates[0] if dates else None


def group_waivers(waivers: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for waiver in waivers:
        group_key = str(waiver[key])
        group = groups.setdefault(
            group_key,
            {
                "count": 0,
                "active_missing_count": 0,
                "retire_candidate_count": 0,
                "review_status_counts": {"overdue": 0, "due_soon": 0, "scheduled": 0},
                "review_due_count": 0,
                "waivers": [],
            },
        )
        group["count"] += 1
        if waiver["lifecycle_state"] == "active_missing":
            group["active_missing_count"] += 1
        if waiver["lifecycle_state"] == "retire_candidate":
            group["retire_candidate_count"] += 1
        group["review_status_counts"][waiver["review_state"]] += 1
        if waiver["review_state"] in {"overdue", "due_soon"}:
            group["review_due_count"] += 1
        group["waivers"].append(waiver["identity"])
    return {group_key: groups[group_key] for group_key in sorted(groups)}


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
    normalized = {
        "fail_on_missing_required": bool(policy.get("fail_on_missing_required", True)),
        "required": [normalize_required_cell(cell) for cell in required],
        "waivers": [normalize_waiver_cell(cell) for cell in waivers],
    }
    validate_policy_cell_identities(normalized["required"], "required")
    validate_policy_cell_identities(normalized["waivers"], "waiver")
    validate_required_waiver_overlap(normalized["required"], normalized["waivers"])
    return normalized


def normalize_required_cell(cell: Any) -> dict[str, Any]:
    check_policy_keys(cell, {"environment", "family", "split", "reason"}, "required")
    normalized = normalize_policy_cell_base(cell, "required")
    return {
        **normalized,
        "reason": str(cell.get("reason", "")),
    }


def normalize_waiver_cell(cell: Any) -> dict[str, Any]:
    check_policy_keys(
        cell,
        {
            "environment",
            "family",
            "split",
            "reason",
            "owner",
            "tracking_ref",
            "review_by",
            "expires_when",
        },
        "waiver",
    )
    normalized = normalize_policy_cell_base(cell, "waiver")
    missing = [
        key
        for key in ("reason", "owner", "tracking_ref", "review_by")
        if not str(cell.get(key, "")).strip()
    ]
    if missing:
        raise RuntimeError(
            f"coverage_policy waiver cell is missing required metadata: {', '.join(missing)}."
        )
    review_by = str(cell["review_by"])
    validate_review_date(review_by)
    waiver = {
        **normalized,
        "reason": str(cell["reason"]),
        "owner": str(cell["owner"]),
        "tracking_ref": str(cell["tracking_ref"]),
        "review_by": review_by,
    }
    if cell.get("expires_when"):
        waiver["expires_when"] = str(cell["expires_when"])
    return waiver


def check_policy_keys(cell: Any, allowed: set[str], label: str) -> None:
    if not isinstance(cell, dict):
        return
    unknown = sorted(set(cell) - allowed)
    if unknown:
        raise RuntimeError(
            f"coverage_policy {label} cell has unknown keys: {', '.join(unknown)}."
        )


def normalize_policy_cell_base(cell: Any, label: str) -> dict[str, str]:
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
    }


def validate_review_date(value: str) -> None:
    validate_iso_date(value, "coverage_policy waiver review_by")


def validate_iso_date(value: str, label: str) -> None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise RuntimeError(f"{label} must be YYYY-MM-DD: {value}.") from error
    if parsed.strftime("%Y-%m-%d") != value:
        raise RuntimeError(f"{label} must be YYYY-MM-DD: {value}.")


def validate_policy_cell_identities(cells: list[dict[str, Any]], label: str) -> None:
    seen: set[tuple[str, str, str]] = set()
    duplicates = []
    for cell in cells:
        identity = cell_identity(cell)
        if identity in seen:
            duplicates.append(identity)
        seen.add(identity)
    if duplicates:
        formatted = ", ".join("/".join(identity) for identity in duplicates)
        raise RuntimeError(f"coverage_policy {label} cells contain duplicates: {formatted}.")


def validate_required_waiver_overlap(
    required: list[dict[str, Any]],
    waivers: list[dict[str, Any]],
) -> None:
    required_identities = {cell_identity(cell) for cell in required}
    overlaps = sorted(required_identities & {cell_identity(cell) for cell in waivers})
    if overlaps:
        formatted = ", ".join("/".join(identity) for identity in overlaps)
        raise RuntimeError(
            "coverage_policy required and waiver cells overlap: "
            f"{formatted}."
        )


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


def cell_identity_string(cell: dict[str, Any]) -> str:
    return "/".join(cell_identity(cell))


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
