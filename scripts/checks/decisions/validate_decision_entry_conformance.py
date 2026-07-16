"""Decision-entry authoring-grammar forward conformance check (DAF-03 / Decision 134 cl.3 /
PLAN-daf-authoring-grammar).

Enforces docs/contracts/decision-entry.yaml's canonical markers on GENUINELY-NEW decision
entries only -- a decision number absent from the origin/main baseline. Modified, amended, or
promoted historical entries (e.g. this same plan's own DECISIONS_ARCHIVE.md h3->h2 promote of
Decisions 52/53/54) are grandfathered: they carry only a "**Status:** Decided -- April 2026"
line with no separate "**Date:**" marker, and would self-fail this check if the historical band
were retro-enforced.

Baseline and current populations are both computed via the SAME shared grammar
(scripts.decisions_md.iter_decision_headings, the '#{2,3}' regex) so a header-level promote
(h3->h2) never manufactures a false "new" entry -- Decisions 52/53/54 are counted as
already-present at origin/main regardless of which heading level either snapshot used.

Required markers are read from docs/contracts/decision-entry.yaml at check time (never a
hardcoded copy) -- the contract is the single source of truth for the canonical marker set.

Advisory SKIP (never a failure) when origin/main is unreachable (mirrors the
validate_graduation_completeness precedent): the check cannot resolve new-vs-baseline without
it. The baseline_reader injection seam returns None for exactly this case, so the default
reader's own reachability check and a test's synthetic "unreachable" case share one code path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import yaml

from scripts.checks import _common, registry
from scripts.decisions_md import _DECISION_MARKER_BODY, iter_decision_headings

_CONTRACT_REL_PATH = "docs/contracts/decision-entry.yaml"
_DECISIONS_REL_PATHS = ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md")

BaselineReaderFn = Callable[[Path], Optional[set[int]]]


def _origin_main_reachable(root: Path) -> bool:
    result = _common.run(
        ["git", "rev-parse", "--verify", "-q", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    return result.returncode == 0


def _default_baseline_decision_numbers(root: Path) -> Optional[set[int]]:
    """Decision numbers present at origin/main, via the shared '#{2,3}' grammar.

    Returns None (advisory-skip sentinel) when origin/main cannot be resolved at all -- a
    detached/shallow clone, a throwaway test repo with no remote, or plain unreachability.
    """
    if not _origin_main_reachable(root):
        return None
    numbers: set[int] = set()
    for rel in _DECISIONS_REL_PATHS:
        result = _common.run(
            ["git", "show", f"origin/main:{rel}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=root,
        )
        if result.returncode != 0:
            continue  # file absent at origin/main (new file) -- not an unreachable-baseline case
        numbers.update(int(m.group(1)) for m in iter_decision_headings(result.stdout))
    return numbers


def _current_decision_entries(root: Path) -> dict[int, str]:
    """decision number -> heading-inclusive raw block, from the CURRENT working tree.

    First-wins on a duplicate number across the two files, mirroring
    scripts.decisions_md.parse_decisions_md's dedup rule.
    """
    entries: dict[int, str] = {}
    for rel in _DECISIONS_REL_PATHS:
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        headings = list(iter_decision_headings(content))
        for i, m in enumerate(headings):
            n = int(m.group(1))
            if n in entries:
                continue
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            entries[n] = content[m.start() : end]
    return entries


def _load_required_markers(root: Path, failed: list[str]) -> Optional[list[str]]:
    contract_path = root / _CONTRACT_REL_PATH
    if not contract_path.exists():
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} not found")
        return None
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        failed.append(f"Decision-entry conformance: could not parse {_CONTRACT_REL_PATH}: {exc}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("required_markers"), list):
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} has no required_markers list")
        return None
    return [str(m) for m in data["required_markers"]]


def _missing_markers(block: str, required_markers: list[str]) -> list[str]:
    """Return the subset of required_markers absent from block.

    The "Decision" marker tolerates the decorated form (e.g. "**Decision (four invariants):**")
    per decision-entry.yaml's decision_marker_tolerance -- reuses decisions_md's own
    _DECISION_MARKER_BODY pattern so this check never diverges from the shared parser's notion
    of what counts as a Decision marker. Every other required marker uses its exact spelling.
    """
    missing: list[str] = []
    for marker in required_markers:
        pattern = rf"\*\*{_DECISION_MARKER_BODY}:\*\*" if marker == "Decision" else rf"\*\*{re.escape(marker)}:\*\*"
        if not re.search(pattern, block):
            missing.append(marker)
    return missing


@registry.register("validate_decision_entry_conformance", owner="platform")
def validate_decision_entry_conformance(
    failed: list[str],
    root: Path | None = None,
    baseline_reader: BaselineReaderFn | None = None,
) -> None:
    """Enforce the decision-entry authoring grammar on new-in-diff decision numbers only.

    root / baseline_reader are test/dogfood injection seams (mirrors the vp_replay /
    graduation_completeness precedents) -- default to _common.ROOT and a real
    `git show origin/main:...` reader respectively.
    """
    print("\n=== Decision-entry authoring-grammar conformance (DAF-03) ===")
    root = root if root is not None else _common.ROOT
    baseline_reader = baseline_reader or _default_baseline_decision_numbers

    baseline_numbers = baseline_reader(root)
    if baseline_numbers is None:
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        return

    required_markers = _load_required_markers(root, failed)
    if required_markers is None:
        return

    current_entries = _current_decision_entries(root)
    new_numbers = sorted(set(current_entries) - baseline_numbers)

    if not new_numbers:
        print("  PASS: no genuinely-new decision entries in this diff (origin/main baseline unchanged).")
        return

    issues: list[str] = []
    for n in new_numbers:
        missing = _missing_markers(current_entries[n], required_markers)
        if missing:
            issues.append(
                f"  FAIL: Decision {n} is new (absent from the origin/main baseline) but missing marker(s): {missing}"
            )

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Decision-entry conformance")
    else:
        plural = "y" if len(new_numbers) == 1 else "ies"
        print(f"  PASS: {len(new_numbers)} new decision entr{plural} conform to the canonical grammar ({new_numbers}).")
