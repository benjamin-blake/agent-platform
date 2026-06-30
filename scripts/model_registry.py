"""Provider-aware model resolver for executor LLM calls.

Reads routing configuration from ``config/agent/copilot/model_routing.yaml``.
Falls back to safe defaults (Gemini auto mode) if the config file is missing.

Usage
-----
from scripts.model_registry import resolve_model, resolve_provider, escalate_model

model_id = resolve_model("planning", "XS")     # "gemini-3-flash-preview" or None
provider = resolve_provider()                   # "gemini" (default for executor)
next_model = escalate_model("planning", "flash")  # "gemini-3-pro-preview"
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/agent/copilot/model_routing.yaml")
_CONFIG: dict | None = None

_VALID_PROVIDERS = frozenset(["gemini"])  # bedrock retired per CD.28
_DEFAULT_EXECUTOR_PROVIDER = "gemini"

_ENV_OVERRIDE_MAP: dict[str, str] = {
    "planning": "COPILOT_MODEL_PLANNING",
    "implementation": "COPILOT_MODEL_EXECUTION",
    "review": "COPILOT_MODEL_REVIEW",
}


def _load_config() -> dict:
    """Load and cache the routing config YAML.

    Returns an empty dict with a warning if the file is missing or unparseable.
    Never raises -- import safety is a hard requirement.
    """
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    if not _CONFIG_PATH.exists():
        logger.warning(
            "model_registry: routing config not found at %s -- using empty defaults",
            _CONFIG_PATH,
        )
        _CONFIG = {}
        return _CONFIG

    try:
        import yaml

        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            _CONFIG = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001
        logger.warning(
            "model_registry: failed to load or parse %s -- using empty defaults",
            _CONFIG_PATH,
        )
        _CONFIG = {}

    return _CONFIG


def _reload_config() -> dict:
    """Force a fresh load from disk (clears cache). Primarily for testing."""
    global _CONFIG
    _CONFIG = None
    return _load_config()


def resolve_provider() -> str:
    """Return the active LLM provider for executor use.

    Reads the ``LLM_PROVIDER`` environment variable. Defaults to ``"gemini"``
    (the executor default; Lambda handlers do not call this path).
    Falls back to the default if an unrecognised value is supplied.
    """
    raw = os.getenv("LLM_PROVIDER", _DEFAULT_EXECUTOR_PROVIDER)
    if raw not in _VALID_PROVIDERS:
        logger.warning(
            "model_registry: unknown provider %r in LLM_PROVIDER -- defaulting to %s",
            raw,
            _DEFAULT_EXECUTOR_PROVIDER,
        )
        return _DEFAULT_EXECUTOR_PROVIDER
    return raw


def resolve_model(role: str, effort: str, file_path: str = "") -> str | None:
    """Return the model ID for a given role and effort level.

    Precedence (highest to lowest):
    1. Environment variable override (``COPILOT_MODEL_PLANNING`` / ``COPILOT_MODEL_EXECUTION`` /
       ``COPILOT_MODEL_REVIEW``).
    2. File-pattern floor: if ``file_path`` matches a sensitive pattern, escalate to ``pro`` tier
       (implementation role only).
    3. Effort-band lookup from ``config/agent/copilot/model_routing.yaml``.
    4. Returns ``None`` (Gemini auto mode -- CLI picks pro or flash based on task complexity).

    When ``LLM_PROVIDER`` is not ``"gemini"``, only the env-var override is applied; all other
    cases return ``None`` so the caller can apply provider-specific defaults.

    Args:
        role: One of ``"planning"``, ``"implementation"``, ``"review"``.
        effort: Effort band string (``"XS"``, ``"S"``, ``"M"``, ``"L"``, ``"XL"``).
        file_path: Optional path of the target file (used for floor checks).

    Returns:
        A Gemini model ID string, or ``None`` for auto mode.
    """
    # 1. Environment variable override (provider-agnostic)
    env_key = _ENV_OVERRIDE_MAP.get(role)
    if env_key:
        override = os.getenv(env_key)
        if override:
            return override

    config = _load_config()
    provider = resolve_provider()

    # Non-Gemini providers: no tier-based selection; caller handles defaults
    if provider != "gemini":
        return None

    executor_cfg = config.get("executor", {})
    roles_cfg = executor_cfg.get("roles", {})
    role_cfg = roles_cfg.get(role, {})

    effort_upper = (effort or "").upper()

    # 2. File-pattern floor (implementation role only)
    if file_path:
        floor_patterns = role_cfg.get("file_pattern_floors", [])
        floor_tier = _get_floor_tier(file_path, floor_patterns)
        if floor_tier:
            return _tier_to_model(provider, floor_tier, config)

    # 3. Effort-band lookup
    effort_bands = role_cfg.get("effort_bands", {})
    band_cfg = effort_bands.get(effort_upper)
    if band_cfg:
        tier = band_cfg.get("model_tier")
        if tier:
            return _tier_to_model(provider, tier, config)

    # 4. Default: auto (None means CLI chooses)
    return None


def escalate_model(role: str, current_tier: str) -> str | None:
    """Return the next model up from ``current_tier`` via the escalation ladder.

    Reads the ``executor.escalation`` table from config. Returns ``None`` when
    at the top of the hierarchy (human intervention required).

    Args:
        role: Informational only (used for logging).
        current_tier: The current model tier (``"flash"``, ``"auto"``, ``"pro"``,
                      ``"unknown"``).

    Returns:
        Next model ID string, or ``None`` at the top of the hierarchy.
    """
    config = _load_config()
    provider = resolve_provider()
    executor_cfg = config.get("executor", {})
    escalation_cfg = executor_cfg.get("escalation", {})

    ladder_key = f"{current_tier}_to"
    next_tier = escalation_cfg.get(ladder_key)

    if next_tier is None:
        logger.warning(
            "model_registry: [%s] escalation from tier %r has no next tier -- human intervention required",
            role,
            current_tier,
        )
        return None

    return _tier_to_model(provider, next_tier, config)


def get_model_tier(model_id: str | None) -> str:
    """Map a model ID back to its tier name for telemetry and escalation.

    Returns:
        ``"auto"`` for ``None`` (Gemini auto mode),
        the tier name string (``"pro"``, ``"flash"``, ``"mid"``, etc.) if found,
        or ``"unknown"`` if the model ID is not recognised in any provider config.
    """
    if model_id is None:
        return "auto"

    config = _load_config()
    providers_cfg = config.get("providers", {})

    for _provider_name, provider_cfg in providers_cfg.items():
        models = provider_cfg.get("models", {})
        for tier, mid in models.items():
            if mid == model_id:
                return tier

    return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_floor_tier(file_path: str, patterns: list[dict]) -> str | None:
    """Return the ``min_tier`` for the first pattern that matches ``file_path``.

    Directory patterns (ending with ``/``) use ``startswith``. Filename
    patterns use ``startswith``, ``endswith``, or exact match so that both
    a bare filename and a path ending with it match the pattern.
    """
    for entry in patterns:
        pattern = entry.get("pattern", "")
        if not pattern:
            continue
        if pattern.endswith("/"):
            matches = file_path.startswith(pattern)
        else:
            matches = file_path.startswith(pattern) or file_path.endswith(pattern) or file_path == pattern
        if matches:
            return entry.get("min_tier")
    return None


def _tier_to_model(provider: str, tier: str, config: dict) -> str | None:
    """Convert a tier name to a model ID for the given provider.

    Returns ``None`` for the ``"auto"`` tier (CLI chooses automatically).
    """
    providers_cfg = config.get("providers", {})
    provider_cfg = providers_cfg.get(provider, {})
    models = provider_cfg.get("models", {})
    return models.get(tier)  # "auto" tier maps to None in the YAML
