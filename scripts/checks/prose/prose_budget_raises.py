"""Prose budget-raise guardrail: Decision 128's raise-marker mechanism, applied to
config/prose_budgets.yaml (self-contained mirror of
scripts/checks/sloc/validate_sloc_budget_raises.py; upgraded to authorization by the
Decision 165 marker-guard consolidation).

An increase to any config/prose_budgets.yaml entry, or a brand-new registration, is a deliberate
trade against the ambient-context budget and must be loud and Decision-cited, not a frictionless
one-line YAML edit. This check diffs the registry against origin/main and retroactively re-scans
every currently-committed marker; both shapes FAIL unless the changed/marked line carries an
inline `# raise-approved: dec-NNN <reason>` marker naming a real `## Decision NNN:` header whose
body actually authorizes the entry's key -- citing a Decision that merely exists is no longer
sufficient.

Ratchet-down direction (decreases, removals) always passes -- this check only gates the upward
direction. Keys are scanned via a flattened, indentation-blind line scan regardless of nesting
depth under the S1/S2/S4/S8 group headers -- budget keys are globally unique across surface
groups (Decision 127 paths and the single S1 aggregate key never collide), so this is lossless.

Cites Decision 128 ONLY for this raise-marker mechanism, never for its SLOC-specific
decompose-into-a-facade-package relief valve, which is wrong for ambient prose (Decision 114/110
anti-fragmentation -- splitting a CLAUDE.md/SKILL.md into @-imported fragments does not shrink the
ambient load an agent must read; it just spreads the same bytes across more files).

Delegates its diff/authorization mechanics to scripts.checks._marker_guard (shared across all
five raise-marker guards); this module owns only the registry's own RegistrySpec binding, plus
its distinct relief-valve text.
"""

from __future__ import annotations

from typing import Callable, Optional

from scripts.checks import _marker_guard, registry

_BUDGETS_REL_PATH = "config/prose_budgets.yaml"

# Deliberately never names "split" / "decompose" -- see module docstring.
_RELIEF_VALVE_TEXT = (
    "Relief valves: relocate the content to docs/PROJECT_CONTEXT.md (L2) or a "
    "docs/contracts/*.yaml contract (Decision 86); defer the detail to an uncapped auxiliary "
    "file this surface points at instead of inlining it; or add a loud, Decision-cited "
    "`# raise-approved: dec-NNN <reason>` marker on the entry line."
)

_SPEC = _marker_guard.RegistrySpec(
    rel_path=_BUDGETS_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_flat_extractor("raise-approved", value_type=int),
    gates_new_entry=lambda _value: True,
    label="Prose budget-raise guardrail (Decision 128 marker mechanism)",
    relief_text=_RELIEF_VALVE_TEXT,
)


@registry.register("validate_prose_budget_raises", owner="platform")
def validate_prose_budget_raises(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/prose_budgets.yaml increase, new registration, or a
    currently-committed marker that no longer authorizes its entry."""
    print(f"\n=== {_SPEC.label} ===")
    violations = _marker_guard.check_diff(_SPEC, base_reader=base_reader) + _marker_guard.check_present_markers(_SPEC)

    if violations:
        print("Prose budget-raise violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append(_SPEC.label)
    else:
        print("No unauthorized prose budget raises.")
