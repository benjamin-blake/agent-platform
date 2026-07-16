"""Retired-provider + telemetry concern of src/data/handlers/scheduled_agent_handler.py (rec-2709 Wave 11).

Covers TestRetiredProvider (Decision 116: copilot-sdk, gemini) and TestHandlerTelemetry
(agent_telemetry open/close_invocation emission). Split from tests/test_scheduled_agent_handler.py
(VERBATIM move). Each class keeps its own class-scoped _enable_agents autouse fixture verbatim.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import src.data.handlers.scheduled_agent_handler as handler_mod
from src.data.handlers.scheduled_agent_handler import RetiredProviderError, handler


class TestRetiredProvider:
    """Tests for the Decision 116 retired-provider path (copilot-sdk, gemini).

    Decision 116 supersedes Decision 49: copilot-sdk and gemini are retired
    scheduled-agent providers. The handler raises RetiredProviderError
    (caught locally) instead of silently misrouting to github-models.
    """

    @pytest.fixture(autouse=True)
    def _enable_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULED_AGENTS_ENABLED", "true")

    def test_retired_provider_error_is_a_runtime_error(self) -> None:
        assert issubclass(RetiredProviderError, RuntimeError)

    @pytest.mark.parametrize("provider", ["copilot-sdk", "gemini"])
    def test_handler_raises_and_records_retired_provider_as_failure(self, provider: str) -> None:
        """Retired providers fail loudly (no silent misroute to github-models)."""
        agent = {
            "name": "doc-freshness",
            "cron": "0 6 * * 1",
            "model": "claude-haiku-4.5",
            "prompt_path": ".github/prompts/scheduled/doc-freshness.prompt.md",
            "provider": provider,
        }

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test") as mock_pat,
            patch.object(handler_mod, "_load_manifest", return_value=[agent]),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            patch("scripts.llm.github_models_client.chat_completion") as mock_gh,
        ):
            result = handler({}, None)

        mock_gh.assert_not_called()
        mock_pat.assert_not_called()
        assert result["agents_run"] == 0
        assert result["agents_failed"] == 1

    def test_retired_provider_failure_message_names_decision_116(self) -> None:
        agent = {
            "name": "rec-curator",
            "cron": "0 8 * * *",
            "model": "claude-sonnet-4.6",
            "prompt_path": ".github/prompts/scheduled/rec-curator.prompt.md",
            "provider": "copilot-sdk",
        }

        with (
            patch.object(handler_mod, "_load_manifest", return_value=[agent]),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            patch(
                "src.data.handlers.agent_telemetry.close_invocation",
            ) as mock_close,
        ):
            handler({}, None)

        mock_close.assert_called_once()
        error_arg = mock_close.call_args.kwargs.get("error", "")
        assert "Decision 116" in error_arg
        assert "retired" in error_arg.lower()


class TestHandlerTelemetry:
    """Tests that handler() emits telemetry via agent_telemetry functions."""

    @pytest.fixture(autouse=True)
    def _enable_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULED_AGENTS_ENABLED", "true")

    def _make_gh_models_agent(self) -> dict:
        return {
            "name": "doc-freshness",
            "cron": "0 6 * * 1",
            "model": "gpt-4.1-mini",
            "prompt_path": ".github/prompts/scheduled/doc-freshness.prompt.md",
            "provider": "github-models",
        }

    def test_telemetry_emitted_for_successful_run(self) -> None:
        """open_invocation and close_invocation called with correct args for a successful run."""
        agents = [self._make_gh_models_agent()]
        fake_response = {"choices": [{"message": {"content": "[]"}}]}

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="test prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            patch(
                "scripts.llm.github_models_client.chat_completion",
                return_value=fake_response,
            ),
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/doc-freshness/ts.jsonl",
            ),
            patch(
                "src.data.handlers.agent_telemetry.open_invocation",
            ) as mock_open,
            patch(
                "src.data.handlers.agent_telemetry.close_invocation",
            ) as mock_close,
        ):
            result = handler({}, None)

        mock_open.assert_called_once_with(
            agent_name="doc-freshness",
            trigger="eventbridge",
            model="gpt-4.1-mini",
            provider="github-models",
        )
        mock_close.assert_called_once()
        close_kwargs = mock_close.call_args
        outcome_arg = close_kwargs.kwargs.get("outcome") or (close_kwargs.args[0] if close_kwargs.args else None)
        assert outcome_arg == "success"
        assert result["agents_run"] == 1

    def test_close_invocation_called_with_failed_on_api_error(self) -> None:
        """close_invocation(outcome='failed') called when agent API call returns error."""
        agents = [self._make_gh_models_agent()]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="test prompt"),
            patch("scripts.run_scheduled_agent.is_agent_due", return_value=True),
            patch(
                "scripts.llm.github_models_client.chat_completion",
                return_value={"error": True, "message": "API timeout"},
            ),
            patch(
                "src.data.handlers.agent_telemetry.open_invocation",
            ),
            patch(
                "src.data.handlers.agent_telemetry.close_invocation",
            ) as mock_close,
        ):
            result = handler({}, None)

        mock_close.assert_called_once()
        close_kwargs = mock_close.call_args
        outcome_arg = close_kwargs.kwargs.get("outcome") or (close_kwargs.args[0] if close_kwargs.args else None)
        assert outcome_arg == "failed"
        assert result["agents_failed"] == 1
