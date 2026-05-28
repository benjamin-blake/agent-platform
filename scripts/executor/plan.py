# complexity-waiver: decision-43
"""Plan generation, critique, refinement, and parsing for the executor.

Encapsulates all LLM interactions related to creating and revising
execution plans.  Dataclasses live here; the JSONL persistence layer
lives in jsonl_store.
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scripts.executor.jsonl_store import PLANS_JSONL
from scripts.llm_client import llm_call
from scripts.llm_utils import (
    _PLAN_EXCLUDED_TOOLS,
    MODEL_PLANNING,
    LLMResponseError,
    build_context_path,
)
from scripts.ops_writer import OpsWriter

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path("config/agent/executor/prompts")

# _PLAN_EXCLUDED_TOOLS now imported from llm_utils


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

DEFAULT_PLAN_TIMEOUT_SECS = 600

# Per-rec failure counter -- canonical state lives in model_routing.py.
from scripts.executor.model_routing import _PLANNING_FAILURE_COUNT  # noqa: E402


def get_plan_timeout_secs() -> int:
    """Return the planning/refinement CLI timeout in seconds."""
    raw_timeout = os.getenv("PLAN_TIMEOUT_SECS", str(DEFAULT_PLAN_TIMEOUT_SECS))
    try:
        return max(1, int(raw_timeout))
    except (TypeError, ValueError):
        return DEFAULT_PLAN_TIMEOUT_SECS


def _validate_model_hierarchy() -> None:
    """No-op stub retained for backwards compatibility.  Model validation now
    delegated to model_registry which loads from config/agent/copilot/model_routing.yaml.
    """
    pass


_validate_model_hierarchy()


def get_planning_model(effort: str) -> str | None:
    """Return appropriate planning model ID based on effort level.

    Delegates to ``model_registry.resolve_model()`` which applies:
    - COPILOT_MODEL_PLANNING env var override (highest priority)
    - Effort-band lookup from config/agent/copilot/model_routing.yaml
    Returns ``None`` for Gemini auto mode (CLI picks the model).
    """
    from scripts.executor.model_routing import get_planning_model as _get_planning_model

    return _get_planning_model(effort)


def escalate_planning_model(rec_id: str, current_model: str | None) -> str | None:
    """Increment failure count for rec_id and escalate model tier if threshold reached.

    Returns the next model ID from the escalation ladder after 2 consecutive
    failures.  Returns ``None`` when already at the top of the hierarchy
    (human intervention required).  Resets the failure counter on escalation.
    """
    from scripts.executor.model_routing import escalate_planning_model as _escalate

    return _escalate(rec_id, current_model)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


def load_prompt(name: str) -> tuple[str, str]:
    """Load prompt template from file.

    Args:
        name: Prompt name without extension (e.g., 'planning', 'critique')

    Returns:
        Tuple of (template, hash) where template is the prompt string with
        {placeholders} for .format() and hash is the first 12 hex characters
        of the SHA-256 digest of the template content.

    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    path = PROMPTS_DIR / f"{name}.prompt.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    content = path.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return content, prompt_hash


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single parsed step from the plan."""

    n: int
    title: str
    file: str
    action: str  # create, modify, delete
    description: str
    acceptance: str


@dataclass
class ExecutionPlan:
    """Execution plan with revision tracking."""

    rec_id: str
    slug: str
    revision: int
    timestamp: str
    status: str  # draft, critique, approved, superseded, failed, no_changes_needed
    model: str
    tokens_used: Optional[int]
    steps: list[dict]
    critique_history: list[dict] = field(default_factory=list)
    plan_text: str = ""
    prompt_hash: str = ""
    planning_session_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, rec_id: str) -> Optional["ExecutionPlan"]:
        """Alias for get_latest_plan for compatibility."""
        return get_latest_plan(rec_id)


# ---------------------------------------------------------------------------
# JSONL persistence
# ---------------------------------------------------------------------------


def save_plan(plan: ExecutionPlan) -> None:
    """Append plan to JSONL log."""
    with open(PLANS_JSONL, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(plan.to_dict()) + "\n")
    logger.info("Saved plan: %s revision %d (%s)", plan.rec_id, plan.revision, plan.status)
    try:
        OpsWriter().write("ops_execution_plans", plan.to_dict())
    except Exception:  # noqa: BLE001
        logger.warning("OpsWriter write-through failed for %s", plan.rec_id, exc_info=True)


def get_latest_plan(rec_id: str) -> Optional[ExecutionPlan]:
    """Get the latest plan revision for a recommendation."""
    if not PLANS_JSONL.exists():
        return None
    latest: Optional[dict] = None
    with open(PLANS_JSONL, encoding="utf-8") as f:
        for line in f:
            if line.startswith('{"_schema'):
                continue
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("rec_id") == rec_id:
                    if latest is None or data.get("revision", 0) > latest.get("revision", 0):
                        latest = data
            except json.JSONDecodeError:
                continue
    if latest:
        return ExecutionPlan(**latest)
    return None


# ---------------------------------------------------------------------------
# Step parsing
# ---------------------------------------------------------------------------


def parse_steps_from_plan(plan_text: str) -> list[dict]:
    """Parse structured steps from plan text.

    Expected format:
    ### Step N: [title]
    **File**: path/to/file.py
    **Action**: create|modify|delete
    **Description**: ...
    **Acceptance**: ...
    """
    steps = []
    step_pattern = r"###\s*Step\s*(\d+):\s*(.+?)(?=###\s*Step|\Z)"
    matches = re.findall(step_pattern, plan_text, re.DOTALL | re.IGNORECASE)

    for step_num, step_content in matches:
        step: dict = {
            "n": int(step_num),
            "title": "",
            "file": "",
            "action": "",
            "description": "",
            "acceptance": "",
        }

        lines = step_content.strip().split("\n")
        if lines:
            step["title"] = lines[0].strip()

        file_match = re.search(r"\*\*File\*\*:\s*(.+)", step_content)
        if file_match:
            file_value = file_match.group(1).strip().strip("`")
            # Guard against malformed markdown artifacts in file field
            if file_value.startswith("**") or "**" in file_value:
                logger.warning(
                    f"Step {step['n']}: Rejecting malformed file value '{file_value}' (contains markdown bold markers)"
                )
                step["file"] = ""
            else:
                step["file"] = file_value

        action_match = re.search(r"\*\*Action\*\*:\s*(\w+)", step_content)
        if action_match:
            step["action"] = action_match.group(1).strip().lower()

        desc_match = re.search(r"\*\*Description\*\*:\s*(.+?)(?=\*\*|$)", step_content, re.DOTALL)
        if desc_match:
            step["description"] = desc_match.group(1).strip()

        acceptance_match = re.search(r"\*\*Acceptance\*\*:\s*(.+?)(?=\*\*|\n###|\n---|\Z)", step_content, re.DOTALL)
        if acceptance_match:
            step["acceptance"] = acceptance_match.group(1).strip()

        steps.append(step)

    # Deduplicate by step number: prefer the occurrence with both file and
    # acceptance fields populated (LLMs sometimes emit duplicate ### Step N:
    # blocks when the plan is long or context wraps).
    seen: dict[int, dict] = {}
    for s in steps:
        if s["n"] not in seen:
            seen[s["n"]] = s
        else:
            existing = seen[s["n"]]
            # Prefer the step that has both file and acceptance populated
            existing_complete = existing.get("file") and existing.get("acceptance")
            current_complete = s.get("file") and s.get("acceptance")
            if current_complete and not existing_complete:
                seen[s["n"]] = s
    steps = list(seen.values())

    # Fallback: numbered list
    if not steps:
        numbered_pattern = r"^\s*(\d+)\.\s+(.+)$"
        for match in re.finditer(numbered_pattern, plan_text, re.MULTILINE):
            steps.append(
                {
                    "n": int(match.group(1)),
                    "title": match.group(2).strip(),
                    "file": "",
                    "action": "modify",
                    "description": match.group(2).strip(),
                    "acceptance": "",
                }
            )

    return sorted(steps, key=lambda s: s["n"])


# ---------------------------------------------------------------------------
# Step scope validation
# ---------------------------------------------------------------------------


def _compute_step_scope(rec: dict) -> set[str]:
    """Derive the set of file paths a plan step may legitimately target.

    When ``rec["file"]`` is empty or missing the returned set is empty,
    which signals *no filtering* (all step files are allowed).

    When a target file is present the scope includes:
    1. The target file itself.
    2. The conventional test file for the target
       (``scripts/executor/foo.py`` -> ``tests/test_executor_foo.py``,
        ``scripts/bar.py``          -> ``tests/test_bar.py``).
    """
    target = (rec.get("file") or "").strip()
    if not target:
        return set()

    scope: set[str] = {target}

    target_path = Path(target)
    stem = target_path.stem
    parts = target_path.parts

    if len(parts) >= 3 and parts[0] == "scripts" and parts[1] == "executor":
        test_name = f"tests/test_executor_{stem}.py"
        scope.add(test_name)
    elif len(parts) >= 2 and parts[0] == "scripts":
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)
    elif len(parts) >= 2 and parts[0] == "src":
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)
    else:
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)

    return scope


def _validate_step_scope(
    steps: list[dict],
    rec: dict,
) -> list[dict]:
    """Filter parsed steps to those within the recommendation scope.

    If the recommendation has no target file (empty or missing ``file``
    key), all steps pass through unchanged -- preserving the existing
    behaviour for scope-free recommendations.

    When a target IS present, steps whose ``file`` field falls outside
    the computed scope are dropped with a warning log.  Steps that have
    an empty ``file`` field are always kept (they represent analysis or
    acceptance-only steps).
    """
    scope = _compute_step_scope(rec)
    if not scope:
        return steps

    kept: list[dict] = []
    for step in steps:
        step_file = (step.get("file") or "").strip()
        if not step_file:
            kept.append(step)
            continue
        if step_file in scope:
            kept.append(step)
        else:
            logger.warning(
                "[SCOPE] Step %d targets '%s' which is outside rec scope %s -- rejected",
                step.get("n", 0),
                step_file,
                sorted(scope),
            )

    return kept


# ---------------------------------------------------------------------------
# LLM plan generation / critique / refinement
# ---------------------------------------------------------------------------

_NO_STEPS_KEYWORDS = (
    "already",
    "nothing to do",
    "no changes",
    "no steps",
    "already implemented",
    "already_implemented",
    "already met",
    "already satisfi",
    "i understand the task",
    "nothing further",
)


def _looks_like_no_changes(text: str) -> bool:
    """Return True if the LLM response appears to indicate no changes are needed.

    Accepts both the prescribed short token ``ALREADY_IMPLEMENTED`` and longer
    prose responses that contain any of the _NO_STEPS_KEYWORDS phrases.
    """
    stripped = text.strip()
    # Prescribed short token — exact match (case-insensitive)
    if stripped.upper() == "ALREADY_IMPLEMENTED":
        return True
    # Prose response — keyword scan on longer text to avoid false positives
    # from file content that happens to contain the words (min 30 chars)
    lower = stripped.lower()
    return len(stripped) > 30 and any(kw in lower for kw in _NO_STEPS_KEYWORDS)


def _all_steps_already_done(steps: list[dict]) -> bool:
    """Return True if all step titles indicate pre-existing implementation.

    Checks each parsed step's title for:
    - "already" (case-insensitive)
    - ends with checkmark (✓ or ✔)
    - starts with check mark emoji (✅)
    - line-reference patterns: "(lines N-M)", "(line N)", "Lines N-M:"
      indicating verification-only steps

    Returns True only if steps list is non-empty AND all titles match
    the pattern.
    """
    if not steps:
        return False

    for step in steps:
        original_title = step.get("title", "")
        title = original_title.strip().lower()
        if not title:
            return False

        # Check for "already" keyword
        if "already" in title:
            continue

        # Check for checkmark suffix (before stripping punctuation)
        if original_title.rstrip().endswith(("✓", "✔")):
            continue

        # Check for check mark emoji prefix (✅)
        if original_title.strip().startswith("✅"):
            continue

        # Check for line-reference patterns (e.g., "(lines 123-456)", "(line 5)",
        # "Lines 10-20:")
        if re.search(r"\(lines?\s+\d+(?:-\d+)?\)|lines?\s+\d+(?:-\d+):", title):
            continue

        # Title doesn't match any condition
        return False

    return True


def generate_initial_plan(
    rec: dict,
    model_override: Optional[str] = None,
    base_session_id: Optional[str] = None,
) -> "ExecutionPlan":
    """Generate initial plan via CLI — single atomic call.

    Args:
        rec: Recommendation dict.
        model_override: If provided, overrides the model hierarchy selection.
            Used by the escalation retry loop to bypass the standard hierarchy.
        base_session_id: Gemini CLI session ID from a pre-seeded warm session.
            When set, the planning call resumes from this session so the cached
            GEMINI.md context is reused instead of cold-starting (~50K tokens).

    Returns ExecutionPlan with status='draft', revision=1.

    Raises:
        LLMResponseError: If the CLI fails, returns a question, or produces
            a response from which no steps can be parsed.
    """
    from scripts.executor.step_runner import gather_step_context  # local import to avoid circularity

    rec_id = rec.get("id", "unknown")
    slug = rec.get("slug", rec_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    f"logs/transcripts/plan-{rec_id}-gen-{int(time.time())}.md"

    _ctx_step = {"file": rec.get("file", ""), "action": "modify"}
    # Cap at 12000 chars for planning: the CLI's MCP view tool fails on files
    # larger than ~30 KB. With template + rec metadata overhead (~2 KB) the
    # 30000-char budget produced 31.2 KB prompts that the model couldn't read.
    # 12000 chars keeps the total well under 14 KB while giving the planner
    # enough function-level context for XS/S recs. Step implementation keeps
    # its own (larger) budget via gather_step_context's default.
    ctx = gather_step_context(_ctx_step, max_chars=12000)

    _hdr_file = "\n## Current File Content\nThe target file already exists. Use this to plan targeted edits.\n\n```\n"
    _hdr_test = "\n## Existing Tests\nUse these to understand expected behaviour and coverage.\n\n```python\n"
    _footer = "\n```\n"
    file_content_section = (_hdr_file + ctx["file_content"] + _footer) if ctx["file_content"] else ""
    test_content_section = (_hdr_test + ctx["test_content"] + _footer) if ctx["test_content"] else ""

    acceptance_str = rec.get("acceptance", "").strip()
    if acceptance_str and acceptance_str != "(no acceptance criteria)":
        _hdr_acceptance = "\n## Acceptance Constraint\nThe step must produce this exact outcome:\n\n"
        acceptance_constraint_section = _hdr_acceptance + "```\n" + acceptance_str + "\n```\n"
        # The acceptance constraint is applied VERBATIM to ensure the model honors
        # the exact acceptance criteria from the JSONL specification without
        # modification. This prevents the planner from reformatting or rewriting
        # the acceptance criteria, ensuring that the step implementation validates
        # against the precise specification provided in the recommendation.
        logger.info("[PLAN] Injecting verbatim acceptance constraint from JSONL: %s", acceptance_str)
    else:
        acceptance_constraint_section = ""

    # Build complexity warning section if warnings file exists
    complexity_warning = ""
    warnings_file = Path("logs/.complexity-warnings.json")
    if warnings_file.exists():
        try:
            with open(warnings_file, encoding="utf-8") as f:
                warnings_data = json.load(f)
            target_file = rec.get("file", "")
            for entry in warnings_data:
                if entry.get("file") == target_file:
                    message = entry.get("message", "")
                    complexity_metric = entry.get("complexity_metric", "")
                    z_score = entry.get("z_score", "")
                    _hdr_complexity = "\n## Complexity Warning\n"
                    _body = f"File: {target_file}\nMetric: {complexity_metric}\nZ-Score: {z_score}\nMessage: {message}\n"
                    complexity_warning = _hdr_complexity + _body
                    logger.info(
                        "[PLAN] Injecting complexity warning for %s (z-score: %s)",
                        target_file,
                        z_score,
                    )
                    break
        except Exception as err:
            logger.warning(
                "[PLAN] Failed to load complexity warnings from %s: %s",
                warnings_file,
                err,
            )

    if ctx["file_content"]:
        logger.info("[PLAN] Injecting %d chars of file context into planning prompt", len(ctx["file_content"]))
    if ctx["test_content"]:
        logger.info("[PLAN] Injecting %d chars of test context into planning prompt", len(ctx["test_content"]))

    template, prompt_hash = load_prompt("planning")
    prompt = template.format(
        rec_id=rec_id,
        title=rec.get("title", "(no title)"),
        context=rec.get("context", "(no context provided)"),
        file=rec.get("file", "(not specified)"),
        acceptance=rec.get("acceptance", "(no acceptance criteria)"),
        dependencies=rec.get("dependencies", []),
        effort=rec.get("effort", "unknown"),
        file_content_section=file_content_section,
        test_content_section=test_content_section,
        acceptance_constraint=acceptance_constraint_section,
        complexity_warning=complexity_warning,
    )

    plan_timeout = get_plan_timeout_secs()
    _plan_model = model_override if model_override else get_planning_model(rec.get("effort", ""))
    logger.info("[PLAN] Generating initial plan with model=%s (timeout=%ds)...", _plan_model or "default", plan_timeout)
    logger.info("[PLAN] Excluding tools: %s", ", ".join(_PLAN_EXCLUDED_TOOLS))
    if base_session_id:
        logger.info("[PLAN] Resuming warm base session %s for token cache reuse", base_session_id[:8])

    result = llm_call(
        prompt,
        model=_plan_model or None,
        timeout=plan_timeout,
        check=True,
        context_file_path=build_context_path("plan-gen", rec_id),
        inline_instruction="Generate a step-by-step plan from the attached spec. Do not implement code.",
        excluded_tools=_PLAN_EXCLUDED_TOOLS,
        purpose="planning",
        resume_session_id=base_session_id or None,
    )

    if result.exit_code != 0:
        raise LLMResponseError(f"[PLAN] CLI exited {result.exit_code}")

    # Reset failure count for this rec on success
    _PLANNING_FAILURE_COUNT.pop(rec_id, None)

    plan_text = result.content

    # Check for acceptance challenge protocol
    if "ACCEPTANCE_CHALLENGE:" in plan_text:
        import sys
        from pathlib import Path as PathlibPath

        root = str(PathlibPath(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from scripts.executor.jsonl_store import update_recommendation_status

        # Extract challenge components
        challenge_match = re.search(r"ACCEPTANCE_CHALLENGE:\s*(.+?)(?:\n|$)", plan_text)
        evidence_match = re.search(r"EVIDENCE:\s*(.+?)(?=\n(?:SUGGESTED_FIX:|$)|$)", plan_text, re.DOTALL)
        suggested_fix_match = re.search(r"SUGGESTED_FIX:\s*`(.+?)`", plan_text, re.DOTALL)

        challenge_reason = challenge_match.group(1).strip() if challenge_match else ""
        evidence = evidence_match.group(1).strip() if evidence_match else ""
        suggested_acceptance = suggested_fix_match.group(1).strip() if suggested_fix_match else ""

        logger.warning(
            "[PLAN] ACCEPTANCE_CHALLENGE detected for %s: %s",
            rec_id,
            challenge_reason,
        )
        if evidence:
            logger.warning("[PLAN] Evidence: %s", evidence[:200])
        if suggested_acceptance:
            logger.warning("[PLAN] Suggested fix: %s", suggested_acceptance[:200])

        challenge_updates = {
            "status": "failed",
            "failure_reason": f"acceptance_challenged: {challenge_reason}",
        }
        if challenge_reason:
            challenge_updates["challenge_reason"] = challenge_reason
        if suggested_acceptance:
            challenge_updates["suggested_acceptance"] = suggested_acceptance

        update_recommendation_status(rec_id, challenge_updates)

        return ExecutionPlan(
            rec_id=rec_id,
            slug=slug,
            revision=1,
            timestamp=timestamp,
            status="acceptance_challenged",
            model=result.model or "default",
            tokens_used=result.tokens_in + result.tokens_out,
            steps=[],
            critique_history=[],
            plan_text=plan_text,
            prompt_hash=prompt_hash,
        )

    steps = parse_steps_from_plan(plan_text)
    steps = _validate_step_scope(steps, rec)

    if _all_steps_already_done(steps):
        logger.info("[PLAN] All steps marked as already done. Setting status to no_changes_needed.")
        return ExecutionPlan(
            rec_id=rec_id,
            slug=slug,
            revision=1,
            timestamp=timestamp,
            status="no_changes_needed",
            model=result.model or "default",
            tokens_used=result.tokens_in + result.tokens_out,
            steps=steps,
            critique_history=[],
            plan_text=plan_text,
            prompt_hash=prompt_hash,
        )

    if not steps:
        if _looks_like_no_changes(plan_text):
            logger.warning(
                "[PLAN] No steps parsed — model indicates no changes needed. Response preview:\n%s",
                plan_text[:300],
            )
            return ExecutionPlan(
                rec_id=rec_id,
                slug=slug,
                revision=1,
                timestamp=timestamp,
                status="no_changes_needed",
                model=result.model or "default",
                tokens_used=result.tokens_in + result.tokens_out,
                steps=[],
                critique_history=[],
                plan_text=plan_text,
                prompt_hash=prompt_hash,
            )
        raise LLMResponseError(f"[PLAN] No steps parsed from plan output. Response preview:\n{plan_text[:500]}")

    plan = ExecutionPlan(
        rec_id=rec_id,
        slug=slug,
        revision=1,
        timestamp=timestamp,
        status="draft",
        model=result.model or "default",
        tokens_used=result.tokens_in + result.tokens_out,
        steps=steps,
        critique_history=[],
        plan_text=plan_text,
        prompt_hash=prompt_hash,
    )

    logger.info("[PLAN] Generated: %d steps, %s tokens", len(steps), result.tokens_in + result.tokens_out)

    logger.info("[PLAN] Step pre-flight summary:")
    for s in steps:
        acceptance_preview = (s.get("acceptance") or "").strip()
        acceptance_preview = acceptance_preview[:80] + "..." if len(acceptance_preview) > 80 else acceptance_preview
        logger.info(
            "[PLAN]   Step %d/%d | action=%-6s | file=%s",
            s["n"],
            len(steps),
            s.get("action", "?"),
            s.get("file", "(no file)"),
        )
        if acceptance_preview:
            logger.info("[PLAN]            acceptance=%s", acceptance_preview)
        else:
            logger.warning("[PLAN]            acceptance=(EMPTY — step will not be verified)")

    if os.getenv("PLAN_SESSION_RESUME", "true").lower() not in ("false", "0"):
        plan.planning_session_id = result.session_id or ""
        if plan.planning_session_id:
            logger.info("[PLAN] Session ID captured: %s", plan.planning_session_id)

    return plan


def generate_compound_plan(recs: list[dict]) -> "ExecutionPlan":
    """Generate a unified plan for multiple recommendations.

    Generates individual plans and merges their steps into a single
    ExecutionPlan. Each step retains its source rec_id for traceability.

    Args:
        recs: List of recommendation dicts to plan for.

    Returns:
        Merged ExecutionPlan with all steps sequenced.
    """
    all_steps: list[dict] = []
    combined_text_parts: list[str] = []

    for rec in recs:
        plan = generate_initial_plan(rec)
        for step in plan.steps:
            step["source_rec_id"] = rec["id"]
            step["n"] = len(all_steps) + 1
            all_steps.append(step)
        combined_text_parts.append(f"## {rec['id']}: {rec.get('title', '')}\n{plan.plan_text}")

    compound = ExecutionPlan(
        rec_id=recs[0]["id"],
        slug=f"compound-{recs[0]['id']}",
        revision=1,
        timestamp=datetime.now(timezone.utc).isoformat(),
        status="approved",
        model=get_planning_model(recs[0].get("effort", "")),
        tokens_used=None,
        steps=all_steps,
        plan_text="\n\n".join(combined_text_parts),
    )
    return compound


def _extract_scope_files(plan_text: str) -> str:
    """Extract file paths from ## Scope table in plan markdown."""
    import re

    scope_match = re.search(r"##\s+Scope\s*\n(.*?)(?=\n##|\Z)", plan_text, re.DOTALL)
    if not scope_match:
        return "(No scope table found)"

    scope_section = scope_match.group(1)
    files = []
    for line in scope_section.split("\n"):
        if line.strip().startswith("|") and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1]:
                file_path = parts[1]
                if file_path.lower() != "file":
                    files.append(f"- {file_path}")

    if not files:
        return "(No files found in scope table)"

    return "Files to review:\n" + "\n".join(files)


def critique_plan(plan: "ExecutionPlan") -> dict:
    """Critique plan via CLI — single atomic call.

    Returns dict with 'verdict' ('approved' or 'needs_revision') and 'suggestions'.

    Raises:
        LLMResponseError: If the CLI fails, asks for clarification, or
            returns an empty response.
    """
    f"logs/transcripts/plan-{plan.rec_id}-critique-r{plan.revision}-{int(time.time())}.md"

    template, _critique_hash = load_prompt("critique")
    scope_files = _extract_scope_files(plan.plan_text)
    prompt = template.format(plan_text=plan.plan_text, scope_files=scope_files)

    logger.info("[CRITIQUE] Reviewing plan revision %d...", plan.revision)

    critique_model = plan.model if plan.model and plan.model != "default" else MODEL_PLANNING or None
    plan_timeout = get_plan_timeout_secs()
    result = llm_call(
        prompt,
        model=critique_model,
        timeout=plan_timeout,
        check=True,
        context_file_path=build_context_path("plan-critique", plan.rec_id),
        inline_instruction="Review the plan and output VERDICT: APPROVED or VERDICT: NEEDS_REVISION.",
        excluded_tools=_PLAN_EXCLUDED_TOOLS,
        purpose="critique",
    )

    if result.exit_code != 0:
        raise LLMResponseError(f"[CRITIQUE] CLI exited {result.exit_code}")

    output = result.content
    if not output.strip():
        raise LLMResponseError("[CRITIQUE] Empty response from CLI")

    verdict = "needs_revision"
    if "VERDICT: APPROVED" in output.upper():
        verdict = "approved"
    elif "VERDICT: NEEDS_REVISION" in output.upper():
        verdict = "needs_revision"

    suggestions = []
    capture = False
    for line in output.split("\n"):
        if "VERDICT:" in line.upper():
            capture = True
            continue
        if capture and line.strip():
            suggestions.append(line.strip())

    critique = {
        "iteration": len(plan.critique_history) + 1,
        "verdict": verdict,
        "suggestions": suggestions,
        "tokens_used": result.tokens_in + result.tokens_out,
        "full_output": output,
    }

    logger.info("[CRITIQUE] Verdict: %s (%d suggestions)", verdict, len(suggestions))
    return critique


def refine_plan(plan: "ExecutionPlan", critique: dict, rec: dict) -> "ExecutionPlan":
    """Refine plan based on critique — single atomic call.

    Args:
        plan: The execution plan to refine.
        critique: The critique feedback dictionary.
        rec: The recommendation metadata dictionary.

    Returns new ExecutionPlan with incremented revision.

    Raises:
        LLMResponseError: If CLI fails, asks for clarification, or produces
            a response with no parseable steps.
    """
    f"logs/transcripts/plan-{plan.rec_id}-refine-r{plan.revision + 1}-{int(time.time())}.md"

    critique_text = critique.get("full_output") or "\n".join(critique.get("suggestions", []))
    template, _refine_hash = load_prompt("refine")

    scope_files = _extract_scope_files(plan.plan_text)

    prompt = template.format(
        plan_text=plan.plan_text,
        critique_text=critique_text,
        rec_id=plan.rec_id,
        title=rec.get("title", ""),
        context=rec.get("context", ""),
        file=rec.get("file", ""),
        acceptance=rec.get("acceptance", ""),
        dependencies=", ".join(rec.get("dependencies", [])) or "None",
        effort=rec.get("effort", ""),
        scope_files=scope_files,
    )

    plan_timeout = get_plan_timeout_secs()
    logger.info("[REFINE] Creating revision %d (timeout=%ds)...", plan.revision + 1, plan_timeout)

    refine_model = plan.model if plan.model and plan.model != "default" else MODEL_PLANNING or None
    result = llm_call(
        prompt,
        model=refine_model,
        timeout=plan_timeout,
        check=True,
        context_file_path=build_context_path("plan-refine", plan.rec_id),
        inline_instruction="Refine the plan based on critique. Output revised steps.",
        excluded_tools=_PLAN_EXCLUDED_TOOLS,
        purpose="refinement",
    )

    if result.exit_code != 0:
        raise LLMResponseError(f"[REFINE] CLI exited {result.exit_code}")

    new_plan_text = result.content
    new_steps = parse_steps_from_plan(new_plan_text)
    new_steps = _validate_step_scope(new_steps, rec)

    if not new_steps:
        if _looks_like_no_changes(new_plan_text):
            logger.warning(
                "[REFINE] No steps parsed — model indicates no changes needed during refine. Response preview:\n%s",
                new_plan_text[:300],
            )
            plan.status = "superseded"
            save_plan(plan)
            return ExecutionPlan(
                rec_id=plan.rec_id,
                slug=plan.slug,
                revision=plan.revision + 1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="no_changes_needed",
                model=result.model or "default",
                tokens_used=result.tokens_in + result.tokens_out,
                steps=[],
                critique_history=plan.critique_history + [critique],
                plan_text=new_plan_text,
                planning_session_id=plan.planning_session_id,
            )
        raise LLMResponseError(f"[REFINE] No steps parsed from refined plan. Response preview:\n{new_plan_text[:500]}")

    plan.status = "superseded"
    save_plan(plan)

    new_plan = ExecutionPlan(
        rec_id=plan.rec_id,
        slug=plan.slug,
        revision=plan.revision + 1,
        timestamp=datetime.now(timezone.utc).isoformat(),
        status="draft",
        model=result.model or "default",
        tokens_used=result.tokens_in + result.tokens_out,
        steps=new_steps,
        critique_history=plan.critique_history + [critique],
        plan_text=new_plan_text,
        planning_session_id=plan.planning_session_id,
    )

    logger.info("[REFINE] Created revision %d: %d steps", new_plan.revision, len(new_steps))
    return new_plan


# ---------------------------------------------------------------------------
# Critique cycling detection
# ---------------------------------------------------------------------------

_VIOLATION_PATTERN = re.compile(r"[Vv]iolation\s+(\d+)\b.*[Ss]tep\s+(\d+)|[Ss]tep\s+(\d+).*[Vv]iolation\s+(\d+)\b")


def _detect_critique_cycling(critique_history: list[dict]) -> bool:
    """Return True if the same (step_n, rule_number) violation pair appears in
    two or more consecutive critique iterations, indicating a cycling pattern.

    Cycling occurs when critique and refine cannot resolve a pattern disagreement
    -- the same step violates the same rule revision after revision. When detected,
    the caller should auto-approve the plan rather than looping indefinitely.

    Args:
        critique_history: List of critique dicts with 'iteration', 'verdict',
            and 'suggestions' keys. As stored in ExecutionPlan.critique_history.

    Returns:
        True if cycling is detected (same (step_n, rule_n) in last 2 iterations),
        False otherwise.
    """
    if len(critique_history) < 2:
        return False

    def _extract_pairs(critique: dict) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for suggestion in critique.get("suggestions", []):
            for m in _VIOLATION_PATTERN.finditer(suggestion):
                rule = int(m.group(1) or m.group(4) or 0)
                step = int(m.group(2) or m.group(3) or 0)
                if rule and step:
                    pairs.add((step, rule))
        return pairs

    last_two = critique_history[-2:]
    pairs_prev = _extract_pairs(last_two[0])
    pairs_curr = _extract_pairs(last_two[1])

    common = pairs_prev & pairs_curr
    if common:
        logger.warning(
            "[CRITIQUE-CYCLING] Cycling detected: same violations in last 2 iterations: %s",
            sorted(common),
        )
        return True
    return False
