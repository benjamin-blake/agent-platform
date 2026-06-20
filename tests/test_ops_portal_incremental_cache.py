#!/usr/bin/env python3
"""D4 incremental-cache unit tests for scripts/ops_data_portal.py (neon-egress-reduction).

VP step 2: a portal write (file_rec / update_rec) refreshes the local read-cache via an incremental
single-row upsert of the writer's committed row -- with ZERO full-table reader pulls. The write still
transits ducklake_writer synchronously (no buffering; Decision 84 I-4 intact); only the post-write
cache refresh changed from a per-write full resync to an in-place upsert.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import sync_ops
from scripts.ops_data_portal import file_rec, update_rec

_VALID_FIELDS = {
    "title": "Incremental cache test recommendation",
    "file": "scripts/ops_data_portal.py",
    "context": "A sufficiently long context string so the write-time content validators are satisfied here.",
    "acceptance": "grep -q upsert_cache_row scripts/sync_ops.py",
    "effort": "XS",
    "priority": "Low",
    "source": "planning",
    "status": "open",
    "risk": "low",
}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestUpsertCacheRowHelper:
    """The sync_ops.upsert_cache_row primitive: replace-or-append by merge key, atomic, deduped."""

    def test_appends_new_row(self, tmp_path: Path) -> None:
        cache = tmp_path / "recs.jsonl"
        n = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-001", "status": "open"}, path=cache)
        assert n == 1
        assert _read_jsonl(cache) == [{"id": "rec-001", "status": "open"}]

    def test_replaces_existing_row_in_place(self, tmp_path: Path) -> None:
        cache = tmp_path / "recs.jsonl"
        cache.write_text(
            json.dumps({"id": "rec-001", "status": "open"}) + "\n" + json.dumps({"id": "rec-002", "status": "open"}) + "\n",
            encoding="utf-8",
        )
        n = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-001", "status": "closed"}, path=cache)
        assert n == 2  # still two rows -- replaced in place, not appended
        rows = _read_jsonl(cache)
        assert rows[0] == {"id": "rec-001", "status": "closed"}  # position preserved
        assert rows[1] == {"id": "rec-002", "status": "open"}

    def test_dedupes_preexisting_duplicate_rows(self, tmp_path: Path) -> None:
        """A cache that already had append-duplicates collapses to one row per id on the next upsert."""
        cache = tmp_path / "recs.jsonl"
        cache.write_text(
            json.dumps({"id": "rec-001", "status": "open"}) + "\n" + json.dumps({"id": "rec-001", "status": "open"}) + "\n",
            encoding="utf-8",
        )
        sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-001", "status": "closed"}, path=cache)
        assert _read_jsonl(cache) == [{"id": "rec-001", "status": "closed"}]

    def test_missing_merge_key_is_noop(self, tmp_path: Path) -> None:
        cache = tmp_path / "recs.jsonl"
        assert sync_ops.upsert_cache_row("ops_recommendations", {"status": "open"}, path=cache) == 0
        assert not cache.exists()


class TestFileRecIncrementalCache:
    def test_file_rec_upserts_cache_without_reader_pull(self, tmp_path: Path) -> None:
        cache = tmp_path / ".recommendations-log.jsonl"
        writer_response = {"key": "rec-700", "ulid": "ulid-test-rec700"}  # low-entropy fake; portal copies verbatim
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value=writer_response),
            patch("scripts.ops_data_portal.RECS_JSONL", cache),
            patch("scripts.sync_ops._pull_single_table") as mock_pull,
            patch("scripts.sync_ops._pull_via_reader") as mock_reader_pull,
        ):
            rec_id = file_rec(dict(_VALID_FIELDS))

        assert rec_id == "rec-700"
        mock_pull.assert_not_called()  # no full-table resync
        mock_reader_pull.assert_not_called()  # no reader round-trip at all
        rows = _read_jsonl(cache)
        assert len(rows) == 1
        assert rows[0]["id"] == "rec-700"
        assert rows[0]["ulid"] == "ulid-test-rec700"  # enriched from the writer response
        assert rows[0]["last_updated_timestamp"]  # stamped for the read projection


class TestUpdateRecIncrementalCache:
    def test_update_rec_upserts_cache_without_reader_pull(self, tmp_path: Path) -> None:
        cache = tmp_path / ".recommendations-log.jsonl"
        existing = {**_VALID_FIELDS, "id": "rec-042", "status": "open", "created_timestamp": "2026-06-01T00:00:00+00:00"}
        cache.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True, "ulid": "ulid-test-rec042"}),
            patch("scripts.ops_data_portal.RECS_JSONL", cache),
            patch("scripts.sync_ops._pull_single_table") as mock_pull,
        ):
            assert update_rec("rec-042", {"status": "closed"}) is True

        mock_pull.assert_not_called()
        rows = _read_jsonl(cache)
        assert len(rows) == 1  # in-place replace, not append
        assert rows[0]["id"] == "rec-042"
        assert rows[0]["status"] == "closed"
        # created_timestamp carried unchanged from the existing row (SCD2 derivation).
        assert rows[0]["created_timestamp"] == "2026-06-01T00:00:00+00:00"

    def test_update_rec_still_writes_through_ducklake_writer(self, tmp_path: Path) -> None:
        """The write transits ducklake_writer synchronously -- the cache refresh is downstream, not a substitute."""
        cache = tmp_path / ".recommendations-log.jsonl"
        existing = {**_VALID_FIELDS, "id": "rec-042", "status": "open"}
        cache.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.RECS_JSONL", cache),
            patch("scripts.sync_ops._pull_single_table"),
        ):
            update_rec("rec-042", {"status": "closed"})

        assert mock_write.call_args.kwargs["action"] == "update_ops"  # synchronous writer commit


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))  # noqa: F821
