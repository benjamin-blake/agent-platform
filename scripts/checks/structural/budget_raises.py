"""Structural-size budget-raise guardrail (Decision 166) -- the SIXTH CONSUMER of
scripts/checks/_marker_guard.py, never a sixth copy.

config/structural_size_budgets.yaml mixes an ordered `classes:` table (carrying scalar
keys like `limit`/`max_line_chars`) with two flat per-file rosters (`budgets:` and
`long_line_budgets:`), so this module declares TWO section-scoped RegistrySpecs over the
SAME rel_path -- THE CRITICAL SEAM: make_section_extractor anchors each spec on its own
top-level section and ends it at the next column-0 non-comment line, so neither
extraction ever captures a `classes:` block scalar as a budget entry (a flat extractor
would). Contains no local Decision-header regex, no local base reader, and no local
entry parser -- scripts.checks._marker_guard owns all of that.
"""

from __future__ import annotations

from typing import Callable, Optional

from scripts.checks import _marker_guard, registry

_REGISTRY_REL_PATH = "config/structural_size_budgets.yaml"

_BUDGET_SPEC = _marker_guard.RegistrySpec(
    rel_path=_REGISTRY_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_section_extractor("budgets", token="raise-approved", value_type=int),
    gates_new_entry=lambda _value: True,
    label="Structural-size budget-raise guardrail (Decision 166, budgets)",
)

_LONG_LINE_SPEC = _marker_guard.RegistrySpec(
    rel_path=_REGISTRY_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_section_extractor("long_line_budgets", token="raise-approved", value_type=int),
    gates_new_entry=lambda _value: True,
    label="Structural-size budget-raise guardrail (Decision 166, long_line_budgets)",
)


@registry.register("validate_structural_size_budget_raises", owner="platform")
def validate_structural_size_budget_raises(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/structural_size_budgets.yaml `budgets:` or
    `long_line_budgets:` increase, new >limit registration, or a currently-committed
    marker that no longer authorizes its entry -- over BOTH sections, each via its own
    section-scoped extractor."""
    print(f"\n=== {_BUDGET_SPEC.label} ===")
    violations = (
        _marker_guard.check_diff(_BUDGET_SPEC, base_reader=base_reader)
        + _marker_guard.check_present_markers(_BUDGET_SPEC)
        + _marker_guard.check_diff(_LONG_LINE_SPEC, base_reader=base_reader)
        + _marker_guard.check_present_markers(_LONG_LINE_SPEC)
    )

    if violations:
        print("Structural-size budget-raise violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append(_BUDGET_SPEC.label)
    else:
        print("No unauthorized structural-size budget raises.")
