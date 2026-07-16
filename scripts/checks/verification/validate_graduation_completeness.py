"""Verification graduation completeness gate (T3.21, VF-05 enforcement).

VF-05 (T3.18) shipped the graduation PRODUCER (the implement skill's Tier_item bookkeeping
walk graduates a plan's own kernel-expressible VP steps into
config/agent/verification_registry/registry.yaml) and VF-06 (validate_verification_registry's
real differential admission gate). Neither one is an OBLIGATION: nothing forces a fix PR to
actually add the registry row it owes, so a skip is invisible to CI (a plan-PR incident, PR
#586, shipped 4 orphaned checks -- no new registry entries, so "correctly graduated nothing"
looked identical to "forgot to graduate"). This check closes that gap by enforcing the plan's
OWN declared graduation dispositions across two legs:

  Plan-PR leg: a diff-added or diff-modified docs/plans/PLAN-*.yaml must carry a graduation
    disposition (graduate|waive|not-applicable) on every pre-deploy VP step -- field presence
    only, no kernel-expressibility inference (that classification judgement is the fresh-context
    plan-critique gate's job, at plan time). Enforced only when the plan is net-new in the diff
    (git diff --diff-filter=A) OR it already declares >=1 disposition somewhere -- a merely-
    modified plan that declares zero dispositions anywhere (a correction to a pre-field plan, or
    the lagged .yaml archival sweep) is a pre-field plan and is skipped, not failed.

  Implement-PR leg: resolves the plan(s) referenced by feat({slug}) commit subjects on
    `git log origin/main..HEAD`, loads PLAN-{slug}.yaml, and asserts every VP step declared
    graduate produced a matching NEW-in-diff registry row (plan_slug == slug AND
    check_id == graduation_check_id). waive/not-applicable steps require no row. A step whose
    graduation proved impossible at implement time is expected to have been flipped to waive
    (with a reason) in the same PR -- that flip satisfies this leg with no row.

Fail-loud (Decision 55) on genuine errors (a schema-import failure). Advisory SKIP (never a
failure) on two disclosed residual-limitation shapes that must not wedge a legitimate PR:
  (a) origin/main is unreachable (no fetch, detached clone, etc) -- skips the WHOLE
      implement-PR leg (the leg cannot resolve new-vs-baseline without it).
  (b) a feat({slug}) commit subject names a plan whose PLAN-{slug}.yaml is absent (legacy
      .md-era plan, archived, or a typo'd slug) -- skips just that commit's obligation.

Injection seams (changed_files, root, load_plan, baseline_registry_reader) mirror the
validate_vp_replay / validate_sloc_budget_raises precedents for testability without real git
state, except where a seam would defeat the point of the test (feat-commit resolution and the
net-new-plan-path predicate use real `git log` / `git diff` against `root` -- tests set up a
throwaway repo with a `refs/remotes/origin/main` ref, mirroring tests/test_verification_graduation.py).

scripts/verification_checks.py (the six-slot CD.29 kernel) is never touched here -- this check
is diff-scoped plan/registry parsing only; it never re-runs a differential (that stays owned by
validate_verification_registry / VF-06).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from scripts.checks import _common, registry

_PLAN_PATH_RE = re.compile(r"^docs/plans/PLAN-([^/]+)\.yaml$")
_FEAT_COMMIT_RE = re.compile(r"^feat\(([^)]+)\):")
_REGISTRY_REL_PATH = "config/agent/verification_registry/registry.yaml"

LoadPlanFn = Callable[[str, Path], object]
BaselineRegistryReaderFn = Callable[[Path], list[dict]]


def _plan_paths_from_changed(changed_files: list[str]) -> list[str]:
    return sorted(f for f in changed_files if _PLAN_PATH_RE.match(f))


def _load_plan(rel_path: str, root: Path):
    """Load a PlanDocument via scripts.roadmap.plan_document.load(), injecting repo root onto sys.path."""
    root_str = str(root)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.plan_document import load  # noqa: PLC0415

        return load(root / rel_path)
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)


def _added_plan_paths(root: Path) -> set[str]:
    """Plan paths added (git diff-filter=A) in this diff vs origin/main -- net-new plans."""
    result = _common.run(
        ["git", "diff", "--name-only", "--diff-filter=A", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return set()
    return {f for f in result.stdout.strip().splitlines() if _PLAN_PATH_RE.match(f)}


def _plan_pr_leg(changed_files: list[str], root: Path, failed: list[str], load_plan: LoadPlanFn | None = None) -> None:
    load_plan = load_plan or _load_plan
    plan_files = _plan_paths_from_changed(changed_files)
    if not plan_files:
        print("  PASS (plan-PR leg): no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        return

    added = _added_plan_paths(root)
    for plan_rel in plan_files:
        plan_path = root / plan_rel
        if not plan_path.exists():
            print(f"  SKIP (plan-PR leg): {plan_rel} (not present on disk -- deleted in this diff)")
            continue

        try:
            doc = load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(
                f"graduation-completeness (plan-PR leg) {plan_rel}: could not import scripts.roadmap.plan_document: {exc}"
            )
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP (plan-PR leg): {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        pre_deploy_steps = [s for s in doc.verification_plan if s.phase == "pre-deploy"]
        if not pre_deploy_steps:
            print(f"  PASS (plan-PR leg): {plan_rel} -- no pre-deploy step(s), nothing to enforce.")
            continue

        has_any_disposition = any(s.graduation is not None for s in doc.verification_plan)
        is_net_new = plan_rel in added
        if not is_net_new and not has_any_disposition:
            print(f"  SKIP (plan-PR leg): {plan_rel} (merely-modified, zero dispositions -- pre-field plan carve-out)")
            continue

        missing = [s.step for s in pre_deploy_steps if s.graduation is None]
        if missing:
            failed.append(
                f"graduation-completeness (plan-PR leg) {plan_rel}: pre-deploy step(s) {missing} lack a graduation disposition"
            )
        else:
            print(f"  PASS (plan-PR leg): {plan_rel} -- all {len(pre_deploy_steps)} pre-deploy step(s) carry a disposition.")


def _origin_main_reachable(root: Path) -> bool:
    result = _common.run(
        ["git", "rev-parse", "--verify", "-q", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    return result.returncode == 0


def _feat_commit_slugs(root: Path) -> list[str]:
    """Ordered, de-duplicated slugs from feat({slug}) commit subjects in origin/main..HEAD."""
    result = _common.run(
        ["git", "log", "origin/main..HEAD", "--format=%s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return []
    slugs: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.strip().splitlines():
        match = _FEAT_COMMIT_RE.match(line.strip())
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            slugs.append(match.group(1))
    return slugs


def _current_registry_entries(root: Path) -> list[dict]:
    registry_path = root / _REGISTRY_REL_PATH
    if not registry_path.exists():
        return []
    import yaml  # noqa: PLC0415

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("entries") or []
    return entries if isinstance(entries, list) else []


def _default_baseline_registry_entries(root: Path) -> list[dict]:
    """Registry entries at origin/main. A missing file/ref yields an empty (legitimate) baseline."""
    result = _common.run(
        ["git", "show", f"origin/main:{_REGISTRY_REL_PATH}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return []
    import yaml  # noqa: PLC0415

    try:
        data = yaml.safe_load(result.stdout)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("entries") or []
    return entries if isinstance(entries, list) else []


def _new_registry_rows(root: Path, baseline_registry_reader: BaselineRegistryReaderFn) -> list[dict]:
    current = _current_registry_entries(root)
    baseline_ids = {e.get("check_id") for e in baseline_registry_reader(root) if isinstance(e, dict)}
    return [e for e in current if isinstance(e, dict) and e.get("check_id") not in baseline_ids]


def _implement_pr_leg(
    root: Path,
    failed: list[str],
    load_plan: LoadPlanFn | None = None,
    baseline_registry_reader: BaselineRegistryReaderFn | None = None,
) -> None:
    load_plan = load_plan or _load_plan
    baseline_registry_reader = baseline_registry_reader or _default_baseline_registry_entries

    if not _origin_main_reachable(root):
        print("  SKIP (implement-PR leg): origin/main unreachable (advisory locally, authoritative in CI).")
        return

    slugs = _feat_commit_slugs(root)
    if not slugs:
        print("  PASS (implement-PR leg): no feat({slug}) commit(s) in this diff -- no-op.")
        return

    added_rows = _new_registry_rows(root, baseline_registry_reader)

    for slug in slugs:
        plan_rel = f"docs/plans/PLAN-{slug}.yaml"
        plan_path = root / plan_rel
        if not plan_path.exists():
            print(f"  SKIP (implement-PR leg): {plan_rel} not found for feat({slug}) commit -- unresolvable plan, advisory.")
            continue

        try:
            doc = load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(
                f"graduation-completeness (implement-PR leg) {plan_rel}: could not import scripts.roadmap.plan_document: {exc}"
            )
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP (implement-PR leg): {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        graduate_steps = [s for s in doc.verification_plan if s.graduation == "graduate"]
        if not graduate_steps:
            print(f"  PASS (implement-PR leg): {plan_rel} -- no graduate-disposition step(s).")
            continue

        for step in graduate_steps:
            cid = step.graduation_check_id
            match = next((row for row in added_rows if row.get("check_id") == cid and row.get("plan_slug") == doc.slug), None)
            if match is None:
                failed.append(
                    f"graduation-completeness (implement-PR leg) {plan_rel}: step {step.step} declared graduate "
                    f"(check_id={cid!r}) but no matching new-in-diff registry row found (plan_slug={doc.slug!r}) -- "
                    "add the registry row, or flip this step to waive with a reason if it proved un-graduatable"
                )
            else:
                print(f"  PASS (implement-PR leg): {plan_rel}:{step.step} -- registry row {cid!r} present.")


@registry.register("validate_graduation_completeness", owner="platform")
def validate_graduation_completeness(
    failed: list[str],
    changed_files: list[str] | None = None,
    root: Path | None = None,
    load_plan: LoadPlanFn | None = None,
    baseline_registry_reader: BaselineRegistryReaderFn | None = None,
) -> None:
    """Enforce the plan-declared VF-05 graduation obligation (T3.21) across both PR legs.

    changed_files / root / load_plan / baseline_registry_reader are test/dogfood injection
    seams -- default to _common.get_changed_files(), _common.ROOT, this module's own
    _load_plan, and a real `git show origin/main:...registry.yaml` reader respectively.
    """
    print("\n=== Verification graduation completeness (T3.21, VF-05 enforcement) ===")
    root = root if root is not None else _common.ROOT
    changed = changed_files if changed_files is not None else _common.get_changed_files()

    _plan_pr_leg(changed, root, failed, load_plan=load_plan)
    _implement_pr_leg(root, failed, load_plan=load_plan, baseline_registry_reader=baseline_registry_reader)
