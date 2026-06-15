from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def call_model(*, model: str, prompt: str, reasoning_effort: str = "medium") -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required unless you pass --mock.")

    body = {
        "model": model,
        "input": prompt,
        "reasoning": {"effort": reasoning_effort},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {error.code}: {detail}") from error

    if text := payload.get("output_text"):
        return text

    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def mock_response(task: dict[str, Any]) -> str:
    evaluator = task.get("eval", {})
    if "expected" in evaluator:
        return str(evaluator["expected"])
    match = re.search(r"include\s+(.+?)(?:\.|$)", task.get("instruction", ""), re.I)
    if match:
        return match.group(1)
    return "mock response"
