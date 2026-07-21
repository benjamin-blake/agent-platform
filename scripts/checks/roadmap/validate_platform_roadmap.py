# complexity-waiver: decision-43
"""Platform roadmap schema validation (Decision 104)."""

from __future__ import annotations

import re
import subprocess
import sys

from scripts.checks import _common, registry

_40HEX_RE = re.compile(r"^[0-9a-f]{40}$")
_ROADMAP_MAX_LINES = 10_000  # Decision 114 (raised from KG.11's 2500)


def _roadmap_size_issues(text: str, ceiling: int = _ROADMAP_MAX_LINES) -> list[str]:
    """Return a one-item FAIL list if text exceeds ceiling lines, else []."""
    line_count = len(text.splitlines())
    if line_count > ceiling:
        return [
            f"  FAIL: docs/ROADMAP-PLATFORM.yaml is {line_count} lines, exceeding the {ceiling}-line ceiling (Decision 114)"
        ]
    return []


@registry.register("validate_platform_roadmap", owner="platform")
def validate_platform_roadmap(failed: list[str]) -> None:
    """Validate docs/ROADMAP-PLATFORM.yaml against the RoadmapDocument Pydantic schema.

    Rejects structural drift: duplicate ids, dangling depends_on, dependency cycles,
    unknown gate-rule helpers, invalid filed_via, unsupported document version.
    Added by T-1.5. Runs in both the --pre and full presubmit tiers (closes-criteria-integrity-guard).

    Extended by T-1.23: criteria-status integrity assertions.
      (i)  met criterion met_by resolves to a real docs/plans/PLAN-<slug>.yaml or a 40-hex sha.
      (ii) any tier_item touched in the git diff (vs origin/main) must have no bare-string criteria.
      (iii) every PLAN-*.yaml closes_criteria ref resolves to a real item:criterion in the roadmap.
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Platform roadmap schema validation ===")

    roadmap_path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path.relative_to(_common.ROOT)} not found")
        failed.append("Platform roadmap schema validation")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from pydantic import ValidationError  # noqa: PLC0415

        from scripts.roadmap.platform_roadmap import ExitCriterion, load  # noqa: PLC0415

        doc = load(roadmap_path)
        issues: list[str] = []
        issues += _roadmap_size_issues(roadmap_path.read_text(encoding="utf-8"))

        # (i) met criterion met_by resolves to a real plan file OR a 40-hex sha
        plans_root = _common.ROOT / "docs" / "plans"
        for item in doc.tier_items:
            for crit in item.exit_criteria:
                if not isinstance(crit, ExitCriterion):
                    continue
                if crit.status == "met" and crit.met_by:
                    plan_file = plans_root / f"PLAN-{crit.met_by}.yaml"
                    if not plan_file.exists() and not _40HEX_RE.match(crit.met_by):
                        issues.append(
                            f"  FAIL: tier_item '{item.id}' criterion '{crit.id}': "
                            f"met_by='{crit.met_by}' does not resolve to a real plan or 40-hex commit"
                        )

        # (ii) git-diff-touched tier_items must have fully-structured criteria (no bare strings)
        diff_result = subprocess.run(
            ["git", "diff", "origin/main", "--", str(roadmap_path.relative_to(_common.ROOT))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(_common.ROOT),
        )
        if diff_result.returncode == 0 and diff_result.stdout.strip():
            touched_ids: set[str] = set(re.findall(r"^[+-]\s+- id: (\S+)", diff_result.stdout, re.MULTILINE))
            if touched_ids:
                with roadmap_path.open(encoding="utf-8") as fh:
                    raw_doc = _yaml.safe_load(fh)
                for raw_item in raw_doc.get("tier_items", []):
                    if raw_item.get("id") in touched_ids:
                        for raw_crit in raw_item.get("exit_criteria", []):
                            if isinstance(raw_crit, str):
                                issues.append(
                                    f"  FAIL: tier_item '{raw_item['id']}' is touched in the git diff "
                                    f"but still has bare-string criteria -- convert to ExitCriterion objects"
                                )
                                break

        # (iii) every PLAN-*.yaml closes_criteria ref resolves to a real item:criterion
        item_criteria: dict[str, set[str]] = {}
        for item in doc.tier_items:
            item_criteria[item.id] = {c.id for c in item.exit_criteria if isinstance(c, ExitCriterion)}
        if plans_root.is_dir():
            for plan_file in sorted(plans_root.glob("PLAN-*.yaml")):
                try:
                    with plan_file.open(encoding="utf-8") as fh:
                        plan_data = _yaml.safe_load(fh)
                    if not isinstance(plan_data, dict):
                        continue
                    closes = plan_data.get("closes_criteria") or []
                    if not isinstance(closes, list):
                        continue
                    for ref in closes:
                        if not isinstance(ref, str) or ":" not in ref:
                            issues.append(
                                f"  FAIL: {plan_file.name}: closes_criteria entry {ref!r} "
                                f"is not in '<item-id>:<crit-id>' format"
                            )
                            continue
                        item_id, crit_id = ref.split(":", 1)
                        if item_id not in item_criteria:
                            issues.append(
                                f"  FAIL: {plan_file.name}: closes_criteria ref '{ref}' names unknown tier_item '{item_id}'"
                            )
                        elif crit_id not in item_criteria[item_id]:
                            issues.append(
                                f"  FAIL: {plan_file.name}: closes_criteria ref '{ref}' "
                                f"names unknown criterion '{crit_id}' on item '{item_id}'"
                            )
                except Exception as plan_exc:  # noqa: BLE001
                    issues.append(f"  FAIL: {plan_file.name}: could not parse for closes_criteria: {plan_exc}")

        if issues:
            for msg in issues:
                print(msg)
            failed.append("Platform roadmap criteria integrity")
        else:
            print("  PASS: platform roadmap schema validation passed.")
    except ImportError as exc:
        print(f"  ERROR: Could not import platform_roadmap: {exc}")
        failed.append("Platform roadmap schema validation")
    except ValidationError as exc:
        print(f"  FAIL: Pydantic validation error:\n{exc}")
        failed.append("Platform roadmap schema validation")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Platform roadmap schema validation")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Platform roadmap schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
