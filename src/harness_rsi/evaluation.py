from __future__ import annotations

import re
from typing import Any


def evaluate(answer: str, evaluator: dict[str, Any]) -> dict[str, Any]:
    kind = evaluator.get("type", "contains")
    expected = str(evaluator.get("expected", ""))

    if kind == "contains":
        passed = expected.lower() in answer.lower()
    elif kind == "exact":
        passed = answer.strip() == expected
    elif kind == "regex":
        passed = bool(re.search(expected, answer, flags=re.I | re.M))
    else:
        raise ValueError(f"Unknown eval type: {kind}")

    return {
        "passed": passed,
        "type": kind,
        "expected": expected,
        "observed": answer,
    }
