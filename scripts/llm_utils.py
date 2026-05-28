"""Shared utilities for LLM inference -- relocated from copilot_wrapper.py.

Contains process safety functions, path builders, model constants, and the
``LLMResponseError`` exception (renamed from ``CopilotResponseError``).

This module is safe to import at module scope in any script; it has no
heavy dependencies or circular import risks.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

# Defaults are Bedrock model IDs -- used when LLM_PROVIDER=bedrock (dormant fallback).
# When LLM_PROVIDER=gemini, the model_registry resolver handles model selection
# and returns None for Gemini auto mode; these constants are not consulted.
MODEL_PLANNING = os.getenv("COPILOT_MODEL_PLANNING", "deepseek.v3.2")
MODEL_EXECUTION = os.getenv("COPILOT_MODEL_EXECUTION", "deepseek.v3.2")
MODEL_CLASSIFICATION = os.getenv("COPILOT_MODEL_CLASSIFICATION", "")

# Tools excluded from all planning-phase LLM calls.
# Stripping write/exec tools forces text-only output (plans, not actions).
_PLAN_EXCLUDED_TOOLS = ["bash", "powershell", "edit", "create", "apply_patch", "task"]

# ---------------------------------------------------------------------------
# Process safety
# ---------------------------------------------------------------------------

_MAX_PYTHON_PROCESSES = 50


def count_python_processes() -> int:
    """Count the number of Python processes currently running."""
    try:
        if sys.platform == "win32":  # Intentional: CD.3 -- Windows tasklist branch
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            return sum(1 for line in result.stdout.splitlines() if "python" in line.lower())
        else:
            result = subprocess.run(
                ["pgrep", "-c", "python"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            return int(result.stdout.strip()) if result.returncode == 0 else 0
    except Exception:  # noqa: BLE001
        return 0


def check_process_killswitch(label: str = "llm_client") -> None:
    """Abort if too many Python processes are running."""
    n = count_python_processes()
    if n > _MAX_PYTHON_PROCESSES:
        msg = f"[KILLSWITCH] {label}: {n} Python processes detected (limit {_MAX_PYTHON_PROCESSES}). Aborting to prevent OOM."
        logger.critical(msg)
        print(msg, file=sys.stderr, flush=True)
        sys.exit(99)


def check_recursion_guard() -> None:
    """Abort if this process was spawned by another executor instance."""
    depth = int(os.environ.get("_EXECUTOR_DEPTH", "0"))
    if depth >= 1:
        msg = f"[RECURSION GUARD] Executor re-invoked at depth {depth}. Refusing to start to prevent recursive agent loop."
        logger.critical(msg)
        print(msg, file=sys.stderr, flush=True)
        sys.exit(98)


def _assign_job_object() -> None:
    """Assign the current process to a Windows Job Object.

    When the Job Object is closed (i.e. when this process exits), Windows
    will terminate every process in the job.  No-op on non-Windows.
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            logger.warning("[JOB] CreateJobObjectW failed")
            return

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        JOBOBJECT_EXTENDED_LIMIT_INFO_CLASS = 9
        kernel32.SetInformationJobObject(
            h_job,
            JOBOBJECT_EXTENDED_LIMIT_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )

        kernel32.AssignProcessToJobObject(h_job, kernel32.GetCurrentProcess())
        logger.info("[JOB] Process assigned to Job Object (kill-on-close enabled)")

        _assign_job_object._handle = h_job  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[JOB] Failed to create Job Object: %s", exc)


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its descendants."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        import signal as _signal

        try:
            os.killpg(os.getpgid(pid), _signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                os.kill(pid, _signal.SIGKILL)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Path and hash helpers
# ---------------------------------------------------------------------------


def build_context_path(
    phase: str,
    rec_id: str,
    step_n: Optional[int] = None,
) -> str:
    """Build a context file path for a given phase, recommendation, and step."""
    base_name = f"{phase}-context-{rec_id}"
    if step_n is not None:
        base_name += f"-step{step_n}"
    return f"logs/debug/{base_name}.md"


def _compute_prompt_hash(prompt: str) -> str:
    """Return first 12 hex chars of SHA-256 hash of prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class LLMResponseError(RuntimeError):
    """Raised when the LLM returns an unusable response.

    Covers: question/clarification requests, empty output, and exit-code failures
    that the caller chose to surface as hard errors.  Renamed from
    ``CopilotResponseError`` during the Bedrock migration.
    """
