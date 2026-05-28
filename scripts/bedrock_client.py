"""AWS Bedrock Converse API client.

Provides ``converse()`` for single-turn inference and ``converse_with_tools()``
for agentic multi-turn tool loops.  Both use the Bedrock Converse API and
implement the flat response shape defined in docs/contracts/inference-provider.md.

Bedrock is the correct delivery mechanism for Lambda agents because it uses
IAM-native auth (no API keys or Secrets Manager secrets for inference) and
is available in eu-west-2. If the Converse request/response semantics are
mapped incorrectly, downstream handlers will receive missing content or
token metadata.

Usage
-----
from scripts.bedrock_client import converse, converse_with_tools

response = converse(
    prompt="Analyse this code for smells.",
    model_id="anthropic.claude-3-5-haiku-20241022-v1:0",
)
content = response["content"]
"""

from __future__ import annotations

import logging
import re
from typing import Any

try:
    import boto3
    from botocore.config import Config as _BotocoreConfig

    _BOTO3_AVAILABLE = True
except ImportError:

    class _Boto3Sentinel:
        """Sentinel so missing boto3 never raises during import."""

        def client(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
            raise RuntimeError("boto3 is not installed")

    boto3 = _Boto3Sentinel()  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False

    class _BotocoreConfig:  # type: ignore[no-redef]
        """Sentinel so missing botocore never raises during import."""

        def __init__(self, **kwargs: Any) -> None:
            pass


logger = logging.getLogger(__name__)

# Regex to strip DeepSeek chain-of-thought <think>...</think> blocks.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_blocks(text: str) -> str:
    """Remove DeepSeek chain-of-thought blocks and non-ASCII artifacts.

    DeepSeek R1/V3 models emit ``<think>...</think>`` reasoning traces that
    include Chinese characters and internal reasoning.  These are stripped
    because (a) downstream parsers expect clean English output, and
    (b) Chinese characters cause encoding errors on Windows terminals.
    """
    cleaned = _THINK_RE.sub("", text)
    # Remove stray Chinese/CJK characters that sometimes leak outside think blocks
    cleaned = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", cleaned)
    return cleaned.strip()


def _create_client(
    region: str = "eu-west-2",
    profile_name: str | None = None,
    credentials: dict[str, str] | None = None,
    read_timeout: int = 300,
) -> Any:
    """Construct a bedrock-runtime boto3 client.

    Args:
        region: AWS region.
        profile_name: Named AWS profile (for local CLI use).
        credentials: Explicit credentials dict with ``aws_access_key_id``
            and ``aws_secret_access_key`` (for Lambda cross-account auth).
        read_timeout: Socket read timeout in seconds.
    """
    config = _BotocoreConfig(read_timeout=read_timeout, connect_timeout=10)
    kwargs: dict[str, Any] = {
        "service_name": "bedrock-runtime",
        "region_name": region,
        "config": config,
    }
    if credentials:
        kwargs["aws_access_key_id"] = credentials["aws_access_key_id"]
        kwargs["aws_secret_access_key"] = credentials["aws_secret_access_key"]
    if profile_name and not credentials:
        session = boto3.Session(profile_name=profile_name)
        return session.client(**kwargs)
    return boto3.client(**kwargs)


def converse(
    prompt: str,
    model_id: str,
    region: str = "eu-west-2",
    max_tokens: int = 4096,
    read_timeout: int = 840,
    system_prompt: str | None = None,
    profile_name: str | None = None,
    credentials: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call the Bedrock Converse API and return a flat response dict.

    Args:
        prompt: The user message content.
        model_id: Bedrock model identifier.
        region: AWS region for the bedrock-runtime client.
        max_tokens: Maximum tokens in the model response.
        read_timeout: Socket read timeout in seconds.
        system_prompt: Optional system prompt text.
        profile_name: Named AWS profile.
        credentials: Explicit credentials dict for cross-account auth.

    Returns:
        Dict with keys: content, stop_reason, input_tokens, output_tokens,
        error, message.
    """
    if not _BOTO3_AVAILABLE:
        return {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": "boto3 library not available",
        }

    try:
        client = _create_client(region, profile_name, credentials, read_timeout)

        api_kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                },
            ],
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system_prompt:
            api_kwargs["system"] = [{"text": system_prompt}]

        response = client.converse(**api_kwargs)

        # Extract text from the Converse response output structure.
        # Response shape: {"output": {"message": {"content": [{"text": "..."}]}}}
        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])
        text_parts = [block["text"] for block in content_blocks if "text" in block]
        content = _strip_think_blocks("\n".join(text_parts))

        stop_reason = response.get("stopReason", "")
        usage = response.get("usage", {})

        return {
            "content": content,
            "stop_reason": stop_reason,
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "error": False,
            "message": "",
        }

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Bedrock converse failed for model %s: %s",
            model_id,
            exc,
        )
        return {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": str(exc),
        }


def converse_with_tools(
    prompt: str,
    model_id: str,
    tools: list[dict[str, Any]],
    tool_runtime: Any,
    system_prompt: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    region: str = "eu-west-2",
    max_tokens: int = 4096,
    max_turns: int = 50,
    profile_name: str | None = None,
    credentials: dict[str, str] | None = None,
    read_timeout: int = 840,
) -> dict[str, Any]:
    """Agentic tool loop using Bedrock Converse API with ``toolConfig``.

    Sends the conversation, executes tool calls via *tool_runtime*, appends
    ``toolResult`` messages, and loops until ``end_turn`` or *max_turns*.

    Args:
        prompt: Initial user message.
        model_id: Bedrock model identifier.
        tools: List of Bedrock ``toolSpec`` dicts.
        tool_runtime: Object with ``execute(tool_name, tool_input) -> str``.
        system_prompt: Optional system prompt.
        messages: Optional pre-existing message history.
        region: AWS region.
        max_tokens: Max tokens per turn.
        max_turns: Safety limit on tool loop iterations.
        profile_name: Named AWS profile.
        credentials: Explicit credentials dict.
        read_timeout: Socket read timeout.

    Returns:
        Dict with keys: content, stop_reason, input_tokens, output_tokens,
        error, message, turn_count.
    """
    if not _BOTO3_AVAILABLE:
        return {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": "boto3 library not available",
            "turn_count": 0,
        }

    try:
        client = _create_client(region, profile_name, credentials, read_timeout)
    except Exception as exc:  # noqa: BLE001
        return {
            "content": "",
            "stop_reason": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": True,
            "message": f"Client creation failed: {exc}",
            "turn_count": 0,
        }

    if messages is None:
        messages = [{"role": "user", "content": [{"text": prompt}]}]

    api_kwargs: dict[str, Any] = {
        "modelId": model_id,
        "inferenceConfig": {"maxTokens": max_tokens},
        "toolConfig": {"tools": tools},
    }
    if system_prompt:
        api_kwargs["system"] = [{"text": system_prompt}]

    total_input_tokens = 0
    total_output_tokens = 0
    final_content = ""
    stop_reason = ""
    turn = 0

    try:
        while turn < max_turns:
            turn += 1
            api_kwargs["messages"] = messages

            response = client.converse(**api_kwargs)

            usage = response.get("usage", {})
            total_input_tokens += usage.get("inputTokens", 0)
            total_output_tokens += usage.get("outputTokens", 0)

            stop_reason = response.get("stopReason", "")
            output_msg = response.get("output", {}).get("message", {})
            content_blocks = output_msg.get("content", [])

            # Append assistant message to history
            messages.append({"role": "assistant", "content": content_blocks})

            if stop_reason == "end_turn" or stop_reason == "max_tokens":
                text_parts = [b["text"] for b in content_blocks if "text" in b]
                final_content = _strip_think_blocks("\n".join(text_parts))
                break

            if stop_reason == "tool_use":
                tool_results: list[dict[str, Any]] = []
                for block in content_blocks:
                    if "toolUse" in block:
                        tool_use = block["toolUse"]
                        tool_name = tool_use["name"]
                        tool_input = tool_use.get("input", {})
                        tool_use_id = tool_use["toolUseId"]

                        logger.info("Tool call: %s(%s)", tool_name, list(tool_input.keys()))
                        result_text = tool_runtime.execute(tool_name, tool_input)

                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [{"text": result_text}],
                                }
                            }
                        )

                messages.append({"role": "user", "content": tool_results})
            else:
                # Unknown stop reason -- extract text and stop
                text_parts = [b["text"] for b in content_blocks if "text" in b]
                final_content = _strip_think_blocks("\n".join(text_parts))
                break

        if turn >= max_turns and stop_reason not in ("end_turn", "max_tokens"):
            logger.warning(
                "converse_with_tools exhausted max_turns=%d without end_turn",
                max_turns,
            )

        return {
            "content": final_content,
            "stop_reason": stop_reason,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "error": False,
            "message": "",
            "turn_count": turn,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("Bedrock converse_with_tools failed for model %s: %s", model_id, exc)
        return {
            "content": final_content,
            "stop_reason": "",
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "error": True,
            "message": str(exc),
            "turn_count": turn,
        }
