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
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry

_DECISIONS_LIVE_MAX_H2 = 120
_DECISIONS_COMBINED_MAX_BYTES = 700_000

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
            f"the {live_max_h2}-header ceiling (Decision 134) -- relief valves: {_RELIEF_VALVES}"
        )
    if combined_bytes > combined_max_bytes:
        issues.append(
            f"  FAIL: docs/DECISIONS.md + docs/DECISIONS_ARCHIVE.md combined are {combined_bytes} "
            f"bytes, exceeding the {combined_max_bytes}-byte combined ceiling (Decision 134) -- "
            f"relief valves: {_RELIEF_VALVES}"
        )
    return issues


@registry.register("validate_decisions_size", owner="platform")
def validate_decisions_size(failed: list[str]) -> None:
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
    """
    print("\n=== DECISIONS size governance ===")

    live_path = _common.ROOT / "docs" / "DECISIONS.md"
    archive_path = _common.ROOT / "docs" / "DECISIONS_ARCHIVE.md"

    if not live_path.exists():
        print(f"  FAIL: {live_path.relative_to(_common.ROOT)} not found")
        failed.append("DECISIONS size governance")
        return
    if not archive_path.exists():
        print(f"  FAIL: {archive_path.relative_to(_common.ROOT)} not found")
        failed.append("DECISIONS size governance")
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
