"""Unit tests for scripts/executor/model_routing.py."""

from __future__ import annotations

from unittest.mock import patch

import scripts.llm.model_registry as model_registry_mod
from scripts.executor.model_routing import (
    _IMPL_FAILURE_COUNT,
    _PLANNING_FAILURE_COUNT,
    escalate_implementation_model,
    escalate_planning_model,
    get_implementation_model,
    get_planning_model,
)


class TestGetPlanningModel:
    """Tests for get_planning_model()."""

    @patch("scripts.llm.model_registry.resolve_model", return_value=None)
    def test_returns_none_for_auto_mode(self, mock_resolve: object) -> None:
        result = get_planning_model("XS")
        assert result is None

    @patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview")
    def test_returns_model_for_effort(self, mock_resolve: object) -> None:
        result = get_planning_model("S")
        assert result == "gemini-3-flash-preview"

    @patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview")
    def test_returns_pro_for_large_effort(self, mock_resolve: object) -> None:
        result = get_planning_model("L")
        assert result == "gemini-3-pro-preview"


class TestEscalatePlanningModel:
    """Tests for escalate_planning_model()."""

    def test_under_threshold_returns_current(self) -> None:
        rec_id = "rec-test-plan-esc-1"
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_planning_model(rec_id, "current-model")
            # First failure (count=1) -- threshold is 2, so no escalation
            mock_esc.assert_not_called()
            assert result == "current-model"
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)

    def test_at_threshold_escalates(self) -> None:
        rec_id = "rec-test-plan-esc-2"
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)
        _PLANNING_FAILURE_COUNT[rec_id] = 1  # Next call makes it 2 (threshold)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model", return_value="gemini-3-pro-preview") as mock_esc,
        ):
            result = escalate_planning_model(rec_id, "current-model")
            mock_esc.assert_called_once()
            assert result == "gemini-3-pro-preview"
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)

    def test_at_top_returns_none(self) -> None:
        rec_id = "rec-test-plan-esc-3"
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)
        _PLANNING_FAILURE_COUNT[rec_id] = 1
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="opus"),
            patch.object(model_registry_mod, "escalate_model", return_value=None),
        ):
            result = escalate_planning_model(rec_id, "claude-opus-4.6")
            assert result is None
        _PLANNING_FAILURE_COUNT.pop(rec_id, None)


class TestGetImplementationModel:
    """Tests for get_implementation_model()."""

    @patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview")
    def test_returns_model(self, mock_resolve: object) -> None:
        result = get_implementation_model("XS")
        assert result == "gemini-3-flash-preview"

    @patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview")
    def test_file_floor_override(self, mock_resolve: object) -> None:
        result = get_implementation_model("XS", "scripts/executor/plan.py")
        assert result == "gemini-3-pro-preview"

    @patch("scripts.llm.model_registry.resolve_model", return_value=None)
    def test_returns_none_for_auto(self, mock_resolve: object) -> None:
        result = get_implementation_model("XS")
        assert result is None


class TestEscalateImplementationModel:
    """Tests for escalate_implementation_model()."""

    def test_under_threshold_returns_current(self) -> None:
        rec_id = "rec-test-impl-esc-1"
        _IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "current-model")
            # First failure (count=1), threshold for non-flash is 3
            mock_esc.assert_not_called()
            assert result == "current-model"
        _IMPL_FAILURE_COUNT.pop(rec_id, None)

    def test_flash_escalates_after_one_failure(self) -> None:
        rec_id = "rec-test-impl-esc-2"
        _IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="flash"),
            patch.object(model_registry_mod, "escalate_model", return_value="gemini-3-pro-preview") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "gpt-5-mini")
            mock_esc.assert_called_once()
            assert result == "gemini-3-pro-preview"
        _IMPL_FAILURE_COUNT.pop(rec_id, None)

    def test_non_flash_escalates_after_three_failures(self) -> None:
        rec_id = "rec-test-impl-esc-3"
        _IMPL_FAILURE_COUNT.pop(rec_id, None)
        _IMPL_FAILURE_COUNT[rec_id] = 2  # Next call makes it 3 (threshold for non-flash)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="pro"),
            patch.object(model_registry_mod, "escalate_model", return_value=None),
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-pro-preview")
            assert result is None  # At top of hierarchy
        _IMPL_FAILURE_COUNT.pop(rec_id, None)
