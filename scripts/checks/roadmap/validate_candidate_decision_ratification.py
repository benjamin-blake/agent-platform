"""Candidate-decision ratification referential guard (Decision 105 / T-1.20 follow-on).

R1: every state==ratified CD resolves to a dec-NNN (via ratified_as, else the dec-NNN
    inside filed_via) that matches a `## Decision NNN:` header in DECISIONS.md OR
    DECISIONS_ARCHIVE.md; when both ratified_as and filed_via are present they must agree.
R2: no state==pending CD carries ratified_as, and its filed_via is absent or the pending
    literal pending_log_decision_lambda (never a dec-pointer).
R3: state==superseded CDs are exempt from R1.
R4 (ESB-02 remediation wave 3, docs/contracts/candidate-decision-ratification.yaml amendment
    note; no numbered Decision, same routing as R1-R3): every state==ratified CD's own string
    discipline_points may declare ratification precondition ids via the literal pattern
    `ratification precondition (XX-NN)`. If it declares any, the CD must carry EXACTLY ONE
    dict discipline_point of shape `{"precondition_discharge": {<id>: <non-empty str>, ...}}`
    with a non-empty entry for every declared id (an entry may record an in-band lapse; a
    present-but-empty or absent entry for a declared id fails). A ratified CD declaring no
    precondition ids is a clean no-op -- R4 does not require a precondition_discharge block to
    exist at all in that case. BLAST RADIUS: this guard already gates every candidate-decision
    ratification repo-wide (R1-R3), so an R4 defect blocks ratification for every CD, not only
    the one whose text motivated R4 -- on the live tree (2026-08) CD.27 is the only CD (of
    dozens) declaring ratification preconditions, and it is state==pending, so R4 fires on
    nothing today; it activates the first time CD.27 (or any future CD reusing the same
    precondition pattern) ratifies.

Referential target is the two git-tracked decision files, not the gitignored
ops_decisions cache (CI PR roles lack reader access) -- see docs/contracts/
candidate-decision-ratification.yaml for the canonical shape this guard enforces.

DAF-03 consolidation (PLAN-daf-authoring-grammar, Decision 134 cl.3): the header-number scan
is now scripts.decisions_md.decision_header_numbers(), the shared '#{2,3}' grammar every
structural consumer imports -- this guard no longer hand-rolls its own header regex. Called
WITH an explicit paths= list derived from _common.ROOT (never no-arg): a no-arg call would read
decisions_md's own module-level repo root instead of the patched _common.ROOT the test suite
(and any future re-rooting) relies on. Stays hermetic (Decision 105): decisions_md reads only
the two git-tracked md files, no warehouse/reader access.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from scripts.checks import _common, registry
from scripts.decisions_md import decision_header_numbers
from scripts.platform_roadmap_models import CandidateDecision
from scripts.platform_roadmap_state import RoadmapDocument

# Anchored on both sides (rec-2467) -- a bare r"dec-(\d+)" would partially match a malformed
# pointer like "dec-0123abc" (silently resolving to dec-123). The lookaround bounds require
# the match not be flanked by another alnum char, so a malformed pointer fails to resolve at
# all (loud failure) instead of partially resolving; "ops_decisions:dec-078" still resolves
# (":" is not alnum).
_DEC_NNN_RE = re.compile(r"(?<![0-9A-Za-z])dec-(\d+)(?![0-9A-Za-z])")

# R4: the precondition-id declaration pattern. Deliberately the SAME literal shape the discharge
# rule's own discipline_point text is forbidden from reproducing (docs/plans/PLAN-esb-fallback-
# spec-carrier.yaml constraint) -- so a discharge-rule point never accidentally self-declares an id.
_PRECONDITION_ID_RE = re.compile(r"ratification precondition \((\w+-\d+)\)")


def _precondition_ids(cd: CandidateDecision) -> list[str]:
    """Precondition ids a CD's discipline_points declare (R4 trigger).

    Scans the SERIALIZED TEXT of discipline_points (yaml.safe_dump), not just
    isinstance(pt, str) entries -- code review round 3 (Medium, promoted to blocking): a
    colon-hazard accidental YAML mapping (CD.27's own pre-existing "T4.x atomic-plan template"
    entry is exactly this shape -- a discipline_point string containing a colon-space silently
    becomes a `{key: value}` mapping) would otherwise silently hide a declared id from a
    str-only filter, understating R4's own coverage: partial enforcement presenting as full is
    the phantom-control shape this wave exists to remove. No discriminator between prose-keyed
    (accidental) and field-keyed (legitimate: fallback_spec / resume_properties /
    stability_definition_14d) dict entries is needed here: the anchored
    `ratification precondition (XX-NN)` pattern cannot legitimately appear inside a structured
    field-keyed dict, so scanning everything uniformly is safe and requires no such
    discrimination.
    """
    pts = cd.discipline_points or []
    blob = yaml.safe_dump(pts, sort_keys=False)
    return _PRECONDITION_ID_RE.findall(blob)


def _precondition_discharge_blocks(cd: CandidateDecision) -> list[dict]:
    """Dict discipline_points carrying a `precondition_discharge` key (R4 discharge record)."""
    pts = cd.discipline_points or []
    return [pt for pt in pts if isinstance(pt, dict) and "precondition_discharge" in pt]


def _precondition_discharge_near_miss_keys(cd: CandidateDecision) -> list[str]:
    """Structural-integrity companion to `_precondition_ids`'s blob-scan fix: the discharge
    side's own colon-hazard risk. `_precondition_discharge_blocks` requires an EXACT top-level
    dict key `precondition_discharge`; a discipline_point that colon-hazards into a dict whose
    key merely CONTAINS that word as a substring (e.g. a string
    "precondition_discharge for ESB-04: ..." silently becomes a dict keyed
    "precondition_discharge for ESB-04") does not resolve as a clean block, yet is present.
    Deliberately scoped to DICT-typed discipline_points only -- never string-typed ones -- so
    ordinary prose that happens to mention the word (e.g. this CD's own discharge-RULE point,
    "...must record a non-empty precondition_discharge entry...") is never mistaken for a
    near-miss; a substring scan over the WHOLE serialized blob would conflate the two and make
    R4 permanently unpassable for any CD whose discharge-rule prose and a real discharge block
    coexist. Returns the list of near-miss keys found (empty if none) -- non-empty means
    something is hiding from `_precondition_discharge_blocks` and must fail loud rather than be
    silently treated as "no discharge attempted".
    """
    pts = cd.discipline_points or []
    near_misses: list[str] = []
    for pt in pts:
        if not isinstance(pt, dict):
            continue
        for key in pt:
            if isinstance(key, str) and key != "precondition_discharge" and "precondition_discharge" in key:
                near_misses.append(key)
    return near_misses


def _decision_header_numbers() -> set[int]:
    """Header-number population, via the shared decisions_md grammar, rooted at _common.ROOT.

    Always passes an explicit paths= list -- never a no-arg call -- so a patched
    scripts.checks._common.ROOT (the test suite's re-rooting seam) is honored instead of
    decisions_md's own module-level repo root.
    """
    return decision_header_numbers(
        paths=[_common.ROOT / "docs" / "DECISIONS.md", _common.ROOT / "docs" / "DECISIONS_ARCHIVE.md"]
    )


def _dec_number(pointer: str | None) -> int | None:
    if not pointer:
        return None
    m = _DEC_NNN_RE.search(pointer)
    return int(m.group(1)) if m else None


def _check_r2_pending(cd: CandidateDecision, issues: list[str]) -> None:
    if cd.ratified_as is not None:
        issues.append(f"  FAIL: {cd.id} is state=pending but carries ratified_as={cd.ratified_as!r}")
    if cd.filed_via is not None and cd.filed_via != "pending_log_decision_lambda":
        issues.append(
            f"  FAIL: {cd.id} is state=pending but filed_via={cd.filed_via!r} "
            "(must be absent or 'pending_log_decision_lambda')"
        )


def _check_r1_ratified(cd: CandidateDecision, header_numbers: set[int], issues: list[str]) -> bool:
    """R1. Returns False only when dec_num is entirely unresolvable -- missing (neither
    ratified_as nor filed_via names one) or disagreeing (ratified_as and filed_via name
    different dec-NNNs) -- because R4 literally has no dec-NNN to reason about in either case.
    A THIRD failure mode (dec_num resolves but no matching '## Decision NNN:' header exists)
    still returns True: R4's precondition-discharge property is independent of whether the
    Decision header text is findable, so R4 still runs and reports its own findings in the same
    pass rather than being silently withheld behind an unrelated R1 failure.
    """
    ratified_num = _dec_number(cd.ratified_as)
    filed_num = _dec_number(cd.filed_via)
    dec_num = ratified_num or filed_num
    if dec_num is None:
        issues.append(f"  FAIL: {cd.id} is state=ratified but neither ratified_as nor filed_via names a dec-NNN")
        return False
    if ratified_num is not None and filed_num is not None and ratified_num != filed_num:
        issues.append(f"  FAIL: {cd.id} ratified_as (dec-{ratified_num}) disagrees with filed_via (dec-{filed_num})")
        return False
    if dec_num not in header_numbers:
        issues.append(
            f"  FAIL: {cd.id} resolves to dec-{dec_num} but no '## Decision {dec_num}:' header "
            "exists in DECISIONS.md or DECISIONS_ARCHIVE.md"
        )
    return True


def _check_r4_precondition_discharge(cd: CandidateDecision, issues: list[str]) -> None:
    """R4. Early-continue (clean no-op) when the CD declares no precondition ids -- R4 must not
    require a block that has nothing to discharge. The text-mismatch integrity check runs FIRST,
    unconditionally (even when precondition_ids is empty) -- it is the loud-failure path for the
    exact defect class `_precondition_ids`'s blob-scan fixes on the declaration side, applied
    symmetrically to the discharge side: something naming `precondition_discharge` must never be
    silently invisible to this guard, whether or not a real precondition id happens to be
    declared elsewhere."""
    near_misses = _precondition_discharge_near_miss_keys(cd)
    if near_misses:
        issues.append(
            f"  FAIL: {cd.id} discipline_points contains dict key(s) {near_misses} that mention "
            "'precondition_discharge' without matching it exactly -- a colon-hazard or malformed entry "
            "may be hiding a discharge record from this guard"
        )
        return
    precondition_ids = sorted(set(_precondition_ids(cd)))
    if not precondition_ids:
        return
    discharge_blocks = _precondition_discharge_blocks(cd)
    if len(discharge_blocks) != 1:
        issues.append(
            f"  FAIL: {cd.id} declares ratification precondition id(s) {precondition_ids} but carries "
            f"{len(discharge_blocks)} precondition_discharge block(s) (must be exactly 1)"
        )
        return
    discharge = discharge_blocks[0].get("precondition_discharge")
    if not isinstance(discharge, dict):
        issues.append(f"  FAIL: {cd.id} precondition_discharge is not a mapping")
        return
    missing = [pid for pid in precondition_ids if not isinstance(discharge.get(pid), str) or not discharge[pid].strip()]
    if missing:
        issues.append(f"  FAIL: {cd.id} precondition_discharge is missing a non-empty entry for {missing}")


def _load_roadmap(roadmap_path: Path, failed: list[str]) -> RoadmapDocument | None:
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.platform_roadmap import load  # noqa: PLC0415

        return load(roadmap_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: could not load roadmap: {exc}")
        failed.append("Candidate decision ratification guard")
        return None
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


@registry.register("validate_candidate_decision_ratification", owner="platform")
def validate_candidate_decision_ratification(failed: list[str]) -> None:
    """Enforce the canonical ratified-CD shape against docs/ROADMAP-PLATFORM.yaml (Decision 105)."""
    print("\n=== Candidate decision ratification guard (Decision 105) ===")

    roadmap_path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path.relative_to(_common.ROOT)} not found")
        failed.append("Candidate decision ratification guard")
        return

    doc = _load_roadmap(roadmap_path, failed)
    if doc is None:
        return

    header_numbers = _decision_header_numbers()
    issues: list[str] = []

    for cd in doc.candidate_decisions:
        if cd.state == "superseded":
            continue
        if cd.state == "pending":
            _check_r2_pending(cd, issues)
            continue
        if cd.state == "ratified":
            if _check_r1_ratified(cd, header_numbers, issues):
                _check_r4_precondition_discharge(cd, issues)

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Candidate decision ratification guard")
    else:
        n = len(header_numbers)
        print(f"  PASS: all non-superseded candidate_decisions carry the canonical shape ({n} headers indexed).")
