"""Mypy error-count baseline: one-time grandfather roster + downward ratchet (VTS-15,
Decision 161; tamper guard mirrors Decision 128's validate_sloc_budget_raises and Decision
159's validate_coverage_baseline_edits).

Collocates the baseline's semantics (load/parse/seed/update) with its enforcement
(`validate_mypy_ratchet`, `validate_mypy_baseline_edits`) in one file (AGENTS.md collocation
rule), following the shape of the closest in-repo sibling scripts/checks/misc/coverage_baseline.py.

A file with NO config/mypy_baseline.yaml entry carries an implicit baseline of 0 -- any mypy
error on an unregistered file fails the ratchet (mirrors the implicit 500 in
config/sloc_budgets.yaml and the implicit 100.0 in config/coverage_baseline.yaml). A file WITH
an entry passes iff its measured error count is at or below that entry.

Marker token is `baseline-raised`, deliberately distinct from sloc's `raise-approved` and
coverage's `baseline-lowered` -- three registries, three direction-correct tokens, so a marker
copy-pasted from one registry cannot silently authorize an edit in another. The tamper guard
(`validate_mypy_baseline_edits`) delegates its diff/authorization mechanics to
scripts.checks._marker_guard (shared across all five raise-marker guards, Decision 165
marker-guard consolidation) -- upgraded from existence to authorization, and the ONLY spec that
enables the Decision 161 clause 4 `moved from <old-path>` same-diff proof. This module owns
only the registry's own RegistrySpec binding, plus the untouched mypy-invocation/ratchet
mechanics below.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable, Optional

import yaml

from scripts.checks import _common, _marker_guard, registry

_BASELINE_REL_PATH = "config/mypy_baseline.yaml"
_GOVERNED_PREFIXES = ("scripts/", "src/")

_ERROR_LINE_RE = re.compile(r"^([^:]+):\d+: error: ")
_FOUND_ERRORS_RE = re.compile(r"Found \d+ errors? in \d+ files?")
_SUCCESS_RE = re.compile(r"Success: no issues found")


def load_baseline(path: Optional[Path] = None) -> dict[str, int]:
    """Load {repo-relative path: baseline error count} from config/mypy_baseline.yaml."""
    p = path or (_common.ROOT / _BASELINE_REL_PATH)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = data.get("entries") or {}
    return {str(k): int(v) for k, v in entries.items()}


def _parse_error_counts(stdout: str) -> dict[str, int]:
    """Parse mypy stdout into {repo-relative path: error count}.

    Counts only ': error:' lines, never ': note:' lines, and never the trailing
    'Found N errors in M files' summary line (it carries no ':digit:: error:' shape so the
    regex never matches it). Keys are RESTRICTED to paths under scripts/ or src/ and
    backslash-normalised before matching baseline keys (harmless on Linux-only CI, correct if
    this is ever run from Windows) -- mypy follows imports, so an unrelated tests/ or venv path
    could otherwise surface here despite the invocation only naming scripts/ src/ on argv.
    """
    counts: dict[str, int] = {}
    for line in stdout.splitlines():
        match = _ERROR_LINE_RE.match(line)
        if not match:
            continue
        path = match.group(1).replace("\\", "/")
        if not path.startswith(_GOVERNED_PREFIXES):
            continue
        counts[path] = counts.get(path, 0) + 1
    return counts


def _run_mypy(failed: list[str]) -> Optional[dict[str, int]]:
    """Run mypy over scripts/ + src/ and parse its stdout into {path: count}.

    Invoked as [sys.executable, "-m", "mypy", ...] -- never a bare "mypy" executable -- so a
    missing mypy surfaces as a normal non-zero run with no terminator (the guard below fires)
    rather than an unhandled FileNotFoundError, and so the interpreter always matches the one
    running this check (AGENTS.md: use sys.executable, never the string "python"). Runs with
    cwd=_common.ROOT so the relative scripts/ src/ argv paths resolve and mypy discovers the
    pyproject.toml [tool.mypy] block from the repo root.

    PROOF-OF-EXECUTION GUARD, mandatory and load-bearing (Decision 55 fail-loud): requires a
    recognizable terminator line in stdout -- either "Found N errors in M files" or "Success:
    no issues found". When NEITHER is present (mypy absent, crashed, misinvoked, or a future
    output-format change), this appends a distinct, loudly-worded failure to `failed` and
    returns None -- never a silently-empty {} that would make every baseline comparison
    vacuously pass. A genuinely clean run ("Success: no issues found") is a real, distinct
    result and returns {} (every file measures zero errors) -- that is NOT the same outcome as
    None, and callers must not conflate the two.
    """
    result = _common.run(
        [_common.PYTHON, "-m", "mypy", "scripts/", "src/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    stdout = result.stdout or ""
    if _FOUND_ERRORS_RE.search(stdout) or _SUCCESS_RE.search(stdout):
        return _parse_error_counts(stdout)

    failed.append(
        "mypy proof-of-execution guard: stdout carried neither 'Found N errors in M files' nor "
        "'Success: no issues found' -- mypy may be absent, crashed, misinvoked, or its output "
        "format has drifted. Treating this as a failed run, not as zero errors everywhere."
    )
    return None


_SPEC = _marker_guard.RegistrySpec(
    rel_path=_BASELINE_REL_PATH,
    token="baseline-raised",
    gated_direction="up",
    extractor=_marker_guard.make_flat_extractor("baseline-raised", value_type=int),
    gates_new_entry=lambda value: value > 0,
    label="mypy baseline tamper guard (Decision 161)",
    moved_from_relief=True,
)


@registry.register("validate_mypy_ratchet", owner="platform")
def validate_mypy_ratchet(failed: list[str], measured: Optional[dict[str, int]] = None) -> None:
    """FULL TIER ONLY. Fails any file whose measured mypy error count exceeds its baseline
    entry (or exceeds 0 when the file is unregistered -- the implicit-zero rule). A measured
    count BELOW its baseline entry always passes, with a non-blocking ratchet-down advisory.

    `measured` is injectable for tests -- an explicit {path: count} skips invoking mypy
    entirely. When omitted, _run_mypy() supplies it; its proof-of-execution guard may append
    to `failed` and return None, in which case this returns immediately rather than running a
    vacuous per-file comparison against an empty-because-it-crashed measurement.
    """
    print("\n=== mypy error-count ratchet (Decision 161) ===")
    if measured is None:
        measured = _run_mypy(failed)
        if measured is None:
            return

    baseline = load_baseline()
    violations: list[str] = []
    advisories: list[str] = []

    for path in sorted(set(baseline) | set(measured)):
        count = measured.get(path, 0)
        threshold = baseline.get(path, 0)
        if count > threshold:
            violations.append(f"{path}: {count} errors exceeds baseline {threshold}.")
        elif count < threshold:
            advisories.append(f"{path}: {count} errors is below baseline {threshold} -- ratchet down with `--update`.")

    if advisories:
        print("mypy ratchet-down advisories (non-blocking):")
        for a in advisories:
            print(f"  ~ {a}")

    if violations:
        print("mypy ratchet violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("mypy error-count ratchet (Decision 161)")
    else:
        print("No mypy error-count regressions.")


@registry.register("validate_mypy_baseline_edits", owner="platform")
def validate_mypy_baseline_edits(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """BOTH TIERS. The cheap tamper guard: fails an unauthorized config/mypy_baseline.yaml
    increase, new registration, or a currently-committed marker that no longer authorizes its
    entry -- unless the entry line carries an inline `# baseline-raised: dec-NNN <reason>`
    marker naming a real `## Decision NNN:` header whose body actually authorizes it (or, the
    Decision 161 clause 4 `moved from <old-path>` same-diff proof). SKIPs (non-failing) when
    origin/main or the base file is unreachable, so the seeding PR itself (no base file yet)
    SKIPs instead of self-failing.
    """
    print(f"\n=== {_SPEC.label} ===")
    violations = _marker_guard.check_diff(_SPEC, base_reader=base_reader) + _marker_guard.check_present_markers(_SPEC)

    if violations:
        print("mypy baseline tamper-guard violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append(_SPEC.label)
    else:
        print("No unauthorized mypy baseline raises or new registrations.")


_BASELINE_HEADER = """# Mypy error-count baseline registry (VTS-15, Decision 161).
# Each entry pins a repo-relative Python file (under scripts/ or src/) to the maximum mypy
# error count it may measure at or below. A file with NO entry carries an implicit baseline of
# 0 -- any error on an unregistered file fails the ratchet (mirrors config/sloc_budgets.yaml's
# implicit 500 and config/coverage_baseline.yaml's implicit 100.0).
#
# Ratchet DOWN only: lowering an entry, or removing it once the file is clean, is always
# unrestricted -- run `bin/venv-python -m scripts.checks.typing.mypy_baseline --update`.
# RAISING an entry, or registering a NEW file, requires a manual, reviewable edit carrying an
# inline `# baseline-raised: dec-NNN <reason>` marker naming a real `## Decision NNN:` header --
# enforced by validate_mypy_baseline_edits in both presubmit tiers.
#
# Seeded via `bin/venv-python -m scripts.checks.typing.mypy_baseline --seed`. This is a
# ONE-TIME grandfather of pre-existing type-logic debt at seeding time -- not a precedent for
# future debt.
entries:
"""


def _write_baseline(path: Path, entries: dict[str, int]) -> None:
    body = "".join(f"  {k}: {v}\n" for k, v in sorted(entries.items()))
    path.write_text(_BASELINE_HEADER + body, encoding="utf-8")


def _seed() -> int:
    """ONE-TIME initial roster creation: writes an entry for every file measuring >=1 error.
    REFUSES (non-zero exit, no write) when config/mypy_baseline.yaml already exists, so it can
    never be repurposed to launder new debt into the roster.
    """
    baseline_path = _common.ROOT / _BASELINE_REL_PATH
    if baseline_path.exists():
        print(f"REFUSING to seed: {_BASELINE_REL_PATH} already exists. Delete it first, or use --update.")
        return 1

    failed: list[str] = []
    measured = _run_mypy(failed)
    if measured is None:
        for f in failed:
            print(f"  - {f}")
        print("Seeding aborted -- mypy did not run to completion.")
        return 1

    entries = {path: count for path, count in measured.items() if count >= 1}
    _write_baseline(baseline_path, entries)
    print(f"Seeded {len(entries)} entries totalling {sum(entries.values())} errors.")
    return 0


def _update() -> int:
    """Steady-state downward-only ratchet: lowers entries whose file improved, drops files now
    clean or deleted, NEVER raises an entry, and NEVER seeds a newly-dirty unregistered file.
    Run against an absent or empty roster, this writes nothing -- that is the precise behaviour
    that makes the separate --seed mode necessary.
    """
    baseline_path = _common.ROOT / _BASELINE_REL_PATH
    existing = load_baseline(baseline_path)
    if not existing:
        print(f"{_BASELINE_REL_PATH} is absent or empty -- nothing to update. Use --seed first.")
        return 0

    failed: list[str] = []
    measured = _run_mypy(failed)
    if measured is None:
        for f in failed:
            print(f"  - {f}")
        print("Update aborted -- mypy did not run to completion.")
        return 1

    new_entries: dict[str, int] = {}
    for path, old_count in existing.items():
        new_count = measured.get(path, 0)
        if new_count < 1:
            continue  # now clean or deleted -- drop
        new_entries[path] = min(new_count, old_count)  # never raise

    lowered = sorted(p for p in new_entries if new_entries[p] < existing[p])
    dropped = sorted(p for p in existing if p not in new_entries)

    _write_baseline(baseline_path, new_entries)
    print(f"mypy baseline updated: {len(lowered)} lowered, {len(dropped)} dropped (no auto-seed; Decision 161).")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mypy error-count baseline: one-time --seed, downward-only --update (Decision 161)."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seed", action="store_true", help="One-time roster creation; refuses if the baseline already exists.")
    mode.add_argument("--update", action="store_true", help="Downward-only ratchet; never raises, never seeds a new file.")
    args = parser.parse_args(argv)
    return _seed() if args.seed else _update()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
