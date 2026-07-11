"""Tests for scripts.llm.client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.llm.client import (
    LLMResult,
    _gemini_call,
    _resolve_provider,
    llm_call,
)
from scripts.llm.utils import LLMResponseError


class TestImports:
    def test_import_llm_call(self) -> None:
        from scripts.llm.client import llm_call  # noqa: F811

        assert callable(llm_call)

    def test_import_llm_result(self) -> None:
        from scripts.llm.client import LLMResult  # noqa: F811

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


class TestResolveProvider:
    def test_defaults_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert _resolve_provider() == "gemini"

    def test_env_var_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert _resolve_provider() == "gemini"

    def test_retired_bedrock_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # bedrock left _VALID_PROVIDERS per CD.28; unknown values fall back
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        assert _resolve_provider() == "gemini"

    def test_invalid_falls_back_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert _resolve_provider() == "gemini"


class TestLLMCall:
    """llm_call() assembly behaviour on the gemini transport."""

    @patch("scripts.llm.client._gemini_call")
    def test_context_file_path_prepended(
        self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("CONTEXT DATA", encoding="utf-8")
        mock_gemini.return_value = LLMResult(
            content="ok",
            exit_code=0,
            session_id="x",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0,
            model="gemini-auto",
        )
        llm_call("my prompt", tools=False, context_file_path=str(ctx_file))
        prompt_sent = mock_gemini.call_args[1]["prompt"]
        assert "CONTEXT DATA" in prompt_sent
        assert "my prompt" in prompt_sent

    @patch("scripts.llm.client._gemini_call")
    def test_inline_instruction_prepended_with_at_refs_stripped(
        self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        mock_gemini.return_value = LLMResult(
            content="ok",
            exit_code=0,
            session_id="x",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            model="gemini-auto",
        )
        llm_call("body", tools=False, inline_instruction="Plan against the spec @spec.txt")
        prompt_sent = mock_gemini.call_args[1]["prompt"]
        assert prompt_sent.startswith("Plan against the spec")
        assert "@spec.txt" not in prompt_sent
        assert "body" in prompt_sent


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

    @patch("scripts.llm.client._gemini_call")
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

    @patch("scripts.llm.client._gemini_call")
    def test_retired_bedrock_provider_routes_to_gemini(self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # bedrock left _VALID_PROVIDERS (CD.28): resolve_provider falls back
        # to gemini, so the call still routes to the gemini transport.
        monkeypatch.setenv("LLM_PROVIDER", "bedrock")
        mock_gemini.return_value = LLMResult(
            content="fallback response",
            exit_code=0,
            session_id="x",
            tokens_in=5,
            tokens_out=5,
            cost_usd=0.0,
            model="gemini-auto",
        )
        result = llm_call("test prompt", tools=False)
        mock_gemini.assert_called_once()
        assert result.content == "fallback response"

    @patch("scripts.llm.client._resolve_provider", return_value="litellm")
    def test_non_gemini_provider_raises_retirement_error(self, mock_provider: MagicMock) -> None:
        # Unreachable via env config (resolve_provider falls back to gemini);
        # defense-in-depth until T4.2's LiteLLM transport lands.
        with pytest.raises(LLMResponseError, match="retired per CD.28"):
            llm_call("test prompt", tools=False)

    @patch("scripts.llm.client._gemini_call")
    def test_compat_kwargs_accepted_and_ignored(self, mock_gemini: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # scripts/executor/plan.py passes excluded_tools=, run_skill.py passes
        # system_prompt= -- the signature must keep accepting both (their own
        # tests mock llm_call, so a TypeError here would be invisible there).
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        mock_gemini.return_value = LLMResult(
            content="ok",
            exit_code=0,
            session_id="x",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            model="gemini-auto",
        )
        result = llm_call(
            "test prompt",
            tools=False,
            excluded_tools=["write", "bash"],
            system_prompt="be terse",
        )
        mock_gemini.assert_called_once()
        assert result.content == "ok"

    @patch("scripts.llm.client._gemini_call")
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
