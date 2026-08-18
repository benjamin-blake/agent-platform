"""DECISIONS.md / DECISIONS_ARCHIVE.md size governance (Decision 134; Decision-114 parity;
live-byte ceiling RETIRED by PLAN-decision-scout-bounded-retrieval, per Decision 145's own
reversal conditions -- the decision-scout gate no longer reads the live file wholesale, so the
ceiling that guard existed to size no longer has a referent).

Ratifies a conscious ceiling + deterministic guard for the decision log, mirroring
scripts/checks/roadmap/validate_platform_roadmap.py's _roadmap_size_issues() precedent
(Decision 114). Two ceilings survive the retirement: a live '## Decision' header count (the
decision-scout gate's `M`, Decision 134) and a live+archive combined byte ceiling, which now
backstops docs/DECISIONS.md's size on its own (Decision 151 consequence). Both are cheap,
structural, and independent of how the decision-scout gate reads the corpus.

PLAN-decision-entry-flow-governance / Decision 167 adds a third ceiling: a forward-only per-NEW-entry
authoring size norm (docs/contracts/decision-entry.yaml size_governance.per_entry_size_norm,
rec-2934). Decision 167 clause 3 explicitly dated this as a WARN-tier pre-commitment, staged
behind migration step 3 (destination readiness) -- migration-step-3-grandfathering IS that
migration step, so this norm now HARD-FAILS: a new-in-diff entry over the cap appends to `failed`.
Historical entries are still never measured (forward-only, mirrors
validate_decision_entry_conformance's own new-vs-baseline scope). Since this check is registered
UNGATED in the --pre tier (unlike the glob-gated conformance check), the per-entry sub-check's own
(git-cost) baseline read is skipped whenever a non-default `root` is injected for testing --
production calls (the default root) always pay it, since the two stock ceilings below already
read both files on every --pre run regardless.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry
from scripts.checks.decisions._baseline import BaselineReaderFn, baseline_decision_numbers
from scripts.decisions_md import iter_decision_sections

_DECISIONS_LIVE_MAX_H2 = 132
_DECISIONS_COMBINED_MAX_BYTES = 780_000
_PER_ENTRY_CAP_BYTES = 6_144

_RELIEF_VALVES = (
    "compact superseded decision bodies to pointer stubs (Decision 149) -- archiving a live "
    "entry to docs/DECISIONS_ARCHIVE.md does NOT relieve the combined ceiling, since it only "
    "moves bytes between the two counted files; only compaction and a leaner per-entry "
    "authoring size norm actually reduce combined bytes"
)

_LIVE_H2_RE = re.compile(r"^## Decision \d+:", re.MULTILINE)


def _decisions_size_issues(
    live_text: str,
    archive_text: str,
    live_max_h2: int = _DECISIONS_LIVE_MAX_H2,
    combined_max_bytes: int = _DECISIONS_COMBINED_MAX_BYTES,
) -> list[str]:
    """Return a FAIL string per breached ceiling, or [] when live/archive are all within bound."""
    issues: list[str] = []

    live_bytes = len(live_text.encode("utf-8"))
    archive_bytes = len(archive_text.encode("utf-8"))
    combined_bytes = live_bytes + archive_bytes
    live_h2_count = len(_LIVE_H2_RE.findall(live_text))

    if live_h2_count > live_max_h2:
        issues.append(
            f"  FAIL: docs/DECISIONS.md has {live_h2_count} live '## Decision' headers, exceeding "
            f"the {live_max_h2}-header ceiling -- relief valves: {_RELIEF_VALVES}"
        )
    if combined_bytes > combined_max_bytes:
        issues.append(
            f"  FAIL: docs/DECISIONS.md + docs/DECISIONS_ARCHIVE.md combined are {combined_bytes} "
            f"bytes, exceeding the {combined_max_bytes}-byte combined ceiling -- "
            f"relief valves: {_RELIEF_VALVES}"
        )
    return issues


_PER_ENTRY_CAP_HARD_FAIL_CITATION = (
    'Decision 167 clause 3: "A new entry over 6,144 bytes ... triggers a named WARN from '
    "validate_decisions_size, never a --pre failure -- a DATED pre-commitment ... this clause "
    "explicitly disclaims that the lever is installed until migration step 3 (destination "
    'readiness) flips it to hard-fail." migration-step-3-grandfathering IS that migration step.'
)


def _new_entries_examined_count(root, baseline_numbers: set[int]) -> int:
    """Count of NEW (non-baseline) decision entries the per-entry cap sub-check evaluated --
    mirrors `_per_entry_cap_failures`'s own new-vs-baseline scope, for the Decision 170
    declaration on the fall-through exit path."""
    count = 0
    for rel in ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"):
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for m, _block in iter_decision_sections(content):
            if int(m.group(1)) not in baseline_numbers:
                count += 1
    return count


def _per_entry_cap_failures(root, baseline_numbers: set[int]) -> list[str]:
    """HARD-FAIL (Decision 167 clause 3's dated pre-commitment, fired by migration step 3) for
    each NEW entry (absent from baseline_numbers) over the per-entry authoring cap. Historical
    entries are still never measured -- forward-only, mirrors
    validate_decision_entry_conformance's own new-vs-baseline scope. Renamed from
    `_per_entry_cap_warnings` (WARN-tier): the old name is actively misleading once this appends
    to `failed` instead of only printing."""
    failures: list[str] = []
    for rel in ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"):
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for m, block in iter_decision_sections(content):
            n = int(m.group(1))
            if n in baseline_numbers:
                continue
            size = len(block.encode("utf-8"))
            if size > _PER_ENTRY_CAP_BYTES:
                failures.append(
                    f"  FAIL: Decision {n} ({rel}) is {size} bytes, exceeding the {_PER_ENTRY_CAP_BYTES}-byte "
                    f"per-entry authoring cap (docs/contracts/decision-entry.yaml "
                    f"size_governance.per_entry_size_norm) -- {_PER_ENTRY_CAP_HARD_FAIL_CITATION}"
                )
    return failures


@registry.register("validate_decisions_size", owner="platform")
def validate_decisions_size(
    failed: list[str],
    root=None,
    baseline_reader: BaselineReaderFn | None = None,
) -> None:
    """Enforce the two surviving Decision 134 size ceilings on docs/DECISIONS.md and
    docs/DECISIONS_ARCHIVE.md: the live '## Decision' header count and the live+archive combined
    byte count. The live-byte-only ceiling (Decision 145's stopgap raise to 500_000) is RETIRED
    (PLAN-decision-scout-bounded-retrieval) -- it existed solely to size the decision-scout
    gate's whole-live-file read, and that read no longer happens (bounded index triage plus
    targeted per-entry reads instead). The combined ceiling continues to bound the live file in
    practice (live <= combined_max_bytes - archive_bytes).

    Cheap stat + header count -- registered in BOTH the --pre and full validate tiers. On
    breach, the failure message names the relief valves that actually reduce combined bytes
    (compaction to pointer stubs per Decision 149; a per-entry authoring size norm) so the guard
    is actionable, not just a stop sign.

    root / baseline_reader are test injection seams (mirrors validate_decision_entry_conformance)
    for the hard-fail per-entry cap sub-check below (Decision 167 clause 3, fired by migration
    step 3). A non-default root always exercises that sub-check (deterministic for tests); the
    default (production) root skips it whenever this
    check's own root equals _common.ROOT AND neither DECISIONS file changed in this diff, since
    this check runs UNGATED on every --pre invocation and the git baseline read is not free.

    Composes exactly ONE terminal Decision 170 declaration on each of its five reachable exit
    paths: a missing live or archive file `skipped()`s (could not examine); the cost-gated
    early return `examined(0, ...)`s (definitively zero new entries to check, not an unmet
    precondition); an unreachable diff base for the per-entry cap `skipped()`s; the
    fall-through `examined(N, ...)`s the new entries actually checked against the cap.
    """
    print("\n=== DECISIONS size governance ===")

    using_default_root = root is None
    root = root if root is not None else _common.ROOT
    baseline_reader = baseline_reader or baseline_decision_numbers

    live_path = root / "docs" / "DECISIONS.md"
    archive_path = root / "docs" / "DECISIONS_ARCHIVE.md"

    if not live_path.exists():
        print("  FAIL: docs/DECISIONS.md not found")
        failed.append("DECISIONS size governance")
        registry.skipped("docs/DECISIONS.md not found")
        return
    if not archive_path.exists():
        print("  FAIL: docs/DECISIONS_ARCHIVE.md not found")
        failed.append("DECISIONS size governance")
        registry.skipped("docs/DECISIONS_ARCHIVE.md not found")
        return

    live_text = live_path.read_text(encoding="utf-8")
    archive_text = archive_path.read_text(encoding="utf-8")

    issues = _decisions_size_issues(live_text, archive_text)

    if issues:
        for msg in issues:
            print(msg)
        failed.append("DECISIONS size governance")
    else:
        print("  PASS: DECISIONS.md / DECISIONS_ARCHIVE.md size within ceiling.")

    if using_default_root and not (set(_common.get_changed_files(root)) & {"docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"}):
        registry.examined(0, unit="new_decision_entries")
        return

    baseline_numbers = baseline_reader(root)
    if baseline_numbers is None:
        print("  (per-entry cap: SKIP, origin/main unreachable.)")
        registry.skipped("origin/main unreachable")
        return
    per_entry_failures = _per_entry_cap_failures(root, baseline_numbers)
    for failure in per_entry_failures:
        print(failure)
    if per_entry_failures:
        failed.append("DECISIONS size governance")
    registry.examined(_new_entries_examined_count(root, baseline_numbers), unit="new_decision_entries")
