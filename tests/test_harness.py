from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from harness_rsi.benchmarks import compare_runs, gate_candidate
from harness_rsi.cli import main
from harness_rsi.io import read_json, write_json


@contextmanager
def working_dir(path: Path) -> Iterator[None]:
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def test_mock_loop(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["init"]) == 0
        assert main(["run", "--mock"]) == 0
        assert main(["improve", "--mock"]) == 0
        proposals = sorted((tmp_path / ".rsi" / "proposals").glob("*.json"))
        assert proposals
        assert main(["promote", str(proposals[-1])]) == 0
        learnings = tmp_path / ".rsi" / "memory" / "learnings.md"
        assert "evaluator target" in learnings.read_text()


def test_benchmark_init_creates_h0_and_splits(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        assert (tmp_path / ".rsi" / "harnesses" / "H0.json").exists()
        assert (tmp_path / ".rsi" / "benchmarks" / "synthetic" / "train.jsonl").exists()
        assert (tmp_path / ".rsi" / "benchmarks" / "synthetic" / "heldout.jsonl").exists()
        assert (tmp_path / ".rsi" / "benchmarks" / "synthetic" / "regression.jsonl").exists()
        manifest = read_json(tmp_path / ".rsi" / "benchmarks" / "synthetic" / "manifest.json")
        assert manifest["baseline_harness"] == "H0"
        assert "world_model" in manifest["environments"]


def test_benchmark_run_records_metadata(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        assert main(["benchmark", "run", "--split", "heldout", "--mock"]) == 0
        run_dir = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        results = read_json(run_dir / "results.json")
        assert results["metadata"] == {
            "benchmark": "synthetic",
            "split": "heldout",
            "harness": "H0",
        }
        assert results["task_digest"]
        assert {item["environment"] for item in results["results"]} >= {
            "knowledge_work",
            "world_model",
        }


def test_compare_and_gate_pass_for_equal_mock_runs(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        h0 = tmp_path / ".rsi" / "harnesses" / "H0.json"
        h1 = tmp_path / ".rsi" / "harnesses" / "H1.json"
        h1_config = read_json(h0) | {"id": "H1", "parent": "H0"}
        write_json(h1, h1_config)

        assert main(["benchmark", "run", "--split", "heldout", "--harness", "H0", "--mock"]) == 0
        assert main(["benchmark", "run", "--split", "heldout", "--harness", "H1", "--mock"]) == 0
        baseline_run, candidate_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-2:]

        comparison = compare_runs(baseline_run, candidate_run)
        assert comparison["model"] == "gpt-5.5"
        assert comparison["baseline_harness"] == "H0"
        assert comparison["candidate_harness"] == "H1"
        assert comparison["pass_rate_delta"] == 0

        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        assert read_json(gate_path)["decision"] == "promote"


def test_gate_rejects_when_threshold_not_met(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0.1,
            max_allowed_drop=0,
        )
        assert read_json(gate_path)["decision"] == "reject"


def test_gate_writes_unique_artifacts_for_multiple_policies(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)
        first = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        second = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0.1,
            max_allowed_drop=0,
        )
        assert first != second
        assert first.exists()
        assert second.exists()


def test_compare_rejects_model_mismatch(tmp_path: Path) -> None:
    baseline_run = write_fake_run(tmp_path / "baseline", model="gpt-5.5")
    candidate_run = write_fake_run(tmp_path / "candidate", model="other-model")
    try:
        compare_runs(baseline_run, candidate_run)
    except RuntimeError as error:
        assert "different models" in str(error)
    else:
        raise AssertionError("Expected model mismatch rejection.")


def test_compare_rejects_task_digest_mismatch(tmp_path: Path) -> None:
    baseline_run = write_fake_run(tmp_path / "baseline", task_digest="same-tasks")
    candidate_run = write_fake_run(tmp_path / "candidate", task_digest="changed-tasks")
    try:
        compare_runs(baseline_run, candidate_run)
    except RuntimeError as error:
        assert "different task or evaluator definitions" in str(error)
    else:
        raise AssertionError("Expected task digest mismatch rejection.")


def test_compare_rejects_split_mismatch(tmp_path: Path) -> None:
    baseline_run = write_fake_run(tmp_path / "baseline", split="heldout")
    candidate_run = write_fake_run(tmp_path / "candidate", split="train")
    try:
        compare_runs(baseline_run, candidate_run)
    except RuntimeError as error:
        assert "different splits" in str(error)
    else:
        raise AssertionError("Expected split mismatch rejection.")


def write_fake_run(
    path: Path,
    *,
    passed: int = 1,
    task_count: int = 2,
    model: str = "gpt-5.5",
    task_digest: str = "same-tasks",
    split: str = "heldout",
) -> Path:
    path.mkdir(parents=True)
    write_json(path / "harness.snapshot.json", {"model": model})
    results = []
    for index in range(task_count):
        results.append(
            {
                "task_id": f"task-{index}",
                "environment": "fake",
                "passed": index < passed,
                "attempt": 0,
            }
        )
    write_json(
        path / "results.json",
        {
            "run_id": path.name,
            "metadata": {"benchmark": "fake", "split": split, "harness": path.name},
            "task_digest": task_digest,
            "tasks": task_count,
            "passed": passed,
            "pass_rate": passed / task_count,
            "results": results,
        },
    )
    return path
