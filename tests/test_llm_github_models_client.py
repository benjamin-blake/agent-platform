"""Unit tests for scripts/llm/github_models_client.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import scripts.llm.github_models_client as client_mod
from scripts.llm.github_models_client import chat_completion


class TestChatCompletionSuccess:
    """Tests for successful API calls."""

    def test_returns_parsed_json_on_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.json.return_value = {"choices": [{"message": {"content": "Hello"}}]}

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.return_value = mock_response
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            result = chat_completion("test prompt", "gpt-4.1-mini", "ghp_test")

        assert result == {"choices": [{"message": {"content": "Hello"}}]}
        call_kwargs = mock_requests.post.call_args
        assert call_kwargs[0][0] == "https://models.github.ai/inference/chat/completions"

    def test_sends_correct_headers_and_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.json.return_value = {"choices": []}

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.return_value = mock_response
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            chat_completion("my prompt", "gemini-3.0-flash", "token123")

        _, kwargs = mock_requests.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer token123"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"]["model"] == "gemini-3.0-flash"
        assert kwargs["json"]["messages"] == [{"role": "user", "content": "my prompt"}]


class TestChatCompletionRateLimit:
    """Tests for 429 rate limit retry logic."""

    def test_retries_on_429_then_succeeds(self) -> None:
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.ok = False
        rate_limit_response.headers = {}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.ok = True
        success_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.side_effect = [rate_limit_response, success_response]
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            with patch("scripts.llm.github_models_client.time") as mock_time:
                result = chat_completion("prompt", "gpt-4.1-mini", "key", max_retries=2, initial_backoff=0.01)

        assert result == {"choices": [{"message": {"content": "ok"}}]}
        assert mock_requests.post.call_count == 2
        mock_time.sleep.assert_called_once()

    def test_returns_error_after_max_retries_exceeded(self) -> None:
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.ok = False
        rate_limit_response.headers = {}

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.return_value = rate_limit_response
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            with patch("scripts.llm.github_models_client.time") as mock_time:
                mock_time.sleep = MagicMock()
                result = chat_completion("prompt", "gpt-4.1-mini", "key", max_retries=2, initial_backoff=0.01)

        assert result["error"] is True
        assert "Rate limit" in result["message"]

    def test_respects_retry_after_header(self) -> None:
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.ok = False
        rate_limit_response.headers = {"Retry-After": "5"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.ok = True
        success_response.json.return_value = {"choices": []}

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.side_effect = [rate_limit_response, success_response]
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            with patch("scripts.llm.github_models_client.time") as mock_time:
                chat_completion("p", "m", "k", max_retries=2, initial_backoff=0.01)

        # Should wait at least 5 seconds (from Retry-After header)
        mock_time.sleep.assert_called_once_with(5.0)


class TestChatCompletionErrors:
    """Tests for error handling."""

    def test_returns_error_on_500(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.ok = False
        mock_response.text = "Internal Server Error"

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.return_value = mock_response
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            result = chat_completion("prompt", "gpt-4.1-mini", "key")

        assert result["error"] is True
        assert "500" in result["message"]

    def test_returns_error_on_timeout(self) -> None:
        class FakeTimeout(Exception):
            pass

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.exceptions.Timeout = FakeTimeout
            mock_requests.exceptions.RequestException = Exception
            mock_requests.post.side_effect = FakeTimeout("timed out")
            result = chat_completion("prompt", "gpt-4.1-mini", "key")

        assert result["error"] is True
        assert "timed out" in result["message"].lower()

    def test_returns_error_on_request_exception(self) -> None:
        class FakeRequestException(Exception):
            pass

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = FakeRequestException
            mock_requests.post.side_effect = FakeRequestException("connection refused")
            result = chat_completion("prompt", "gpt-4.1-mini", "key")

        assert result["error"] is True

    def test_returns_error_on_malformed_json(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.json.side_effect = ValueError("No JSON object")

        with patch.object(client_mod, "_requests_lib") as mock_requests:
            mock_requests.post.return_value = mock_response
            mock_requests.exceptions.Timeout = Exception
            mock_requests.exceptions.RequestException = Exception
            result = chat_completion("prompt", "gpt-4.1-mini", "key")

        assert result["error"] is True
        assert "JSON" in result["message"]

    def test_returns_error_when_requests_unavailable(self) -> None:
        with patch.object(client_mod, "_REQUESTS_AVAILABLE", False):
            result = chat_completion("prompt", "gpt-4.1-mini", "key")

        assert result["error"] is True
        assert "not available" in result["message"]
