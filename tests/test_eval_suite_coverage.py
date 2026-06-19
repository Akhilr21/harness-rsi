from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from harness_rsi.benchmarks import compare_runs, evaluator_digest, suite_digest
from harness_rsi.cli import main
from harness_rsi.harness import harness_behavior_digest
from harness_rsi.io import read_json, read_jsonl


@contextmanager
def working_dir(path: Path) -> Iterator[None]:
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def test_benchmark_run_writes_core_artifact_schema(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        assert main(["benchmark", "run", "--split", "heldout", "--mock"]) == 0

        run_dir = latest_run_dir(tmp_path)
        assert {path.name for path in run_dir.iterdir()} >= {
            "harness.snapshot.json",
            "input.json",
            "results.json",
            "summary.md",
            "trace.jsonl",
        }

        run_input = read_json(run_dir / "input.json")
        results = read_json(run_dir / "results.json")
        snapshot = read_json(run_dir / "harness.snapshot.json")
        trace = read_jsonl(run_dir / "trace.jsonl")

        assert run_input["tasks_path"].endswith(".rsi/benchmarks/synthetic/heldout.jsonl")
        assert run_input["task_count"] == results["tasks"]
        assert run_input["task_digest"] == results["task_digest"]
        assert run_input["harness_behavior_digest"] == results["harness_behavior_digest"]
        assert run_input["harness_behavior_digest"] == harness_behavior_digest(snapshot)
        assert run_input["metadata"] == results["metadata"] == {
            "benchmark": "synthetic",
            "split": "heldout",
            "harness": "H0",
        }

        assert results["run_id"] == run_dir.name
        assert set(results) >= {
            "started_at",
            "ended_at",
            "duration_ms",
            "metrics",
            "usage",
            "per_environment",
            "results",
        }
        assert set(results["metrics"]) == {"attempts", "tool_calls", "duration_ms", "cost_usd"}
        assert set(results["usage"]) == {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "source",
        }
        assert results["usage"]["source"] == "not_collected"
        assert results["passed"] == results["tasks"]
        assert len(trace) == results["attempts"] == results["tasks"]

        first_event = trace[0]
        assert set(first_event) >= {
            "task_id",
            "environment",
            "attempt",
            "attempt_count",
            "tool_calls",
            "model",
            "mock",
            "prompt",
            "answer",
            "score",
        }
        assert first_event["mock"] is True
        assert first_event["score"]["passed"] is True
        assert set(first_event["score"]) == {"passed", "type", "expected", "observed"}


def test_real_benchmark_splits_have_isolated_task_digests(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        assert main(["benchmark", "run", "--split", "train", "--mock"]) == 0
        train_run = latest_run_dir(tmp_path)
        assert main(["benchmark", "run", "--split", "heldout", "--mock"]) == 0
        heldout_run = latest_run_dir(tmp_path)

        train_input = read_json(train_run / "input.json")
        heldout_input = read_json(heldout_run / "input.json")
        train_results = read_json(train_run / "results.json")
        heldout_results = read_json(heldout_run / "results.json")

        assert train_input["metadata"]["split"] == "train"
        assert heldout_input["metadata"]["split"] == "heldout"
        assert train_input["task_digest"] != heldout_input["task_digest"]
        assert {item["task_id"] for item in train_results["results"]}.isdisjoint(
            {item["task_id"] for item in heldout_results["results"]}
        )

        try:
            compare_runs(train_run, heldout_run)
        except RuntimeError as error:
            assert "different splits" in str(error)
        else:
            raise AssertionError("Expected comparison across benchmark splits to fail.")


def test_mock_proposal_records_source_run_and_candidate_lineage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["init"]) == 0
        assert main(["benchmark", "init"]) == 0
        assert main(["benchmark", "run", "--split", "train", "--mock"]) == 0
        source_run = latest_run_dir(tmp_path)

        assert main(["improve", "--run", str(source_run), "--mock"]) == 0
        proposal_path = sorted((tmp_path / ".rsi" / "proposals").glob("*.json"))[-1]
        proposal = read_json(proposal_path)
        assert proposal["source_run"] == source_run.name
        assert proposal["evidence"]["run_id"] == source_run.name
        assert proposal["evidence"]["metadata"]["split"] == "train"
        assert proposal["config_patch"]

        assert (
            main(
                [
                    "harness",
                    "create-candidate",
                    "--parent",
                    "H0",
                    "--candidate",
                    "H1",
                    "--proposal",
                    str(proposal_path),
                ]
            )
            == 0
        )
        candidate = read_json(tmp_path / ".rsi" / "harnesses" / "H1.json")
        assert candidate["status"] == "candidate"
        assert candidate["created_from_proposal"] == proposal["id"]
        assert candidate["lineage"] == {"parent": "H0", "proposal": str(proposal_path)}


def test_sim_v0_materialized_coverage_reports_family_matrix(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0

        root = tmp_path / ".rsi" / "benchmarks" / "sim-v0"
        manifest = read_json(root / "manifest.json")
        coverage = read_json(root / "coverage.json")
        split_families = {
            split: {row["family"] for row in read_jsonl(root / f"{split}.jsonl")}
            for split in ("train", "heldout", "regression")
        }
        all_families = sorted(set().union(*split_families.values()))

        assert manifest["families"] == all_families
        assert coverage["families"] == all_families
        assert coverage["suite_digest"] == manifest["suite_digest"]
        assert coverage["task_count"] == sum(manifest["split_counts"].values())
        assert set(manifest["families"]) >= {
            "failure_signal",
            "impossible_transition",
            "promoted_behavior",
            "regex_eval",
        }
        assert split_families["train"] >= {"failure_signal", "policy_following"}
        assert split_families["heldout"] >= {"impossible_transition", "tool_sequence"}
        assert split_families["regression"] >= {"promoted_behavior", "exact_eval"}
        assert coverage["family_split_counts"]["failure_signal"] == {
            "train": 1,
            "heldout": 0,
            "regression": 0,
        }
        assert coverage["environment_family_matrix"]["coding_micro"]["failure_signal"][
            "train"
        ] == 1
        assert {"name": "failure_signal", "split": "heldout"} in coverage[
            "missing_family_splits"
        ]
        assert coverage["coverage_digest"]


def test_suite_and_evaluator_digests_are_stable_and_evaluator_sensitive() -> None:
    evaluator = {"type": "contains", "expected": "heldout"}
    same_evaluator_reordered = {"expected": "heldout", "type": "contains"}
    changed_evaluator = {"type": "contains", "expected": "regression"}

    assert evaluator_digest(evaluator) == evaluator_digest(same_evaluator_reordered)
    assert evaluator_digest(evaluator) != evaluator_digest(changed_evaluator)

    split_rows = {
        "train": [source_task("train-task", "train", evaluator)],
        "heldout": [source_task("heldout-task", "heldout", same_evaluator_reordered)],
        "regression": [source_task("regression-task", "regression", evaluator)],
    }
    same_split_rows_reordered = {
        "train": [source_task_reordered("train-task", "train", same_evaluator_reordered)],
        "heldout": [source_task_reordered("heldout-task", "heldout", evaluator)],
        "regression": [source_task_reordered("regression-task", "regression", evaluator)],
    }
    changed_split_rows = {
        **split_rows,
        "heldout": [source_task("heldout-task", "heldout", changed_evaluator)],
    }
    manifest = {
        "name": "digest-suite",
        "suite_version": "digest-suite.1",
        "source_path": "/tmp/source-a",
        "suite_digest": "old-digest",
    }
    same_manifest_reordered = {
        "suite_digest": "new-digest",
        "source_path": "/tmp/source-b",
        "suite_version": "digest-suite.1",
        "name": "digest-suite",
    }
    gate_policy = {"heldout": {"min_pass_rate_delta": 0}}

    base_digest = suite_digest(manifest, split_rows, gate_policy)
    assert base_digest == suite_digest(same_manifest_reordered, same_split_rows_reordered, gate_policy)
    assert base_digest != suite_digest(manifest, changed_split_rows, gate_policy)


def test_malformed_benchmark_source_invalid_jsonl_reports_path_and_line(
    tmp_path: Path, capsys
) -> None:
    with working_dir(tmp_path):
        source = tmp_path / "benchmarks" / "bad-json" / "sources"
        write_source_split(source, "train", ['{"id": "bad-task"'])
        write_source_split(source, "heldout", [valid_task_line("heldout-task", "heldout")])
        write_source_split(source, "regression", [valid_task_line("regression-task", "regression")])

        assert main(["benchmark", "init", "--name", "bad-json", "--profile", "bad-json"]) == 1
        output = capsys.readouterr()
        assert "Invalid JSONL at" in output.err
        assert "bad-json/sources/train/tasks.jsonl:1" in output.err


def test_malformed_benchmark_source_rejects_missing_eval(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        source = tmp_path / "benchmarks" / "missing-eval" / "sources"
        missing_eval = {
            "id": "missing-eval-task",
            "split": "train",
            "instruction": "Return heldout.",
        }
        write_source_split(source, "train", [json.dumps(missing_eval, sort_keys=True)])
        write_source_split(source, "heldout", [valid_task_line("heldout-task", "heldout")])
        write_source_split(source, "regression", [valid_task_line("regression-task", "regression")])

        assert (
            main(
                [
                    "benchmark",
                    "init",
                    "--name",
                    "missing-eval",
                    "--profile",
                    "missing-eval",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "Task missing-eval-task" in output.err
        assert "needs instruction and eval" in output.err


def test_malformed_benchmark_source_rejects_duplicate_task_ids(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        source = tmp_path / "benchmarks" / "duplicate-ids" / "sources"
        write_source_split(
            source,
            "train",
            [
                valid_task_line("duplicate-task", "train"),
                valid_task_line("duplicate-task", "train"),
            ],
        )
        write_source_split(source, "heldout", [valid_task_line("heldout-task", "heldout")])
        write_source_split(source, "regression", [valid_task_line("regression-task", "regression")])

        assert (
            main(
                [
                    "benchmark",
                    "init",
                    "--name",
                    "duplicate-ids",
                    "--profile",
                    "duplicate-ids",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "Duplicate task id duplicate-task in train split" in output.err


def test_cli_main_smoke_for_benchmark_commands(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        init_output = capsys.readouterr()
        assert "Initialized benchmark at" in init_output.out
        assert init_output.err == ""

        assert main(["benchmark", "run", "--split", "regression", "--mock"]) == 0
        run_output = capsys.readouterr()
        assert "Wrote benchmark run artifacts to" in run_output.out
        assert "(synthetic/regression/H0)" in run_output.out
        assert run_output.err == ""


def latest_run_dir(path: Path) -> Path:
    return sorted((path / ".rsi" / "runs").iterdir())[-1]


def write_source_split(source: Path, split: str, lines: list[str]) -> None:
    split_dir = source / split
    split_dir.mkdir(parents=True, exist_ok=True)
    (split_dir / "tasks.jsonl").write_text("\n".join(lines) + "\n")


def valid_task_line(task_id: str, split: str) -> str:
    return json.dumps(
        {
            "id": task_id,
            "split": split,
            "environment": "knowledge_work",
            "family": "smoke",
            "instruction": "Return heldout.",
            "eval": {"type": "contains", "expected": "heldout"},
        },
        sort_keys=True,
    )


def source_task(task_id: str, split: str, evaluator: dict[str, str]) -> dict[str, object]:
    return {
        "id": task_id,
        "split": split,
        "suite_version": "digest-suite.1",
        "environment": "knowledge_work",
        "family": "digest",
        "instruction": "Return heldout.",
        "eval": evaluator,
        "evaluator_digest": evaluator_digest(evaluator),
    }


def source_task_reordered(task_id: str, split: str, evaluator: dict[str, str]) -> dict[str, object]:
    return {
        "evaluator_digest": evaluator_digest(evaluator),
        "eval": evaluator,
        "instruction": "Return heldout.",
        "family": "digest",
        "environment": "knowledge_work",
        "suite_version": "digest-suite.1",
        "split": split,
        "id": task_id,
    }
