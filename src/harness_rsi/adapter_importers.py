from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_rsi.benchmarks import (
    ADAPTER_KINDS,
    REQUIRED_SPLITS,
    SOURCE_BENCHMARKS,
    digest_payload,
    evaluator_digest,
    validate_external_adapter_metadata,
    write_jsonl,
)
from harness_rsi.io import read_json, write_json

ADAPTER_CONTRACT_VERSION = "adapter-contract-v0.1"
IMPORTER_VERSION = "external-adapter-importer-v0.1"

DEFAULT_ADAPTERS = {
    "terminal-bench": {
        "kind": "terminal",
        "source_url": "https://www.tbench.ai/",
        "environment": "terminal_ops",
        "family": "terminal_task_planning",
    },
    "swe-bench": {
        "kind": "swe_patch",
        "source_url": "https://www.swebench.com/SWE-bench/",
        "environment": "coding_micro",
        "family": "issue_patch_planning",
    },
    "tau2-bench": {
        "kind": "tool_agent_user",
        "source_url": "https://github.com/sierra-research/tau2-bench",
        "environment": "customer_support",
        "family": "tool_agent_user",
    },
    "tau3-bench": {
        "kind": "tool_agent_user",
        "source_url": "https://github.com/sierra-research/tau2-bench",
        "environment": "customer_support",
        "family": "tool_agent_user",
    },
}


@dataclass(frozen=True)
class FrozenExport:
    rows: list[dict[str, Any]]
    defaults: dict[str, Any]
    source_name: str
    source_digest: str


def import_external_adapter_profile(
    *,
    source: Path,
    profile: str,
    suite_version: str | None = None,
    force: bool = False,
) -> Path:
    export = read_frozen_export(source)
    output = source_profile_output(profile)
    if output.exists() and not force:
        raise RuntimeError(f"Benchmark source profile already exists: {output}")

    split_rows = normalize_export_rows(export, profile=profile)
    validate_external_adapter_metadata(split_rows)
    ensure_required_import_splits(split_rows)

    if output.exists():
        shutil.rmtree(output)
    write_imported_source_profile(
        output=output,
        profile=profile,
        split_rows=split_rows,
        export=export,
        suite_version=suite_version or export.defaults.get("suite_version") or f"{profile}.1",
    )
    return output


def read_frozen_export(source: Path) -> FrozenExport:
    if not source.exists():
        raise RuntimeError(f"Frozen export source not found: {source}")
    if source.is_dir():
        return read_export_directory(source)
    if source.suffix == ".jsonl":
        rows = read_export_jsonl(source)
        return FrozenExport(
            rows=rows,
            defaults={},
            source_name=source.name,
            source_digest=digest_payload({"file": source.name, "rows": rows}),
        )
    if source.suffix == ".json":
        payload = read_json(source)
        rows, defaults = rows_and_defaults_from_payload(payload, source)
        return FrozenExport(
            rows=rows,
            defaults=defaults,
            source_name=source.name,
            source_digest=digest_payload({"file": source.name, "payload": payload}),
        )
    raise RuntimeError(f"Unsupported frozen export format: {source}")


def read_export_directory(source: Path) -> FrozenExport:
    if (source / "tasks.json").exists():
        payload = read_json(source / "tasks.json")
        rows, defaults = rows_and_defaults_from_payload(payload, source / "tasks.json")
        return FrozenExport(
            rows=rows,
            defaults=defaults,
            source_name=source.name,
            source_digest=digest_payload({"directory": source.name, "tasks": payload}),
        )

    files = sorted(source.rglob("*.jsonl"))
    if not files:
        raise RuntimeError(f"Frozen export directory has no JSONL task files: {source}")
    rows: list[dict[str, Any]] = []
    digest_files = []
    for path in files:
        file_rows = read_export_jsonl(path)
        rows.extend(file_rows)
        digest_files.append({"path": str(path.relative_to(source)), "rows": file_rows})
    return FrozenExport(
        rows=rows,
        defaults={},
        source_name=source.name,
        source_digest=digest_payload({"directory": source.name, "files": digest_files}),
    )


def read_export_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid frozen export JSONL at {path}:{line_number}: {error}") from error
        if not isinstance(row, dict):
            raise RuntimeError(f"Frozen export row at {path}:{line_number} must be an object.")
        rows.append(row)
    return rows


def rows_and_defaults_from_payload(
    payload: Any,
    source: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        return payload, {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"Frozen export JSON must be an object or object-row list: {source}")
    rows = payload.get("tasks", payload.get("rows"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError(f"Frozen export JSON must contain object rows under tasks or rows: {source}")
    defaults = {
        key: payload[key]
        for key in (
            "suite_version",
            "fixture_version",
            "source_url",
            "adapter_contract_version",
        )
        if key in payload
    }
    return rows, defaults


def source_profile_output(profile: str) -> Path:
    profile_path = Path(profile)
    if profile_path.is_absolute() or any(part in {"", ".", ".."} for part in profile_path.parts):
        raise RuntimeError(f"Invalid benchmark source profile name: {profile}")
    return SOURCE_BENCHMARKS / profile_path


def normalize_export_rows(export: FrozenExport, *, profile: str) -> dict[str, list[dict[str, Any]]]:
    if not export.rows:
        raise RuntimeError("Frozen export contains no rows.")
    split_rows: dict[str, list[dict[str, Any]]] = {split: [] for split in REQUIRED_SPLITS}
    seen_ids: dict[str, set[str]] = {split: set() for split in REQUIRED_SPLITS}
    for index, row in enumerate(export.rows, start=1):
        normalized = normalize_export_row(
            row,
            index=index,
            profile=profile,
            defaults=export.defaults,
        )
        split = normalized["split"]
        if normalized["id"] in seen_ids[split]:
            raise RuntimeError(f"Duplicate imported task id {normalized['id']} in {split} split.")
        seen_ids[split].add(normalized["id"])
        split_rows[split].append(normalized)
    ensure_unique_external_ids(split_rows)
    return split_rows


def normalize_export_row(
    row: dict[str, Any],
    *,
    index: int,
    profile: str,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    split = str(row.get("split") or row.get("local_split") or "").strip()
    if split not in REQUIRED_SPLITS:
        raise RuntimeError(
            f"Frozen export row {index} must set split to one of {', '.join(REQUIRED_SPLITS)}."
        )

    adapter = normalized_adapter(row, index=index, defaults=defaults)
    shape_defaults = DEFAULT_ADAPTERS.get(str(adapter["name"]), {})
    instruction = first_nonempty(
        row,
        ("instruction", "prompt", "problem_statement", "task", "scenario"),
    )
    if instruction is None:
        raise RuntimeError(f"Frozen export row {index} is missing instruction-like text.")

    evaluator = row.get("eval")
    if evaluator is None and str(row.get("expected", "")).strip():
        evaluator = {"type": "exact", "expected": str(row["expected"])}
    if not isinstance(evaluator, dict):
        raise RuntimeError(f"Frozen export row {index} is missing a deterministic eval object.")

    external_id = str(adapter["external_id"])
    task_id = str(row.get("id") or f"{split}_{sanitize_id(external_id)}")
    normalized = {
        "id": task_id,
        "environment": str(row.get("environment") or shape_defaults.get("environment") or "default"),
        "family": str(row.get("family") or shape_defaults.get("family") or adapter["kind"]),
        "split": split,
        "instruction": instruction,
        "eval": evaluator,
        "external_adapter": adapter,
        "source": str(
            row.get("source") or f"{profile}/frozen-export/{adapter['name']}/{external_id}"
        ),
    }
    normalized["evaluator_digest"] = evaluator_digest(evaluator)
    return normalized


def normalized_adapter(
    row: dict[str, Any],
    *,
    index: int,
    defaults: dict[str, Any],
) -> dict[str, str]:
    source_adapter = row.get("external_adapter") or row.get("adapter") or {}
    if not isinstance(source_adapter, dict):
        raise RuntimeError(f"Frozen export row {index} adapter metadata must be an object.")

    name = string_value(source_adapter.get("name") or row.get("adapter_name") or row.get("benchmark"))
    if name is None:
        raise RuntimeError(f"Frozen export row {index} is missing adapter name.")

    shape_defaults = DEFAULT_ADAPTERS.get(name, {})
    kind = string_value(
        source_adapter.get("kind") or row.get("adapter_kind") or row.get("kind")
    ) or string_value(shape_defaults.get("kind"))
    external_id = string_value(
        source_adapter.get("external_id")
        or row.get("external_id")
        or row.get("source_task_id")
        or row.get("task_id")
    )
    fixture_version = string_value(
        source_adapter.get("fixture_version")
        or row.get("fixture_version")
        or defaults.get("fixture_version")
    )
    source_url = string_value(
        source_adapter.get("source_url")
        or row.get("source_url")
        or defaults.get("source_url")
        or shape_defaults.get("source_url")
    )
    mode = string_value(source_adapter.get("mode") or row.get("mode") or "read_only")

    missing = [
        key
        for key, value in {
            "kind": kind,
            "external_id": external_id,
            "fixture_version": fixture_version,
            "source_url": source_url,
            "mode": mode,
        }.items()
        if value is None
    ]
    if missing:
        raise RuntimeError(
            f"Frozen export row {index} is missing adapter field(s): {', '.join(missing)}."
        )
    if kind not in ADAPTER_KINDS:
        raise RuntimeError(f"Frozen export row {index} has unsupported adapter kind: {kind}.")
    if mode != "read_only":
        raise RuntimeError(f"Frozen export row {index} must use mode: read_only.")

    return {
        "name": name,
        "kind": kind,
        "external_id": external_id,
        "fixture_version": fixture_version,
        "source_url": source_url,
        "mode": mode,
    }


def write_imported_source_profile(
    *,
    output: Path,
    profile: str,
    split_rows: dict[str, list[dict[str, Any]]],
    export: FrozenExport,
    suite_version: str,
) -> None:
    for split, rows in split_rows.items():
        for adapter_name, adapter_rows in group_by_adapter_name(rows).items():
            write_jsonl(output / "sources" / split / f"{sanitize_filename(adapter_name)}.jsonl", adapter_rows)

    manifest = {
        "id": profile,
        "suite_version": suite_version,
        "description": (
            "Imported read-only external-adapter tasks from a frozen local export. "
            "This profile preserves fixture identity but does not run external benchmark harnesses."
        ),
        "adapter_contract_version": export.defaults.get(
            "adapter_contract_version",
            ADAPTER_CONTRACT_VERSION,
        ),
        "importer_version": IMPORTER_VERSION,
        "source_export_name": export.source_name,
        "source_export_digest": export.source_digest,
        "external_adapters": adapter_manifest(split_rows),
        "coverage_policy": imported_coverage_policy(split_rows),
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "gate_policy.json", imported_gate_policy())
    report = import_report(
        profile=profile,
        suite_version=suite_version,
        split_rows=split_rows,
        export=export,
    )
    write_json(output / "import_report.json", report)


def import_report(
    *,
    profile: str,
    suite_version: str,
    split_rows: dict[str, list[dict[str, Any]]],
    export: FrozenExport,
) -> dict[str, Any]:
    rows = [row for split in REQUIRED_SPLITS for row in split_rows[split]]
    report = {
        "profile": profile,
        "suite_version": suite_version,
        "source_export_name": export.source_name,
        "source_export_digest": export.source_digest,
        "importer_version": IMPORTER_VERSION,
        "adapter_contract_version": export.defaults.get(
            "adapter_contract_version",
            ADAPTER_CONTRACT_VERSION,
        ),
        "status": "pass",
        "read_only": True,
        "gate_semantics_changed": False,
        "task_count": len(rows),
        "split_counts": count_field(rows, "split"),
        "kind_counts": count_adapter_field(rows, "kind"),
        "adapter_counts": count_adapter_field(rows, "name"),
        "fixture_versions": fixture_versions(rows),
        "metadata_failures": [],
    }
    report["import_report_digest"] = digest_payload(report)
    return report


def adapter_manifest(split_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    adapters: dict[str, dict[str, str]] = {}
    for rows in split_rows.values():
        for row in rows:
            adapter = row["external_adapter"]
            adapters[str(adapter["name"])] = {
                "name": str(adapter["name"]),
                "kind": str(adapter["kind"]),
                "mode": str(adapter["mode"]),
                "source_url": str(adapter["source_url"]),
            }
    return [adapters[name] for name in sorted(adapters)]


def imported_coverage_policy(split_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    required = []
    seen: set[tuple[str, str, str]] = set()
    for split in ("heldout", "regression"):
        for row in split_rows[split]:
            key = (row["environment"], row["family"], split)
            if key in seen:
                continue
            seen.add(key)
            required.append(
                {
                    "environment": row["environment"],
                    "family": row["family"],
                    "split": split,
                    "reason": (
                        "Imported adapter coverage must preserve "
                        f"{row['external_adapter']['name']} {split} metadata."
                    ),
                }
            )
    return {"fail_on_missing_required": True, "required": required, "waivers": []}


def imported_gate_policy() -> dict[str, Any]:
    return {
        "heldout": {
            "min_pass_rate_delta": 0.0,
            "max_allowed_drop": 0.0,
            "max_environment_drop": 0.0,
            "protected_environments": "all",
            "max_attempt_delta": 0,
            "max_tool_call_delta": 0,
        },
        "regression": {
            "min_pass_rate_delta": 0.0,
            "max_allowed_drop": 0.0,
            "max_environment_drop": 0.0,
            "protected_environments": "all",
            "max_attempt_delta": 0,
            "max_tool_call_delta": 0,
        },
    }


def ensure_required_import_splits(split_rows: dict[str, list[dict[str, Any]]]) -> None:
    missing = [split for split in REQUIRED_SPLITS if not split_rows[split]]
    if missing:
        raise RuntimeError(f"Frozen export is missing required split(s): {', '.join(missing)}.")


def ensure_unique_external_ids(split_rows: dict[str, list[dict[str, Any]]]) -> None:
    seen: dict[tuple[str, str], str] = {}
    for split, rows in split_rows.items():
        for row in rows:
            adapter = row["external_adapter"]
            key = (str(adapter["name"]), str(adapter["external_id"]))
            if key in seen:
                raise RuntimeError(
                    "Duplicate imported external id "
                    f"{adapter['external_id']} for {adapter['name']} in "
                    f"{seen[key]} and {split} splits."
                )
            seen[key] = split


def group_by_adapter_name(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["external_adapter"]["name"]), []).append(row)
    return {name: groups[name] for name in sorted(groups)}


def count_field(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field))
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def count_adapter_field(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row["external_adapter"].get(field))
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def fixture_versions(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    versions: dict[str, set[str]] = {}
    for row in rows:
        adapter = row["external_adapter"]
        versions.setdefault(str(adapter["name"]), set()).add(str(adapter["fixture_version"]))
    return {name: sorted(versions[name]) for name in sorted(versions)}


def first_nonempty(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = string_value(row.get(key))
        if value is not None:
            return value
    return None


def string_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sanitize_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return sanitized.strip("_") or "task"


def sanitize_filename(value: str) -> str:
    return sanitize_id(value).lower()
