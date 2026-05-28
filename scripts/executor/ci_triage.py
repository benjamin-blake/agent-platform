"""Deterministic CI failure classification and auto-fix for the executor.

Handles ~40-50% of CI failures without LLM involvement:
  - Lint errors (ruff) — run ``ruff check --fix``
  - Import order errors — run ``ruff check --select I --fix``

For test failures and unknown categories, returns escalate_to_llm=True
with focused context so the LLM receives a pre-filtered problem description.
"""

import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from scripts.executor.errors import CIFailureCategory

logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    """Result from a deterministic CI triage attempt."""

    category: CIFailureCategory
    fixed: bool
    files_changed: list[str] = field(default_factory=list)
    escalate_to_llm: bool = False
    context_for_llm: str = ""


def triage_ci_failure(error_output: str) -> TriageResult:
    """Classify a CI failure and attempt a deterministic fix where possible.

    Parses ruff/lint errors and import errors from the CI output.
    Runs ``ruff check --fix`` or ``ruff check --select I --fix`` as appropriate.
    Returns a TriageResult indicating whether the fix was applied.

    For test failures or unrecognised errors, returns a TriageResult with
    ``escalate_to_llm=True`` and a context string summarising the error.

    Args:
        error_output: Raw CI failure output (stdout + stderr combined).

    Returns:
        TriageResult with category, fix status, and LLM escalation flag.
    """
    category = _classify(error_output)
    logger.info("[TRIAGE] Classified CI failure as: %s", category.value)

    if category == CIFailureCategory.LINT:
        return _fix_lint(error_output)

    if category == CIFailureCategory.IMPORT:
        return _fix_imports(error_output)

    if category == CIFailureCategory.TYPE:
        # mypy errors are deterministically classifiable but not auto-fixable.
        # Escalate with focused context.
        context = _extract_type_errors(error_output)
        return TriageResult(
            category=category,
            fixed=False,
            escalate_to_llm=True,
            context_for_llm=f"mypy type errors:\n{context}",
        )

    if category == CIFailureCategory.TEST:
        context = _extract_test_errors(error_output)
        return TriageResult(
            category=category,
            fixed=False,
            escalate_to_llm=True,
            context_for_llm=f"pytest failures:\n{context}",
        )

    # Unknown — escalate the full (capped) output
    capped = error_output[:3000]
    return TriageResult(
        category=CIFailureCategory.UNKNOWN,
        fixed=False,
        escalate_to_llm=True,
        context_for_llm=f"Unrecognised CI failure:\n{capped}",
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify(error_output: str) -> CIFailureCategory:
    """Heuristically classify a CI error string into a CIFailureCategory."""
    lower = error_output.lower()

    # Ruff import-order violations are a subset of lint — check first
    # because import errors look like 'E401', 'I001', 'F401' etc.
    if re.search(r"\bI\d{3}\b", error_output) and "ruff" in lower:
        return CIFailureCategory.IMPORT

    # Generic ruff / flake8 / pycodestyle lint
    if "ruff" in lower or re.search(r"\b[A-Z]\d{3}\b", error_output):
        return CIFailureCategory.LINT

    # mypy type errors
    if "error:" in lower and ("mypy" in lower or re.search(r"\.py:\d+: error:", error_output)):
        return CIFailureCategory.TYPE

    # pytest test failures
    if "failed" in lower and ("pytest" in lower or "test session starts" in lower or "FAILED tests/" in error_output):
        return CIFailureCategory.TEST

    return CIFailureCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Lint fix
# ---------------------------------------------------------------------------


def _fix_lint(error_output: str) -> TriageResult:
    """Run ruff check --fix and report which files were changed."""
    ruff = shutil.which("ruff")
    if not ruff:
        # Try via sys.executable (venv may not have ruff on PATH)
        ruff_via_python = _try_ruff_via_python()
        if not ruff_via_python:
            logger.warning("[TRIAGE] ruff not found — cannot auto-fix lint errors")
            return TriageResult(
                category=CIFailureCategory.LINT,
                fixed=False,
                escalate_to_llm=True,
                context_for_llm=f"ruff not available. Lint errors:\n{error_output[:2000]}",
            )
        cmd = [sys.executable, "-m", "ruff", "check", "--fix", "."]
    else:
        cmd = [ruff, "check", "--fix", "."]

    before = _get_tracked_changes()
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    after = _get_tracked_changes()

    files_changed = [f for f in after if f not in before]
    fixed = result.returncode == 0
    logger.info("[TRIAGE] ruff --fix exit=%d, files_changed=%s", result.returncode, files_changed)
    return TriageResult(
        category=CIFailureCategory.LINT,
        fixed=fixed,
        files_changed=files_changed,
        escalate_to_llm=not fixed,
        context_for_llm=("" if fixed else f"ruff --fix failed (exit {result.returncode}):\n{result.stderr[:1000]}"),
    )


def _fix_imports(error_output: str) -> TriageResult:
    """Run ruff check --select I --fix to fix import order."""
    cmd: list[str]
    if shutil.which("ruff"):
        cmd = ["ruff", "check", "--select", "I", "--fix", "."]
    else:
        cmd = [sys.executable, "-m", "ruff", "check", "--select", "I", "--fix", "."]

    before = _get_tracked_changes()
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    after = _get_tracked_changes()

    files_changed = [f for f in after if f not in before]
    fixed = result.returncode == 0
    logger.info("[TRIAGE] ruff --select I --fix exit=%d, files_changed=%s", result.returncode, files_changed)
    return TriageResult(
        category=CIFailureCategory.IMPORT,
        fixed=fixed,
        files_changed=files_changed,
        escalate_to_llm=not fixed,
        context_for_llm=("" if fixed else f"ruff import fix failed (exit {result.returncode}):\n{result.stderr[:1000]}"),
    )


# ---------------------------------------------------------------------------
# Error extraction helpers
# ---------------------------------------------------------------------------


def _extract_type_errors(error_output: str) -> str:
    """Extract mypy error lines from output, capped at 2000 chars."""
    lines = [line for line in error_output.splitlines() if re.search(r"\.py:\d+: error:", line)]
    result = "\n".join(lines[:50])
    return result[:2000]


def _extract_test_errors(error_output: str) -> str:
    """Extract pytest FAILED/ERROR lines from output, capped at 2000 chars."""
    lines = [
        line
        for line in error_output.splitlines()
        if line.startswith("FAILED") or line.startswith("ERROR") or "AssertionError" in line
    ]
    result = "\n".join(lines[:50])
    return result[:2000]


def _get_tracked_changes() -> set[str]:
    """Return set of currently-changed tracked files from git diff."""
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return set(r.stdout.splitlines()) if r.returncode == 0 else set()
    except Exception:
        return set()


def _try_ruff_via_python() -> bool:
    """Return True if 'python -m ruff' is available."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode == 0
    except Exception:
        return False
