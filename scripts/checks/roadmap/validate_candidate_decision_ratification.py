"""Candidate-decision ratification referential guard (Decision 105 / T-1.20 follow-on).

R1: every state==ratified CD resolves to a dec-NNN (via ratified_as, else the dec-NNN
    inside filed_via) that matches a `## Decision NNN:` header in DECISIONS.md OR
    DECISIONS_ARCHIVE.md; when both ratified_as and filed_via are present they must agree.
R2: no state==pending CD carries ratified_as, and its filed_via is absent or the pending
    literal pending_log_decision_lambda (never a dec-pointer).
R3: state==superseded CDs are exempt from R1.

Referential target is the two git-tracked decision files, not the gitignored
ops_decisions cache (CI PR roles lack reader access) -- see docs/contracts/
candidate-decision-ratification.yaml for the canonical shape this guard enforces.
"""

from __future__ import annotations

import re
import sys

from scripts.checks import _common, registry

_HEADER_RE = re.compile(r"^## Decision (\d+):", re.MULTILINE)
# Anchored on both sides (rec-2467) -- a bare r"dec-(\d+)" would partially match a malformed
# pointer like "dec-0123abc" (silently resolving to dec-123). The lookaround bounds require
# the match not be flanked by another alnum char, so a malformed pointer fails to resolve at
# all (loud failure) instead of partially resolving; "ops_decisions:dec-078" still resolves
# (":" is not alnum).
_DEC_NNN_RE = re.compile(r"(?<![0-9A-Za-z])dec-(\d+)(?![0-9A-Za-z])")


def _decision_header_numbers() -> set[int]:
    numbers: set[int] = set()
    for name in ("DECISIONS.md", "DECISIONS_ARCHIVE.md"):
        path = _common.ROOT / "docs" / name
        if not path.exists():
            continue
        numbers.update(int(n) for n in _HEADER_RE.findall(path.read_text(encoding="utf-8")))
    return numbers


def _dec_number(pointer: str | None) -> int | None:
    if not pointer:
        return None
    m = _DEC_NNN_RE.search(pointer)
    return int(m.group(1)) if m else None


@registry.register("validate_candidate_decision_ratification", owner="platform")
def validate_candidate_decision_ratification(failed: list[str]) -> None:
    """Enforce the canonical ratified-CD shape against docs/ROADMAP-PLATFORM.yaml (Decision 105)."""
    print("\n=== Candidate decision ratification guard (Decision 105) ===")

    roadmap_path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path.relative_to(_common.ROOT)} not found")
        failed.append("Candidate decision ratification guard")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.platform_roadmap import load  # noqa: PLC0415

        doc = load(roadmap_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: could not load roadmap: {exc}")
        failed.append("Candidate decision ratification guard")
        return
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)

    header_numbers = _decision_header_numbers()
    issues: list[str] = []

    for cd in doc.candidate_decisions:
        if cd.state == "superseded":
            continue

        if cd.state == "pending":
            if cd.ratified_as is not None:
                issues.append(f"  FAIL: {cd.id} is state=pending but carries ratified_as={cd.ratified_as!r}")
            if cd.filed_via is not None and cd.filed_via != "pending_log_decision_lambda":
                issues.append(
                    f"  FAIL: {cd.id} is state=pending but filed_via={cd.filed_via!r} "
                    "(must be absent or 'pending_log_decision_lambda')"
                )
            continue

        if cd.state == "ratified":
            ratified_num = _dec_number(cd.ratified_as)
            filed_num = _dec_number(cd.filed_via)
            dec_num = ratified_num or filed_num
            if dec_num is None:
                issues.append(f"  FAIL: {cd.id} is state=ratified but neither ratified_as nor filed_via names a dec-NNN")
                continue
            if ratified_num is not None and filed_num is not None and ratified_num != filed_num:
                issues.append(f"  FAIL: {cd.id} ratified_as (dec-{ratified_num}) disagrees with filed_via (dec-{filed_num})")
                continue
            if dec_num not in header_numbers:
                issues.append(
                    f"  FAIL: {cd.id} resolves to dec-{dec_num} but no '## Decision {dec_num}:' header "
                    "exists in DECISIONS.md or DECISIONS_ARCHIVE.md"
                )

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Candidate decision ratification guard")
    else:
        n = len(header_numbers)
        print(f"  PASS: all non-superseded candidate_decisions carry the canonical shape ({n} headers indexed).")
