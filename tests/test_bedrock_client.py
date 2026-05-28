"""Unit tests for scripts/bedrock_client.py."""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

from scripts.bedrock_client import _strip_think_blocks, converse

# Contract-defined response keys (docs/contracts/inference-provider.md)
_CONTRACT_KEYS = {
    "content",
    "stop_reason",
    "input_tokens",
    "output_tokens",
    "error",
    "message",
}


def _mock_converse_response(
    text: str = "Hello",
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> dict:
    """Build a Bedrock Converse API response dict."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            },
        },
        "stopReason": stop_reason,
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
        },
    }


class TestConverseSuccess:
    """Tests for successful Bedrock Converse calls."""

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_returns_content_from_converse(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response(text="Test response")
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["content"] == "Test response"
        assert result["error"] is False
        assert result["message"] == ""

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_passes_correct_params_to_client(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response()
        mock_boto3.client.return_value = mock_client

        converse(
            prompt="Test prompt",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
            region="us-east-1",
            max_tokens=2048,
        )

        mock_boto3.client.assert_called_once_with(service_name="bedrock-runtime", region_name="us-east-1", config=ANY)
        mock_client.converse.assert_called_once_with(
            modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
            messages=[
                {
                    "role": "user",
                    "content": [{"text": "Test prompt"}],
                },
            ],
            inferenceConfig={"maxTokens": 2048},
        )

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_extracts_usage_metadata(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response(input_tokens=42, output_tokens=17)
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["input_tokens"] == 42
        assert result["output_tokens"] == 17

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_extracts_stop_reason(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response(stop_reason="max_tokens")
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["stop_reason"] == "max_tokens"

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_joins_multiple_content_blocks(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Part one"},
                        {"text": "Part two"},
                    ],
                },
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 8},
        }
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["content"] == "Part one\nPart two"

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_strips_think_blocks_from_response(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response(text="<think>internal reasoning</think>The answer is 42.")
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="deepseek.v3.2",
        )

        assert result["content"] == "The answer is 42."
        assert "<think>" not in result["content"]


class TestStripThinkBlocks:
    """Tests for _strip_think_blocks() utility."""

    def test_removes_single_think_block(self) -> None:
        assert _strip_think_blocks("<think>reasoning</think>answer") == "answer"

    def test_removes_multiline_think_block(self) -> None:
        text = "<think>\nline1\nline2\n</think>\nThe result."
        assert _strip_think_blocks(text) == "The result."

    def test_removes_multiple_think_blocks(self) -> None:
        text = "<think>first</think>A<think>second</think>B"
        assert _strip_think_blocks(text) == "AB"

    def test_removes_chinese_characters(self) -> None:
        assert _strip_think_blocks("Hello \u4f60\u597d World") == "Hello  World"

    def test_passthrough_clean_text(self) -> None:
        assert _strip_think_blocks("No think blocks here") == "No think blocks here"

    def test_empty_string(self) -> None:
        assert _strip_think_blocks("") == ""


class TestConverseFailure:
    """Tests for Bedrock client failure handling."""

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_handles_client_exception(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("ResourceNotFoundException")
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="bad.model.id",
        )

        assert result["error"] is True
        assert "ResourceNotFoundException" in result["message"]
        assert result["content"] == ""
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", False)
    def test_returns_error_when_boto3_missing(self) -> None:
        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["error"] is True
        assert "boto3" in result["message"].lower()
        assert result["content"] == ""

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_handles_empty_response_gracefully(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = {}
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert result["error"] is False
        assert result["content"] == ""
        assert result["stop_reason"] == ""
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0


class TestContractSchema:
    """Validate the flat response shape from the contract."""

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_success_response_has_contract_keys(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response()
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert set(result.keys()) == _CONTRACT_KEYS

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_error_response_has_contract_keys(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.side_effect = RuntimeError("boom")
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert set(result.keys()) == _CONTRACT_KEYS

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", False)
    def test_boto3_missing_response_has_contract_keys(self) -> None:
        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert set(result.keys()) == _CONTRACT_KEYS

    @patch("scripts.bedrock_client._BOTO3_AVAILABLE", True)
    @patch("scripts.bedrock_client.boto3")
    def test_success_response_types_match_contract(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.converse.return_value = _mock_converse_response()
        mock_boto3.client.return_value = mock_client

        result = converse(
            prompt="Hello",
            model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        assert isinstance(result["content"], str)
        assert isinstance(result["stop_reason"], str)
        assert isinstance(result["input_tokens"], int)
        assert isinstance(result["output_tokens"], int)
        assert isinstance(result["error"], bool)
        assert isinstance(result["message"], str)
