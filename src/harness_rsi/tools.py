from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any


def parse_tool_call(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    tool = payload.get("tool") if isinstance(payload, dict) else None
    if isinstance(tool, dict) and tool.get("name") == "shell":
        return tool
    return None


def run_shell_tool(tool: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    tool_config = config.get("tools", {})
    command = str(tool.get("command", ""))
    if not tool_config.get("shell"):
        return {"ok": False, "error": "shell tool is disabled"}

    allowed = set(tool_config.get("allowed_commands", []))
    executable = shlex.split(command)[0] if command.strip() else ""
    if allowed and executable not in allowed:
        return {"ok": False, "error": f"command not allowed: {executable}"}

    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=int(tool_config.get("timeout_seconds", 30)),
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }
