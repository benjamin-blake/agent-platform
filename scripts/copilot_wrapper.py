# complexity-waiver: decision-43
"""
DEPRECATED: This module is superseded by scripts/llm_client.py.

Subprocess wrapper for GitHub Copilot CLI with OTel metric capture.
Retained for rollback only; removal is owned by CD.28's
PLAN-retire-copilot-sdk follow-on. New code should import from
scripts.llm_client instead.

Debug mode
----------
Set COPILOT_DEBUG=1 to write every call's prompt, command, and response to
logs/debug/.  Files are named by an auto-incrementing call counter so nothing
is overwritten between calls.
"""

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, TypedDict

_wrapper_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process safety: prevent recursive agent invocation and orphan accumulation
# ---------------------------------------------------------------------------

# Maximum number of Python processes allowed before the kill-switch triggers.
# Tuned conservatively: a normal dev session has <20 Python processes.
_MAX_PYTHON_PROCESSES = 50


def count_python_processes() -> int:
    """Count the number of Python processes currently running.

    Uses ``tasklist`` on Windows and ``pgrep`` on Unix.  Returns 0 on any
    error (don't block execution because of a monitoring failure).
    """
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
            # Each running python.exe produces one CSV line
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
    except Exception:
        return 0


def check_process_killswitch(label: str = "copilot_wrapper") -> None:
    """Abort if too many Python processes are running.

    Call at script entry points (main(), execute_recommendation, etc.) to
    prevent cascading fork explosions from draining system memory.

    Args:
        label: Human-readable name for the caller, used in the log message.

    Raises:
        SystemExit: If the number of Python processes exceeds _MAX_PYTHON_PROCESSES.
    """
    n = count_python_processes()
    if n > _MAX_PYTHON_PROCESSES:
        msg = f"[KILLSWITCH] {label}: {n} Python processes detected (limit {_MAX_PYTHON_PROCESSES}). Aborting to prevent OOM."
        _wrapper_logger.critical(msg)
        print(msg, file=sys.stderr, flush=True)
        sys.exit(99)


def check_recursion_guard() -> None:
    """Abort if this process was spawned by another executor instance.

    The executor sets ``_EXECUTOR_DEPTH`` in the environment before invoking
    the Copilot CLI.  If the CLI (or a subagent) re-invokes the executor,
    this guard detects the env var and refuses to start, breaking the
    recursive loop.

    Raises:
        SystemExit: If ``_EXECUTOR_DEPTH`` >= 1.
    """
    depth = int(os.environ.get("_EXECUTOR_DEPTH", "0"))
    if depth >= 1:
        msg = f"[RECURSION GUARD] Executor re-invoked at depth {depth}. Refusing to start to prevent recursive agent loop."
        _wrapper_logger.critical(msg)
        print(msg, file=sys.stderr, flush=True)
        sys.exit(98)


def _assign_job_object() -> None:
    """Assign the current process to a Windows Job Object.

    When the Job Object is closed (i.e. when this process exits), Windows
    will terminate every process in the job -- including all children and
    grandchildren.  This is the definitive fix for orphaned subprocess
    accumulation on Windows.

    On non-Windows platforms this is a no-op.
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        # CreateJobObjectW(lpJobAttributes, lpName)
        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            _wrapper_logger.warning("[JOB] CreateJobObjectW failed")
            return

        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION structure (partial)
        # We only need to set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
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

        # SetInformationJobObject(hJob, JobObjectExtendedLimitInformation, &info, sizeof)
        JOBOBJECT_EXTENDED_LIMIT_INFO_CLASS = 9
        kernel32.SetInformationJobObject(
            h_job,
            JOBOBJECT_EXTENDED_LIMIT_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )

        # AssignProcessToJobObject(hJob, GetCurrentProcess())
        kernel32.AssignProcessToJobObject(h_job, kernel32.GetCurrentProcess())
        _wrapper_logger.info("[JOB] Process assigned to Job Object (kill-on-close enabled)")

        # Store handle to prevent GC from closing the Job Object prematurely
        _assign_job_object._handle = h_job  # type: ignore[attr-defined]
    except Exception as exc:
        _wrapper_logger.warning("[JOB] Failed to create Job Object: %s", exc)


class CopilotResponseError(RuntimeError):
    """Raised when the Copilot CLI returns an unusable response.

    Covers: question/clarification requests, empty output, and exit-code failures
    that the caller chose to surface as hard errors.
    """


# Patterns that indicate the model is asking for clarification rather than
# producing the requested output.  Matched against the last 600 chars of stdout.
_QUESTION_SIGNATURES: list[re.Pattern[str]] = [
    re.compile(r"which\s+(one|recommendation|option|file)\b", re.IGNORECASE),
    re.compile(r"could you\s+(please\s+)?(clarify|specify|provide|confirm)", re.IGNORECASE),
    re.compile(r"your message ends with", re.IGNORECASE),
    re.compile(r"nothing follows", re.IGNORECASE),
    re.compile(r"can you (confirm|tell me|let me know)", re.IGNORECASE),
    re.compile(r"what\s+(is|are)\s+the\s+recommendation", re.IGNORECASE),
    re.compile(r"I('m| am) not sure (which|what)", re.IGNORECASE),
]


def validate_response(text: str, context: str = "") -> None:
    """Raise CopilotResponseError if the CLI returned a clarification request.

    Only checks for question patterns - callers are responsible for raising on
    empty content when that applies to their use-case.
    """
    tail = text.strip()[-600:]
    for pattern in _QUESTION_SIGNATURES:
        if pattern.search(tail):
            raise CopilotResponseError(
                f"CLI asked for clarification instead of producing output"
                f"{': ' + context if context else ''}.\n"
                f"Response tail: {text.strip()[-300:]}"
            )


@dataclass
class CopilotResult:
    """Result of a copilot CLI invocation."""

    exit_code: int
    stdout: str
    stderr: str
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    transcript_path: Optional[str] = None
    session_id: Optional[str] = None


class ParsedJsonlOutput(TypedDict):
    """Typed output of parse_jsonl_output().

    Keys:
        - content: Concatenated text from all assistant.message events
        - session_id: Session ID from result.sessionId (empty string if absent)
        - exit_code: Exit code from result.exitCode (0 if absent)
    """

    content: str
    session_id: str
    exit_code: int


def parse_jsonl_output(raw: str) -> ParsedJsonlOutput:
    """Parse JSONL output from copilot CLI --output-format=json.

    Extracts content from ``assistant.message`` events and session metadata
    from the ``result`` event.  See docs/contracts/cli-json-output.md for the
    full schema.

    Args:
        raw: Raw JSONL string from the CLI, one JSON object per line.

    Returns:
        dict with keys:
            - ``content``: str -- concatenated text from all assistant.message events
            - ``session_id``: str -- from result.sessionId (empty string if absent)
            - ``exit_code``: int -- from result.exitCode (0 if absent)

    Raises:
        CopilotResponseError: If any non-empty line fails JSON parsing.
    """
    content_parts: list[str] = []
    session_id = ""
    exit_code = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CopilotResponseError(f"Failed to parse JSONL output line: {exc}\nLine: {line!r}") from exc

        event_type = obj.get("type", "")
        if event_type == "assistant.message":
            data = obj.get("data", {})
            content_parts.append(data.get("content", ""))
        elif event_type == "result":
            session_id = obj.get("sessionId", "")
            exit_code = obj.get("exitCode", 0)

    message_count = len(content_parts)
    _wrapper_logger.debug("Parsed %d assistant.message events", message_count)
    return {
        "content": "".join(p.strip() for p in content_parts if p.strip()),
        "session_id": session_id,
        "exit_code": exit_code,
    }


def _parse_otel_metrics(otel_file_path: str, offset: int = 0) -> tuple:
    """Parse OTel JSONL export to extract tokens and cost.

    Args:
        otel_file_path: Path to the OTel JSONL file.
        offset: Byte offset to start reading from. Pass the file size captured
            before the CLI call to avoid picking up spans from prior invocations.
    """
    if not os.path.exists(otel_file_path):
        return None, None
    tokens = None
    cost = None
    try:
        with open(otel_file_path, "r", encoding="utf-8", errors="replace") as f:
            if offset:
                f.seek(offset)
            for line in f:
                if not line.strip():
                    continue
                span = json.loads(line)
                attrs = span.get("attributes", {})
                for key in [
                    "gen_ai.usage.input_tokens",
                    "gen_ai.usage.output_tokens",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "tokens",
                ]:
                    if key in attrs:
                        try:
                            val = int(attrs[key])
                            if tokens is None:
                                tokens = val
                            else:
                                tokens += val
                        except (ValueError, TypeError):
                            pass
    except (json.JSONDecodeError, IOError):
        return None, None
    return tokens, cost


# Model configuration for different tasks
# Override via env vars; plan.py and step_runner.py select per-effort models
MODEL_PLANNING = os.getenv("COPILOT_MODEL_PLANNING", "gpt-5.4")
MODEL_EXECUTION = os.getenv("COPILOT_MODEL_EXECUTION", "gpt-5.3-codex")
MODEL_CLASSIFICATION = os.getenv("COPILOT_MODEL_CLASSIFICATION", "")

# Default OTel path
DEFAULT_OTEL_PATH = "logs/.copilot-otel.jsonl"

# Auto-incrementing call counter so debug files don't overwrite each other
_call_counter = 0


def _compute_prompt_hash(prompt: str) -> str:
    """Return first 12 hex chars of SHA-256 hash of prompt for deduplication."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def _get_latest_session_id() -> Optional[str]:
    """Return the session ID (UUID) of the most recently modified Copilot CLI session.

    Sessions are stored as subdirectories of ~/.copilot/session-state/ (or
    $COPILOT_HOME/session-state/).  The directory name is the session UUID.
    Returns None if the session-state directory is absent or empty.
    """
    copilot_home = os.getenv("COPILOT_HOME", str(Path.home() / ".copilot"))
    session_dir = Path(copilot_home) / "session-state"
    if not session_dir.exists():
        return None
    try:
        dirs = [d for d in session_dir.iterdir() if d.is_dir()]
        if not dirs:
            return None
        return max(dirs, key=lambda d: d.stat().st_mtime).name
    except OSError:
        return None


def build_context_path(
    phase: str,
    rec_id: str,
    step_n: Optional[int] = None,
) -> str:
    """Build a context file path for a given phase, recommendation, and step.

    Args:
        phase: Phase name (e.g., "planning", "implementation")
        rec_id: Recommendation ID (e.g., "rec-252")
        step_n: Optional step number. If provided, appends -step{n} to the path.

    Returns:
        Path string in the format logs/debug/{phase}-context-{rec_id}[-step{n}].md
    """
    base_name = f"{phase}-context-{rec_id}"
    if step_n is not None:
        base_name += f"-step{step_n}"
    return f"logs/debug/{base_name}.md"


def _debug_log(call_n: int, label: str, content: str) -> None:
    """Write debug artefact to logs/debug/ if COPILOT_DEBUG is set."""
    if not os.getenv("COPILOT_DEBUG"):
        return
    debug_dir = Path("logs/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"call-{call_n:03d}-{label}.txt"
    path.write_text(content, encoding="utf-8")
    print(f"[DEBUG] wrote {path}", flush=True)


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its descendants to prevent orphan accumulation.

    On Windows, uses ``taskkill /F /T`` which terminates the process and all
    child processes recursively.  On Unix, sends SIGKILL to the process group.
    Called when a subprocess times out to prevent grandchild processes from
    lingering after their parent is killed.
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        except Exception:
            pass
    else:
        import signal as _signal

        try:
            os.killpg(os.getpgid(pid), _signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, _signal.SIGKILL)
            except Exception:
                pass


def copilot_call(
    prompt: str,
    model: Optional[str] = None,
    available_tools: Optional[list[str]] = None,
    excluded_tools: Optional[list[str]] = None,
    no_ask_user: bool = True,
    timeout: int = 300,
    output_file: Optional[str] = None,
    transcript_path: Optional[str] = None,
    check: bool = True,
    resume_session_id: Optional[str] = None,
    continue_session: bool = False,
    autopilot: bool = False,
    max_autopilot_continues: Optional[int] = None,
    output_format: Literal["text", "json"] = "json",
    context_file_path: Optional[str] = None,
    inline_instruction: Optional[str] = None,
    purpose: str = "unknown",
) -> CopilotResult:
    """Execute a Copilot CLI command with OTel metric capture.

    Both ``context_file_path`` and ``inline_instruction`` must be set to
    enable workspace-file mode. When both are set, the prompt is written to
    ``context_file_path`` and the ``inline_instruction`` is passed via ``-p``.

    Stable rules and constraints are loaded automatically from
    ``.github/instructions/*.instructions.md`` files (custom instructions)
    which the CLI injects as system context.

    Args:
        prompt: The prompt text to send to Copilot CLI. When
            ``context_file_path`` and ``inline_instruction`` are both set,
            written to the context file.
        model: Model to use (defaults to MODEL_EXECUTION if not specified).
        available_tools: Restrict the model to only these tool names.
            Each name is passed as a separate ``--available-tools`` flag.
        excluded_tools: Deny the model access to these tool names.
            Each name is passed as a separate ``--excluded-tools`` flag.
        no_ask_user: Add ``--no-ask-user`` so the model cannot pause to ask
            clarifying questions (default True - required for non-interactive use).
        timeout: Subprocess timeout in seconds.
        output_file: Optional file to write stdout to.
        transcript_path: Optional path for --share transcript export.
        check: If True (default), call validate_response() on stdout and raise
            CopilotResponseError when the model asks for clarification.
        resume_session_id: Session UUID to pass as ``--resume`` so the backend
            can reuse its KV-cached context window from a prior call in the same
            logical conversation (e.g. plan → critique → refine loop).
        continue_session: If True, pass ``--continue`` to resume the most recent
            CLI session without needing an explicit session UUID. Mutually
            exclusive with ``resume_session_id``; the explicit ID takes precedence
            when both are set (so callers can unconditionally set
            ``continue_session=True`` and fall back to explicit resume cleanly).
        autopilot: If True, pass ``--autopilot`` to enable autonomous continuation
            in prompt mode without Python-side orchestration between turns.
        max_autopilot_continues: Maximum number of continuation messages when
            running in autopilot mode. Passed as ``--max-autopilot-continues``.
            Has no effect unless ``autopilot=True``.
        output_format: ``"json"`` (default) adds ``--output-format json`` to the
            CLI invocation and calls :func:`parse_jsonl_output` on the raw stdout,
            populating ``CopilotResult.stdout`` with the extracted text content.  Use
            ``"text"`` only when consuming raw CLI output directly.
        context_file_path: Path to write the prompt to. Must be set along
            with ``inline_instruction`` to enable workspace-file mode.
            Creates the logs/debug/ directory if needed. The file is NOT cleaned up.
        inline_instruction: Short instruction to pass via ``-p`` without
            the @ prefix. Must be set along with ``context_file_path`` to enable
            workspace-file mode. When both are set, the prompt is written to
            ``context_file_path`` and the instruction is passed to the CLI.
    """
    if output_format not in ("text", "json"):
        raise ValueError(f"Invalid output_format: {output_format!r}. Must be one of: 'text', 'json'")

    _call_start_time = time.time()
    _call_started_iso = datetime.now(timezone.utc).isoformat()

    otel_path = os.getenv("COPILOT_OTEL_FILE_EXPORTER_PATH")
    if not otel_path:
        # Default to repo-local path and set env for CLI to see it
        otel_path = str(Path.cwd() / DEFAULT_OTEL_PATH)
        os.environ["COPILOT_OTEL_FILE_EXPORTER_PATH"] = otel_path

    # Default model if not specified
    if model is None:
        model = MODEL_EXECUTION

    # Resolve copilot path - required for Windows subprocess
    copilot_path = shutil.which("copilot")
    if not copilot_path:
        raise FileNotFoundError("copilot CLI not found in PATH. Install via 'gh extension install github/gh-copilot'")

    cmd = [copilot_path]
    # --resume / --continue: reuse the KV-cached context window to avoid
    # reloading the full context on every call. --resume with an explicit
    # session UUID is preferred; --continue (most-recent session) is used
    # when continue_session=True and no explicit ID is provided.
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    elif continue_session:
        cmd.append("--continue")
    # --allow-all-tools: required for non-interactive mode; prevents per-tool confirmations
    cmd.append("--allow-all-tools")
    if no_ask_user:
        # --no-ask-user: prevents the model from pausing to ask clarifying questions
        cmd.append("--no-ask-user")
    if autopilot:
        cmd.append("--autopilot")
        if max_autopilot_continues is not None:
            cmd.extend(["--max-autopilot-continues", str(max_autopilot_continues)])
    if model:
        cmd.extend(["--model", model])
    if available_tools:
        for tool in available_tools:
            cmd.extend(["--available-tools", tool])
    if excluded_tools:
        for tool in excluded_tools:
            cmd.extend(["--excluded-tools", tool])
    if transcript_path:
        cmd.extend(["--share", transcript_path])
    if output_format == "json":
        cmd.extend(["--output-format", "json"])

    # Track call for debug output
    global _call_counter
    _call_counter += 1
    call_n = _call_counter

    # Determine whether to use context file path or temp file
    if context_file_path and inline_instruction:
        # Write prompt body to a persistent context file in logs/debug/.
        # Pass the inline instruction + @context_file_path inside the -p
        # argument so the CLI expands @file inline as user-message content
        # (not as document context).  This is the correct invocation pattern
        # per AGENTS.md/PROJECT_CONTEXT.md Known Gotchas ("@file vs user message").
        context_path = Path(context_file_path)
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(prompt, encoding="utf-8")
        cmd.extend(["-p", f"{inline_instruction} @{context_file_path}"])
        prompt_file = context_file_path

    _debug_log(call_n, "prompt", prompt)
    _debug_log(
        call_n,
        "command",
        " ".join(f"@{prompt_file}" if arg.startswith("@") else arg for arg in cmd),
    )

    # Snapshot the OTel file size before the call so the parser only reads new
    # spans appended during *this* invocation, not accumulated history.
    otel_offset = 0
    try:
        otel_offset = Path(otel_path).stat().st_size if Path(otel_path).exists() else 0
    except OSError:
        pass

    result = None
    try:
        # Propagate _EXECUTOR_DEPTH incremented by 1 so any child that
        # re-invokes execute_recommendation.py will hit the recursion guard.
        child_env = os.environ.copy()
        current_depth = int(child_env.get("_EXECUTOR_DEPTH", "0"))
        child_env["_EXECUTOR_DEPTH"] = str(current_depth + 1)

        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc.pid)
                proc.wait()
                raise subprocess.TimeoutExpired(cmd=" ".join(cmd), timeout=timeout)
            result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except Exception as e:
        _debug_log(call_n, "response", f"Exception during subprocess execution: {e}")
        raise

    _debug_log(
        call_n,
        "response",
        (f"exit_code: {result.returncode}\n\n=== STDOUT ===\n{result.stdout}\n\n=== STDERR ===\n{result.stderr}"),
    )

    # Parse JSON output and extract text content + billing metadata.
    # parse_jsonl_output() raises CopilotResponseError on malformed JSON.
    _parsed_session_id: Optional[str] = None
    if output_format == "json":
        parsed = parse_jsonl_output(result.stdout)
        result = subprocess.CompletedProcess(result.args, result.returncode, parsed["content"], result.stderr)
        _parsed_session_id = parsed["session_id"] or None

    if output_file:
        Path(output_file).write_text(result.stdout)
    tokens, _cost = _parse_otel_metrics(otel_path, offset=otel_offset)
    session_id = _parsed_session_id or _get_latest_session_id()
    if check and result.returncode == 0:
        if not result.stdout and "is not available" in result.stderr:
            raise CopilotResponseError(
                (
                    "Model is not available in this org. Use COPILOT_MODEL_PLANNING "
                    "to specify a different model.\n"
                    f"Error: {result.stderr.strip()}"
                )
            )
        validate_response(result.stdout)
    _copilot_result = CopilotResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        tokens_used=tokens,
        model=model or "",
        transcript_path=transcript_path,
        session_id=session_id,
    )
    try:
        from scripts.executor.telemetry import emit_model_call as _emit_model_call

        _emit_model_call(
            provider="copilot_cli",
            model=_copilot_result.model or model or "",
            purpose=purpose,
            timestamp=_call_started_iso,
            duration_seconds=int(time.time() - _call_start_time),
            tokens_input=_copilot_result.tokens_used,
            exit_code=_copilot_result.exit_code,
            copilot_session_id=_copilot_result.session_id,
            prompt_hash=_compute_prompt_hash(prompt),
            error=result.stderr[:500] if result.returncode != 0 else None,
        )
    except Exception:
        pass  # telemetry must never break the call path
    return _copilot_result
