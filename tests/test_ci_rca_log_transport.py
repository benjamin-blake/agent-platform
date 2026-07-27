from __future__ import annotations

import io
import urllib.error
import urllib.request
from email.message import Message

import pytest

import scripts.ci_rca.log_transport as transport


class _Response(io.BytesIO):
    pass


class _Opener:
    def __init__(self, location: str, body: bytes = b"safe\n", *, code: int = 302) -> None:
        self.location = location
        self.body = body
        self.code = code
        self.requests: list[urllib.request.Request] = []
        self.redirect_body = _Response()
        self.stream: _Response | None = None

    def open(self, request: urllib.request.Request, timeout: int) -> _Response:
        self.requests.append(request)
        if len(self.requests) == 1:
            headers = Message()
            headers["Location"] = self.location
            raise urllib.error.HTTPError(request.full_url, self.code, "redirect", headers, self.redirect_body)
        self.stream = _Response(self.body)
        return self.stream


@pytest.mark.parametrize("code", [302, 307])
def test_job_log_redirect_does_not_forward_authentication(code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _Opener("https://results-receiver.actions.githubusercontent.com/signed?token=secret", code=code)
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)

    with transport.open_job_log("owner/repo", 7, token="github-secret") as stream:
        assert stream.read(4) == b"safe"

    assert opener.redirect_body.closed
    assert opener.stream is not None and opener.stream.closed
    assert opener.requests[0].get_header("Authorization") == "Bearer github-secret"
    assert opener.requests[1].get_header("Authorization") is None
    assert opener.requests[1].get_header("Range") is None
    assert opener.requests[1].full_url.endswith("?token=secret")


@pytest.mark.parametrize(
    "location",
    [
        "http://results-receiver.actions.githubusercontent.com/signed",
        "https://actions.githubusercontent.com.evil.test/signed",
        "https://example.com/signed",
        "https://actions.githubusercontent.com/signed",
        "https://user:password@results-receiver.actions.githubusercontent.com/signed",
        "https://results-receiver.actions.githubusercontent.com:444/signed",
        "https://results-receiver.actions.githubusercontent.com/signed#fragment",
        "https://results-receiver.actions.githubusercontent.com/signed?secret=query\nInjected: yes",
        "https://[malformed/signed?secret=query",
    ],
)
def test_untrusted_redirect_is_rejected_without_rendering_url(location: str, monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _Opener(location)
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)

    with pytest.raises(transport.LogTransportError, match="^CI_RCA_LOG_REDIRECT_REJECTED$"):
        transport.open_job_log("owner/repo", 7, token="github-secret")

    assert opener.redirect_body.closed
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "location",
    [
        "https://results-receiver.actions.githubusercontent.com/signed?secret=query\rInjected: yes",
        "https://[broken-ipv6/signed?secret=query",
    ],
)
def test_malformed_redirect_never_leaks_secret_or_builds_second_request(
    location: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _Opener(location)
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)
    with pytest.raises(transport.LogTransportError) as raised:
        transport.open_job_log("owner/repo", 7, token="github-secret")
    assert str(raised.value) == "CI_RCA_LOG_REDIRECT_REJECTED"
    assert "secret" not in str(raised.value)
    assert len(opener.requests) == 1


def test_blob_storage_redirect_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _Opener("https://productionresults.blob.core.windows.net/signed")
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)
    with transport.open_job_log("owner/repo", 7, token="secret") as stream:
        assert stream.readline() == b"safe\n"


class _UnexpectedOpener:
    def __init__(self) -> None:
        self.response = _Response(b"unexpected")

    def open(self, request: urllib.request.Request, timeout: int) -> _Response:
        return self.response


def test_unexpected_initial_success_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _UnexpectedOpener()
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)
    with pytest.raises(transport.LogTransportError, match="^CI_RCA_LOG_REDIRECT_MISSING$"):
        transport.open_job_log("owner/repo", 7, token="secret")
    assert opener.response.closed


class _SecondHopFailure(_Opener):
    def open(self, request: urllib.request.Request, timeout: int) -> _Response:
        if self.requests:
            headers = Message()
            body = _Response(b"signed URL details")
            error = urllib.error.HTTPError(request.full_url, 403, "secret detail", headers, body)
            self.stream = body
            raise error
        return super().open(request, timeout)


def test_second_hop_failure_is_closed_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = _SecondHopFailure("https://results-receiver.actions.githubusercontent.com/signed?secret=query")
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *handlers: opener)
    with pytest.raises(transport.LogTransportError, match="^CI_RCA_LOG_STREAM_UNAVAILABLE$") as raised:
        transport.open_job_log("owner/repo", 7, token="secret")
    assert "query" not in str(raised.value)
    assert opener.stream is not None and opener.stream.closed
