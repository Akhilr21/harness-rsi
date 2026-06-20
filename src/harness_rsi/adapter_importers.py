from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
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


@dataclass
class SplitMap:
    entries: dict[str, str]
    source_name: str
    source_digest: str
    used_keys: set[str] = field(default_factory=set)


@dataclass
class ImportResult:
    split_rows: dict[str, list[dict[str, Any]]]
    rejected_rows: list[dict[str, Any]]
    split_map: SplitMap | None


def import_external_adapter_profile(
    *,
    source: Path,
    profile: str,
    suite_version: str | None = None,
    split_map_path: Path | None = None,
    allow_rejects: bool = False,
    review_only: bool = False,
    force: bool = False,
) -> Path:
    export = read_frozen_export(source)
    split_map = read_split_map(split_map_path) if split_map_path else None
    output = source_profile_output(profile)
    review_output = import_review_output(profile)
    if output.exists() and not force and not review_only:
        raise RuntimeError(f"Benchmark source profile already exists: {output}")

    result = normalize_export_rows(export, profile=profile, split_map=split_map)
    resolved_suite_version = suite_version or export.defaults.get("suite_version") or f"{profile}.1"
    if review_only:
        if review_output.exists():
            shutil.rmtree(review_output)
        write_import_review(
            output=review_output,
            profile=profile,
            split_rows=result.split_rows,
            rejected_rows=result.rejected_rows,
            split_map=result.split_map,
            allow_rejects=allow_rejects,
            export=export,
            suite_version=resolved_suite_version,
        )
        return review_output
    if result.rejected_rows and not allow_rejects:
        if review_output.exists():
            shutil.rmtree(review_output)
        write_import_review(
            output=review_output,
            profile=profile,
            split_rows=result.split_rows,
            rejected_rows=result.rejected_rows,
            split_map=result.split_map,
            allow_rejects=allow_rejects,
            export=export,
            suite_version=resolved_suite_version,
        )
        first = result.rejected_rows[0]
        raise RuntimeError(
            "Frozen export has "
            f"{len(result.rejected_rows)} rejected row(s); first rejection: "
            f"{first['message']}. Review written to {review_output / 'import_review.json'}. "
            "Rerun with --allow-rejected-rows to write a partial import."
        )
    validate_external_adapter_metadata(result.split_rows)
    ensure_required_import_splits(result.split_rows)

    if output.exists():
        shutil.rmtree(output)
    write_imported_source_profile(
        output=output,
        profile=profile,
        split_rows=result.split_rows,
        rejected_rows=result.rejected_rows,
        split_map=result.split_map,
        allow_rejects=allow_rejects,
        export=export,
        suite_version=resolved_suite_version,
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
    return SOURCE_BENCHMARKS / safe_profile_path(profile)


def import_review_output(profile: str) -> Path:
    return SOURCE_BENCHMARKS / "_import_reviews" / safe_profile_path(profile)


def safe_profile_path(profile: str) -> Path:
    profile_path = Path(profile)
    if profile_path.is_absolute() or any(part in {"", ".", ".."} for part in profile_path.parts):
        raise RuntimeError(f"Invalid benchmark source profile name: {profile}")
    return profile_path


def read_split_map(path: Path) -> SplitMap:
    if not path.exists():
        raise RuntimeError(f"Split map not found: {path}")
    payload = read_json(path)
    raw_entries = payload.get("splits", payload) if isinstance(payload, dict) else None
    if not isinstance(raw_entries, dict):
        raise RuntimeError("Split map must be an object or contain an object under splits.")
    entries: dict[str, str] = {}
    for raw_key, raw_split in raw_entries.items():
        key = string_value(raw_key)
        split = string_value(raw_split)
        if key is None or split not in REQUIRED_SPLITS:
            raise RuntimeError(
                f"Split map entries must map non-empty keys to {', '.join(REQUIRED_SPLITS)}."
            )
        entries[key] = split
    return SplitMap(
        entries=entries,
        source_name=path.name,
        source_digest=digest_payload({"file": path.name, "payload": payload}),
    )


def normalize_export_rows(
    export: FrozenExport,
    *,
    profile: str,
    split_map: SplitMap | None = None,
) -> ImportResult:
    if not export.rows:
        raise RuntimeError("Frozen export contains no rows.")
    split_rows: dict[str, list[dict[str, Any]]] = {split: [] for split in REQUIRED_SPLITS}
    seen_ids: dict[str, set[str]] = {split: set() for split in REQUIRED_SPLITS}
    seen_external_ids: dict[tuple[str, str], str] = {}
    rejected_rows: list[dict[str, Any]] = []
    for index, row in enumerate(export.rows, start=1):
        try:
            normalized = normalize_export_row(
                row,
                index=index,
                profile=profile,
                defaults=export.defaults,
                split_map=split_map,
            )
        except RuntimeError as error:
            rejected_rows.append(
                rejected_row(
                    row,
                    index=index,
                    reason="invalid_row",
                    error=error,
                    source_name=export.source_name,
                )
            )
            continue
        split = normalized["split"]
        if normalized["id"] in seen_ids[split]:
            rejected_rows.append(
                rejected_row(
                    row,
                    index=index,
                    reason="duplicate_task_id",
                    error=RuntimeError(
                        f"Duplicate imported task id {normalized['id']} in {split} split."
                    ),
                    source_name=export.source_name,
                )
            )
            continue
        adapter = normalized["external_adapter"]
        external_key = (str(adapter["name"]), str(adapter["external_id"]))
        if external_key in seen_external_ids:
            rejected_rows.append(
                rejected_row(
                    row,
                    index=index,
                    reason="duplicate_external_id",
                    error=RuntimeError(
                        "Duplicate imported external id "
                        f"{adapter['external_id']} for {adapter['name']} in "
                        f"{seen_external_ids[external_key]} and {split} splits."
                    ),
                    source_name=export.source_name,
                )
            )
            continue
        seen_ids[split].add(normalized["id"])
        seen_external_ids[external_key] = split
        split_rows[split].append(normalized)
    return ImportResult(split_rows=split_rows, rejected_rows=rejected_rows, split_map=split_map)


def normalize_export_row(
    row: dict[str, Any],
    *,
    index: int,
    profile: str,
    defaults: dict[str, Any],
    split_map: SplitMap | None,
) -> dict[str, Any]:
    adapter = normalized_adapter(row, index=index, defaults=defaults)
    split = resolve_split(row, adapter=adapter, index=index, split_map=split_map)
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


def resolve_split(
    row: dict[str, Any],
    *,
    adapter: dict[str, str],
    index: int,
    split_map: SplitMap | None,
) -> str:
    row_split = string_value(row.get("split") or row.get("local_split"))
    mapped_split = mapped_split_for_raw_split(row_split, split_map) or mapped_split_for_row(
        row,
        adapter=adapter,
        split_map=split_map,
    )
    if row_split and row_split not in REQUIRED_SPLITS and mapped_split is None:
        raise RuntimeError(
            f"Frozen export row {index} must set split to one of {', '.join(REQUIRED_SPLITS)}."
        )
    if row_split in REQUIRED_SPLITS and mapped_split and row_split != mapped_split:
        raise RuntimeError(
            f"Frozen export row {index} split {row_split} conflicts with split map {mapped_split}."
        )
    split = row_split if row_split in REQUIRED_SPLITS else mapped_split
    if split not in REQUIRED_SPLITS:
        raise RuntimeError(
            f"Frozen export row {index} must set split to one of {', '.join(REQUIRED_SPLITS)}."
        )
    return split


def mapped_split_for_raw_split(row_split: str | None, split_map: SplitMap | None) -> str | None:
    if row_split is None or split_map is None or row_split not in split_map.entries:
        return None
    split_map.used_keys.add(row_split)
    return split_map.entries[row_split]


def mapped_split_for_row(
    row: dict[str, Any],
    *,
    adapter: dict[str, str],
    split_map: SplitMap | None,
) -> str | None:
    if split_map is None:
        return None
    for key in split_map_keys(row, adapter):
        if key in split_map.entries:
            split_map.used_keys.add(key)
            return split_map.entries[key]
    return None


def split_map_keys(row: dict[str, Any], adapter: dict[str, str]) -> list[str]:
    keys = [
        f"{adapter['name']}:{adapter['external_id']}",
        adapter["external_id"],
    ]
    for key in ("id", "task_id", "source_task_id"):
        value = string_value(row.get(key))
        if value:
            keys.append(value)
            keys.append(f"{adapter['name']}:{value}")
    return dedupe_strings(keys)


def write_imported_source_profile(
    *,
    output: Path,
    profile: str,
    split_rows: dict[str, list[dict[str, Any]]],
    rejected_rows: list[dict[str, Any]],
    split_map: SplitMap | None,
    allow_rejects: bool,
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
        "import_status": import_status(rejected_rows, review_only=False),
        "rejected_row_count": len(rejected_rows),
        "split_map": split_map_summary(split_map),
        "external_adapters": adapter_manifest(split_rows),
        "coverage_policy": imported_coverage_policy(split_rows),
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "gate_policy.json", imported_gate_policy())
    report = import_report(
        profile=profile,
        suite_version=suite_version,
        split_rows=split_rows,
        rejected_rows=rejected_rows,
        split_map=split_map,
        allow_rejects=allow_rejects,
        export=export,
        review_only=False,
    )
    write_json(output / "import_report.json", report)


def write_import_review(
    *,
    output: Path,
    profile: str,
    split_rows: dict[str, list[dict[str, Any]]],
    rejected_rows: list[dict[str, Any]],
    split_map: SplitMap | None,
    allow_rejects: bool,
    export: FrozenExport,
    suite_version: str,
) -> None:
    report = import_report(
        profile=profile,
        suite_version=suite_version,
        split_rows=split_rows,
        rejected_rows=rejected_rows,
        split_map=split_map,
        allow_rejects=allow_rejects,
        export=export,
        review_only=True,
    )
    write_json(output / "import_review.json", report)


def import_report(
    *,
    profile: str,
    suite_version: str,
    split_rows: dict[str, list[dict[str, Any]]],
    rejected_rows: list[dict[str, Any]],
    split_map: SplitMap | None,
    allow_rejects: bool,
    export: FrozenExport,
    review_only: bool,
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
        "status": import_status(rejected_rows, review_only=review_only),
        "review_only": review_only,
        "read_only": True,
        "gate_semantics_changed": False,
        "allow_rejects": allow_rejects,
        "source_row_count": len(rows) + len(rejected_rows),
        "row_count": len(rows) + len(rejected_rows),
        "task_count": len(rows),
        "accepted_task_count": len(rows),
        "imported_row_count": len(rows),
        "rejected_row_count": len(rejected_rows),
        "rejection_reason_counts": count_rejection_reasons(rejected_rows),
        "accepted_rows_digest": digest_payload(rows),
        "rejected_rows_digest": digest_payload(rejected_rows),
        "split_map_digest": split_map.source_digest if split_map else None,
        "split_counts": count_field(rows, "split"),
        "kind_counts": count_adapter_field(rows, "kind"),
        "adapter_counts": count_adapter_field(rows, "name"),
        "fixture_versions": fixture_versions(rows),
        "split_map": split_map_summary(split_map),
        "rejected_rows": rejected_rows,
        "metadata_failures": [],
    }
    report["import_report_digest"] = digest_payload(report)
    return report


def import_status(rejected_rows: list[dict[str, Any]], *, review_only: bool) -> str:
    if review_only:
        return "review"
    return "pass_with_rejections" if rejected_rows else "pass"


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


def count_rejection_reasons(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get("reason"))
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def fixture_versions(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    versions: dict[str, set[str]] = {}
    for row in rows:
        adapter = row["external_adapter"]
        versions.setdefault(str(adapter["name"]), set()).add(str(adapter["fixture_version"]))
    return {name: sorted(versions[name]) for name in sorted(versions)}


def split_map_summary(split_map: SplitMap | None) -> dict[str, Any]:
    if split_map is None:
        return {"provided": False}
    unused = sorted(set(split_map.entries) - split_map.used_keys)
    return {
        "provided": True,
        "source_name": split_map.source_name,
        "source_digest": split_map.source_digest,
        "entry_count": len(split_map.entries),
        "used_count": len(split_map.used_keys),
        "unused_count": len(unused),
        "unused_keys": unused,
    }


def rejected_row(
    row: dict[str, Any],
    *,
    index: int,
    reason: str,
    error: RuntimeError,
    source_name: str,
) -> dict[str, Any]:
    return {
        "row_index": index,
        "source_path": source_name,
        "line_number": None,
        "status": "rejected",
        "reason": reason,
        "message": str(error),
        "adapter_name": string_value(
            adapter_value(row, "name") or row.get("adapter_name") or row.get("benchmark")
        ),
        "external_id": string_value(
            adapter_value(row, "external_id")
            or row.get("external_id")
            or row.get("source_task_id")
            or row.get("task_id")
        ),
        "split": string_value(row.get("split") or row.get("local_split")),
        "source_row_digest": digest_payload(row),
        "row_keys": sorted(str(key) for key in row),
    }


def adapter_value(row: dict[str, Any], key: str) -> object:
    adapter = row.get("external_adapter") or row.get("adapter")
    if isinstance(adapter, dict):
        return adapter.get(key)
    return None


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
