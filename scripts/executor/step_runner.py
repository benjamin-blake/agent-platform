# complexity-waiver: decision-43
"""Step implementation, acceptance verification, and telemetry for the executor.

Handles per-step file-context gathering, LLM calls, acceptance command
execution, git commits, and step-level telemetry writes.

This module is a thin facade (Decision 102/104 facade mechanism, T-1 SLOC
decomposition): context gathering lives in step_context.py, acceptance and
verification command running in step_acceptance.py, and commit/scope
enforcement in step_commit.py. Every symbol from those siblings is
re-exported here so `scripts.executor.step_runner.<name>` and
`from scripts.executor.step_runner import <name>` keep resolving for every
existing importer and test patch with zero migration. implement_step and all
shared module state stay here because they are the interception surface the
siblings route back through via a function-local `import
scripts.executor.step_runner as _sr` alias.
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from scripts.executor.plan import load_prompt
from scripts.executor.telemetry import emit_process_event, emit_step, emit_transcript
from scripts.llm.client import llm_call
from scripts.llm.utils import build_context_path, kill_process_tree
from scripts.s3_log_store import append_jsonl, get_backend

logger = logging.getLogger(__name__)

STEP_TELEMETRY_JSONL = Path("logs/.execution-step-telemetry.jsonl")


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
# Context gathering (extracted to scripts/executor/step_context.py)
# Re-exports preserved for backward compatibility.
# ---------------------------------------------------------------------------
from scripts.executor.step_context import (  # noqa: E402, F401, I001
    _GOTCHA_INJECTION_MAX_CHARS,
    _GOTCHA_MAP,
    _get_relevant_gotchas,
    gather_step_context,
)


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
# Acceptance and verification command running (extracted to
# scripts/executor/step_acceptance.py). Re-exports preserved for backward
# compatibility. The raw _LAST_ACCEPTANCE_OUTPUT/_LAST_VERIFICATION_OUTPUT
# globals stay co-located with their setters in step_acceptance.py and are
# deliberately NOT re-exported here -- only the getters (which always read
# the live current value) are, so a re-exported binding never goes stale.
# ---------------------------------------------------------------------------
from scripts.executor.step_acceptance import (  # noqa: E402, F401, I001
    _extract_acceptance_command,
    _normalize_acceptance,
    get_last_acceptance_output,
    get_last_verification_output,
    run_acceptance,
    run_verification,
)


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
# Pre-commit scope enforcement and git commit (extracted to
# scripts/executor/step_commit.py). Re-exports preserved for backward
# compatibility.
# ---------------------------------------------------------------------------
from scripts.executor.step_commit import _enforce_step_scope, commit_step  # noqa: E402, F401, I001


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
