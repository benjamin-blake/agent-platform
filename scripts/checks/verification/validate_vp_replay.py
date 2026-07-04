"""Interactive VP independent re-execution (T3.15 criterion c2, VF-01, Decision 104).

Closes the cooperative-self-evaluation gap named in VF-01: a PLAN-*.yaml's Verification Plan
is currently self-reported by the implementing agent. This check independently re-executes,
in the --pre PR-gate tier, every VP step of a diff-added/modified docs/plans/PLAN-*.yaml where
``phase == "pre-deploy"`` AND ``hermetic == True``, so a hermetic pre-deploy step that fails on
the PR tree cannot go green on self-report alone.

Matching rule (mirrored in .claude/skills/planning/SKILL.md's VP Design Rationale note):
  (a) Exit-code, always: the replayed command's returncode must be 0, else the step diverges.
  (b) Substring, opt-in: backtick-delimited literals (`` `like this` ``) extracted from the
      step's ``expected`` field via regex must each appear in the captured stdout+stderr, else
      the step diverges. Non-backtick prose in ``expected`` is never auto-extracted (false-
      positive risk -- Decision 104 plan constraint).
  A ``subprocess.TimeoutExpired`` is always a divergence.

Steps that are not (pre-deploy AND hermetic) are printed as EXCLUDED with an explicit reason
(``not-hermetic`` or ``post-deploy``) -- never silently skipped. A diff with no PLAN-*.yaml is a
no-op PASS. A PLAN-*.yaml that fails PlanDocument content validation (schema_version/YAML/field
errors) is skipped with a note -- schema validity is validate_plan_documents' concern, not
replayed here (avoids double-reporting the same defect under two check names). An ``ImportError``
loading ``scripts.plan_document`` itself is a distinct, infrastructural failure -- it is NOT
downgraded to a skip; it reddens this check directly (mirrors the ImportError/content-error split
in ``validate_plan_documents.py``, Decision 55 fail-loud).

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

_PLAN_PATH_RE = re.compile(r"^docs/plans/PLAN-[^/]+\.yaml$")
_BACKTICK_LITERAL_RE = re.compile(r"`([^`]+)`")


def _plan_paths_from_changed(changed_files: list[str]) -> list[str]:
    return sorted(f for f in changed_files if _PLAN_PATH_RE.match(f))


def _load_plan(rel_path: str, root: Path):
    """Load a PlanDocument via scripts.plan_document.load(), injecting repo root onto sys.path."""
    root_str = str(root)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.plan_document import load  # noqa: PLC0415

        return load(root / rel_path)
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)


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


@registry.register("validate_vp_replay", owner="platform")
def validate_vp_replay(failed: list[str], changed_files: list[str] | None = None, root: Path | None = None) -> None:
    """Independently re-execute hermetic pre-deploy VP steps of PLAN-*.yaml files in the diff.

    changed_files / root are test/dogfood injection seams -- default to
    _common.get_changed_files() (vs origin/main) and _common.ROOT respectively.
    """
    print("\n=== Interactive VP replay (T3.15 c2, VF-01) ===")
    root = root if root is not None else _common.ROOT
    changed = changed_files if changed_files is not None else _common.get_changed_files()

    plan_files = _plan_paths_from_changed(changed)
    if not plan_files:
        print("  PASS: no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        return

    total_elapsed = 0.0
    replayed_count = 0
    budget_hit = False

    for plan_rel in plan_files:
        plan_path = root / plan_rel
        if not plan_path.exists():
            print(f"  SKIP: {plan_rel} (not present on disk -- deleted in this diff)")
            continue

        try:
            doc = _load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(f"vp-replay {plan_rel}: could not import scripts.plan_document: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

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
        print(f"  PASS: {replayed_count} hermetic pre-deploy step(s) replayed clean across {len(plan_files)} plan(s).")
    elif not replayed_count and not budget_hit:
        print(f"  PASS: {len(plan_files)} plan(s) in diff, no hermetic pre-deploy steps to replay.")
