"""Pydantic-YAML DQ annotation drift gate (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry

_YAML_TO_DQ: dict[str, str] = {
    "not_null": "DqNotNull",
    "accepted_values": "DqAcceptedValues",
    "unique": "DqUnique",
    "relationships": "DqRelationship",
    # DqRecency and DqRowCount are intentionally absent: these markers are table-level
    # blocks in ops.yaml (not column-level tests), so they never appear in the per-column
    # check sets that the drift detector compares. Adding them here would cause false drifts.
}


def _check_drift_for_table(failed: list[str], model_cls: type, table_data: dict) -> None:
    """Compare DqXxx Annotated markers in model_cls against YAML table_data column checks.

    Only in-vocabulary checks are compared (not_null, accepted_values, unique, relationships).
    expression, path_syntax, acceptance_lint have no Pydantic equivalents per CD.12.
    DqDeleted fields short-circuit before YAML lookup. MigratingMarker allows divergence
    until target date passes. Added by T0.12.
    """
    import typing  # noqa: PLC0415

    from src.schemas.annotations import DqDeleted, MigratingMarker  # noqa: PLC0415

    columns: dict = table_data.get("columns", {})
    hints = typing.get_type_hints(model_cls, include_extras=True)

    for field_name, hint in hints.items():
        if typing.get_origin(hint) is not typing.Annotated:
            continue

        args = typing.get_args(hint)
        metadata = args[1:]

        if any(isinstance(m, DqDeleted) for m in metadata):
            continue

        migrating_marker = next((m for m in metadata if isinstance(m, MigratingMarker)), None)

        if field_name not in columns:
            continue

        if migrating_marker and not migrating_marker.is_expired():
            continue

        pydantic_dq_names: set[str] = {type(m).__name__ for m in metadata if type(m).__name__.startswith("Dq")}

        col_entry = columns[field_name] or {}
        yaml_tests = col_entry.get("tests", []) if isinstance(col_entry, dict) else []
        yaml_dq_names: set[str] = set()
        for test in yaml_tests:
            if isinstance(test, str):
                mapped = _YAML_TO_DQ.get(test)
                if mapped:
                    yaml_dq_names.add(mapped)
            elif isinstance(test, dict):
                for check_name in test:
                    mapped = _YAML_TO_DQ.get(check_name)
                    if mapped:
                        yaml_dq_names.add(mapped)

        diff = pydantic_dq_names.symmetric_difference(yaml_dq_names)
        if diff:
            note = ""
            if migrating_marker and migrating_marker.is_expired():
                note = f" (@migrating target={migrating_marker.target!r} expired)"
            print(
                f"  DRIFT: {model_cls.__name__}.{field_name}: "
                f"Pydantic={sorted(pydantic_dq_names)}, YAML={sorted(yaml_dq_names)}{note}"
            )
            failed.append(f"Pydantic-YAML drift: {model_cls.__name__}.{field_name}")


@registry.register("validate_pydantic_yaml_drift", owner="platform")
def validate_pydantic_yaml_drift(failed: list[str]) -> None:
    """Detect drift between Annotated DqXxx markers in Pydantic models and ops.yaml.

    Walks RecPayload and DecisionPayload annotated fields. For each overlapping field
    (present in both model and YAML columns), compares in-vocabulary check sets.
    Fails CI when the symmetric difference is non-empty and no active migration marker exists.
    Added by T0.12. Runs in full presubmit only (not --pre).
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Pydantic-YAML DQ drift ===")

    yaml_path = _common.ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
    if not yaml_path.exists():
        print(f"  FAIL: {yaml_path.relative_to(_common.ROOT)} not found")
        failed.append("Pydantic-YAML drift")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from src.schemas import DecisionPayload, RecPayload  # noqa: PLC0415

        with yaml_path.open(encoding="utf-8") as fh:
            ops = _yaml.safe_load(fh)
        tables: dict = ops.get("tables", {})

        before = len(failed)
        _check_drift_for_table(failed, RecPayload, tables.get("ops_recommendations", {}))
        _check_drift_for_table(failed, DecisionPayload, tables.get("ops_decisions", {}))

        if len(failed) == before:
            print("  PASS: pydantic-yaml drift check")
    except ImportError as exc:
        print(f"  ERROR: Could not import src.schemas: {exc}")
        failed.append("Pydantic-YAML drift")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Pydantic-YAML drift")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Pydantic-YAML drift")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
