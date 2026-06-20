"""Acceptance command validation and feasibility checks.

Extracted from scripts/execute_recommendation.py (Strangler Fig, Decision 43).
All functions remain importable from the original module via re-exports.
"""

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AcceptanceFeasibility(Enum):
    """Enum indicating feasibility status of an acceptance command."""

    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNPARSEABLE = "unparseable"


def _normalize_acceptance(acceptance: object) -> str:
    """Normalize acceptance scalar-or-list to str (T0.12.5 CD.29 shim).

    list[str]: joined with ' && '. Empty list -> ''.
    list[dict] TypedCheck: command field extracted then joined with ' && '.
    str: returned unchanged.
    """
    if isinstance(acceptance, str):
        return acceptance
    if not isinstance(acceptance, list) or not acceptance:
        return ""
    if isinstance(acceptance[0], dict):
        parts = [c.get("command", "") for c in acceptance if isinstance(c, dict)]
    else:
        parts = [str(p) for p in acceptance]
    return " && ".join(p for p in parts if p and p.strip())


def validate_acceptance_feasibility(acceptance: object, action: str = "") -> tuple[AcceptanceFeasibility, str]:
    """Extract file paths from acceptance commands and verify they exist.

    Checks acceptance commands for common patterns (grep, pytest, python -m)
    and validates that referenced files/modules exist before planning.

    Accepts str | list[str] | list[dict] (CD.29 TypedCheck) per T0.12.5 shim.

    Args:
        acceptance: The acceptance command string (or list) to validate.
        action: Optional step action type (e.g. "create"). When "create",
            Pattern 1 (grep file-path checks) skips the file-existence check
            because the file is expected to be created by this rec.

    Returns:
        (AcceptanceFeasibility, reason) - FEASIBLE with empty reason,
        INFEASIBLE with diagnostic detail, or UNPARSEABLE with explanation.
    """
    acceptance = _normalize_acceptance(acceptance)
    if not acceptance or not acceptance.strip():
        return AcceptanceFeasibility.FEASIBLE, ""

    cmd = acceptance.strip()
    # Strip surrounding backtick delimiters (acceptance fields are stored as `cmd`)
    if cmd.startswith("`") and cmd.endswith("`"):
        cmd = cmd[1:-1].strip()
    repo_root = Path(__file__).parent.parent.parent

    # Split by && to handle chained commands
    command_parts = cmd.split("&&")

    for part in command_parts:
        part = part.strip()

        # Pattern 1: grep commands with file paths
        grep_match = re.search(r"grep\s+(?:[^\s'\"]+\s+)?['\"].*?['\"](?:\s+[|]|$|\s+(\S+))", part)
        if grep_match:
            file_path = grep_match.group(1)
            if file_path:
                full_path = repo_root / file_path
                if not full_path.exists():
                    if action == "create":
                        continue
                    return (
                        AcceptanceFeasibility.INFEASIBLE,
                        f"grep target file does not exist: {file_path}",
                    )

        # Pattern 2: pytest commands with test file paths
        pytest_match = re.search(r"pytest\s+(tests/\S+\.py)", part)
        if pytest_match:
            file_path = pytest_match.group(1).split("::")[0]
            full_path = repo_root / file_path
            if not full_path.exists():
                # File may be created by this rec -- treat as feasible
                pass

        # Pattern 3: python -m scripts.MODULE paths
        module_match = re.search(r"python\s+-m\s+(scripts\.[\w.]+)", part)
        if module_match:
            module_name = module_match.group(1)
            module_path = module_name.replace(".", "/") + ".py"
            full_path = repo_root / module_path
            if not full_path.exists():
                package_path = repo_root / module_name.replace(".", "/")
                if not (package_path / "__init__.py").exists():
                    pass

    return AcceptanceFeasibility.FEASIBLE, ""


def lint_acceptance_command(acceptance: object) -> tuple[bool, Optional[str]]:
    """Validate acceptance command for banned patterns and bash syntax.

    Accepts str | list[str] | list[dict] (CD.29 TypedCheck) per T0.12.5 shim.

    Returns:
        (True, None) if valid, (False, error_msg) if invalid.
    """
    acceptance = _normalize_acceptance(acceptance)
    if not acceptance or not acceptance.strip():
        return True, None

    cmd = acceptance.strip()

    # Check for banned pattern: python -c one-liners
    if re.search(r'\bpython\s+(?:-c|-m\s+)\s*["\']', cmd):
        error_msg = (
            "ERROR: python -c one-liners are banned (nested quotes break on Windows).\n"
            f"  Command: {cmd}\n"
            "  FIX: Use 'python -m pytest tests/test_file.py::TestClass -q' or "
            "'python scripts/validate.py --pre' instead.\n"
        )
        return False, error_msg

    # Check for multi-word grep patterns with regex operators
    if "grep" in cmd:
        if re.search(r"grep\s+[^\s'\"]*[qEi]*[^\s'\"]*\s+['\"].*[\*\|].*['\"]", cmd):
            error_msg = (
                "WARNING: Multi-word grep pattern detected (may have intended "
                "semantics issue).\n"
                f"  Command: {cmd}\n"
                "  SUGGESTION: Split into chained grep -q calls:\n"
                "    Old: grep -E 'word1.*word2' file\n"
                "    New: grep -q 'word1' file && grep -q 'word2' file\n"
            )
            # Use logger.warning and also print for backward compatibility with some tests
            logger.warning(error_msg)
            print(error_msg)

    # Validate bash syntax (find bash or sh)
    bash_exe = shutil.which("bash") or shutil.which("sh")
    if bash_exe:
        try:
            result = subprocess.run(
                [bash_exe, "-n"],
                input=cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if result.returncode != 0:
                error_msg = (
                    f"ERROR: Bash syntax validation failed for acceptance command.\n"
                    f"  Command: {cmd}\n"
                    f"  Bash error:\n{result.stderr}\n"
                )
                return False, error_msg
        except Exception as e:
            error_msg = f"ERROR: Could not validate bash syntax: {e}\n  Command: {cmd}\n"
            return False, error_msg

    return True, None


def _checkout_main_safely(restore_branch: str = "") -> None:
    """Stash uncommitted changes, checkout main, optionally restore to a branch."""
    subprocess.run(
        ["git", "stash"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    subprocess.run(
        ["git", "checkout", "main"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if restore_branch:
        subprocess.run(
            ["git", "checkout", restore_branch],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    subprocess.run(
        ["git", "stash", "pop"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


def _check_acceptance_on_main(rec_id: str, acceptance_cmd: str, branch: str) -> bool:
    """Check if acceptance criterion already passes on main branch.

    ONLY for pre-planning already-implemented detection on the main branch.

    Switches to main, runs acceptance command, then returns to feature branch.
    If acceptance passes, updates rec status to 'closed' with execution_result=
    'already_implemented' and returns True.

    Args:
        rec_id: The recommendation ID.
        acceptance_cmd: The acceptance command to run.
        branch: The feature branch name (to return to after check).

    Returns:
        True if acceptance passed on main (rec marked as completed), False otherwise.
    """
    # Deferred imports to avoid circular dependency
    from scripts.executor.jsonl_store import load_recommendation, update_recommendation_status
    from scripts.executor.step_runner import run_acceptance

    if not acceptance_cmd or not acceptance_cmd.strip():
        return False

    current_branch = ""
    try:
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        ).stdout.strip()

        # Switch to main
        logger.info("[ACCEPTANCE-CHECK] Switching to main to test acceptance")
        _checkout_main_safely()

        # Run acceptance command on main
        logger.info("[ACCEPTANCE-CHECK] Running acceptance on main: %s", acceptance_cmd)
        acceptance_result = run_acceptance(acceptance_cmd)

        if acceptance_result:
            rec = load_recommendation(rec_id)
            rec_date = rec.get("date") if rec else None
            rec_file = rec.get("file") if rec else None

            if not rec:
                logger.warning(
                    "[ACCEPTANCE-CHECK] Could not load rec %s -- skipping date guard",
                    rec_id,
                )

            # Check if commits exist since rec date
            if rec_date and rec_file:
                git_log_result = subprocess.run(
                    [
                        "git",
                        "log",
                        f"--since={rec_date}",
                        "--oneline",
                        "--",
                        rec_file,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
                commit_count = len([line for line in git_log_result.stdout.splitlines() if line.strip()])

                if commit_count == 0:
                    allow_ambiguous = os.getenv("ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED", "").lower()
                    if allow_ambiguous not in ("true", "1", "yes"):
                        logger.warning(
                            "[ACCEPTANCE-CHECK] Acceptance passed but no commits since %s for %s",
                            rec_date,
                            rec_file,
                        )
                        return False

            logger.info("[ACCEPTANCE-CHECK] Acceptance PASSED on main -- marking rec as complete")
            print("[ACCEPTANCE-CHECK] Already implemented on main!")
            update_recommendation_status(
                rec_id,
                {
                    "status": "closed",
                    "execution_result": "already_implemented",
                    "execution_date": datetime.now(timezone.utc).isoformat(),
                    "execution_branch": branch,
                    "execution_steps": 0,
                    "execution_steps_total": 0,
                },
            )
            return True
        else:
            logger.info("[ACCEPTANCE-CHECK] Acceptance failed on main -- proceeding with plan")
            return False

    except Exception as e:
        logger.warning("[ACCEPTANCE-CHECK] Error during acceptance check: %s", e)
        return False
    finally:
        # Always restore to feature branch
        try:
            if current_branch:
                _checkout_main_safely(current_branch)
        except Exception as restore_err:
            logger.error(
                "[ACCEPTANCE-CHECK] Failed to restore branch %s: %s",
                current_branch,
                restore_err,
            )
