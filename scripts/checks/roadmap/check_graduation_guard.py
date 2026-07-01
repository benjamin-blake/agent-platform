"""Enforced graduation guard for data-quality YAML (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


def _extract_enforced_map(yaml_content: str) -> dict[tuple[str, str | None, str], bool]:
    """Extract {(table, col, test): enforced} from YAML content string for the graduation guard."""
    import yaml as _yaml

    try:
        spec = _yaml.safe_load(yaml_content) or {}
    except Exception:
        return {}
    result: dict[tuple[str, str | None, str], bool] = {}
    for table_name, table_def in (spec.get("tables") or {}).items():
        if not isinstance(table_def, dict):
            continue
        if "row_count" in table_def:
            rc = table_def["row_count"]
            if isinstance(rc, dict):
                result[(table_name, None, "row_count")] = bool(rc.get("enforced", True))
        if "recency" in table_def:
            rec = table_def["recency"]
            if isinstance(rec, dict):
                col = rec.get("column", "")
                result[(table_name, col, "recency")] = bool(rec.get("enforced", True))
        for col_name, col_def in (table_def.get("columns") or {}).items():
            if not isinstance(col_def, dict):
                continue
            for test in col_def.get("tests") or []:
                if isinstance(test, str):
                    result[(table_name, col_name, test)] = True
                elif isinstance(test, dict):
                    test_type = next(iter(test))
                    params = test[test_type]
                    enforced = bool(params.get("enforced", True)) if isinstance(params, dict) else True
                    result[(table_name, col_name, test_type)] = enforced
    return result


@registry.register("_check_graduation_guard", owner="platform")
def _check_graduation_guard(failed: list[str]) -> None:
    """Block enforced:false->true flips when the check's verdict in dq-latest.json is not PASS.

    Note: --pre skips the enforced graduation guard.
    """
    import json as _json

    print("\n=== Enforced graduation guard ===")
    print("  Note: --pre skips the enforced graduation guard.")

    diff_result = _common.run(
        ["git", "diff", "HEAD", "--name-only", "--", "config/agent/data_quality/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    changed_files = [f.strip() for f in diff_result.stdout.splitlines() if f.strip().endswith(".yaml")]
    if not changed_files:
        print("  No DQ YAML changes detected -- guard has nothing to check.")
        return

    dq_file = _common.ROOT / "logs" / "debug" / "dq-latest.json"
    if not dq_file.exists():
        print("  WARN: dq-latest.json missing -- cannot verify enforced flips (warn only).")
        return

    try:
        data = _json.loads(dq_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        print("  WARN: dq-latest.json unreadable -- cannot verify enforced flips (warn only).")
        return

    checks_list = data.get("checks")
    if not checks_list:
        print("  WARN: dq-latest.json has no 'checks' array -- cannot verify enforced flips (warn only).")
        return

    verdict_lookup: dict[tuple[str, str | None, str], str] = {}
    for entry in checks_list:
        key = (entry.get("table"), entry.get("column"), entry.get("test"))
        verdict_lookup[key] = entry.get("verdict", "UNKNOWN")

    for rel_path in changed_files:
        show_result = _common.run(
            ["git", "show", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=_common.ROOT,
        )
        old_map = _extract_enforced_map(show_result.stdout) if show_result.returncode == 0 else {}
        new_file = _common.ROOT / rel_path
        if not new_file.exists():
            continue
        new_map = _extract_enforced_map(new_file.read_text(encoding="utf-8"))

        for key, new_enforced in new_map.items():
            if not new_enforced:
                continue
            old_enforced = old_map.get(key, False)
            if old_enforced:
                continue

            verdict = verdict_lookup.get(key)
            table, col, test = key
            col_str = f".{col}" if col else ""
            label = f"{table}{col_str}.{test}"

            if verdict is None:
                print(f"  WARN: {label} flipped to enforced:true but not found in dq-latest.json checks.")
                continue
            if verdict in {"SKIP", "UNAVAILABLE"}:
                print(f"  WARN: {label} has verdict={verdict} (inconclusive) -- flip not blocked but unverified.")
                continue
            if verdict != "PASS":
                failed.append(
                    f"Graduation guard: {label} cannot be graduated to enforced:true "
                    f"(current verdict: {verdict}). Run data_quality_runner and verify PASS first."
                )
