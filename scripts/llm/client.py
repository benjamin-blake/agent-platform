# complexity-waiver: decision-43
"""Provider-agnostic LLM client -- primary inference interface.

Routes to the Gemini CLI transport (``_gemini_call``).  The Bedrock
transport was retired per CD.28 (Bedrock left the architecture as an LLM
substrate); the LiteLLM tier model (Tier 1 DeepSeek-direct, Tier 2
Anthropic-direct) lands with T4.2's transport rewrite.

The active provider resolves via ``model_registry.resolve_provider()``
(``LLM_PROVIDER`` env var, default ``"gemini"``).  Lambda handlers do not
use this path -- they route by the ``provider`` field in ``schedule.yaml``.

Usage
-----
from scripts.llm.client import llm_call, LLMResult

result = llm_call("Summarise this module.", tools=False)
print(result.content)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.llm.utils import LLMResponseError

logger = logging.getLogger(__name__)


def _resolve_provider() -> str:
    """Return the active inference provider.

    Delegates to ``model_registry.resolve_provider()`` which reads the
    ``LLM_PROVIDER`` environment variable and defaults to ``"gemini"``
    for executor use.  Lambda handlers do not call this path (they route
    by the ``provider`` field in schedule.yaml).
    """
    from scripts.llm.model_registry import resolve_provider

    return resolve_provider()


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMResult:
    """Result of an LLM inference call."""

    content: str
    exit_code: int
    session_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    stderr: str = ""
    raw_json: str = ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def llm_call(
    prompt: str,
    model: str | None = None,
    tools: bool = True,
    excluded_tools: list[str] | None = None,
    timeout: int = 300,
    purpose: str = "unknown",
    context_file_path: str | None = None,
    resume_session_id: str | None = None,
    inline_instruction: str | None = None,
    check: bool = True,
    system_prompt: str | None = None,
) -> LLMResult:
    """Execute an LLM inference call via the configured provider.

    Routes to ``_gemini_call()``. Bedrock was retired per CD.28; a
    non-gemini provider raises ``LLMResponseError`` until T4.2's LiteLLM
    transport lands.

    Args:
        prompt: The prompt or context text.
        model: Model shortname or provider-specific ID (default from env).
        tools: If True, use agentic tool loop; if False, single-turn.
        excluded_tools: Accepted for caller compatibility; consumed only by
            the retired Bedrock transport, ignored on gemini. Removed at
            T4.2's LiteLLM rewrite.
        timeout: Read timeout in seconds.
        purpose: Telemetry label for this call.
        context_file_path: Path to a file whose content is prepended to prompt.
        inline_instruction: Short instruction prepended before the context.
        check: If True, raise ``LLMResponseError`` on empty content.
        system_prompt: Accepted for caller compatibility; consumed only by
            the retired Bedrock transport, ignored on gemini. Removed at
            T4.2's LiteLLM rewrite.
        resume_session_id: Gemini CLI session UUID to resume. When set, ``--resume``
            is appended to the CLI command so the GEMINI.md context is reused from
            the server-side token cache rather than cold-started on each call.

    Returns:
        LLMResult with inference output and metadata.

    Raises:
        LLMResponseError: On empty response (when check=True), API error, or
            a provider other than ``gemini``.
    """
    del excluded_tools, system_prompt  # compatibility-only (see docstring)
    provider = _resolve_provider()
    session_id = str(uuid.uuid4())

    if provider != "gemini":
        raise LLMResponseError(
            f"provider {provider!r} retired per CD.28 -- gemini is the only llm_call transport until T4.2's LiteLLM lands"
        )

    full_prompt = prompt
    if context_file_path:
        ctx_path = Path(context_file_path)
        if ctx_path.exists():
            ctx_content = ctx_path.read_text(encoding="utf-8", errors="replace")
            full_prompt = ctx_content + "\n\n" + prompt

    # For Gemini CLI: strip @path references from inline_instruction
    # (Gemini doesn't expand @ in stdin mode — it's literal noise tokens)
    _gemini_instruction = inline_instruction
    if _gemini_instruction:
        import re as _re

        _gemini_instruction = _re.sub(r"\s*@\S+", "", _gemini_instruction).strip()
    if _gemini_instruction:
        full_prompt = _gemini_instruction + "\n\n" + full_prompt
    return _gemini_call(
        prompt=full_prompt,
        model=model,
        tools=tools,
        timeout=timeout,
        purpose=purpose,
        session_id=session_id,
        check=check,
        resume_session_id=resume_session_id,
    )


# ---------------------------------------------------------------------------
# Gemini CLI transport
# ---------------------------------------------------------------------------


def _gemini_call(
    prompt: str,
    model: str | None,
    tools: bool,
    timeout: int,
    purpose: str,
    session_id: str,
    check: bool,
    resume_session_id: str | None = None,
) -> LLMResult:
    """Execute an LLM call via the Gemini CLI headless mode.

    Pipes the prompt via stdin and uses ``-p ""`` to trigger non-interactive
    (headless) mode.  This avoids both Windows shell quoting issues and the
    ~8 191-char command-line length limit that breaks large prompts.

    The Gemini CLI docs state: *-p/--prompt: Appended to input on stdin
    (if any)*.  So ``-p ""`` means "headless mode, prompt is fully on stdin".

    Exit codes:
    - 0: success
    - 1: general error
    - 42: bad input
    - 53: turn limit exceeded (treated as retriable LLMResponseError)
    """
    # On Windows, npm installs gemini as gemini.CMD -- subprocess.run
    # cannot find bare "gemini" without shell=True.  shutil.which resolves
    # the full path (including the .CMD extension) so the call works with
    # shell=False on all platforms.
    _gemini_exe = shutil.which("gemini") or "gemini"
    cmd = [_gemini_exe, "-p", "", "--output-format", "stream-json"]
    if not tools:
        cmd += ["--approval-mode", "plan"]
    else:
        # Headless subprocess has no TTY for interactive approval.
        # yolo mode auto-approves all tool calls; planning relies on
        # prompt-level instructions (not tool restrictions) to prevent
        # file edits, plus a post-planning dirty-tree guard.
        cmd += ["--approval-mode", "yolo"]
    if model is not None:
        cmd += ["--model", model]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"},
        )

        exit_code = result.returncode
        _stderr = result.stderr.strip() if result.stderr else ""
        _raw_stdout = result.stdout or ""

        # Always log stderr -- critical for Gemini CLI diagnostics
        if _stderr:
            logger.info(
                "[GEMINI] stderr (exit %d, %s): %s",
                exit_code,
                purpose,
                _stderr[:500],
            )

        # Save raw JSON output to debug file for post-mortem
        _debug_dir = Path("logs/debug")
        _debug_dir.mkdir(parents=True, exist_ok=True)
        _ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _debug_file = _debug_dir / f"gemini-{purpose}-{_ts}.json"
        try:
            _debug_file.write_text(
                json.dumps(
                    {
                        "exit_code": exit_code,
                        "model": model,
                        "purpose": purpose,
                        "prompt_chars": len(prompt),
                        "stdout_chars": len(_raw_stdout),
                        "stderr": _stderr[:2000],
                        "stdout_preview": _raw_stdout[:5000],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.debug("[GEMINI] Raw output saved: %s", _debug_file)
        except OSError:
            pass

        # Exit 53 = turn limit exceeded -- treat as retriable
        if exit_code == 53:
            raise LLMResponseError(
                f"Gemini CLI turn limit exceeded (exit 53). Prompt may be too long. stderr: {result.stderr[:500]}"
            )

        if exit_code not in (0,) and not _raw_stdout.strip():
            err_detail = _stderr[:500] or "(no stderr)"
            if check:
                raise LLMResponseError(f"Gemini CLI exited with code {exit_code}: {err_detail}")
            return LLMResult(
                content=err_detail,
                exit_code=exit_code,
                session_id=session_id,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model=model or "gemini-auto",
                stderr=_stderr,
                raw_json=_raw_stdout,
            )

        # Parse response: stream-json (JSONL typed events) or old JSON blob fallback.
        # stream-json emits typed event lines: {"type":"init",...}, {"type":"message",...},
        # {"type":"result",...}.  Old json format emits a single {"response":...} blob.
        # Detect by presence of "type" field near line start (first 60 chars).
        _lines = (_raw_stdout or "").splitlines()
        _typed_count = sum(1 for _l in _lines if _l.strip().startswith("{") and '"type"' in _l[:60])
        _effective_session_id = session_id  # updated from init event in JSONL path

        if _typed_count > 0:
            # --- stream-json JSONL path ---
            # Accumulate: session_id from init, response from assistant message deltas,
            # token counts from result event stats.
            _response_parts: list[str] = []
            tokens_in = 0
            tokens_out = 0
            error_obj = None

            for _line in _lines:
                _line = _line.strip()
                if not _line.startswith("{"):
                    continue  # skip noise lines (YOLO warning, ImportProcessor errors)
                try:
                    _ev = json.loads(_line)
                except json.JSONDecodeError:
                    continue
                _etype = _ev.get("type", "")
                if _etype == "init":
                    _effective_session_id = _ev.get("session_id", session_id)
                elif _etype == "message" and _ev.get("role") == "assistant":
                    _response_parts.append(_ev.get("content", ""))
                elif _etype == "error" and _ev.get("fatal"):
                    error_obj = _ev
                elif _etype == "result":
                    _st = _ev.get("stats", {}) or {}
                    tokens_in = _st.get("input_tokens", 0) or 0
                    tokens_out = _st.get("output_tokens", 0) or 0
                    if _ev.get("status", "success") != "success" and not error_obj:
                        error_obj = {"message": f"Gemini CLI status={_ev.get('status')}"}

            content = "".join(_response_parts)

        else:
            # --- Old JSON blob fallback (handles non-JSONL output, existing test mocks) ---
            try:
                data = json.loads(_raw_stdout)
            except json.JSONDecodeError as exc:
                raw_preview = _raw_stdout[:300]
                if check:
                    raise LLMResponseError(f"Gemini CLI returned non-JSON output (exit {exit_code}): {raw_preview}") from exc
                return LLMResult(
                    content=_raw_stdout,
                    exit_code=exit_code,
                    session_id=session_id,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                    model=model or "gemini-auto",
                    stderr=_stderr,
                    raw_json=_raw_stdout,
                )

            content = data.get("response", "")
            stats = data.get("stats", {}) or {}
            tokens_in = 0
            tokens_out = 0
            models_stats = stats.get("models", {}) or {}
            if models_stats:
                for m_stats in models_stats.values():
                    toks = m_stats.get("tokens", {}) or {}
                    tokens_in += toks.get("input", 0) or 0
                    tokens_out += toks.get("candidates", 0) or 0
            else:
                token_usage = stats.get("tokenUsage", {}) or {}
                tokens_in = token_usage.get("inputTokens", 0) or 0
                tokens_out = token_usage.get("outputTokens", 0) or 0
            error_obj = data.get("error")

        # --- Common error handling and return (both paths) ---
        if error_obj or (exit_code != 0 and not content.strip()):
            if isinstance(error_obj, dict):
                _err_text = str(error_obj.get("message", error_obj))
            elif error_obj:
                _err_text = str(error_obj)
            else:
                _err_text = f"exit {exit_code}"
            if check:
                raise LLMResponseError(f"Gemini CLI error: {_err_text}")
            return LLMResult(
                content=_err_text,
                exit_code=exit_code,
                session_id=_effective_session_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,
                model=model or "gemini-auto",
                stderr=_stderr,
                raw_json=_raw_stdout,
            )

        if check and not content.strip():
            raise LLMResponseError("Gemini CLI returned empty response content")

        _emit_telemetry("gemini", model or "gemini-auto", purpose, tokens_in, tokens_out, 0.0)

        return LLMResult(
            content=content,
            exit_code=0,
            session_id=_effective_session_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            model=model or "gemini-auto",
            stderr=_stderr,
            raw_json=_raw_stdout,
        )
    except subprocess.TimeoutExpired:
        raise LLMResponseError(f"Gemini CLI timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit_telemetry(
    provider: str,
    model_id: str,
    purpose: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
) -> None:
    """Emit telemetry via deferred import (avoids circular deps)."""
    try:
        from scripts.executor.telemetry import emit_model_call as _emit

        _emit(
            provider=provider,
            model=model_id,
            purpose=purpose,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Telemetry emit skipped (not in executor context)")
