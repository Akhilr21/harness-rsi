from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import harness_rsi.improve as improve_module
from harness_rsi.benchmarks import compare_runs, digest_payload, evaluator_digest, gate_candidate
from harness_rsi.cli import main
from harness_rsi.cycle import (
    run_experiment_cycle,
    run_experiment_stability,
    write_composite_gate,
    write_split_isolation_audit,
)
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
        assert manifest["split_counts"] == {"heldout": 12, "regression": 9, "train": 12}
        assert "world_model_static" in manifest["environments"]
        assert "impossible_transition" in manifest["families"]
        assert "rollout_summarization" in manifest["families"]
        assert "reset_replay" in manifest["families"]
        assert (root / "gate_policy.json").exists()
        gate_policy = read_json(root / "gate_policy.json")
        assert gate_policy["heldout"]["max_attempt_delta"] == 0
        assert gate_policy["heldout"]["max_tool_call_delta"] == 0
        assert gate_policy["heldout"]["fail_on_overdue_waivers"] is True
        assert gate_policy["heldout"]["waiver_review_as_of"] == "2026-06-19"
        assert gate_policy["heldout"]["waiver_due_within_days"] == 30
        assert "max_duration_ms_delta" not in gate_policy["heldout"]
        assert "max_cost_usd_delta" not in gate_policy["heldout"]
        assert gate_policy["regression"]["max_attempt_delta"] == 0
        assert gate_policy["regression"]["max_tool_call_delta"] == 0
        assert gate_policy["regression"]["fail_on_overdue_waivers"] is True
        assert gate_policy["regression"]["waiver_review_as_of"] == "2026-06-19"
        assert gate_policy["regression"]["waiver_due_within_days"] == 30
        assert "max_duration_ms_delta" not in gate_policy["regression"]
        assert "max_cost_usd_delta" not in gate_policy["regression"]
        heldout = read_jsonl(root / "heldout.jsonl")
        heldout_task = next(row for row in heldout if row["id"] == "kw_heldout_decision_001")
        assert heldout_task["split"] == "heldout"
        assert heldout_task["suite_version"] == "sim-v0.1"
        assert heldout_task["evaluator_digest"] == evaluator_digest(heldout_task["eval"])
        coverage = read_json(root / "coverage.json")
        assert coverage["suite_digest"] == manifest["suite_digest"]
        assert coverage["split_counts"] == {"heldout": 12, "regression": 9, "train": 12}
        assert coverage["environment_family_matrix"]["world_model_static"][
            "impossible_transition"
        ]["heldout"] == 1
        assert coverage["environment_family_matrix"]["world_model_static"][
            "rollout_summarization"
        ] == {"heldout": 1, "regression": 0, "train": 1}
        assert coverage["environment_family_matrix"]["world_model_static"][
            "reset_replay"
        ] == {"heldout": 1, "regression": 1, "train": 1}
        assert {
            "environment": "world_model_static",
            "family": "reset_replay",
            "split": "regression",
            "reason": "World-model reset/replay discipline must not regress once introduced.",
            "count": 1,
            "status": "covered_required",
        } in coverage["required_cells"]
        assert coverage["coverage_policy"]["fail_on_missing_required"] is True
        assert not coverage["missing_required_cells"]
        assert {
            "environment": "data_ops",
            "family": "schema_reasoning",
            "split": "regression",
            "reason": "Data-ops regression fixtures are deferred until asset-backed schemas are added.",
            "owner": "data-evals",
            "tracking_ref": "CM-0012",
            "review_by": "2026-09-30",
            "expires_when": "Asset-backed schema fixtures land in sim-v0.",
            "count": 0,
            "status": "waived_missing",
        } in coverage["waived_missing_cells"]
        assert coverage["coverage_digest"]
        assert (tmp_path / ".rsi" / "harnesses" / "H0.json").exists()


def test_external_adapter_smoke_profile_materializes_metadata(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "external-adapter-smoke-v0"]) == 0
        root = tmp_path / ".rsi" / "benchmarks" / "external-adapter-smoke-v0"
        manifest = read_json(root / "manifest.json")
        assert manifest["suite_version"] == "external-adapter-smoke-v0.1"
        assert manifest["adapter_contract_version"] == "adapter-contract-v0.1"
        assert manifest["split_counts"] == {"heldout": 3, "regression": 3, "train": 3}
        assert manifest["families"] == [
            "issue_patch_planning",
            "terminal_task_planning",
            "tool_agent_user",
        ]
        heldout = read_jsonl(root / "heldout.jsonl")
        terminal_task = next(
            row for row in heldout if row["id"] == "adapter_heldout_terminal_metadata_001"
        )
        assert terminal_task["external_adapter"] == {
            "external_id": "tb-heldout-terminal-metadata",
            "fixture_version": "terminal-bench-smoke-v0.1",
            "kind": "terminal",
            "mode": "read_only",
            "name": "terminal-bench",
            "source_url": "https://www.tbench.ai/",
        }
        assert terminal_task["split"] == "heldout"
        assert terminal_task["evaluator_digest"] == evaluator_digest(terminal_task["eval"])
        coverage = read_json(root / "coverage.json")
        assert not coverage["missing_required_cells"]
        assert coverage["coverage_policy"]["fail_on_missing_required"] is True


def test_benchmark_adapters_command_writes_read_only_report(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "external-adapter-smoke-v0"]) == 0
        coverage_before = read_json(
            tmp_path / ".rsi" / "benchmarks" / "external-adapter-smoke-v0" / "coverage.json"
        )
        gate_policy_before = read_json(
            tmp_path / ".rsi" / "benchmarks" / "external-adapter-smoke-v0" / "gate_policy.json"
        )
        assert (
            main(["benchmark", "adapters", "--benchmark", "external-adapter-smoke-v0"])
            == 0
        )
        output = capsys.readouterr().out
        assert "Wrote adapter report to" in output
        assert "Status: pass" in output
        assert "Adapter tasks: 9" in output
        root = tmp_path / ".rsi" / "benchmarks" / "external-adapter-smoke-v0"
        report = read_json(root / "adapter_report.json")
        assert report["status"] == "pass"
        assert report["read_only"] is True
        assert report["gate_semantics_changed"] is False
        assert report["task_count"] == 9
        assert report["external_adapter_task_count"] == 9
        assert report["kind_counts"] == {
            "swe_patch": 3,
            "terminal": 3,
            "tool_agent_user": 3,
        }
        assert report["split_counts"] == {"heldout": 3, "regression": 3, "train": 3}
        assert report["fixture_versions"] == {
            "swe-bench": ["swe-bench-smoke-v0.1"],
            "tau2-bench": ["tau2-bench-smoke-v0.1"],
            "terminal-bench": ["terminal-bench-smoke-v0.1"],
        }
        assert report["metadata_failures"] == []
        assert report["adapter_report_digest"]
        assert not (tmp_path / ".rsi" / "runs").exists()
        assert not (tmp_path / ".rsi" / "gates").exists()
        assert read_json(root / "coverage.json") == coverage_before
        assert read_json(root / "gate_policy.json") == gate_policy_before


def test_benchmark_adapters_reads_materialized_copy_only(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        source = tmp_path / "benchmarks" / "adapter-local"
        write_adapter_source_profile(source)
        assert (
            main(
                [
                    "benchmark",
                    "init",
                    "--name",
                    "adapter-local",
                    "--profile",
                    "adapter-local",
                ]
            )
            == 0
        )
        shutil.rmtree(source)
        assert main(["benchmark", "adapters", "--benchmark", "adapter-local"]) == 0
        report = read_json(tmp_path / ".rsi" / "benchmarks" / "adapter-local" / "adapter_report.json")
        assert report["status"] == "pass"
        assert report["external_adapter_task_count"] == 3


def test_benchmark_import_adapters_writes_source_profile_and_materializes(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "frozen-adapter-export.json"
        write_frozen_adapter_export(export)
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "frozen-adapters-v0",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Wrote imported adapter profile to" in output
        assert "Task count: 3" in output
        assert "Gate semantics changed: False" in output
        source_profile = tmp_path / "benchmarks" / "frozen-adapters-v0"
        import_report = read_json(source_profile / "import_report.json")
        assert import_report["status"] == "pass"
        assert import_report["read_only"] is True
        assert import_report["gate_semantics_changed"] is False
        assert import_report["row_count"] == 3
        assert import_report["imported_row_count"] == 3
        assert import_report["rejected_row_count"] == 0
        assert import_report["rejected_rows"] == []
        assert import_report["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        assert import_report["kind_counts"] == {
            "swe_patch": 1,
            "terminal": 1,
            "tool_agent_user": 1,
        }
        assert import_report["adapter_counts"] == {
            "swe-bench": 1,
            "tau2-bench": 1,
            "terminal-bench": 1,
        }
        assert import_report["fixture_versions"] == {
            "swe-bench": ["swe-frozen-v1"],
            "tau2-bench": ["tau-frozen-v1"],
            "terminal-bench": ["terminal-frozen-v1"],
        }
        assert import_report["source_export_digest"]
        assert import_report["import_report_digest"]
        assert not (tmp_path / ".rsi" / "runs").exists()
        assert not (tmp_path / ".rsi" / "gates").exists()

        assert main(["benchmark", "init", "--name", "frozen-adapters-v0"]) == 0
        materialized = tmp_path / ".rsi" / "benchmarks" / "frozen-adapters-v0"
        manifest = read_json(materialized / "manifest.json")
        assert manifest["importer_version"] == "external-adapter-importer-v0.1"
        assert manifest["source_export_digest"] == import_report["source_export_digest"]
        assert manifest["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        heldout = read_jsonl(materialized / "heldout.jsonl")
        assert heldout[0]["external_adapter"] == {
            "external_id": "swe-issue-1",
            "fixture_version": "swe-frozen-v1",
            "kind": "swe_patch",
            "mode": "read_only",
            "name": "swe-bench",
            "source_url": "https://www.swebench.com/SWE-bench/",
        }
        assert heldout[0]["evaluator_digest"] == evaluator_digest(heldout[0]["eval"])
        coverage = read_json(materialized / "coverage.json")
        assert coverage["coverage_policy"]["fail_on_missing_required"] is True
        assert not coverage["missing_required_cells"]

        assert main(["benchmark", "adapters", "--benchmark", "frozen-adapters-v0"]) == 0
        adapter_report = read_json(materialized / "adapter_report.json")
        assert adapter_report["status"] == "pass"
        assert adapter_report["external_adapter_task_count"] == 3
        assert adapter_report["gate_semantics_changed"] is False


def test_benchmark_import_adapters_allows_rejected_rows_with_report(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "partial-export.json"
        rows = frozen_adapter_rows()
        rejected = frozen_adapter_row("bad-row", "train", "terminal-bench", "bad-row")
        del rejected["instruction"]
        del rejected["expected"]
        rows.append(rejected)
        write_frozen_adapter_export(export, rows=rows)

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "partial-adapters",
                    "--allow-rejected-rows",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Status: pass_with_rejections" in output
        assert "Rejected rows: 1" in output

        report = read_json(tmp_path / "benchmarks" / "partial-adapters" / "import_report.json")
        assert report["status"] == "pass_with_rejections"
        assert report["allow_rejects"] is True
        assert report["review_only"] is False
        assert report["source_row_count"] == 4
        assert report["row_count"] == 4
        assert report["accepted_task_count"] == 3
        assert report["imported_row_count"] == 3
        assert report["rejected_row_count"] == 1
        assert report["rejection_reason_counts"] == {"invalid_row": 1}
        assert report["accepted_rows_digest"]
        assert report["rejected_rows_digest"]
        assert report["rejected_rows"][0]["status"] == "rejected"
        assert report["rejected_rows"][0]["reason"] == "invalid_row"
        assert report["rejected_rows"][0]["source_path"] == "partial-export.json"
        assert report["rejected_rows"][0]["line_number"] is None
        assert "instruction-like text" in report["rejected_rows"][0]["message"]
        assert report["rejected_rows"][0]["external_id"] == "bad-row"
        assert report["rejected_rows"][0]["source_row_digest"]
        assert "instruction" not in report["rejected_rows"][0]

        assert main(["benchmark", "init", "--name", "partial-adapters"]) == 0
        assert main(["benchmark", "adapters", "--benchmark", "partial-adapters"]) == 0
        adapter_report = read_json(
            tmp_path / ".rsi" / "benchmarks" / "partial-adapters" / "adapter_report.json"
        )
        assert adapter_report["status"] == "pass"
        assert adapter_report["external_adapter_task_count"] == 3
        assert not (tmp_path / ".rsi" / "runs").exists()
        assert not (tmp_path / ".rsi" / "gates").exists()


def test_benchmark_import_adapters_preserves_jsonl_rejected_row_source_location(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export_dir = tmp_path / "jsonl-directory-export"
        export_file = export_dir / "partitions" / "adapter.jsonl"
        export_file.parent.mkdir(parents=True)
        rows = [
            frozen_adapter_row(
                "jsonl-train",
                "train",
                "terminal-bench",
                "jsonl-train",
                fixture_version="jsonl-source-v1",
            ),
            frozen_adapter_row(
                "jsonl-bad",
                "heldout",
                "swe-bench",
                "jsonl-bad",
                fixture_version="jsonl-source-v1",
            ),
            frozen_adapter_row(
                "jsonl-heldout",
                "heldout",
                "swe-bench",
                "jsonl-heldout",
                fixture_version="jsonl-source-v1",
            ),
            frozen_adapter_row(
                "jsonl-regression",
                "regression",
                "tau2-bench",
                "jsonl-regression",
                fixture_version="jsonl-source-v1",
            ),
        ]
        del rows[1]["instruction"]
        del rows[1]["expected"]
        export_file.write_text(
            "\n".join(
                [
                    json.dumps(rows[0], sort_keys=True),
                    "",
                    json.dumps(rows[1], sort_keys=True),
                    json.dumps(rows[2], sort_keys=True),
                    json.dumps(rows[3], sort_keys=True),
                ]
            )
            + "\n"
        )

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export_dir),
                    "--profile",
                    "jsonl-directory-adapters",
                    "--allow-rejected-rows",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Status: pass_with_rejections" in output
        report = read_json(
            tmp_path / "benchmarks" / "jsonl-directory-adapters" / "import_report.json"
        )
        assert report["status"] == "pass_with_rejections"
        assert report["source_export_name"] == "jsonl-directory-export"
        assert report["source_row_count"] == 4
        assert report["imported_row_count"] == 3
        assert report["rejected_row_count"] == 1
        rejected = report["rejected_rows"][0]
        assert rejected["source_path"] == "partitions/adapter.jsonl"
        assert rejected["line_number"] == 3
        assert rejected["row_index"] == 2
        assert rejected["external_id"] == "jsonl-bad"
        assert "__harness_rsi_source_location" not in rejected["row_keys"]

        accepted_rows = read_jsonl(
            tmp_path
            / "benchmarks"
            / "jsonl-directory-adapters"
            / "sources"
            / "train"
            / "terminal-bench.jsonl"
        )
        assert "__harness_rsi_source_location" not in accepted_rows[0]
        assert main(["benchmark", "init", "--name", "jsonl-directory-adapters"]) == 0
        assert main(["benchmark", "adapters", "--benchmark", "jsonl-directory-adapters"]) == 0
        adapter_report = read_json(
            tmp_path
            / ".rsi"
            / "benchmarks"
            / "jsonl-directory-adapters"
            / "adapter_report.json"
        )
        assert adapter_report["status"] == "pass"
        assert adapter_report["external_adapter_task_count"] == 3


def test_benchmark_import_adapters_rejects_bad_rows_by_default(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "strict-reject-export.json"
        rows = frozen_adapter_rows()
        rejected = frozen_adapter_row("bad-row", "train", "terminal-bench", "bad-row")
        del rejected["instruction"]
        del rejected["expected"]
        rows.append(rejected)
        write_frozen_adapter_export(export, rows=rows)

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "strict-reject",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "rejected row" in output.err
        assert "instruction-like text" in output.err
        assert not (tmp_path / "benchmarks" / "strict-reject").exists()
        review = read_json(
            tmp_path / "benchmarks" / "_import_reviews" / "strict-reject" / "import_review.json"
        )
        assert review["status"] == "review"
        assert review["review_only"] is True
        assert review["rejected_row_count"] == 1
        assert review["rejection_reason_counts"] == {"invalid_row": 1}


def test_benchmark_import_adapters_uses_split_map_for_missing_splits(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "split-map-export.json"
        rows = frozen_adapter_rows()
        for row in rows:
            del row["split"]
        write_frozen_adapter_export(export, rows=rows)
        split_map = tmp_path / "split-map.json"
        write_json(
            split_map,
            {
                "splits": {
                    "tb-task-1": "train",
                    "swe-issue-1": "heldout",
                    "tau-dialog-1": "regression",
                    "unused-external-id": "train",
                }
            },
        )

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "split-map-adapters",
                    "--split-map",
                    str(split_map),
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Split map: split-map.json used=3 unused=1" in output
        report = read_json(tmp_path / "benchmarks" / "split-map-adapters" / "import_report.json")
        assert report["status"] == "pass"
        assert report["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        assert report["split_map"]["provided"] is True
        assert report["split_map"]["source_name"] == "split-map.json"
        assert report["split_map"]["source_digest"]
        assert report["split_map"]["entry_count"] == 4
        assert report["split_map"]["used_count"] == 3
        assert report["split_map"]["unused_count"] == 1
        assert report["split_map"]["unused_keys"] == ["unused-external-id"]

        assert main(["benchmark", "init", "--name", "split-map-adapters"]) == 0
        materialized = tmp_path / ".rsi" / "benchmarks" / "split-map-adapters"
        manifest = read_json(materialized / "manifest.json")
        assert manifest["split_map"]["used_count"] == 3
        assert manifest["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}


def test_benchmark_import_adapters_materializes_swe_bench_lite_smoke_fixture(
    tmp_path: Path,
    capsys,
) -> None:
    assert_frozen_export_smoke_fixture(
        tmp_path,
        capsys,
        profile="swe-bench-lite-smoke-v0",
        suite_version="swe-bench-lite-smoke-v0.1",
        adapter_name="swe-bench",
        adapter_kind="swe_patch",
        fixture_version="swe-bench-lite-smoke-v0.1",
        source_url="https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite",
        environment="coding_micro",
        family="issue_patch_planning",
        heldout_external_id="sqlfluff__sqlfluff-2419",
        heldout_source="princeton-nlp/SWE-bench_Lite/test/sqlfluff__sqlfluff-2419",
        candidate_prefix="DryRunSwe",
    )


def test_benchmark_import_adapters_materializes_terminal_bench_smoke_fixture(
    tmp_path: Path,
    capsys,
) -> None:
    assert_frozen_export_smoke_fixture(
        tmp_path,
        capsys,
        profile="terminal-bench-smoke-v0",
        suite_version="terminal-bench-smoke-v0.1",
        adapter_name="terminal-bench",
        adapter_kind="terminal",
        fixture_version="terminal-bench-smoke-v0.1",
        source_url="https://github.com/harbor-framework/terminal-bench",
        environment="terminal_ops",
        family="terminal_task_planning",
        heldout_external_id="original-tasks/analyze-access-logs",
        heldout_source="harbor-framework/terminal-bench/original-tasks/analyze-access-logs",
        candidate_prefix="DryRunTerminal",
    )


def test_benchmark_import_adapters_materializes_tau2_bench_retail_smoke_fixture(
    tmp_path: Path,
    capsys,
) -> None:
    assert_frozen_export_smoke_fixture(
        tmp_path,
        capsys,
        profile="tau2-bench-retail-smoke-v0",
        suite_version="tau2-bench-retail-smoke-v0.1",
        adapter_name="tau2-bench",
        adapter_kind="tool_agent_user",
        fixture_version="tau2-bench-retail-smoke-v0.1",
        source_url="https://github.com/sierra-research/tau2-bench",
        environment="customer_support",
        family="tool_agent_user",
        heldout_external_id="retail:5",
        heldout_source="sierra-research/tau2-bench/data/tau2/domains/retail/tasks.json#5",
        candidate_prefix="DryRunTau",
    )


def assert_frozen_export_smoke_fixture(
    tmp_path: Path,
    capsys,
    *,
    profile: str,
    suite_version: str,
    adapter_name: str,
    adapter_kind: str,
    fixture_version: str,
    source_url: str,
    environment: str,
    family: str,
    heldout_external_id: str,
    heldout_source: str,
    candidate_prefix: str,
) -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "_frozen_exports"
        / profile
    )
    with working_dir(tmp_path):
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(fixture / "tasks.json"),
                    "--profile",
                    profile,
                    "--split-map",
                    str(fixture / "split-map.json"),
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Task count: 3" in output
        assert "Split map: split-map.json used=3 unused=0" in output

        source_profile = tmp_path / "benchmarks" / profile
        import_report = read_json(source_profile / "import_report.json")
        assert import_report["status"] == "pass"
        assert import_report["read_only"] is True
        assert import_report["gate_semantics_changed"] is False
        assert import_report["suite_version"] == suite_version
        assert import_report["source_export_name"] == "tasks.json"
        assert import_report["source_row_count"] == 3
        assert import_report["imported_row_count"] == 3
        assert import_report["rejected_row_count"] == 0
        assert import_report["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        assert import_report["kind_counts"] == {adapter_kind: 3}
        assert import_report["adapter_counts"] == {adapter_name: 3}
        assert import_report["fixture_versions"] == {adapter_name: [fixture_version]}
        assert import_report["split_map"]["provided"] is True
        assert import_report["split_map"]["used_count"] == 3
        assert import_report["split_map"]["unused_count"] == 0
        assert import_report["metadata_failures"] == []
        assert import_report["source_export_digest"]
        assert import_report["import_report_digest"]
        assert not (tmp_path / ".rsi" / "runs").exists()
        assert not (tmp_path / ".rsi" / "gates").exists()

        assert main(["benchmark", "init", "--name", profile]) == 0
        materialized = tmp_path / ".rsi" / "benchmarks" / profile
        manifest = read_json(materialized / "manifest.json")
        assert manifest["suite_version"] == suite_version
        assert manifest["source_export_digest"] == import_report["source_export_digest"]
        assert manifest["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        assert manifest["environments"] == [environment]
        assert manifest["families"] == [family]
        assert manifest["split_map"]["used_count"] == 3
        heldout = read_jsonl(materialized / "heldout.jsonl")
        assert heldout[0]["external_adapter"] == {
            "external_id": heldout_external_id,
            "fixture_version": fixture_version,
            "kind": adapter_kind,
            "mode": "read_only",
            "name": adapter_name,
            "source_url": source_url,
        }
        assert heldout[0]["source"] == heldout_source
        assert heldout[0]["suite_version"] == suite_version
        assert heldout[0]["evaluator_digest"] == evaluator_digest(heldout[0]["eval"])
        coverage = read_json(materialized / "coverage.json")
        assert coverage["missing_required_cells"] == []
        assert coverage["coverage_policy"]["fail_on_missing_required"] is True

        assert main(["benchmark", "adapters", "--benchmark", profile]) == 0
        adapter_report = read_json(materialized / "adapter_report.json")
        assert adapter_report["status"] == "pass"
        assert adapter_report["read_only"] is True
        assert adapter_report["gate_semantics_changed"] is False
        assert adapter_report["external_adapter_task_count"] == 3
        assert adapter_report["metadata_failures"] == []

        stability_path = run_experiment_stability(
            parent="H0",
            candidate_prefix=candidate_prefix,
            first_candidate_index=1,
            cycles=1,
            benchmark=profile,
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=False,
        )
        stability = read_json(stability_path)
        assert stability["status"] == "pass"
        assert stability["validation_status"] == "pass"
        assert stability["promotion_status"] == "not_requested"
        assert stability["final_parent"] == "H0"
        assert stability["completed_cycles"] == 1
        assert stability["cycles"][0]["validation_passed"] is True
        assert read_json(tmp_path / ".rsi" / "harnesses" / f"{candidate_prefix}1.json")[
            "status"
        ] == "candidate"


def test_benchmark_import_adapters_maps_raw_split_labels(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "raw-split-export.json"
        rows = frozen_adapter_rows()
        rows[0]["split"] = "fit"
        rows[1]["split"] = "dev"
        rows[2]["split"] = "test"
        write_frozen_adapter_export(export, rows=rows)
        split_map = tmp_path / "raw-split-map.json"
        write_json(split_map, {"splits": {"fit": "train", "dev": "heldout", "test": "regression"}})

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "raw-split-adapters",
                    "--split-map",
                    str(split_map),
                ]
            )
            == 0
        )
        report = read_json(tmp_path / "benchmarks" / "raw-split-adapters" / "import_report.json")
        assert report["status"] == "pass"
        assert report["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}
        assert report["split_map"]["used_count"] == 3
        assert report["split_map_digest"] == report["split_map"]["source_digest"]


def test_benchmark_import_adapters_review_split_map_writes_review_only(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "review-export.json"
        rows = frozen_adapter_rows()
        rows[1]["split"] = "dev"
        write_frozen_adapter_export(export, rows=rows)
        split_map = tmp_path / "review-map.json"
        write_json(split_map, {"splits": {"dev": "heldout"}})

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "review-adapters",
                    "--split-map",
                    str(split_map),
                    "--review-split-map",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Wrote adapter import review" in output
        assert not (tmp_path / "benchmarks" / "review-adapters").exists()
        review = read_json(
            tmp_path / "benchmarks" / "_import_reviews" / "review-adapters" / "import_review.json"
        )
        assert review["status"] == "review"
        assert review["review_only"] is True
        assert review["split_map"]["used_count"] == 1
        assert review["split_counts"] == {"heldout": 1, "regression": 1, "train": 1}


def test_benchmark_import_adapters_rejects_split_map_conflicts(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "split-conflict-export.json"
        write_frozen_adapter_export(export)
        split_map = tmp_path / "split-map.json"
        write_json(split_map, {"splits": {"terminal-bench:tb-task-1": "heldout"}})

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "split-conflict",
                    "--split-map",
                    str(split_map),
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "conflicts with split map" in output.err
        assert not (tmp_path / "benchmarks" / "split-conflict").exists()


def test_benchmark_import_adapters_rejects_missing_required_split(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "missing-regression.json"
        write_frozen_adapter_export(
            export,
            rows=[
                frozen_adapter_row("tb-train", "train", "terminal-bench", "terminal-1"),
                frozen_adapter_row("swe-heldout", "heldout", "swe-bench", "swe-1"),
            ],
        )
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "missing-regression",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "missing required split" in output.err
        assert not (tmp_path / "benchmarks" / "missing-regression").exists()


def test_benchmark_import_adapters_rejects_live_mode(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "live-mode.json"
        rows = frozen_adapter_rows()
        rows[0]["mode"] = "runner"
        write_frozen_adapter_export(export, rows=rows)
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "live-mode",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "mode: read_only" in output.err
        assert not (tmp_path / "benchmarks" / "live-mode").exists()


def test_benchmark_import_adapters_rejects_duplicate_external_ids(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "duplicate-external-id.json"
        rows = frozen_adapter_rows()
        rows[1]["external_id"] = rows[0]["external_id"]
        rows[1]["benchmark"] = rows[0]["benchmark"]
        write_frozen_adapter_export(export, rows=rows)
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "duplicate-external-id",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "Duplicate imported external id" in output.err
        assert not (tmp_path / "benchmarks" / "duplicate-external-id").exists()


def test_benchmark_import_adapters_requires_force_for_existing_profile(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "frozen-adapter-export.json"
        write_frozen_adapter_export(export)
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "force-adapters",
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "force-adapters",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "already exists" in output.err
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "force-adapters",
                    "--force",
                ]
            )
            == 0
        )


def test_benchmark_import_adapters_accepts_top_level_json_list(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "frozen-list-export.json"
        export.write_text(json.dumps(frozen_adapter_rows(), sort_keys=True) + "\n")
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "list-export",
                ]
            )
            == 0
        )
        report = read_json(tmp_path / "benchmarks" / "list-export" / "import_report.json")
        assert report["status"] == "pass"
        assert report["task_count"] == 3


def test_benchmark_import_adapters_json_list_rejections_remain_file_scoped(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "frozen-list-export.json"
        rows = frozen_adapter_rows()
        rejected = frozen_adapter_row("bad-list-row", "train", "terminal-bench", "bad-list-row")
        del rejected["instruction"]
        del rejected["expected"]
        rows.append(rejected)
        export.write_text(json.dumps(rows, sort_keys=True) + "\n")

        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "list-export-partial",
                    "--allow-rejected-rows",
                ]
            )
            == 0
        )
        report = read_json(tmp_path / "benchmarks" / "list-export-partial" / "import_report.json")
        assert report["status"] == "pass_with_rejections"
        assert report["rejected_row_count"] == 1
        assert report["rejected_rows"][0]["source_path"] == "frozen-list-export.json"
        assert report["rejected_rows"][0]["line_number"] is None


def test_benchmark_import_adapters_rejects_unsafe_profile_path(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        export = tmp_path / "frozen-adapter-export.json"
        write_frozen_adapter_export(export)
        assert (
            main(
                [
                    "benchmark",
                    "import-adapters",
                    "--source",
                    str(export),
                    "--profile",
                    "../escape",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "Invalid benchmark source profile name" in output.err
        assert not (tmp_path / "escape").exists()


def test_benchmark_coverage_command_writes_report(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "coverage", "--benchmark", "sim-v0"]) == 0
        output = capsys.readouterr().out
        assert "Task count: 33" in output
        assert "Required cells: 14" in output
        assert "Missing required cells: 0" in output
        assert "Waived missing cells: 4" in output
        assert "Unclassified missing cells:" in output
        assert "environment_family_matrix" not in output
        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        assert coverage["task_count"] == 33
        assert coverage["environment_split_counts"]["knowledge_work"] == {
            "heldout": 2,
            "regression": 2,
            "train": 2,
        }
        assert {"name": "data_ops", "split": "regression"} in coverage[
            "missing_environment_splits"
        ]


def test_benchmark_waivers_command_writes_lifecycle_report(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert (
            main(
                [
                    "benchmark",
                    "waivers",
                    "--benchmark",
                    "sim-v0",
                    "--as-of",
                    "2026-06-19",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Wrote waiver lifecycle report to" in output
        assert "Waivers: 4" in output
        assert "Waived missing cells: 4" in output
        assert "Waived covered cells: 0" in output
        assert "Active missing: 4" in output
        assert "Retire candidates: 0" in output
        assert "Review status: overdue=0, due_soon=0, scheduled=4" in output
        assert "Next review: 2026-09-30" in output
        assert "Owners: coding-evals=1, data-evals=1, eval-suite=2" in output
        assert "Review dates: 2026-09-30=4" in output
        assert "Coverage digest matches stored: True" in output
        assert "waiver_lifecycle_digest" not in output

        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        report = read_json(
            tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "waiver_lifecycle.json"
        )
        assert report["benchmark"] == "sim-v0"
        assert report["coverage_digest"] == coverage["coverage_digest"]
        assert report["stored_coverage_digest"] == coverage["coverage_digest"]
        assert report["coverage_digest_matches_stored"] is True
        assert report["due_within_days"] == 30
        assert report["waiver_count"] == 4
        assert report["waived_missing_count"] == 4
        assert report["waived_covered_count"] == 0
        assert report["active_missing_count"] == 4
        assert report["retire_candidate_count"] == 0
        assert report["review_due_count"] == 0
        assert report["review_status_counts"] == {
            "overdue": 0,
            "due_soon": 0,
            "scheduled": 4,
        }
        assert report["next_review_by"] == "2026-09-30"
        assert report["by_owner"]["eval-suite"] == {
            "count": 2,
            "active_missing_count": 2,
            "retire_candidate_count": 0,
            "review_due_count": 0,
            "review_status_counts": {"overdue": 0, "due_soon": 0, "scheduled": 2},
            "waivers": [
                "mechanics/exact_eval/train",
                "mechanics/exact_eval/heldout",
            ],
        }
        assert report["by_review_date"]["2026-09-30"]["count"] == 4
        assert {
            "environment": "data_ops",
            "family": "schema_reasoning",
            "split": "regression",
            "reason": "Data-ops regression fixtures are deferred until asset-backed schemas are added.",
            "owner": "data-evals",
            "tracking_ref": "CM-0012",
            "review_by": "2026-09-30",
            "expires_when": "Asset-backed schema fixtures land in sim-v0.",
            "count": 0,
            "status": "waived_missing",
            "identity": "data_ops/schema_reasoning/regression",
            "review_state": "scheduled",
            "lifecycle_state": "active_missing",
        } in report["waivers"]
        assert report["waiver_lifecycle_digest"]


def test_benchmark_waivers_command_marks_reviews_due(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert (
            main(
                [
                    "benchmark",
                    "waivers",
                    "--benchmark",
                    "sim-v0",
                    "--as-of",
                    "2026-10-01",
                ]
            )
            == 0
        )

        report = read_json(
            tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "waiver_lifecycle.json"
        )
        assert report["review_due_count"] == 4
        assert report["by_owner"]["data-evals"]["review_due_count"] == 1
        assert report["review_status_counts"] == {
            "overdue": 4,
            "due_soon": 0,
            "scheduled": 0,
        }
        assert {waiver["review_state"] for waiver in report["waivers"]} == {"overdue"}


def test_benchmark_waivers_command_marks_due_soon(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert (
            main(
                [
                    "benchmark",
                    "waivers",
                    "--benchmark",
                    "sim-v0",
                    "--as-of",
                    "2026-09-15",
                    "--due-within-days",
                    "30",
                ]
            )
            == 0
        )

        report = read_json(
            tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "waiver_lifecycle.json"
        )
        assert report["review_due_count"] == 4
        assert report["review_status_counts"] == {
            "overdue": 0,
            "due_soon": 4,
            "scheduled": 0,
        }
        assert {waiver["review_state"] for waiver in report["waivers"]} == {"due_soon"}


def test_benchmark_waivers_report_detects_stale_stored_coverage_digest(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["coverage_policy"]["waivers"][0]["owner"] = "changed-after-coverage"
        write_json(manifest_path, manifest)

        assert (
            main(
                [
                    "benchmark",
                    "waivers",
                    "--benchmark",
                    "sim-v0",
                    "--as-of",
                    "2026-06-19",
                ]
            )
            == 0
        )

        stored_coverage = read_json(
            tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json"
        )
        report = read_json(
            tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "waiver_lifecycle.json"
        )
        assert report["stored_coverage_digest"] == stored_coverage["coverage_digest"]
        assert report["coverage_digest"] != stored_coverage["coverage_digest"]
        assert report["coverage_digest_matches_stored"] is False


def test_benchmark_waivers_command_rejects_bad_as_of_date(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert (
            main(
                [
                    "benchmark",
                    "waivers",
                    "--benchmark",
                    "sim-v0",
                    "--as-of",
                    "10-01-2026",
                ]
            )
            == 1
        )
        output = capsys.readouterr()
        assert "YYYY-MM-DD" in output.err


def test_improve_rejects_validation_split_source_run(
    tmp_path: Path,
    capsys,
) -> None:
    with working_dir(tmp_path):
        assert main(["init"]) == 0
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        heldout_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        assert main(["improve", "--run", str(heldout_run), "--mock"]) == 1
        output = capsys.readouterr()
        assert "requires a train split run" in output.err


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
        assert gate["missing_required_cells"] == []
        assert gate["coverage_policy_digest"]
        assert {
            "environment": "data_ops",
            "family": "schema_reasoning",
            "split": "regression",
            "reason": "Data-ops regression fixtures are deferred until asset-backed schemas are added.",
            "owner": "data-evals",
            "tracking_ref": "CM-0012",
            "review_by": "2026-09-30",
            "expires_when": "Asset-backed schema fixtures land in sim-v0.",
            "count": 0,
            "status": "waived_missing",
        } in gate["waived_missing_cells"]


def test_sim_v0_gate_rejects_missing_required_coverage(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["coverage_policy"]["required"].append(
            {
                "environment": "data_ops",
                "family": "metric_selection",
                "split": "regression",
                "reason": "Test-only missing required cell.",
            }
        )
        write_json(manifest_path, manifest)
        assert main(["benchmark", "coverage", "--benchmark", "sim-v0"]) == 0
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
                "family": "metric_selection",
                "split": "regression",
                "reason": "Test-only missing required cell.",
                "count": 0,
                "status": "missing_required",
            }
        ]


def test_sim_v0_gate_rejects_coverage_policy_drift_after_runs(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        baseline_run, candidate_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-2:]
        baseline_coverage_digest = read_json(baseline_run / "results.json")["metadata"][
            "coverage_digest"
        ]

        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["coverage_policy"]["waivers"][0]["owner"] = "changed-after-run"
        write_json(manifest_path, manifest)

        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["decision"] == "reject"
        assert gate["coverage_digest"] == baseline_coverage_digest
        assert gate["current_coverage_digest"] != baseline_coverage_digest
        assert {
            "type": "coverage_digest_mismatch",
            "expected_coverage_digest": baseline_coverage_digest,
            "current_coverage_digest": gate["current_coverage_digest"],
            "status": "coverage_drift",
        } in gate["coverage_failures"]


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


def test_external_adapter_metadata_rejects_malformed_rows(
    tmp_path: Path,
    capsys,
) -> None:
    cases = [
        (
            "non-object-adapter",
            "external_adapter",
            "must_be_object",
            {"external_adapter": "terminal-bench"},
        ),
        (
            "missing-adapter-key",
            "fixture_version",
            "missing",
            {
                "external_adapter": {
                    "name": "terminal-bench",
                    "kind": "terminal",
                    "external_id": "missing-fixture",
                    "source_url": "https://www.tbench.ai/",
                    "mode": "read_only",
                }
            },
        ),
        (
            "write-mode-adapter",
            "mode",
            "must_be_read_only",
            {
                "external_adapter": {
                    "name": "terminal-bench",
                    "kind": "terminal",
                    "external_id": "write-mode",
                    "fixture_version": "fixture-v0",
                    "source_url": "https://www.tbench.ai/",
                    "mode": "runner",
                }
            },
        ),
        (
            "unknown-kind-adapter",
            "kind",
            "unknown_kind",
            {
                "external_adapter": {
                    "name": "world-model",
                    "kind": "world_model_trace",
                    "external_id": "world-model-live",
                    "fixture_version": "fixture-v0",
                    "source_url": "https://example.com/world-model",
                    "mode": "read_only",
                }
            },
        ),
        (
            "split-mismatch-adapter",
            "split",
            "task_split_mismatch",
            {
                "split": "heldout",
                "external_adapter": {
                    "name": "terminal-bench",
                    "kind": "terminal",
                    "external_id": "split-mismatch",
                    "fixture_version": "fixture-v0",
                    "source_url": "https://www.tbench.ai/",
                    "mode": "read_only",
                },
            },
        ),
    ]
    for profile, field, status, overrides in cases:
        case_root = tmp_path / profile
        case_root.mkdir()
        with working_dir(case_root):
            write_adapter_source_profile(
                case_root / "benchmarks" / profile,
                train_overrides=overrides,
            )
            assert main(["benchmark", "init", "--name", profile, "--profile", profile]) == 1
            output = capsys.readouterr()
            assert "External adapter metadata is invalid" in output.err
            assert field in output.err
            assert status in output.err


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


def test_gate_rejects_attempt_regression_from_policy(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {"heldout": {"min_pass_rate_delta": 0, "max_attempt_delta": 0}},
        )
        baseline_run = write_fake_run(tmp_path / "baseline", attempts=2)
        candidate_run = write_fake_run(tmp_path / "candidate", attempts=3)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["pass_rate_delta"] == 0
        assert gate["metric_deltas"]["attempts"] == 1
        assert gate["efficiency_thresholds"]["attempts"] == 0
        assert gate["decision"] == "reject"
        assert gate["efficiency_failures"] == [
            {
                "metric": "attempts",
                "max_delta": 0.0,
                "delta": 1,
                "status": "efficiency_regression",
            }
        ]


def test_gate_rejects_tool_call_regression_from_policy(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {"heldout": {"min_pass_rate_delta": 0, "max_tool_call_delta": 0}},
        )
        baseline_run = write_fake_run(tmp_path / "baseline", tool_calls=0)
        candidate_run = write_fake_run(tmp_path / "candidate", tool_calls=1)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["metric_deltas"]["tool_calls"] == 1
        assert gate["decision"] == "reject"
        assert gate["efficiency_failures"] == [
            {
                "metric": "tool_calls",
                "max_delta": 0.0,
                "delta": 1,
                "status": "efficiency_regression",
            }
        ]


def test_gate_allows_equal_efficiency_under_policy(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "max_attempt_delta": 0,
                    "max_tool_call_delta": 0,
                }
            },
        )
        baseline_run = write_fake_run(tmp_path / "baseline", attempts=2, tool_calls=1)
        candidate_run = write_fake_run(tmp_path / "candidate", attempts=2, tool_calls=1)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["decision"] == "promote"
        assert gate["metric_deltas"]["attempts"] == 0
        assert gate["metric_deltas"]["tool_calls"] == 0
        assert gate["efficiency_failures"] == []


def test_gate_rejects_unavailable_cost_when_cost_policy_is_configured(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {"heldout": {"min_pass_rate_delta": 0, "max_cost_usd_delta": 0}},
        )
        baseline_run = write_fake_run(tmp_path / "baseline", cost_usd=None)
        candidate_run = write_fake_run(tmp_path / "candidate", cost_usd=None)
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["metric_deltas"]["cost_usd"] is None
        assert gate["decision"] == "reject"
        assert gate["efficiency_failures"] == [
            {
                "metric": "cost_usd",
                "max_delta": 0.0,
                "delta": None,
                "status": "metric_unavailable",
            }
        ]


def test_gate_rejects_duration_regression_from_policy(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        baseline_run = write_fake_run(tmp_path / "baseline", duration_ms=1.0)
        candidate_run = write_fake_run(tmp_path / "candidate", duration_ms=2.0)
        evidence_only_gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        evidence_only_gate = read_json(evidence_only_gate_path)
        assert evidence_only_gate["decision"] == "promote"
        assert evidence_only_gate["metric_deltas"]["duration_ms"] == 1.0
        assert evidence_only_gate["efficiency_thresholds"]["duration_ms"] is None

        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {"heldout": {"min_pass_rate_delta": 0, "max_duration_ms_delta": 0.5}},
        )
        gate_path = gate_candidate(
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            min_pass_rate_delta=0,
            max_allowed_drop=0,
        )
        gate = read_json(gate_path)
        assert gate["metric_deltas"]["duration_ms"] == 1.0
        assert gate["decision"] == "reject"
        assert gate["efficiency_failures"] == [
            {
                "metric": "duration_ms",
                "max_delta": 0.5,
                "delta": 1.0,
                "status": "efficiency_regression",
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
            "owner": "data-evals",
            "tracking_ref": "TEST-WAIVER",
            "review_by": "2099-01-31",
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


def test_gate_allows_scheduled_waiver_review_under_policy(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        waiver = {
            "environment": "data_ops",
            "family": "metric_selection",
            "split": "regression",
            "reason": "Covered by heldout until regression data fixtures exist.",
            "owner": "data-evals",
            "tracking_ref": "TEST-WAIVER",
            "review_by": "2026-09-30",
        }
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[waiver])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "fail_on_overdue_waivers": True,
                    "waiver_review_as_of": "2026-06-19",
                }
            },
        )
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
        assert gate["waiver_review_policy"] == {
            "fail_on_overdue_waivers": True,
            "waiver_review_as_of": "2026-06-19",
            "waiver_due_within_days": 30,
        }
        assert gate["waiver_review"]["review_status_counts"] == {
            "overdue": 0,
            "due_soon": 0,
            "scheduled": 1,
        }
        assert gate["waiver_review_failures"] == []


def test_gate_rejects_overdue_active_missing_waiver_when_policy_enabled(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        waiver = {
            "environment": "data_ops",
            "family": "metric_selection",
            "split": "regression",
            "reason": "Covered by heldout until regression data fixtures exist.",
            "owner": "data-evals",
            "tracking_ref": "TEST-WAIVER",
            "review_by": "2026-09-30",
        }
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[waiver])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "fail_on_overdue_waivers": True,
                    "waiver_review_as_of": "2026-10-01",
                }
            },
        )
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
        assert gate["pass_rate_delta"] == 0
        assert gate["waiver_review"]["review_status_counts"] == {
            "overdue": 1,
            "due_soon": 0,
            "scheduled": 0,
        }
        assert gate["waiver_review_failures"] == [
            {
                "environment": "data_ops",
                "family": "metric_selection",
                "split": "regression",
                "identity": "data_ops/metric_selection/regression",
                "owner": "data-evals",
                "tracking_ref": "TEST-WAIVER",
                "review_by": "2026-09-30",
                "review_state": "overdue",
                "lifecycle_state": "active_missing",
                "status": "overdue_waiver",
            }
        ]


def test_gate_keeps_due_soon_waiver_review_informational(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        waiver = {
            "environment": "data_ops",
            "family": "metric_selection",
            "split": "regression",
            "reason": "Covered by heldout until regression data fixtures exist.",
            "owner": "data-evals",
            "tracking_ref": "TEST-WAIVER",
            "review_by": "2026-09-30",
        }
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[waiver])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "fail_on_overdue_waivers": True,
                    "waiver_review_as_of": "2026-09-15",
                    "waiver_due_within_days": 30,
                }
            },
        )
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
        assert gate["waiver_review"]["review_status_counts"] == {
            "overdue": 0,
            "due_soon": 1,
            "scheduled": 0,
        }
        assert gate["waiver_review_failures"] == []


def test_gate_allows_overdue_retire_candidate_waiver(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        waiver = {
            "environment": "fake",
            "family": "smoke",
            "split": "heldout",
            "reason": "Covered now; waiver should be retired rather than block promotion.",
            "owner": "eval-suite",
            "tracking_ref": "TEST-WAIVER",
            "review_by": "2026-09-30",
        }
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[waiver])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "fail_on_overdue_waivers": True,
                    "waiver_review_as_of": "2026-10-01",
                }
            },
        )
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
        assert gate["waiver_review"]["retire_candidate_count"] == 1
        assert gate["waiver_review"]["review_status_counts"] == {
            "overdue": 1,
            "due_soon": 0,
            "scheduled": 0,
        }
        assert gate["waiver_review_failures"] == []


def test_gate_requires_explicit_waiver_review_date_for_blocking_policy(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {"heldout": {"min_pass_rate_delta": 0, "fail_on_overdue_waivers": True}},
        )
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)

        try:
            gate_candidate(
                baseline_run=baseline_run,
                candidate_run=candidate_run,
                min_pass_rate_delta=0,
                max_allowed_drop=0,
            )
        except RuntimeError as error:
            assert "waiver_review_as_of" in str(error)
        else:
            raise AssertionError("Expected missing waiver_review_as_of rejection.")


def test_gate_rejects_malformed_waiver_review_date(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        write_fake_coverage_report(tmp_path, missing_required=[], waived_missing=[])
        write_json(
            tmp_path / ".rsi" / "benchmarks" / "fake" / "gate_policy.json",
            {
                "heldout": {
                    "min_pass_rate_delta": 0,
                    "fail_on_overdue_waivers": True,
                    "waiver_review_as_of": "10-01-2026",
                }
            },
        )
        baseline_run = write_fake_run(tmp_path / "baseline", passed=2, task_count=2)
        candidate_run = write_fake_run(tmp_path / "candidate", passed=2, task_count=2)

        try:
            gate_candidate(
                baseline_run=baseline_run,
                candidate_run=candidate_run,
                min_pass_rate_delta=0,
                max_allowed_drop=0,
            )
        except RuntimeError as error:
            assert "gate_policy waiver_review_as_of must be YYYY-MM-DD" in str(error)
        else:
            raise AssertionError("Expected malformed waiver_review_as_of rejection.")


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


def test_compare_rejects_coverage_digest_mismatch(tmp_path: Path) -> None:
    baseline_run = write_fake_run(tmp_path / "baseline", coverage_digest="coverage-a")
    candidate_run = write_fake_run(tmp_path / "candidate", coverage_digest="coverage-b")
    try:
        compare_runs(baseline_run, candidate_run)
    except RuntimeError as error:
        assert "different coverage digests" in str(error)
    else:
        raise AssertionError("Expected coverage digest mismatch rejection.")


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
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(candidate),
        )
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
        gate_payload = read_json(gate)
        assert versions["id"] == "H1"
        assert versions["status"] == "promoted"
        assert versions["promoted_from_gate"] == gate.name
        assert versions["lineage"]["pass_rate_delta"] == 0.1
        assert versions["lineage"]["heldout_gate_digest"] == gate_payload["heldout_gate_digest"]
        assert versions["lineage"]["regression_gate_digest"] == gate_payload[
            "regression_gate_digest"
        ]


def test_promote_candidate_version_rejects_single_split_gate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "composite heldout+regression gate" in str(error)
        else:
            raise AssertionError("Expected single-split gate rejection.")


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


def test_promote_candidate_version_rejects_stale_coverage_digest(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        manifest_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json"
        coverage_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json"
        manifest = read_json(manifest_path)
        coverage = read_json(coverage_path)
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
            benchmark="sim-v0",
            suite_version=manifest["suite_version"],
            suite_digest=manifest["suite_digest"],
            coverage_digest=coverage["coverage_digest"],
            current_coverage_digest=coverage["coverage_digest"],
            coverage_policy_digest=coverage["coverage_policy_digest"],
        )

        manifest["coverage_policy"]["waivers"][0]["owner"] = "changed-after-composite-gate"
        write_json(manifest_path, manifest)

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "coverage digest is stale" in str(error)
        else:
            raise AssertionError("Expected stale coverage digest rejection.")


def test_promote_candidate_version_rejects_failing_waiver_review_policy(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        manifest = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "manifest.json")
        coverage = read_json(tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "coverage.json")
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
            benchmark="sim-v0",
            suite_version=manifest["suite_version"],
            suite_digest=manifest["suite_digest"],
            coverage_digest=coverage["coverage_digest"],
            current_coverage_digest=coverage["coverage_digest"],
            coverage_policy_digest=coverage["coverage_policy_digest"],
            waiver_review_policy={
                "fail_on_overdue_waivers": True,
                "waiver_review_as_of": "2026-10-01",
                "waiver_due_within_days": 30,
            },
        )

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "waiver review policy is failing" in str(error)
        else:
            raise AssertionError("Expected failing waiver review policy rejection.")


def test_promote_candidate_version_rejects_missing_child_gate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        composite = read_json(gate)
        Path(composite["heldout_gate"]).unlink()

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "child gate not found" in str(error)
        else:
            raise AssertionError("Expected missing child gate rejection.")


def test_promote_candidate_version_rejects_mutated_child_gate(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        composite = read_json(gate)
        heldout_gate = Path(composite["heldout_gate"])
        child = read_json(heldout_gate)
        child["pass_rate_delta"] = -1
        write_json(heldout_gate, child)

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "child digest mismatch" in str(error)
        else:
            raise AssertionError("Expected mutated child gate rejection.")


def test_promote_candidate_version_rejects_missing_split_isolation_audit(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        composite = read_json(gate)
        Path(composite["split_isolation_audit"]).unlink()

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "split isolation audit not found" in str(error)
        else:
            raise AssertionError("Expected missing split isolation audit rejection.")


def test_promote_candidate_version_rejects_failing_split_isolation_audit(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        proposal = write_proposal(tmp_path)
        candidate_path = create_candidate_version(parent="H0", candidate="H1", proposal_path=proposal)
        gate = write_promote_composite_gate(
            tmp_path,
            candidate_digest=harness_behavior_digest(read_json(candidate_path)),
        )
        composite = read_json(gate)
        audit_path = Path(composite["split_isolation_audit"])
        audit = read_json(audit_path)
        audit["status"] = "fail"
        write_json(audit_path, audit)

        try:
            promote_candidate_version(candidate="H1", gate_path=gate)
        except RuntimeError as error:
            assert "requires a passing split isolation audit" in str(error)
        else:
            raise AssertionError("Expected failing split isolation audit rejection.")


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
            "split_isolation_audit",
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
        assert proposal["source_split"] == "train"
        assert proposal["evidence_manifest"]["source_split"] == "train"
        assert proposal["evidence_manifest"]["task_ids"] == run_task_ids(
            Path(next(step["run"] for step in cycle["steps"] if step["name"] == "train_parent"))
        )


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
        assert decision["split_isolation_audit"]
        assert decision["split_isolation_digest"]
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
        split_audit_step = next(
            step for step in cycle["steps"] if step["name"] == "split_isolation_audit"
        )
        composite = read_json(Path(composite_step["gate"]))
        split_audit = read_json(Path(split_audit_step["audit"]))
        decision = read_json(Path(cycle["decision_artifact"]))
        assert cycle["suite_version"] == "sim-v0.1"
        assert cycle["suite_digest"] == manifest["suite_digest"]
        assert cycle["coverage_digest"] == coverage["coverage_digest"]
        assert split_audit_step["status"] == "pass"
        assert split_audit["status"] == "pass"
        assert split_audit["proposal_source_split"] == "train"
        assert split_audit["proposal_embedded_evidence_present"] is True
        assert split_audit["proposal_embedded_task_ids"] == split_audit["train"]["task_ids"]
        assert set(split_audit["train"]["task_ids"]).isdisjoint(
            split_audit["validation"]["heldout"]["task_ids"]
        )
        assert set(split_audit["train"]["task_ids"]).isdisjoint(
            split_audit["validation"]["regression"]["task_ids"]
        )
        assert {check["passed"] for check in split_audit["checks"]} == {True}
        assert split_audit["violations"] == []
        assert split_audit["split_isolation_digest"]
        assert composite["suite_digest"] == manifest["suite_digest"]
        assert composite["coverage_digest"] == coverage["coverage_digest"]
        assert composite["heldout_evaluator_digests"]
        assert composite["regression_evaluator_digests"]
        assert decision["suite_digest"] == manifest["suite_digest"]
        assert decision["evaluator_digests"]["heldout"]
        assert decision["evaluator_digests"]["regression"]


def test_experiment_stability_promotes_sequential_sim_v0_chain(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        report_path = run_experiment_stability(
            parent="H0",
            candidate_prefix="H",
            cycles=2,
            benchmark="sim-v0",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=True,
        )

        report = read_json(report_path)
        assert report["status"] == "pass"
        assert report["validation_status"] == "pass"
        assert report["promotion_status"] == "pass"
        assert report["parent_start"] == "H0"
        assert report["final_parent"] == "H2"
        assert report["requested_cycles"] == 2
        assert report["completed_cycles"] == 2
        assert report["totals"] == {
            "promoted": 2,
            "rejected": 0,
            "validation_failures": 0,
            "heldout_gate_rejects": 0,
            "regression_gate_rejects": 0,
            "split_isolation_failures": 0,
            "environment_failures": 0,
            "coverage_failures": 0,
            "waiver_review_failures": 0,
            "efficiency_failures": 0,
        }
        assert report["kind"] == "local_cycle_stability"
        assert report["gate_contract"]["split_isolation_required"] is True
        assert report["gate_contract"]["heldout"]["waiver_review_policy"] == {
            "fail_on_overdue_waivers": True,
            "waiver_due_within_days": 30,
            "waiver_review_as_of": "2026-06-19",
        }
        assert report["rollup"] == {
            "all_cycles_passed": True,
            "suite_digest_stable": True,
            "coverage_digest_stable": True,
            "coverage_policy_digest_stable": True,
            "waiver_review_policy_stable": True,
            "total_failures": 0,
        }
        assert report["failures"] == []
        assert [cycle["parent"] for cycle in report["cycles"]] == ["H0", "H1"]
        assert [cycle["candidate"] for cycle in report["cycles"]] == ["H1", "H2"]
        assert {cycle["cycle_status"] for cycle in report["cycles"]} == {"promoted"}
        assert {cycle["validation_passed"] for cycle in report["cycles"]} == {True}
        assert report["stability_digest"]

        for cycle in report["cycles"]:
            assert cycle["suite_version"] == "sim-v0.1"
            assert cycle["heldout"]["decision"] == "promote"
            assert cycle["regression"]["decision"] == "promote"
            assert cycle["decisions"] == {
                "heldout": "promote",
                "regression": "promote",
                "composite": "promote",
            }
            assert cycle["failure_counts"] == {
                "environment": 0,
                "coverage": 0,
                "waiver_review": 0,
                "efficiency": 0,
                "split_isolation": 0,
            }
            assert cycle["heldout"]["waiver_review_as_of"] == "2026-06-19"
            assert cycle["regression"]["waiver_review_as_of"] == "2026-06-19"
            assert cycle["heldout"]["waiver_review_failures"] == 0
            assert cycle["regression"]["waiver_review_failures"] == 0
            assert cycle["heldout"]["efficiency_failures"] == 0
            assert cycle["regression"]["efficiency_failures"] == 0
            assert cycle["split_isolation"]["status"] == "pass"
            assert cycle["split_isolation"]["violations"] == 0
            assert Path(cycle["heldout"]["gate"]).exists()
            assert Path(cycle["regression"]["gate"]).exists()
            assert Path(cycle["composite_gate"]).exists()

        h2 = read_json(tmp_path / ".rsi" / "harnesses" / "H2.json")
        assert h2["status"] == "promoted"
        assert h2["parent"] == "H1"
        assert h2["lineage"]["heldout_gate"]
        assert h2["lineage"]["regression_gate"]
        assert h2["lineage"]["split_isolation_audit"]
        assert h2["lineage"]["waiver_review_policy"]["waiver_review_as_of"] == "2026-06-19"


def test_experiment_stability_no_promote_keeps_validation_separate(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        report_path = run_experiment_stability(
            parent="H0",
            candidate_prefix="DryRun",
            first_candidate_index=1,
            cycles=2,
            benchmark="sim-v0",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=False,
        )

        report = read_json(report_path)
        assert report["status"] == "pass"
        assert report["validation_status"] == "pass"
        assert report["promotion_status"] == "not_requested"
        assert report["parent_start"] == "H0"
        assert report["final_parent"] == "H0"
        assert [cycle["parent"] for cycle in report["cycles"]] == ["H0", "H0"]
        assert [cycle["candidate"] for cycle in report["cycles"]] == ["DryRun1", "DryRun2"]
        assert {cycle["cycle_status"] for cycle in report["cycles"]} == {"rejected"}
        assert {cycle["validation_passed"] for cycle in report["cycles"]} == {True}
        assert report["totals"]["rejected"] == 2
        assert report["totals"]["validation_failures"] == 0
        assert read_json(tmp_path / ".rsi" / "harnesses" / "DryRun1.json")["status"] == "candidate"
        assert read_json(tmp_path / ".rsi" / "harnesses" / "DryRun2.json")["status"] == "candidate"


def test_experiment_stability_reports_overdue_waiver_gate_failure(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        policy_path = tmp_path / ".rsi" / "benchmarks" / "sim-v0" / "gate_policy.json"
        policy = read_json(policy_path)
        policy["heldout"]["waiver_review_as_of"] = "2026-10-01"
        policy["regression"]["waiver_review_as_of"] = "2026-10-01"
        write_json(policy_path, policy)

        report_path = run_experiment_stability(
            parent="H0",
            candidate_prefix="H",
            cycles=1,
            benchmark="sim-v0",
            model=None,
            reasoning_effort="medium",
            mock=True,
            min_heldout_delta=0,
            max_regression_drop=0,
            promote=True,
        )

        report = read_json(report_path)
        assert report["status"] == "review"
        assert report["validation_status"] == "fail"
        assert report["promotion_status"] == "partial"
        assert report["final_parent"] == "H0"
        assert report["totals"]["promoted"] == 0
        assert report["totals"]["rejected"] == 1
        assert report["totals"]["validation_failures"] == 1
        assert report["totals"]["waiver_review_failures"] == 8
        assert report["rollup"]["all_cycles_passed"] is False
        assert report["rollup"]["waiver_review_policy_stable"] is True
        assert report["failures"] == [
            {
                "type": "cycle_validation_failed",
                "cycle_id": report["cycles"][0]["cycle_id"],
                "candidate": "H1",
                "decisions": {
                    "heldout": "reject",
                    "regression": "reject",
                    "composite": "reject",
                },
                "failure_counts": {
                    "environment": 0,
                    "coverage": 0,
                    "waiver_review": 8,
                    "efficiency": 0,
                    "split_isolation": 0,
                },
            }
        ]
        assert report["cycles"][0]["heldout"]["waiver_review_failures"] == 4
        assert report["cycles"][0]["regression"]["waiver_review_failures"] == 4


def test_experiment_stability_cli_writes_report(tmp_path: Path, capsys) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert (
            main(
                [
                    "experiment",
                    "stability",
                    "--parent",
                    "H0",
                    "--candidate-prefix",
                    "H",
                    "--cycles",
                    "1",
                    "--benchmark",
                    "sim-v0",
                    "--mock",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "Wrote stability report to" in output
        reports = sorted((tmp_path / ".rsi" / "cycles").glob("stability-*.json"))
        assert len(reports) == 1
        report = read_json(reports[0])
        assert report["status"] == "pass"
        assert report["completed_cycles"] == 1


def test_experiment_stability_rejects_invalid_cycle_count(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init"]) == 0
        try:
            run_experiment_stability(
                parent="H0",
                candidate_prefix="H",
                cycles=0,
                benchmark="synthetic",
                model=None,
                reasoning_effort="medium",
                mock=True,
                min_heldout_delta=0,
                max_regression_drop=0,
                promote=True,
            )
        except RuntimeError as error:
            assert "cycles" in str(error)
        else:
            raise AssertionError("Expected invalid cycle count rejection.")


def test_split_isolation_audit_rejects_embedded_heldout_evidence(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "train", "--mock"]) == 0
        train_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        heldout_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        assert (
            main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "regression", "--mock"])
            == 0
        )
        regression_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        proposal = tmp_path / ".rsi" / "proposals" / "leaky-proposal.json"
        write_json(
            proposal,
            {
                "id": "leaky-proposal",
                "source_run": train_run.name,
                "status": "proposed",
                "config_patch": {"prompt_append": "Leaked validation evidence."},
                "learning": f"Leaked validation trace at {heldout_run}/trace.jsonl.",
                "evidence": read_json(heldout_run / "results.json"),
            },
        )

        try:
            write_split_isolation_audit(
                cycle_id="cycle-leaky",
                proposal_path=proposal,
                train_run=train_run,
                heldout_parent_run=heldout_run,
                heldout_candidate_run=heldout_run,
                regression_parent_run=regression_run,
                regression_candidate_run=regression_run,
            )
        except RuntimeError as error:
            assert "Split isolation audit failed" in str(error)
        else:
            raise AssertionError("Expected split isolation audit failure.")

        audit = read_json(tmp_path / ".rsi" / "cycles" / "cycle-leaky-split-isolation.json")
        assert audit["status"] == "fail"
        failed_checks = {check["name"] for check in audit["violations"]}
        assert "proposal_embedded_evidence_is_train" in failed_checks
        assert "proposal_embedded_task_ids_subset_of_train" in failed_checks
        assert "proposal_has_no_validation_references" in failed_checks
        assert f"{heldout_run}/trace.jsonl" in audit["leaked_validation_references"]


def test_non_mock_proposal_prompt_uses_only_train_trace(tmp_path: Path, monkeypatch) -> None:
    with working_dir(tmp_path):
        assert main(["benchmark", "init", "--name", "sim-v0"]) == 0
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "train", "--mock"]) == 0
        train_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        assert main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "heldout", "--mock"]) == 0
        heldout_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        assert (
            main(["benchmark", "run", "--benchmark", "sim-v0", "--split", "regression", "--mock"])
            == 0
        )
        regression_run = sorted((tmp_path / ".rsi" / "runs").iterdir())[-1]
        captured: dict[str, str] = {}

        def fake_call_model(*, model: str, prompt: str, reasoning_effort: str) -> str:
            captured["prompt"] = prompt
            return json.dumps(
                {
                    "summary": "Train-only prompt audit proposal.",
                    "learning": "Use only training evidence for proposal generation.",
                    "config_patch": {"prompt_append": "Respect split isolation."},
                    "risks": [],
                    "expected_metric": "pass_rate",
                }
            )

        monkeypatch.setattr(improve_module, "call_model", fake_call_model)
        proposal = improve_module.propose_patch(
            run_dir=train_run,
            model=None,
            reasoning_effort="medium",
            mock=False,
            config_path=Path(".rsi/harnesses/H0.json"),
        )
        prompt = captured["prompt"]
        proposal_payload = read_json(proposal)
        assert proposal_payload["source_run"] == train_run.name
        assert proposal_payload["source_split"] == "train"
        assert proposal_payload["evidence_manifest"]["source_split"] == "train"
        assert proposal_payload["evidence_manifest"]["prompt_digest"]
        assert proposal_payload["evidence_manifest"]["task_ids"] == run_task_ids(train_run)
        assert "'split': 'train'" in prompt
        assert set(run_task_ids(train_run)).isdisjoint(run_task_ids(heldout_run))
        assert set(run_task_ids(train_run)).isdisjoint(run_task_ids(regression_run))
        for task_id in run_task_ids(train_run):
            assert task_id in prompt
        for task_id in [*run_task_ids(heldout_run), *run_task_ids(regression_run)]:
            assert task_id not in prompt


def test_write_composite_gate_rejects_wrong_split_roles(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        heldout = write_gate(tmp_path, name="train-gate.json", split="train")
        regression = write_gate(tmp_path, name="regression-gate.json", split="regression")
        try:
            write_composite_gate(
                heldout_gate=heldout,
                regression_gate=regression,
                decision="promote",
            )
        except RuntimeError as error:
            assert "first gate is the heldout split" in str(error)
        else:
            raise AssertionError("Expected split role mismatch rejection.")


def test_write_composite_gate_rejects_identity_mismatches(tmp_path: Path) -> None:
    cases = [
        ("baseline_harness", {"baseline_harness": "H9"}, "baseline harnesses"),
        ("candidate_harness", {"candidate_harness": "H9"}, "candidate harnesses"),
        ("candidate_digest", {"candidate_digest": "digest-b"}, "candidate behavior digests"),
        ("benchmark", {"benchmark": "other-benchmark"}, "benchmarks"),
        ("model", {"model": "other-model"}, "models"),
    ]
    for field, regression_overrides, expected_error in cases:
        case_path = tmp_path / field
        case_path.mkdir()
        with working_dir(case_path):
            heldout = write_gate(
                Path.cwd(),
                name="heldout-gate.json",
                split="heldout",
                candidate_digest="digest-a",
            )
            regression_kwargs = {"candidate_digest": "digest-a", **regression_overrides}
            regression = write_gate(
                Path.cwd(),
                name="regression-gate.json",
                split="regression",
                **regression_kwargs,
            )
            try:
                write_composite_gate(
                    heldout_gate=heldout,
                    regression_gate=regression,
                    decision="promote",
                )
            except RuntimeError as error:
                assert expected_error in str(error)
            else:
                raise AssertionError(f"Expected {field} mismatch rejection.")


def test_write_composite_gate_rejects_coverage_digest_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        heldout = write_gate(
            tmp_path,
            name="heldout-gate.json",
            split="heldout",
            coverage_digest="coverage-a",
        )
        regression = write_gate(
            tmp_path,
            name="regression-gate.json",
            split="regression",
            coverage_digest="coverage-b",
        )
        try:
            write_composite_gate(
                heldout_gate=heldout,
                regression_gate=regression,
                decision="promote",
            )
        except RuntimeError as error:
            assert "coverage digests" in str(error)
        else:
            raise AssertionError("Expected coverage digest mismatch rejection.")


def test_write_composite_gate_rejects_suite_digest_mismatch(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        heldout = write_gate(
            tmp_path,
            name="heldout-gate.json",
            split="heldout",
            suite_digest="suite-a",
        )
        regression = write_gate(
            tmp_path,
            name="regression-gate.json",
            split="regression",
            suite_digest="suite-b",
        )
        try:
            write_composite_gate(
                heldout_gate=heldout,
                regression_gate=regression,
                decision="promote",
            )
        except RuntimeError as error:
            assert "benchmark suite digests" in str(error)
        else:
            raise AssertionError("Expected suite digest mismatch rejection.")


def test_write_composite_gate_rejects_waiver_review_policy_mismatch(
    tmp_path: Path,
) -> None:
    with working_dir(tmp_path):
        heldout = write_gate(
            tmp_path,
            name="heldout-gate.json",
            split="heldout",
            waiver_review_policy={
                "fail_on_overdue_waivers": True,
                "waiver_review_as_of": "2026-06-19",
                "waiver_due_within_days": 30,
            },
        )
        regression = write_gate(
            tmp_path,
            name="regression-gate.json",
            split="regression",
            waiver_review_policy={
                "fail_on_overdue_waivers": True,
                "waiver_review_as_of": "2026-10-01",
                "waiver_due_within_days": 30,
            },
        )
        try:
            write_composite_gate(
                heldout_gate=heldout,
                regression_gate=regression,
                decision="promote",
            )
        except RuntimeError as error:
            assert "waiver review policies" in str(error)
        else:
            raise AssertionError("Expected waiver review policy mismatch rejection.")


def test_write_composite_gate_rejects_promote_when_component_rejects(tmp_path: Path) -> None:
    with working_dir(tmp_path):
        heldout = write_gate(tmp_path, name="heldout-gate.json", split="heldout")
        regression = write_gate(
            tmp_path,
            name="regression-gate.json",
            split="regression",
            decision="reject",
        )
        try:
            write_composite_gate(
                heldout_gate=heldout,
                regression_gate=regression,
                decision="promote",
            )
        except RuntimeError as error:
            assert "both component gates promote" in str(error)
        else:
            raise AssertionError("Expected component reject mismatch rejection.")


def write_fake_run(
    path: Path,
    *,
    passed: int = 1,
    task_count: int = 2,
    model: str = "gpt-5.5",
    task_digest: str = "same-tasks",
    split: str = "heldout",
    coverage_digest: str | None = None,
    attempts: int | None = None,
    tool_calls: int = 0,
    duration_ms: float = 1,
    cost_usd: float | None = None,
) -> Path:
    path.mkdir(parents=True)
    write_json(path / "harness.snapshot.json", {"model": model})
    attempts = attempts if attempts is not None else task_count
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
    metadata = {"benchmark": "fake", "split": split, "harness": path.name}
    if coverage_digest:
        metadata["coverage_digest"] = coverage_digest
    write_json(
        path / "results.json",
        {
            "run_id": path.name,
            "metadata": metadata,
            "task_digest": task_digest,
            "tasks": task_count,
            "passed": passed,
            "pass_rate": passed / task_count,
            "attempts": attempts,
            "tool_calls": tool_calls,
            "duration_ms": duration_ms,
            "metrics": {
                "attempts": attempts,
                "tool_calls": tool_calls,
                "duration_ms": duration_ms,
                "cost_usd": cost_usd,
            },
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


def write_adapter_source_profile(
    path: Path,
    *,
    train_overrides: dict[str, object] | None = None,
) -> None:
    write_json(
        path / "manifest.json",
        {
            "id": path.name,
            "suite_version": f"{path.name}.1",
            "adapter_contract_version": "adapter-contract-test",
        },
    )
    adapter = {
        "name": "terminal-bench",
        "kind": "terminal",
        "external_id": "terminal-test",
        "fixture_version": "fixture-test",
        "source_url": "https://www.tbench.ai/",
        "mode": "read_only",
    }
    for split in ("train", "heldout", "regression"):
        row: dict[str, object] = {
            "id": f"{split}-adapter-task",
            "environment": "terminal_ops",
            "family": "terminal_task_planning",
            "instruction": "Return ok.",
            "eval": {"type": "exact", "expected": "ok"},
            "source": f"{path.name}/{split}",
            "external_adapter": dict(adapter),
        }
        if split == "train" and train_overrides:
            row.update(train_overrides)
        split_dir = path / "sources" / split
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "tasks.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n")


def write_frozen_adapter_export(
    path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
) -> None:
    payload = {
        "suite_version": "frozen-adapters-v0.1",
        "adapter_contract_version": "adapter-contract-v0.1",
        "tasks": rows or frozen_adapter_rows(),
    }
    write_json(path, payload)


def frozen_adapter_rows() -> list[dict[str, object]]:
    return [
        frozen_adapter_row(
            "tb-train",
            "train",
            "terminal-bench",
            "tb-task-1",
            fixture_version="terminal-frozen-v1",
        ),
        frozen_adapter_row(
            "swe-heldout",
            "heldout",
            "swe-bench",
            "swe-issue-1",
            fixture_version="swe-frozen-v1",
        ),
        frozen_adapter_row(
            "tau-regression",
            "regression",
            "tau2-bench",
            "tau-dialog-1",
            fixture_version="tau-frozen-v1",
        ),
    ]


def frozen_adapter_row(
    task_id: str,
    split: str,
    adapter_name: str,
    external_id: str,
    *,
    fixture_version: str = "frozen-v1",
) -> dict[str, object]:
    expected = f"{adapter_name} {external_id}"
    return {
        "id": task_id,
        "split": split,
        "benchmark": adapter_name,
        "external_id": external_id,
        "fixture_version": fixture_version,
        "instruction": f"Return exactly {expected}.",
        "expected": expected,
    }


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


def run_task_ids(run_dir: Path) -> list[str]:
    results = read_json(run_dir / "results.json")
    return [str(item["task_id"]) for item in results["results"]]


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
    name: str = "gate-test.json",
    decision: str = "promote",
    baseline_harness: str = "H0",
    candidate_harness: str = "H1",
    candidate_digest: str | None = None,
    benchmark: str = "synthetic",
    split: str = "heldout",
    model: str = "gpt-5.5",
    suite_version: str = "synthetic-v0",
    suite_digest: str = "suite-a",
    coverage_digest: str | None = None,
    current_coverage_digest: str | None = None,
    coverage_policy_digest: str | None = None,
    waiver_review_policy: dict[str, object] | None = None,
    waiver_review: dict[str, object] | None = None,
) -> Path:
    gate = path / ".rsi" / "gates" / name
    payload = {
        "decision": decision,
        "baseline_harness": baseline_harness,
        "candidate_harness": candidate_harness,
        "baseline_run": "baseline",
        "candidate_run": "candidate",
        "benchmark": benchmark,
        "split": split,
        "model": model,
        "suite_version": suite_version,
        "suite_digest": suite_digest,
        "coverage_digest": coverage_digest,
        "current_coverage_digest": current_coverage_digest,
        "coverage_policy_digest": coverage_policy_digest,
        "waiver_review_policy": waiver_review_policy,
        "waiver_review": waiver_review,
        "evaluator_digests": [f"{split}-evaluator"],
        "pass_rate_delta": 0.1,
    }
    if candidate_digest is not None:
        payload["candidate_harness_digest"] = candidate_digest
    write_json(gate, payload)
    return gate


def write_promote_composite_gate(
    path: Path,
    *,
    candidate_digest: str,
    benchmark: str = "synthetic",
    suite_version: str = "synthetic-v0",
    suite_digest: str = "suite-a",
    coverage_digest: str | None = None,
    current_coverage_digest: str | None = None,
    coverage_policy_digest: str | None = None,
    waiver_review_policy: dict[str, object] | None = None,
    waiver_review: dict[str, object] | None = None,
) -> Path:
    heldout = write_gate(
        path,
        name="heldout-gate.json",
        split="heldout",
        candidate_digest=candidate_digest,
        benchmark=benchmark,
        suite_version=suite_version,
        suite_digest=suite_digest,
        coverage_digest=coverage_digest,
        current_coverage_digest=current_coverage_digest,
        coverage_policy_digest=coverage_policy_digest,
        waiver_review_policy=waiver_review_policy,
        waiver_review=waiver_review,
    )
    regression = write_gate(
        path,
        name="regression-gate.json",
        split="regression",
        candidate_digest=candidate_digest,
        benchmark=benchmark,
        suite_version=suite_version,
        suite_digest=suite_digest,
        coverage_digest=coverage_digest,
        current_coverage_digest=current_coverage_digest,
        coverage_policy_digest=coverage_policy_digest,
        waiver_review_policy=waiver_review_policy,
        waiver_review=waiver_review,
    )
    split_audit = write_fake_split_isolation_audit(path)
    return write_composite_gate(
        heldout_gate=heldout,
        regression_gate=regression,
        split_isolation_audit=split_audit,
        decision="promote",
    )


def write_fake_split_isolation_audit(path: Path) -> Path:
    audit_path = path / ".rsi" / "cycles" / "fake-split-isolation.json"
    audit = {
        "status": "pass",
        "checks": [],
        "violations": [],
    }
    audit["split_isolation_digest"] = digest_payload(audit)
    write_json(audit_path, audit)
    return audit_path
