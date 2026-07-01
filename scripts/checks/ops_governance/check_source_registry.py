"""Source-registry CI guard: schedule.yaml agent names + ops_data_portal.py literals (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("check_source_registry", owner="platform")
def check_source_registry(failed: list[str]) -> None:
    """Verify that all agent names in schedule.yaml are registered canonical_ids.

    Also checks ops_data_portal.py for hardcoded source string literals and verifies
    each is registered. Wired into run_python_checks() -- runs on presubmit.
    """
    import yaml as _yaml

    print("\n=== Source registry CI guard ===")

    registry_path = _common.ROOT / "config" / "agent" / "data_quality" / "source_registry.yaml"
    if not registry_path.exists():
        print(f"  FAIL: {registry_path} not found -- create source_registry.yaml first")
        failed.append("Source registry CI guard")
        return

    registry_data = _yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    valid_ids: set[str] = {e["canonical_id"] for e in registry_data.get("entries", [])}

    violations: list[str] = []

    schedule_path = _common.ROOT / ".github" / "agents" / "schedule.yaml"
    if schedule_path.exists():
        schedule_data = _yaml.safe_load(schedule_path.read_text(encoding="utf-8"))
        for agent in schedule_data.get("agents", []):
            name = agent.get("name", "")
            if name and name not in valid_ids:
                violations.append(f"schedule.yaml agent name '{name}' not in source_registry.yaml")
    else:
        print(f"  WARNING: {schedule_path} not found -- skipping agent name check")

    portal_path = _common.ROOT / "scripts" / "ops_data_portal.py"
    if portal_path.exists():
        portal_source = portal_path.read_text(encoding="utf-8")
        import re as _re

        for match in _re.finditer(r'source\s*==\s*[\'"]([^\'"]+)[\'"]|"source"\s*:\s*"([^"]+)"', portal_source):
            literal = match.group(1) or match.group(2)
            if literal and not literal.startswith("{") and literal not in valid_ids:
                violations.append(f"ops_data_portal.py hardcoded source '{literal}' not in source_registry.yaml")

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
        failed.append("Source registry CI guard")
    else:
        print(f"  PASS: all agent names and hardcoded source values registered ({len(valid_ids)} entries)")
