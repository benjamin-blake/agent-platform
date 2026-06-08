"""Tests for scripts/migrate_ops_iceberg_to_ducklake.py (T2.19 backfill parity, mocked).

No live catalog: the Iceberg source is a fake reader, the DuckLake target is an in-memory store
driven through monkeypatched runtime primitives. The live backfill is the [post-deploy] VP9 gate;
these tests prove the comparator catches mismatches, the Decision-70 exclusion, and idempotency.
"""

from __future__ import annotations

import pytest

import scripts.migrate_ops_iceberg_to_ducklake as mig

pytestmark = pytest.mark.unit


class FakeIcebergReader:
    """current_state(table) -> the canned Iceberg current rows for that table."""

    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows = rows_by_table

    def current_state(self, table, **_kwargs):
        return [dict(r) for r in self._rows.get(table, [])]


class InMemoryDuckLake:
    """In-memory current projection keyed by merge_key, driving the runtime primitives in tests."""

    def __init__(self):
        self.store: dict[str, dict[str, dict]] = {}
        self.recreated: list[str] = []

    def create(self, con, *, table, force_recreate=False):  # noqa: ARG002
        if force_recreate or table not in self.store:
            self.store[table] = {}
            self.recreated.append(table)

    def write(self, con, record, *, table, **_kwargs):  # noqa: ARG002
        from src.common.ducklake_runtime import resolve_table_spec

        key = record[resolve_table_spec(table).merge_key]
        self.store.setdefault(table, {})[key] = dict(record)

    def read(self, con, *, table, **_kwargs):  # noqa: ARG002
        return list(self.store.get(table, {}).values())


def _patch_runtime(monkeypatch, dl: InMemoryDuckLake):
    from src.common import ducklake_runtime as rt

    monkeypatch.setattr(rt, "create_scd2_tables", dl.create)
    monkeypatch.setattr(rt, "write_scd2", dl.write)
    monkeypatch.setattr(rt, "read_current", dl.read)


_RECS = [
    {"id": "rec-1", "status": "open", "title": "one", "tags": ["a"]},
    {"id": "rec-2", "status": "closed", "title": "two", "automatable": True},
]


def test_dry_run_counts_no_writes(monkeypatch):
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    stats = mig.backfill_table("ops_recommendations", con=None, reader=reader, execute=False)
    assert stats == {
        "table": "ops_recommendations",
        "source_rows": 2,
        "excluded_tombstones": 0,
        "written": 0,
        "executed": False,
    }
    assert dl.store == {}


def test_backfill_writes_all_rows(monkeypatch):
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    stats = mig.backfill_table("ops_recommendations", con=object(), reader=reader, execute=True)
    assert stats["written"] == 2
    assert set(dl.store["ops_recommendations"]) == {"rec-1", "rec-2"}


def test_backfill_excludes_decision70_tombstones(monkeypatch):
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: {"rec-2"})
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    stats = mig.backfill_table("ops_recommendations", con=object(), reader=reader, execute=True)
    assert stats["written"] == 1
    assert stats["excluded_tombstones"] == 1
    assert set(dl.store["ops_recommendations"]) == {"rec-1"}  # tombstoned rec-2 not resurrected


def test_idempotent_recreate_not_append(monkeypatch):
    """A second backfill DROPs + recreates -- the store is not doubled (resurrection-loop guard)."""
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    mig.backfill_table("ops_recommendations", con=object(), reader=reader, execute=True)
    mig.backfill_table("ops_recommendations", con=object(), reader=reader, execute=True)
    assert len(dl.store["ops_recommendations"]) == 2  # not 4
    assert dl.recreated.count("ops_recommendations") == 2  # force-recreated each run


def test_parity_pass_after_backfill(monkeypatch):
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    mig.backfill_table("ops_recommendations", con=object(), reader=reader, execute=True)
    parity = mig.verify_parity("ops_recommendations", con=object(), reader=reader)
    assert parity["parity"] == "PASS"
    assert parity["rows"] == 2


def test_parity_catches_count_mismatch(monkeypatch):
    """A missing DuckLake row (count mismatch) loud-fails (Decision 55)."""
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    # Backfill only ONE row into DuckLake, but Iceberg has two -> mismatch.
    dl.store["ops_recommendations"] = {"rec-1": dict(_RECS[0])}
    with pytest.raises(mig.ParityError, match="current="):
        mig.verify_parity("ops_recommendations", con=object(), reader=reader)


def test_parity_catches_content_mismatch(monkeypatch):
    """Equal counts but divergent content loud-fails (the comparator is not count-only)."""
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS})
    # Two rows but rec-2's title differs from the Iceberg source.
    dl.store["ops_recommendations"] = {
        "rec-1": dict(_RECS[0]),
        "rec-2": {"id": "rec-2", "status": "closed", "title": "DIFFERENT", "automatable": True},
    }
    with pytest.raises(mig.ParityError, match="content hash differs"):
        mig.verify_parity("ops_recommendations", con=object(), reader=reader)


def test_run_migration_dry_run_opens_no_connection(monkeypatch):
    """A dry-run (no execute/verify) never opens a catalog connection."""
    reader = FakeIcebergReader({"ops_recommendations": _RECS, "ops_decisions": [], "ops_priority_queue": []})

    def _boom():
        raise AssertionError("connection_factory must not be called in dry-run")

    result = mig.run_migration(connection_factory=_boom, reader=reader)
    assert result["executed"] is False
    assert {b["table"] for b in result["backfill"]} == set(mig.DEFAULT_TABLES)


class _FakeCon:
    def close(self):
        pass


def test_run_migration_execute_and_verify(monkeypatch):
    dl = InMemoryDuckLake()
    _patch_runtime(monkeypatch, dl)
    monkeypatch.setattr(mig, "load_tombstone_ids", lambda *_a, **_k: set())
    reader = FakeIcebergReader({"ops_recommendations": _RECS, "ops_decisions": [], "ops_priority_queue": []})
    result = mig.run_migration(
        ("ops_recommendations", "ops_decisions", "ops_priority_queue"),
        execute=True,
        verify=True,
        connection_factory=_FakeCon,
        reader=reader,
    )
    assert result["executed"] is True and result["verified"] is True
    assert all(p["parity"] == "PASS" for p in result["parity"])


def test_load_tombstone_ids_filters_by_table(tmp_path, monkeypatch):
    manifest = tmp_path / "dq_tombstones.yaml"
    manifest.write_text(
        "tombstones:\n  - {table: ops_recommendations, id: rec-9}\n  - {table: ops_decisions, id: dec-3}\n",
        encoding="utf-8",
    )
    ids = mig.load_tombstone_ids("ops_recommendations", path=manifest)
    assert ids == {"rec-9"}


def test_load_tombstone_ids_missing_file_empty(tmp_path):
    assert mig.load_tombstone_ids("ops_recommendations", path=tmp_path / "nope.yaml") == set()


def test_open_ducklake_connection_requires_data_path(monkeypatch):
    monkeypatch.delenv("DUCKLAKE_DATA_PATH", raising=False)
    with pytest.raises(RuntimeError, match="DUCKLAKE_DATA_PATH"):
        mig._open_ducklake_connection()


def test_main_dry_run(monkeypatch, capsys):
    rows = {"ops_recommendations": _RECS, "ops_decisions": [], "ops_priority_queue": []}
    monkeypatch.setattr(mig, "read_iceberg_current", lambda table, reader=None: [dict(r) for r in rows.get(table, [])])
    rc = mig.main([])
    assert rc == 0
    assert "backfill" in capsys.readouterr().out


def test_main_parity_failure_returns_1(monkeypatch, capsys):
    def _boom(*a, **k):
        raise mig.ParityError("mismatch")

    monkeypatch.setattr(mig, "run_migration", _boom)
    rc = mig.main(["--execute", "--verify-parity"])
    assert rc == 1
    assert "PARITY FAIL" in capsys.readouterr().err


def test_content_hash_normalizes_type_asymmetry():
    """An Iceberg string-array vs a DuckLake native-list hash IDENTICALLY after normalization (High #4)."""
    iceberg_side = [{"id": "rec-1", "status": "open", "title": "t", "tags": "[a, b]", "dependencies": "[rec-2]"}]
    ducklake_side = [{"id": "rec-1", "status": "open", "title": "t", "tags": ["a", "b"], "dependencies": ["rec-2"]}]
    assert mig._content_hash("ops_recommendations", iceberg_side) == mig._content_hash("ops_recommendations", ducklake_side)


def test_default_tables_excludes_priority_queue():
    """ops_priority_queue is excluded from the live backfill set (snapshot semantics, Medium #1)."""
    assert mig.DEFAULT_TABLES == ("ops_recommendations", "ops_decisions")
