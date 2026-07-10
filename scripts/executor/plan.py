"""Plan generation, critique, refinement, and parsing for the executor.

Encapsulates all LLM interactions related to creating and revising
execution plans.  Dataclasses live here; the JSONL persistence layer
lives in jsonl_store.

Thin facade (Decision 104/80 mechanism): step parsing and scope
validation live in scripts.executor.plan_parsing; LLM plan generation,
critique, and refinement live in scripts.executor.plan_generation. Both
are re-exported here so ``from scripts.executor.plan import X`` and
patches on ``scripts.executor.plan.X`` keep working for every caller and
test, with zero migration.
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from scripts.executor.jsonl_store import PLANS_JSONL
from scripts.executor.plan_generation import (  # noqa: F401  (facade re-export)
    _NO_STEPS_KEYWORDS,
    _VIOLATION_PATTERN,
    _all_steps_already_done,
    _detect_critique_cycling,
    _extract_scope_files,
    _looks_like_no_changes,
    critique_plan,
    generate_compound_plan,
    generate_initial_plan,
    refine_plan,
)
from scripts.executor.plan_parsing import (  # noqa: F401  (facade re-export)
    _compute_step_scope,
    _validate_step_scope,
    parse_steps_from_plan,
)
from scripts.llm_client import llm_call  # noqa: F401  (re-exported; routed via _pl by plan_generation)
from scripts.llm_utils import (  # noqa: F401  (re-exported for backward compat; consumed directly by plan_generation)
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
from scripts.executor.model_routing import _PLANNING_FAILURE_COUNT  # noqa: E402, F401  (re-exported; routed via _pl)


def get_plan_timeout_secs() -> int:
    """Return the planning/refinement CLI timeout in seconds."""
    raw_timeout = os.getenv("PLAN_TIMEOUT_SECS", str(DEFAULT_PLAN_TIMEOUT_SECS))
    try:
        return max(1, int(raw_timeout))
    except (TypeError, ValueError):
        return DEFAULT_PLAN_TIMEOUT_SECS


def _validate_model_hierarchy() -> None:
    """No-op stub retained for backwards compatibility.  Model validation now
    delegated to model_registry which loads from docs/contracts/inference-provider.yaml.
    """
    pass


_validate_model_hierarchy()


def get_planning_model(effort: str) -> str | None:
    """Return appropriate planning model ID based on effort level.

    Delegates to ``model_registry.resolve_model()`` which applies:
    - COPILOT_MODEL_PLANNING env var override (highest priority)
    - Effort-band lookup from docs/contracts/inference-provider.yaml
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
