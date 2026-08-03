"""Fallback re-evaluation carrier for CD.27's Lambda Durable Functions fallback (ESB-02
remediation, docs/plans/PLAN-esb-fallback-spec-carrier.yaml).

CD.27's maturity-monitoring discipline_point promised a re-evaluation trigger at each gated
atomic-plan filing; before this module, no carrier enforced it (ESB-02: a phantom control).
This check is the instantiated carrier: it resolves CD.27's OWN `gates` list from the roadmap
as the trigger set (single-sourced, drift-proof -- Decision 136 precedent), then requires any
NET-NEW docs/plans/PLAN-*.yaml naming a gated tier item -- via `closes_criteria` OR via the
required `phase` field -- to carry a `fallback_reevaluation` block (scripts/roadmap/
plan_document.py FallbackReevaluation).

NET-NEW SCOPING (Decision 132's settled answer to retro-fitting): only plans added
(git status "A") since the origin/main merge-base are in scope. A whole-directory version of
this predicate reddens 8 historical plans (verified at authoring time) that legitimately touch
CD.27-gated tier items without ever having formed a substrate verdict -- retro-fitting them
would be exactly the kind of after-the-fact assertion ESB-02 exists to remove. A net-new-but-
UNCOMMITTED plan surfaces as git status "??", not "A", and is therefore NOT in scope until
committed.

PHASE-LEG INSTANTIABILITY: a closes_criteria-only trigger is UNINSTANTIABLE today -- T4.1,
T4.2 and T4.4 exit_criteria are bare strings (only T4.3 and T4.12 are ledger dicts), so
validate_platform_roadmap check (iii) cannot resolve a `"T4.2:c1"`-shaped ref against them, and
two live guards pin those criteria bare. The phase leg is therefore what makes this carrier
reachable at all until a T4.x plan converts to ledger form.

BOUNDARY-AWARE TOKEN MATCH IS MANDATORY on the phase leg -- gate `T4.1` is a string PREFIX of
six live tier_item ids (T4.10, T4.10a, T4.11, T4.12, T4.13, T4.14). A bare substring match would
compel a future T4.13 plan to record a substrate verdict it has no basis to form -- doc-says-X /
control-does-Y, reproduced INSIDE the control this wave built to remove that defect. The pattern
is `(?<![\\w.])<gate>(?![\\w])`: the lookahead excludes word characters ONLY (not `.`), so a
legitimate sentence-final "T4.4." still matches while "T4.12"/"T4.13" do not match gate "T4.1".
The closes_criteria leg needs no such matcher: its item ids are already discrete tokens (split
on ':', index 0 -- Decision 136: existence is validate_platform_roadmap check (iii)'s job, not
re-validated here), so exact set membership suffices.

THREE MECHANICS THIS PRIMITIVE DOES NOT SHARE with the validate_graduation_completeness /
validate_verifier_same_pr_guard `_added_plan_paths` precedent, all load-bearing:
  (a) this module takes NO `root` argument and hard-keys on module-level `_common.ROOT` (Decision
      104 discipline: shared primitives referenced via the qualified `_common.<name>` form).
  (b) net-new derivation is `_common.get_status_aware_diff()`'s "A" entries, which diffs against
      the MERGE-BASE with origin/main (not origin/main directly) -- not a drop-in equivalent of
      the `_added_plan_paths` precedent's `git diff --diff-filter=A origin/main`.
  (c) `_common.get_status_aware_diff()` SILENTLY FALLS BACK TO comparing against HEAD when the
      merge-base lookup fails, rather than raising -- an unreachable origin/main would otherwise
      make this check pass VACUOUSLY (no net-new plans found) instead of admitting it could not
      determine the diff. This is exactly what makes the `_common.origin_main_reachable()` guard
      below load-bearing rather than decorative: it must run BEFORE the diff, as an explicit
      advisory-SKIP, not be inferred from an empty diff result.

Fail-loud (Decision 55) if CD.27 is absent from the roadmap -- a missing trigger set is not
"nothing to check". Advisory-SKIP (never a failure) when origin/main is unreachable (Decision 132
limitation A) -- structurally identical to validate_graduation_completeness's own advisory-SKIP
for the same condition.

Injectable seam: `roadmap_path` ONLY. There is deliberately no `plans_dir` seam and no
`added_paths` seam. `_common.ROOT` is the SOLE root for everything net-new-plan-related (the
diff itself, and resolving each added path back to a file to load) -- a second, independent
root parameter here would be two ways to be wrong instead of one: a caller could patch
`_common.ROOT` (which the real-git tests do) while a stale `plans_dir` default silently pointed
elsewhere, and nothing would catch the mismatch. Tests that need to prove the net-new predicate
against real git state patch `scripts.checks._common.ROOT` and lay out the fixture tree there --
see tests/checks/roadmap/test_validate_fallback_reevaluation.py. NO `added_paths` injection seam
either: validate_graduation_completeness's own docstring (:34-38) refuses that seam because "a
seam would defeat the point of the test": the net-new predicate must be proven against REAL git
state (a throwaway repo with a real refs/remotes/origin/main), not an injected stub, because
this plan's entire retro-fit defence rests on that property actually holding.

CARRIER LIFECYCLE -- CANONICAL HERE (code review round 3 / High): this module docstring is the
enforcement-collocated site (AGENTS.md: "collocate semantic definitions with their enforcement
counterparts in a single file"), so the full lifecycle lives ONLY here. CD.27's own
`fallback_spec.reevaluation_carrier` text and the plan's CARRIER LIFECYCLE context entry each
carry a one-line POINTER to this paragraph, never a restatement -- a second or third verbatim
copy with nothing enforcing sync would be a NEW unenforced claim minted inside the very
remediation ESB-02 exists to close.
  - PERSISTENCE: the carrier PERSISTS against a ratified CD. All ratified CDs retain their
    candidate_decisions entry and `gates` list, so the CD.27-sourced trigger set survives
    ratification unchanged -- this is correct rather than incidental, because CD.27 scopes the
    maturity hedge to the first 12 months AFTER ratification, so the obligation's live window
    BEGINS at ratification and the check is a no-op in practice before it.
  - EXIT: in-band, via the `obligation_lapsed` FallbackVerdict recorded on a plan's
    `fallback_reevaluation` block (basis: the ratification date, or whatever event closed the
    obligation). The carrier requires A recorded verdict, never a particular one -- it retires by
    leaving an audit trail, never by someone remembering to delete a check, which is the exact
    failure that would make it a cousin of the phantom control it replaces.
  - DISCLOSED RESIDUALS (all three, not a partial list -- each is an honest floor of a text-keyed
    trigger, accepted rather than papered over):
      (i) a plan MODIFIED rather than added escapes the net-new-scoping leg (Decision 132's own
          disclosed limitation, inherited knowingly here).
      (ii) an unreachable origin/main advisory-SKIPs the whole check rather than failing (Decision
           132 limitation A) -- see the origin_main_reachable() discussion above.
      (iii) a T4.x plan naming no gated item in either `phase` or `closes_criteria` escapes
            entirely -- the carrier has no third leg to catch it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.checks import _common, registry

# The two halves of the boundary-aware gate-token match, named separately (not just embedded in
# _gate_pattern's return) because VP step 3's regex-identity ratchet pins each independently: the
# lookbehind alone was insufficient -- round 2's own history is a lookahead defect
# ((?![0-9a-zA-Z.]) silently dropping a legitimate sentence-final "T4.4."), so a ratchet that only
# checks the lookbehind pins the half that never broke. One definition, consumed by _gate_pattern
# -- no second copy of either literal anywhere in this module.
_GATE_LOOKBEHIND = r"(?<![\w.])"
_GATE_LOOKAHEAD = r"(?![\w])"


def _cd27_gates(roadmap_path: Path) -> list[str] | None:
    """CD.27's own `gates` list from the roadmap at roadmap_path, or None if CD.27 is absent."""
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.platform_roadmap import load  # noqa: PLC0415

        doc = load(roadmap_path)
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    cd27 = next((cd for cd in doc.candidate_decisions if cd.id == "CD.27"), None)
    if cd27 is None:
        return None
    return list(cd27.gates)


def _gate_pattern(gates: list[str]) -> re.Pattern[str]:
    """Boundary-aware alternation over gates: (?<![\\w.])(gate1|gate2|...)(?![\\w])."""
    alts = "|".join(re.escape(g) for g in gates)
    return re.compile(_GATE_LOOKBEHIND + "(" + alts + ")" + _GATE_LOOKAHEAD)


def _closes_criteria_item_ids(closes_criteria: list[str]) -> set[str]:
    """Item ids named in closes_criteria refs (split on ':', index 0).

    Decision 136 CONSUMED, not re-implemented: validate_platform_roadmap check (iii) already
    resolves every closes_criteria ref to a real item:criterion. A second existence-resolver
    here would be a drift surface.
    """
    ids: set[str] = set()
    for ref in closes_criteria:
        if ":" in ref:
            item_id, _, _crit = ref.partition(":")
            if item_id:
                ids.add(item_id)
    return ids


def _net_new_plan_paths() -> list[str] | None:
    """Net-new (git status 'A') docs/plans/PLAN-*.yaml paths vs the origin/main merge-base.

    Returns None when origin/main is unreachable (caller advisory-SKIPs). Always runs against
    module-level `_common.ROOT` -- the sole root (no parameter here); a caller proving the
    net-new predicate against real git state patches `scripts.checks._common.ROOT` directly.
    """
    if not _common.origin_main_reachable(_common.ROOT):
        return None
    entries = _common.get_status_aware_diff()
    return sorted(path for status, path in entries if status == "A" and _common.PLAN_PATH_RE.match(path))


@registry.register("validate_fallback_reevaluation", owner="platform")
def validate_fallback_reevaluation(
    failed: list[str],
    roadmap_path: Path | None = None,
) -> None:
    """Enforce the CD.27 fallback re-evaluation carrier on net-new gated atomic plans.

    roadmap_path is the sole injectable seam (test/dogfood); the net-new-plan-path predicate
    itself is never injectable -- see module docstring.
    """
    print("\n=== Fallback re-evaluation carrier (ESB-02 remediation) ===")

    roadmap_path = roadmap_path if roadmap_path is not None else _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"

    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path} not found -- the re-evaluation carrier has no roadmap to resolve CD.27's gates from.")
        failed.append("Fallback re-evaluation carrier")
        return

    try:
        gates = _cd27_gates(roadmap_path)
    except Exception as exc:  # noqa: BLE001 -- any parse failure is a hard FAIL, never a silent pass
        print(f"  FAIL: could not load roadmap to resolve CD.27's gates: {exc}")
        failed.append("Fallback re-evaluation carrier")
        return

    if gates is None:
        print(
            f"  FAIL: CD.27 not found in {roadmap_path} -- the re-evaluation carrier has no trigger set "
            "(Decision 55: fail loud, never treat a missing trigger as nothing to check)."
        )
        failed.append("Fallback re-evaluation carrier")
        return

    if not gates:
        print(
            f"  FAIL: CD.27 in {roadmap_path} declares an empty gates list -- the re-evaluation carrier has no "
            "trigger set (Decision 55: fail loud; an emptied gates list is the phantom-control shape this wave "
            "exists to remove -- a silent pass here would make the carrier a permanent, undetectable no-op)."
        )
        failed.append("Fallback re-evaluation carrier")
        return

    added = _net_new_plan_paths()
    if added is None:
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI; Decision 132 limitation A).")
        return

    if not added:
        print("  PASS: no net-new docs/plans/PLAN-*.yaml in this diff.")
        return

    gate_set = set(gates)
    gate_pattern = _gate_pattern(gates)
    issues: list[str] = []

    for rel in added:
        plan_path = _common.ROOT / rel
        if not plan_path.exists():
            print(f"  SKIP: {rel} (not present on disk).")
            continue

        try:
            doc = _common.load_plan(rel, _common.ROOT)
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {rel}: load error ({exc}) -- not double-reported here.")
            continue

        closes_hits = sorted(_closes_criteria_item_ids(doc.closes_criteria) & gate_set)
        phase_hits = sorted(set(gate_pattern.findall(doc.phase)))

        if not closes_hits and not phase_hits:
            print(f"  PASS: {rel} -- names no CD.27-gated item.")
            continue

        legs = []
        if closes_hits:
            legs.append(f"closes_criteria names {closes_hits}")
        if phase_hits:
            legs.append(f"phase names {phase_hits}")
        leg_desc = "; ".join(legs)

        if doc.fallback_reevaluation is None:
            issues.append(f"  FAIL: {rel} names CD.27-gated item(s) ({leg_desc}) but carries no fallback_reevaluation block")
        else:
            print(f"  PASS: {rel} -- gated ({leg_desc}), fallback_reevaluation present.")

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Fallback re-evaluation carrier")
