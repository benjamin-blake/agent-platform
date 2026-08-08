"""Shared origin/main decision-number baseline reader (PLAN-decision-entry-flow-governance,
Decision 153 fast-tier budget).

Single git-read primitive for the two --pre consumers that need "which decision numbers exist
at origin/main" -- validate_decision_entry_conformance (new-vs-baseline routing) and
validate_decisions_size (the per-entry cap's new-entry classification). Memoized per root so a
single --pre run pays for exactly one `git show` per file, not one per consumer.

Reachability delegates to scripts.checks._common.origin_main_reachable -- never a private
duplicate (Decision 134 clause 3 shared-parser mandate; this module supersedes the former
private _origin_main_reachable in validate_decision_entry_conformance.py, deleted rather than
relocated).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from scripts.checks import _common
from scripts.decisions_md import iter_decision_headings

_DECISIONS_REL_PATHS = ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md")

# Shared injection-seam type for every --pre consumer's baseline_reader parameter (mirrors the
# vp_replay / graduation_completeness precedents) -- defined once here so
# validate_decision_entry_conformance and validate_decisions_size import the identical alias
# instead of each declaring their own.
BaselineReaderFn = Callable[[Path], Optional[set[int]]]

_cache: dict[Path, Optional[set[int]]] = {}


def baseline_decision_numbers(root: Path) -> Optional[set[int]]:
    """Decision numbers present at origin/main, via the shared '#{2,3}' grammar.

    Returns None (advisory-skip sentinel) when origin/main cannot be resolved at all -- a
    detached/shallow clone, a throwaway test repo with no remote, or plain unreachability.
    Memoized per root: a second call with the same root returns the cached result without a
    further git invocation.
    """
    if root in _cache:
        return _cache[root]
    if not _common.origin_main_reachable(root):
        _cache[root] = None
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
    _cache[root] = numbers
    return numbers
