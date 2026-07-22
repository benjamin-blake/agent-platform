"""Interactive VP independent re-execution (T3.15 criterion c2, VF-01, Decision 148).

Closes the cooperative-self-evaluation gap named in VF-01: a PLAN-*.yaml's Verification Plan
is currently self-reported by the implementing agent. This check independently re-executes,
in the --pre PR-gate tier, every ``phase == "pre-deploy"`` AND ``hermetic == True`` VP step of
a plan resolved by the two-leg model below (mirrors validate_graduation_completeness, Decision
132/148):

  Plan-only-PR leg: a diff-added/modified docs/plans/PLAN-*.yaml with NO co-present
    feat({slug}) implementation commit on `git log origin/main..HEAD` DEFERS -- the
    implementation is absent by construction (two-PR plan/implement flow, Decision 76), so
    replaying feature-verification steps against a plan-only tree would fail every hermetic
    step regardless of whether the eventual implementation is correct. Prints a DEFER line and
    replays nothing for that plan.

  Implement-PR leg: resolves PLAN-{slug}.yaml from feat({slug}) commit subjects on
    `git log origin/main..HEAD` (co-present plan+code included), loads each plan from disk, and
    replays its hermetic pre-deploy steps against the complete (implementation-bearing) tree.

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

Advisory SKIP (never a failure), mirroring Decision 132's disclosed residual limitations:
  (a) origin/main is unreachable (no fetch, detached clone, etc) -- skips the WHOLE
      implement-PR leg (feat-commit resolution needs it).
  (b) a feat({slug}) commit subject names a plan whose PLAN-{slug}.yaml is absent (legacy
      .md-era plan, archived, or a typo'd slug) -- skips just that commit's replay.

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


def _plan_only_pr_leg(changed_files: list[str], root: Path) -> None:
    """Diff-added/modified plans with no co-present feat({slug}) commit DEFER replay.

    The implementation is absent by construction on a plan-only PR (two-PR plan/implement flow,
    Decision 76) -- replaying feature-verification steps against an implementation-less tree
    would fail every hermetic step regardless of whether the eventual implementation is correct.
    A plan whose slug DOES have a co-present feat({slug}) commit in this same diff is left to the
    implement-PR leg, which replays it against the complete tree.
    """
    plan_files = _common.plan_paths_from_changed(changed_files)
    if not plan_files:
        print("  PASS: no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        return

    implemented_slugs = set(_common.feat_commit_slugs(root))
    for plan_rel in plan_files:
        if not (root / plan_rel).exists():
            print(f"  SKIP: {plan_rel} (not present on disk -- deleted in this diff)")
            continue
        match = _common.PLAN_PATH_RE.match(plan_rel)
        slug = match.group(1) if match else None
        if slug is not None and slug in implemented_slugs:
            print(f"  PASS: {plan_rel} -- co-present feat({slug}) commit in this diff; replayed by the implement-PR leg.")
        else:
            print(
                f"  DEFER: {plan_rel} -- plan-only PR (no co-present feat({{slug}}) implementation commit in this "
                "diff); replay deferred to the implement PR, where the plan resolves against a complete tree."
            )


def _implement_pr_leg(root: Path, failed: list[str]) -> None:
    """Resolve PLAN-{slug}.yaml from feat({slug}) commit subjects on origin/main..HEAD and replay
    each plan's hermetic pre-deploy steps against the complete (implementation-bearing) tree.
    """
    if not _common.origin_main_reachable(root):
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI) -- implement-PR leg skipped.")
        return

    slugs = _common.feat_commit_slugs(root)
    if not slugs:
        print("  PASS: no feat({slug}) commit(s) in this diff -- no-op.")
        return

    total_elapsed = 0.0
    replayed_count = 0
    budget_hit = False
    plans_resolved = 0

    for slug in slugs:
        plan_rel = f"docs/plans/PLAN-{slug}.yaml"
        plan_path = root / plan_rel
        if not plan_path.exists():
            print(f"  SKIP: {plan_rel} not found for feat({slug}) commit -- unresolvable plan, advisory.")
            continue

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
        print(f"  PASS: {plans_resolved} plan(s) resolved via feat({{slug}}) commit(s), no hermetic step(s) to replay.")


@registry.register("validate_vp_replay", owner="platform")
def validate_vp_replay(failed: list[str], changed_files: list[str] | None = None, root: Path | None = None) -> None:
    """Independently re-execute hermetic pre-deploy VP steps, resolved via the two-leg model
    (plan-only-PR defers, implement-PR replays -- see module docstring).

    changed_files / root are test/dogfood injection seams -- default to
    _common.get_changed_files() (vs origin/main) and _common.ROOT respectively.
    """
    print("\n=== Interactive VP replay (T3.15 c2, VF-01) ===")
    root = root if root is not None else _common.ROOT
    changed = changed_files if changed_files is not None else _common.get_changed_files()

    _plan_only_pr_leg(changed, root)
    _implement_pr_leg(root, failed)
