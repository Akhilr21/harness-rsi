from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_rsi.evaluation import evaluate
from harness_rsi.io import append_jsonl, read_json, read_jsonl, write_json
from harness_rsi.model import call_model, mock_response
from harness_rsi.paths import HARNESS, LEARNINGS, RUNS
from harness_rsi.tools import parse_tool_call, run_shell_tool


DEFAULT_HARNESS: dict[str, Any] = {
    "model": "gpt-5.5",
    "reasoning_effort": "medium",
    "max_retries": 1,
    "tools": {
        "shell": False,
        "allowed_commands": [],
        "timeout_seconds": 30,
    },
    "prompt": (
        "You are a careful benchmark agent. Answer the task directly. "
        "Use promoted learnings when relevant. Keep outputs concise."
    ),
}


def load_harness(path: Path = HARNESS) -> dict[str, Any]:
    return read_json(path)


def task_digest(tasks: list[dict[str, Any]]) -> str:
    encoded = json.dumps(tasks, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def harness_behavior_digest(config: dict[str, Any]) -> str:
    behavior = {
        "model": config.get("model"),
        "reasoning_effort": config.get("reasoning_effort"),
        "max_retries": config.get("max_retries"),
        "tools": config.get("tools", {}),
        "prompt": config.get("prompt", ""),
    }
    encoded = json.dumps(behavior, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_prompt(config: dict[str, Any], task: dict[str, Any], learnings: str) -> str:
    return "\n\n".join(
        [
            f"SYSTEM:\n{config['prompt']}",
            (
                "TOOLS:\n"
                f"{config.get('tools', {})}\n"
                'If you need a shell command and it is enabled, return JSON like '
                '{"tool":{"name":"shell","command":"python --version"}}. '
                "Otherwise return only the final answer."
            ),
            f"PROMOTED LEARNINGS:\n{learnings or '(none)'}",
            f"TASK {task['id']}:\n{task['instruction']}",
            "Return only the answer to the task.",
        ]
    )


def run_suite(
    *,
    tasks_path: Path,
    config_path: Path = HARNESS,
    model_override: str | None = None,
    mock: bool = False,
    metadata: dict[str, Any] | None = None,
) -> Path:
    config = load_harness(config_path)
    if model_override:
        config["model"] = model_override

    tasks = read_jsonl(tasks_path)
    tasks_sha = task_digest(tasks)
    harness_sha = harness_behavior_digest(config)
    evaluator_digests = sorted(
        {task["evaluator_digest"] for task in tasks if task.get("evaluator_digest")}
    )
    learnings = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    started = datetime.now(timezone.utc)
    started_monotonic = time.perf_counter()
    run_id = started.strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = RUNS / run_id
    trace_path = run_dir / "trace.jsonl"
    results = []

    write_json(run_dir / "harness.snapshot.json", config)
    write_json(
        run_dir / "input.json",
        {
            "tasks_path": str(tasks_path),
            "task_count": len(tasks),
            "task_digest": tasks_sha,
            "evaluator_digests": evaluator_digests,
            "harness_behavior_digest": harness_sha,
            "metadata": metadata or {},
        },
    )

    for task in tasks:
        best_result = None
        observations: list[dict[str, Any]] = []
        for attempt in range(config.get("max_retries", 0) + 1):
            task_with_observations = dict(task)
            if observations:
                task_with_observations["instruction"] = (
                    f"{task['instruction']}\n\nTool observations:\n{observations}"
                )
            prompt = build_prompt(config, task_with_observations, learnings)
            answer = mock_response(task) if mock else call_model(
                model=config["model"],
                prompt=prompt,
                reasoning_effort=config.get("reasoning_effort", "medium"),
            )
            if tool_call := parse_tool_call(answer):
                observation = run_shell_tool(tool_call, config)
                observations.append({"tool": tool_call, "observation": observation})
                append_jsonl(
                    trace_path,
                    {
                        "task_id": task["id"],
                        "attempt": attempt,
                        "model": config["model"],
                        "mock": mock,
                        "prompt": prompt,
                        "tool_call": tool_call,
                        "observation": observation,
                    },
                )
                continue
            score = evaluate(answer, task["eval"])
            event = {
                "task_id": task["id"],
                "environment": task.get("environment", "default"),
                "family": task.get("family"),
                "evaluator_digest": task.get("evaluator_digest"),
                "suite_version": task.get("suite_version"),
                "source": task.get("source"),
                "attempt": attempt,
                "attempt_count": attempt + 1,
                "tool_calls": len(observations),
                "model": config["model"],
                "mock": mock,
                "prompt": prompt,
                "answer": answer,
                "score": score,
            }
            append_jsonl(trace_path, event)
            best_result = event
            if score["passed"]:
                break
        results.append(best_result)

    ended = datetime.now(timezone.utc)
    passed = sum(1 for item in results if item and item["score"]["passed"])
    completed_results = [item for item in results if item]
    duration_ms = round((time.perf_counter() - started_monotonic) * 1000, 3)
    attempts = sum(item.get("attempt_count", item["attempt"] + 1) for item in completed_results)
    tool_calls = sum(item.get("tool_calls", 0) for item in completed_results)
    metrics = {
        "attempts": attempts,
        "tool_calls": tool_calls,
        "duration_ms": duration_ms,
        "cost_usd": None,
    }
    summary = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_ms": duration_ms,
        "metadata": metadata or {},
        "task_digest": tasks_sha,
        "evaluator_digests": evaluator_digests,
        "harness_behavior_digest": harness_sha,
        "tasks": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "attempts": attempts,
        "tool_calls": tool_calls,
        "metrics": metrics,
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
            "source": "not_collected",
        },
        "per_environment": summarize_by_environment(completed_results),
        "results": [
            {
                "task_id": item["task_id"],
                "environment": item.get("environment", "default"),
                "family": item.get("family"),
                "evaluator_digest": item.get("evaluator_digest"),
                "suite_version": item.get("suite_version"),
                "source": item.get("source"),
                "passed": item["score"]["passed"],
                "attempt": item["attempt"],
                "attempt_count": item.get("attempt_count", item["attempt"] + 1),
                "tool_calls": item.get("tool_calls", 0),
            }
            for item in completed_results
        ],
    }
    write_json(run_dir / "results.json", summary)
    (run_dir / "summary.md").write_text(
        f"# Run {run_id}\n\nPassed {passed}/{len(results)} tasks.\n"
    )
    return run_dir


def summarize_by_environment(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for item in results:
        environment = item.get("environment", "default")
        entry = summary.setdefault(
            environment,
            {"tasks": 0, "passed": 0, "attempts": 0, "tool_calls": 0, "pass_rate": 0.0},
        )
        entry["tasks"] += 1
        entry["passed"] += int(item["score"]["passed"])
        entry["attempts"] += item.get("attempt_count", item["attempt"] + 1)
        entry["tool_calls"] += item.get("tool_calls", 0)
    for entry in summary.values():
        entry["pass_rate"] = entry["passed"] / entry["tasks"] if entry["tasks"] else 0
    return summary
