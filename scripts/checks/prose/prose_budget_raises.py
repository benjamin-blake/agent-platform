"""Prose budget-raise guardrail: Decision 128's raise-marker mechanism, applied to
config/prose_budgets.yaml (self-contained mirror of
scripts/checks/sloc/validate_sloc_budget_raises.py).

An increase to any config/prose_budgets.yaml entry, or a brand-new registration, is a deliberate
trade against the ambient-context budget and must be loud and Decision-cited, not a frictionless
one-line YAML edit. This check diffs the registry against origin/main and FAILS the PR on any
such raise unless the changed line carries an inline `# raise-approved: dec-NNN <reason>` marker
naming a real `## Decision NNN:` header in docs/DECISIONS.md.

Ratchet-down direction (decreases, removals) always passes -- this check only gates the upward
direction. It parses the raw YAML text rather than yaml.safe_load (which drops comments and would
lose the inline marker), scanning every 'key: N  # comment' line regardless of its nesting depth
under the S1/S2/S4/S8 group headers -- budget keys are globally unique across surface groups
(Decision 127 paths and the single S1 aggregate key never collide), so this flattened,
indentation-blind line scan is lossless.

Cites Decision 128 ONLY for this raise-marker mechanism, never for its SLOC-specific
decompose-into-a-facade-package relief valve, which is wrong for ambient prose (Decision 114/110
anti-fragmentation -- splitting a CLAUDE.md/SKILL.md into @-imported fragments does not shrink the
ambient load an agent must read; it just spreads the same bytes across more files).

The base-content reader is injectable for tests. When origin/main is unreachable, this check
SKIPs (non-failing) rather than failing -- advisory locally, authoritative in CI, mirroring
validate_sloc_budget_raises / validate_vp_replay.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from scripts.checks import _common, registry

_BUDGETS_REL_PATH = "config/prose_budgets.yaml"
_DECISIONS_REL_PATH = "docs/DECISIONS.md"

_BUDGET_LINE_RE = re.compile(r"^\s*([\w./_-]+):\s*(\d+)\s*(#.*)?$")
_RAISE_MARKER_RE = re.compile(r"#\s*raise-approved:\s*dec-(\d+)")
_DECISION_HEADER_RE = re.compile(r"^## Decision (\d+):", re.MULTILINE)

# Deliberately never names "split" / "decompose" -- see module docstring.
_RELIEF_VALVE_TEXT = (
    "Relief valves: relocate the content to docs/PROJECT_CONTEXT.md (L2) or a "
    "docs/contracts/*.yaml contract (Decision 86); defer the detail to an uncapped auxiliary "
    "file this surface points at instead of inlining it; or add a loud, Decision-cited "
    "`# raise-approved: dec-NNN <reason>` marker on the entry line."
)


def _default_base_reader(rel_path: str) -> Optional[str]:
    """Read a file's content at origin/main; return None if the ref/path is unreachable."""
    result = _common.run(
        ["git", "show", f"origin/main:{rel_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_budget_lines(text: str) -> dict[str, tuple[int, Optional[str]]]:
    """Parse raw 'path: N  # comment' lines (any indentation) into {path: (value, marker)}.

    Comment-only and blank lines are skipped. Nesting under the S1/S2/S4/S8 group headers is
    irrelevant to this line-level scan -- see the module docstring for why the flattened parse
    is lossless.
    """
    budgets: dict[str, tuple[int, Optional[str]]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _BUDGET_LINE_RE.match(stripped)
        if not match:
            continue
        path, value_str, comment = match.group(1), match.group(2), match.group(3)
        marker: Optional[str] = None
        if comment:
            marker_match = _RAISE_MARKER_RE.search(comment)
            if marker_match:
                marker = f"dec-{marker_match.group(1)}"
        budgets[path] = (int(value_str), marker)
    return budgets


def _decision_header_exists(dec_id: str, decisions_text: str) -> bool:
    number = dec_id.removeprefix("dec-")
    return any(number == n for n in _DECISION_HEADER_RE.findall(decisions_text))


@registry.register("validate_prose_budget_raises", owner="platform")
def validate_prose_budget_raises(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/prose_budgets.yaml increase or new registration."""
    print("\n=== Prose budget-raise guardrail (Decision 128 marker mechanism) ===")
    reader = base_reader or _default_base_reader

    current_path = _common.ROOT / _BUDGETS_REL_PATH
    if not current_path.exists():
        print(f"  {_BUDGETS_REL_PATH} not found -- nothing to check.")
        return

    base_text = reader(_BUDGETS_REL_PATH)
    if base_text is None:
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        return

    current_text = current_path.read_text(encoding="utf-8")
    base_budgets = _parse_budget_lines(base_text)
    current_budgets = _parse_budget_lines(current_text)

    decisions_path = _common.ROOT / _DECISIONS_REL_PATH
    decisions_text = decisions_path.read_text(encoding="utf-8") if decisions_path.exists() else ""

    violations: list[str] = []
    for path, (new_value, marker) in sorted(current_budgets.items()):
        base_entry = base_budgets.get(path)
        is_new = base_entry is None
        is_increase = base_entry is not None and new_value > base_entry[0]
        if not (is_new or is_increase):
            continue

        if marker is None:
            kind = "new registration" if is_new else f"increase {base_entry[0]} -> {new_value}"
            violations.append(
                f"{path}: unauthorized {kind} with no `# raise-approved: dec-NNN` marker on the "
                f"entry line. {_RELIEF_VALVE_TEXT}"
            )
            continue

        if not _decision_header_exists(marker, decisions_text):
            violations.append(
                f"{path}: raise-approved marker cites {marker}, but no `## Decision N:` header "
                f"for it exists. {_RELIEF_VALVE_TEXT}"
            )

    if violations:
        print("Prose budget-raise violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Prose budget-raise guardrail (Decision 128 marker mechanism)")
    else:
        print("No unauthorized prose budget raises.")
