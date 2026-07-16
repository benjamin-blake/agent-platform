"""DECISIONS.md / DECISIONS_ARCHIVE.md size governance (Decision 133; Decision-114 parity).

Ratifies a conscious ceiling + deterministic guard for the decision log, mirroring
scripts/checks/roadmap/validate_platform_roadmap.py's _roadmap_size_issues() precedent
(Decision 114). Unlike the roadmap guard (structured, cheaply projectable), the decision
log's binding consumer is the decision-scout subagent, which reads the whole LIVE file
every /plan with no offset/limit -- so the ceiling is sized against that whole-file read,
not a line count.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry

_DECISIONS_LIVE_MAX_BYTES = 400_000
_DECISIONS_LIVE_MAX_H2 = 120
_DECISIONS_COMBINED_MAX_BYTES = 700_000

_RELIEF_VALVES = (
    "archive superseded entries per DPI-04's dispositions "
    "(audits/decision-log-premise-integrity-8fb581e.yaml) or compact superseded decision "
    "bodies to pointer stubs"
)

_LIVE_H2_RE = re.compile(r"^## Decision \d+:", re.MULTILINE)


def _decisions_size_issues(
    live_text: str,
    archive_text: str,
    live_max_bytes: int = _DECISIONS_LIVE_MAX_BYTES,
    live_max_h2: int = _DECISIONS_LIVE_MAX_H2,
    combined_max_bytes: int = _DECISIONS_COMBINED_MAX_BYTES,
) -> list[str]:
    """Return a FAIL string per breached ceiling, or [] when live/archive are all within bound."""
    issues: list[str] = []

    live_bytes = len(live_text.encode("utf-8"))
    archive_bytes = len(archive_text.encode("utf-8"))
    combined_bytes = live_bytes + archive_bytes
    live_h2_count = len(_LIVE_H2_RE.findall(live_text))

    if live_bytes > live_max_bytes:
        issues.append(
            f"  FAIL: docs/DECISIONS.md is {live_bytes} bytes, exceeding the {live_max_bytes}-byte "
            f"live ceiling (Decision 133) -- relief valves: {_RELIEF_VALVES}"
        )
    if live_h2_count > live_max_h2:
        issues.append(
            f"  FAIL: docs/DECISIONS.md has {live_h2_count} live '## Decision' headers, exceeding "
            f"the {live_max_h2}-header ceiling (Decision 133) -- relief valves: {_RELIEF_VALVES}"
        )
    if combined_bytes > combined_max_bytes:
        issues.append(
            f"  FAIL: docs/DECISIONS.md + docs/DECISIONS_ARCHIVE.md combined are {combined_bytes} "
            f"bytes, exceeding the {combined_max_bytes}-byte combined ceiling (Decision 133) -- "
            f"relief valves: {_RELIEF_VALVES}"
        )
    return issues


@registry.register("validate_decisions_size", owner="platform")
def validate_decisions_size(failed: list[str]) -> None:
    """Enforce the Decision 133 size ceiling on docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md.

    Cheap stat + header count -- registered in BOTH the --pre and full validate tiers. Guards
    the decision-scout subagent's mandatory whole-live-file read every /plan: live bytes, live
    '## Decision' header count, and live+archive combined bytes must each stay under their
    ceiling (_DECISIONS_LIVE_MAX_BYTES / _DECISIONS_LIVE_MAX_H2 / _DECISIONS_COMBINED_MAX_BYTES).
    On breach, the failure message names the relief valves (archival per DPI-04; compaction of
    superseded bodies to pointer stubs) so the guard is actionable, not just a stop sign.
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
