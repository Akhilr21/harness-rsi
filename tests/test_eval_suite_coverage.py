from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from harness_rsi.benchmarks import compare_runs
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
