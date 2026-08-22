"""Fast-tier heavy-dependency test deferral for the --pre pytest-diff step (rec-2485, Decision
104; extracted from scripts/checks/_scaffolding.py under Decision 128's decompose-by-default SLOC
rule -- this concern (partition/probe/re-run around requirements-fast.txt's heavy-dep exclusions)
is fully self-contained and had no coupling to the rest of that file's scaffolding steps).
scripts/checks/_scaffolding.py re-exports this module's public surface for facade back-compat
(`from scripts.checks._scaffolding import run_pytest_diff` etc keep resolving), mirroring how that
file already re-exports scripts/checks/_terraform.py and _budget_recs.py.

requirements-fast.txt (the pr-validate CI job) deliberately omits heavy wheels
(torch/pandas/numpy/pyarrow/duckdb/etc, ~3GB dominant per .github/workflows/ci.yml:49-59).
A handful of test files import one of these at module scope, so they can never be
collected under the fast tier -- that is a structural, not a regression, signal (Google
TAP / Bazel precedent: SKIPPED-dep-unavailable is distinct from FAILED). The classifier
below positively identifies that ONE shape and defers it to main-validate (full tier,
post-merge); every other collection error or test failure stays hard-red (fail-closed).
"""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import re
from pathlib import Path

from scripts.checks import _common

# Parallelism + per-test timeout for both --pre pytest-diff invocations (primary and reactive
# survivor re-run). Cap (60s) is comfortably above the slowest legitimate unit (~3s) and well
# under the 300s fast-tier budget.
#
# rec-2653: a fixed integer --randomly-seed overrides pyproject.toml's addopts
# "--randomly-seed=last" for these xdist-parallel invocations only, so every -n auto worker
# resolves the same collection order on a cold .pytest_cache. "last" resolves inconsistently
# across workers on GH-hosted runners, producing "Different tests were collected between gw1
# and gwN". pyproject.toml itself is untouched (local-dev re-run ergonomics), and -n auto is
# untouched (worker count is not the defect).
_PYTEST_RANDOMLY_SEED = 20260710
_PYTEST_FLAGS = [
    "-n",
    "auto",
    "--timeout",
    "60",
    "--timeout-method=thread",
    f"--randomly-seed={_PYTEST_RANDOMLY_SEED}",
]

# Concurrency cap for the reactive per-file heavy-dep probe loop (_runtime_heavy_dep_defer_reason).
# Each probe is its own isolated pytest subprocess (see that function's docstring for why isolation
# matters) -- running several concurrently is safe (separate processes, no shared state) and turns
# a serial chain of per-process startup overheads into a bounded number of parallel batches.
_REACTIVE_PROBE_MAX_WORKERS = 8

# PLAN-premerge-diff-coverage-gate: coverage artifact + machine-readable deferral map emitted by
# the ONE primary invocation below, consumed by scripts/checks/misc/validate_diff_coverage.py.
# Both paths are gitignored (logs/debug/ -- Decision 55 debug-artifact convention, mirrors
# scripts/checks/deps/affected_tests.py's selection-manifest.json). --cov-fail-under=0 overrides
# pyproject.toml's fail_under=37 for THIS invocation only (a CLI --cov flag overrides the config
# [tool.coverage.run] source, verified live) -- an affected-set run measuring well under 37% must
# never redden the fast tier on a coverage floor that was designed for the full suite.
COVERAGE_ARTIFACT_REL = "logs/debug/diff-coverage.json"
DEFERRAL_MAP_REL = "logs/debug/diff-coverage-deferrals.json"

# The reactive survivor re-run is deliberately NOT traced (no --cov flag at all -- pytest-cov only
# activates coverage when at least one --cov flag is present, and pyproject.toml's addopts carries
# none): only the ONE primary invocation is ever traced, per this plan's declared green-path levers.
_COV_FLAGS = ["--cov=src", "--cov=scripts", "--cov-fail-under=0", f"--cov-report=json:{COVERAGE_ARTIFACT_REL}"]

# Deferral-map state vocabulary: STATE_OK means the coverage artifact reflects the single primary
# invocation's real measurement (whether or not that invocation's tests all passed -- coverage.py
# records line execution independent of assertion outcomes). The other three are the "no usable
# artifact" states this plan's classifier must recognise rather than silently misread:
#   - EMPTY_AFFECTED_SET: changed_tests was empty -- no invocation was ever attempted.
#   - ALL_DEFERRED: every changed test file deferred at collect-only (or reactive-probe) time --
#     no primary invocation ran, so no coverage was ever collected.
#   - TWO_INVOCATION_FAILURE: the primary invocation failed on an excluded-heavy-dep signature and
#     a SECOND real invocation ran on the survivor subset. The primary run's coverage.json still
#     exists on disk, but it measured a run that included files later found to need deferral (their
#     partial, crash-truncated execution is not a reliable line-coverage signal) and does not
#     reflect the actually-validated survivor set -- so it is not a usable diff-coverage snapshot.
STATE_OK = "ok"
STATE_EMPTY_AFFECTED_SET = "empty_affected_set"
STATE_ALL_DEFERRED = "all_deferred"
STATE_TWO_INVOCATION_FAILURE = "two_invocation_failure"
NO_ARTIFACT_STATES = frozenset({STATE_EMPTY_AFFECTED_SET, STATE_ALL_DEFERRED, STATE_TWO_INVOCATION_FAILURE})


def _write_deferral_map(state: str, file_reasons: dict[str, str], *, root: Path = _common.ROOT) -> None:
    """Best-effort write of {"state": ..., "deferred": {test_file: reason}} (Decision 55: LOUD
    skip on OSError, never raising -- mirrors scripts/checks/deps/affected_tests.py's
    emit_manifest write style). `state` is one of the STATE_* constants above; `file_reasons`
    covers BOTH the collect-only partition's deferred list and the reactive heavy-dep probe's
    finds (previously printed and discarded, per this plan's acceptance criteria)."""
    path = root / DEFERRAL_MAP_REL
    payload = {"state": state, "deferred": file_reasons}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        print(f"Diff-coverage deferral map: local write to {path} failed -- loud skip (Decision 55): {exc!r}")


# Curated dist-name -> import-name aliases for names that differ; default is
# name.lower().replace("-", "_").
_DIST_TO_IMPORT_ALIASES: dict[str, str] = {
    "scikit-learn": "sklearn",
    "psycopg2-binary": "psycopg2",
    "beautifulsoup4": "bs4",
    "python-ulid": "ulid",
}

_NO_MODULE_NAMED_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")


def _parse_requirement_dist_names(path: Path) -> set[str]:
    """Parse a requirements file into bare distribution names.

    Strips comments, extras (`[...]`), environment markers (after `;`), and version specifiers.
    """
    names: set[str] = set()
    if not path.exists():
        return names
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        line = re.sub(r"\[[^\]]*\]", "", line)
        line = line.split(";", 1)[0].strip()
        name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names


def _dist_to_import_name(dist_name: str) -> str:
    return _DIST_TO_IMPORT_ALIASES.get(dist_name, dist_name.lower().replace("-", "_"))


def _excluded_heavy_import_names() -> set[str]:
    """Import names deliberately excluded from the fast tier.

    Derived at runtime as (requirements.txt distributions) - (requirements-fast.txt
    distributions), no hard-coded dep list (rec-2485 acceptance).
    """
    full = _parse_requirement_dist_names(_common.ROOT / "requirements.txt")
    fast = _parse_requirement_dist_names(_common.ROOT / "requirements-fast.txt")
    return {_dist_to_import_name(dist) for dist in full - fast}


def _excluded_and_absent(missing: str | None, excluded: set[str]) -> str | None:
    """Return `missing`'s top-level module name if it's a deliberately-excluded, genuinely-absent
    heavy dependency (both conditions checked); otherwise None."""
    if not missing:
        return None
    top_level = missing.split(".")[0]
    if top_level in excluded and importlib.util.find_spec(top_level) is None:
        return top_level
    return None


def _runtime_heavy_dep_defer_reason(test_file: str, excluded: set[str]) -> str | None:
    """Run a single collectible test file for real, in isolation; return the excluded heavy-dep
    name if ANY failure in it traces to a genuinely-absent heavy dependency.

    Catches the shape `--collect-only` cannot see: a dependency imported lazily inside a test or
    the production code it exercises (function scope, not module scope), which only raises
    ModuleNotFoundError when the specific test actually runs. Isolated (one file, one process)
    so a mid-run ModuleNotFoundError in one test cannot leave shared fixture/mock state that
    manifests as unrelated-looking failures in later tests within the same file -- deferring
    the whole file on ANY such hit (not requiring every failure to match) is what makes that
    safe: once the file is known to need a missing dependency, downstream failures in the same
    isolated run aren't independently meaningful.
    """
    result = _common.run(
        [_common.PYTHON, "-m", "pytest", test_file, "-m", "not integration", "-q"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode == 0:
        return None
    combined = (result.stdout or "") + (result.stderr or "")
    for match in _NO_MODULE_NAMED_RE.findall(combined):
        found = _excluded_and_absent(match, excluded)
        if found:
            return found
    return None


# Decision affected-set-selection: pytest's own `ERROR collecting <path>` block header
# (verified empirically -- one header per uncollectable file, in argv order, regardless of
# argv position) and the `-rs` short-summary `SKIPPED [N] <path>:<line>: <reason>` line (a
# graceful module-level pytest.importorskip, not a hard collection error). Both carry the file
# path verbatim as passed on argv, so a straight substring/suffix match resolves it back to its
# entry in changed_tests.
_ERROR_COLLECTING_RE = re.compile(r"ERROR collecting (\S+)")
_SKIPPED_LINE_RE = re.compile(r"^SKIPPED\s+\[\d+\]\s+(\S+):\d+:\s*(.+)$", re.MULTILINE)
# VTS-04 M1: a pytest section-separator line (e.g. the "short test summary info" banner) --
# bounds the LAST ERROR-collecting block so it stops there instead of running to end-of-output.
_SECTION_SEPARATOR_RE = re.compile(r"^=+.+=+$", re.MULTILINE)
# A pytest short-summary FAILED/ERROR line (e.g. "FAILED tests/foo.py::TestX::test_y - Module...").
# Used to attribute the combined run's failures back to individual files (see
# _attribute_failed_test_files below) so the reactive heavy-dep probe targets only the files that
# actually failed, not every runnable file.
_FAILED_SUMMARY_LINE_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def _match_changed_test_path(file_token: str, changed_tests: list[str], *, repo_root: Path = _common.ROOT) -> str | None:
    """Resolve a path token echoed by pytest (relative-as-passed, or occasionally an
    absolute/rootdir-relative variant) back to its exact entry in changed_tests."""
    normalized = file_token.replace("\\", "/")
    for f in changed_tests:
        if normalized == f or normalized.endswith("/" + f):
            return f
        target = repo_root / f
        if not target.is_dir():
            continue
        candidate = repo_root / normalized
        try:
            candidate.relative_to(target)
        except ValueError:
            continue
        if candidate.is_file() and candidate.name.startswith("test_") and candidate.suffix == ".py":
            return candidate.relative_to(repo_root).as_posix()
    return None


def _expand_directory_test_targets(targets: list[str]) -> list[str]:
    """Defensively normalize any legacy directory target to individual test modules."""
    expanded: list[str] = []
    for target in targets:
        path = _common.ROOT / target
        if not path.is_dir():
            expanded.append(target)
            continue
        expanded.extend(
            test_file.relative_to(_common.ROOT).as_posix()
            for test_file in sorted(path.rglob("test_*.py"))
            if "__pycache__" not in test_file.parts and test_file.is_file()
        )
    return list(dict.fromkeys(expanded))


def _attribute_batched_collect_errors(combined: str, changed_tests: list[str], excluded: set[str]) -> dict[str, str]:
    """Parse ONE combined `--collect-only -rs` invocation's stdout+stderr and attribute each
    per-file signal -- a hard collection-ERROR block, or a graceful SKIPPED line -- to its OWN
    file, so a mixed batch (one uncollectable file among several runnable ones) defers exactly
    the uncollectable file(s), never the whole batch.

    VTS-04 M1: the LAST header's block is additionally bounded at the first pytest section
    separator (e.g. "=== short test summary info ===") that follows it, not just the next
    header/end-of-string -- otherwise it swallows the trailing summary section, which echoes
    EVERY errored file's own "No module named" message, and `matches[-1]` (the last match in an
    unbounded block) can mis-attribute an earlier file's heavy-dep message to the last file even
    when the last file's own error is a genuine, unrelated bug."""
    deferred: dict[str, str] = {}

    headers = list(_ERROR_COLLECTING_RE.finditer(combined))
    for i, header in enumerate(headers):
        file_token = header.group(1)
        next_start = headers[i + 1].start() if i + 1 < len(headers) else len(combined)
        sep_match = _SECTION_SEPARATOR_RE.search(combined, header.end(), next_start)
        block_end = sep_match.start() if sep_match else next_start
        block = combined[header.end() : block_end]
        matches = _NO_MODULE_NAMED_RE.findall(block)
        missing = _excluded_and_absent(matches[-1], excluded) if matches else None
        matched_file = _match_changed_test_path(file_token, changed_tests)
        if matched_file and missing:
            deferred[matched_file] = missing

    for skip_match in _SKIPPED_LINE_RE.finditer(combined):
        file_token, reason = skip_match.group(1), skip_match.group(2)
        matches = _NO_MODULE_NAMED_RE.findall(reason)
        missing = _excluded_and_absent(matches[-1], excluded) if matches else None
        matched_file = _match_changed_test_path(file_token, changed_tests)
        if matched_file and missing and matched_file not in deferred:
            deferred[matched_file] = missing

    return deferred


def partition_changed_tests_by_collectability(changed_tests: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Partition changed test files into (runnable, deferred) via a SINGLE batched
    `--collect-only` invocation covering every changed test file at once (Decision
    affected-set-selection, ~30x fewer collect-only subprocess spawns than the prior one-call-
    per-file loop; net-funds the affected-set derivation's added cost inside the 5-min budget).

    A file defers when its OWN per-file signal (a `ERROR collecting <path>` block, or a `-rs`
    SKIPPED line) root-causes to a deliberately-excluded heavy dependency (in requirements.txt,
    not requirements-fast.txt) that is genuinely absent (`importlib.util.find_spec` is None) --
    module-scope, visible without running any test body. Every other shape -- a real test
    failure, a non-heavy collection error, or a file with no signal at all -- routes to
    `runnable`, so the subsequent real pytest run reproduces and reddens the genuine failure
    with full diagnostics (fail-closed). Attribution is PER FILE (see
    _attribute_batched_collect_errors): a mixed batch of one uncollectable file and several
    runnable ones defers only the uncollectable one -- never a whole-batch mis-defer on one bad
    file (a near-silent under-run this batching would otherwise risk).

    `-rs` (show skip reasons) is required here: a module-level `pytest.importorskip("duckdb")`
    guard (e.g. tests/test_ops_data_portal.py) makes `--collect-only` exit 5 (NO_TESTS_COLLECTED)
    with "collected 0 items / 1 skipped" -- a graceful skip, not a collection error -- and without
    `-rs` the "could not import 'duckdb': No module named 'duckdb'" reason text never appears in
    stdout, so this genuinely-absent-heavy-dep shape is invisible to the regex below and the file
    is misrouted to `runnable`. A self-skipping file alongside at least one good file in the SAME
    batch exits 0 overall (verified empirically) -- so per-file SKIPPED-line attribution runs
    UNCONDITIONALLY (not gated on a nonzero returncode) to still catch it.

    A heavy dependency imported LAZILY (function scope, not module scope) is invisible to
    `--collect-only` and is no longer proactively probed here -- `run_pytest_diff` catches that
    shape reactively, only if and after the combined run fails (see `_runtime_heavy_dep_defer_reason`).
    """
    if not changed_tests:
        return [], []
    excluded = _excluded_heavy_import_names()
    result = _common.run(
        [_common.PYTHON, "-m", "pytest", "--collect-only", "-q", "-rs", *changed_tests, "-m", "not integration"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    deferred_map = _attribute_batched_collect_errors(combined, changed_tests, excluded)
    runnable = [f for f in changed_tests if f not in deferred_map]
    deferred = [(f, deferred_map[f]) for f in changed_tests if f in deferred_map]
    return runnable, deferred


def _print_deferred_warning(test_file: str, missing_dep: str) -> None:
    print(
        f"\n=== DEFERRED TO FULL TIER (main-validate) ===\n"
        f"{test_file}: cannot run under the fast tier -- dependency '{missing_dep}' is "
        "deliberately excluded from requirements-fast.txt. main-validate (full tier) runs "
        "this file post-merge; a genuine failure there files a source=ci_rca critical rec."
    )


def _reactive_heavy_dep_signature(combined_output: str, excluded: set[str]) -> str | None:
    """Return the first deliberately-excluded, genuinely-absent heavy-dep name whose ModuleNotFoundError
    signature appears in `combined_output`, or None if no such signature is present."""
    for match in _NO_MODULE_NAMED_RE.findall(combined_output):
        found = _excluded_and_absent(match, excluded)
        if found:
            return found
    return None


def _attribute_failed_test_files(combined: str, runnable: list[str], *, repo_root: Path = _common.ROOT) -> set[str] | None:
    """Extract the subset of `runnable` implicated by the combined run's FAILED/ERROR short-summary
    lines, so the reactive heavy-dep probe below targets only files that actually failed instead of
    isolated-re-running every runnable file (rec-2871-adjacent fast-tier budget-breach fix: probing
    the whole runnable set serially -- one pytest subprocess start per file -- dominated pytest_diff's
    wall-clock on a diff whose affected-set widened past a few dozen files).

    Returns None (never an empty set) when no FAILED/ERROR line resolves to an entry in `runnable` --
    the caller falls back to probing the whole runnable set, fail-safe: this function only NARROWS
    the probe target, it never causes a file that needs checking to be silently skipped.
    """
    files: set[str] = set()
    for match in _FAILED_SUMMARY_LINE_RE.finditer(combined):
        token = match.group(1).split("::", 1)[0]
        matched = _match_changed_test_path(token, runnable, repo_root=repo_root)
        if matched:
            files.add(matched)
    return files or None


def run_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
    """Orchestrate the --pre pytest-diff step: partition, warn, run once, and reactively fall
    back only on failure (Decision 104 / rec-2485; single-execution reshape).

    Common case: `--collect-only` partitions changed_tests into (runnable, deferred); a loud
    un-swallowable warning is printed per deferred file; the runnable subset is run through pytest
    EXACTLY ONCE. If that run passes (or every file deferred), the gate is done -- no proactive
    per-file isolated probe.

    Only on a non-zero return does this reactively check whether the failure signature names a
    deliberately-excluded, genuinely-absent heavy dependency (a lazy, function-scope import
    invisible to `--collect-only`, e.g. the rec-2572..2576 test_ops_writer.py shape). If so, it
    falls back to per-file classification via `_runtime_heavy_dep_defer_reason` -- targeted at only
    the files `_attribute_failed_test_files` implicates in the combined run's FAILED/ERROR lines
    (falling back to the whole runnable set if attribution finds nothing, fail-safe), run
    CONCURRENTLY (each is its own isolated subprocess, so parallelizing is safe) up to
    `_REACTIVE_PROBE_MAX_WORKERS` at a time. Prints DEFERRED warnings for files that resolve to that
    shape, and re-runs the survivors once (reddening only on a survivor failure). Any other failure
    shape reddens immediately (fail-closed) -- no reactive re-run is spent chasing a genuine test
    failure.
    """
    if not changed_tests:
        _write_deferral_map(STATE_EMPTY_AFFECTED_SET, {})
        return
    runnable, deferred = partition_changed_tests_by_collectability(changed_tests)
    runnable = _expand_directory_test_targets(runnable)
    file_reasons: dict[str, str] = dict(deferred)
    for test_file, missing_dep in deferred:
        _print_deferred_warning(test_file, missing_dep)
    if not runnable:
        print(f"\nAll {len(deferred)} changed test file(s) deferred to the full tier -- fast-tier gate not reddened.")
        _write_deferral_map(STATE_ALL_DEFERRED, file_reasons)
        return

    print("\n=== Tests (pytest -- explicit changed files) ===")
    cmd = [_common.PYTHON, "-m", "pytest", *runnable, "-m", "not integration", "-v", *_PYTEST_FLAGS, *_COV_FLAGS]
    result = _common.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
    print(result.stdout or "", end="")
    print(result.stderr or "", end="")
    if result.returncode == 0:
        _write_deferral_map(STATE_OK, file_reasons)
        return

    excluded = _excluded_heavy_import_names()
    combined = (result.stdout or "") + (result.stderr or "")
    if _reactive_heavy_dep_signature(combined, excluded) is None:
        # No excluded-heavy-dep signature in the failure output: a genuine failure, a non-heavy
        # collection/runtime error, or an unrelated shape -- redden immediately (fail-closed).
        # The primary invocation was still the SOLE invocation, so its coverage.json remains a
        # usable snapshot of that one run.
        failed.append("Tests (pytest)")
        _write_deferral_map(STATE_OK, file_reasons)
        return

    probe_targets = _attribute_failed_test_files(combined, runnable)
    if probe_targets is None:
        probe_targets = set(runnable)

    deferred_from_probe: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(_REACTIVE_PROBE_MAX_WORKERS, len(probe_targets))) as pool:
        future_to_file = {pool.submit(_runtime_heavy_dep_defer_reason, f, excluded): f for f in probe_targets}
        for future in concurrent.futures.as_completed(future_to_file):
            test_file = future_to_file[future]
            runtime_missing = future.result()
            if runtime_missing:
                deferred_from_probe[test_file] = runtime_missing
    for test_file in sorted(deferred_from_probe):
        _print_deferred_warning(test_file, deferred_from_probe[test_file])
    file_reasons.update(deferred_from_probe)
    survivors = [f for f in runnable if f not in deferred_from_probe]
    if not survivors:
        print(
            "\nAll remaining changed test file(s) deferred to the full tier on reactive "
            "detection -- fast-tier gate not reddened."
        )
        _write_deferral_map(STATE_ALL_DEFERRED, file_reasons)
        return

    print("\n=== Tests (pytest -- reactive re-run on survivors) ===")
    rerun_cmd = [_common.PYTHON, "-m", "pytest", *survivors, "-m", "not integration", "-v", *_PYTEST_FLAGS]
    rerun_result = _common.run(rerun_cmd, cwd=_common.ROOT)
    # Two real invocations happened (primary + this reactive re-run): the primary invocation's
    # coverage.json is still on disk but no longer a trustworthy diff-coverage snapshot (see
    # STATE_TWO_INVOCATION_FAILURE's docstring above) -- classify it as such regardless of this
    # re-run's own outcome.
    _write_deferral_map(STATE_TWO_INVOCATION_FAILURE, file_reasons)
    if rerun_result.returncode != 0:
        failed.append("Tests (pytest)")
