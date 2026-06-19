from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import BENCHMARKS, GATES, HARNESSES


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


def init_benchmark(name: str = "synthetic") -> Path:
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
        metadata={"benchmark": benchmark, "split": split, "harness": harness},
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
) -> Path:
    comparison = compare_runs(baseline_run, candidate_run)
    delta = comparison["pass_rate_delta"]
    passed = delta >= min_pass_rate_delta and delta >= -max_allowed_drop
    decision = {
        **comparison,
        "min_pass_rate_delta": min_pass_rate_delta,
        "max_allowed_drop": max_allowed_drop,
        "decision": "promote" if passed else "reject",
        "rationale": (
            "Candidate met pass-rate gate."
            if passed
            else "Candidate failed pass-rate gate or exceeded allowed drop."
        ),
    }
    decided_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = GATES / f"{candidate_run.name}-{decided_at}-gate.json"
    write_json(path, decision)
    return path


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
