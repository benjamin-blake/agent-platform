"""Tests for scripts.model_registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.model_registry as registry_mod
from scripts.model_registry import (
    _get_floor_tier,
    _load_config,
    escalate_model,
    get_model_tier,
    resolve_model,
    resolve_provider,
)

# ---------------------------------------------------------------------------
# Minimal config fixture
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG = {
    "providers": {
        "gemini": {
            "models": {
                "pro": "gemini-3-pro-preview",
                "flash": "gemini-3-flash-preview",
                "auto": None,
            }
        },
        "bedrock": {
            "models": {
                "mid": "deepseek.v3.2",
                "opus": "claude-opus-4.6",
            }
        },
    },
    "executor": {
        "default_provider": "gemini",
        "roles": {
            "planning": {
                "effort_bands": {
                    "XS": {"model_tier": "flash"},
                    "S": {"model_tier": "auto"},
                    "M": {"model_tier": "auto"},
                    "L": {"model_tier": "pro"},
                    "XL": {"model_tier": "pro"},
                }
            },
            "implementation": {
                "effort_bands": {
                    "XS": {"model_tier": "flash"},
                    "S": {"model_tier": "auto"},
                    "M": {"model_tier": "auto"},
                    "L": {"model_tier": "pro"},
                    "XL": {"model_tier": "pro"},
                },
                "file_pattern_floors": [
                    {"pattern": "scripts/executor/", "min_tier": "pro"},
                    {"pattern": "scripts/validate.py", "min_tier": "pro"},
                    {"pattern": "config/prompts/", "min_tier": "pro"},
                    {"pattern": ".github/prompts/", "min_tier": "pro"},
                    {"pattern": ".github/instructions/", "min_tier": "pro"},
                    {"pattern": ".github/agents/", "min_tier": "pro"},
                    {"pattern": "copilot-instructions.md", "min_tier": "pro"},
                ],
            },
            "review": {
                "effort_bands": {
                    "XS": {"model_tier": "flash"},
                    "S": {"model_tier": "auto"},
                    "M": {"model_tier": "auto"},
                    "L": {"model_tier": "pro"},
                    "XL": {"model_tier": "pro"},
                }
            },
        },
        "escalation": {
            "flash_to": "auto",
            "auto_to": "pro",
            "pro_to": None,
        },
    },
}


@pytest.fixture(autouse=True)
def reset_config() -> None:  # type: ignore[return]
    """Clear the module-level config cache before each test."""
    registry_mod._CONFIG = None
    yield
    registry_mod._CONFIG = None


@pytest.fixture
def mock_config() -> None:  # type: ignore[return]
    """Patch _load_config to return the minimal fixture config."""
    with patch.object(registry_mod, "_load_config", return_value=_MINIMAL_CONFIG):
        yield


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------


class TestResolveProvider:
    def test_defaults_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert resolve_provider() == "gemini"

    def test_reads_env_var_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert resolve_provider() == "gemini"

    def test_reads_env_var_bedrock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        assert resolve_provider() == "bedrock"

    def test_invalid_provider_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert resolve_provider() == "gemini"

    def test_empty_string_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "")
        assert resolve_provider() == "gemini"


# ---------------------------------------------------------------------------
# resolve_model -- planning role
# ---------------------------------------------------------------------------


class TestResolveModelPlanning:
    def test_xs_returns_flash(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "XS") == "gemini-3-flash-preview"

    def test_s_returns_none_auto(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "S") is None

    def test_m_returns_none_auto(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "M") is None

    def test_l_returns_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "L") == "gemini-3-pro-preview"

    def test_xl_returns_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "XL") == "gemini-3-pro-preview"

    def test_unknown_effort_returns_none(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "UNKNOWN") is None

    def test_empty_effort_returns_none(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "") is None

    def test_lowercase_effort_normalised(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "xs") == "gemini-3-flash-preview"
        assert resolve_model("planning", "l") == "gemini-3-pro-preview"

    def test_env_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.setenv("COPILOT_MODEL_PLANNING", "my-custom-model")
        assert resolve_model("planning", "XS") == "my-custom-model"
        assert resolve_model("planning", "L") == "my-custom-model"

    def test_bedrock_provider_returns_none(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        assert resolve_model("planning", "XS") is None


# ---------------------------------------------------------------------------
# resolve_model -- implementation role
# ---------------------------------------------------------------------------


class TestResolveModelImplementation:
    def test_xs_returns_flash(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        assert resolve_model("implementation", "XS") == "gemini-3-flash-preview"

    def test_l_returns_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        assert resolve_model("implementation", "L") == "gemini-3-pro-preview"

    def test_executor_file_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path="scripts/executor/plan.py")
        assert result == "gemini-3-pro-preview"

    def test_executor_step_runner_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path="scripts/executor/step_runner.py")
        assert result == "gemini-3-pro-preview"

    def test_validate_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path="scripts/validate.py")
        assert result == "gemini-3-pro-preview"

    def test_config_prompts_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path="config/prompts/planning.prompt.md")
        assert result == "gemini-3-pro-preview"

    def test_github_prompts_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "M", file_path=".github/prompts/implement.prompt.md")
        assert result == "gemini-3-pro-preview"

    def test_github_instructions_floor_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "S", file_path=".github/instructions/executor-review.instructions.md")
        assert result == "gemini-3-pro-preview"

    def test_copilot_instructions_floor_endswith_match(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path=".github/copilot-instructions.md")
        assert result == "gemini-3-pro-preview"

    def test_regular_file_no_floor(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        result = resolve_model("implementation", "XS", file_path="scripts/some_script.py")
        assert result == "gemini-3-flash-preview"

    def test_env_override_takes_precedence_over_floor(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.setenv("COPILOT_MODEL_EXECUTION", "my-override")
        result = resolve_model("implementation", "XS", file_path="scripts/executor/plan.py")
        assert result == "my-override"


# ---------------------------------------------------------------------------
# resolve_model -- review role
# ---------------------------------------------------------------------------


class TestResolveModelReview:
    def test_xs_returns_flash(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_REVIEW", raising=False)
        assert resolve_model("review", "XS") == "gemini-3-flash-preview"

    def test_m_returns_none_auto(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_REVIEW", raising=False)
        assert resolve_model("review", "M") is None

    def test_l_returns_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_REVIEW", raising=False)
        assert resolve_model("review", "L") == "gemini-3-pro-preview"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.setenv("COPILOT_MODEL_REVIEW", "custom-review-model")
        assert resolve_model("review", "M") == "custom-review-model"


# ---------------------------------------------------------------------------
# escalate_model
# ---------------------------------------------------------------------------


class TestEscalateModel:
    def test_flash_escalates_to_auto(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        result = escalate_model("planning", "flash")
        assert result is None  # auto tier maps to None in models YAML

    def test_auto_escalates_to_pro(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        result = escalate_model("planning", "auto")
        assert result == "gemini-3-pro-preview"

    def test_pro_returns_none_top_of_hierarchy(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        result = escalate_model("planning", "pro")
        assert result is None

    def test_unknown_tier_returns_none(self, monkeypatch: pytest.MonkeyPatch, mock_config: None) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        result = escalate_model("planning", "unknown")
        assert result is None


# ---------------------------------------------------------------------------
# get_model_tier
# ---------------------------------------------------------------------------


class TestGetModelTier:
    def test_none_returns_auto(self, mock_config: None) -> None:
        assert get_model_tier(None) == "auto"

    def test_gemini_pro_returns_pro(self, mock_config: None) -> None:
        assert get_model_tier("gemini-3-pro-preview") == "pro"

    def test_gemini_flash_returns_flash(self, mock_config: None) -> None:
        assert get_model_tier("gemini-3-flash-preview") == "flash"

    def test_bedrock_deepseek_returns_mid(self, mock_config: None) -> None:
        assert get_model_tier("deepseek.v3.2") == "mid"

    def test_unknown_model_returns_unknown(self, mock_config: None) -> None:
        assert get_model_tier("some-unknown-model-v999") == "unknown"


# ---------------------------------------------------------------------------
# _load_config -- missing file fallback
# ---------------------------------------------------------------------------


class TestLoadConfigFallback:
    def test_missing_config_returns_empty_dict(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent.yaml"
        with patch.object(registry_mod, "_CONFIG_PATH", nonexistent):
            registry_mod._CONFIG = None
            result = _load_config()
        assert result == {}

    def test_missing_config_resolve_model_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        nonexistent = tmp_path / "nonexistent.yaml"
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        with patch.object(registry_mod, "_CONFIG_PATH", nonexistent):
            registry_mod._CONFIG = None
            result = resolve_model("planning", "L")
        assert result is None

    def test_malformed_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(": : : invalid yaml :::", encoding="utf-8")
        with patch.object(registry_mod, "_CONFIG_PATH", bad_yaml):
            registry_mod._CONFIG = None
            result = _load_config()
        assert result == {}


# ---------------------------------------------------------------------------
# _get_floor_tier
# ---------------------------------------------------------------------------


class TestGetFloorTier:
    _PATTERNS = [
        {"pattern": "scripts/executor/", "min_tier": "pro"},
        {"pattern": "scripts/validate.py", "min_tier": "pro"},
        {"pattern": "copilot-instructions.md", "min_tier": "pro"},
    ]

    def test_executor_dir_match(self) -> None:
        assert _get_floor_tier("scripts/executor/plan.py", self._PATTERNS) == "pro"

    def test_exact_filename_match(self) -> None:
        assert _get_floor_tier("scripts/validate.py", self._PATTERNS) == "pro"

    def test_endswith_match(self) -> None:
        assert _get_floor_tier(".github/copilot-instructions.md", self._PATTERNS) == "pro"

    def test_no_match_returns_none(self) -> None:
        assert _get_floor_tier("scripts/some_script.py", self._PATTERNS) is None

    def test_empty_file_path_returns_none(self) -> None:
        assert _get_floor_tier("", self._PATTERNS) is None

    def test_empty_patterns_returns_none(self) -> None:
        assert _get_floor_tier("scripts/executor/plan.py", []) is None

    def test_first_match_wins(self) -> None:
        patterns = [
            {"pattern": "scripts/executor/", "min_tier": "flash"},
            {"pattern": "scripts/executor/plan.py", "min_tier": "pro"},
        ]
        assert _get_floor_tier("scripts/executor/plan.py", patterns) == "flash"
