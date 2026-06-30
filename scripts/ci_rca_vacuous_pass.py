"""Deterministic gate-escape evidence: vacuous-pass detection and merged-diff analysis.

Provides three evidence fields for the evidence bundle (schema_version 2):
  - vacuous_pass (True / False / "undetermined"): did the --pre picked-pytest step
    collect 0 items because --picked selected nothing (the defect) vs. because
    -m 'not integration' deselected an all-integration file (expected)?
  - merge_gate_test_coverage ("selected" / "not_selected" / "undetermined"): did the
    merged diff include a test file matching the --pre changed-tests selector?
  - coverage_regression (True / False / "undetermined"): were any test files deleted?

All computations are self-contained (gh-free), working from the pre-fetched CI log and
the local git checkout. HEAD^ must exist (fetch-depth: 2 in ci-rca.yml).
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
_UNDETERMINED = "undetermined"

# mirrors scripts/validate.py:3871 -- keep in sync
_TEST_FILE_RE = re.compile(r"tests/.*test_[^/]+\.py$")


def parse_vacuous_pass(log_text: str) -> bool | str:
    """Parse pytest collection summary from CI log (tri-state).

    Returns:
      True           -- "0 collected, 0 deselected": --picked selected nothing
                        (the gate-escape defect; vacuous_pass=true)
      False          -- "0 ran because -m 'not integration' deselected all":
                        expected edge case (validate.py:3868)
      "undetermined" -- no parseable pytest collection summary; never silently
                        returns False (fail-loud per Decision 55)
    """
    # "collected N item(s) / M deselected" -- canonical line when -m is active
    desel_match = re.search(
        r"collected\s+(\d+)\s+items?\s*/\s*(\d+)\s+deselected",
        log_text,
        re.IGNORECASE,
    )
    if desel_match:
        if int(desel_match.group(2)) > 0:
            return False  # -m "not integration" deselection -- expected per validate.py:3868

    # "collected N item(s)" without a deselection clause
    col_match = re.search(r"collected\s+(\d+)\s+items?", log_text, re.IGNORECASE)
    if col_match:
        if int(col_match.group(1)) == 0:
            return True  # vacuous pass: 0 collected, no deselection
        return False  # tests actually ran

    # "no tests ran" as a fallback signal
    if re.search(r"no tests ran", log_text, re.IGNORECASE):
        if re.search(r"\bdeselected\b", log_text, re.IGNORECASE):
            return False
        return True

    return _UNDETERMINED


def _run_git_diff(extra_args: list[str]) -> list[str] | str:
    """Run git diff --name-only HEAD^ HEAD and return file list, or "undetermined" on failure."""
    cmd = ["git", "diff", "--name-only"] + extra_args + ["HEAD^", "HEAD"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )
        if result.returncode != 0:
            logger.warning("git diff returned %d: %s", result.returncode, result.stderr.strip())
            return _UNDETERMINED
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except Exception as exc:
        logger.warning("git diff failed: %s", exc)
        return _UNDETERMINED


def merged_diff_files() -> list[str] | str:
    """Return files changed in the merged commit via git diff HEAD^ HEAD.

    Returns "undetermined" when HEAD^ is absent or git fails (fetch-depth: 2 required).
    """
    return _run_git_diff([])


def deleted_test_files() -> list[str] | str:
    """Return test files deleted in the merged commit via git diff --diff-filter=D HEAD^ HEAD.

    Returns "undetermined" when HEAD^ is absent or git fails.
    """
    files = _run_git_diff(["--diff-filter=D"])
    if isinstance(files, str):
        return files
    return [f for f in files if _TEST_FILE_RE.match(f)]


def compute_merge_gate_test_coverage(failed_check: str, merged_files: list[str] | str) -> str:
    """Replay the --pre changed-tests selector (validate.py:3871) on merged_files.

    Returns "selected" if the diff contains a matching test file, "not_selected" for
    source-only diffs, or "undetermined" when merged_files is the undetermined sentinel.
    """
    if merged_files == _UNDETERMINED:
        return _UNDETERMINED
    matching = [f for f in merged_files if _TEST_FILE_RE.match(f)]
    return "selected" if matching else "not_selected"


def compute_coverage_regression(deleted_files: list[str] | str) -> bool | str:
    """True if any deleted files are test files (coverage regression).

    Returns "undetermined" when the deletion diff was unavailable.
    """
    if deleted_files == _UNDETERMINED:
        return _UNDETERMINED
    return len(deleted_files) > 0
