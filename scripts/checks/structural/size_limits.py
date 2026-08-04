"""Structural-size limit gate (SGE-01/SGE-02/SGE-04, Decision 166).

Walks scripts.checks.structural._classify.iter_measured_files(); for each governed file,
compares effective lines against its `budgets:` roster entry (else its class row's
`limit`), and its longest line against its `long_line_budgets:` roster entry (else its
class row's `max_line_chars`). Registered in BOTH presubmit tiers, unscoped (no
pre_globs) -- measured whole-tree cost is ~0.1s against Decision 73's 300s fast-tier
budget, so pre_globs machinery would cost more complexity than it saves (the
validate_sloc_limits precedent).
"""

from __future__ import annotations

from scripts.checks import _common, registry
from scripts.checks.structural._classify import effective_lines, iter_measured_files, load_registry, longest_line


@registry.register("validate_structural_size_limits", owner="platform")
def validate_structural_size_limits(failed: list[str]) -> None:
    """Enforce the structural-size class engine (Decision 166): per-class effective-line
    limit plus the max-line-character companion, over every governed non-Python class."""
    print("\n=== Structural-size limits (Decision 166) ===")
    reg = load_registry()
    classes_by_slug = {row["slug"]: row for row in reg.get("classes") or []}
    budgets: dict[str, int] = reg.get("budgets") or {}
    long_line_budgets: dict[str, int] = reg.get("long_line_budgets") or {}

    errors: list[str] = []
    for rel, slug in iter_measured_files():
        text = (_common.ROOT / rel).read_text(encoding="utf-8", errors="replace")
        class_row = classes_by_slug[slug]
        relief_valves = class_row.get("relief_valve", "")

        eff = effective_lines(text)
        limit = budgets.get(rel, class_row["limit"])
        if eff > limit:
            errors.append(
                f"{rel}: {eff} effective lines exceeds limit {limit} (class: {slug}). Relief valves: {relief_valves}"
            )

        longest = longest_line(text)
        char_limit = long_line_budgets.get(rel, class_row["max_line_chars"])
        if longest > char_limit:
            errors.append(
                f"{rel}: longest line {longest} chars exceeds limit {char_limit} (class: {slug}). "
                f"Relief valves: {relief_valves}"
            )

    if errors:
        print("Structural-size violations:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Structural-size limits (Decision 166)")
    else:
        print("All governed files within structural-size budgets.")
