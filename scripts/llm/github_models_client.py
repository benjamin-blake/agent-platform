"""HTTP client for the GitHub Models Inference API.

Provides a minimal chat_completion() function compatible with the
OpenAI-format endpoint at https://models.github.ai/inference/chat/completions.

Usage
-----
from scripts.llm.github_models_client import chat_completion

response = chat_completion(
    prompt="Analyse this code for smells.",
    model="gpt-5-mini",
    api_key="ghp_...",  # pragma: allowlist secret
)
content = response["choices"][0]["message"]["content"]
"""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    import requests as _requests_lib

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

_API_URL = "https://models.github.ai/inference/chat/completions"
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 10.0


def chat_completion(
    prompt: str,
    model: str,
    api_key: str,
    *,
    max_retries: int = _MAX_RETRIES,
    initial_backoff: float = _INITIAL_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Call the GitHub Models API and return the parsed JSON response.

    Args:
        prompt: The user message content.
        model: Model identifier, e.g. ``"gpt-5-mini"`` or ``"gpt-5.4"``.
        api_key: GitHub PAT with Models API access.
        max_retries: Maximum number of retries on rate-limit (429) responses.
        initial_backoff: Initial backoff in seconds (doubles each retry).

    Returns:
        Parsed JSON response dict on success.
        On error returns a dict with ``{"error": True, "message": "..."}``.
    """
    if not _REQUESTS_AVAILABLE:
        return {"error": True, "message": "requests library not available"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    backoff = initial_backoff
    for attempt in range(1, max_retries + 2):  # + 1 for the first attempt
        try:
            response = _requests_lib.post(
                _API_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )
        except _requests_lib.exceptions.Timeout:
            logger.warning("GitHub Models API request timed out (attempt %d)", attempt)
            return {"error": True, "message": "Request timed out"}
        except _requests_lib.exceptions.RequestException as exc:
            logger.warning("GitHub Models API request failed (attempt %d): %s", attempt, exc)
            return {"error": True, "message": str(exc)}

        if response.status_code == 429:
            if attempt > max_retries:
                logger.error("GitHub Models API rate limit exceeded after %d retries", max_retries)
                return {"error": True, "message": "Rate limit exceeded after retries"}
            retry_after = float(response.headers.get("Retry-After", backoff))
            wait = max(retry_after, backoff)
            logger.warning("Rate limited (429); retrying in %.1f seconds (attempt %d/%d)", wait, attempt, max_retries)
            time.sleep(wait)
            backoff *= 2
            continue

        if not response.ok:
            logger.error(
                "GitHub Models API returned HTTP %d: %s",
                response.status_code,
                response.text[:200],
            )
            return {
                "error": True,
                "message": f"HTTP {response.status_code}",
                "status_code": response.status_code,
            }

        try:
            return response.json()
        except ValueError as exc:
            logger.error("GitHub Models API returned non-JSON response: %s", exc)
            return {"error": True, "message": f"Malformed JSON response: {exc}"}

    # Should not be reached, but satisfies type checker
    return {"error": True, "message": "Unexpected: exhausted retry loop"}
