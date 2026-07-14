"""Model selection and escalation routing for the executor.

Extracted from plan.py and step_runner.py (Part 5 of monolith extraction plan).
Functions: get_planning_model, escalate_planning_model, get_implementation_model,
escalate_implementation_model.
"""

import logging

from scripts.llm import model_registry

logger = logging.getLogger(__name__)

# Per-rec failure counters for escalation tracking.
_PLANNING_FAILURE_COUNT: dict[str, int] = {}
_IMPL_FAILURE_COUNT: dict[str, int] = {}


def get_planning_model(effort: str) -> str | None:
    """Return appropriate planning model ID based on effort level.

    Delegates to ``model_registry.resolve_model()`` which applies:
    - COPILOT_MODEL_PLANNING env var override (highest priority)
    - Effort-band lookup from docs/contracts/inference-provider.yaml
    Returns ``None`` for Gemini auto mode (CLI picks the model).
    """
    return model_registry.resolve_model("planning", effort)


def escalate_planning_model(rec_id: str, current_model: str | None) -> str | None:
    """Increment failure count for rec_id and escalate model tier if threshold reached.

    Returns the next model ID from the escalation ladder after 2 consecutive
    failures.  Returns ``None`` when already at the top of the hierarchy
    (human intervention required).  Resets the failure counter on escalation.
    """
    _PLANNING_FAILURE_COUNT[rec_id] = _PLANNING_FAILURE_COUNT.get(rec_id, 0) + 1
    count = _PLANNING_FAILURE_COUNT[rec_id]
    if count >= 2:
        current_tier = model_registry.get_model_tier(current_model)
        next_model = model_registry.escalate_model("planning", current_tier)
        if next_model is not None:
            logger.info(
                "[ESCALATE] %s: %d failures -- escalating %s (tier=%s) -> %s",
                rec_id,
                count,
                current_model,
                current_tier,
                next_model,
            )
        else:
            logger.warning(
                "[ESCALATE] %s: at top of hierarchy (tier=%s) -- human intervention required",
                rec_id,
                current_tier,
            )
        _PLANNING_FAILURE_COUNT[rec_id] = 0
        return next_model
    return current_model


def get_implementation_model(effort: str, file: str = "", action: str = "") -> str | None:
    """Return appropriate implementation model ID based on effort level and file path.

    Delegates to ``model_registry.resolve_model()`` which applies:
    - COPILOT_MODEL_EXECUTION env var override (highest priority)
    - File-pattern floors (executor paths, config/prompts, .github/ files -> pro tier)
    - Effort-band lookup from docs/contracts/inference-provider.yaml
    Returns ``None`` for Gemini auto mode.
    """
    return model_registry.resolve_model("implementation", effort, file_path=file)


def escalate_implementation_model(rec_id: str, current_model: str | None) -> str | None:
    """Increment failure count for rec_id and escalate implementation model tier.

    Delegates tier-based escalation to ``model_registry.escalate_model()``.
    Returns the next model ID, or ``None`` when at the top of the hierarchy
    (human intervention required). Resets the failure counter on escalation.
    gpt-5-mini (flash tier) escalates after 1 failure; other tiers after 3.
    """
    _IMPL_FAILURE_COUNT[rec_id] = _IMPL_FAILURE_COUNT.get(rec_id, 0) + 1
    count = _IMPL_FAILURE_COUNT[rec_id]
    current_tier = model_registry.get_model_tier(current_model)
    threshold = 1 if current_tier == "flash" else 3
    if count >= threshold:
        next_model = model_registry.escalate_model("implementation", current_tier)
        if next_model is not None:
            logger.info(
                "[ESCALATE-IMPL] %s: %d failures -- escalating %s (tier=%s) -> %s",
                rec_id,
                count,
                current_model,
                current_tier,
                next_model,
            )
        else:
            logger.warning(
                "[ESCALATE-IMPL] %s: at top of hierarchy (tier=%s) -- human intervention required",
                rec_id,
                current_tier,
            )
        _IMPL_FAILURE_COUNT[rec_id] = 0
        return next_model
    return current_model
