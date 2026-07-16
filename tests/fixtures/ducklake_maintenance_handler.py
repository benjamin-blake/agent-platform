"""Shared test doubles for the tests/lambdas/ducklake_maintenance/handler/ concern-split package.

FakeCon, _response_body(), and _FULL_DSN are copied verbatim from the former
tests/test_ducklake_maintenance_handler.py monolith (rec-2709 Wave 8). Used across >1 split
module (test_dispatch.py, test_maintenance_actions.py, test_operational_actions.py,
test_clone_catalog.py). An importable tests/fixtures/ module -- exempt from the no-cross-test-import
guard because its name does not start with test_ (tests/CLAUDE.md).
"""

from __future__ import annotations

import json
from typing import Any


class FakeCon:
    """Minimal connection double for handler dispatch tests."""

    def __init__(self, fetchall=None, fetchone_map=None):
        self.closed = False
        self._fetchall = fetchall or []
        self._fetchone_map = fetchone_map or {}
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "FakeCon":
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self) -> list[Any]:
        return self._fetchall

    def close(self) -> None:
        self.closed = True


def _response_body(r: dict[str, Any]) -> dict[str, Any]:
    return json.loads(r["body"])


_FULL_DSN = {"username": "u", "password": "p", "host": "hostx", "dbname": "neondb", "sslmode": "require"}
