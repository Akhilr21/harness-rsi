from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_rsi.adapter_importers import (
    import_external_adapter_profile,
    import_review_output,
    source_profile_output,
)
from harness_rsi.benchmarks import (
    compare_runs,
    gate_candidate,
    init_benchmark,
    run_benchmark,
    write_adapter_report,
    write_coverage_report,
    write_waiver_report,
)
from harness_rsi.cycle import run_experiment_cycle, run_experiment_stability
from harness_rsi.decisions import promote, reject
from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.improve import latest_run, propose_patch
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import HARNESS, LEARNINGS, ROOT, RUNS, TASKS, ensure_dirs
from harness_rsi.testing_levels import write_testing_levels_report
from harness_rsi.versions import (
    create_candidate_version,
    list_harness_versions,
    promote_candidate_version,
)


SAMPLE_TASKS = """\
{"id":"contains-harness","instruction":"Return a short answer that includes the phrase harness-level improvement.","eval":{"type":"contains","expected":"harness-level improvement"}}
{"id":"exact-four","instruction":"Return exactly the result of 2 + 2.","eval":{"type":"exact","expected":"4"}}
"""


def init_project(args: argparse.Namespace) -> int:
    ensure_dirs()
    if not HARNESS.exists() or args.force:
        write_json(HARNESS, DEFAULT_HARNESS)
    sample = TASKS / "sample.jsonl"
    if not sample.exists() or args.force:
        sample.write_text(SAMPLE_TASKS)
    if not LEARNINGS.exists() or args.force:
        LEARNINGS.write_text("# Promoted Learnings\n")
    print(f"Initialized {ROOT}")
    return 0


def run(args: argparse.Namespace) -> int:
    run_dir = run_suite(
        tasks_path=Path(args.tasks),
        config_path=Path(args.config),
        model_override=args.model,
        mock=args.mock,
    )
    print(f"Wrote run artifacts to {run_dir}")
    return 0


def improve(args: argparse.Namespace) -> int:
    run_dir = Path(args.run) if args.run else latest_run(RUNS)
    config_model = args.model or DEFAULT_HARNESS["model"]
    path = propose_patch(
        run_dir=run_dir,
        model=config_model,
        reasoning_effort=args.reasoning_effort,
        mock=args.mock,
        config_path=HARNESS,
    )
    print(f"Wrote proposal to {path}")
    return 0


def promote_cmd(args: argparse.Namespace) -> int:
    path = promote(Path(args.proposal))
    print(f"Promoted proposal; wrote decision to {path}")
    return 0


def reject_cmd(args: argparse.Namespace) -> int:
    path = reject(Path(args.proposal), args.reason)
    print(f"Rejected proposal; wrote decision to {path}")
    return 0


def benchmark_init(args: argparse.Namespace) -> int:
    path = init_benchmark(args.name, profile=args.profile)
    print(f"Initialized benchmark at {path}")
    return 0


def benchmark_run(args: argparse.Namespace) -> int:
    result = run_benchmark(
        benchmark=args.benchmark,
        split=args.split,
        harness=args.harness,
        model=args.model,
        mock=args.mock,
    )
    print(
        "Wrote benchmark run artifacts to "
        f"{result.run_dir} ({result.benchmark}/{result.split}/{result.harness})"
    )
    return 0


def benchmark_compare(args: argparse.Namespace) -> int:
    comparison = compare_runs(Path(args.baseline_run), Path(args.candidate_run))
    print(readable_json(comparison))
    return 0


def benchmark_gate(args: argparse.Namespace) -> int:
    path = gate_candidate(
        baseline_run=Path(args.baseline_run),
        candidate_run=Path(args.candidate_run),
        min_pass_rate_delta=args.min_pass_rate_delta,
        max_allowed_drop=args.max_allowed_drop,
        max_environment_drop=args.max_environment_drop,
    )
    print(f"Wrote gate decision to {path}")
    print(readable_json(read_json(path)))
    return 0


def benchmark_coverage(args: argparse.Namespace) -> int:
    path = write_coverage_report(args.benchmark)
    report = read_json(path)
    print(f"Wrote coverage report to {path}")
    print(readable_coverage_summary(report))
    return 0


def benchmark_waivers(args: argparse.Namespace) -> int:
    path = write_waiver_report(
        args.benchmark,
        as_of=args.as_of,
        due_within_days=args.due_within_days,
    )
    report = read_json(path)
    print(f"Wrote waiver lifecycle report to {path}")
    print(readable_waiver_summary(report))
    return 0


def benchmark_adapters(args: argparse.Namespace) -> int:
    path = write_adapter_report(args.benchmark)
    report = read_json(path)
    print(f"Wrote adapter report to {path}")
    print(readable_adapter_summary(report))
    return 0


def benchmark_levels(args: argparse.Namespace) -> int:
    path = write_testing_levels_report(args.benchmark)
    report = read_json(path)
    if args.json:
        print(readable_json(report))
    else:
        print(f"Wrote testing levels report to {path}")
        print(readable_testing_levels_summary(report))
    return 0


def benchmark_import_adapters(args: argparse.Namespace) -> int:
    path = import_external_adapter_profile(
        source=Path(args.source),
        profile=args.profile,
        suite_version=args.suite_version,
        split_map_path=Path(args.split_map) if args.split_map else None,
        allow_rejects=args.allow_rejects,
        review_only=args.review_split_map,
        force=args.force,
    )
    report_name = "import_review.json" if args.review_split_map else "import_report.json"
    report = read_json(path / report_name)
    if args.review_split_map:
        print(f"Wrote adapter import review to {path}")
    else:
        print(f"Wrote imported adapter profile to {path}")
    print(readable_import_summary(report))
    return 0


def benchmark_import_audit(args: argparse.Namespace) -> int:
    root = import_review_output(args.profile) if args.review else source_profile_output(args.profile)
    report_name = "import_review.json" if args.review else "import_report.json"
    report_path = root / report_name
    if not report_path.exists():
        raise RuntimeError(f"Import audit artifact not found: {report_path}")
    report = read_json(report_path)
    if args.json:
        print(readable_json(report))
    else:
        print(f"Import audit artifact: {report_path}")
        print(
            readable_import_audit_summary(
                report,
                max_rejected_rows=args.max_rejected_rows,
                reason=args.reason,
                adapter=args.adapter,
                split=args.split,
                source_contains=args.source_contains,
            )
        )
    return 0


def harness_create_candidate(args: argparse.Namespace) -> int:
    path = create_candidate_version(
        parent=args.parent,
        candidate=args.candidate,
        proposal_path=Path(args.proposal),
        overwrite=args.overwrite,
    )
    print(f"Wrote candidate harness to {path}")
    return 0


def harness_promote(args: argparse.Namespace) -> int:
    path = promote_candidate_version(candidate=args.candidate, gate_path=Path(args.gate))
    print(f"Promoted candidate harness at {path}")
    return 0


def harness_list(args: argparse.Namespace) -> int:
    print(readable_json(list_harness_versions()))
    return 0


def experiment_cycle(args: argparse.Namespace) -> int:
    path = run_experiment_cycle(
        parent=args.parent,
        candidate=args.candidate,
        benchmark=args.benchmark,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        mock=args.mock,
        min_heldout_delta=args.min_heldout_delta,
        max_regression_drop=args.max_regression_drop,
        promote=not args.no_promote,
    )
    print(f"Wrote cycle summary to {path}")
    print(readable_json(read_json(path)))
    return 0


def experiment_stability(args: argparse.Namespace) -> int:
    path = run_experiment_stability(
        parent=args.parent,
        candidate_prefix=args.candidate_prefix,
        cycles=args.cycles,
        benchmark=args.benchmark,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        mock=args.mock,
        min_heldout_delta=args.min_heldout_delta,
        max_regression_drop=args.max_regression_drop,
        promote=not args.no_promote,
        first_candidate_index=args.first_candidate_index,
    )
    print(f"Wrote stability report to {path}")
    print(readable_json(read_json(path)))
    return 0


def readable_json(payload: object) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


def readable_coverage_summary(report: dict[str, object]) -> str:
    lines = [
        f"Benchmark: {report.get('benchmark')}",
        f"Suite version: {report.get('suite_version')}",
        f"Task count: {report.get('task_count')}",
        f"Split counts: {readable_split_counts(report.get('split_counts', {}))}",
        f"Required cells: {list_count(report.get('required_cells'))}",
        f"Missing required cells: {list_count(report.get('missing_required_cells'))}",
        f"Waived missing cells: {list_count(report.get('waived_missing_cells'))}",
        f"Unclassified missing cells: {list_count(report.get('unclassified_missing_cells'))}",
        f"Coverage digest: {report.get('coverage_digest')}",
    ]
    return "\n".join(lines)


def readable_waiver_summary(report: dict[str, object]) -> str:
    lines = [
        f"Benchmark: {report.get('benchmark')}",
        f"Suite version: {report.get('suite_version')}",
        f"As of: {report.get('as_of')}",
        f"Due within days: {report.get('due_within_days')}",
        f"Waivers: {report.get('waiver_count')}",
        f"Waived missing cells: {report.get('waived_missing_count')}",
        f"Waived covered cells: {report.get('waived_covered_count')}",
        f"Active missing: {report.get('active_missing_count')}",
        f"Retire candidates: {report.get('retire_candidate_count')}",
        f"Review status: {readable_status_counts(report.get('review_status_counts', {}))}",
        f"Next review: {report.get('next_review_by')}",
        f"Owners: {readable_group_counts(report.get('by_owner', {}))}",
        f"Review dates: {readable_group_counts(report.get('by_review_date', {}))}",
        f"Coverage digest: {report.get('coverage_digest')}",
        f"Stored coverage digest: {report.get('stored_coverage_digest')}",
        f"Coverage digest matches stored: {report.get('coverage_digest_matches_stored')}",
        f"Waiver lifecycle digest: {report.get('waiver_lifecycle_digest')}",
    ]
    return "\n".join(lines)


def readable_adapter_summary(report: dict[str, object]) -> str:
    lines = [
        f"Benchmark: {report.get('benchmark')}",
        f"Suite version: {report.get('suite_version')}",
        f"Status: {report.get('status')}",
        f"Read only: {report.get('read_only')}",
        f"Adapter tasks: {report.get('external_adapter_task_count')}",
        f"Adapters: {readable_adapter_counts(report.get('adapters', {}))}",
        f"Failures: {list_count(report.get('failures'))}",
        f"Gate semantics changed: {report.get('gate_semantics_changed')}",
        f"Adapter report digest: {report.get('adapter_report_digest')}",
    ]
    return "\n".join(lines)


def readable_import_summary(report: dict[str, object]) -> str:
    lines = [
        f"Profile: {report.get('profile')}",
        f"Suite version: {report.get('suite_version')}",
        f"Status: {report.get('status')}",
        f"Read only: {report.get('read_only')}",
        f"Task count: {report.get('task_count')}",
        f"Rejected rows: {report.get('rejected_row_count')}",
        f"Splits: {readable_split_counts(report.get('split_counts', {}))}",
        f"Adapters: {readable_status_counts_for_dict(report.get('adapter_counts', {}))}",
        f"Split map: {readable_split_map_summary(report.get('split_map', {}))}",
        f"Gate semantics changed: {report.get('gate_semantics_changed')}",
        f"Import report digest: {report.get('import_report_digest')}",
    ]
    return "\n".join(lines)


def readable_testing_levels_summary(report: dict[str, object]) -> str:
    summary = report.get("summary", {})
    frontier = report.get("frontier_model_boundary", {})
    world_model = report.get("world_model_boundary", {})
    adapter = report.get("external_adapter_boundary", {})
    lines = [
        f"Benchmark: {report.get('benchmark')}",
        f"Read only: {report.get('read_only')}",
        f"Report only: {report.get('report_only')}",
        f"Promotion semantics changed: {report.get('promotion_semantics_changed')}",
        f"Promotion evidence: {report.get('promotion_evidence')}",
        f"Promotion ready: {dict_get(summary, 'promotion_ready')}",
        f"Status counts: {readable_status_counts_for_dict(dict_get(summary, 'status_counts', {}))}",
        f"Blocking levels: {readable_list(dict_get(summary, 'blocking_levels', []))}",
        (
            "External adapter boundary: "
            f"status={dict_get(adapter, 'status')} "
            f"tasks={dict_get(adapter, 'external_adapter_task_count')}"
        ),
        (
            "Frontier boundary: "
            f"fixed_model_required={dict_get(frontier, 'fixed_model_required')} "
            f"observed_models={readable_list(dict_get(frontier, 'observed_models', []))} "
            f"usage_sources={readable_list(dict_get(frontier, 'usage_sources', []))} "
            f"runs_missing_cost_usd={dict_get(frontier, 'runs_missing_cost_usd')}"
        ),
        (
            "World-model boundary: "
            f"status={dict_get(world_model, 'status')} "
            f"static_tasks={dict_get(world_model, 'static_world_model_task_count')} "
            f"live_simulator_adapter_present={dict_get(world_model, 'live_simulator_adapter_present')}"
        ),
        "Levels:",
    ]
    levels = report.get("levels", [])
    if isinstance(levels, list):
        for item in levels:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('id')} {item.get('name')}: {item.get('status')} "
                f"(missing={readable_list(item.get('missing', []))})"
            )
    return "\n".join(lines)


def readable_import_audit_summary(
    report: dict[str, object],
    *,
    max_rejected_rows: int,
    reason: str | None = None,
    adapter: str | None = None,
    split: str | None = None,
    source_contains: str | None = None,
) -> str:
    all_rejected_rows = report.get("rejected_rows", [])
    rejected_rows = filter_rejected_rows(
        all_rejected_rows,
        reason=reason,
        adapter=adapter,
        split=split,
        source_contains=source_contains,
    )
    lines = [
        f"Profile: {report.get('profile')}",
        f"Suite version: {report.get('suite_version')}",
        f"Status: {report.get('status')}",
        f"Review only: {report.get('review_only')}",
        f"Read only: {report.get('read_only')}",
        f"Gate semantics changed: {report.get('gate_semantics_changed')}",
        f"Source export: {report.get('source_export_name')}",
        f"Source export digest: {report.get('source_export_digest')}",
        (
            "Rows: "
            f"source={report.get('source_row_count')} "
            f"imported={report.get('imported_row_count')} "
            f"rejected={report.get('rejected_row_count')}"
        ),
        f"Rejection reasons: {readable_status_counts_for_dict(report.get('rejection_reason_counts', {}))}",
        f"Splits: {readable_split_counts(report.get('split_counts', {}))}",
        f"Adapters: {readable_status_counts_for_dict(report.get('adapter_counts', {}))}",
        f"Kinds: {readable_status_counts_for_dict(report.get('kind_counts', {}))}",
        f"Fixture versions: {readable_fixture_versions(report.get('fixture_versions', {}))}",
        f"Split map: {readable_split_map_summary(report.get('split_map', {}))}",
        f"Split map digest: {report.get('split_map_digest')}",
        f"Accepted rows digest: {report.get('accepted_rows_digest')}",
        f"Rejected rows digest: {report.get('rejected_rows_digest')}",
        f"Import report digest: {report.get('import_report_digest')}",
        f"Rejected row filters: {readable_rejected_row_filters(reason, adapter, split, source_contains)}",
    ]
    lines.extend(
        readable_rejected_row_locators(
            rejected_rows,
            total_rejected_rows=list_count(all_rejected_rows),
            max_rejected_rows=max_rejected_rows,
        )
    )
    return "\n".join(lines)


def filter_rejected_rows(
    value: object,
    *,
    reason: str | None,
    adapter: str | None,
    split: str | None,
    source_contains: str | None,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows = [row for row in value if isinstance(row, dict)]
    if reason:
        rows = [row for row in rows if row.get("reason") == reason]
    if adapter:
        rows = [row for row in rows if row.get("adapter_name") == adapter]
    if split:
        rows = [row for row in rows if row.get("split") == split]
    if source_contains:
        rows = [row for row in rows if source_contains in str(row.get("source_path"))]
    return rows


def readable_rejected_row_filters(
    reason: str | None,
    adapter: str | None,
    split: str | None,
    source_contains: str | None,
) -> str:
    filters = {
        "reason": reason,
        "adapter": adapter,
        "split": split,
        "source_contains": source_contains,
    }
    active = [f"{key}={value}" for key, value in filters.items() if value]
    return ", ".join(active) if active else "none"


def readable_fixture_versions(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    parts = []
    for name in sorted(value):
        versions = value[name]
        if isinstance(versions, list):
            parts.append(f"{name}={','.join(str(version) for version in versions)}")
        else:
            parts.append(f"{name}={versions}")
    return ", ".join(parts)


def readable_rejected_row_locators(
    value: object,
    *,
    total_rejected_rows: int,
    max_rejected_rows: int,
) -> list[str]:
    if not isinstance(value, list) or not value:
        return ["Rejected row locators: none"]
    limit = max(max_rejected_rows, 0)
    lines = [
        "Rejected row locators shown: "
        f"{min(len(value), limit)} of {len(value)} matching "
        f"({total_rejected_rows} total)"
    ]
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        location = readable_row_location(row)
        reason = row.get("reason")
        external_id = row.get("external_id")
        message = row.get("message")
        lines.append(
            f"- {location} reason={reason} external_id={external_id} "
            f"source_row_digest={row.get('source_row_digest')} message={message}"
        )
    if len(value) > limit:
        lines.append(f"- ... {len(value) - limit} more rejected row(s)")
    return lines


def readable_row_location(row: dict[str, object]) -> str:
    source_path = row.get("source_path")
    line_number = row.get("line_number")
    row_index = row.get("row_index")
    if isinstance(line_number, int):
        return f"{source_path}:{line_number}"
    return f"{source_path}:row-{row_index}"


def readable_status_counts(value: object) -> str:
    if not isinstance(value, dict):
        return "unavailable"
    return ", ".join(
        f"{name}={value.get(name, 0)}"
        for name in ("overdue", "due_soon", "scheduled")
    )


def readable_group_counts(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{name}={value[name]['count']}" for name in sorted(value))


def readable_adapter_counts(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{name}={value[name]['task_count']}" for name in sorted(value))


def readable_status_counts_for_dict(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{name}={value[name]}" for name in sorted(value))


def dict_get(value: object, key: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(key, default)
    return default


def readable_list(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ",".join(str(item) for item in value)


def readable_split_map_summary(value: object) -> str:
    if not isinstance(value, dict) or not value.get("provided"):
        return "none"
    return (
        f"{value.get('source_name')} used={value.get('used_count')} "
        f"unused={value.get('unused_count')}"
    )


def readable_split_counts(value: object) -> str:
    if not isinstance(value, dict):
        return "unavailable"
    return ", ".join(f"{split}={value[split]}" for split in sorted(value))


def list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-rsi")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create .rsi harness artifacts.")
    init.add_argument("--force", action="store_true", help="Overwrite existing starter files.")
    init.set_defaults(func=init_project)

    run_parser = sub.add_parser("run", help="Run a task suite and capture traces.")
    run_parser.add_argument("--tasks", default=str(TASKS / "sample.jsonl"))
    run_parser.add_argument("--config", default=str(HARNESS))
    run_parser.add_argument("--model")
    run_parser.add_argument("--mock", action="store_true")
    run_parser.set_defaults(func=run)

    improve_parser = sub.add_parser("improve", help="Propose one small harness improvement.")
    improve_parser.add_argument("--run", help="Run directory. Defaults to latest.")
    improve_parser.add_argument("--model", default=DEFAULT_HARNESS["model"])
    improve_parser.add_argument("--reasoning-effort", default=DEFAULT_HARNESS["reasoning_effort"])
    improve_parser.add_argument("--mock", action="store_true")
    improve_parser.set_defaults(func=improve)

    promote_parser = sub.add_parser("promote", help="Promote a proposal into harness memory/config.")
    promote_parser.add_argument("proposal")
    promote_parser.set_defaults(func=promote_cmd)

    reject_parser = sub.add_parser("reject", help="Reject a proposal with a reason.")
    reject_parser.add_argument("proposal")
    reject_parser.add_argument("--reason", required=True)
    reject_parser.set_defaults(func=reject_cmd)

    benchmark = sub.add_parser("benchmark", help="Manage benchmark environments and gates.")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)

    benchmark_init_parser = benchmark_sub.add_parser("init", help="Create synthetic benchmark splits.")
    benchmark_init_parser.add_argument("--name", default="synthetic")
    benchmark_init_parser.add_argument(
        "--profile",
        help="Compile benchmark sources from benchmarks/<profile> into .rsi/benchmarks/<name>.",
    )
    benchmark_init_parser.set_defaults(func=benchmark_init)

    benchmark_run_parser = benchmark_sub.add_parser("run", help="Run one benchmark split.")
    benchmark_run_parser.add_argument("--benchmark", default="synthetic")
    benchmark_run_parser.add_argument("--split", choices=["train", "heldout", "regression"], required=True)
    benchmark_run_parser.add_argument("--harness", default="H0")
    benchmark_run_parser.add_argument("--model")
    benchmark_run_parser.add_argument("--mock", action="store_true")
    benchmark_run_parser.set_defaults(func=benchmark_run)

    benchmark_compare_parser = benchmark_sub.add_parser("compare", help="Compare two run directories.")
    benchmark_compare_parser.add_argument("--baseline-run", required=True)
    benchmark_compare_parser.add_argument("--candidate-run", required=True)
    benchmark_compare_parser.set_defaults(func=benchmark_compare)

    benchmark_gate_parser = benchmark_sub.add_parser("gate", help="Write a promotion gate decision.")
    benchmark_gate_parser.add_argument("--baseline-run", required=True)
    benchmark_gate_parser.add_argument("--candidate-run", required=True)
    benchmark_gate_parser.add_argument("--min-pass-rate-delta", type=float, default=0.0)
    benchmark_gate_parser.add_argument("--max-allowed-drop", type=float, default=0.0)
    benchmark_gate_parser.add_argument("--max-environment-drop", type=float)
    benchmark_gate_parser.set_defaults(func=benchmark_gate)

    benchmark_coverage_parser = benchmark_sub.add_parser(
        "coverage",
        help="Write environment/family/split coverage report for a benchmark.",
    )
    benchmark_coverage_parser.add_argument("--benchmark", default="synthetic")
    benchmark_coverage_parser.set_defaults(func=benchmark_coverage)

    benchmark_waivers_parser = benchmark_sub.add_parser(
        "waivers",
        help="Write waiver lifecycle report grouped by owner and review date.",
    )
    benchmark_waivers_parser.add_argument("--benchmark", default="synthetic")
    benchmark_waivers_parser.add_argument(
        "--as-of",
        help="Review date in YYYY-MM-DD format. Defaults to today's UTC date.",
    )
    benchmark_waivers_parser.add_argument(
        "--due-within-days",
        type=int,
        default=30,
        help="Mark reviews due soon when review_by is within this many days.",
    )
    benchmark_waivers_parser.set_defaults(func=benchmark_waivers)

    benchmark_adapters_parser = benchmark_sub.add_parser(
        "adapters",
        help="Write read-only external adapter metadata report for a benchmark.",
    )
    benchmark_adapters_parser.add_argument("--benchmark", default="synthetic")
    benchmark_adapters_parser.set_defaults(func=benchmark_adapters)

    benchmark_levels_parser = benchmark_sub.add_parser(
        "levels",
        help="Write a read-only evaluation/testing-level readiness report.",
    )
    benchmark_levels_parser.add_argument("--benchmark", default="synthetic")
    benchmark_levels_parser.add_argument("--json", action="store_true")
    benchmark_levels_parser.set_defaults(func=benchmark_levels)

    benchmark_import_adapters_parser = benchmark_sub.add_parser(
        "import-adapters",
        help="Compile frozen local external-adapter exports into a source profile.",
    )
    benchmark_import_adapters_parser.add_argument("--source", required=True)
    benchmark_import_adapters_parser.add_argument("--profile", required=True)
    benchmark_import_adapters_parser.add_argument("--suite-version")
    benchmark_import_adapters_parser.add_argument("--split-map")
    benchmark_import_adapters_parser.add_argument(
        "--allow-rejected-rows",
        "--allow-rejects",
        dest="allow_rejects",
        action="store_true",
        help="Write a partial source profile when invalid rows are rejected but required splits remain.",
    )
    benchmark_import_adapters_parser.add_argument(
        "--review-split-map",
        action="store_true",
        help="Write only an import review artifact under benchmarks/_import_reviews/<profile>.",
    )
    benchmark_import_adapters_parser.add_argument("--force", action="store_true")
    benchmark_import_adapters_parser.set_defaults(func=benchmark_import_adapters)

    benchmark_import_audit_parser = benchmark_sub.add_parser(
        "import-audit",
        help="Read an import report or review artifact without changing benchmark state.",
    )
    benchmark_import_audit_parser.add_argument("--profile", required=True)
    benchmark_import_audit_parser.add_argument(
        "--review",
        action="store_true",
        help="Read benchmarks/_import_reviews/<profile>/import_review.json instead of import_report.json.",
    )
    benchmark_import_audit_parser.add_argument(
        "--max-rejected-rows",
        type=int,
        default=5,
        help="Maximum rejected-row locators to print in the readable summary.",
    )
    benchmark_import_audit_parser.add_argument(
        "--reason",
        help="Only print rejected-row locators with this rejection reason.",
    )
    benchmark_import_audit_parser.add_argument(
        "--adapter",
        help="Only print rejected-row locators for this adapter name.",
    )
    benchmark_import_audit_parser.add_argument(
        "--split",
        choices=["train", "heldout", "regression"],
        help="Only print rejected-row locators from this split.",
    )
    benchmark_import_audit_parser.add_argument(
        "--source-contains",
        help="Only print rejected-row locators whose source_path contains this text.",
    )
    benchmark_import_audit_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full import artifact JSON.",
    )
    benchmark_import_audit_parser.set_defaults(func=benchmark_import_audit)

    harness = sub.add_parser("harness", help="Manage versioned harness configs.")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)

    harness_list_parser = harness_sub.add_parser("list", help="List harness versions.")
    harness_list_parser.set_defaults(func=harness_list)

    harness_create_parser = harness_sub.add_parser(
        "create-candidate",
        help="Create a candidate harness version from a parent and proposal.",
    )
    harness_create_parser.add_argument("--parent", required=True)
    harness_create_parser.add_argument("--candidate", "--new-id", required=True)
    harness_create_parser.add_argument("--proposal", required=True)
    harness_create_parser.add_argument("--overwrite", action="store_true")
    harness_create_parser.set_defaults(func=harness_create_candidate)

    harness_promote_parser = harness_sub.add_parser(
        "promote",
        help="Promote an existing candidate harness using a promote gate.",
    )
    harness_promote_parser.add_argument("--candidate", "--new-id", required=True)
    harness_promote_parser.add_argument("--gate", required=True)
    harness_promote_parser.set_defaults(func=harness_promote)

    harness_version_parser = harness_sub.add_parser(
        "propose-version",
        help="Alias for `harness create-candidate`.",
    )
    harness_version_parser.add_argument("--parent", required=True)
    harness_version_parser.add_argument("--candidate", "--new-id", required=True)
    harness_version_parser.add_argument("--proposal", required=True)
    harness_version_parser.add_argument("--overwrite", action="store_true")
    harness_version_parser.set_defaults(func=harness_create_candidate)

    experiment = sub.add_parser("experiment", help="Run higher-level harness experiments.")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)

    cycle_parser = experiment_sub.add_parser(
        "cycle",
        help="Run train -> propose -> candidate -> heldout/regression gates -> promote.",
    )
    cycle_parser.add_argument("--parent", required=True)
    cycle_parser.add_argument("--candidate", required=True)
    cycle_parser.add_argument("--benchmark", default="synthetic")
    cycle_parser.add_argument("--model")
    cycle_parser.add_argument("--reasoning-effort", default=DEFAULT_HARNESS["reasoning_effort"])
    cycle_parser.add_argument("--mock", action="store_true")
    cycle_parser.add_argument("--min-heldout-delta", type=float, default=0.0)
    cycle_parser.add_argument("--max-regression-drop", type=float, default=0.0)
    cycle_parser.add_argument("--no-promote", action="store_true")
    cycle_parser.set_defaults(func=experiment_cycle)

    stability_parser = experiment_sub.add_parser(
        "stability",
        help="Run repeated experiment cycles and summarize gate stability.",
    )
    stability_parser.add_argument("--parent", required=True)
    stability_parser.add_argument("--candidate-prefix", default="H")
    stability_parser.add_argument("--first-candidate-index", type=int)
    stability_parser.add_argument("--cycles", type=int, default=2)
    stability_parser.add_argument("--benchmark", default="synthetic")
    stability_parser.add_argument("--model")
    stability_parser.add_argument("--reasoning-effort", default=DEFAULT_HARNESS["reasoning_effort"])
    stability_parser.add_argument("--mock", action="store_true")
    stability_parser.add_argument("--min-heldout-delta", type=float, default=0.0)
    stability_parser.add_argument("--max-regression-drop", type=float, default=0.0)
    stability_parser.add_argument("--no-promote", action="store_true")
    stability_parser.set_defaults(func=experiment_stability)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
