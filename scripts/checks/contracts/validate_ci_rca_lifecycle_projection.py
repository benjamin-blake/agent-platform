"""CI-RCA lifecycle projection-field check (rec-3059 first-wave enforcer build).

Asserts docs/contracts/ci-rca-lifecycle.yaml's projection_fields are a SUBSET of the live
CiRcaContext (scripts/ops_portal/ci_rca_schema.py) pydantic model fields -- deliberately
one-directional, since CiRcaContext carries many non-projection fields (proximate_cause,
why_chain, fingerprint, ...); escape_class's declared enum equals the live pydantic pattern
alternation; and watched_workflow_set's pointers (source_of_truth file + field,
evaluator/evaluator_module) resolve.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_NAME = "ci-rca-lifecycle.yaml"
_ALTERNATION_RE = re.compile(r"^\^\((.*)\)\$$")


def _field_pattern(field_info: object) -> str | None:
    for meta in getattr(field_info, "metadata", []):
        pattern = getattr(meta, "pattern", None)
        if isinstance(pattern, str):
            return pattern
    return None


def _check_projection_fields(failed: list[str], path: Path, projection_fields: dict) -> None:
    from scripts.ops_portal.ci_rca_schema import CiRcaContext  # noqa: PLC0415

    live_fields = CiRcaContext.model_fields
    unknown = sorted(f for f in projection_fields if f not in live_fields)
    if unknown:
        failed.append(f"CI-RCA lifecycle projection: {_CONTRACT_NAME} projection_fields not on CiRcaContext: {unknown}")

    escape_field = projection_fields.get("escape_class")
    declared_enum = escape_field.get("enum") if isinstance(escape_field, dict) else None
    if not isinstance(declared_enum, list) or not declared_enum:
        failed.append(f"CI-RCA lifecycle projection: {path} projection_fields.escape_class missing a non-empty 'enum'")
        return

    live_field_info = live_fields.get("escape_class")
    live_pattern = _field_pattern(live_field_info) if live_field_info is not None else None
    match = _ALTERNATION_RE.match(live_pattern) if live_pattern else None
    live_enum = match.group(1).split("|") if match else None
    if live_enum is None or sorted(declared_enum) != sorted(live_enum):
        failed.append(
            f"CI-RCA lifecycle projection: {_CONTRACT_NAME} escape_class.enum={declared_enum} does not equal "
            f"the live CiRcaContext.escape_class pattern alternation {live_enum}"
        )


def _check_watched_workflow_set(failed: list[str], watched: dict) -> None:
    problems: list[str] = []

    sot_path = watched.get("source_of_truth")
    sot_field = watched.get("source_of_truth_field")
    if not isinstance(sot_path, str) or not (_common.ROOT / sot_path).is_file():
        problems.append(f"source_of_truth {sot_path!r} does not resolve to an existing file")
    else:
        key = sot_field.split(":", 1)[0].strip() if isinstance(sot_field, str) else ""
        try:
            sot_data = yaml.safe_load((_common.ROOT / sot_path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            sot_data = None
        if not key or not isinstance(sot_data, dict) or key not in sot_data:
            problems.append(f"source_of_truth_field {sot_field!r} names no top-level key present in {sot_path}")

    evaluator_name = watched.get("evaluator")
    if not isinstance(evaluator_name, str) or evaluator_name not in registry.all_checks():
        problems.append(f"evaluator {evaluator_name!r} is not a registered check")

    evaluator_module = watched.get("evaluator_module")
    if not isinstance(evaluator_module, str) or not (_common.ROOT / evaluator_module).is_file():
        problems.append(f"evaluator_module {evaluator_module!r} does not resolve to an existing file")

    if problems:
        failed.append(f"CI-RCA lifecycle projection: {_CONTRACT_NAME} watched_workflow_set: {'; '.join(problems)}")


@registry.register("validate_ci_rca_lifecycle_projection", owner="platform")
def validate_ci_rca_lifecycle_projection(failed: list[str], *, contracts_dir: Path | None = None) -> None:
    """Fail if projection_fields, escape_class's enum, or watched_workflow_set's pointers drift."""
    print("\n=== CI-RCA lifecycle projection parity ===")
    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    path = target_dir / _CONTRACT_NAME

    if not path.is_file():
        failed.append(f"CI-RCA lifecycle projection: {path} not found")
        registry.skipped(f"{_CONTRACT_NAME} not found")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"CI-RCA lifecycle projection: could not read/parse {path}: {exc}")
        registry.skipped(f"{_CONTRACT_NAME} not parseable")
        return
    if not isinstance(data, dict):
        failed.append(f"CI-RCA lifecycle projection: {path} is not a YAML mapping")
        registry.skipped(f"{_CONTRACT_NAME} not a YAML mapping")
        return

    error_count_before = len(failed)
    examined_count = 0

    projection_fields = data.get("projection_fields")
    if not isinstance(projection_fields, dict) or not projection_fields:
        failed.append(f"CI-RCA lifecycle projection: {path} missing or empty top-level 'projection_fields'")
    else:
        examined_count += len(projection_fields)
        _check_projection_fields(failed, path, projection_fields)

    watched = data.get("watched_workflow_set")
    if not isinstance(watched, dict) or not watched:
        failed.append(f"CI-RCA lifecycle projection: {path} missing or empty top-level 'watched_workflow_set'")
    else:
        examined_count += len(watched)
        _check_watched_workflow_set(failed, watched)

    registry.examined(examined_count, unit="projection_fields_and_pointers")

    if len(failed) == error_count_before:
        print(f"  PASS: {_CONTRACT_NAME} projection_fields, escape_class enum, and watched_workflow_set all resolve.")
