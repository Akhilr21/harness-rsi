from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from harness_rsi.benchmarks import compare_runs, evaluator_digest, gate_candidate
from harness_rsi.cli import main
from harness_rsi.cycle import run_experiment_cycle
from harness_rsi.harness import harness_behavior_digest
from harness_rsi.io import read_json, read_jsonl, write_json
from harness_rsi.versions import (
    create_candidate_version,
    list_harness_versions,
    promote_candidate_version,
)


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


def test_source_benchmark_profile_materializes_sim_v0(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        root = tmp_path / ".rsi" / "benchmarks" / "sim-v0"
        manifest = read_json(root / "manifest.json")
        assert manifest["profile"] == "sim-v0"
        assert manifest["suite_version"] == "sim-v0.1"
        assert manifest["suite_digest"]
        assert manifest["split_counts"] == {"heldout": 10, "regression": 7, "train": 10}
        assert "world_model_static" in manifest["environments"]
        assert "impossible_transition" in manifest["families"]
        assert (root / "gate_policy.json").exists()
        heldout = read_jsonl(root / "heldout.jsonl")
        heldout_task = next(row for row in heldout if row["id"] == "kw_heldout_decision_001")
        assert heldout_task["split"] == "heldout"
        assert heldout_task["suite_version"] == "sim-v0.1"
        assert heldout_task["evaluator_digest"] == evaluator_digest(heldout_task["eval"])
        coverage = read_json(root / "coverage.json")
        assert coverage["suite_digest"] == manifest["suite_digest"]
        assert coverage["split_counts"] == {"heldout": 10, "regression": 7, "train": 10}
        assert coverage["environment_family_matrix"]["world_model_static"][
            "impossible_transition"
        ]["heldout"] == 1
        assert coverage["coverage_policy"]["fail_on_missing_required"] is True
        assert not coverage["missing_required_cells"]
        assert {
            "environment": "data_ops",
            "family": "schema_reasoning",
            "split": "regression",
            "reason": "Data-ops regression fixtures are deferred until asset-backed schemas are added.",
            "count": 0,
            "status": "waived_missing",
        } in coverage["waived_missing_cells"]
        assert coverage["coverage_digest"]
        assert (tmp_path / ".rsi" / "harnesses" / "H0.json").exists()


def test_benchmark_coverage_command_writes_report(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "coverage", "--benchmark", "sim-v0"]) == 0
        output = capsys.readouterr().out
        assert "Missing required cells: 0" in output
        assert "Waived missing cells: 4" in output
        assert "Unclassified missing cells:" in output
        assert "environment_family_matrix" not in output
        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        assert coverage["task_count"] == 27
        assert coverage["environment_split_counts"]["knowledge_work"] == {
            "heldout": 2,
            "regression": 2,
            "train": 2,
        }
        assert {"name": "data_ops", "split": "regression"} in coverage[
            "missing_environment_splits"
        ]


def test_sim_v0_gate_passes_with_waived_missing_coverage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        baseline_run, candidate_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-2:]
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["decision"] == "promote"
        assert gate["coverage_failures"] == []
        assert gate["coverage_policy_digest"]
        assert gate["waived_missing_cells"]


def test_sim_v0_gate_rejects_missing_required_coverage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["coverage_policy"]["required"].append(
            {
                "environment": "data_ops",
                "family": "schema_reasoning",
                "split": "regression",
                "reason": "Test-only missing required cell.",
            }
        )
        write_json(manifest_path, manifest)
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        baseline_run, candidate_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-2:]
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["pass_rate_delta"] == 0
        assert gate["decision"] == "reject"
        assert gate["coverage_failures"] == [
            {
                "environment": "data_ops",
                "family": "schema_reasoning",
                "split": "regression",
                "reason": "Test-only missing required cell.",
                "count": 0,
                "status": "missing_required",
            }
        ]


def test_coverage_policy_rejects_malformed_required_shape(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["coverage_policy"]["required"] = {"environment": "knowledge_work"}
        write_json(manifest_path, manifest)
        assert main(["benchmark", "coverage", "--benchmark", "sim-v0"]) == 1


def test_source_benchmark_profile_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_minimal_source_profile(
            tmp_path / "benchmarks" / "bad-profile",
            train_rows=[
                {
                    "id": "duplicate",
                    "instruction": "Return yes.",
                    "eval": {"type": "exact", "expected": "yes"},
                },
                {
                    "id": "duplicate",
                    "instruction": "Return no.",
                    "eval": {"type": "exact", "expected": "no"},
                },
            ],
        )
        assert main(["benchmark", "init", "--name", "bad", "--profile", "bad-profile"]) == 1


def test_sim_v0_runs_record_suite_metadata(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json")
        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        results = read_json(sorted((tmp_path / ".rsi" / "runs").iterdir())[-1] / "results.json")
        assert results["metadata"]["suite_version"] == "sim-v0.1"
        assert results["metadata"]["suite_digest"] == manifest["suite_digest"]
        assert results["metadata"]["coverage_digest"] == coverage["coverage_digest"]


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
        assert results["metrics"]["attempts"] == len(results["results"])
        assert results["metrics"]["tool_calls"] == 0
        assert results["metrics"]["cost_usd"] is None
        assert results["duration_ms"] >= 0
        assert {item["environment"] for item in results["results"]} >= {
            "knowledge_work",
            "world_model",
        }
        assert_environment_rollup_reconciles(results)


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
        assert comparison["candidate_harness_digest"]
        assert comparison["pass_rate_delta"] == 0
        assert comparison["metric_deltas"]["attempts"] == 0
        assert comparison["metric_deltas"]["tool_calls"] == 0
        assert comparison["environment_scores"]["knowledge_work"]["task_count"] == 1

        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["decision"] == "promote"
        assert "metric_deltas" in gate
        assert "environment_scores" in gate


def test_gate_allows_configured_regression_drop(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        baseline_run = write_fake_run(tmp_path / "baseline", passed=10, task_count=10)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=9, task_count=10)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0.1,
        )
        gate = read_json(gate_path)
        assert gate["decision"] == "promote"
        assert gate["effective_min_delta"] == -0.1


def test_gate_rejects_environment_drop_with_flat_aggregate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        baseline_run = write_fake_environment_run(
            tmp_path / "baseline",
            first_environment_passed=True,
            second_environment_passed=False,
        )
        candidate_run = write_fake_environment_run(
            tmp_path / "candidate",
            first_environment_passed=False,
            second_environment_passed=True,
        )
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
            max_environment_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["pass_rate_delta"] == 0
        assert gate["decision"] == "reject"
        assert gate["environment_failures"] == [
            {
                "environment": "knowledge_work",
                "max_environment_drop": 0,
                "pass_rate_delta": -1.0,
            }
        ]


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


def test_gate_rejects_missing_required_coverage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        missing = {
            "environment": "knowledge_work",
            "family": "policy_following",
            "split": "heldout",
        }
        write_fake_coverage_report(tmp_path, missing_required=[missing], waived_missing=[])
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)

        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )

        gate = read_json(gate_path)
        assert gate["decision"] == "reject"
        assert gate["coverage_failures"] == [
            {
                **missing,
                "reason": "",
                "count": 0,
                "status": "missing_required",
            }
        ]


def test_gate_allows_waived_missing_coverage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        waiver = {
            "environment": "data_ops",
            "family": "metric_selection",
            "split": "regression",
            "reason": "Covered by heldout until regression data fixtures exist.",
        }
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[waiver])
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)

        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )

        gate = read_json(gate_path)
        assert gate["decision"] == "promote"
        assert gate["coverage_failures"] == []
        assert gate["waived_missing_cells"] == [
            {
                **waiver,
                "count": 0,
                "status": "waived_missing",
            }
        ]


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


def test_create_candidate_version_from_proposal(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = tmp_path / ".rsi" / "proposals" / "proposal-test.json"
        write_json(
            proposal,
            {
                "id": "proposal-test",
                "config_patch": {
                    "prompt_append": "Check heldout behavior before promotion.",
                    "max_retries": 2,
                },
            },
        )

        path = create_candidate_version(
            parent="H0",
            candidate="H1",
            proposal_path=proposal,
        )
        config = read_json(path)
        assert config["id"] == "H1"
        assert config["parent"] == "H0"
        assert config["status"] == "candidate"
        assert config["max_retries"] == 2
        assert "Check heldout behavior" in config["prompt"]
        assert config["lineage"]["proposal"] == str(proposal)


def test_promote_candidate_version_rejects_rejected_gate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(
            tmp_path,
            decision="reject",
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        try:
            promote_candidate_version(
                candidate="H1",
                gate_path=gate,
            )
        except RuntimeError as error:
            assert "rejected gate" in str(error)
        else:
            raise AssertionError("Expected rejected gate to block promotion.")


def test_promote_candidate_version_rejects_parent_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(
            tmp_path,
            baseline_harness="H9",
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        try:
            promote_candidate_version(
                candidate="H1",
                gate_path=gate,
            )
        except RuntimeError as error:
            assert "does not match parent" in str(error)
        else:
            raise AssertionError("Expected parent mismatch rejection.")


def test_promote_candidate_version_rejects_candidate_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(
            tmp_path,
            candidate_harness="H9",
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        try:
            promote_candidate_version(
                candidate="H1",
                gate_path=gate,
            )
        except RuntimeError as error:
            assert "does not match H1" in str(error)
        else:
            raise AssertionError("Expected candidate mismatch rejection.")


def test_create_candidate_version_refuses_overwrite(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        create_candidate_version(
            parent="H0",
            candidate="H1",
            proposal_path=proposal,
        )
        try:
            create_candidate_version(
                parent="H0",
                candidate="H1",
                proposal_path=proposal,
            )
        except RuntimeError as error:
            assert "already exists" in str(error)
        else:
            raise AssertionError("Expected overwrite rejection.")


def test_create_candidate_version_rejects_model_change(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = tmp_path / ".rsi" / "proposals" / "proposal-test.json"
        write_json(
            proposal,
            {
                "id": "proposal-test",
                "config_patch": {"model": "different-model"},
            },
        )
        try:
            create_candidate_version(
                parent="H0",
                candidate="H1",
                proposal_path=proposal,
            )
        except RuntimeError as error:
            assert "cannot change the model" in str(error)
        else:
            raise AssertionError("Expected model-change rejection.")


def test_harness_create_and_promote_cli_lifecycle(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
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
                    str(proposal),
                ]
            )
            == 0
        )
        candidate = read_json(tmp_path / ".rsi" / "harnesses" / "H1.json")
        assert candidate["status"] == "candidate"
        gate = write_gate(tmp_path, candidate_digest=harness_behavior_digest(candidate))
        assert (
            main(
                [
                    "harness",
                    "promote",
                    "--candidate",
                    "H1",
                    "--gate",
                    str(gate),
                ]
            )
            == 0
        )
        versions = read_json(tmp_path / ".rsi" / "harnesses" / "H1.json")
        assert versions["id"] == "H1"
        assert versions["status"] == "promoted"
        assert versions["promoted_from_gate"] == gate.name
        assert versions["lineage"]["pass_rate_delta"] == 0.1


def test_promote_candidate_version_rejects_missing_digest(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(tmp_path)
        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "missing candidate harness digest" in str(error)
        else:
            raise AssertionError("Expected missing digest rejection.")


def test_promote_candidate_version_rejects_digest_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(tmp_path, candidate_digest="not-the-current-candidate")
        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "digest does not match" in str(error)
        else:
            raise AssertionError("Expected digest mismatch rejection.")


def test_harness_list_flags_filename_id_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        h1 = tmp_path / ".rsi" / "harnesses" / "H1.json"
        write_json(h1, read_json(tmp_path / ".rsi" / "harnesses" / "H0.json"))
        versions = list_harness_versions()
        h1_listing = next(item for item in versions if item["name"] == "H1")
        assert h1_listing["declared_id"] == "H0"
        assert h1_listing["id_matches_filename"] is False


def test_experiment_cycle_promotes_candidate_with_composite_gate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        cycle_path = run_experiment_cycle(
            parent="H0",
            candidate="H1",
            benchmark="synthetic",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=True,
        )
        cycle = read_json(cycle_path)
        assert cycle["status"] == "promoted"
        assert {step["name"] for step in cycle["steps"]} >= {
            "train_parent",
            "propose_patch",
            "create_candidate",
            "heldout_gate",
            "regression_gate",
            "composite_gate",
        }
        config = read_json(tmp_path / ".rsi" / "harnesses" / "H1.json")
        assert config["status"] == "promoted"
        assert config["lineage"]["heldout_gate"]
        assert config["lineage"]["regression_gate"]
        assert config["lineage"]["heldout_candidate_run"]
        assert config["lineage"]["regression_candidate_run"]
        assert config["lineage"]["split"] == "heldout+regression"
        proposal = read_json(Path(next(step["proposal"] for step in cycle["steps"] if step["name"] == "propose_patch")))
        assert proposal["evidence"]["metadata"]["split"] == "train"


def test_experiment_cycle_no_promote_keeps_candidate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        cycle_path = run_experiment_cycle(
            parent="H0",
            candidate="H1",
            benchmark="synthetic",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=False,
        )
        cycle = read_json(cycle_path)
        assert cycle["status"] == "rejected"
        assert cycle["rejection_reason"] == "promotion disabled"
        decision = read_json(Path(cycle["decision_artifact"]))
        assert decision["decision"] == "reject"
        assert decision["proposal"]
        assert decision["heldout_gate"]
        assert decision["regression_gate"]
        assert "heldout_pass_rate_delta" in decision["score_deltas"]
        assert "heldout" in decision["metric_deltas"]
        config = read_json(tmp_path / ".rsi" / "harnesses" / "H1.json")
        assert config["status"] == "candidate"


def test_experiment_cycle_records_suite_identity_for_sim_v0(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json")
        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        cycle_path = run_experiment_cycle(
            parent="H0",
            candidate="H1",
            benchmark="sim-v0",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=False,
        )
        cycle = read_json(cycle_path)
        composite_step = next(step for step in cycle["steps"] if step["name"] == "composite_gate")
        composite = read_json(Path(composite_step["gate"]))
        decision = read_json(Path(cycle["decision_artifact"]))
        assert cycle["suite_version"] == "sim-v0.1"
        assert cycle["suite_digest"] == manifest["suite_digest"]
        assert cycle["coverage_digest"] == coverage["coverage_digest"]
        assert composite["suite_digest"] == manifest["suite_digest"]
        assert composite["coverage_digest"] == coverage["coverage_digest"]
        assert composite["heldout_evaluator_digests"]
        assert composite["regression_evaluator_digests"]
        assert decision["suite_digest"] == manifest["suite_digest"]
        assert decision["evaluator_digests"]["heldout"]
        assert decision["evaluator_digests"]["regression"]


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


def write_fake_coverage_report(
    path: Path,
    *,
    missing_required: list[dict[str, str]],
    waived_missing: list[dict[str, str]],
) -> None:
    root = path / ".rsi" / "benchmarks" / "fake"
    write_json(
        root / "manifest.json",
        {
            "name": "fake",
            "coverage_policy": {
                "fail_on_missing_required": True,
                "required": missing_required,
                "waivers": waived_missing,
            },
        },
    )
    write_json(root / "gate_policy.json", {"heldout": {"min_pass_rate_delta": 0}})
    for split in ("train", "heldout", "regression"):
        rows = [
            {
                "id": f"{split}-task",
                "environment": "fake",
                "family": "smoke",
                "instruction": "Return ok.",
                "eval": {"type": "exact", "expected": "ok"},
            }
        ]
        (root / f"{split}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )


def write_minimal_source_profile(path: Path, train_rows: list[dict[str, object]]) -> None:
    write_json(path / "manifest.json", {"id": path.name, "suite_version": f"{path.name}.1"})
    for split in ("train", "heldout", "regression"):
        rows = train_rows if split == "train" else [
            {
                "id": f"{split}-task",
                "instruction": "Return ok.",
                "eval": {"type": "exact", "expected": "ok"},
            }
        ]
        split_dir = path / "sources" / split
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "tasks.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )


def write_fake_environment_run(
    path: Path,
    *,
    first_environment_passed: bool,
    second_environment_passed: bool,
) -> Path:
    path.mkdir(parents=True)
    write_json(path / "harness.snapshot.json", {"model": "gpt-5.5"})
    rows = [
        {
            "task_id": "kw-task",
            "environment": "knowledge_work",
            "passed": first_environment_passed,
            "attempt": 0,
        },
        {
            "task_id": "code-task",
            "environment": "coding_micro",
            "passed": second_environment_passed,
            "attempt": 0,
        },
    ]
    passed = sum(1 for row in rows if row["passed"])
    per_environment = {}
    for row in rows:
        per_environment[row["environment"]] = {
            "tasks": 1,
            "passed": int(row["passed"]),
            "pass_rate": 1.0 if row["passed"] else 0.0,
            "attempts": 1,
            "tool_calls": 0,
        }
    write_json(
        path / "results.json",
        {
            "run_id": path.name,
            "metadata": {"benchmark": "fake", "split": "heldout", "harness": path.name},
            "task_digest": "same-tasks",
            "harness_behavior_digest": f"{path.name}-digest",
            "tasks": len(rows),
            "passed": passed,
            "pass_rate": passed / len(rows),
            "attempts": len(rows),
            "tool_calls": 0,
            "metrics": {
                "attempts": len(rows),
                "tool_calls": 0,
                "duration_ms": 1,
                "cost_usd": None,
            },
            "per_environment": per_environment,
            "results": rows,
        },
    )
    return path


def assert_environment_rollup_reconciles(results: dict[str, object]) -> None:
    per_environment = results["per_environment"]
    assert isinstance(per_environment, dict)
    assert sum(item["tasks"] for item in per_environment.values()) == results["tasks"]
    assert sum(item["passed"] for item in per_environment.values()) == results["passed"]
    assert sum(item["attempts"] for item in per_environment.values()) == results["attempts"]
    assert sum(item["tool_calls"] for item in per_environment.values()) == results["tool_calls"]


def write_proposal(path: Path) -> Path:
    proposal = path / ".rsi" / "proposals" / "proposal-test.json"
    write_json(
        proposal,
        {
            "id": "proposal-test",
            "config_patch": {"prompt_append": "Use the gate evidence."},
        },
    )
    return proposal


def write_gate(
    path: Path,
    *,
    decision: str = "promote",
    baseline_harness: str = "H0",
    candidate_harness: str = "H1",
    candidate_digest: str | None = None,
) -> Path:
    gate = path / ".rsi" / "gates" / "gate-test.json"
    payload = {
        "decision": decision,
        "baseline_harness": baseline_harness,
        "candidate_harness": candidate_harness,
        "baseline_run": "baseline",
        "candidate_run": "candidate",
        "benchmark": "synthetic",
        "split": "heldout",
        "pass_rate_delta": 0.1,
    }
    if candidate_digest is not None:
        payload["candidate_harness_digest"] = candidate_digest
    write_json(gate, payload)
    return gate
