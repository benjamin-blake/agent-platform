# complexity-waiver: decision-43
"""Provider-agnostic LLM client -- primary inference interface.

Routes to the Bedrock transport (``_bedrock_call``) or Gemini CLI transport
(``_gemini_call``) based on the ``LLM_PROVIDER`` environment variable.

Defaults to ``"gemini"`` (via ``model_registry.resolve_provider()``) when no
env var is set.  Lambda handlers do not use this path -- they route by the
``provider`` field in ``schedule.yaml``.

Usage
-----
from scripts.llm_client import llm_call, LLMResult

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

from scripts.llm_utils import LLMResponseError

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Model name mapping: shortnames -> Bedrock model IDs
# ---------------------------------------------------------------------------

_MODEL_MAP: dict[str, str] = {
    "deepseek": "deepseek.v3.2",
    "claude-sonnet-4.6": "anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-haiku-4.5": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-opus-4.6": "anthropic.claude-opus-4-20250514-v1:0",
    # Gemini shortnames (no mapping needed -- passed directly to CLI)
    "gemini-3-pro-preview": "gemini-3-pro-preview",
    "gemini-3-flash-preview": "gemini-3-flash-preview",
}

# ---------------------------------------------------------------------------
# Bedrock per-token pricing (USD per 1M tokens): (input, output)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    "deepseek.v3.2": (0.90, 2.61),
    "anthropic.claude-sonnet-4-20250514-v1:0": (3.00, 15.00),
    "anthropic.claude-3-5-haiku-20241022-v1:0": (0.80, 4.00),
    "anthropic.claude-opus-4-20250514-v1:0": (15.00, 75.00),
    "gemini-3-flash-preview": (0.50, 3.00),
}

_DEFAULT_REGION = "eu-west-2"


def _resolve_provider() -> str:
    """Return the active inference provider.

    Delegates to ``model_registry.resolve_provider()`` which reads the
    ``LLM_PROVIDER`` environment variable and defaults to ``"gemini"``
    for executor use.  Lambda handlers do not call this path (they route
    by the ``provider`` field in schedule.yaml).
    """
    from scripts.model_registry import resolve_provider

    return resolve_provider()


def _resolve_model_id(model: str | None) -> str:
    """Map a shortname or env-var model to a Bedrock model ID."""
    if not model:
        model = os.getenv("COPILOT_MODEL_EXECUTION", "deepseek.v3.2")
    return _MODEL_MAP.get(model, model)


def _compute_cost(model_id: str | None, tokens_in: int, tokens_out: int) -> float:
    """Compute USD cost from token counts."""
    if not model_id:
        return 0.0
    in_price, out_price = _PRICING.get(model_id, (0.0, 0.0))
    return (tokens_in * in_price / 1_000_000) + (tokens_out * out_price / 1_000_000)


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
    profile_name: str | None = None,
    system_prompt: str | None = None,
) -> LLMResult:
    """Execute an LLM inference call via the configured provider.

    Routes to ``_gemini_call()`` when ``LLM_PROVIDER=gemini`` is set, or
    ``_bedrock_call()`` otherwise (default).

    Args:
        prompt: The prompt or context text.
        model: Model shortname or provider-specific ID (default from env).
        tools: If True, use agentic tool loop; if False, single-turn.
        excluded_tools: Tool names to exclude from the agentic loop (Bedrock only).
        timeout: Read timeout in seconds.
        purpose: Telemetry label for this call.
        context_file_path: Path to a file whose content is prepended to prompt.
        inline_instruction: Short instruction prepended before the context.
        check: If True, raise ``LLMResponseError`` on empty content.
        profile_name: AWS profile for Bedrock local CLI use.
        system_prompt: Optional system prompt (Bedrock only).
        resume_session_id: Gemini CLI session UUID to resume. When set, ``--resume``
            is appended to the CLI command so the GEMINI.md context is reused from
            the server-side token cache rather than cold-started on each call.
            Ignored for Bedrock provider.

    Returns:
        LLMResult with inference output and metadata.

    Raises:
        LLMResponseError: On empty response (when check=True) or API error.
    """
    provider = _resolve_provider()
    session_id = str(uuid.uuid4())

    # Build the full prompt (both providers receive the same assembled prompt)
    full_prompt = prompt
    if context_file_path:
        ctx_path = Path(context_file_path)
        if ctx_path.exists():
            ctx_content = ctx_path.read_text(encoding="utf-8", errors="replace")
            full_prompt = ctx_content + "\n\n" + prompt

    if provider == "gemini":
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

    if inline_instruction:
        full_prompt = inline_instruction + "\n\n" + full_prompt
    else:
        return _bedrock_call(
            prompt=full_prompt,
            model=model,
            tools=tools,
            excluded_tools=excluded_tools,
            timeout=timeout,
            purpose=purpose,
            session_id=session_id,
            check=check,
            profile_name=profile_name,
            system_prompt=system_prompt,
        )


# ---------------------------------------------------------------------------
# Bedrock transport
# ---------------------------------------------------------------------------


def _bedrock_call(
    prompt: str,
    model: str | None,
    tools: bool,
    excluded_tools: list[str] | None,
    timeout: int,
    purpose: str,
    session_id: str,
    check: bool,
    profile_name: str | None,
    system_prompt: str | None,
) -> LLMResult:
    """Execute a single LLM call via AWS Bedrock Converse API."""
    from scripts.bedrock_client import converse, converse_with_tools

    model_id = _resolve_model_id(model)
    credentials = _get_bedrock_credentials()
    profile = profile_name or os.getenv("AWS_PROFILE_BEDROCK")

    if tools:
        from scripts.tool_runtime import ToolRuntime

        runtime = ToolRuntime(working_dir=_REPO_ROOT)
        all_schemas = runtime.tool_schemas()

        if excluded_tools:
            excluded_set = set(excluded_tools)
            all_schemas = [s for s in all_schemas if s.get("toolSpec", {}).get("name") not in excluded_set]

        response = converse_with_tools(
            prompt=prompt,
            model_id=model_id,
            tools=all_schemas,
            tool_runtime=runtime,
            system_prompt=system_prompt,
            region=_DEFAULT_REGION,
            max_tokens=4096,
            max_turns=50,
            profile_name=profile,
            credentials=credentials,
            read_timeout=timeout,
        )
    else:
        response = converse(
            prompt=prompt,
            model_id=model_id,
            region=_DEFAULT_REGION,
            max_tokens=4096,
            read_timeout=timeout,
            system_prompt=system_prompt,
            profile_name=profile,
            credentials=credentials,
        )

    content = response.get("content", "")
    tokens_in = response.get("input_tokens", 0)
    tokens_out = response.get("output_tokens", 0)
    has_error = response.get("error", False)
    error_msg = response.get("message", "")

    if has_error:
        if check:
            raise LLMResponseError(f"LLM call failed: {error_msg}")
        return LLMResult(
            content=error_msg,
            exit_code=1,
            session_id=session_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_compute_cost(model_id, tokens_in, tokens_out),
            model=model_id,
        )

    if check and not content.strip():
        raise LLMResponseError("LLM returned empty content")

    cost = _compute_cost(model_id, tokens_in, tokens_out)
    _emit_telemetry("bedrock", model_id, purpose, tokens_in, tokens_out, cost)

    return LLMResult(
        content=content,
        exit_code=0,
        session_id=session_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        model=model_id,
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


def _get_bedrock_credentials() -> dict[str, str] | None:
    """Read Bedrock credentials from env or return None for default chain."""
    key_id = os.getenv("BEDROCK_AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("BEDROCK_AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        return {"aws_access_key_id": key_id, "aws_secret_access_key": secret}
    return None


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
