"""Interactive VP independent re-execution (T3.15 criterion c2, VF-01, Decision 148, re-keyed
to content resolution by the plan-resolution-content-keyed plan -- see the amendment on
Decision 132/148 in docs/DECISIONS.md).

Closes the cooperative-self-evaluation gap named in VF-01: a PLAN-*.yaml's Verification Plan
is currently self-reported by the implementing agent. This check independently re-executes,
in the --pre PR-gate tier, every ``phase == "pre-deploy"`` AND ``hermetic == True`` VP step of
a plan resolved via ``_common.resolve_declared_plans`` (content-keyed: an edge-triggered
``implementation_declared`` False->True flip between the diff base and the working tree,
mirrors validate_graduation_completeness's own implement-PR leg):

  Plan-only leg: a diff-present docs/plans/PLAN-*.yaml whose ``implementation_declared`` did
    NOT newly flip true in this diff DEFERS -- either the implementation is absent by
    construction (two-PR plan/implement flow, Decision 76) or the plan simply is not being
    implemented in this PR, so replaying feature-verification steps against it would fail every
    hermetic step regardless of whether the eventual implementation is correct. Prints a DEFER
    line and replays nothing for that plan.

  Implement leg: for every plan path resolved by ``_common.resolve_declared_plans``, loads the
    plan from disk and replays its hermetic pre-deploy steps against the complete
    (implementation-bearing) tree.

Matching rule (mirrored in .claude/skills/planning/SKILL.md's VP Design Rationale note):
  (a) Exit-code, always: the replayed command's returncode must be 0, else the step diverges.
  (b) Substring, opt-in: backtick-delimited literals (`` `like this` ``) extracted from the
      step's ``expected`` field via regex must each appear in the captured stdout+stderr, else
      the step diverges. Non-backtick prose in ``expected`` is never auto-extracted (false-
      positive risk -- Decision 104 plan constraint).
  A ``subprocess.TimeoutExpired`` is always a divergence.

Steps that are not (pre-deploy AND hermetic) are printed as EXCLUDED with an explicit reason
(``not-hermetic`` or ``post-deploy``) -- never silently skipped. A PLAN-*.yaml that fails
PlanDocument content validation (schema_version/YAML/field errors) is skipped with a note --
schema validity is validate_plan_documents' concern, not replayed here (avoids double-reporting
the same defect under two check names). An ``ImportError`` loading ``scripts.roadmap.plan_document``
itself is a distinct, infrastructural failure -- it is NOT downgraded to a skip; it reddens this
check directly (mirrors the ImportError/content-error split in ``validate_plan_documents.py``,
Decision 55 fail-loud).

Advisory SKIP (never a failure): no docs/plans/PLAN-*.yaml is present in the diff at all is a
no-op PASS (an empty domain, not a skip -- see the accounting-declaration composition in
``validate_vp_replay`` below); origin/main being unreachable (no fetch, detached clone, etc)
DEFERs every diff-present plan and declares ``skipped`` (content resolution needs a reachable
base to distinguish a flip from a pre-existing declaration).

One terminal Decision 170 declaration per dispatch (docs/contracts/check-accounting.yaml):
unreachable base -> ``skipped``; otherwise ``examined(len(resolved), unit="declared_plans")``
(0 -> vacuous, >0 -> enforced unless a replay diverges, which always wins as failed).

Bounded cost: a per-step timeout (PER_STEP_TIMEOUT_SECONDS) plus an aggregate wall-clock/step-
count cap (MAX_AGGREGATE_SECONDS / MAX_REPLAYED_STEPS) so a pathological hermetic command cannot
blow the 5-minute fast-tier budget (Decision 73). Hitting the cap appends one budget-guard
failure and stops replay -- it never silently truncates.

No network and no AWS calls are made BY THIS CHECK; it runs in the creds-free pr-validate job.
It trusts the plan author's ``hermetic: true`` marker (a plan constraint, not runtime-enforced
here) that the replayed command itself is creds-free and side-effect-free.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from scripts.checks import _common, registry

PER_STEP_TIMEOUT_SECONDS = 30
MAX_AGGREGATE_SECONDS = 120
MAX_REPLAYED_STEPS = 20

_BACKTICK_LITERAL_RE = re.compile(r"`([^`]+)`")


def _partition_steps(verification_plan) -> tuple[list, list[tuple]]:
    """Split VP steps into (replay set, EXCLUDED set with reason).

    Phase eligibility is checked before hermetic eligibility: a post-deploy step is reported
    as "post-deploy" regardless of its hermetic marker (phase alone disqualifies it from
    replay), and "not-hermetic" is reserved for a pre-deploy step that isn't marked hermetic.
    """
    replay = []
    excluded = []
    for step in verification_plan:
        if step.phase != "pre-deploy":
            excluded.append((step, "post-deploy"))
        elif not step.hermetic:
            excluded.append((step, "not-hermetic"))
        else:
            replay.append(step)
    return replay, excluded


def _extract_literals(expected: str) -> list[str]:
    return _BACKTICK_LITERAL_RE.findall(expected)


def _replay_step(plan_rel: str, step, root: Path, failed: list[str]) -> float:
    """Execute one hermetic pre-deploy VP step; append a divergence to failed[] if any.

    Returns elapsed wall-clock seconds (fed into the aggregate budget guard).
    """
    start = time.monotonic()
    try:
        result = subprocess.run(
            step.command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PER_STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        failed.append(
            f"vp-replay {plan_rel}:{step.step}: actual=TIMEOUT after {PER_STEP_TIMEOUT_SECONDS}s != expected={step.expected!r}"
        )
        return elapsed

    elapsed = time.monotonic() - start
    combined_output = result.stdout + result.stderr
    if result.returncode != 0:
        failed.append(
            f"vp-replay {plan_rel}:{step.step}: actual=exit {result.returncode} "
            f"!= expected=exit 0 (expected={step.expected!r}; output tail={combined_output[-500:]!r})"
        )
        return elapsed

    missing = [lit for lit in _extract_literals(step.expected) if lit not in combined_output]
    if missing:
        failed.append(
            f"vp-replay {plan_rel}:{step.step}: actual=missing literal(s) {missing} "
            f"!= expected={step.expected!r} (output tail={combined_output[-500:]!r})"
        )
    else:
        print(f"  PASS: {plan_rel}:{step.step} replayed ({step.command[:80]})")
    return elapsed


def _plan_only_pr_leg(plan_files: list[str], root: Path, resolved: set[str]) -> None:
    """Print DEFER for every diff-present plan whose `implementation_declared` did not newly
    flip true in this diff; a resolved plan's replay happens in `_implement_pr_leg`.
    """
    for plan_rel in plan_files:
        if not (root / plan_rel).exists():
            print(f"  SKIP: {plan_rel} (not present on disk -- deleted in this diff)")
            continue
        if plan_rel in resolved:
            print(f"  PASS: {plan_rel} -- implementation_declared newly true in this diff; replayed by the implement leg.")
        else:
            print(
                f"  DEFER: {plan_rel} -- implementation_declared not newly true in this diff; replay deferred until "
                "the plan declares its implementation."
            )


def _implement_pr_leg(root: Path, resolved: list[str], failed: list[str]) -> None:
    """Replay every resolved plan's hermetic pre-deploy steps against the complete
    (implementation-bearing) tree. `resolved` is the content-keyed resolution from
    `_common.resolve_declared_plans` -- every path in it already exists on disk.
    """
    if not resolved:
        print("  PASS: no plan(s) with a newly-true implementation_declared in this diff -- no-op.")
        return

    total_elapsed = 0.0
    replayed_count = 0
    budget_hit = False
    plans_resolved = 0

    for plan_rel in resolved:
        try:
            doc = _common.load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(f"vp-replay {plan_rel}: could not import scripts.roadmap.plan_document: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        plans_resolved += 1
        replay_steps, excluded_steps = _partition_steps(doc.verification_plan)

        for step, reason in excluded_steps:
            print(f"  EXCLUDED: {plan_rel}:{step.step} ({reason})")

        for step in replay_steps:
            if replayed_count >= MAX_REPLAYED_STEPS or total_elapsed >= MAX_AGGREGATE_SECONDS:
                failed.append(
                    f"vp-replay: aggregate replay budget exceeded "
                    f"(steps={replayed_count}, elapsed={total_elapsed:.1f}s) -- stopping replay"
                )
                budget_hit = True
                break
            total_elapsed += _replay_step(plan_rel, step, root, failed)
            replayed_count += 1

        if budget_hit:
            break

    if not any(f.startswith("vp-replay") for f in failed) and replayed_count:
        print(f"  PASS: {replayed_count} hermetic pre-deploy step(s) replayed clean across {plans_resolved} plan(s).")
    elif not replayed_count and not budget_hit and plans_resolved:
        print(f"  PASS: {plans_resolved} plan(s) resolved via implementation_declared, no hermetic step(s) to replay.")


@registry.register("validate_vp_replay", owner="platform")
def validate_vp_replay(failed: list[str], changed_files: list[str] | None = None, root: Path | None = None) -> None:
    """Independently re-execute hermetic pre-deploy VP steps, resolved via content-keyed
    resolution (plan-only defers, implement leg replays -- see module docstring).

    changed_files / root are test/dogfood injection seams -- default to
    _common.get_changed_files(root) (vs origin/main) and _common.ROOT respectively.

    Composes exactly ONE terminal Decision 170 declaration (docs/contracts/check-accounting.yaml):
    no plan present in the diff at all is an empty domain (examined(0), never skipped, since the
    domain is provably empty without needing the base at all); a diff-present plan set with an
    unreachable base DEFERs everything and declares skipped (content resolution needs a reachable
    base to tell a flip from a pre-existing declaration); otherwise examined(len(resolved)).
    """
    print("\n=== Interactive VP replay (T3.15 c2, VF-01) ===")
    root = root if root is not None else _common.ROOT
    changed = changed_files if changed_files is not None else _common.get_changed_files(root)

    plan_files = _common.plan_paths_from_changed(changed)
    if not plan_files:
        print("  PASS: no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        registry.examined(0, unit="declared_plans")
        return

    if not _common.origin_main_reachable(root):
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI) -- deferring every in-diff plan.")
        for plan_rel in plan_files:
            print(f"  DEFER: {plan_rel} -- diff base unreachable.")
        registry.skipped("diff base unreachable")
        return

    base = _common.push_context_base(root) or "origin/main"
    resolved = _common.resolve_declared_plans(changed, root, base)
    _plan_only_pr_leg(plan_files, root, set(resolved))
    _implement_pr_leg(root, resolved, failed)
    registry.examined(len(resolved), unit="declared_plans")
