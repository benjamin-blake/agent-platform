"""Metadata-count helpers + describe verb-schema + open-writer-connection concern for
src/lambdas/ducklake_writer/handler.py (T2.17, 100% coverage, mocked runtime).

Split from the former tests/test_ducklake_writer_handler.py monolith (rec-2709 Wave 8).
Functions copied VERBATIM.
"""

from __future__ import annotations

import json

import pytest

import src.lambdas.ducklake_writer.handler as h
from src.common import ducklake_runtime as rt
from tests.fixtures.ducklake_writer_handler import FakeCon

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# describe: per-verb parameter schema (CD.10 / CD.15), connectionless
# ---------------------------------------------------------------------------


def test_action_describe_returns_write_verb_schema():
    out = h.action_describe({}, None)
    assert out["ok"] is True
    assert set(out["verbs"]) == set(rt.VERB_REGISTRY)
    assert "params_schema" in out["verbs"]["update_ops"]


def test_describe_in_connectionless_actions():
    assert "describe" in h._CONNECTIONLESS_ACTIONS
    assert h._ACTIONS["describe"] is h.action_describe


def test_handler_describe_end_to_end():
    r = h.handler({"action": "describe"})
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["ok"] is True
    assert "write_ops" in body["verbs"]


# ---------------------------------------------------------------------------
# Growth-safe per-verb parametrized dispatch: every VERB_REGISTRY write verb has a describe entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", sorted(rt.VERB_REGISTRY))
def test_describe_write_verbs_covers_every_registered_verb(verb):
    out = h.action_describe({}, None)
    assert verb in out["verbs"]
    assert "description" in out["verbs"][verb]
    assert "params_schema" in out["verbs"][verb]


# ---------------------------------------------------------------------------
# metadata helpers
# ---------------------------------------------------------------------------


def test_count_files_success():
    con = FakeCon(fetchone_map={"ducklake_list_files": (3,)})
    assert h._count_files(con, rt.SMOKE_HISTORY_TABLE) == 3


def test_count_files_swallows_error():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("no such function")

    assert h._count_files(Boom(), "t") == 0


def test_count_files_for_predicate_success():
    con = FakeCon(fetchone_map={"WHERE": (1,)})
    assert h._count_files_for_predicate(con, rt.SMOKE_HISTORY_TABLE, "x = 1") == 1


def test_count_files_for_predicate_fallback():
    class PartialBoom:
        def __init__(self):
            self.calls = 0
            self._last = ""

        def execute(self, sql, params=None):
            self._last = sql
            if "ducklake_list_files" in sql:
                raise RuntimeError("no function")
            return self

        def fetchone(self):
            return (2,)

    assert h._count_files_for_predicate(PartialBoom(), "t", "x = 1") == 2


def test_count_inlined_rows_success():
    con = FakeCon(fetchone_map={"ducklake_list_inlined_data": (0,)})
    assert h._count_inlined_rows(con, rt.SMOKE_HISTORY_TABLE) == 0


def test_count_inlined_rows_swallows_error():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("nope")

    assert h._count_inlined_rows(Boom(), "t") == 0


# ---------------------------------------------------------------------------
# _open_writer_connection
# ---------------------------------------------------------------------------


def test_open_writer_connection(monkeypatch):
    monkeypatch.setattr(rt, "fetch_dsn", lambda: {"host": "h"})
    captured = {}
    monkeypatch.setattr(rt, "open_connection", lambda **kw: captured.update(kw) or "CON")
    out = h._open_writer_connection()
    assert out == "CON"
    assert captured["extension_directory"] == h.EXTENSION_DIRECTORY
