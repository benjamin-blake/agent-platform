# complexity-waiver: decision-43
"""Step implementation, acceptance verification, and telemetry for the executor.

Handles per-step file-context gathering, LLM calls, acceptance command
execution, git commits, and step-level telemetry writes.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from scripts.executor.plan import load_prompt
from scripts.executor.telemetry import emit_process_event, emit_step, emit_transcript
from scripts.llm_client import llm_call
from scripts.llm_utils import build_context_path, kill_process_tree
from scripts.s3_log_store import append_jsonl, get_backend

logger = logging.getLogger(__name__)

STEP_TELEMETRY_JSONL = Path("logs/.execution-step-telemetry.jsonl")
_LAST_ACCEPTANCE_OUTPUT = ""


class StepOutcome(Enum):
    """Outcome states for step implementation execution."""

    SUCCESS = "success"
    CLI_ERROR = "cli_error"
    GHOST_STEP = "ghost_step"
    FORMAT_ERROR = "format_error"
    RUFF_ERROR = "ruff_error"
    VALIDATE_TIMEOUT = "validate_timeout"
    VALIDATE_FAILED = "validate_failed"
    ACCEPTANCE_FAILED = "acceptance_failed"


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

# Retained for external importers that reference OPUS_FALLBACK as a constant.
# After migration, model selection is delegated to model_registry.resolve_model().
OPUS_FALLBACK = "claude-opus-4.6"
_LARGE_FILE_THRESHOLD = 800  # kept for gather_step_context() large-file detection
DEFAULT_STEP_TIMEOUT_SECS = 900

# Executor-mode environment variables that should be stripped from acceptance
# subprocess environments. These control executor behavior but should not leak
# into test execution or other acceptance commands.
_EXECUTOR_ACC_VARS = frozenset(
    [
        "SKIP_CI_WAIT",
        "SKIP_CODE_REVIEW",
        "COPILOT_MODEL_EXECUTION",
        "COPILOT_MODEL_PLANNING",
        "CI_FIX_RETRIES",
    ]
)

# ---------------------------------------------------------------------------
# Known Gotcha injection
# ---------------------------------------------------------------------------

# Maps file-path prefixes (or substrings) to relevant Known Gotcha strings.
# Keys are matched as prefixes first, then as substrings, against the step's
# target file path. Entries are ordered from most-specific to least-specific.
_GOTCHA_MAP: dict[str, list[str]] = {
    "scripts/executor/": [
        "replace_string_in_file context boundary: Include 3-5 lines of unchanged code before "
        "and after target text. Weak boundaries cause wrong-occurrence matches or silent formatting changes.",
        "ruff E501 and multi-line section builders: Define intermediate _header, _footer, _section "
        "variables for long f-strings to stay under 127 chars.",
        "Executor self-modification boundary: Never modify executor machinery files from within the executor.",
    ],
    "terraform/": [
        "Terraform File-Optional Operations: Always wrap filemd5() and file() calls on optional "
        "artifacts with try(). BAD: source_code_hash = filemd5('build/lambda.zip'). "
        "GOOD: source_code_hash = try(filemd5('build/lambda.zip'), md5(file('module_file.tf'))).",
        "Lambda tag values must use ASCII-safe characters: use plain ASCII hyphens (-) not em dashes.",
    ],
    "tests/": [
        "Test Isolation Patterns: Never spawn pytest tests/ from a script any test imports -- "
        "recursion risk. Always mock both subprocess.Popen AND subprocess.run for subprocess-spawning functions.",
        "ruff format duplicate import consolidation: Never split the same module imports across two "
        "blocks -- ruff silently drops symbols from the second block during format.",
        "postflight.py function mock exhaustion: Count total subprocess.run call sequence and update "
        "mock side_effect counts in tests/test_execute_recommendation.py when adding new calls.",
    ],
    "src/data/handlers/": [
        "Import Safety Patterns: Never raise exceptions during module import -- breaks pytest collection in CI. "
        "Defer validation to explicit validate() calls.",
        "Lambda deployment pipeline: Any plan modifying Lambda-packaged files must include "
        "build and deploy steps via scripts/build_lambda.py.",
    ],
}

_GOTCHA_INJECTION_MAX_CHARS = 2000


def _get_relevant_gotchas(file_path: str) -> str:
    """Return a string of relevant Known Gotchas for the given file path.

    Matches entries in ``_GOTCHA_MAP`` by prefix (checked first) then
    substring. Returns an empty string when no match is found.
    """
    if not file_path:
        return ""

    matched: list[str] = []
    for key, gotchas in _GOTCHA_MAP.items():
        if file_path.startswith(key) or key in file_path:
            matched.extend(gotchas)

    if not matched:
        return ""

    lines = ["## Relevant Known Gotchas"]
    for item in matched:
        lines.append(f"- {item}")
    result = "\n".join(lines)
    if len(result) > _GOTCHA_INJECTION_MAX_CHARS:
        result = result[:_GOTCHA_INJECTION_MAX_CHARS] + "\n# ... (truncated)"
    return result


def get_implementation_model(effort: str, file: str = "", action: str = "") -> str | None:
    """Return appropriate implementation model ID based on effort level and file path."""
    from scripts.executor.model_routing import get_implementation_model as _get_impl_model

    return _get_impl_model(effort, file, action)


def get_step_timeout_secs() -> int:
    """Return the implementation CLI timeout in seconds."""
    raw_timeout = os.environ.get("COPILOT_STEP_TIMEOUT_SECS", str(DEFAULT_STEP_TIMEOUT_SECS))
    try:
        return max(1, int(raw_timeout))
    except (TypeError, ValueError):
        return DEFAULT_STEP_TIMEOUT_SECS


def escalate_implementation_model(rec_id: str, current_model: str | None) -> str | None:
    """Increment failure count for rec_id and escalate implementation model tier."""
    from scripts.executor.model_routing import escalate_implementation_model as _escalate

    return _escalate(rec_id, current_model)


# Re-export failure counter so tests can reset state via sr_mod._IMPL_FAILURE_COUNT
from scripts.executor.model_routing import _IMPL_FAILURE_COUNT  # noqa: E402, F401, I001


# ---------------------------------------------------------------------------
# Python executable resolution
# ---------------------------------------------------------------------------

# Prefer the project venv Python over sys.executable. When the executor is
# launched from a terminal without venv activation (e.g. VS Code background
# tasks under bare pyenv), sys.executable resolves to the pyenv Python, which
# lacks project dependencies (yaml, ruff, pytest). Look for the venv Python at
# the canonical repo-relative path and fall back to sys.executable only if the
# venv is missing entirely.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = (
    _REPO_ROOT / ".venv" / "bin" / "python"  # Linux/macOS (CD.2 primary)
    if (_REPO_ROOT / ".venv" / "bin" / "python").exists()
    else _REPO_ROOT / ".venv" / "Scripts" / "python.exe"  # Why: CD.2/CD.3 -- Windows fallback
)
_PROJECT_PYTHON: str = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


def gather_step_context(step: dict, max_chars: int = 28000, recommendation_target_file: str = "") -> dict:
    """Gather file context for a step to inject into the implementation prompt.

    For action == 'modify': reads step['file'] if it exists.
        For large files (> _LARGE_FILE_THRESHOLD lines), attempts to extract
        a targeted function region based on context hints in step['title']
        or step['description']. The targeted region includes: imports section
        (first 60 lines) + 50 lines before target function + entire function body.
    For action == 'create': finds the most recently modified file with the same
        extension in the same directory to use as a coding pattern.
    Always looks for a corresponding test file at tests/test_{stem}.py.

    All content is capped at max_chars total (summed across all three keys).
    Oversized content is truncated with an '# ... (N lines omitted)' marker.

    Args:
        step: PlanStep dict with keys 'action' and 'file'.
        max_chars: Maximum total characters across all returned content strings.
        recommendation_target_file: Optional fallback file path when step has
            no 'file' field. Used to provide context for the recommendation's
            target file.

    Returns:
        dict with keys: file_content, test_content, pattern_content.
        Each value is a string (empty string if not found or not applicable).
    """
    result: dict[str, str] = {"file_content": "", "test_content": "", "pattern_content": ""}

    file_path_str: str = step.get("file", "") or recommendation_target_file
    if not file_path_str:
        return result

    file_path = Path(file_path_str)
    action: str = step.get("action", "").lower()

    def _read_truncated(path: Path, budget: int) -> str:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if len(content) <= budget:
            return content
        truncated = content[:budget]
        lines_omitted = content[budget:].count("\n")
        return truncated + f"\n# ... ({lines_omitted} lines omitted)\n"

    def _extract_targeted_function_region(path: Path, context_hint: str, budget: int) -> str:
        """Extract targeted function region from a large file using context hints.

        Scans context_hint for function name patterns, then extracts:
        - Imports section (first 60 lines)
        - 50 lines before target function definition
        - Entire function body (until next def or class at same indentation)

        Returns empty string if no function hint found or extraction fails.
        """
        try:
            full_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

        lines = full_content.splitlines(keepends=True)

        # Extract function name from context_hint
        # Pattern: "modify function_name" or "update function_name" or just "function_name"
        # Use word boundary after optional verb to prevent matching irrelevant words
        func_pattern = r"\b(?:modify|update|enhance|add|change|fix)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
        matches = re.findall(func_pattern, context_hint.lower())
        # Also try matching standalone function-like identifiers if no verb match
        if not matches:
            func_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]{3,})\b"
            matches = re.findall(func_pattern, context_hint.lower())
        if not matches:
            return ""

        # Try each extracted name as a potential function name
        for func_name in matches:
            # Find the function definition line
            # Use case-insensitive matching to support CamelCase function names
            func_def_pattern = re.compile(rf"^\s*def\s+{re.escape(func_name)}\s*\(", re.IGNORECASE)
            insertion_point = -1

            for i, line in enumerate(lines):
                if func_def_pattern.match(line):
                    insertion_point = i
                    break

            if insertion_point == -1:
                continue  # Try next function name candidate

            # Extract function body by finding the end of the function
            # Normalize indentation: count leading whitespace in visual columns
            # by expanding tabs to spaces (Python default: 8 spaces per tab)
            def get_indent_level(line: str) -> int:
                return len(line.expandtabs(8)) - len(line.expandtabs(8).lstrip())

            func_indent = get_indent_level(lines[insertion_point])
            func_end = insertion_point + 1

            for j in range(insertion_point + 1, len(lines)):
                line = lines[j]
                if line.strip() == "":
                    continue  # Skip blank lines
                current_indent = get_indent_level(line)
                # End when we hit next function/class definition at same or lower indentation
                if current_indent <= func_indent and (line.lstrip().startswith("def ") or line.lstrip().startswith("class ")):
                    func_end = j
                    break
            else:
                func_end = len(lines)  # Function extends to end of file

            # Build the targeted region
            region_parts = []

            # 1. Imports section (first 60 lines)
            import_section = "".join(lines[:60])
            region_parts.append(import_section)
            region_parts.append("\n# ... (imports section) ...\n\n")

            # 2. 50 lines before the function
            context_start = max(60, insertion_point - 50)
            if context_start < insertion_point:
                context_before = "".join(lines[context_start:insertion_point])
                region_parts.append(context_before)

            # 3. The target function body
            # Include func_end in the slice to capture the final line of the function
            function_body = "".join(lines[insertion_point : func_end + 1])
            region_parts.append(function_body)

            targeted_content = "".join(region_parts)

            # Apply budget limit
            if len(targeted_content) <= budget:
                return targeted_content

            truncated = targeted_content[:budget]
            lines_omitted = targeted_content[budget:].count("\n")
            return truncated + f"\n# ... ({lines_omitted} lines omitted)\n"

        return ""  # No valid function found

    remaining = max_chars

    if action == "modify" and file_path.exists():
        # Check if file is large and we have context hints
        try:
            file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            is_large_file = len(file_lines) > _LARGE_FILE_THRESHOLD
        except OSError:
            is_large_file = False

        if is_large_file:
            # Try to extract context hint from title or description
            context_hint = step.get("title", "") + " " + step.get("description", "")
            targeted_region = _extract_targeted_function_region(file_path, context_hint, remaining)

            if targeted_region:
                result["file_content"] = targeted_region
                remaining -= len(result["file_content"])
            else:
                # Fallback to top-of-file truncation
                result["file_content"] = _read_truncated(file_path, remaining)
                remaining -= len(result["file_content"])
        else:
            # Small file: use normal truncation
            result["file_content"] = _read_truncated(file_path, remaining)
            remaining -= len(result["file_content"])

    elif action == "create":
        parent = file_path.parent
        suffix = file_path.suffix
        if parent.is_dir() and suffix:
            candidates = sorted(parent.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
            candidates = [c for c in candidates if c.resolve() != file_path.resolve()]
            if candidates:
                result["pattern_content"] = _read_truncated(candidates[0], remaining)
                remaining -= len(result["pattern_content"])

    if remaining > 0:
        stem = file_path.stem
        test_file = Path("tests") / f"test_{stem}.py"
        if test_file.exists():
            result["test_content"] = _read_truncated(test_file, remaining)

    # Inject relevant Known Gotchas for the target file path.
    gotchas = _get_relevant_gotchas(file_path_str)
    if gotchas:
        result["file_content"] = result["file_content"] + "\n\n" + gotchas if result["file_content"] else gotchas

    return result


# ---------------------------------------------------------------------------
# Test file formatting (extracted to scripts/executor/formatters.py)
# Re-exports preserved for backward compatibility.
# ---------------------------------------------------------------------------
from scripts.executor.formatters import (  # noqa: E402, F401, I001
    _run_ruff_fix,
    _run_ruff_format,
    auto_format_test_files,
)


# ---------------------------------------------------------------------------
# Acceptance verification
# ---------------------------------------------------------------------------


def _normalize_acceptance(acceptance_cmd: object) -> str:
    """Normalize acceptance scalar-or-list to a str before any str methods are applied.

    Handles three shapes (T0.12.5 CD.29 shim; full typed-check dispatch deferred to T3.6):
      - str: returned unchanged.
      - list[str]: elements joined with ' && '. An empty list or all-empty-strings list
        is treated as null (empty string).
      - list[dict] TypedCheck: the 'command' field from each element is extracted then
        joined with ' && '. Only command_exit_zero / bare-command elements are executed at
        T0.12.5; full typed-check dispatch by type deferred to T3.6.
    """
    if isinstance(acceptance_cmd, str):
        return acceptance_cmd
    if not isinstance(acceptance_cmd, list) or not acceptance_cmd:
        return ""
    if isinstance(acceptance_cmd[0], dict):
        parts = [c.get("command", "") for c in acceptance_cmd if isinstance(c, dict)]
    else:
        parts = [str(p) for p in acceptance_cmd]
    joined = " && ".join(p for p in parts if p and p.strip())
    return joined


def run_acceptance(acceptance_cmd: object) -> bool:
    """Run acceptance command for a plan step.

    Returns True immediately if acceptance_cmd is empty or whitespace
    (no check required).

    Returns True when acceptance_cmd is non-empty but contains no extractable
    shell command -- prose-only acceptance fields are silently allowed
    (backwards compatible with existing step patterns).

    LLM-generated acceptance commands may be wrapped in backticks (markdown
    inline code) or contain shell operators (&&, |, >). The command is run
    via ``bash -c`` so Unix tools (grep, python, git) and shell operators work
    on all platforms including Windows (Git Bash required).

    Accepts str | list[str] | list[dict] (CD.29 TypedCheck) per T0.12.5 shim.
    """
    global _LAST_ACCEPTANCE_OUTPUT
    _LAST_ACCEPTANCE_OUTPUT = ""
    acceptance_cmd = _normalize_acceptance(acceptance_cmd)
    if not acceptance_cmd or not acceptance_cmd.strip():
        return True

    cmd_str = _extract_acceptance_command(acceptance_cmd)

    if not cmd_str:
        logger.debug(
            "[ACCEPTANCE] No executable command found in acceptance field; skipping check. Raw acceptance value: %r",
            acceptance_cmd[:200],
        )
        _LAST_ACCEPTANCE_OUTPUT = ""
        return True

    # Normalize 'python scripts/MODULE.py' → 'python -m scripts.MODULE'
    # Only apply this transformation if it's a safe mechanical fix
    cmd_str = re.sub(r"\bpython\s+scripts/(\w+)\.py\b", r"python -m scripts.\1", cmd_str)
    # Make plain grep presence checks case-insensitive unless the command already opts in.
    cmd_str = re.sub(r"\bgrep\s+-q(?![A-Za-z])", "grep -qi", cmd_str)

    # Reject python -c "..." one-liners: nested double-quotes in bash -c "..." produce
    # mangled commands on Windows (commander.js splits on the embedded "). The planner
    # should use grep or pytest instead. Fail fast with a clear message rather than
    # letting bash produce a cryptic syntax error.
    if re.search(r'\bpython\s+-c\s+["\']', cmd_str):
        logger.error(
            "[ACCEPTANCE] Banned pattern: python -c one-liner in acceptance command. "
            "Nested double-quotes break on Windows. "
            "Use grep -q or python -m pytest instead. Command: %r",
            cmd_str[:200],
        )
        _LAST_ACCEPTANCE_OUTPUT = "Acceptance command rejected: python -c one-liner is banned for Windows bash compatibility."
        return False

    bash = shutil.which("bash")
    if not bash:
        logger.warning("[ACCEPTANCE] bash not found; skipping acceptance check for: %r", cmd_str)
        _LAST_ACCEPTANCE_OUTPUT = ""
        return True

    _accept_env = os.environ.copy()
    _venv_bin = str(Path(_PROJECT_PYTHON).parent)
    _accept_env["PATH"] = _venv_bin + os.pathsep + _accept_env.get("PATH", "")

    # Strip executor-mode env vars to prevent contaminating acceptance behavior
    for var in _EXECUTOR_ACC_VARS:
        _accept_env.pop(var, None)

    with subprocess.Popen(
        [bash, "-c", cmd_str],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_accept_env,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait()
            logger.error("[ACCEPTANCE] Timeout (300s): %r", cmd_str)
            _LAST_ACCEPTANCE_OUTPUT = "Acceptance command timed out after 300s."
            return False

    _LAST_ACCEPTANCE_OUTPUT = f"{stdout}\n{stderr}".strip()
    passed = proc.returncode == 0
    if passed:
        logger.info("[ACCEPTANCE] Passed: %r (exit 0)", cmd_str)
    else:
        logger.error(
            "[ACCEPTANCE] Failed: %r (exit %d)\nstdout: %s\nstderr: %s",
            cmd_str,
            proc.returncode,
            stdout[:1500],
            stderr[:1500],
        )
    return passed


def get_last_acceptance_output() -> str:
    """Return stdout/stderr captured from the most recent acceptance command run."""
    return _LAST_ACCEPTANCE_OUTPUT


# ---------------------------------------------------------------------------
# Verification command runner (post-acceptance behavioural proof)
# ---------------------------------------------------------------------------

_LAST_VERIFICATION_OUTPUT: str = ""


def run_verification(verification_cmd: str) -> dict[str, object]:
    """Run a behavioural verification command after acceptance passes.

    Returns a dict with keys:
        passed (bool): True if the command exited 0.
        output (str): Combined stdout/stderr (truncated).
        skipped (bool): True if the command was empty or no executable
            command could be extracted.
        rejected (bool): True if the command was rejected (e.g. python -c).
        error (str): Reason for rejection or failure, empty on success.

    Unlike run_acceptance(), verification failure is advisory -- the caller
    decides whether to abort or continue.
    """
    global _LAST_VERIFICATION_OUTPUT
    _LAST_VERIFICATION_OUTPUT = ""

    if not verification_cmd or not verification_cmd.strip():
        return {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}

    cmd_str = _extract_acceptance_command(verification_cmd)
    if not cmd_str:
        logger.debug(
            "[VERIFICATION] No executable command found; skipping. Raw: %r",
            verification_cmd[:200],
        )
        return {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}

    # Same normalisations as run_acceptance
    cmd_str = re.sub(r"\bpython\s+scripts/(\w+)\.py\b", r"python -m scripts.\1", cmd_str)
    cmd_str = re.sub(r"\bgrep\s+-q(?![A-Za-z])", "grep -qi", cmd_str)

    # Ban python -c one-liners (Windows bash compatibility)
    if re.search(r'\bpython\s+-c\s+["\']', cmd_str):
        msg = "Verification command rejected: python -c one-liner is banned for Windows bash compatibility."
        logger.error("[VERIFICATION] Banned pattern: python -c in verification command: %r", cmd_str[:200])
        _LAST_VERIFICATION_OUTPUT = msg
        return {"passed": False, "output": msg, "skipped": False, "rejected": True, "error": msg}

    bash = shutil.which("bash")
    if not bash:
        logger.warning("[VERIFICATION] bash not found; skipping verification for: %r", cmd_str)
        return {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}

    _verify_env = os.environ.copy()
    _venv_bin = str(Path(_PROJECT_PYTHON).parent)
    _verify_env["PATH"] = _venv_bin + os.pathsep + _verify_env.get("PATH", "")
    for var in _EXECUTOR_ACC_VARS:
        _verify_env.pop(var, None)

    with subprocess.Popen(
        [bash, "-c", cmd_str],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_verify_env,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait()
            msg = "Verification command timed out after 300s."
            logger.error("[VERIFICATION] Timeout (300s): %r", cmd_str)
            _LAST_VERIFICATION_OUTPUT = msg
            return {"passed": False, "output": msg, "skipped": False, "rejected": False, "error": msg}

    output = f"{stdout}\n{stderr}".strip()
    _LAST_VERIFICATION_OUTPUT = output
    passed = proc.returncode == 0

    if passed:
        logger.info("[VERIFICATION] Passed: %r (exit 0)", cmd_str)
    else:
        logger.warning(
            "[VERIFICATION] Failed (advisory): %r (exit %d)\nstdout: %s\nstderr: %s",
            cmd_str,
            proc.returncode,
            stdout[:1500],
            stderr[:1500],
        )

    _error = "" if passed else f"exit {proc.returncode}"
    return {"passed": passed, "output": output, "skipped": False, "rejected": False, "error": _error}


def get_last_verification_output() -> str:
    """Return stdout/stderr captured from the most recent verification command run."""
    return _LAST_VERIFICATION_OUTPUT


def _extract_acceptance_command(acceptance_cmd: object) -> str:
    """Extract the first executable shell command from an acceptance field string.

    Returns an empty string if no command could be found.

    Accepts str | list[str] | list[dict] (CD.29 TypedCheck) -- normalizes via
    _normalize_acceptance before applying string-based extraction logic (T0.12.5 shim).

    Priority (highest to lowest):
    0. Fenced code block (``` ... ```) -- join the block body
    1. Inline-code span (`...`) -- content between first backtick pair
    2. Line-by-line scan -- fallback for plain-text commands
    """
    acceptance_cmd = _normalize_acceptance(acceptance_cmd)
    # Pass 0: fenced code block
    fence_match = re.search(r"```(?:\w+)?\n(.*?)```", acceptance_cmd, re.DOTALL)
    if fence_match:
        block_body = fence_match.group(1).strip()
        if block_body:
            return block_body

    # Pass 1: inline-code span
    inline_match = re.search(r"`([^`\n]+)`", acceptance_cmd)
    if inline_match:
        candidate = inline_match.group(1).strip()
        _shell_prefixes = (
            "python",
            "pytest",
            "grep",
            "git",
            "gh",
            "bash",
            "sh",
            "cat",
            "ls",
            "find",
            "echo",
            "wc",
            "awk",
            "sed",
            "test",
            "[",
        )
        if any(candidate.startswith(p) for p in _shell_prefixes) or "/" in candidate or "--" in candidate:
            return candidate

    # Pass 2: line-by-line scan
    _lang_tags = {"bash", "sh", "python", "python3", "zsh", "fish", "shell"}
    for raw_line in acceptance_cmd.splitlines():
        line = raw_line.strip().strip("`").strip()
        if not line or line == "---" or line.startswith("#"):
            continue
        if line.lower() in _lang_tags:
            continue
        if any(
            line.startswith(p)
            for p in (
                "python",
                "pytest",
                "grep",
                "git",
                "gh",
                "bash",
                "sh",
                "cat",
                "ls",
                "find",
                "echo",
                "wc",
                "awk",
                "sed",
            )
        ):
            return line
        if "/" in line or "--" in line or (line and line[0].islower()):
            return line

    return ""


# ---------------------------------------------------------------------------
# Step implementation
# ---------------------------------------------------------------------------


def _detect_ghost_step(action: str, step_file: str) -> bool:
    """Detect if action is 'modify' but git diff shows no changes.

    Returns True if ghost step detected (modify action with no file changes),
    False otherwise.
    """
    if action != "modify":
        return False

    try:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", step_file],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if diff_result.returncode == 0 and not diff_result.stdout.strip():
            logger.error(
                "[GHOST-STEP] modify action but git diff shows no changes — possible copilot LLM failure to write files"
            )
            return True
    except Exception as e:
        logger.warning("[GHOST-STEP] error detecting ghost step: %s", e)

    return False


def _list_meaningful_worktree_changes() -> list[str]:
    """Return non-log, non-cache worktree paths with uncommitted changes."""

    ignored_prefixes = (
        "logs/",
        ".mypy_cache/",
        ".pytest_cache/",
        "__pycache__/",
    )
    changed_paths: set[str] = set()
    commands = (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )

    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except Exception as e:
            logger.warning("[GHOST-STEP] error listing worktree changes: %s", e)
            continue

        if result.returncode != 0:
            continue

        for raw_path in result.stdout.splitlines():
            normalized_path = raw_path.strip()
            if " -> " in normalized_path:
                normalized_path = normalized_path.split(" -> ", 1)[1]
            normalized_path = normalized_path.replace("\\", "/")
            if not normalized_path or normalized_path.startswith(ignored_prefixes):
                continue
            changed_paths.add(normalized_path)

    return sorted(changed_paths)


def implement_step(
    step: dict,
    rec_id: str,
    step_n: int,
    total_steps: int,
    resume_session_id: Optional[str] = None,
    recommendation_target_file: str = "",
    effort: str = "",
) -> tuple[StepOutcome, float, str, str]:
    """Implement a single step via CLI — atomic call.

    Args:
        step: Plan step dict.
        rec_id: Recommendation ID.
        step_n: 1-based step number.
        total_steps: Total steps in the plan.
        resume_session_id: Copilot CLI session UUID from the previous step.
        recommendation_target_file: Optional recommendation target file path
            for fallback context when step has no explicit file field.
        effort: Effort level (XS/S/M/L/XL) used to select implementation model.

    Returns:
        Tuple of (success, prompt_hash, session_id).
    """
    transcript_path = f"logs/transcripts/impl-{rec_id}-step{step_n}-{int(time.time())}.md"
    effort = effort or step.get("effort", "")

    if effort.upper() in ("XS", "S") and resume_session_id:
        logger.info(
            "[IMPL] Step %d: effort=%s -- skipping session resume (token cost optimisation)",
            step_n,
            effort,
        )
        resume_session_id = None

    step_text = (
        f"### Step {step['n']}: {step.get('title', '')}\n"
        f"**File**: {step.get('file', 'not specified')}\n"
        f"**Action**: {step.get('action', 'modify')}\n"
        f"**Description**: {step.get('description', '')}\n"
        f"**Acceptance**: {step.get('acceptance', '')}"
    )

    ctx = gather_step_context(step, recommendation_target_file=recommendation_target_file)
    total_ctx_chars = sum(len(v) for v in ctx.values())
    logger.info(
        "[IMPL] Context injected: %d chars (file=%d, test=%d, pattern=%d)",
        total_ctx_chars,
        len(ctx["file_content"]),
        len(ctx["test_content"]),
        len(ctx["pattern_content"]),
    )

    _header_file = "\n## Current File Content\nThe file to be modified already exists. Make targeted changes only.\n\n```\n"
    _header_test = "\n## Existing Tests\nUse these as a guide for style, fixtures, and coverage expectations.\n\n```python\n"
    _header_pattern = "\n## Pattern File (for new file creation)\nUse this as a style and structure reference.\n\n```\n"
    _footer = "\n```\n"

    file_content_section = (_header_file + ctx["file_content"] + _footer) if ctx["file_content"] else ""
    test_content_section = (_header_test + ctx["test_content"] + _footer) if ctx["test_content"] else ""
    pattern_content_section = (_header_pattern + ctx["pattern_content"] + _footer) if ctx["pattern_content"] else ""

    template, impl_prompt_hash = load_prompt("implement-step")
    prompt = template.format(
        step_text=step_text,
        rec_id=rec_id,
        step_n=step_n,
        total_steps=total_steps,
        file_content_section=file_content_section,
        test_content_section=test_content_section,
        pattern_content_section=pattern_content_section,
    )

    acceptance_cmd = step.get("acceptance", "").strip()
    if resume_session_id:
        logger.info("[IMPL] Step %d resuming session %s (KV-cache reuse)", step_n, resume_session_id[:8])
    elif step_n > 1:
        logger.info("[IMPL] Step %d resuming most recent session via --continue", step_n)
    logger.info(
        "[STEP %d/%d START] action=%s | file=%s | prompt_hash=%s",
        step_n,
        total_steps,
        step.get("action", "?"),
        step.get("file", "(none)"),
        impl_prompt_hash,
    )
    if acceptance_cmd:
        logger.info("[STEP %d/%d] acceptance=%s", step_n, total_steps, acceptance_cmd[:120])
    else:
        logger.warning("[STEP %d/%d] acceptance=(EMPTY — step result will not be verified)", step_n, total_steps)

    _step_started_iso = datetime.now(timezone.utc).isoformat()
    _tel_step: dict = {
        "outcome": StepOutcome.CLI_ERROR.value,
        "reqs": 0.0,
        "hash": impl_prompt_hash,
        "transcript": transcript_path,
    }

    try:
        context_file_path = build_context_path("impl", rec_id, step_n)
        inline_instruction = (
            f"Implement step {step_n}/{total_steps}. "
            f"Follow the step implementation requirements and acceptance criteria. "
            f"@{context_file_path}"
        )

        # Resume from the planning session so all impl steps reuse the cached
        # GEMINI.md context from the plan generation turn instead of cold-starting.
        # resume_session_id is the planning session captured by plan.planning_session_id
        # and threaded here via execute_recommendation.py.
        if resume_session_id:
            logger.info("[IMPL] Step %d resuming planning session %s", step_n, resume_session_id[:8])

        _step_timeout = get_step_timeout_secs()
        result = llm_call(
            prompt,
            model=get_implementation_model(
                effort,
                step.get("file", ""),
                step.get("action", ""),
            )
            or None,
            timeout=_step_timeout,
            check=False,
            context_file_path=context_file_path,
            inline_instruction=inline_instruction,
            purpose="implementation",
            resume_session_id=resume_session_id,
        )

        # Write synthetic transcript for Gemini CLI (which has no --share)
        try:
            _transcript_dir = Path("logs/transcripts")
            _transcript_dir.mkdir(parents=True, exist_ok=True)
            _content_preview = result.content[:3000] if result.content else "(empty)"
            _transcript_text = (
                f"# Gemini CLI Implementation Transcript\n\n"
                f"- **Rec**: {rec_id}\n"
                f"- **Step**: {step_n}/{total_steps}\n"
                f"- **Model**: {result.model}\n"
                f"- **Session**: {result.session_id or '(none)'}\n"
                f"- **Exit code**: {result.exit_code}\n"
                f"- **Tokens in**: {result.tokens_in}\n"
                f"- **Tokens out**: {result.tokens_out}\n"
                f"- **File**: {step.get('file', '(none)')}\n\n"
                f"## Prompt (first 500 chars)\n\n```\n{prompt[:500]}\n```\n\n"
                f"## Response\n\n```\n{_content_preview}\n```\n\n"
                f"## Stderr\n\n```\n{getattr(result, 'stderr', '') or '(none)'}\n```\n"
            )
            Path(transcript_path).write_text(_transcript_text, encoding="utf-8")
            logger.info("[IMPL] Transcript written: %s", transcript_path)
        except OSError as _te:
            logger.warning("[IMPL] Failed to write transcript: %s", _te)

        if result.exit_code != 0:
            logger.error("[IMPL] Step %d failed: exit code %d", step_n, result.exit_code)
            if hasattr(result, "stderr") and result.stderr:
                logger.error("[IMPL] stderr: %s", result.stderr[:500])
            step_reqs = result.cost_usd
            _tel_step.update({"outcome": StepOutcome.CLI_ERROR.value, "reqs": step_reqs})
            return StepOutcome.CLI_ERROR, step_reqs, impl_prompt_hash, ""

        step_reqs = result.cost_usd
        logger.info(
            "[IMPL] Step %d completed (%s tokens, %.2f premium requests)",
            step_n,
            result.tokens_in + result.tokens_out,
            step_reqs,
        )

        if _detect_ghost_step(step.get("action", "modify"), step.get("file", "")):
            meaningful_changes = _list_meaningful_worktree_changes()
            extracted_acceptance = _extract_acceptance_command(acceptance_cmd)
            if not meaningful_changes and extracted_acceptance and run_acceptance(acceptance_cmd):
                logger.warning(
                    "[GHOST-STEP] Step %d made no new edits, but acceptance already passes; treating it as complete",
                    step_n,
                )
                _tel_step.update({"outcome": StepOutcome.SUCCESS.value, "reqs": step_reqs})
                return StepOutcome.SUCCESS, step_reqs, impl_prompt_hash, result.session_id or ""

            if meaningful_changes:
                logger.error(
                    "[GHOST-STEP] Target file unchanged while other files changed: %s",
                    ", ".join(meaningful_changes[:5]),
                )
            logger.error("[GHOST-STEP] Failing step %d due to ghost step detection", step_n)
            _tel_step.update({"outcome": StepOutcome.GHOST_STEP.value, "reqs": step_reqs})
            return StepOutcome.GHOST_STEP, step_reqs, impl_prompt_hash, ""

        if not auto_format_test_files(step.get("file", "")):
            logger.error("[FORMAT] Auto-format failed for step %d", step_n)
            _tel_step.update({"outcome": StepOutcome.FORMAT_ERROR.value, "reqs": step_reqs})
            return StepOutcome.FORMAT_ERROR, step_reqs, impl_prompt_hash, ""

        # Auto-fix trivially fixable lint issues (I001, F401, etc.)
        step_file = step.get("file", "")
        ruff_targets = [step_file] if step_file else []
        if not _run_ruff_fix(ruff_targets):
            logger.error("[RUFF] Auto-fix failed for step %d", step_n)
            _tel_step.update({"outcome": StepOutcome.RUFF_ERROR.value, "reqs": step_reqs})
            return StepOutcome.RUFF_ERROR, step_reqs, impl_prompt_hash, ""
        if not _run_ruff_format(ruff_targets):
            logger.error("[FORMAT] Post-fix format failed for step %d", step_n)
            _tel_step.update({"outcome": StepOutcome.FORMAT_ERROR.value, "reqs": step_reqs})
            return StepOutcome.FORMAT_ERROR, step_reqs, impl_prompt_hash, ""

        logger.info("[VALIDATE] Running validate.py after step %d...", step_n)
        with subprocess.Popen(
            [_PROJECT_PYTHON, "scripts/validate.py", "--pre"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as val_proc:
            try:
                val_stdout, val_stderr = val_proc.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                kill_process_tree(val_proc.pid)
                val_proc.wait()
                logger.error("[VALIDATE] Timeout (120s) after step %d", step_n)
                _tel_step.update({"outcome": StepOutcome.VALIDATE_TIMEOUT.value, "reqs": step_reqs})
                return StepOutcome.VALIDATE_TIMEOUT, step_reqs, impl_prompt_hash, ""
        if val_proc.returncode != 0:
            combined = (val_stdout + "\n" + val_stderr).strip()
            output_lines = combined.splitlines()
            capped = "\n".join(output_lines[-100:])
            if len(output_lines) > 100:
                capped = f"... ({len(output_lines) - 100} earlier lines — see transcript)\n" + capped
            logger.error("[VALIDATE] Failed after step %d:\n%s", step_n, capped)
            # Persist full output for post-mortem when terminal scrollback is lost.
            _ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            _debug_path = Path(f"logs/debug/validate-{rec_id}-step{step_n}-{_ts}.txt")
            try:
                _debug_path.parent.mkdir(parents=True, exist_ok=True)
                _debug_path.write_text(combined, encoding="utf-8")
                logger.info("[VALIDATE] Full output saved: %s", _debug_path)
            except OSError as _e:
                logger.warning("[VALIDATE] Could not save debug output: %s", _e)
            _tel_step.update({"outcome": StepOutcome.VALIDATE_FAILED.value, "reqs": step_reqs})
            return StepOutcome.VALIDATE_FAILED, step_reqs, impl_prompt_hash, ""
        logger.info("[VALIDATE] Passed after step %d", step_n)

        if not run_acceptance(step.get("acceptance", "")):
            logger.error("[ACCEPTANCE] Failed for step %d", step_n)
            _tel_step.update({"outcome": StepOutcome.ACCEPTANCE_FAILED.value, "reqs": step_reqs})
            return StepOutcome.ACCEPTANCE_FAILED, step_reqs, impl_prompt_hash, ""

        _tel_step.update({"outcome": StepOutcome.SUCCESS.value, "reqs": step_reqs})
        return StepOutcome.SUCCESS, step_reqs, impl_prompt_hash, result.session_id or ""

    except subprocess.TimeoutExpired:
        logger.error("[IMPL] Step %d timeout", step_n)
        _tel_step["outcome"] = StepOutcome.VALIDATE_TIMEOUT.value
        return StepOutcome.VALIDATE_TIMEOUT, 0.0, impl_prompt_hash, ""
    except Exception as e:
        logger.error("[IMPL] Step %d error: %s", step_n, e)
        _tel_step["outcome"] = StepOutcome.CLI_ERROR.value
        return StepOutcome.CLI_ERROR, 0.0, impl_prompt_hash, ""
    finally:
        _step_ended_iso = datetime.now(timezone.utc).isoformat()
        try:
            emit_step(
                step_number=step_n,
                total_steps=total_steps,
                title=step.get("title", f"Step {step_n}"),
                outcome=_tel_step["outcome"],
                started_at=_step_started_iso,
                ended_at=_step_ended_iso,
                target_file=step.get("file") or None,
                action=step.get("action") or None,
                acceptance_command=acceptance_cmd or None,
                prompt_hash=_tel_step["hash"],
                transcript_path=(_tel_step["transcript"] if Path(_tel_step["transcript"]).exists() else None),
            )
            _final_outcome = _tel_step["outcome"]
            if _final_outcome == StepOutcome.GHOST_STEP.value:
                emit_process_event(
                    tier="decision",
                    category="ghost_step",
                    severity="info",
                    description=f"Step {step_n} produced no changes",
                )
            elif _final_outcome == StepOutcome.VALIDATE_FAILED.value:
                emit_process_event(
                    tier="rework",
                    category="validate_failed",
                    severity="warning",
                    description=f"Step {step_n} validation failed",
                )
            elif _final_outcome == StepOutcome.ACCEPTANCE_FAILED.value:
                emit_process_event(
                    tier="rework",
                    category="acceptance_failed",
                    severity="warning",
                    description=f"Step {step_n} acceptance failed",
                )
            _transcript_file = _tel_step["transcript"]
            if Path(_transcript_file).exists():
                emit_transcript(
                    purpose="implementation",
                    local_path=_transcript_file,
                    size_bytes=Path(_transcript_file).stat().st_size,
                    rec_id=rec_id,
                )
        except Exception:
            pass  # telemetry must never break the step path


# ---------------------------------------------------------------------------
# Pre-commit scope enforcement
# ---------------------------------------------------------------------------


def _enforce_step_scope(step: dict, step_n: int) -> bool:
    """Verify worktree changes are limited to the declared step file.

    Compares the normalized declared step file path against non-log
    worktree changes reported by ``git diff --name-only`` (unstaged),
    ``git diff --name-only --cached`` (staged), and
    ``git ls-files --others --exclude-standard`` (untracked).

    Paths are normalized to forward-slash POSIX form for comparison
    because Git always reports paths with forward slashes regardless
    of the OS.

    Returns True if all changed files are in scope (the declared step
    file, its corresponding test file, or log/cache paths already
    filtered by ``_list_meaningful_worktree_changes``). Returns False
    and logs an error when out-of-scope files are detected.
    """
    step_file = (step.get("file", "") or "").strip()
    if not step_file:
        # No declared file -- nothing to enforce.
        return True

    # Normalize to POSIX forward-slash form to match git output.
    declared = step_file.replace("\\", "/").strip("/")

    # Build the set of allowed paths: the declared step file and its
    # conventional test file (tests/test_{stem}.py).
    allowed: set[str] = {declared}
    try:
        stem = Path(declared).stem
        if stem:
            test_path = f"tests/test_{stem}.py"
            allowed.add(test_path)
    except Exception:
        pass

    changed = _list_meaningful_worktree_changes()
    if not changed:
        return True

    out_of_scope = [p for p in changed if p not in allowed]
    if not out_of_scope:
        return True

    logger.error(
        "[SCOPE] Step %d declared file %r but worktree has out-of-scope changes: %s",
        step_n,
        declared,
        ", ".join(out_of_scope),
    )
    return False


# ---------------------------------------------------------------------------
# Git commit
# ---------------------------------------------------------------------------


def commit_step(step: dict, rec_id: str, step_n: int) -> tuple[bool, str]:
    """Commit changes from a single step.

    Runs scope enforcement before ``git add -A`` to prevent out-of-scope
    files from being swept into the step commit.

    Retries up to 3 times: pre-commit hooks may modify files and abort the
    first attempt.

    Returns:
        Tuple of (success, diff_stat) where diff_stat is the output of
        ``git diff HEAD~1 --stat`` (empty on failure or nothing to commit).
    """
    try:
        if not _enforce_step_scope(step, step_n):
            logger.error(
                "[GIT] Scope enforcement failed for step %d — aborting commit",
                step_n,
            )
            return False, ""

        msg = f"impl({rec_id}): step {step_n} - {step.get('title', 'untitled')[:50]}"
        for attempt in range(1, 4):
            subprocess.run(
                ["git", "add", "-A"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                commit_cmd = ["git", "commit", "-m", msg]
                if attempt == 3:
                    commit_cmd.append("--no-verify")
                subprocess.run(
                    commit_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                break
            except subprocess.CalledProcessError as e:
                err_out = (e.stderr or "") + (e.stdout or "")
                if "nothing to commit" in err_out or "nothing added to commit" in err_out:
                    logger.info("[GIT] No changes to commit for step %d", step_n)
                    return True, ""
                if attempt < 3 and ("files were modified by this hook" in err_out or "modified by hooks" in err_out):
                    logger.warning("[GIT] Pre-commit hooks modified files, retrying (%d/3)", attempt)
                    continue
                raise
        logger.info("[GIT] Committed step %d", step_n)

        diff_stat = ""
        try:
            diff_result = subprocess.run(
                ["git", "diff", "HEAD~1", "--stat"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if diff_result.returncode == 0:
                diff_stat = diff_result.stdout.strip()
        except Exception:
            pass

        return True, diff_stat
    except subprocess.CalledProcessError as e:
        if "nothing to commit" in str(e.stderr):
            logger.info("[GIT] No changes to commit for step %d", step_n)
            return True, ""
        logger.error("[GIT] Commit failed for step %d: %s", step_n, e)
        return False, ""


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def _append_step_telemetry(
    rec_id: str,
    step_n: int,
    total_steps: int,
    prompt_hash: str,
    diff_stat: str,
    model: str = "",
) -> None:
    """Append per-step telemetry to logs/.execution-step-telemetry.jsonl.

    Best-effort: logs a warning on any error but does not raise.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rec_id": rec_id,
        "step_n": step_n,
        "total_steps": total_steps,
        "prompt_hash": prompt_hash,
        "diff_stat": diff_stat,
        "model": model,
    }
    try:
        if get_backend() == "s3":
            append_jsonl(".execution-step-telemetry.jsonl", entry)
        else:
            with STEP_TELEMETRY_JSONL.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        logger.info(
            "[TELEMETRY] Step %d/%d logged (model=%s)",
            step_n,
            total_steps,
            model or "unknown",
        )
    except OSError as e:
        logger.warning("[TELEMETRY] Failed to write step telemetry: %s", e)
