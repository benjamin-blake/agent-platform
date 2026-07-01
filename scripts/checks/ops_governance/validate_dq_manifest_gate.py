# complexity-waiver: decision-43
"""DQ manifest enforcement-readiness gate (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_dq_manifest_gate", owner="platform")
def validate_dq_manifest_gate(failed: list[str]) -> None:
    """For every enforced: true test in ops.yaml, assert the decisions manifest is in an allowed state.

    Allowed states: READY_NOW, write_fix_deployed, GRADUATED, NEEDS_TEMPORAL_GATE.
    Any other state (including NEEDS_WRITE_FIX, NEEDS_DATA_CORRECTION, missing, or unknown)
    is rejected so that unrecognised states fail closed rather than silently passing.
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== DQ manifest gate ===")

    ops_yaml_path = _common.ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
    decisions_dir = _common.ROOT / "config" / "agent" / "data_quality" / "decisions"

    if not ops_yaml_path.exists():
        print("  ops.yaml not found -- skipping.")
        return

    try:
        ops_data = _yaml.safe_load(ops_yaml_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError) as exc:
        print(f"  WARN: could not parse ops.yaml: {exc}")
        return

    manifests: dict[str, dict] = {}
    if decisions_dir.exists():
        for mf in decisions_dir.glob("*.yaml"):
            try:
                manifest = _yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
                table = manifest.get("table")
                if table:
                    manifests[table] = manifest
            except (OSError, _yaml.YAMLError):
                pass

    _ALLOWED_STATES = {"READY_NOW", "write_fix_deployed", "GRADUATED", "NEEDS_TEMPORAL_GATE"}
    errors: list[str] = []

    for table_name, table_def in ops_data.get("tables", {}).items():
        manifest_fields = manifests.get(table_name, {}).get("fields", {})
        for col_name, col_def in table_def.get("columns", {}).items():
            if not isinstance(col_def, dict):
                continue
            for test_entry in col_def.get("tests", []):
                if not isinstance(test_entry, dict):
                    continue
                for test_name, params in test_entry.items():
                    if not isinstance(params, dict) or not params.get("enforced"):
                        continue
                    state = manifest_fields.get(col_name, {}).get("enforcement_ready", "")
                    if state not in _ALLOWED_STATES:
                        errors.append(
                            f"{table_name}.{col_name} ({test_name}) is enforced: true "
                            f"but manifest shows enforcement_ready: {state!r} "
                            f"(allowed: {sorted(_ALLOWED_STATES)}). "
                            f"Update manifest before promoting enforcement."
                        )

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        failed.append("DQ manifest gate")
    else:
        print("  DQ manifest gate: all enforced checks have allowed enforcement_ready states.")
