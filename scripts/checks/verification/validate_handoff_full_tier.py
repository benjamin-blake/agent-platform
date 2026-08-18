"""Handoff full-tier verification-plan obligation gate (rec-2965 remediation, Decision 163).

PR #836's plan declared `handoff_policy.full_validation_required_before_commit: true` --
mandatory metadata on every schema_version-3 IMPLEMENTATION plan (plan_document.py) -- while its
verification_plan ran only the fast (--pre) tier. Nothing checked that the plan's own executable
steps actually invoked the full tier, so the declared obligation was silently unenforced: main
went red on the next push touching the ratification guard (rec-2965), a coverage gap the fast
tier's diff-scoped coverage check does not catch on an already-red file.

This check closes that gap. For every diff-added or diff-modified docs/plans/PLAN-*.yaml that
declares handoff_policy (equivalently: every v3 IMPLEMENTATION plan, since the field is
Literal[True] and required -- there is no "declares but sets false"), at least one
verification_plan step must invoke the full tier.

THE MATCHER (pinned; the sole authority for this check's classification, per
docs/plans/PLAN-coverage-gate-handoff-integrity.yaml's execution_steps): split a step's raw
`command` string on the shell separators '&&', '||', ';' and newline, then treat a segment as a
full-tier invocation iff it matches the regex `-m\\s+scripts\\.validate(?![\\w.])` (module
entry-point form, not preceded by anything requiring a boundary check -- the lookahead alone
blocks a scripts.validate_foo submodule from false-matching) AND the segment does not contain the
substring "--pre". This rejects a bare `import scripts.validate` inside a python -c body (no `-m`
entry-point form present) and a `scripts.validate --pre`-only command (chained or standalone),
while accepting a chained `... --pre && ... scripts.validate` command on its second segment.

Deliberately no advisory-SKIP leg: this check has no git-log-dependent leg (unlike
validate_graduation_completeness's implement-PR leg) -- _common.get_changed_files() already
degrades to a `git diff HEAD` fallback, so a silent whole-check no-op path would reintroduce the
exact declared-vs-executed failure mode this check exists to remove. A plan present on disk but
absent from the diff is never evaluated (grandfathered stock); a diff containing no plan is a
clean no-op (flow is zero-tolerance, stock is not retroactively gated).

Injection seams (changed_files, root, load_plan) mirror validate_graduation_completeness's
signature style for testability without real git state.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from scripts.checks import _common, registry

LoadPlanFn = Callable[[str, Path], Any]

_SHELL_SEPARATOR_RE = re.compile(r"&&|\|\||;|\n")
_FULL_TIER_RE = re.compile(r"-m\s+scripts\.validate(?![\w.])")


def _is_full_tier_segment(segment: str) -> bool:
    return bool(_FULL_TIER_RE.search(segment)) and "--pre" not in segment


def _has_full_tier_step(doc) -> bool:
    return any(
        _is_full_tier_segment(segment) for step in doc.verification_plan for segment in _SHELL_SEPARATOR_RE.split(step.command)
    )


@registry.register("validate_handoff_full_tier", owner="platform")
def validate_handoff_full_tier(
    failed: list[str],
    changed_files: list[str] | None = None,
    root: Path | None = None,
    load_plan: LoadPlanFn | None = None,
) -> None:
    """Diff-added/modified plans declaring handoff_policy must carry a full-tier VP step.

    changed_files / root / load_plan are test/dogfood injection seams -- default to
    _common.get_changed_files(root), _common.ROOT, and _common.load_plan respectively.

    Composes exactly ONE terminal Decision 170 declaration on each of its two reachable exit
    paths: an empty diff-present plan set declares `examined(0, unit="declared_plans")`
    (empty domain, never skipped -- this check has no git-log-dependent leg to defer); the
    loop fall-through declares `examined(len(plan_files), unit="declared_plans")`.
    """
    print("\n=== Handoff full-tier verification-plan obligation (rec-2965 / Decision 163) ===")
    root = root if root is not None else _common.ROOT
    load_plan_fn = load_plan or _common.load_plan
    changed = changed_files if changed_files is not None else _common.get_changed_files(root)

    plan_files = _common.plan_paths_from_changed(changed)
    if not plan_files:
        print("  PASS: no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        registry.examined(0, unit="declared_plans")
        return

    for plan_rel in plan_files:
        plan_path = root / plan_rel
        if not plan_path.exists():
            print(f"  SKIP: {plan_rel} (not present on disk -- deleted in this diff)")
            continue

        try:
            doc = load_plan_fn(plan_rel, root)
        except ImportError as exc:
            failed.append(f"handoff-full-tier {plan_rel}: could not import scripts.roadmap.plan_document: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        if doc.handoff_policy is None:
            print(f"  PASS: {plan_rel} -- no handoff_policy declared, not subject to this obligation.")
            continue

        if _has_full_tier_step(doc):
            print(f"  PASS: {plan_rel} -- carries a full-tier `-m scripts.validate` verification_plan step.")
        else:
            message = (
                f"handoff-full-tier {plan_rel}: declares handoff_policy.full_validation_required_before_commit but "
                "no verification_plan step invokes the full tier (`-m scripts.validate` without --pre)"
            )
            print(f"  FAIL: {message}")
            failed.append(message)

    registry.examined(len(plan_files), unit="declared_plans")
