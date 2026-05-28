"""DEPRECATED: This module is superseded by scripts/llm_client.py (Bedrock).

GitHub Copilot SDK inference client for Lambda-executed agents.
Retained for rollback only. Will be removed once Bedrock migration is
confirmed stable. New code should import from scripts.llm_client instead.

SDK reference: https://github.com/github/copilot-sdk
Decision 49 (docs/DECISIONS.md): Copilot SDK replaces Bedrock as Lambda
inference provider.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def copilot_sdk_inference(
    prompt: str,
    model: str,
    github_token: str,
    max_tokens: int = 4096,  # noqa: ARG001 -- reserved for future SDK support
    timeout: float = 300.0,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the GitHub Copilot SDK and return a flat response dict.

    Args:
        prompt: The user message to send.
        model: Copilot SDK model identifier, e.g. ``"claude-haiku-4.5"``.
        github_token: GitHub PAT with Copilot scope.
        max_tokens: Maximum tokens in the model response (reserved; SDK does
            not currently expose this parameter).
        timeout: Seconds to wait for the model response before raising
            ``TimeoutError``.
        provider_config: Optional BYOK provider dict forwarded to
            ``create_session(provider=...)``.  When set, inference is routed
            through the specified backend (e.g. Gemini via the
            OpenAI-compatible endpoint) instead of GitHub Copilot.
            Expected keys: ``type`` (``"openai"``), ``base_url``, ``api_key``.

    Returns:
        Dict with keys:
          content: str   -- model response text
          error: bool    -- True if the call failed
          message: str   -- error description if error is True
    """
    try:
        from copilot import CopilotClient, SubprocessConfig
        from copilot.session import PermissionHandler
    except ImportError as exc:
        return {
            "content": "",
            "error": True,
            "message": f"github-copilot-sdk not installed: {exc}",
        }

    import os

    # Lambda provides no home directory for the sandbox user.  The bundled
    # Copilot CLI binary uses $HOME to write extraction artifacts.  Override to
    # /tmp so the binary can write without ENOENT on /home/sbx_user*.
    cli_env = dict(os.environ)
    cli_env["HOME"] = "/tmp"

    client: Any = None
    session: Any = None
    try:
        config = SubprocessConfig(github_token=github_token, env=cli_env)
        client = CopilotClient(config)
        await client.start()

        create_kwargs: dict[str, Any] = {
            "model": model,
            "tools": [],  # Disable agent tool use -- Lambda cannot execute tool calls
            "on_permission_request": PermissionHandler.approve_all,
        }
        if provider_config is not None:
            create_kwargs["provider"] = provider_config
        session = await client.create_session(**create_kwargs)

        response = await session.send_and_wait(prompt, timeout=timeout)
        content: str = response.data.content
        return {"content": content, "error": False, "message": ""}

    except Exception as exc:  # noqa: BLE001
        logger.error("Copilot SDK inference failed: %s", exc)
        return {"content": "", "error": True, "message": str(exc)}

    finally:
        if session is not None:
            try:
                await session.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            try:
                await client.stop()
            except Exception:  # noqa: BLE001
                pass


def copilot_sdk_inference_sync(
    prompt: str,
    model: str,
    github_token: str,
    max_tokens: int = 4096,
    timeout: float = 300.0,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synchronous entry point for Lambda handler (which is not async).

    Wraps :func:`copilot_sdk_inference` in ``asyncio.run()``.

    Args:
        prompt: The user message to send.
        model: Copilot SDK model identifier, e.g. ``"claude-haiku-4.5"``.
        github_token: GitHub PAT with Copilot scope.
        max_tokens: Maximum tokens (reserved for future SDK support).
        timeout: Seconds to wait for the response.
        provider_config: Optional BYOK provider dict; passed through to
            :func:`copilot_sdk_inference`.

    Returns:
        Dict with keys ``content``, ``error``, ``message``.
    """
    return asyncio.run(
        copilot_sdk_inference(
            prompt=prompt,
            model=model,
            github_token=github_token,
            max_tokens=max_tokens,
            timeout=timeout,
            provider_config=provider_config,
        )
    )
