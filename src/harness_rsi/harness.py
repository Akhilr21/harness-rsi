from __future__ import annotations

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
) -> Path:
    config = load_harness(config_path)
    if model_override:
        config["model"] = model_override

    tasks = read_jsonl(tasks_path)
    learnings = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    trace_path = run_dir / "trace.jsonl"
    results = []

    write_json(run_dir / "harness.snapshot.json", config)
    write_json(run_dir / "input.json", {"tasks_path": str(tasks_path), "task_count": len(tasks)})

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
                "attempt": attempt,
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

    passed = sum(1 for item in results if item and item["score"]["passed"])
    summary = {
        "run_id": run_id,
        "tasks": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "results": [
            {
                "task_id": item["task_id"],
                "passed": item["score"]["passed"],
                "attempt": item["attempt"],
            }
            for item in results
            if item
        ],
    }
    write_json(run_dir / "results.json", summary)
    (run_dir / "summary.md").write_text(
        f"# Run {run_id}\n\nPassed {passed}/{len(results)} tasks.\n"
    )
    return run_dir
