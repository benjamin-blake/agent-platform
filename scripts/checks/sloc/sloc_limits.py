"""Per-file SLOC budget ratchet (Decision 43/102)."""

from __future__ import annotations

from scripts.checks import _common, registry
from scripts.checks.sloc._shared import _SLOC_EXCLUDE_DIRS, _SLOC_LIMIT, _WAIVER_PATTERN


def _load_sloc_budgets() -> dict[str, int]:
    """Load config/sloc_budgets.yaml; return {} if absent or empty."""
    import yaml as _yaml  # noqa: PLC0415

    budget_path = _common.ROOT / "config" / "sloc_budgets.yaml"
    if not budget_path.exists():
        return {}
    data = _yaml.safe_load(budget_path.read_text(encoding="utf-8")) or {}
    return {k: int(v) for k, v in (data.get("budgets") or {}).items()}


def _update_sloc_budgets() -> None:
    """Regenerate config/sloc_budgets.yaml with a downward-only ratchet.

    - Lowers any registered budget whose file shrank (never below its current SLOC).
    - Drops registered files now <=500 SLOC or deleted.
    - Never raises an existing budget.
    - Does NOT seed newly-oversized (currently-unregistered) files (Decision 128 / B2 --
      forces a deliberate `# raise-approved: dec-NNN` registration or a decompose instead of a
      frictionless one-command auto-seed; validate_sloc_limits fails such a file until then).
    """
    import yaml as _yaml  # noqa: PLC0415

    existing = _load_sloc_budgets()
    current_sloc: dict[str, int] = {}

    for search_dir in (_common.ROOT / "scripts", _common.ROOT / "src"):
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file.name == "__init__.py":
                continue
            if any(part in _SLOC_EXCLUDE_DIRS for part in py_file.parts):
                continue
            content = py_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            sloc = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")])
            rel = str(py_file.relative_to(_common.ROOT)).replace("\\", "/")
            current_sloc[rel] = sloc

    new_budgets: dict[str, int] = {}
    for rel, budget in existing.items():
        sloc = current_sloc.get(rel)
        if sloc is None or sloc <= _SLOC_LIMIT:
            continue  # deleted, or shrank to <=500 -- drop from the registry
        new_budgets[rel] = min(sloc, budget)

    lowered = sorted(k for k in new_budgets if new_budgets[k] < existing[k])
    dropped = sorted(k for k in existing if k not in new_budgets)

    header_lines = [
        "# SLOC budget registry (Decision 102, amends Decision 43; raise gate per Decision 128).",
        "# Each entry pins a scripts/ or src/ Python file to its SLOC budget.",
        "# Budgets ratchet DOWN only: run `validate --update-sloc-budgets` to lower.",
        "# Raising a budget (or registering a NEW >500-SLOC file) requires a manual, reviewable",
        "# edit carrying an inline `# raise-approved: dec-NNN <reason>` marker -- enforced by",
        "# validate_sloc_budget_raises in the --pre tier. --update-sloc-budgets never seeds a",
        "# newly-oversized file; decompose it, or register it deliberately with a marker.",
        "# Forward-compatible with the Decision 80 validate.py decomposition:",
        "# keys are re-pointed at new module paths at decomposition time.",
    ]
    header = "\n".join(header_lines) + "\n"

    yaml_body = _yaml.safe_dump({"budgets": new_budgets}, default_flow_style=False, sort_keys=True)

    budget_path = _common.ROOT / "config" / "sloc_budgets.yaml"
    budget_path.write_text(header + yaml_body, encoding="utf-8")

    print(f"SLOC budgets updated: {len(lowered)} lowered, {len(dropped)} dropped (no auto-seed; Decision 128).")
    if lowered:
        for k in lowered:
            print(f"  v {k}: {existing[k]} -> {new_budgets[k]}")
    if dropped:
        for k in dropped:
            print(f"  - {k} (now <={_SLOC_LIMIT} or deleted)")


@registry.register("validate_sloc_limits", owner="platform")
def validate_sloc_limits(failed: list[str]) -> None:
    """Enforce Decision 43/102: per-file SLOC budget ratchet for scripts/ and src/."""
    print("\n=== SLOC limits (Decision 43) ===")
    budgets = _load_sloc_budgets()
    errors: list[str] = []
    advisories: list[str] = []

    for search_dir in (_common.ROOT / "scripts", _common.ROOT / "src"):
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file.name == "__init__.py":
                continue
            if any(part in _SLOC_EXCLUDE_DIRS for part in py_file.parts):
                continue
            content = py_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            sloc = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")])
            header = "\n".join(lines[:10])
            has_waiver = bool(_WAIVER_PATTERN.search(header))
            rel = str(py_file.relative_to(_common.ROOT)).replace("\\", "/")

            if sloc <= _SLOC_LIMIT:
                if has_waiver:
                    advisories.append(
                        f"{rel}: stale SLOC waiver (<=500 SLOC); "
                        "the comment may still be needed for the CC gate -- verify before removing."
                    )
                continue

            if rel in budgets:
                budget = budgets[rel]
                if sloc > budget:
                    errors.append(
                        f"{rel}: {sloc} SLOC exceeds budget {budget}. "
                        f"Reduce, or (with justification) raise the budget in config/sloc_budgets.yaml."
                    )
                elif sloc < budget:
                    advisories.append(
                        f"{rel}: {sloc} SLOC below budget {budget}; run `validate --update-sloc-budgets` to ratchet down."
                    )
            else:
                errors.append(
                    f"{rel}: {sloc} SLOC exceeds limit {_SLOC_LIMIT} and is not registered in config/sloc_budgets.yaml. "
                    f"Reduce below {_SLOC_LIMIT}, or register via `validate --update-sloc-budgets`. "
                    f"A bare '# complexity-waiver: decision-43' no longer authorises unbounded SLOC."
                )

    if advisories:
        print("SLOC advisories (non-blocking):")
        for a in advisories:
            print(f"  ~ {a}")

    if errors:
        print("SLOC limit violations:")
        for e in errors:
            print(f"  - {e}")
        failed.append("SLOC limits (Decision 43)")
    else:
        print("All files within SLOC budgets.")
