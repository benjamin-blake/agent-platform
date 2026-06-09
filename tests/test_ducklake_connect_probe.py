"""Unit tests for src/common/ducklake_connect_probe.py (T2.19 RCA).

Each phase's failure is classified to the correct failed_phase. A fully-successful mock returns
ok=True, phase_reached="attach". No phase can hang -- timeouts are passed through to the
underlying socket/psycopg2 calls.
"""

from __future__ import annotations

import concurrent.futures
import os
from unittest.mock import MagicMock, patch

import pytest

from src.common import ducklake_connect_probe as probe

pytestmark = pytest.mark.unit

_DSN = {
    "host": "ep-test-123.eu-west-2.aws.neon.tech",
    "dbname": "ducklake_ops",
    "username": "ducklake_ops",
    "password": "secret-pw",  # pragma: allowlist secret -- fake fixture value
    "sslmode": "require",
}

_PROBE_KWARGS = dict(
    data_path="s3://test-bucket/ducklake/",
    meta_schema="ducklake_ops",
    extension_directory="/opt/extensions",
    timeout_s=10,
)


# ---------------------------------------------------------------------------
# DNS failure
# ---------------------------------------------------------------------------


def test_dns_failure_classifies_to_dns():
    with patch("src.common.ducklake_connect_probe.socket.getaddrinfo", side_effect=OSError("name not found")):
        result = probe.probe_connection(_DSN, **_PROBE_KWARGS)
    assert result["failed_phase"] == "dns"
    assert result["phase_reached"] == "none"
    assert result["ok"] is False
    assert "DNS" in result["error"]
    assert result["dns_ms"] is not None
    assert result["tcp_ms"] is None
    assert result["auth_ms"] is None
    assert result["attach_ms"] is None


# ---------------------------------------------------------------------------
# TCP failure
# ---------------------------------------------------------------------------


def test_tcp_failure_classifies_to_tcp():
    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", side_effect=ConnectionRefusedError("refused")),
    ):
        result = probe.probe_connection(_DSN, **_PROBE_KWARGS)
    assert result["failed_phase"] == "tcp"
    assert result["phase_reached"] == "dns"
    assert result["ok"] is False
    assert "TCP" in result["error"]
    assert result["dns_ms"] is not None
    assert result["tcp_ms"] is not None
    assert result["auth_ms"] is None
    assert result["attach_ms"] is None


# ---------------------------------------------------------------------------
# AUTH failure
# ---------------------------------------------------------------------------


def test_auth_failure_classifies_to_auth():
    mock_sock = MagicMock()
    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", side_effect=Exception("authentication failed")),
    ):
        result = probe.probe_connection(_DSN, **_PROBE_KWARGS)
    assert result["failed_phase"] == "auth"
    assert result["phase_reached"] == "tcp"
    assert result["ok"] is False
    assert "AUTH" in result["error"]
    assert result["dns_ms"] is not None
    assert result["tcp_ms"] is not None
    assert result["auth_ms"] is not None
    assert result["attach_ms"] is None


# ---------------------------------------------------------------------------
# ATTACH failure
# ---------------------------------------------------------------------------


def test_attach_failure_classifies_to_attach():
    mock_sock = MagicMock()
    mock_pg_conn = MagicMock()
    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", return_value=mock_pg_conn),
        patch("src.common.ducklake_runtime.open_connection", side_effect=Exception("ATTACH failed: could not connect")),
    ):
        result = probe.probe_connection(_DSN, **_PROBE_KWARGS)
    assert result["failed_phase"] == "attach"
    assert result["phase_reached"] == "auth"
    assert result["ok"] is False
    assert "ATTACH" in result["error"]
    assert result["dns_ms"] is not None
    assert result["tcp_ms"] is not None
    assert result["auth_ms"] is not None
    assert result["attach_ms"] is not None


# ---------------------------------------------------------------------------
# Full success path
# ---------------------------------------------------------------------------


def test_full_success_returns_ok_attach():
    mock_sock = MagicMock()
    mock_pg_conn = MagicMock()
    mock_duck_con = MagicMock()
    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", return_value=mock_pg_conn),
        patch("src.common.ducklake_runtime.open_connection", return_value=mock_duck_con),
    ):
        result = probe.probe_connection(_DSN, **_PROBE_KWARGS)
    assert result["ok"] is True
    assert result["phase_reached"] == "attach"
    assert result["failed_phase"] is None
    assert result["error"] is None
    assert result["dns_ms"] is not None
    assert result["tcp_ms"] is not None
    assert result["auth_ms"] is not None
    assert result["attach_ms"] is not None
    mock_duck_con.execute.assert_called_once_with("SELECT 1")
    mock_duck_con.close.assert_called_once()


# ---------------------------------------------------------------------------
# Timeout is passed through to socket.create_connection
# ---------------------------------------------------------------------------


def test_timeout_passed_to_socket_create_connection():
    captured = {}

    def _fake_create_connection(address, timeout):
        captured["address"] = address
        captured["timeout"] = timeout
        raise ConnectionRefusedError("refused")

    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", side_effect=_fake_create_connection),
    ):
        probe.probe_connection(_DSN, **{**_PROBE_KWARGS, "timeout_s": 7})
    assert captured["timeout"] == 7
    assert captured["address"] == (_DSN["host"], 5432)


# ---------------------------------------------------------------------------
# Timeout is passed through to psycopg2.connect
# ---------------------------------------------------------------------------


def test_timeout_passed_to_psycopg2():
    mock_sock = MagicMock()
    captured = {}

    def _fake_psycopg2_connect(**kwargs):
        captured.update(kwargs)
        raise Exception("fail auth")

    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", side_effect=_fake_psycopg2_connect),
    ):
        probe.probe_connection(_DSN, **{**_PROBE_KWARGS, "timeout_s": 5})
    assert captured.get("connect_timeout") == 5
    assert captured.get("sslmode") == "require"


# ---------------------------------------------------------------------------
# DNS phase is bounded (H1): a blackhole resolver does NOT hang the probe
# ---------------------------------------------------------------------------


def test_dns_phase_is_bounded_on_blackhole(monkeypatch):
    """A getaddrinfo that never returns is bounded by timeout_s -> classified as dns failure.

    The bounded helper runs getaddrinfo in a worker thread with future.result(timeout=...). We
    patch the helper's underlying getaddrinfo to block; the future times out and the phase fails.
    """
    import threading

    blocking = threading.Event()

    def _never_returns(host, port):
        blocking.wait(timeout=30)  # would hang well past timeout_s if unbounded
        return []

    with patch("src.common.ducklake_connect_probe.socket.getaddrinfo", side_effect=_never_returns):
        result = probe.probe_connection(_DSN, **{**_PROBE_KWARGS, "timeout_s": 1})
    blocking.set()
    assert result["failed_phase"] == "dns"
    assert result["ok"] is False
    assert "DNS" in result["error"]


def test_bounded_getaddrinfo_raises_timeout_on_block(monkeypatch):
    """_bounded_getaddrinfo raises concurrent.futures.TimeoutError when the call exceeds timeout_s."""
    import threading

    blocking = threading.Event()

    def _never_returns(host, port):
        blocking.wait(timeout=30)
        return []

    with patch("src.common.ducklake_connect_probe.socket.getaddrinfo", side_effect=_never_returns):
        with pytest.raises(concurrent.futures.TimeoutError):
            probe._bounded_getaddrinfo("h", 5432, 1)
    blocking.set()


# ---------------------------------------------------------------------------
# ATTACH phase forwards timeout_s via DUCKLAKE_CONNECT_TIMEOUT_S (H2 / M3)
# ---------------------------------------------------------------------------


def test_attach_forwards_timeout_s_and_restores_env(monkeypatch):
    """The ATTACH phase sets DUCKLAKE_CONNECT_TIMEOUT_S=timeout_s for open_connection, then restores it."""
    monkeypatch.setenv("DUCKLAKE_CONNECT_TIMEOUT_S", "99")
    captured = {}
    mock_sock = MagicMock()
    mock_pg_conn = MagicMock()
    mock_duck_con = MagicMock()

    def _capture_open(**kwargs):
        captured["env_at_call"] = os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S")
        return mock_duck_con

    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", return_value=mock_pg_conn),
        patch("src.common.ducklake_runtime.open_connection", side_effect=_capture_open),
    ):
        result = probe.probe_connection(_DSN, **{**_PROBE_KWARGS, "timeout_s": 4})
    assert result["ok"] is True
    assert captured["env_at_call"] == "4", "ATTACH must forward timeout_s via the env var"
    assert os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S") == "99", "prior env value must be restored"


def test_attach_restores_absent_env(monkeypatch):
    """When DUCKLAKE_CONNECT_TIMEOUT_S was unset, the ATTACH phase removes it again after the call."""
    monkeypatch.delenv("DUCKLAKE_CONNECT_TIMEOUT_S", raising=False)
    mock_sock = MagicMock()
    mock_pg_conn = MagicMock()
    mock_duck_con = MagicMock()
    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", return_value=mock_pg_conn),
        patch("src.common.ducklake_runtime.open_connection", return_value=mock_duck_con),
    ):
        probe.probe_connection(_DSN, **{**_PROBE_KWARGS, "timeout_s": 4})
    assert "DUCKLAKE_CONNECT_TIMEOUT_S" not in os.environ


# ---------------------------------------------------------------------------
# DSN sslmode default
# ---------------------------------------------------------------------------


def test_sslmode_defaults_to_require():
    mock_sock = MagicMock()
    captured = {}
    dsn_no_ssl = {k: v for k, v in _DSN.items() if k != "sslmode"}

    def _fake_psycopg2_connect(**kwargs):
        captured.update(kwargs)
        raise Exception("fail auth")

    with (
        patch("src.common.ducklake_connect_probe.socket.getaddrinfo", return_value=[("AF_INET", None, None, None, None)]),
        patch("src.common.ducklake_connect_probe.socket.create_connection", return_value=mock_sock),
        patch("psycopg2.connect", side_effect=_fake_psycopg2_connect),
    ):
        probe.probe_connection(dsn_no_ssl, **_PROBE_KWARGS)
    assert captured.get("sslmode") == "require"
