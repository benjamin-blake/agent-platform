"""Loader / helper-function concern of src/data/handlers/scheduled_agent_handler.py (rec-2709 Wave 11).

Covers _get_github_pat, _load_prompt, _load_manifest, the Bedrock-retirement absence check, and
_invoke_github_models. Split from tests/test_scheduled_agent_handler.py (VERBATIM move).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.data.handlers.scheduled_agent_handler as handler_mod
from src.data.handlers.scheduled_agent_handler import (
    _get_github_pat,
    _invoke_github_models,
    _load_manifest,
    _load_prompt,
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
            "scripts.llm.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == "some output"
        assert has_error is False

    def test_returns_error_on_api_error(self) -> None:
        fake_response = {"error": True, "message": "Rate limit"}
        with patch(
            "scripts.llm.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == ""
        assert has_error is True
        assert err_msg == "Rate limit"

    def test_returns_error_on_malformed_response(self) -> None:
        fake_response = {"choices": []}
        with patch(
            "scripts.llm.github_models_client.chat_completion",
            return_value=fake_response,
        ):
            output, has_error, err_msg = _invoke_github_models("prompt", "gpt-4.1-mini", "ghp_test")
        assert output == ""
        assert has_error is True
        assert "missing content" in err_msg.lower()
