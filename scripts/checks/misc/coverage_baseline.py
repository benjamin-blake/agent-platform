"""Coverage baseline: one-time grandfather roster + measurement engine (Decision 130 style,
tamper guard mirrors Decision 128's validate_sloc_budget_raises).

Collocates the baseline's semantics (load/compare) with its enforcement
(`validate_coverage_baseline_edits`) in one file (AGENTS.md collocation rule), and hosts the
per-file pytest+coverage measurement mechanics that used to live in
scripts/test_coverage_checker.py (moved here under the Decision 102/128 decompose-by-default
SLOC rule -- that file re-exports `measure_per_file_coverage` as a one-line facade).

`measure_and_check`/`measure_per_file_coverage` deliberately access `map_source_to_test`,
`_is_empty_directory_target`, `ROOT`, and `subprocess` via the scripts.test_coverage_checker
MODULE OBJECT (an attribute lookup at call time), not a direct name import -- this is what lets
existing `unittest.mock.patch("test_coverage_checker.<name>")` call sites keep intercepting
correctly after the relocation (the patch mutates the attribute on that module object, and an
attribute lookup on the same object sees the patched value; a `from ... import name` binding
would not).

A changed file WITHOUT a config/coverage_baseline.yaml entry keeps the 100% standard
(Decision 48 V2 row, narrowed by forward reference in the carrying Decision); a file WITH an
entry passes iff measured >= that entry's threshold. Lowering an entry, or registering a new
sub-100 entry, requires an inline `# baseline-lowered: dec-NNN <reason>` marker naming a real
`## Decision NNN:` header -- raises and removals are always unrestricted. When
config/coverage_baseline.yaml does not exist at origin/main (e.g. the seeding PR itself), the
guard SKIPs rather than treating "missing base" as "empty base" (mirrors
validate_sloc_budget_raises' `_default_base_reader` contract).
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Callable, Optional

import yaml

from scripts.checks import _common, registry

_BASELINE_REL_PATH = "config/coverage_baseline.yaml"
_DECISIONS_REL_PATH = "docs/DECISIONS.md"

_ENTRY_LINE_RE = re.compile(r"^\s*([\w./_-]+):\s*([\d.]+)\s*(#.*)?$")
_LOWERED_MARKER_RE = re.compile(r"#\s*baseline-lowered:\s*dec-(\d+)")
_DECISION_HEADER_RE = re.compile(r"^## Decision (\d+):", re.MULTILINE)


def load_baseline(path=None) -> dict[str, float]:
    """Load {repo-relative path: baseline pct} from config/coverage_baseline.yaml."""
    p = path or (_common.ROOT / _BASELINE_REL_PATH)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = data.get("entries") or {}
    return {str(k): round(float(v), 1) for k, v in entries.items()}


def compare(measured_pct: float, rel_path: str, baseline: dict[str, float] | None = None) -> bool:
    """True (pass) iff measured_pct >= the file's baseline threshold (100.0 if unbaselined)."""
    table = baseline if baseline is not None else load_baseline()
    threshold = table.get(rel_path, 100.0)
    return round(measured_pct, 1) >= threshold


def measure_and_check(source_files: list, *, root, map_source_to_test, is_empty_dir, subprocess_module) -> tuple:
    """Run pytest coverage for each source file.

    Returns ({str(resolved path): measured pct | None}, hard-error strings unrelated to the
    baseline compare -- coverage timeouts and "no tests exercise this file"). A None value
    means no usable measurement was produced.

    `root`/`map_source_to_test`/`is_empty_dir`/`subprocess_module` are passed in by the caller
    (scripts/test_coverage_checker.py) rather than imported here, so the lookup happens on the
    CALLER's own module globals -- this is what keeps `patch("test_coverage_checker.<name>")`
    (which patches an attribute on whichever module object loaded that file) intercepting
    correctly, including the ad hoc `importlib.spec_from_file_location` copy the legacy split
    test suite (tests/fixtures/coverage_checker_module.py) loads under a bare module name.
    """
    pcts: dict = {}
    errors: list = []

    for source_path in source_files:
        try:
            rel = source_path.resolve().relative_to(root)
        except ValueError:
            continue
        key = str(source_path.resolve())

        # rec-943: --cov must be the file's PARENT DIRECTORY, never a single .py path --
        # coverage.py treats a --cov/source entry as an importable name or a directory; a
        # single-file dotted/path spec silently collects no data at all (module-not-imported +
        # no-data-collected), which would otherwise masquerade as a pass.
        cov_target = str(rel.parent)

        test_path = map_source_to_test(source_path)
        if test_path is None or not test_path.exists():
            continue
        if is_empty_dir(test_path):
            continue
        test_path_str = str(test_path.relative_to(root)).replace("\\", "/")
        print(f"  mapping: {rel} -> {test_path_str} (--cov={cov_target})")

        child_env = os.environ.copy()
        child_env["_COVERAGE_SUBPROCESS"] = "1"

        with subprocess_module.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                test_path_str,
                f"--cov={cov_target}",
                "--cov-report=json:.coverage.json",
                "-q",
                "--no-header",
            ],
            stdout=subprocess_module.PIPE,
            stderr=subprocess_module.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            env=child_env,
        ) as proc:
            try:
                proc.communicate(timeout=300)
            except subprocess_module.TimeoutExpired:
                from scripts.llm.utils import kill_process_tree  # noqa: PLC0415

                kill_process_tree(proc.pid)
                proc.wait()
                errors.append(f"{rel}: coverage check timed out (300s)")
                pcts[key] = None
                continue

        coverage_json = root / ".coverage.json"
        if not coverage_json.exists():
            print(f"  [info] no coverage data for {rel} (coverage.py unavailable or file not tracked)")
            pcts[key] = None
            continue

        try:
            data = json.loads(coverage_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pcts[key] = None
            continue
        finally:
            try:
                coverage_json.unlink()
            except OSError:
                pass

        rel_str = str(rel).replace("\\", "/")
        matched: dict[str, float] = {}
        for file_key, file_data in data.get("files", {}).items():
            normalised_key = file_key.replace("\\", "/")
            if rel_str in normalised_key or normalised_key.endswith(rel_str):
                matched[file_key] = file_data.get("summary", {}).get("percent_covered", 0.0)

        if not matched:
            errors.append(f"{rel}: 0% coverage (no tests exercise this file)")
            pcts[key] = None
            continue

        pcts[key] = min(matched.values())

    return pcts, errors


def _default_base_reader(rel_path: str) -> Optional[str]:
    result = _common.run(
        ["git", "show", f"origin/main:{rel_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_entry_lines(text: str) -> dict[str, tuple[float, Optional[str]]]:
    """Parse raw 'path: N.N  # comment' lines into {path: (value, baseline-lowered dec_id | None)}."""
    entries: dict[str, tuple[float, Optional[str]]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in ("entries:",):
            continue
        match = _ENTRY_LINE_RE.match(stripped)
        if not match:
            continue
        path, value_str, comment = match.group(1), match.group(2), match.group(3)
        marker: Optional[str] = None
        if comment:
            marker_match = _LOWERED_MARKER_RE.search(comment)
            if marker_match:
                marker = f"dec-{marker_match.group(1)}"
        entries[path] = (float(value_str), marker)
    return entries


def _decision_header_exists(dec_id: str, decisions_text: str) -> bool:
    number = dec_id.removeprefix("dec-")
    return any(number == n for n in _DECISION_HEADER_RE.findall(decisions_text))


@registry.register("validate_coverage_baseline_edits", owner="platform")
def validate_coverage_baseline_edits(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/coverage_baseline.yaml lowering or new sub-100 entry."""
    print("\n=== Coverage baseline tamper guard ===")
    reader = base_reader or _default_base_reader

    current_path = _common.ROOT / _BASELINE_REL_PATH
    if not current_path.exists():
        print(f"  {_BASELINE_REL_PATH} not found -- nothing to check.")
        return

    base_text = reader(_BASELINE_REL_PATH)
    if base_text is None:
        print("  SKIP: origin/main unreachable, or the baseline file does not exist there yet.")
        return

    current_text = current_path.read_text(encoding="utf-8")
    base_entries = _parse_entry_lines(base_text)
    current_entries = _parse_entry_lines(current_text)

    decisions_path = _common.ROOT / _DECISIONS_REL_PATH
    decisions_text = decisions_path.read_text(encoding="utf-8") if decisions_path.exists() else ""

    violations: list[str] = []
    for path, (new_value, marker) in sorted(current_entries.items()):
        base_entry = base_entries.get(path)
        is_new = base_entry is None
        is_lowered = base_entry is not None and new_value < base_entry[0]
        if not (is_new or is_lowered):
            continue

        if marker is None:
            kind = "new sub-100 registration" if is_new else f"lowered {base_entry[0]} -> {new_value}"
            violations.append(f"{path}: unauthorized {kind} with no `# baseline-lowered: dec-NNN` marker on the entry line.")
            continue

        if not _decision_header_exists(marker, decisions_text):
            violations.append(f"{path}: baseline-lowered marker cites {marker}, but no `## Decision N:` header for it exists.")

    if violations:
        print("Coverage baseline tamper-guard violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Coverage baseline tamper guard")
    else:
        print("No unauthorized coverage baseline lowering or new sub-100 registration.")
