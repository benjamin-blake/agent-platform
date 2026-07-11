# complexity-waiver: decision-43
"""Auto-formatting helpers for the executor step runner.

Extracted from step_runner.py (Part 4 of monolith extraction plan).
Functions: auto_format_test_files, _run_ruff_fix, _run_ruff_format.
"""

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.llm.utils import kill_process_tree

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = (
    _REPO_ROOT / ".venv" / "bin" / "python"  # Linux/macOS (CD.2 primary)
    if (_REPO_ROOT / ".venv" / "bin" / "python").exists()
    else _REPO_ROOT / ".venv" / "Scripts" / "python.exe"  # Why: CD.2/CD.3 -- Windows fallback
)
_PROJECT_PYTHON: str = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


def auto_format_test_files(step_file: str) -> bool:
    """Auto-format Python test files created or modified in this step.

    Searches for test files that correspond to the step's target file
    (or any newly created test files in the tests/ directory modified
    very recently). Runs ruff format on each one to prevent validate.py
    failures due to formatting issues.

    Args:
        step_file: The main file being modified/created in this step.

    Returns:
        True if formatting succeeded or was skipped (no test files found).
        False if any ruff format command failed.
    """
    if not step_file:
        return True

    step_path = Path(step_file)
    stem = step_path.stem

    test_files_to_format: list[Path] = []

    # If the step file IS a test file, format it directly
    if step_path.parts[0:1] == ("tests",) and stem.startswith("test_"):
        if step_path.exists() and step_path.is_file():
            test_files_to_format.append(step_path)
    else:
        # Look for the primary test file matching the stem
        test_file = Path("tests") / f"test_{stem}.py"
        if test_file.exists() and test_file.is_file():
            test_files_to_format.append(test_file)

    # Then, discover any other test files in tests/ modified recently (last 120 seconds)
    tests_dir = Path("tests")
    if tests_dir.is_dir():
        now = time.time()
        for test_path in tests_dir.glob("test_*.py"):
            if test_path.is_file() and test_path not in test_files_to_format:
                try:
                    mtime = test_path.stat().st_mtime
                    if now - mtime < 120:  # Modified in the last 120 seconds
                        test_files_to_format.append(test_path)
                except OSError:
                    pass

    # Prefer the venv ruff binary by absolute path, then PATH lookup, then
    # python -m ruff fallback. The venv binary works even when venv is not
    # activated (PATH doesn't include .venv/bin).
    _venv_ruff = _REPO_ROOT / ".venv" / "bin" / "ruff"  # Linux/macOS (CD.2 primary)
    if not _venv_ruff.exists():
        _venv_ruff = _REPO_ROOT / ".venv" / "Scripts" / "ruff.exe"  # Why: CD.2/CD.3 -- Windows fallback
    if _venv_ruff.exists():
        ruff_cmd_prefix: list[str] = [str(_venv_ruff)]
    else:
        _ruff_which = shutil.which("ruff")
        ruff_cmd_prefix = [_ruff_which] if _ruff_which else [_PROJECT_PYTHON, "-m", "ruff"]

    for test_path in test_files_to_format:
        logger.info("[FORMAT] Running ruff format on %s", test_path)

        with subprocess.Popen(
            [*ruff_cmd_prefix, "format", test_path.as_posix()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc.pid)
                proc.wait()
                logger.warning("[FORMAT] Timeout (30s) formatting %s -- skipping", test_path)
                continue

        if proc.returncode != 0:
            logger.warning(
                "[FORMAT] ruff format failed for %s (exit %d) -- skipping\nstdout: %s\nstderr: %s",
                test_path,
                proc.returncode,
                stdout[:1500],
                stderr[:1500],
            )
            # Non-fatal: formatting is best-effort. Correctness is enforced by
            # _run_ruff_fix and validate.py --pre later in the same step.
            continue

        logger.info("[FORMAT] Successfully formatted %s", test_path)

    return True


def _run_ruff_fix(changed_files: list[str]) -> bool:
    """Run ``ruff check --fix`` on changed Python files.

    Auto-fixes import ordering (I001), unused imports (F401), and other
    auto-fixable lint issues that the implementation agent may introduce.
    Called before ``validate.py`` so that trivially fixable errors do not
    cause step failures.

    Args:
        changed_files: File paths modified/created in the current step.

    Returns:
        True if fixing succeeded or no Python files found.
        False only on unexpected ruff errors (exit code >= 2).
    """
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return True

    _ruff_which = shutil.which("ruff")
    ruff_fix_cmd: list[str] = [_ruff_which] if _ruff_which else [sys.executable, "-m", "ruff"]

    for file_path in py_files:
        if not Path(file_path).exists():
            continue
        logger.info("[RUFF] Running ruff check --fix on %s", file_path)
        with subprocess.Popen(
            [*ruff_fix_cmd, "check", "--fix", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc.pid)
                proc.wait()
                logger.error("[RUFF] Timeout fixing %s", file_path)
                return False

        # Exit 0 = no issues, 1 = issues found (some fixed), 2 = error
        if proc.returncode >= 2:
            logger.error(
                "[RUFF] ruff check --fix failed for %s (exit %d)\nstderr: %s",
                file_path,
                proc.returncode,
                stderr[:1500],
            )
            return False

        if proc.returncode == 1:
            logger.info("[RUFF] Applied auto-fixes to %s", file_path)
            # Second pass: I001 import reordering sometimes needs another fix cycle
            # because first-pass fixes alter block structure and trigger new I001.
            with subprocess.Popen(
                [*ruff_fix_cmd, "check", "--fix", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            ) as proc2:
                try:
                    stdout2, stderr2 = proc2.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    kill_process_tree(proc2.pid)
                    proc2.wait()
                    logger.error("[RUFF] Timeout on second pass for %s", file_path)
                    return False
            if proc2.returncode >= 2:
                logger.error(
                    "[RUFF] ruff check --fix (pass 2) failed for %s (exit %d)\nstderr: %s",
                    file_path,
                    proc2.returncode,
                    stderr2[:1500],
                )
                return False
            if proc2.returncode == 1:
                logger.info("[RUFF] Applied second-pass auto-fixes to %s", file_path)
            # Third pass: W291/W293 (trailing whitespace in string literals) and
            # F841 (unused variables from LLM-generated test stubs) require
            # --unsafe-fixes. These fixes are safe for test/plan files.
            if file_path.endswith("_plan.py") or "test_" in file_path:
                with subprocess.Popen(
                    [*ruff_fix_cmd, "check", "--fix", "--unsafe-fixes", "--select", "W291,W293,F841", file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                ) as proc3:
                    try:
                        _stdout3, _stderr3 = proc3.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        kill_process_tree(proc3.pid)
                        proc3.wait()
                        logger.warning("[RUFF] Timeout on W291/W293/F841 unsafe pass for %s -- continuing", file_path)
                    else:
                        if proc3.returncode == 1:
                            logger.info("[RUFF] Applied W291/W293/F841 unsafe-fix to %s", file_path)
        else:
            logger.debug("[RUFF] No issues in %s", file_path)

    return True


def _run_ruff_format(changed_files: list[str]) -> bool:
    """Run ``ruff format`` on changed Python files after auto-fixes.

    ``ruff check --fix`` can leave files syntactically correct but not formatted
    to the formatter's final style. Running ``ruff format`` after auto-fixes
    prevents validate.py --pre from failing on a format-only delta.

    Args:
        changed_files: File paths modified/created in the current step.

    Returns:
        True if formatting succeeded or no Python files found.
        False on unexpected ruff errors or timeouts.
    """
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return True

    _venv_ruff = _REPO_ROOT / ".venv" / "bin" / "ruff"  # Linux/macOS (CD.2 primary)
    if not _venv_ruff.exists():
        _venv_ruff = _REPO_ROOT / ".venv" / "Scripts" / "ruff.exe"  # Why: CD.2/CD.3 -- Windows fallback
    if _venv_ruff.exists():
        ruff_format_cmd: list[str] = [str(_venv_ruff)]
    else:
        _ruff_which = shutil.which("ruff")
        ruff_format_cmd = [_ruff_which] if _ruff_which else [_PROJECT_PYTHON, "-m", "ruff"]

    for file_path in py_files:
        if not Path(file_path).exists():
            continue
        logger.info("[FORMAT] Running post-fix ruff format on %s", file_path)
        with subprocess.Popen(
            [*ruff_format_cmd, "format", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as proc:
            try:
                _stdout, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc.pid)
                proc.wait()
                logger.error("[FORMAT] Timeout on post-fix format for %s", file_path)
                return False

        if proc.returncode != 0:
            logger.error(
                "[FORMAT] post-fix ruff format failed for %s (exit %d)\nstderr: %s",
                file_path,
                proc.returncode,
                stderr[:1500],
            )
            return False

    return True
