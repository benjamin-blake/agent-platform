"""Unit tests for src/data/handlers/scheduled_agent_handler.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.data.handlers.scheduled_agent_handler as handler_mod
from src.data.handlers.scheduled_agent_handler import (
    RetiredProviderError,
    _get_github_pat,
    _invoke_github_models,
    _load_manifest,
    _load_prompt,
    handler,
)


class TestGetGithubPat:
    """Tests for _get_github_pat()."""

    def test_returns_env_var_pat_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_PAT", "ghp_direct_token")
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)
        assert _get_github_pat() == "ghp_direct_token"

    def test_returns_empty_when_no_env_and_no_arn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)
        assert _get_github_pat() == ""

    @pytest.mark.integration
    def test_fetches_from_secrets_manager_when_arn_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.setenv("GITHUB_PAT_SECRET_ARN", "arn:aws:secretsmanager:eu-west-2:123:secret/pat")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "ghp_from_secrets"}  # pragma: allowlist secret
        with patch("boto3.client", return_value=mock_client):
            result = _get_github_pat()
        assert result == "ghp_from_secrets"

    @pytest.mark.integration
    def test_returns_empty_on_secrets_manager_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.setenv("GITHUB_PAT_SECRET_ARN", "arn:aws:secretsmanager:eu-west-2:123:secret/pat")
        with patch("boto3.client", side_effect=Exception("access denied")):
            result = _get_github_pat()
        assert result == ""


class TestLoadPrompt:
    """Tests for _load_prompt()."""

    def test_reads_prompt_from_repo_root(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / ".github" / "prompts" / "scheduled" / "test.prompt.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("## Test prompt", encoding="utf-8")
        with patch.object(handler_mod, "_REPO_ROOT", tmp_path):
            result = _load_prompt(".github/prompts/scheduled/test.prompt.md")
        assert result == "## Test prompt"

    def test_returns_empty_when_not_found(self, tmp_path: Path) -> None:
        with patch.object(handler_mod, "_REPO_ROOT", tmp_path):
            result = _load_prompt(".github/prompts/scheduled/missing.prompt.md")
        assert result == ""


class TestLoadManifest:
    """Tests for _load_manifest()."""

    def test_loads_manifest_from_repo_root(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / ".github" / "agents"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "schedule.yaml").write_text(
            "agents:\n  - name: test-agent\n    cron: '0 6 * * 1'\n"
            "    model: gpt-4.1-mini\n    prompt_path: prompts/test.md\n",
            encoding="utf-8",
        )
        with patch.object(handler_mod, "_REPO_ROOT", tmp_path):
            agents = _load_manifest()
        assert len(agents) == 1
        assert agents[0]["name"] == "test-agent"

    def test_returns_empty_when_manifest_missing(self, tmp_path: Path) -> None:
        with patch.object(handler_mod, "_REPO_ROOT", tmp_path):
            agents = _load_manifest()
        assert agents == []


class TestBedrockRetired:
    """Bedrock dispatch left the handler with the CD.28 retirement."""

    def test_invoke_bedrock_absent(self) -> None:
        assert not hasattr(handler_mod, "_invoke_bedrock")
        assert not hasattr(handler_mod, "_get_bedrock_credentials")


class TestInvokeGithubModels:
    """Tests for _invoke_github_models()."""

    def test_returns_content_on_success(self) -> None:
        fake_response = {"choices": [{"message": {"content": "some output"}}]}
        with patch(
            "scripts.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == "some output"
        assert has_error is False

    def test_returns_error_on_api_error(self) -> None:
        fake_response = {"error": True, "message": "Rate limit"}
        with patch(
            "scripts.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == ""
        assert has_error is True
        assert err_msg == "Rate limit"

    def test_returns_error_on_malformed_response(self) -> None:
        fake_response = {"choices": []}
        with patch(
            "scripts.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == ""
        assert has_error is True
        assert "missing content" in err_msg.lower()


class TestHandler:
    """Tests for handler()."""

    @pytest.fixture(autouse=True)
    def _enable_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULED_AGENTS_ENABLED", "true")

    def _make_agent(
        self,
        name: str = "doc-freshness",
        cron: str = "0 6 * * 1",
        provider: str = "github-models",
    ) -> dict:
        return {
            "name": name,
            "cron": cron,
            "model": "gpt-4.1-mini",
            "prompt_path": ".github/prompts/scheduled/test.prompt.md",
            "provider": provider,
        }

    def test_counts_failed_agent_when_pat_unavailable(self) -> None:
        """Missing PAT fails github-models agent without global early return."""
        agents = [self._make_agent(provider="github-models")]
        with (
            patch.object(handler_mod, "_get_github_pat", return_value=""),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
        ):
            result = handler({}, None)
        assert result["agents_run"] == 0
        assert result["agents_failed"] == 1

    def test_runs_due_agents_and_writes_findings(self) -> None:
        fake_response = {"choices": [{"message": {"content": ('[{"title": "stale doc", "file": "ARCH.md"}]')}}]}
        agents = [self._make_agent()]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="test prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value=fake_response,
            ),
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/doc-freshness/ts.jsonl",
            ),
        ):
            result = handler({}, None)

        assert result["agents_run"] == 1
        assert result["agents_failed"] == 0
        assert result["total_findings"] == 1
        assert "agents/doc-freshness/ts.jsonl" in result["keys_written"]

    def test_skips_agent_when_not_due(self) -> None:
        agents = [self._make_agent()]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=False,
            ),
        ):
            result = handler({}, None)

        assert result["agents_run"] == 0
        assert result["agents_failed"] == 0

    def test_counts_failed_agent_on_api_error(self) -> None:
        agents = [self._make_agent()]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="test prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value={"error": True, "message": "Rate limit"},
            ),
        ):
            result = handler({}, None)

        assert result["agents_run"] == 0
        assert result["agents_failed"] == 1

    def test_counts_failed_agent_when_prompt_missing(self) -> None:
        agents = [self._make_agent()]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value=""),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
        ):
            result = handler({}, None)

        assert result["agents_run"] == 0
        assert result["agents_failed"] == 1

    def test_counts_failed_agent_when_write_fails(self) -> None:
        agents = [self._make_agent()]
        fake_response = {"choices": [{"message": {"content": "[]"}}]}

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value=fake_response,
            ),
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="",
            ),
        ):
            result = handler({}, None)

        assert result["agents_failed"] == 1

    def test_model_override_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULED_AGENT_MODEL", "gemini-3.0-flash")
        agents = [self._make_agent()]
        fake_response = {"choices": [{"message": {"content": "[]"}}]}
        captured_calls: list[dict] = []

        def mock_chat(**kwargs: object) -> dict:
            captured_calls.append(dict(kwargs))
            return fake_response

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                side_effect=mock_chat,
            ),
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/x/ts.jsonl",
            ),
        ):
            handler({}, None)

        assert captured_calls[0]["model"] == "gemini-3.0-flash"

    def test_retired_bedrock_provider_falls_through_to_default_branch(self) -> None:
        """provider: bedrock has no branch (CD.28); it hits the github-models default."""
        agents = [
            self._make_agent(
                name="code-smell",
                provider="bedrock",
            )
        ]
        fake_response = {"choices": [{"message": {"content": "[]"}}]}

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test") as mock_pat,
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value=fake_response,
            ) as mock_gh,
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/code-smell/ts.jsonl",
            ),
        ):
            result = handler({}, None)

        # No Bedrock branch remains: the agent transits the default
        # (github-models) branch, which requires the PAT.
        mock_pat.assert_called_once()
        mock_gh.assert_called_once()
        assert result["agents_run"] == 1

    def test_default_missing_provider_falls_back_to_github_models(
        self,
    ) -> None:
        """Agent without a provider field defaults to github-models."""
        agent = {
            "name": "legacy-agent",
            "cron": "0 6 * * 1",
            "model": "gpt-4.1-mini",
            "prompt_path": ".github/prompts/scheduled/test.prompt.md",
            # No "provider" key -- must default to github-models
        }
        fake_response = {"choices": [{"message": {"content": "[]"}}]}

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(handler_mod, "_load_manifest", return_value=[agent]),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value=fake_response,
            ) as mock_gh,
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/legacy-agent/ts.jsonl",
            ),
        ):
            result = handler({}, None)

        # Should have called github-models, not bedrock
        mock_gh.assert_called_once()
        assert result["agents_run"] == 1

    def test_retired_provider_agent_short_circuits_before_pat_lookup(self) -> None:
        """A retired-provider agent fails without consuming the shared PAT lookup."""
        sdk_agent = self._make_agent(name="sdk-agent", provider="copilot-sdk")
        sdk_agent["model"] = "claude-haiku-4.5"
        gh_agent = self._make_agent(name="gh-agent", provider="github-models")
        agents = [sdk_agent, gh_agent]

        fake_gh_response = {"choices": [{"message": {"content": "[]"}}]}

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="ghp_test") as mock_pat,
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
                return_value=fake_gh_response,
            ),
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/x/ts.jsonl",
            ),
        ):
            result = handler({}, None)

        # Only the github-models agent needs the PAT; the retired-provider
        # agent fails before reaching the shared PAT lookup.
        mock_pat.assert_called_once()
        assert result["agents_run"] == 1
        assert result["agents_failed"] == 1

    def test_missing_pat_fails_github_models_only(self) -> None:
        """Without a PAT, the github-models agent fails; the retired-provider agent already failed."""
        sdk_agent = self._make_agent(name="sdk-agent", provider="copilot-sdk")
        sdk_agent["model"] = "claude-haiku-4.5"
        gh_agent = self._make_agent(name="gh-agent", provider="github-models")
        agents = [sdk_agent, gh_agent]

        with (
            patch.object(handler_mod, "_get_github_pat", return_value="") as mock_pat,
            patch.object(handler_mod, "_load_manifest", return_value=agents),
            patch.object(handler_mod, "_load_prompt", return_value="prompt"),
            patch(
                "scripts.run_scheduled_agent.is_agent_due",
                return_value=True,
            ),
            patch(
                "scripts.github_models_client.chat_completion",
            ) as mock_gh,
            patch(
                "scripts.s3_log_store.write_timestamped_findings",
                return_value="agents/x/ts.jsonl",
            ),
        ):
            result = handler({}, None)

        mock_pat.assert_called_once()
        mock_gh.assert_not_called()
        assert result["agents_run"] == 0
        assert result["agents_failed"] == 2


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
            patch("scripts.github_models_client.chat_completion") as mock_gh,
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
                "scripts.github_models_client.chat_completion",
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
                "scripts.github_models_client.chat_completion",
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
