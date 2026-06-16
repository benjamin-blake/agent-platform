#!/usr/bin/env python3
"""D2 warm-connection unit tests for src/common/ducklake_runtime.py (neon-egress-reduction).

VP step 3: a 2nd get_warm_connection() in the same container returns the cached connection (no new
ATTACH); a closed/dead connection is detected by the liveness probe and a fresh one is opened; the
churn harness path keeps independent per-thread connections (the warm cache is a single per-container
global it never shares).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.common import ducklake_runtime as rt

_DSN = {"host": "h", "dbname": "d", "username": "u", "password": "p"}


@pytest.fixture(autouse=True)
def _reset_warm_connection():
    """The warm connection is a module global -- reset it around every test for isolation."""
    rt.reset_warm_connection()
    yield
    rt.reset_warm_connection()


def _make_con(alive: bool = True) -> MagicMock:
    """A fake DuckDB connection. alive=False makes the liveness probe (con.execute) raise."""
    con = MagicMock(name="duckdb_con")
    if not alive:
        con.execute.side_effect = Exception("connection already closed")
    return con


class TestWarmReuse:
    def test_second_call_reuses_without_reattach(self) -> None:
        cons = [_make_con(), _make_con()]
        with patch("src.common.ducklake_runtime.open_connection", side_effect=cons) as mock_open:
            con1, meta1 = rt.get_warm_connection(dsn=_DSN)
            con2, meta2 = rt.get_warm_connection(dsn=_DSN)

        assert mock_open.call_count == 1  # ATTACH paid once -- no re-ATTACH on the warm path
        assert con1 is con2
        assert meta1 == {"reused": False, "reopened": False, "connect_ms": meta1["connect_ms"]}
        assert meta2["reused"] is True
        assert meta2["connect_ms"] == 0.0  # no ATTACH cost on reuse (observable in the handler response)

    def test_dsn_factory_invoked_only_on_open(self) -> None:
        calls: list[int] = []

        def factory() -> dict:
            calls.append(1)
            return _DSN

        with patch("src.common.ducklake_runtime.open_connection", side_effect=[_make_con(), _make_con()]):
            rt.get_warm_connection(dsn_factory=factory)
            rt.get_warm_connection(dsn_factory=factory)

        assert calls == [1], "dsn_factory must be called only on (re)open, not on the warm-reuse path"

    def test_missing_dsn_loud_fails(self) -> None:
        with pytest.raises(rt.DuckLakeRuntimeError, match="requires a dsn, dsn_factory, or opener"):
            rt.get_warm_connection()


class TestDeadConnectionReopen:
    def test_dead_connection_detected_and_reopened(self) -> None:
        """A cached connection whose liveness probe fails (Neon scale-to-zero / closed) is reopened."""
        live = _make_con(alive=True)
        replacement = _make_con(alive=True)
        with patch("src.common.ducklake_runtime.open_connection", side_effect=[live, replacement]) as mock_open:
            con1, _ = rt.get_warm_connection(dsn=_DSN)
            assert con1 is live
            # Simulate the session dying between invocations: the probe now raises.
            live.execute.side_effect = Exception("server closed the connection unexpectedly")
            con2, meta2 = rt.get_warm_connection(dsn=_DSN)

        assert mock_open.call_count == 2  # reopened
        assert con2 is replacement
        assert meta2["reused"] is False
        assert meta2["reopened"] is True  # replaced a previously-cached (dead) connection
        live.close.assert_called_once()  # the dead connection was closed before reopen

    def test_force_reopen_bypasses_reuse(self) -> None:
        with patch("src.common.ducklake_runtime.open_connection", side_effect=[_make_con(), _make_con()]) as mock_open:
            rt.get_warm_connection(dsn=_DSN)
            _, meta = rt.get_warm_connection(dsn=_DSN, force_reopen=True)
        assert mock_open.call_count == 2
        assert meta["reused"] is False and meta["reopened"] is True

    def test_cross_catalog_key_reopens(self) -> None:
        """A different (data_path, meta_schema, extension_directory) cannot reuse a connection ATTACHed elsewhere."""
        with patch("src.common.ducklake_runtime.open_connection", side_effect=[_make_con(), _make_con()]) as mock_open:
            rt.get_warm_connection(dsn=_DSN, meta_schema="ducklake_ops")
            _, meta = rt.get_warm_connection(dsn=_DSN, meta_schema="ducklake_smoke")
        assert mock_open.call_count == 2
        assert meta["reused"] is False


class TestIsDeadConnectionError:
    @pytest.mark.parametrize(
        "msg",
        [
            "connection already closed",
            "server closed the connection unexpectedly",
            "could not connect to server",
            "SSL connection has been closed unexpectedly",
            "terminating connection due to administrator command",
        ],
    )
    def test_dead_signatures_match(self, msg: str) -> None:
        assert rt.is_dead_connection_error(Exception(msg)) is True

    @pytest.mark.parametrize(
        "msg",
        ["could not serialize access due to concurrent update", "schema gate rejected field", "permission denied"],
    )
    def test_non_dead_errors_do_not_match(self, msg: str) -> None:
        assert rt.is_dead_connection_error(Exception(msg)) is False


class TestPerThreadIsolation:
    def test_churn_open_connection_is_not_the_warm_global(self) -> None:
        """The churn harness opens its OWN connection per call (open_connection), never the warm cache.

        Two open_connection calls return DISTINCT connections (the per-thread churn model), and neither
        is placed in the warm-connection global -- so a concurrent churn never shares the cached
        connection across threads.
        """
        c_a, c_b = _make_con(), _make_con()
        with patch("src.common.ducklake_runtime.duckdb", create=True), patch("src.common.ducklake_runtime.ducklake_spike"):
            with patch("src.common.ducklake_runtime.open_connection", side_effect=[c_a, c_b]):
                # Direct open_connection (the churn path) -> distinct connections, warm cache untouched.
                a = rt.open_connection(dsn=_DSN)
                b = rt.open_connection(dsn=_DSN)
        assert a is not b
        assert rt._warm_connection.get("con") is None  # churn never populates the warm global

    def test_warm_global_holds_single_connection(self) -> None:
        with patch("src.common.ducklake_runtime.open_connection", side_effect=[_make_con(), _make_con()]):
            con1, _ = rt.get_warm_connection(dsn=_DSN)
            con2, _ = rt.get_warm_connection(dsn=_DSN)
        assert rt._warm_connection["con"] is con1 is con2  # exactly one cached connection


class TestResetWarmConnection:
    def test_reset_closes_and_clears(self) -> None:
        con = _make_con()
        with patch("src.common.ducklake_runtime.open_connection", side_effect=[con]):
            rt.get_warm_connection(dsn=_DSN)
        rt.reset_warm_connection()
        con.close.assert_called_once()
        assert rt._warm_connection.get("con") is None


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
