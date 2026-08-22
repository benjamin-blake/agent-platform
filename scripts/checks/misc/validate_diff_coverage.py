"""Patch/diff (added-line) coverage classifier -- REPORT ONLY (PLAN-premerge-diff-coverage-gate).

Measurement half of the preventive for the coverage-gate escape class (rec-2970, rec-3043/3044,
rec-3147, rec-3211/3212, the 2026-08-21 canary red): validate_test_coverage enforces the
100%-per-file floor only in the full tier (full_after_lint), so every coverage regression is
structurally guaranteed to land on main before anyone sees it. This module intersects the
coverage artifact scripts/checks/_pytest_diff.py's ONE instrumented pytest invocation already
produces with the diff's added/modified executable lines and PRINTS the classification. It must
NEVER append to `failed` here -- the blocking flip is a follow-on plan, taken on this plan's
measured false-positive and DEFERRED rates (Decision 55: generate the justifying evidence before
committing to block, not in the same change).

Classification is COVERED / UNCOVERED / DEFERRED. DEFERRED is machine-derived at FILE granularity
via scripts.test_coverage_checker.map_source_to_test (line granularity is not derivable -- a
deferred file's covering test, by definition, did not run) and covers exactly three sources:
  (a) affected-set capped or deferred -- the covering test is absent from
      logs/debug/selection-manifest.json's `selected` list (capped residue or otherwise not run).
  (b) heavy-dependency exclusion -- the covering test is in _pytest_diff.py's deferral map
      (collect-only partition deferred list, or the reactive per-file heavy-dep probe).
  (d) never a selection candidate -- map_source_to_test returns None (includes the Decision 124
      carve-outs scripts/executor/** and scripts/ops_portal/**, deliberately NOT closed here).
A fourth shape -- lines covered only by a test the `-m "not integration"` marker excludes on
every run_pytest_diff invocation (class (c)) -- is a DECLARED KNOWN RESIDUAL, not a derived
DEFERRED class: map_source_to_test carries no marker information, so it lands in UNCOVERED like
any other genuinely-uncovered line. Suppressing it would hide the false positives this plan
exists to measure.

An absent logs/debug/selection-manifest.json is a declared skip (registry.skipped()) -- the
affected-set deferral state is unknowable, never "everything uncovered" and never a silent pass.
The same applies when _pytest_diff.py's own deferral map records one of its three no-artifact
states (empty affected set, all-files-deferred, the two-invocation reactive-fallback path) --
nothing was measurably examined this run, which is "could not examine", not "examined nothing".

Diff base is push_context_base(root) or "origin/main", threaded with the SAME root through every
git probe here (Decision 159 clause 1, rec-3166 amendment) -- a hardcoded origin/main...HEAD
self-compares post-merge and would make any future full-tier leg a permanent vacuous green (this
check is registered PRE-TIER-ONLY for unrelated reasons -- see scripts/checks/misc/_manifest.py --
but the base-threading discipline is followed regardless, for the `--replay-history`/direct-CLI
callers that do pass an explicit root).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional

from scripts.checks import _common, _pytest_diff, registry
from scripts.test_coverage_checker import map_source_to_test as _default_map_source_to_test

_SELECTION_MANIFEST_REL = "logs/debug/selection-manifest.json"

COVERED = "COVERED"
UNCOVERED = "UNCOVERED"
DEFERRED = "DEFERRED"

REASON_AFFECTED_SET = "affected_set_capped_or_deferred"
REASON_HEAVY_DEP = "heavy_dependency_exclusion"
REASON_UNMAPPED = "never_a_selection_candidate"

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_DIFF_GIT_RE = re.compile(r"^diff --git a/.+ b/(.+)$")


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _tracked_added_lines(root: Path, base: str) -> dict[str, set[int]]:
    """{repo-relative src/scripts .py path: {added/modified line numbers in the NEW file}} vs
    `base`, via ONE `git diff -U0` invocation (never one subprocess per changed file). Zero
    context lines means every body line in a hunk is a `+` or `-`; `-` lines never advance the
    new-file line counter, so only `+` lines are recorded. Covers tracked (A/M) paths only --
    `git diff <base>` is blind to untracked new files by construction (see
    added_line_numbers_by_file, which unions in the untracked leg)."""
    result = _common.run(
        ["git", "diff", "-U0", "--no-color", "--no-renames", base, "--", "src", "scripts"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return {}

    out: dict[str, set[int]] = {}
    current: Optional[str] = None
    next_new_line: Optional[int] = None
    for line in (result.stdout or "").splitlines():
        git_match = _DIFF_GIT_RE.match(line)
        if git_match:
            candidate = git_match.group(1)
            current = candidate if candidate.endswith(".py") else None
            if current is not None:
                out.setdefault(current, set())
            next_new_line = None
            continue
        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match and current is not None:
            next_new_line = int(hunk_match.group(1))
            continue
        if current is None or next_new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            out[current].add(next_new_line)
            next_new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
    return out


def _untracked_added_lines(root: Path) -> dict[str, set[int]]:
    """Every line of a brand-new, untracked src/scripts .py file counts as added (rec-2638
    precedent: `git diff <base>` is blind to untracked paths -- mirrors
    scripts.checks._common.get_status_aware_diff's separate `git ls-files --others` leg for the
    exact same reason). A local session's own newly-created files would otherwise vanish from
    this classifier's domain entirely -- a CI checkout only ever contains committed/staged
    files, so this leg is primarily a local-session correctness fix, like rec-2638 itself."""
    result = _common.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src", "scripts"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return {}
    out: dict[str, set[int]] = {}
    for path in (result.stdout or "").splitlines():
        path = path.strip()
        if not path.endswith(".py"):
            continue
        full = root / path
        try:
            n_lines = len(full.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        out[path] = set(range(1, n_lines + 1))
    return out


def added_line_numbers_by_file(root: Path, base: str) -> dict[str, set[int]]:
    """{repo-relative src/scripts .py path: {added/modified line numbers in the NEW file}} vs
    `base`, unioning the tracked (A/M, via `git diff -U0`) and untracked (new, via `git ls-files
    --others`) legs -- see _tracked_added_lines / _untracked_added_lines for why both are needed."""
    out = _tracked_added_lines(root, base)
    for path, lines in _untracked_added_lines(root).items():
        out.setdefault(path, set()).update(lines)
    return out


def _find_coverage_file_entry(coverage_files: dict, rel_path: str) -> Optional[dict]:
    """coverage.py JSON keys are not guaranteed to match `rel_path` byte-for-byte (absolute vs
    relative, backslash-normalised) -- mirrors coverage_baseline.py's own fuzzy match."""
    if rel_path in coverage_files:
        return coverage_files[rel_path]
    for key, entry in coverage_files.items():
        normalised = key.replace("\\", "/")
        if normalised == rel_path or normalised.endswith("/" + rel_path):
            return entry
    return None


def expand_covering_tests(test_path: Optional[Path], root: Path) -> frozenset[str]:
    """map_source_to_test() sometimes resolves to a test PACKAGE DIRECTORY (a declared
    concern-split monolith, or scripts/checks/_pytest_diff.py's own orchestration-internal
    special case -- see that function's docstring), not a single file. Expand a directory result
    to its individual test_*.py modules (mirrors scripts.checks.deps.affected_tests._mirror_map_
    channel's own expansion, so this classifier's "did the covering test run" question is asked
    at the SAME grain the affected-set derivation itself operates on) -- a bare directory string
    would never match any entry in logs/debug/selection-manifest.json's `selected` list of
    individual files, silently mis-deferring every line under a concern-split source file."""
    if test_path is None:
        return frozenset()
    if test_path.suffix == ".py":
        return frozenset({str(test_path.relative_to(root)).replace("\\", "/")}) if test_path.exists() else frozenset()
    if test_path.is_dir():
        return frozenset(
            str(f.relative_to(root)).replace("\\", "/")
            for f in sorted(test_path.rglob("test_*.py"))
            if "__pycache__" not in f.parts and f.is_file()
        )
    return frozenset()


def classify_file(
    rel_path: str,
    added_lines: set[int],
    *,
    coverage_files: dict,
    covering_tests: frozenset[str],
    selected: set[str],
    heavy_dep_deferred: set[str],
) -> tuple[dict[int, str], Optional[str]]:
    """Classify one file's added/modified lines. Returns ({line: status}, defer_reason_or_None).

    File-granularity DEFERRED gate, checked in order: no covering test at all -- either
    map_source_to_test returned None, or (for a concern-split directory result) the expansion
    yielded zero test modules (d) -> none of the covering tests ran this affected-set pass, i.e.
    every one is capped/deferred there (a) -> at least one covering test ran but every one that
    ran was itself heavy-dep-deferred by _pytest_diff.py (b). Only once none of those apply does
    a line's actual coverage.json executed/missing membership decide COVERED vs UNCOVERED (this
    is where the class-(c) residual necessarily lands -- coverage.json carries no marker
    information, so a line covered only by an integration-marked test reads identically to a
    genuinely uncovered one). A line absent from BOTH executed_lines and missing_lines is not an
    executable line per coverage.py (blank/comment/docstring) and is silently excluded from the
    returned mapping -- it is not part of the domain being classified.
    """
    if not covering_tests:
        return {ln: DEFERRED for ln in added_lines}, REASON_UNMAPPED
    ran = covering_tests & selected
    if not ran:
        return {ln: DEFERRED for ln in added_lines}, REASON_AFFECTED_SET
    if ran <= heavy_dep_deferred:
        return {ln: DEFERRED for ln in added_lines}, REASON_HEAVY_DEP

    file_cov = _find_coverage_file_entry(coverage_files, rel_path) or {}
    executed = set(file_cov.get("executed_lines") or [])
    missing = set(file_cov.get("missing_lines") or [])
    result: dict[int, str] = {}
    for ln in sorted(added_lines):
        if ln in executed:
            result[ln] = COVERED
        elif ln in missing:
            result[ln] = UNCOVERED
    return result, None


def _replay_history(n: int, *, root: Optional[Path] = None) -> int:
    """Coarse historical proxy measurement over the last `n` origin/main commits.

    True per-commit diff-coverage ground truth would require re-running the full historical test
    suite with coverage at each replayed commit -- session-budget-infeasible (VP step 3 fix_if).
    This instead reports, per src/scripts .py file touched in each of the last `n` commits,
    whether map_source_to_test resolves a covering test in the CURRENT tree -- a coarse existence
    proxy, not a coverage measurement -- and explicitly recommends the FORWARD ARM rather than
    fabricating a false-positive/DEFERRED rate from it (Decision 55: no fabricated rates).
    """
    r = root if root is not None else _common.ROOT
    result = _common.run(
        ["git", "log", "--first-parent", "-n", str(n), "--format=%H", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=r,
    )
    commits = [c.strip() for c in (result.stdout or "").splitlines() if c.strip()]
    if result.returncode != 0 or not commits:
        print("REPLAY-HISTORY: origin/main is not resolvable, or no commits were returned -- nothing to replay.")
        return 0

    touched_total = mapped_total = unmapped_total = 0
    for commit in commits:
        diff = _common.run(
            ["git", "diff", "--name-only", "--no-renames", f"{commit}^", commit, "--", "src", "scripts"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=r,
        )
        if diff.returncode != 0:
            continue
        for path in (diff.stdout or "").splitlines():
            path = path.strip()
            if not path.endswith(".py"):
                continue
            touched_total += 1
            if _default_map_source_to_test(r / path) is not None:
                mapped_total += 1
            else:
                unmapped_total += 1

    print(f"REPLAY-HISTORY (proxy measurement, {len(commits)} commit(s) from origin/main):")
    print(f"  touched src/scripts .py files: {touched_total}")
    print(f"  with a mapped covering test (current tree): {mapped_total}")
    print(f"  with NO mapped covering test (current tree -- Decision 124-style carve-outs etc.): {unmapped_total}")
    print(
        "  CAVEAT: this is a file-existence proxy, NOT per-line coverage ground truth -- producing "
        "that needs re-running the full historical suite with coverage at each replayed commit, "
        "which is session-budget-infeasible (VP step 3 fix_if).\n"
        "  RECOMMENDATION: take the FORWARD ARM -- land this check report-only and accumulate real "
        "per-PR measurements from the landing commit forward (>= 20 merged PRs); do not derive a "
        "false-positive/DEFERRED rate from this proxy."
    )
    return 0


def _current_diff_report(
    *,
    root: Path,
    base: str,
    map_source_to_test: Callable[[Path], Optional[Path]],
) -> None:
    manifest = _load_json(root / _SELECTION_MANIFEST_REL)
    if manifest is None:
        registry.skipped(f"{_SELECTION_MANIFEST_REL} absent -- affected-set selection state unknown this run.")
        print(f"SKIP: {_SELECTION_MANIFEST_REL} is absent -- cannot classify affected-set deferral (declared skip).")
        return

    deferral_doc = _load_json(root / _pytest_diff.DEFERRAL_MAP_REL) or {
        "state": _pytest_diff.STATE_EMPTY_AFFECTED_SET,
        "deferred": {},
    }
    state = deferral_doc.get("state", _pytest_diff.STATE_EMPTY_AFFECTED_SET)
    if state in _pytest_diff.NO_ARTIFACT_STATES:
        registry.skipped(f"pytest-diff produced no usable coverage artifact this run (state={state!r}).")
        print(f"SKIP: no usable diff-coverage artifact this run (state={state!r}) -- declared skip, not a pass.")
        return
    heavy_dep_deferred: set[str] = set(deferral_doc.get("deferred") or {})

    coverage_doc = _load_json(root / _pytest_diff.COVERAGE_ARTIFACT_REL) or {}
    coverage_files: dict = coverage_doc.get("files", {})
    selected: set[str] = set(manifest.get("selected") or [])

    added = added_line_numbers_by_file(root, base)
    covered = uncovered = deferred = 0
    deferred_reasons: dict[str, int] = {}
    uncovered_lines: list[str] = []

    for rel_path in sorted(added):
        lines = added[rel_path]
        if not lines:
            continue
        test_path = map_source_to_test(root / rel_path)
        covering_tests = expand_covering_tests(test_path, root)
        line_status, reason = classify_file(
            rel_path,
            lines,
            coverage_files=coverage_files,
            covering_tests=covering_tests,
            selected=selected,
            heavy_dep_deferred=heavy_dep_deferred,
        )
        for status in line_status.values():
            if status == COVERED:
                covered += 1
            elif status == UNCOVERED:
                uncovered += 1
        if reason is not None:
            deferred += len(line_status)
            deferred_reasons[reason] = deferred_reasons.get(reason, 0) + len(line_status)
        uncovered_lines.extend(f"{rel_path}:{ln}" for ln, status in sorted(line_status.items()) if status == UNCOVERED)

    total = covered + uncovered + deferred
    print("\n=== Diff (patch) coverage -- REPORT ONLY (PLAN-premerge-diff-coverage-gate) ===")
    print(f"  base: {base}")
    print(f"  COVERED={covered} UNCOVERED={uncovered} DEFERRED={deferred} (total added executable lines: {total})")
    if deferred_reasons:
        print("  DEFERRED breakdown:")
        for reason in sorted(deferred_reasons):
            print(f"    {reason}: {deferred_reasons[reason]}")
    if uncovered_lines:
        print("  UNCOVERED lines:")
        for entry in uncovered_lines:
            print(f"    {entry}")
    if total:
        ratio = deferred / total
        print(f"  DEFERRED-to-changed-line ratio: {ratio:.1%}")
        if ratio > 0.5:
            print(
                "  FINDING: DEFERRED ratio exceeds 50% -- a check that defers most of what it sees "
                "would be vacuous if made blocking."
            )
        registry.examined(total, unit="lines")
    else:
        registry.examined(0, unit="lines")


@registry.register("validate_diff_coverage", owner="platform")
def validate_diff_coverage(
    failed: list[str],
    *,
    root: Path | None = None,
    base: str | None = None,
    map_source_to_test: Callable[[Path], Optional[Path]] | None = None,
) -> None:
    """REPORT-ONLY diff-line coverage classifier -- NEVER appends to `failed`.

    `root`/`base`/`map_source_to_test` are test/dogfood injection seams (mirrors
    scripts/checks/verification/validate_vp_replay.py's own root/changed_files seam); production
    dispatch calls this with only `failed`, defaulting root to _common.ROOT, base to
    push_context_base(root) or "origin/main", and map_source_to_test to the real
    scripts.test_coverage_checker.map_source_to_test.
    """
    del failed  # never appended to -- report-only by construction (this plan's central constraint)
    root = root if root is not None else _common.ROOT
    base = base if base is not None else (_common.push_context_base(root) or "origin/main")
    m = map_source_to_test if map_source_to_test is not None else _default_map_source_to_test
    _current_diff_report(root=root, base=base, map_source_to_test=m)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diff (patch) coverage classifier -- REPORT ONLY, never fails (PLAN-premerge-diff-coverage-gate)."
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Explicit no-op: this check is always report-only regardless of this flag.",
    )
    parser.add_argument(
        "--replay-history",
        type=int,
        default=None,
        metavar="N",
        help="Coarse historical proxy measurement over the last N origin/main commits (see the "
        "owning plan's VP step 3 fix_if; recommends the forward arm rather than a fabricated rate).",
    )
    args = parser.parse_args(argv)

    if args.replay_history is not None:
        return _replay_history(args.replay_history)

    failed: list[str] = []
    validate_diff_coverage(failed)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
