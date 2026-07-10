"""Acceptance and verification command running for the executor.

Extracted from scripts/executor/step_runner.py (SLOC decomposition, Decision
102/104 facade mechanism). Runs step acceptance/verification shell commands
and tracks their last captured output. Routed-name references (subprocess,
Path, kill_process_tree, _EXECUTOR_ACC_VARS, _PROJECT_PYTHON) resolve through
the scripts.executor.step_runner facade via a function-local import so the
existing test suite's patches on scripts.executor.step_runner.<name> keep
intercepting with zero migration.
"""

import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

_LAST_ACCEPTANCE_OUTPUT = ""
_LAST_VERIFICATION_OUTPUT: str = ""


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
    import scripts.executor.step_runner as _sr

    global _LAST_ACCEPTANCE_OUTPUT
    _LAST_ACCEPTANCE_OUTPUT = ""
    acceptance_cmd = _normalize_acceptance(acceptance_cmd)
    if not acceptance_cmd or not acceptance_cmd.strip():
        return True

    cmd_str = _sr._extract_acceptance_command(acceptance_cmd)

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
    _venv_bin = str(_sr.Path(_sr._PROJECT_PYTHON).parent)
    _accept_env["PATH"] = _venv_bin + os.pathsep + _accept_env.get("PATH", "")

    # Strip executor-mode env vars to prevent contaminating acceptance behavior
    for var in _sr._EXECUTOR_ACC_VARS:
        _accept_env.pop(var, None)

    with _sr.subprocess.Popen(
        [bash, "-c", cmd_str],
        stdout=_sr.subprocess.PIPE,
        stderr=_sr.subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_accept_env,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except _sr.subprocess.TimeoutExpired:
            _sr.kill_process_tree(proc.pid)
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
    import scripts.executor.step_runner as _sr

    global _LAST_VERIFICATION_OUTPUT
    _LAST_VERIFICATION_OUTPUT = ""

    if not verification_cmd or not verification_cmd.strip():
        return {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}

    cmd_str = _sr._extract_acceptance_command(verification_cmd)
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
    _venv_bin = str(_sr.Path(_sr._PROJECT_PYTHON).parent)
    _verify_env["PATH"] = _venv_bin + os.pathsep + _verify_env.get("PATH", "")
    for var in _sr._EXECUTOR_ACC_VARS:
        _verify_env.pop(var, None)

    with _sr.subprocess.Popen(
        [bash, "-c", cmd_str],
        stdout=_sr.subprocess.PIPE,
        stderr=_sr.subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_verify_env,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except _sr.subprocess.TimeoutExpired:
            _sr.kill_process_tree(proc.pid)
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
