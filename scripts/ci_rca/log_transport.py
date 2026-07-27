"""Authenticated, redirect-safe streaming access to one GitHub Actions job log."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPException
from typing import BinaryIO, ContextManager, Protocol, cast
from urllib.parse import urlsplit


class LogTransportError(OSError):
    """A redacted transport failure safe to classify and present."""


class StreamOpener(Protocol):
    def __call__(self, repo: str, job_id: int) -> ContextManager[BinaryIO]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _SafeResponse:
    def __init__(self, response: BinaryIO) -> None:
        self._response = response

    def read(self, size: int = -1) -> bytes:
        return self._call(self._response.read, size)

    def readline(self, size: int = -1) -> bytes:
        return self._call(self._response.readline, size)

    def _call(self, method: Callable[[int], bytes], size: int) -> bytes:
        try:
            return cast(bytes, method(size))
        except (OSError, HTTPException):
            raise LogTransportError("CI_RCA_LOG_STREAM_INTERRUPTED") from None

    def close(self) -> None:
        self._response.close()

    def __enter__(self) -> _SafeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _allowed_redirect(location: str) -> bool:
    if any(ord(character) < 32 or ord(character) == 127 for character in location):
        return False
    try:
        parsed = urlsplit(location)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and port in {None, 443}
        and host.endswith((".actions.githubusercontent.com", ".blob.core.windows.net"))
    )


def open_job_log(repo: str, job_id: int, *, token: str) -> ContextManager[BinaryIO]:
    """Open one job log without forwarding authentication to its signed redirect."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        unexpected = opener.open(request, timeout=20)
    except urllib.error.HTTPError as exc:
        try:
            if exc.code not in {302, 307}:
                raise LogTransportError(f"CI_RCA_LOG_HTTP_{exc.code}") from None
            location = exc.headers.get("Location", "")
        finally:
            exc.close()
    except urllib.error.URLError:
        raise LogTransportError("CI_RCA_LOG_API_UNAVAILABLE") from None
    else:
        unexpected.close()
        raise LogTransportError("CI_RCA_LOG_REDIRECT_MISSING")
    if not _allowed_redirect(location):
        raise LogTransportError("CI_RCA_LOG_REDIRECT_REJECTED")
    try:
        signed_request = urllib.request.Request(location)
        response = opener.open(signed_request, timeout=20)
    except ValueError:
        raise LogTransportError("CI_RCA_LOG_REDIRECT_REJECTED") from None
    except urllib.error.HTTPError as exc:
        exc.close()
        raise LogTransportError("CI_RCA_LOG_STREAM_UNAVAILABLE") from None
    except (OSError, urllib.error.URLError, HTTPException):
        raise LogTransportError("CI_RCA_LOG_STREAM_UNAVAILABLE") from None
    return cast(ContextManager[BinaryIO], _SafeResponse(cast(BinaryIO, response)))
