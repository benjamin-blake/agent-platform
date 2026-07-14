"""SLOC budget-raise guardrail (Decision 128, amends Decision 102).

A `config/sloc_budgets.yaml` entry increase, or a brand-new >500-SLOC registration, is a
deliberate trade against model-portability (large files degrade comprehension on lower-tier
models) and must be loud and Decision-cited, not a frictionless one-line YAML edit. This check
diffs the registry against origin/main and FAILS the PR on any such raise unless the changed
line carries an inline `# raise-approved: dec-NNN <reason>` marker naming a real
`## Decision NNN:` header in docs/DECISIONS.md.

Ratchet-down direction (decreases, removals) always passes -- this check only gates the upward
direction. It parses the raw YAML text rather than yaml.safe_load, because safe_load drops
comments and the raise-approved marker lives in an inline comment on the budget entry line
(`path: N  # raise-approved: dec-NNN <reason>`); markers are not required to persist after
merge (the raise is durably recorded in git history + the cited Decision instead).

The base-content reader is injectable for tests. When origin/main is unreachable, this check
SKIPs (non-failing) rather than failing -- advisory locally, authoritative in CI, mirroring
validate_vp_replay.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from scripts.checks import _common, registry

_BUDGETS_REL_PATH = "config/sloc_budgets.yaml"
_DECISIONS_REL_PATH = "docs/DECISIONS.md"

_BUDGET_LINE_RE = re.compile(r"^\s*([\w./_-]+):\s*(\d+)\s*(#.*)?$")
_RAISE_MARKER_RE = re.compile(r"#\s*raise-approved:\s*dec-(\d+)")
_DECISION_HEADER_RE = re.compile(r"^## Decision (\d+):", re.MULTILINE)


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
    """Parse raw 'path: N  # comment' lines into {path: (value, raise_approved_dec_id | None)}.

    Comment-only and blank lines are skipped (this is a raw-text scan, not a YAML parse -- the
    budgets mapping is flat and every real entry is a single 'path: N' line).
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


@registry.register("validate_sloc_budget_raises", owner="platform")
def validate_sloc_budget_raises(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/sloc_budgets.yaml increase or new >500 registration."""
    print("\n=== SLOC budget-raise guardrail (Decision 128) ===")
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
            kind = "new >500 registration" if is_new else f"increase {base_entry[0]} -> {new_value}"
            violations.append(f"{path}: unauthorized {kind} with no `# raise-approved: dec-NNN` marker on the entry line.")
            continue

        if not _decision_header_exists(marker, decisions_text):
            violations.append(f"{path}: raise-approved marker cites {marker}, but no `## Decision N:` header for it exists.")

    if violations:
        print("SLOC budget-raise violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("SLOC budget-raise guardrail (Decision 128)")
    else:
        print("No unauthorized SLOC budget raises.")
