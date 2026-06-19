from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_rsi.benchmarks import compare_runs, gate_candidate, init_benchmark, run_benchmark
from harness_rsi.decisions import promote, reject
from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.improve import latest_run, propose_patch
from harness_rsi.io import read_json, write_json
from harness_rsi.paths import HARNESS, LEARNINGS, ROOT, RUNS, TASKS, ensure_dirs
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
    path = init_benchmark(args.name)
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
    )
    print(f"Wrote gate decision to {path}")
    print(readable_json(read_json(path)))
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


def readable_json(payload: object) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


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
    benchmark_gate_parser.set_defaults(func=benchmark_gate)

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
