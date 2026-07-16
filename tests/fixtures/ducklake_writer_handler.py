"""Shared test doubles for the tests/lambdas/ducklake_writer/handler/ concern-split package.

FakeCon and _result() are copied verbatim from the former tests/test_ducklake_writer_handler.py
monolith (rec-2709 Wave 8). Used across >1 split module (test_envelope_dispatch.py,
test_churn.py, test_ops_actions.py). This writer FakeCon is DIFFERENT from the maintenance
FakeCon (tests/fixtures/ducklake_maintenance_handler.py) -- kept in a separate module to avoid
any name collision. An importable tests/fixtures/ module -- exempt from the no-cross-test-import
guard because its name does not start with test_ (tests/CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.common import ducklake_runtime as rt


class FakeCon:
    """Connection double: records SQL; canned fetchone by substring; fetchall list."""

    def __init__(self, fetchone_map=None, fetchall_result=None):
        self.executed: list[tuple[str, object]] = []
        self.closed = False
        self._fetchone_map = fetchone_map or {}
        self._fetchall = fetchall_result or []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self):
        return self._fetchall

    def close(self):
        self.closed = True


def _result(**kw):
    base = dict(
        ulid="01ULID",
        rec_id="rec-1",
        occ_retries=0,
        commit_ms=1.0,
        created_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_updated_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    base.update(kw)
    return rt.WriteResult(**base)
