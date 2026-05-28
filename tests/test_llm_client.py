"""Tests for scripts.llm_client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.llm_client import (
    LLMResult,
    _compute_cost,
    _gemini_call,
    _resolve_model_id,
    _resolve_provider,
    llm_call,
)
from scripts.llm_utils import LLMResponseError


class TestImports:
    def test_import_llm_call(self) -> None:
        from scripts.llm_client import llm_call  # noqa: F811

        assert callable(llm_call)

    def test_import_llm_result(self) -> None:
        from scripts.llm_client import LLMResult  # noqa: F811

        r = LLMResult(
            content="ok",
            exit_code=0,
            session_id="abc",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.01,
            model="test",
        )
        assert r.content == "ok"
        assert r.tokens_in == 10
        assert r.tokens_out == 20
        assert r.cost_usd == 0.01
        assert r.model == "test"


class TestResolveModelId:
    def test_maps_shortname(self) -> None:
        assert _resolve_model_id("deepseek.v3.2") == "deepseek.v3.2"

    def test_maps_sonnet(self) -> None:
        result = _resolve_model_id("claude-sonnet-4.6")
        assert "anthropic" in result

    def test_passthrough_unknown(self) -> None:
        assert _resolve_model_id("custom.model.v1") == "custom.model.v1"

    def test_default_from_env(self) -> None:
        with patch.dict("os.environ", {"COPILOT_MODEL_EXECUTION": "deepseek.v3.2"}):
            result = _resolve_model_id(None)
            assert "deepseek" in result


class TestComputeCost:
    def test_known_model(self) -> None:
        cost = _compute_cost("deepseek.v3.2", 1_000_000, 1_000_000)
        assert abs(cost - (0.90 + 2.61)) < 0.01

    def test_unknown_model_returns_zero(self) -> None:
        # Unknown models (including Gemini) have no entry in _PRICING -- cost is 0.0
        cost = _compute_cost("unknown.model", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_none_model_returns_zero(self) -> None:
        cost = _compute_cost(None, 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_gemini_pro_returns_zero(self) -> None:
        cost = _compute_cost("gemini-3-pro-preview", 1_000_000, 1_000_000)
        assert cost == 0.0


class TestResolveProvider:
    def test_defaults_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert _resolve_provider() == "gemini"

    def test_env_var_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert _resolve_provider() == "gemini"

    def test_env_var_bedrock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        assert _resolve_provider() == "bedrock"

    def test_invalid_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert _resolve_provider() == "gemini"


class TestDataResidency:
    @patch("scripts.bedrock_client.converse")
    def test_uses_eu_west_2(self, mock_converse: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        mock_converse.return_value = {
            "content": "ok",
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
            "error": False,
            "message": "",
        }
        llm_call("test", tools=False, check=False)
        _, kwargs = mock_converse.call_args
        assert kwargs["region"] == "eu-west-2"


@patch.dict("os.environ", {"LLM_PROVIDER": "bedrock"})
class TestLLMCall:
    @patch("scripts.bedrock_client.converse")
    def test_single_turn_returns_llm_result(self, mock_converse: MagicMock) -> None:
        mock_converse.return_value = {
            "content": "response text",
            "stop_reason": "end_turn",
            "input_tokens": 100,
            "output_tokens": 50,
            "error": False,
            "message": "",
        }
        result = llm_call("test prompt", tools=False)
        assert isinstance(result, LLMResult)
        assert result.content == "response text"
        assert result.exit_code == 0
        assert result.tokens_in == 100
        assert result.tokens_out == 50

    @patch("scripts.bedrock_client.converse")
    def test_empty_response_raises_when_check(self, mock_converse: MagicMock) -> None:
        mock_converse.return_value = {
            "content": "",
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 0,
            "error": False,
            "message": "",
        }
        with pytest.raises(LLMResponseError, match="empty"):
            llm_call("test", tools=False, check=True)

    @patch("scripts.bedrock_client.converse")
    def test_error_raises_when_check(self, mock_converse: MagicMock) -> None:
        mock_converse.return_value = {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": "model unavailable",
        }
        with pytest.raises(LLMResponseError, match="model unavailable"):
            llm_call("test", tools=False, check=True)

    @patch("scripts.bedrock_client.converse")
    def test_error_returns_result_when_no_check(self, mock_converse: MagicMock) -> None:
        mock_converse.return_value = {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": "model unavailable",
        }
        result = llm_call("test", tools=False, check=False)
        assert result.exit_code == 1

    @patch("scripts.bedrock_client.converse")
    def test_context_file_path_prepended(self, mock_converse: MagicMock, tmp_path: Path) -> None:
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("CONTEXT DATA", encoding="utf-8")
        mock_converse.return_value = {
            "content": "ok",
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
            "error": False,
            "message": "",
        }
        llm_call("my prompt", tools=False, context_file_path=str(ctx_file))
        call_args = mock_converse.call_args
        prompt_sent = call_args[1]["prompt"]
        assert "CONTEXT DATA" in prompt_sent
        assert "my prompt" in prompt_sent

    @patch("scripts.bedrock_client.converse_with_tools")
    def test_tools_mode_uses_converse_with_tools(self, mock_cwt: MagicMock) -> None:
        mock_cwt.return_value = {
            "content": "done",
            "stop_reason": "end_turn",
            "input_tokens": 50,
            "output_tokens": 30,
            "error": False,
            "message": "",
            "turn_count": 3,
        }
        result = llm_call("implement this", tools=True)
        assert result.content == "done"
        mock_cwt.assert_called_once()


class TestGeminiCall:
    """Tests for _gemini_call() -- Gemini CLI transport."""

    _GOOD_RESPONSE = {
        "response": "Hello from Gemini",
        "stats": {
            "models": {
                "gemini-3-flash-preview": {
                    "tokens": {"input": 20, "candidates": 10},
                }
            }
        },
    }

    def _make_proc(
        self,
        stdout: str = "",
        returncode: int = 0,
        stderr: str = "",
    ) -> MagicMock:
        proc = MagicMock()
        proc.stdout = stdout
        proc.returncode = returncode
        proc.stderr = stderr
        return proc

    @patch("subprocess.run")
    def test_success_returns_llm_result(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(
            stdout=json.dumps(
                {
                    "response": "Hello",
                    "stats": {
                        "models": {
                            "gemini-3-flash-preview": {
                                "tokens": {"input": 5, "candidates": 3},
                            }
                        }
                    },
                }
            )
        )
        result = _gemini_call(
            prompt="Hi",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=True,
        )
        assert result.content == "Hello"
        assert result.exit_code == 0
        assert result.tokens_in == 5
        assert result.tokens_out == 3
        assert result.cost_usd == 0.0
        # Verify prompt piped via stdin, not on command line
        _, call_kwargs = mock_run.call_args
        assert call_kwargs["input"] == "Hi"
        cmd = mock_run.call_args[0][0]
        assert "Hi" not in cmd  # prompt must NOT be inline

    @patch("subprocess.run")
    def test_legacy_token_usage_fallback(self, mock_run: MagicMock) -> None:
        """Fallback to tokenUsage format if models dict is absent."""
        mock_run.return_value = self._make_proc(
            stdout='{"response": "ok", "stats": {"tokenUsage": {"inputTokens": 7, "outputTokens": 2}}}'
        )
        result = _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=True,
        )
        assert result.tokens_in == 7
        assert result.tokens_out == 2

    @patch("subprocess.run")
    def test_multi_model_token_aggregation(self, mock_run: MagicMock) -> None:
        """Tokens from multiple models are summed."""
        mock_run.return_value = self._make_proc(
            stdout=json.dumps(
                {
                    "response": "ok",
                    "stats": {
                        "models": {
                            "gemini-2.5-flash-lite": {"tokens": {"input": 100, "candidates": 10}},
                            "gemini-3-flash-preview": {"tokens": {"input": 200, "candidates": 20}},
                        }
                    },
                }
            )
        )
        result = _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=True,
        )
        assert result.tokens_in == 300
        assert result.tokens_out == 30

    @patch("subprocess.run")
    def test_with_explicit_model_adds_model_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": {}}')
        _gemini_call(
            prompt="test",
            model="gemini-3-pro-preview",
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "gemini-3-pro-preview" in cmd

    @patch("subprocess.run")
    def test_no_model_omits_model_flag(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": {}}')
        _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        cmd = mock_run.call_args[0][0]
        assert "--model" not in cmd

    @patch("subprocess.run")
    def test_command_includes_output_format_stream_json(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": {}}')
        _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        cmd = mock_run.call_args[0][0]
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    @patch("subprocess.run")
    def test_jsonl_stream_format_parsed(self, mock_run: MagicMock) -> None:
        """stream-json JSONL events are parsed: session_id from init, content from messages, tokens from result."""
        jsonl = "\n".join(
            [
                json.dumps({"type": "init", "session_id": "gemini-sess-xyz", "model": "gemini-3-flash-preview"}),
                json.dumps({"type": "message", "role": "assistant", "content": "Hello ", "delta": True}),
                json.dumps({"type": "message", "role": "assistant", "content": "Gemini", "delta": True}),
                json.dumps(
                    {
                        "type": "result",
                        "status": "success",
                        "stats": {
                            "input_tokens": 42,
                            "output_tokens": 7,
                            "models": {"gemini-3-flash-preview": {"input_tokens": 42, "output_tokens": 7}},
                        },
                    }
                ),
            ]
        )
        mock_run.return_value = self._make_proc(stdout=jsonl)
        result = _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="fallback-uuid",
            check=True,
        )
        assert result.content == "Hello Gemini"
        assert result.session_id == "gemini-sess-xyz"  # from init event, not our UUID
        assert result.tokens_in == 42
        assert result.tokens_out == 7

    @patch("subprocess.run")
    def test_resume_session_id_adds_resume_flag(self, mock_run: MagicMock) -> None:
        """resume_session_id appends --resume <id> to the CLI command."""
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": {}}')
        _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
            resume_session_id="prev-session-123",
        )
        cmd = mock_run.call_args[0][0]
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "prev-session-123"

    @patch("subprocess.run")
    def test_no_resume_session_id_omits_resume_flag(self, mock_run: MagicMock) -> None:
        """When resume_session_id is None, no --resume flag is added."""
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": {}}')
        _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        cmd = mock_run.call_args[0][0]
        assert "--resume" not in cmd
        mock_run.return_value = self._make_proc(returncode=53, stderr="turn limit")
        with pytest.raises(LLMResponseError, match="turn limit"):
            _gemini_call(
                prompt="test",
                model=None,
                tools=False,
                timeout=60,
                purpose="test",
                session_id="abc",
                check=True,
            )

    @patch("subprocess.run")
    def test_exit_1_empty_stdout_raises_when_check(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(returncode=1, stderr="some error")
        with pytest.raises(LLMResponseError, match="Gemini CLI exited"):
            _gemini_call(
                prompt="test",
                model=None,
                tools=False,
                timeout=60,
                purpose="test",
                session_id="abc",
                check=True,
            )

    @patch("subprocess.run")
    def test_exit_1_empty_stdout_returns_result_when_no_check(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(returncode=1, stderr="some error")
        result = _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        assert result.exit_code == 1

    @patch("subprocess.run")
    def test_non_json_stdout_raises_when_check(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout="not json at all")
        with pytest.raises(LLMResponseError, match="non-JSON"):
            _gemini_call(
                prompt="test",
                model=None,
                tools=False,
                timeout=60,
                purpose="test",
                session_id="abc",
                check=True,
            )

    @patch("subprocess.run")
    def test_empty_response_field_raises_when_check(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "", "stats": {}}')
        with pytest.raises(LLMResponseError, match="empty"):
            _gemini_call(
                prompt="test",
                model=None,
                tools=False,
                timeout=60,
                purpose="test",
                session_id="abc",
                check=True,
            )

    @patch("subprocess.run")
    def test_api_error_in_json_raises_when_check(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "", "error": {"message": "quota exceeded"}, "stats": {}}')
        with pytest.raises(LLMResponseError, match="Gemini CLI error"):
            _gemini_call(
                prompt="test",
                model=None,
                tools=False,
                timeout=60,
                purpose="test",
                session_id="abc",
                check=True,
            )

    @patch("subprocess.run")
    def test_missing_stats_field_defaults_to_zero(self, mock_run: MagicMock) -> None:
        mock_run.return_value = self._make_proc(stdout='{"response": "Hello", "stats": null}')
        result = _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=True,
        )
        assert result.tokens_in == 0
        assert result.tokens_out == 0

    @patch("subprocess.run")
    def test_trust_workspace_env_var_injected(self, mock_run: MagicMock) -> None:
        """GEMINI_CLI_TRUST_WORKSPACE=true must be present in subprocess env."""
        mock_run.return_value = self._make_proc(stdout='{"response": "ok", "stats": null}')
        _gemini_call(
            prompt="test",
            model=None,
            tools=False,
            timeout=60,
            purpose="test",
            session_id="abc",
            check=False,
        )
        _, call_kwargs = mock_run.call_args
        assert "env" in call_kwargs
        assert call_kwargs["env"].get("GEMINI_CLI_TRUST_WORKSPACE") == "true"


class TestProviderRouting:
    """Tests that llm_call() routes to the correct transport based on LLM_PROVIDER."""

    @patch("scripts.llm_client._gemini_call")
    def test_llm_provider_gemini_routes_to_gemini(self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        mock_gemini.return_value = LLMResult(
            content="gemini response",
            exit_code=0,
            session_id="x",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
            model="gemini-auto",
        )
        result = llm_call("test prompt", tools=False)
        mock_gemini.assert_called_once()
        assert result.content == "gemini response"

    @patch("scripts.bedrock_client.converse")
    def test_llm_provider_bedrock_routes_to_bedrock(self, mock_converse: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        mock_converse.return_value = {
            "content": "bedrock response",
            "stop_reason": "end_turn",
            "input_tokens": 10,
            "output_tokens": 5,
            "error": False,
            "message": "",
        }
        result = llm_call("test prompt", tools=False)
        mock_converse.assert_called_once()
        assert result.content == "bedrock response"

    @patch("scripts.llm_client._gemini_call")
    def test_no_llm_provider_defaults_to_gemini(self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        mock_gemini.return_value = LLMResult(
            content="gemini default",
            exit_code=0,
            session_id="x",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
            model="gemini-auto",
        )
        result = llm_call("test prompt", tools=False)
        mock_gemini.assert_called_once()
        assert result.content == "gemini default"
