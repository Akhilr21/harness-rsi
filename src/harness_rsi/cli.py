from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_rsi.decisions import promote, reject
from harness_rsi.harness import DEFAULT_HARNESS, run_suite
from harness_rsi.improve import latest_run, propose_patch
from harness_rsi.io import write_json
from harness_rsi.paths import HARNESS, LEARNINGS, ROOT, RUNS, TASKS, ensure_dirs


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
