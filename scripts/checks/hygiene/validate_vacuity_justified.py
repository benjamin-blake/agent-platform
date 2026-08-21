"""validate_vacuity_justified -- narrow, fail-closed vacuity alarm for validate_test_coverage
(rec-3163 / PLAN-probe-discrimination-vacuity-alarm).

Closes the second half of the coverage-gate escape class alongside acceptance_lint.py's
discrimination arm: validate_test_coverage declares examined(len(get_changed_source_files())),
so vacuity is exactly "that call returned empty". This check independently re-derives the
changed-source set via a GENUINELY BASE-FREE oracle (`git diff --name-only HEAD~1 HEAD`) and
fails when the oracle disagrees with the checker -- oracle non-empty, checker empty.

Why base-free, not _common.get_changed_files(): that helper shares
_common.push_context_base()/origin/main with test_coverage_checker.get_changed_source_files()
(scripts/checks/_common.py:102-119 vs scripts/test_coverage_checker.py:466-509) and both degrade
identically to an empty set on a shallow clone with origin/main unresolvable -- an alarm built on
that pairing would pass vacuously in exactly the scenario it exists to catch. HEAD~1..HEAD touches
no base ref. This is a real, accepted trade: it can miss a defect whose source change landed in an
earlier commit, and its discriminating power is weak on the post-merge main run (where the
checker's own base coincides with HEAD~1 almost by construction) -- see
docs/plans/PLAN-probe-discrimination-vacuity-alarm.yaml Context for the full accounting.

Deliberately NARROW (Decision 170 divergence, a scope-narrowing substitute for the general
fail-closed vacuity enforcement Decision 170 declined -- see the plan's Context section for the
ratified reasoning): covers validate_test_coverage alone via the frozen _COVERED_CHECKS roster.
This is NOT a general vacuity gate and must never grow beyond a single-check frozen roster without
a fresh Decision.

Fail-closed accounting (Decision 170 clauses 3-4, surface 7): every reachable exit path declares
registry.examined(n, unit="source_files") or registry.skipped(reason) -- an uncomputable oracle is
skipped(), never a silent pass. Filesystem/subprocess-only (Decision 153 fast-tier budget note:
this check itself is full-tier only, see _manifest.py, so the budget is advisory here).
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks import _common, registry

_COVERED_CHECKS: frozenset[str] = frozenset({"validate_test_coverage"})
_EXCLUDED_BASENAMES: frozenset[str] = frozenset({"__init__.py", "conftest.py"})
_ELIGIBLE_TOP_LEVEL: frozenset[str] = frozenset({"src", "scripts"})


def _base_free_oracle(root: Path) -> tuple[list[str] | None, str | None]:
    """Return (changed_source_files, skip_reason) -- exactly one is None.

    `git diff --name-only HEAD~1 HEAD` touches no base ref (unlike origin/main-anchored
    derivations). Filters EXACTLY like test_coverage_checker.get_changed_source_files(): .py
    only, under src/ or scripts/, excluding __init__.py/conftest.py, and dropping paths that no
    longer exist on disk -- a delete-only commit must never fire a false alarm.
    """
    result = _common.run(
        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return None, "HEAD~1 unavailable (git diff --name-only HEAD~1 HEAD failed -- shallow or single-commit tree)"

    changed: list[str] = []
    for line in result.stdout.strip().splitlines():
        rel = line.strip()
        if not rel or not rel.endswith(".py"):
            continue
        p = Path(rel)
        if p.name in _EXCLUDED_BASENAMES:
            continue
        if not p.parts or p.parts[0] not in _ELIGIBLE_TOP_LEVEL:
            continue
        if not (root / rel).exists():
            continue
        changed.append(rel)
    return changed, None


@registry.register("validate_vacuity_justified", owner="platform")
def validate_vacuity_justified(
    failed: list[str],
    root: Path | None = None,
    checker_files: list[str] | None = None,
) -> None:
    """Fail when validate_test_coverage's changed-source derivation is empty while the base-free
    oracle is non-empty; pass (with an honest examined() count) on agreement or a legitimately
    vacuous test-only diff; skip when the oracle itself cannot be computed.

    `root` / `checker_files` are test/dogfood injection seams. `root` scopes the base-free
    oracle's git probe (defaults to _common.ROOT). `checker_files` is forwarded verbatim to
    test_coverage_checker.get_changed_source_files(files=...) -- that function's own public
    injection seam, never mocked here (asserting on the fixture rather than the adjudicated
    derivation would defeat the point of this check).
    """
    print(f"\n=== Vacuity-justified alarm ({sorted(_COVERED_CHECKS)} only, rec-3163) ===")
    root = root if root is not None else _common.ROOT

    oracle_files, skip_reason = _base_free_oracle(root)
    if skip_reason is not None:
        print(f"  SKIP: {skip_reason} -- absence of evidence is recorded as skipped, never as green.")
        registry.skipped(skip_reason)
        return
    assert oracle_files is not None  # _base_free_oracle: exactly one of the pair is None

    from scripts.test_coverage_checker import get_changed_source_files  # noqa: PLC0415

    checker_paths = get_changed_source_files(files=checker_files)

    oracle_non_empty = bool(oracle_files)
    checker_non_empty = bool(checker_paths)

    if oracle_non_empty and not checker_non_empty:
        failed.append(
            "Vacuity-justified alarm: validate_test_coverage's changed-source derivation is "
            f"EMPTY but the base-free oracle (git diff --name-only HEAD~1 HEAD) found "
            f"{len(oracle_files)} coverage-eligible source file(s): {sorted(oracle_files)}. This "
            "is the escape class rec-2970/rec-3043/rec-3044/rec-3147/rec-3211/rec-3212 all share "
            "-- a coverage floor that passes without enforcing."
        )
        registry.examined(len(oracle_files), unit="source_files")
        return

    if checker_non_empty:
        n = len(checker_paths)
        print(f"  PASS: checker examined {n} source file(s); no disagreement with the base-free oracle.")
    else:
        n = 0
        print("  PASS: both the checker and the base-free oracle see an empty domain -- legitimately vacuous.")

    registry.examined(n, unit="source_files")
