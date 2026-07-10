"""Tests for scripts/ops_data_portal.py (Decision 84 contracts).

The offline outbox is retired: file_rec/file_decision raise loudly on failure and
never return 'pending-...'. IDs are allocated by the ducklake_writer (file_ops) or
supplied by the caller (decisions / migration backfill). All warehouse reads transit
the DuckLake reader's named-verb surface.

Decision 124 namespace migration: most patches below target the facade
(scripts.ops_data_portal) because the driving call (file_rec/update_rec/propose_or_close_rec/
_fetch_rec_from_reader/sync/get_ci_rca_strict_mode) is facade-resident and resolves its
dependencies as its own module globals. Where the driving call has MOVED to a
scripts/ops_portal submodule that holds its own bare-imported copy of the dependency
(file_decision/update_decision/backfill_decisions_from_md -> decisions.py;
selftest_roundtrip/find_open_postmortem_for -> maintenance_ops.py; compute_risk ->
risk_scoring.py; _load_write_time_validators's cache -> write_validators.py;
_run_ci_rca_cross_check's bundle load -> ci_rca_schema.py; _ducklake_write's URL
resolution -> writer_transport.py), the patch targets that submodule instead -- the
namespace the moved caller actually resolves at call time (tests/CLAUDE.md namespace
migration discipline).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

duckdb = pytest.importorskip("duckdb")
from pydantic import ValidationError  # noqa: E402

from scripts.ops_portal import ci_rca_schema as _ci_rca_schema_mod  # noqa: E402
from scripts.ops_portal import maintenance_ops as _maintenance_ops_mod  # noqa: E402
from scripts.ops_portal import writer_transport as _writer_transport_mod  # noqa: E402
from src.common import ducklake_runtime as rt  # noqa: E402
from src.common.ducklake_scd2_schema import load_field_semantics, resolve_table_spec  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal valid rec fields (all required Recommendation fields)
# ---------------------------------------------------------------------------
_VALID_FIELDS = {
    "title": "Test recommendation",
    "file": "scripts/ops_data_portal.py",
    "context": "This is a test rec context with enough detail to satisfy the 80-character minimum requirement.",
    "acceptance": "grep -q 'ops_data_portal' scripts/ops_data_portal.py",
    "effort": "XS",
    "priority": "Low",
    "source": "planning",
    "risk": "low",
    "status": "open",
    "automatable": True,
}

_VALID_DECISION_FIELDS = {
    "title": "Test decision",
    "status": "open",
    "decision_id": 56,
}


class _FakeResp:
    """Minimal requests.Response stand-in for _ducklake_write transport tests."""

    def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self) -> dict:
        return self._body


def _patch_writer_transport(monkeypatch, responses: list[_FakeResp], sleeps: list | None = None) -> list[dict]:
    """Install fake boto3 session / SigV4 / requests.post returning *responses* in order.

    Returns the list of JSON-decoded request bodies captured per POST.
    """
    import time

    import boto3
    import requests
    from botocore.auth import SigV4Auth

    class _Creds:
        access_key = "AK"
        secret_key = "SK"  # noqa: S105 -- fake fixture  # pragma: allowlist secret
        token = None

        def get_frozen_credentials(self):
            return self

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return _Creds()

    monkeypatch.setattr(boto3, "Session", _Session)
    monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s) if sleeps is not None else None)

    bodies: list[dict] = []
    seq = iter(responses)

    def _post(url, data=None, headers=None, timeout=None):
        bodies.append(json.loads(data))
        return next(seq)

    monkeypatch.setattr(requests, "post", _post)
    return bodies


class TestFileRec:
    """Tests for file_rec() -- writer-allocated IDs via the file_ops action."""

    def test_file_rec_success_consumes_allocated_key(self, tmp_path: Path) -> None:
        """file_rec() sends action=file_ops with an idempotency ULID and returns the writer-allocated id."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-2171"}) as mock_dl_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS))

        assert result == "rec-2171"
        mock_dl_write.assert_called_once()
        call_table, call_rec = mock_dl_write.call_args[0]
        assert call_table == "ops_recommendations"
        assert call_rec["status"] == "open"
        assert mock_dl_write.call_args.kwargs["action"] == "file_ops"
        ulid = mock_dl_write.call_args.kwargs["idempotency_ulid"]
        assert isinstance(ulid, str) and len(ulid) == 26  # ULID (time-ordered tiebreak for history reads)
        # write-through: local JSONL has new entry carrying the allocated id
        lines = recs_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["id"] == "rec-2171"

    def test_file_rec_missing_allocated_key_raises(self, tmp_path: Path) -> None:
        """file_rec() raises RuntimeError when the writer response carries no allocated key."""
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
        ):
            from scripts.ops_data_portal import file_rec

            with pytest.raises(RuntimeError, match="no allocated key"):
                file_rec(dict(_VALID_FIELDS))

    def test_file_rec_raises_loudly_on_writer_failure(self, tmp_path: Path) -> None:
        """file_rec() propagates the writer failure -- there is no offline outbox / 'pending-' path."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch(
                "scripts.ops_data_portal._ducklake_write",
                side_effect=RuntimeError("ducklake_writer file_ops ops_recommendations failed (HTTP 500)"),
            ),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            with pytest.raises(RuntimeError, match="ducklake_writer"):
                file_rec(dict(_VALID_FIELDS))

        assert not recs_file.exists()  # nothing was written through

    def test_file_rec_invalid_schema(self) -> None:
        """file_rec() raises when rec fields fail validation (write-time gate or Pydantic)."""
        invalid_fields = dict(_VALID_FIELDS)
        invalid_fields.pop("status")

        from scripts.ops_data_portal import file_rec

        with pytest.raises((ValidationError, ValueError)):
            file_rec(invalid_fields)

    def test_file_rec_date_added_if_missing(self, tmp_path: Path) -> None:
        """file_rec() adds today's date to the record if not supplied."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-602"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS))

        assert result == "rec-602"
        entry = json.loads(recs_file.read_text(encoding="utf-8").strip().splitlines()[0])
        assert entry.get("date") is not None  # date was added

    def test_file_rec_rejects_unregistered_source(self, tmp_path: Path) -> None:
        """file_rec() raises ValueError when source is not in the registry; no write is attempted."""
        fields = dict(_VALID_FIELDS)
        fields["source"] = "ghost-agent"

        with (
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
        ):
            from scripts.ops_data_portal import file_rec

            with pytest.raises(ValueError, match="Unknown source 'ghost-agent'"):
                file_rec(fields)

        mock_dl_write.assert_not_called()

    def test_file_rec_accepts_registered_source(self, tmp_path: Path) -> None:
        """file_rec() succeeds when source is a registered canonical_id."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        fields = dict(_VALID_FIELDS)
        fields["source"] = "planning"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-998"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(fields)

        assert result == "rec-998"


class TestUpdateRec:
    """Tests for update_rec()."""

    def test_update_rec_success(self, tmp_path: Path) -> None:
        """update_rec() reads via the reader, merges updates, writes update_ops, appends to local JSONL."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            result = update_rec("rec-042", {"status": "closed", "execution_result": "success"})

        assert result is True
        call_table, call_rec = mock_dl_write.call_args[0]
        assert call_table == "ops_recommendations"
        assert call_rec["status"] == "closed"
        assert call_rec["execution_result"] == "success"
        assert mock_dl_write.call_args.kwargs["action"] == "update_ops"
        # write-through: the incremental upsert keeps ONE deduplicated row per id (D4), reflecting
        # the update (was: append, which left the stale original behind until the next full sync).
        lines = recs_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        cached = json.loads(lines[0])
        assert cached["id"] == "rec-042" and cached["status"] == "closed"

    def test_update_rec_invalid_status(self) -> None:
        """update_rec() raises ValueError for invalid status values (before any read)."""
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="Invalid status"):
            update_rec("rec-042", {"status": "done"})

    def test_update_rec_absent_rec_loud_fails(self, tmp_path: Path) -> None:
        """update_rec() loud-fails on an absent rec (referential, CD.33 cl.8 / D-5).

        An update of a record that does not exist in the current projection raises
        RuntimeError and never silently creates a partial row.
        """
        recs_file = tmp_path / ".recommendations-log.jsonl"
        updates = {**_VALID_FIELDS, "id": "rec-042", "status": "closed"}

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=None),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            with pytest.raises(RuntimeError, match="does not exist"):
                update_rec("rec-042", updates)

        # No write happened -- the absent rec was rejected before any write path.
        mock_dl_write.assert_not_called()


class TestFileDecision:
    """Tests for file_decision() -- DECISIONS.md is the numbering authority (Decision 84 I-2 exception)."""

    def test_file_decision_success_with_decision_id(self, tmp_path: Path) -> None:
        """file_decision() forms dec-NNN from fields['decision_id'] and writes via write_ops."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        with (
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision(dict(_VALID_DECISION_FIELDS))

        assert result == "dec-056"
        call_table, call_rec = mock_dl_write.call_args[0]
        assert call_table == "ops_decisions"
        assert mock_dl_write.call_args.kwargs["action"] == "write_ops"
        assert call_rec["decision_id"] == 56
        assert call_rec["id"] == "dec-056"
        assert call_rec["created_timestamp"] and call_rec["last_updated_timestamp"]
        # D4: the cache refresh is an incremental upsert, not a full-table _sync_table pull.
        mock_sync.assert_not_called()
        cached = [json.loads(line) for line in decisions_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(d["id"] == "dec-056" for d in cached)

    def test_file_decision_requires_decision_id(self, tmp_path: Path) -> None:
        """file_decision() raises ValueError when no DECISIONS.md-assigned integer is supplied."""
        with patch("scripts.ops_portal.decisions._ducklake_write") as mock_dl_write:
            from scripts.ops_data_portal import file_decision

            with pytest.raises(ValueError, match="DECISIONS.md-assigned integer"):
                file_decision({"title": "No number", "status": "open"})

        mock_dl_write.assert_not_called()

    def test_file_decision_rejects_non_positive_and_non_int_decision_id(self) -> None:
        """decision_id must be a positive int -- 0 and string forms are rejected."""
        from scripts.ops_data_portal import file_decision

        with pytest.raises(ValueError, match="DECISIONS.md-assigned integer"):
            file_decision({"title": "Zero", "status": "open", "decision_id": 0})
        with pytest.raises(ValueError, match="DECISIONS.md-assigned integer"):
            file_decision({"title": "String", "status": "open", "decision_id": "84"})

    def test_file_decision_migration_int_id_takes_precedence(self, tmp_path: Path) -> None:
        """_migration_int_id supplies the number on the backfill path (no decision_id field needed)."""
        with (
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", tmp_path / "dec.jsonl"),
            patch("scripts.ops_portal.decisions._sync_table"),
            patch("scripts.ops_portal.decisions._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision({"title": "Backfill", "status": "open"}, _migration_int_id=84)

        assert result == "dec-084"
        _, call_rec = mock_dl_write.call_args[0]
        assert call_rec["id"] == "dec-084"
        assert call_rec["decision_id"] == 84


class TestUpdateDecision:
    """Tests for update_decision() and the reader-backed decision fetch."""

    _EXISTING = {
        "id": "dec-042",
        "title": "D",
        "status": "open",
        "created_timestamp": "2026-05-01T00:00:00+00:00",
        "last_updated_timestamp": "2026-05-01T00:00:00+00:00",
    }

    def test_update_decision_routes_update_ops(self, tmp_path: Path) -> None:
        """update_decision() merges and writes via _ducklake_write(action='update_ops')."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        with (
            patch("scripts.ops_portal.decisions._fetch_decision_from_reader", return_value=dict(self._EXISTING)),
            patch("scripts.ops_portal.decisions._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_portal.decisions.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import update_decision

            assert update_decision("dec-042", {"status": "closed"}) is True

        call_table, call_rec = mock_dl_write.call_args[0]
        assert call_table == "ops_decisions"
        assert call_rec["status"] == "closed"
        assert mock_dl_write.call_args.kwargs["action"] == "update_ops"
        # D4: the cache refresh is an incremental upsert, not a full-table _sync_table pull.
        mock_sync.assert_not_called()
        cached = [json.loads(line) for line in decisions_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(d["id"] == "dec-042" and d["status"] == "closed" for d in cached)

    def test_update_decision_absent_loud_fails(self) -> None:
        """update_decision() raises RuntimeError when the decision is absent from the projection."""
        with (
            patch("scripts.ops_portal.decisions._fetch_decision_from_reader", return_value=None),
            patch("scripts.ops_portal.decisions._ducklake_write") as mock_dl_write,
        ):
            from scripts.ops_data_portal import update_decision

            with pytest.raises(RuntimeError, match="does not exist"):
                update_decision("dec-042", {"status": "closed"})

        mock_dl_write.assert_not_called()

    def test_fetch_decision_from_reader_uses_named_verb(self) -> None:
        """_fetch_decision_from_reader uses named('decision_by_id', id=...) on the DuckLake reader."""
        reader = MagicMock()
        reader.named.return_value = [dict(self._EXISTING)]

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_decision_from_reader

            result = _fetch_decision_from_reader("dec-042")

        assert result is not None
        assert result["id"] == "dec-042"
        reader.named.assert_called_once_with("decision_by_id", id="dec-042")

    def test_fetch_decision_from_reader_invalid_id(self) -> None:
        """Malformed decision_id raises ValueError before any reader call."""
        from scripts.ops_data_portal import _fetch_decision_from_reader

        with pytest.raises(ValueError, match="invalid decision_id"):
            _fetch_decision_from_reader("rec-042")

    def test_fetch_decision_athena_alias_retained(self) -> None:
        """The historical _fetch_decision_from_athena symbol aliases the reader fetch (read-engine.yaml)."""
        from scripts.ops_data_portal import _fetch_decision_from_athena, _fetch_decision_from_reader

        assert _fetch_decision_from_athena is _fetch_decision_from_reader


class TestRetiredSurfaces:
    """Decision 84: the offline outbox, OpsWriter transport, and DynamoDB id allocation are gone."""

    def test_outbox_and_legacy_symbols_absent(self) -> None:
        """drain_pending / outbox dirs / _next_id / OpsWriter / backend flag no longer exist on the portal."""
        import scripts.ops_data_portal as portal

        for name in (
            "drain_pending",
            "drain_pending_decisions",
            "_PENDING_OUTBOX",
            "_DECISIONS_PENDING_OUTBOX",
            "_next_id",
            "OpsWriter",
            "_ops_backend",
            "_delete_postmortems_from_iceberg",
            "_rewrite_jsonl_excluding_postmortems",
        ):
            assert not hasattr(portal, name), f"retired symbol still present: {name}"

    def test_portal_exposes_no_import_bypass_write_surface(self) -> None:
        """The ONLY ops write surface is file_rec/update_rec/file_decision/update_decision. No
        import/bootstrap/bypass writer is exposed on the portal (Decision 81)."""
        import scripts.ops_data_portal as portal

        forbidden = [
            n
            for n in dir(portal)
            if any(k in n.lower() for k in ("import_rec", "bootstrap", "bypass", "seed_rec", "raw_write", "import_ops"))
        ]
        assert forbidden == []


class TestEnqueueFindings:
    """Tests for enqueue_findings()."""

    def test_enqueue_findings_bulk_success(self, tmp_path: Path) -> None:
        """enqueue_findings() files each valid entry through file_rec (writer-allocated ids)."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        jsonl_file = tmp_path / "findings.jsonl"
        entry = {**_VALID_FIELDS, "source": "cc-scheduled-agent-test"}
        jsonl_file.write_text("\n".join([json.dumps(entry)] * 3) + "\n", encoding="utf-8")

        with (
            patch(
                "scripts.ops_data_portal._ducklake_write",
                side_effect=[{"key": "rec-801"}, {"key": "rec-802"}, {"key": "rec-803"}],
            ),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import enqueue_findings

            result = enqueue_findings(jsonl_file)

        assert result == {"enqueued": 3, "invalid": 0, "skipped": 0}
        ids = [json.loads(line)["id"] for line in recs_file.read_text(encoding="utf-8").strip().splitlines()]
        assert ids == ["rec-801", "rec-802", "rec-803"]

    def test_enqueue_findings_invalid_entries_counted_not_raised(self, tmp_path: Path) -> None:
        """enqueue_findings() counts schema failures as invalid and JSON parse errors as skipped."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        jsonl_file = tmp_path / "mixed.jsonl"
        valid = {**_VALID_FIELDS, "source": "cc-scheduled-agent-test"}
        lines = [
            json.dumps(valid),
            json.dumps(valid),
            json.dumps({"missing_required_fields": True}),
            "not valid json {{{",
        ]
        jsonl_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._ducklake_write", side_effect=[{"key": "rec-801"}, {"key": "rec-802"}]),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import enqueue_findings

            result = enqueue_findings(jsonl_file)

        assert result == {"enqueued": 2, "invalid": 1, "skipped": 1}

    def test_enqueue_findings_missing_path(self, tmp_path: Path) -> None:
        """enqueue_findings() returns zeros without raising when given a non-existent path."""
        from scripts.ops_data_portal import enqueue_findings

        result = enqueue_findings(tmp_path / "does_not_exist.jsonl")

        assert result == {"enqueued": 0, "invalid": 0, "skipped": 0}


class TestPostmortems:
    """Tests for find_open_postmortem_for and the SCD2 purge (supersede) flow."""

    def test_find_open_postmortem_for_returns_match(self, tmp_path: Path) -> None:
        recs_file = tmp_path / "recs.jsonl"
        postmortem = {
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
        }
        recs_file.write_text(json.dumps(postmortem) + "\n", encoding="utf-8")

        with patch("scripts.ops_portal.maintenance_ops.RECS_JSONL", recs_file):
            from scripts.ops_data_portal import find_open_postmortem_for

            result = find_open_postmortem_for("rec-100")

        assert result is not None
        assert result["id"] == "rec-529"

    def test_find_open_postmortem_for_returns_none_when_declined(self, tmp_path: Path) -> None:
        recs_file = tmp_path / "recs.jsonl"
        postmortem = {
            "id": "rec-529",
            "status": "declined",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
        }
        recs_file.write_text(json.dumps(postmortem) + "\n", encoding="utf-8")

        with patch("scripts.ops_portal.maintenance_ops.RECS_JSONL", recs_file):
            from scripts.ops_data_portal import find_open_postmortem_for

            result = find_open_postmortem_for("rec-100")

        assert result is None

    def test_find_open_postmortem_for_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        missing_file = tmp_path / "missing.jsonl"
        with patch("scripts.ops_portal.maintenance_ops.RECS_JSONL", missing_file):
            from scripts.ops_data_portal import find_open_postmortem_for

            result = find_open_postmortem_for("rec-100")

        assert result is None

    @staticmethod
    def _reader_with_rows(rows: list[dict]) -> MagicMock:
        reader = MagicMock()
        reader.named.return_value = rows
        return reader

    def test_purge_postmortems_dry_run_matches_without_writing(self) -> None:
        """dry_run reports the matched (non-superseded executor-postmortem) recs and writes nothing."""
        rows = [
            {
                "id": "rec-529",
                "source": "executor-postmortem",
                "status": "open",
                "title": "Investigate executor failure for rec-100 (attempt 2)",
            },
            {
                "id": "rec-530",
                "source": "executor-postmortem",
                "status": "superseded",
                "title": "Investigate executor failure for rec-100",
            },
            {"id": "rec-531", "source": "code-review", "status": "open", "title": "Investigate executor failure for rec-100"},
            {
                "id": "rec-532",
                "source": "executor-postmortem",
                "status": "open",
                "title": "Investigate executor failure for rec-1001",
            },
        ]
        reader = self._reader_with_rows(rows)

        with (
            patch("src.common.iceberg_reader.make_reader", return_value=reader),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            from scripts.ops_data_portal import purge_postmortems_for

            result = purge_postmortems_for("rec-100", dry_run=True)

        assert result == {"matched": ["rec-529"], "superseded": 0}
        reader.named.assert_called_once_with("recs_by_title_prefix", title_prefix="Investigate executor failure for rec-100%")
        mock_update.assert_not_called()

    def test_purge_postmortems_supersedes_and_declines(self) -> None:
        """Each matched postmortem becomes status=superseded via update_rec; the failed rec is declined."""
        rows = [
            {
                "id": "rec-529",
                "source": "executor-postmortem",
                "status": "open",
                "title": "Investigate executor failure for rec-100",
            },
            {
                "id": "rec-533",
                "source": "executor-postmortem",
                "status": "open",
                "title": "Investigate executor failure for rec-100 (attempt 2)",
            },
        ]
        reader = self._reader_with_rows(rows)

        with (
            patch("src.common.iceberg_reader.make_reader", return_value=reader),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            from scripts.ops_data_portal import purge_postmortems_for

            result = purge_postmortems_for("rec-100", dry_run=False)

        assert result["matched"] == ["rec-529", "rec-533"]
        assert result["superseded"] == 2
        statuses = {call.args[0]: call.args[1]["status"] for call in mock_update.call_args_list}
        assert statuses["rec-529"] == "superseded"
        assert statuses["rec-533"] == "superseded"
        assert statuses["rec-100"] == "declined"
        assert mock_update.call_count == 3

    def test_purge_postmortems_invalid_rec_id_raises(self) -> None:
        """Malformed rec id raises ValueError before any reader call."""
        from scripts.ops_data_portal import purge_postmortems_for

        with pytest.raises(ValueError, match="Invalid rec ID"):
            purge_postmortems_for("'; DROP TABLE ops_recommendations; --")


class TestBackfillDecisionsFromMd:
    """Tests for backfill_decisions_from_md() -- DECISIONS.md -> ops_decisions ETL."""

    def test_backfill_writes_coerced_entries(self) -> None:
        """Each parsed entry is filed via file_decision(_migration_int_id=n, _skip_sync=True)."""
        entries = [
            {
                "decision_id": 84,
                "title": "Decision 84",
                "status": "Decided",
                "problem": "p",
                "decision_text": "d",
                "context": "c",
                "decided_date": "2026-06-10",
                "related_decisions": "[81, 79]",
                "not_a_backfill_col": "dropped",
            },
            {"decision_id": "", "title": "no number"},  # skipped
        ]
        with (
            patch("scripts.decisions_md.parse_decisions_md", return_value=entries),
            patch("scripts.ops_portal.decisions.file_decision", return_value="dec-084") as mock_fd,
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import backfill_decisions_from_md

            result = backfill_decisions_from_md()

        assert result == {"written": 1, "failed": 0, "skipped": 1}
        mock_fd.assert_called_once()
        fields = mock_fd.call_args.args[0]
        assert fields["related_decisions"] == [81, 79]
        assert "not_a_backfill_col" not in fields and "decision_id" not in fields
        assert mock_fd.call_args.kwargs["_migration_int_id"] == 84
        assert mock_fd.call_args.kwargs["_skip_sync"] is True
        mock_sync.assert_called_once_with("ops_decisions")

    def test_backfill_isolates_per_row_failures(self) -> None:
        """A failing row increments failed without aborting the run; no sync when nothing written."""
        entries = [
            {"decision_id": 1, "title": "boom", "status": "Decided"},
            {"decision_id": "not-an-int", "title": "skip me"},
        ]
        with (
            patch("scripts.decisions_md.parse_decisions_md", return_value=entries),
            patch("scripts.ops_portal.decisions.file_decision", side_effect=RuntimeError("writer down")),
            patch("scripts.ops_portal.decisions._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import backfill_decisions_from_md

            result = backfill_decisions_from_md()

        assert result == {"written": 0, "failed": 1, "skipped": 1}
        mock_sync.assert_not_called()


class TestCLI:
    """Tests for the CLI entrypoint."""

    def test_cli_file_rec_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec prints the writer-allocated rec ID to stdout."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-700"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(
                [
                    "--file-rec",
                    "--title",
                    "CLI test rec",
                    "--file",
                    "scripts/ops_data_portal.py",
                    "--context",
                    "Testing the CLI entrypoint for file_rec -- this context satisfies the 80-char minimum.",
                    "--acceptance",
                    "grep -q ops_data_portal scripts/ops_data_portal.py",
                    "--effort",
                    "XS",
                    "--priority",
                    "Low",
                    "--source",
                    "planning",
                    "--risk",
                    "low",
                ]
            )

        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-700" in captured.out

    def test_cli_file_rec_missing_required(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec exits 1 and prints error when required fields missing."""
        from scripts.ops_data_portal import main

        rc = main(["--file-rec", "--title", "Only title"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_cli_update_rec_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --update-rec calls update_rec and prints confirmation."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(["--update-rec", "rec-042", "--status", "closed"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-042" in captured.out

    def test_cli_enqueue_findings_dispatches(self, tmp_path: Path) -> None:
        """CLI --enqueue-findings calls enqueue_findings with the given path and profile."""
        jsonl_file = tmp_path / "findings.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        with patch(
            "scripts.ops_data_portal.enqueue_findings",
            return_value={"enqueued": 0, "invalid": 0, "skipped": 0},
        ) as mock_enqueue:
            from scripts.ops_data_portal import main

            rc = main(["--enqueue-findings", str(jsonl_file)])

        assert rc == 0
        mock_enqueue.assert_called_once_with(Path(str(jsonl_file)), profile=None)

    def test_cli_backfill_decisions_md_dispatches(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --backfill-decisions-md runs the ETL and exits 1 when any row failed."""
        with patch(
            "scripts.ops_data_portal.backfill_decisions_from_md",
            return_value={"written": 5, "failed": 0, "skipped": 1},
        ) as mock_backfill:
            from scripts.ops_data_portal import main

            rc = main(["--backfill-decisions-md"])

        assert rc == 0
        mock_backfill.assert_called_once_with(profile=None)
        assert '"written": 5' in capsys.readouterr().out

        with patch(
            "scripts.ops_data_portal.backfill_decisions_from_md",
            return_value={"written": 4, "failed": 1, "skipped": 0},
        ):
            from scripts.ops_data_portal import main

            assert main(["--backfill-decisions-md"]) == 1


class TestWriteTimeDispatch:
    """Tests for _load_write_time_validators and _derive_computed_fields via file_rec."""

    def test_write_time_validators_loaded(self) -> None:
        """_load_write_time_validators returns >= 6 validators for ops_recommendations."""
        from scripts.ops_data_portal import _load_write_time_validators, _write_time_validators_cache

        _write_time_validators_cache.clear()
        validators = _load_write_time_validators("ops_recommendations")
        assert len(validators) >= 6, f"Expected >= 6 write_time validators, got {len(validators)}"
        col_names = [col for col, _ in validators]
        assert "title" in col_names
        assert "status" in col_names
        assert "effort" in col_names
        assert "priority" in col_names

    def test_write_time_rejects_null_required_field(self) -> None:
        """file_rec() raises ValueError via write_time validators when a required field is null."""
        from scripts.ops_data_portal import _write_time_validators_cache, file_rec

        _write_time_validators_cache.clear()
        fields = dict(_VALID_FIELDS)
        fields["status"] = None  # status has write_time: true in ops.yaml

        with pytest.raises(ValueError, match="status"):
            file_rec(fields)

    def test_file_rec_computes_automatable(self, tmp_path: Path) -> None:
        """file_rec() derives and sets automatable for records that lack it."""
        recs_file = tmp_path / "recs.jsonl"
        fields_no_automatable = {k: v for k, v in _VALID_FIELDS.items() if k != "automatable"}

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-950"}) as mock_dl_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_portal.write_validators._write_time_validators_cache", {}),
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(fields_no_automatable)

        _, written = mock_dl_write.call_args[0]
        assert written.get("automatable") is not None, "automatable should be derived and non-null"

    def test_file_rec_created_timestamp_full_precision(self, tmp_path: Path) -> None:
        """file_rec() sets created_timestamp with a time component, not a date-only midnight fallback."""
        recs_file = tmp_path / "recs.jsonl"
        fields = dict(_VALID_FIELDS)
        fields.pop("created_timestamp", None)

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-951"}) as mock_dl_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_portal.write_validators._write_time_validators_cache", {}),
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(fields)

        _, written = mock_dl_write.call_args[0]
        ts = written.get("created_timestamp", "")
        assert ts, "created_timestamp must be set"
        assert "T" in ts, f"created_timestamp must contain a time component (got {ts!r})"
        assert len(ts) > 10, f"created_timestamp must be a full ISO datetime, not date-only (got {ts!r})"


class TestCiRcaSourceFileGate:
    """Tests for the ci-rca source-file gate in file_rec()."""

    _MINIMAL_CI_RCA_FIELDS = {
        "title": "CI broken: IAM gap in runner policy",
        "file": "terraform/ec2_runner.tf",
        "context": (
            "Runner IAM denied s3:GetObject on agent-logs/tmp/* during the upload-artifacts CI step. "
            "Error: AccessDeniedException was thrown. Fix: add s3:GetObject to the runner policy resource block."
        ),
        "acceptance": "grep -q 'GetObject' terraform/ec2_runner.tf",
        "effort": "S",
        "priority": "Critical",
        "source": "ci_rca",
        "risk": "low",
        "status": "open",
        "automatable": True,
    }

    def test_rejects_empty_file(self) -> None:
        fields = dict(self._MINIMAL_CI_RCA_FIELDS)
        fields["file"] = ""
        from scripts.ops_data_portal import file_rec

        with pytest.raises(ValueError) as exc_info:
            file_rec(fields)
        assert "source_file" in str(exc_info.value)

    def test_rejects_missing_file_key(self) -> None:
        fields = dict(self._MINIMAL_CI_RCA_FIELDS)
        fields.pop("file")
        from scripts.ops_data_portal import file_rec

        with pytest.raises(ValueError) as exc_info:
            file_rec(fields)
        assert "source_file" in str(exc_info.value)

    def test_accepts_populated_file(self, tmp_path: Path) -> None:
        fields = dict(self._MINIMAL_CI_RCA_FIELDS)
        from scripts.ops_data_portal import file_rec

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-1234"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
        ):
            result = file_rec(fields)
        assert result == "rec-1234"


class TestComputeRisk:
    """Tests for compute_risk()."""

    def _radon_mock(self, stdout: str, returncode: int = 0):
        """Return a mock subprocess.CompletedProcess with given stdout."""
        from unittest.mock import MagicMock

        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        return m

    def test_low_tier_returned_for_small_r(self) -> None:
        """R = (1 * 0.1) / 0.1 = 1.0 -> 'low' (C=1 from radon, S=XS, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (1)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "XS") == "low"

    def test_medium_tier_returned_for_mid_r(self) -> None:
        """R = (2 * 0.5) / 0.1 = 10 -> 'medium' (C=2, effort=S, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (2)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "S") == "medium"

    def test_high_tier_returned_for_large_r(self) -> None:
        """R = (10 * 1.0) / 0.1 = 100 -> 'high' (C=10, effort=M, M=0.1 baseline)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - C (10)\n")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            assert compute_risk("file.py", "M") == "high"

    def test_fallback_c_on_radon_failure(self) -> None:
        """Radon subprocess exception -> C=1.0 fallback, formula still produces valid tier."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", side_effect=OSError("radon missing")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("missing.py", "XS")
        assert result in ("low", "medium", "high")

    def test_fallback_c_on_empty_radon_output(self) -> None:
        """Radon returns empty stdout -> C=1.0 fallback."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "XS")
        assert result in ("low", "medium", "high")

    def test_fallback_c_on_nonzero_radon_returncode(self) -> None:
        """Radon non-zero exit -> C=1.0 fallback (returncode check)."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("error output", returncode=1)),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "M")
        assert result in ("low", "medium", "high")

    def test_coverage_xml_line_rate_applied(self, tmp_path: Path) -> None:
        """When coverage.xml has a matching class entry, M = line_rate + 0.1."""
        coverage_xml = tmp_path / "coverage.xml"
        coverage_xml.write_text(
            '<?xml version="1.0"?>'
            "<coverage><packages><package><classes>"
            '<class filename="scripts/ops_data_portal.py" line-rate="0.9"></class>'
            "</classes></package></packages></coverage>",
            encoding="utf-8",
        )
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("file.py\n    F 1:0 f - A (1)\n")),
            patch("scripts.ops_portal.risk_scoring._COVERAGE_XML", coverage_xml),
        ):
            from scripts.ops_data_portal import compute_risk

            # C=1, S=0.1 (XS), M=0.9+0.1=1.0 -> R=0.1 -> 'low'
            assert compute_risk("scripts/ops_data_portal.py", "XS") == "low"

    def test_unknown_effort_uses_fallback_scale(self) -> None:
        """Unknown effort label falls back to S=1.0."""
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock("")),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            result = compute_risk("file.py", "UNKNOWN")
        assert result in ("low", "medium", "high")

    def test_max_complexity_used_from_multiple_blocks(self) -> None:
        """Takes the maximum cyclomatic complexity across all blocks in the file."""
        radon_out = "file.py\n    F 1:0 a - A (2)\n    F 10:0 b - C (12)\n    F 20:0 c - A (1)\n"
        with (
            patch("scripts.ops_data_portal.subprocess.run", return_value=self._radon_mock(radon_out)),
            patch("scripts.ops_data_portal.ET.parse", side_effect=OSError("absent")),
        ):
            from scripts.ops_data_portal import compute_risk

            # C=12, S=0.1 (XS), M=0.1 -> R=(12*0.1)/0.1=12 -> medium
            assert compute_risk("file.py", "XS") == "medium"


class TestPipelineConsolidation:
    """Tests for the ops pipeline consolidation changes (Decision 69 / Decision 84)."""

    def test_update_rec_reads_from_reader_not_jsonl(self, tmp_path: Path) -> None:
        """update_rec() calls _fetch_rec_from_reader (warehouse reader) not a local JSONL read."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        existing = dict(_VALID_FIELDS, id="rec-042", status="open")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=existing) as mock_fetch,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            update_rec("rec-042", {"status": "closed"})

        mock_fetch.assert_called_once_with("rec-042", profile=None)

    def test_update_rec_refreshes_cache_incrementally(self, tmp_path: Path) -> None:
        """update_rec() refreshes the cache via an incremental upsert -- no full-table reader pull (D4)."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        existing = dict(_VALID_FIELDS, id="rec-042", status="open")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=existing),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True, "ulid": "ulid-test-0001"}),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
            patch("scripts.sync_ops._pull_single_table") as mock_pull,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            update_rec("rec-042", {"status": "closed"})

        # Neon-egress-reduction D4: the per-write full-table resync is gone.
        mock_sync.assert_not_called()
        mock_pull.assert_not_called()
        rows = [json.loads(line) for line in recs_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(r["id"] == "rec-042" and r["status"] == "closed" for r in rows)

    def test_file_rec_refreshes_cache_incrementally(self, tmp_path: Path) -> None:
        """file_rec() refreshes the cache via an incremental upsert -- no full-table reader pull (D4)."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-700", "ulid": "ulid-test-0001"}),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
            patch("scripts.sync_ops._pull_single_table") as mock_pull,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(dict(_VALID_FIELDS))

        mock_sync.assert_not_called()
        mock_pull.assert_not_called()
        rows = [json.loads(line) for line in recs_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(r["id"] == "rec-700" for r in rows)

    def test_sync_returns_pull_only_report(self) -> None:
        """sync() returns {'pulled': ...} only -- no drain/compact/view-refresh keys (Decision 84 I-4)."""
        with patch("scripts.sync_ops._pull_single_table", return_value=10):
            from scripts.ops_data_portal import sync

            result = sync(["ops_recommendations"])

        assert result == {"pulled": {"ops_recommendations": 10}}

    def test_sync_defaults_to_all_migrated_tables(self) -> None:
        """sync() with no args pulls recs, decisions, and the priority queue."""
        pulled: list[str] = []
        with patch("scripts.sync_ops._pull_single_table", side_effect=lambda t: pulled.append(t) or 1):
            from scripts.ops_data_portal import sync

            result = sync()

        assert pulled == ["ops_recommendations", "ops_decisions", "ops_priority_queue"]
        assert result == {"pulled": {t: 1 for t in pulled}}

    def test_update_rec_raises_on_reader_unreachable(self, tmp_path: Path) -> None:
        """update_rec() propagates RuntimeError when _fetch_rec_from_reader raises."""
        with (
            patch(
                "scripts.ops_data_portal._fetch_rec_from_reader",
                side_effect=RuntimeError("reader unreachable"),
            ),
        ):
            from scripts.ops_data_portal import update_rec

            with pytest.raises(RuntimeError, match="reader unreachable"):
                update_rec("rec-042", {"status": "closed"})


class TestMigrationParams:
    """Tests for the private migration params on file_rec / file_decision."""

    def test_file_rec_migration_int_id_pads_and_uses_write_ops(self, tmp_path: Path) -> None:
        """_migration_int_id preserves the historical id via a caller-keyed write_ops upsert."""
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS), _migration_int_id=5, _migration_mode=True, _skip_sync=True)

        assert result == "rec-005"
        _, call_rec = mock_dl_write.call_args[0]
        assert call_rec["id"] == "rec-005"
        assert mock_dl_write.call_args.kwargs["action"] == "write_ops"
        assert "idempotency_ulid" not in mock_dl_write.call_args.kwargs

    def test_file_rec_skip_sync_uses_append_not_upsert(self, tmp_path: Path) -> None:
        """_skip_sync=True appends (bulk path; final sync reconciles); the default path upserts (D4)."""
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-700"}),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
            patch("scripts.ops_portal.cache._append_to_local_jsonl") as mock_append,
            patch("scripts.sync_ops.upsert_cache_row") as mock_upsert,
        ):
            from scripts.ops_data_portal import file_rec

            # Bulk path: append only, no per-row upsert and never the full-table _sync_table.
            file_rec(dict(_VALID_FIELDS), _skip_sync=True)
            mock_append.assert_called_once()
            mock_upsert.assert_not_called()
            mock_sync.assert_not_called()

            # Default path: incremental upsert, no append and no full-table _sync_table (D4).
            mock_append.reset_mock()
            file_rec(dict(_VALID_FIELDS))
            mock_upsert.assert_called_once()
            mock_append.assert_not_called()
            mock_sync.assert_not_called()

    def test_file_rec_migration_mode_bypasses_content_validators(self, tmp_path: Path) -> None:
        """_migration_mode lets a historical row that fails content rules import; the schema still applies."""
        thin = {**_VALID_FIELDS, "context": "too short", "acceptance": ""}

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import file_rec

            # Without migration mode the short context is rejected.
            with pytest.raises(ValueError, match="context"):
                file_rec(dict(thin), _migration_int_id=701)

            # With migration mode it imports.
            assert file_rec(dict(thin), _migration_int_id=701, _migration_mode=True, _skip_sync=True) == "rec-701"

    def test_file_decision_skip_sync_suppresses_sync_table(self, tmp_path: Path) -> None:
        """_skip_sync=True on file_decision defers the per-row flush."""
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", tmp_path / "dec.jsonl"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import file_decision

            file_decision({"title": "d", "status": "open", "decision_id": 77}, _skip_sync=True)
            mock_sync.assert_not_called()


class TestFetchRecFromReader:
    """Tests for _fetch_rec_from_reader -- the rec_by_id named verb (Decision 84 I-3)."""

    _REC_ROW = {
        "id": "rec-042",
        "title": "Test rec",
        "file": "scripts/ops_data_portal.py",
        "context": "ctx",
        "acceptance": "grep -q x y",
        "effort": "XS",
        "priority": "Low",
        "source": "planning",
        "risk": "low",
        "status": "open",
        "automatable": True,
        "last_updated_timestamp": "2026-05-01T00:00:00Z",
        "created_timestamp": "2026-05-01T00:00:00Z",
    }

    def test_named_verb_returns_record(self) -> None:
        """Reader named('rec_by_id', id=...) success -> returns sanitised record."""
        reader = MagicMock()
        reader.named.return_value = [dict(self._REC_ROW)]

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_rec_from_reader

            result = _fetch_rec_from_reader("rec-042")

        assert result is not None
        assert result["id"] == "rec-042"
        assert result["status"] == "open"
        reader.named.assert_called_once_with("rec_by_id", id="rec-042")

    def test_reader_failure_loud_fails(self) -> None:
        """Reader failure propagates -- no Athena fallback, no local-cache fallback (Decision 69)."""
        reader = MagicMock()
        reader.named.side_effect = RuntimeError("ducklake_reader 'named_read' failed (HTTP 500)")

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_rec_from_reader

            with pytest.raises(RuntimeError, match="ducklake_reader"):
                _fetch_rec_from_reader("rec-042")

    def test_reader_returns_none_when_row_not_found(self) -> None:
        """Reader returns empty list -> function returns None."""
        reader = MagicMock()
        reader.named.return_value = []

        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            from scripts.ops_data_portal import _fetch_rec_from_reader

            result = _fetch_rec_from_reader("rec-999")

        assert result is None

    def test_invalid_rec_id_raises_value_error(self) -> None:
        """Malformed rec_id raises ValueError before any reader call (security guard)."""
        from scripts.ops_data_portal import _fetch_rec_from_reader

        with pytest.raises(ValueError, match="invalid rec_id"):
            _fetch_rec_from_reader("'; DROP TABLE ops_recommendations; --")


class TestDuckLakeTransportHelpers:
    """Coverage for the DuckLake transport helpers: URL resolve, projection, SigV4 write, retry."""

    def test_resolve_writer_url_env(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("DUCKLAKE_WRITER_URL", "https://writer.example/")
        assert p._resolve_writer_url() == "https://writer.example"

    def test_resolve_writer_url_loud_fail(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p
        import src.common.iceberg_reader as ir

        monkeypatch.delenv("DUCKLAKE_WRITER_URL", raising=False)
        monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        # Patch at the source module so the lazy import inside _resolve_writer_url picks them up.
        monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", lambda *a, **k: None)
        monkeypatch.setattr(ir, "_resolve_function_url_via_api", lambda *a, **k: None)
        with pytest.raises(RuntimeError, match="DUCKLAKE_WRITER_URL not set"):
            p._resolve_writer_url()

    def test_resolve_writer_url_api_fallback(self, monkeypatch) -> None:
        """When env + terraform are unavailable, the writer URL resolves via GetFunctionUrlConfig (CI case)."""
        import scripts.ops_data_portal as p
        import src.common.iceberg_reader as ir

        monkeypatch.delenv("DUCKLAKE_WRITER_URL", raising=False)
        monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        # Patch at the source module so the lazy import inside _resolve_writer_url picks them up.
        monkeypatch.setattr(ir, "_resolve_function_url_via_ssm", lambda *a, **k: None)
        monkeypatch.setattr(ir, "_resolve_function_url_via_api", lambda name, **kw: "https://api.example/")
        assert p._resolve_writer_url() == "https://api.example"

    def test_project_ops_record_drops_derived_and_unknown(self) -> None:
        import scripts.ops_data_portal as p

        rec = {
            "id": "rec-1",
            "status": "open",
            "title": "t",
            "ulid": "01X",  # derived -> dropped
            "created_timestamp": "2026-01-01",  # derived -> dropped
            "last_updated_timestamp": "2026-01-01",  # derived -> dropped
            "date": "2026-01-01",  # unknown -> dropped
        }
        projected = p._project_ops_record("ops_recommendations", rec)
        assert "ulid" not in projected and "created_timestamp" not in projected and "date" not in projected
        assert projected["id"] == "rec-1" and projected["status"] == "open" and projected["title"] == "t"

    def test_ducklake_write_sigv4_success(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("DUCKLAKE_WRITER_URL", "https://writer.example/")
        bodies = _patch_writer_transport(monkeypatch, [_FakeResp(200, {"ok": True, "key": "rec-1"})])

        out = p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "open"}, action="write_ops")
        assert out["ok"] is True
        assert bodies[0]["action"] == "write_ops"
        assert bodies[0]["table"] == "ops_recommendations"
        assert "idempotency_ulid" not in bodies[0]

    def test_ducklake_write_carries_idempotency_ulid(self, monkeypatch) -> None:
        """When the caller passes idempotency_ulid it is included in the request payload."""
        import scripts.ops_data_portal as p

        monkeypatch.setenv("DUCKLAKE_WRITER_URL", "https://writer.example/")
        bodies = _patch_writer_transport(monkeypatch, [_FakeResp(200, {"key": "rec-9"})])

        out = p._ducklake_write(
            "ops_recommendations", {"status": "open", "title": "t"}, action="file_ops", idempotency_ulid="abc123"
        )
        assert out["key"] == "rec-9"
        assert bodies[0]["idempotency_ulid"] == "abc123"
        assert bodies[0]["action"] == "file_ops"

    def test_ducklake_write_referential_409_maps_to_runtimeerror(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        _patch_writer_transport(monkeypatch, [_FakeResp(409, text="absent")])
        with pytest.raises(RuntimeError, match="referential"):
            p._ducklake_write("ops_recommendations", {"id": "rec-x", "status": "closed"}, action="update_ops")

    def test_ducklake_write_schema_422_maps_to_valueerror(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        _patch_writer_transport(monkeypatch, [_FakeResp(422, text="bad field")])
        with pytest.raises(ValueError, match="schema-gate"):
            p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "open"}, action="write_ops")

    def test_ducklake_write_transient_503_retries_when_idempotent(self, monkeypatch) -> None:
        """A 503 (Neon cold-resume) retries when idempotency_ulid is set; the retry consumes the 200."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        sleeps: list = []
        bodies = _patch_writer_transport(
            monkeypatch,
            [_FakeResp(503, text="cold"), _FakeResp(200, {"key": "rec-77"})],
            sleeps=sleeps,
        )

        out = p._ducklake_write(
            "ops_recommendations", {"status": "open", "title": "t"}, action="file_ops", idempotency_ulid="u1"
        )
        assert out["key"] == "rec-77"
        assert len(bodies) == 2  # exactly one retry
        assert len(sleeps) == 1  # backed off once
        assert bodies[0] == bodies[1]  # the retried request is the identical idempotent payload

    def test_ducklake_write_transient_503_no_retry_without_idempotency(self, monkeypatch) -> None:
        """A non-idempotent write (write_ops without ULID is caller-keyed but file-path-unsafe) fails fast."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        bodies = _patch_writer_transport(monkeypatch, [_FakeResp(503, text="cold")])

        with pytest.raises(RuntimeError, match="HTTP 503"):
            p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "open"}, action="write_ops")
        assert len(bodies) == 1  # no retry attempted

    def test_ducklake_write_update_ops_retries_transient(self, monkeypatch) -> None:
        """update_ops is idempotent by id, so transient 5xx retries even without a ULID."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        sleeps: list = []
        bodies = _patch_writer_transport(
            monkeypatch, [_FakeResp(502, text="cold"), _FakeResp(200, {"ok": True})], sleeps=sleeps
        )

        out = p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "closed"}, action="update_ops")
        assert out == {"ok": True}
        assert len(bodies) == 2

    def test_ducklake_write_transient_exhausts_after_three_attempts(self, monkeypatch) -> None:
        """Three transient failures exhaust the retry budget and raise loudly."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_writer_transport_mod, "_resolve_writer_url", lambda *a, **k: "https://w.example")
        bodies = _patch_writer_transport(
            monkeypatch,
            [_FakeResp(503, text="cold")] * 3,
            sleeps=[],
        )

        with pytest.raises(RuntimeError, match="HTTP 503"):
            p._ducklake_write(
                "ops_recommendations", {"status": "open", "title": "t"}, action="file_ops", idempotency_ulid="u2"
            )
        assert len(bodies) == 3


class TestSyncTable:
    """_sync_table / sync are a pure reader cache-pull (no drain, no compaction)."""

    def test_sync_table_pulls_single_table(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        calls: list[str] = []
        monkeypatch.setattr("scripts.sync_ops._pull_single_table", lambda t: calls.append(t) or 0)
        p._sync_table("ops_recommendations")
        p._sync_table("ops_decisions")
        assert calls == ["ops_recommendations", "ops_decisions"]


class TestSelftests:
    """--selftest-read / --selftest-roundtrip portal probes (VP14/15)."""

    def test_selftest_read_reports_ducklake(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        class _Reader:
            def current_state(self, table, **kw):
                return [{"id": "rec-1"}]

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        out = p.selftest_read()
        assert out["backend"] == "ducklake" and out["row_count"] == 1 and out["sample_id"] == "rec-1"

    def test_selftest_roundtrip_ducklake(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        written: dict = {}
        monkeypatch.setattr(
            _maintenance_ops_mod, "_ducklake_write", lambda t, r, *, action, profile=None: written.update(id=r["id"])
        )

        class _Reader:
            def current_state(self, table, *, row_filter=None, **kw):
                return [{"id": written["id"]}]

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        out = p.selftest_roundtrip()
        assert out["read_back"] is True and out["backend"] == "ducklake"

    def test_selftest_roundtrip_loud_fails_when_not_read_back(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setattr(_maintenance_ops_mod, "_ducklake_write", lambda *a, **k: {"ok": True})

        class _Reader:
            def current_state(self, table, *, row_filter=None, **kw):
                return []

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        with pytest.raises(RuntimeError, match="read-back"):
            p.selftest_roundtrip()


_CI_RCA_FIELDS = {
    **_VALID_FIELDS,
    "source": "ci_rca",
    "context": ("CI RCA test rec with sufficient length to satisfy the 80-char minimum for the legacy context column field."),
}

_VALID_CONTEXT_V2 = {
    "schema_version": 1,
    "proximate_cause": (
        "validate_sloc_limits() raised: scripts/product_roadmap.py is 810 SLOC, exceeds 500 limit "
        "(Decision 43, no complexity-waiver header found in first 10 lines)."
    ),
    "why_chain": [
        "The file was committed at over 500 SLOC in a single PR with no incremental breakpoint.",
        "No local --pre check fired because validate_sloc_limits() is presubmit-tier only.",
        "The validate_sloc_limits() check was placed in the presubmit tier not --pre despite being O(lines); "
        "this tier placement defect is the gap at scripts/validate.py:2294.",
    ],
    "detection_gap": {
        "earliest_viable_gate": "pre",
        "actual_gate_that_caught_it": "CI",
        "gap_explanation": (
            "validate_sloc_limits() gates on scope=='all' at scripts/validate.py:2294, unreachable from "
            "--pre (exits at scripts/validate.py:2284). Gap is tier-placement, not logic."
        ),
    },
    "recurrence_class": "instance_of_known_pattern",
    "corrective_action": (
        "Add a complexity-waiver header OR refactor the module below 500 SLOC to satisfy the "
        "validate_sloc_limits() check in scripts/validate.py and unblock CI."
    ),
    "preventive_action": (
        "Promote validate_sloc_limits() to the --pre tier at scripts/validate.py so the check fires "
        "during local development and prevents the same tier-placement failure mode in future PRs. "
        "Additionally gate new check additions: require a documented tier-placement rationale."
    ),
}


class TestCiRcaSchemaEnforcement:
    """Tests for the CI_RCA_STRICT_MODE feature flag, CiRcaContext schema, and file_rec warn-mode validation."""

    def setup_method(self) -> None:
        import scripts.ops_data_portal as p

        p._ci_rca_strict_mode_cache = None  # reset the module-level cache before each test

    def test_flag_default_is_warn(self, tmp_path: Path) -> None:
        """get_ci_rca_strict_mode() returns 'warn' when the key is absent or file is missing."""
        import scripts.ops_data_portal as p

        with patch.object(p, "_FEATURE_FLAGS_YAML", tmp_path / "nonexistent.yaml"):
            result = p.get_ci_rca_strict_mode()
        assert result == "warn"

    def test_flag_reads_yaml(self, tmp_path: Path) -> None:
        """get_ci_rca_strict_mode() reads CI_RCA_STRICT_MODE from the feature flags YAML."""
        import scripts.ops_data_portal as p

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: warn\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            result = p.get_ci_rca_strict_mode()
        assert result == "warn"

    def test_flag_rejects_unknown_value(self, tmp_path: Path) -> None:
        """get_ci_rca_strict_mode() raises ValueError for unrecognised flag values."""
        import scripts.ops_data_portal as p

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: debug\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_STRICT_MODE"):
                p.get_ci_rca_strict_mode()

    def test_guidance_returns_schema(self) -> None:
        """get_rec_write_guidance('ci_rca') returns all six CiRcaContext schema fields."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca")
        assert "context_v2_json" in guidance
        schema_fields = guidance["context_v2_json"]["schema_fields"]
        for field in [
            "proximate_cause",
            "why_chain",
            "detection_gap",
            "recurrence_class",
            "corrective_action",
            "preventive_action",
        ]:
            assert field in schema_fields, f"schema_fields missing {field!r}"

    def test_valid_context_v2_passes(self, tmp_path: Path) -> None:
        """file_rec(source=ci_rca, context_v2_json=<valid>) succeeds and persists context_v2_json."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9001"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=dict(_VALID_CONTEXT_V2))
        assert rec_id == "rec-9001"
        entry = json.loads(recs_file.read_text(encoding="utf-8").splitlines()[0])
        assert "context_v2_json" in entry
        stored = json.loads(entry["context_v2_json"])
        assert stored["schema_version"] == 1

    def test_deficient_why_chain_warns_not_raises(self, tmp_path: Path, caplog) -> None:
        """In warn mode a deficient why_chain logs a warning and does NOT raise."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        deficient_ctx = {**_VALID_CONTEXT_V2, "why_chain": ["short", "also short", "still short"]}
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: warn\n", encoding="utf-8")
        with (
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9002"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=deficient_ctx)
        assert rec_id == "rec-9002"
        assert any("CI_RCA_STRICT_MODE=warn" in r.message for r in caplog.records)

    def test_legacy_free_text_passes_with_deprecation_warning(self, tmp_path: Path, caplog) -> None:
        """file_rec(source=ci_rca) with no context_v2_json logs a deprecation warning and passes."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9003"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS))
        assert rec_id == "rec-9003"
        assert any("legacy free-text" in r.message for r in caplog.records)

    def test_strict_mode_raises_on_deficiency(self, tmp_path: Path) -> None:
        """In strict mode a deficient why_chain raises ValueError (branch exists but inert by default)."""
        import scripts.ops_data_portal as p

        deficient_ctx = {**_VALID_CONTEXT_V2, "why_chain": ["short", "also short", "still short"]}
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_STRICT_MODE=strict"):
                p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=deficient_ctx)

    def test_reconcile_table_columns_rerun_safety(self) -> None:
        """reconcile_table_columns on a table that already has context_v2_json is a no-op.

        Uses real duckdb in-memory tables with CATALOG_ALIAS patched to 'memory' so that
        information_schema queries and ALTER TABLE work without a DuckLake catalog.
        Proves introspection-based idempotency: a second call adds nothing.
        """
        semantics = load_field_semantics()
        spec = resolve_table_spec("ops_recommendations", semantics)

        con = duckdb.connect(":memory:")

        # Create both tables with all spec columns (including context_v2_json) up front.
        # Note: BIGINT[] and VARCHAR[] must be written as DuckDB array types.
        def _safe_ddl_type(sql_type: str) -> str:
            return sql_type.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ")

        cols_ddl = ", ".join(f"{col} {_safe_ddl_type(spec.fields[col].get('sql_type', 'VARCHAR'))}" for col in spec.fields)
        con.execute(f"CREATE TABLE ops_recommendations_history ({cols_ddl})")
        con.execute(f"CREATE TABLE ops_recommendations_current ({cols_ddl})")

        # Patch CATALOG_ALIAS to 'memory' so reconcile_table_columns resolves table_fq
        # as 'memory.ops_recommendations_*' -- valid in a plain DuckDB in-memory connection.
        with patch("src.common.ducklake_runtime.CATALOG_ALIAS", "memory"):
            result1 = rt.reconcile_table_columns(con, table="ops_recommendations")
            result2 = rt.reconcile_table_columns(con, table="ops_recommendations")

        # First call: context_v2_json is already present -- nothing to add.
        assert result1["added_history"] == []
        assert result1["added_current"] == []
        # Second call: idempotent no-op.
        assert result2["added_history"] == []
        assert result2["added_current"] == []
        con.close()

    def test_guidance_source_ci_rca_returns_schema(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --guidance --source ci_rca emits the context_v2_json schema_fields block."""
        from scripts.ops_data_portal import main

        rc = main(["--guidance", "--source", "ci_rca"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "context_v2_json" in out
        assert "schema_fields" in out
        assert "proximate_cause" in out

    def test_file_rec_context_v2_json_valid_routes_to_file_rec(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec --context-v2-json with valid JSON parses and routes to file_rec(context_v2_json=...)."""
        import json as _json

        from scripts.ops_data_portal import main

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-cv2-1"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rc = main(
                [
                    "--file-rec",
                    "--source",
                    "ci_rca",
                    "--priority",
                    "Critical",
                    "--risk",
                    "medium",
                    "--effort",
                    "S",
                    "--file",
                    "scripts/validate.py",
                    "--title",
                    "validate_sloc_limits missed in pre tier",
                    "--context",
                    "validate_sloc_limits() raised on scripts/product_roadmap.py: 810 SLOC exceeds 500 limit. "
                    "CI step 'validate' failed; resource: scripts/product_roadmap.py.",
                    "--acceptance",
                    "grep -q validate_sloc_limits scripts/validate.py",
                    "--context-v2-json",
                    _json.dumps(_VALID_CONTEXT_V2),
                ]
            )
        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-cv2-1" in captured.out
        entry = _json.loads(recs_file.read_text(encoding="utf-8").splitlines()[0])
        assert "context_v2_json" in entry
        stored = _json.loads(entry["context_v2_json"])
        assert stored["schema_version"] == 1

    def test_file_rec_context_v2_json_invalid_json_exits_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec --context-v2-json with malformed JSON exits 1 and files nothing."""
        from scripts.ops_data_portal import main

        rc = main(
            [
                "--file-rec",
                "--source",
                "ci_rca",
                "--priority",
                "Critical",
                "--risk",
                "low",
                "--effort",
                "XS",
                "--file",
                "scripts/validate.py",
                "--title",
                "Test invalid JSON path",
                "--context",
                "validate_sloc_limits() raised: file is over limit. CI step failed; resource: scripts/foo.py.",
                "--acceptance",
                "grep -q validate scripts/validate.py",
                "--context-v2-json",
                "{not: valid json",
            ]
        )
        assert rc == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err
        assert "not valid JSON" in captured.err

    def test_file_rec_ci_rca_legacy_path_warns_and_files(self, tmp_path: Path, caplog, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec source=ci_rca without --context-v2-json still files in warn mode."""
        import logging

        from scripts.ops_data_portal import main

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-legacy-1"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            rc = main(
                [
                    "--file-rec",
                    "--source",
                    "ci_rca",
                    "--priority",
                    "Critical",
                    "--risk",
                    "low",
                    "--effort",
                    "XS",
                    "--file",
                    "scripts/validate.py",
                    "--title",
                    "Legacy ci_rca path test",
                    "--context",
                    "validate_sloc_limits() raised: file is over 500 SLOC. CI step failed; resource: scripts/foo.py.",
                    "--acceptance",
                    "grep -q validate scripts/validate.py",
                ]
            )
        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-legacy-1" in captured.out
        assert any("legacy free-text" in r.message for r in caplog.records)

    @pytest.mark.integration
    @pytest.mark.enable_socket()
    def test_context_v2_roundtrip_live(self) -> None:
        """Live roundtrip: file a ci_rca rec with context_v2_json, read back, assert persisted, close.

        Skipped unless RUN_LIVE_DUCKLAKE=1 (requires portal connectivity + production DuckLake).
        """
        if not os.environ.get("RUN_LIVE_DUCKLAKE"):
            pytest.skip("set RUN_LIVE_DUCKLAKE=1 to run live DuckLake roundtrip")

        import scripts.ops_data_portal as p

        live_fields = {
            **_CI_RCA_FIELDS,
            "title": "test_context_v2_roundtrip_live (T1.13 VP10)",
            "context": (
                "Live roundtrip test for context_v2_json persistence filed by TestCiRcaSchemaEnforcement. "
                "This rec will be immediately closed via update_rec (self-cleaning, Decision 70)."
            ),
        }
        rec_id = p.file_rec(live_fields, context_v2_json=dict(_VALID_CONTEXT_V2))
        assert rec_id.startswith("rec-"), f"Expected rec-NNN, got {rec_id!r}"

        # Read back via reader and assert context_v2_json was persisted.
        row = p._fetch_rec_from_reader(rec_id)
        assert row is not None, f"{rec_id} not found after filing"
        ctx_v2 = row.get("context_v2_json")
        assert ctx_v2 is not None, f"context_v2_json not persisted for {rec_id}: {row}"
        if isinstance(ctx_v2, str):
            ctx_v2 = json.loads(ctx_v2)
        assert ctx_v2.get("schema_version") == 1
        legacy_ctx = row.get("context", "")
        assert len((legacy_ctx or "").strip()) >= 80, f"legacy context too short: {legacy_ctx!r}"

        # Close the test rec (self-cleaning, Decision 70).
        closed = p.update_rec(
            rec_id,
            {
                "status": "closed",
                "resolution": "test_context_v2_roundtrip_live self-cleaning close (T1.13 VP10)",
            },
        )
        assert closed is True, f"update_rec failed for {rec_id}"


class TestClosedBoundaryNoAthenaFallback:
    """A reader failure must NOT fall back to Athena (OQ.7 / Decision 84 I-1)."""

    def test_fetch_rec_no_athena_fallback(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        class _Reader:
            def named(self, verb, **params):
                raise RuntimeError("reader down")

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        # boto3 must never be touched (no Athena escape hatch). Make it explode if constructed.
        import boto3

        monkeypatch.setattr(boto3, "Session", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Athena fallback used")))
        with pytest.raises(RuntimeError, match="reader down"):
            p._fetch_rec_from_reader("rec-1")


_DISPUTE_FIELDS = {
    **_VALID_FIELDS,
    "source": "ci_rca_evidence_dispute",
    "file": "scripts/ops_data_portal.py",
    "context": "",
}

_VALID_DISPUTE_PAYLOAD = {
    "parent_rec_id": "rec-1234",
    "disputed_field": "earliest_viable_gate",
    "agent_value": "pre",
    "bundle_value": "CI",
    "evidence_for_dispute": (
        "scripts/collect_ci_evidence.py:142 shows earliest_viable_gate is derived from validate.py --pre "
        "output; the agent value 'pre' is wrong because the check is guarded by a CI-only env var at "
        "validate.py:87, making 'pre' impossible."
    ),
}


class TestCiRcaEvidenceDispute:
    """Tests for the CiRcaEvidenceDispute schema and the Section-4 check-8 carve-out in file_rec()."""

    def test_valid_payload_passes(self) -> None:
        """CiRcaEvidenceDispute.model_validate accepts a well-formed dispute payload."""
        from scripts.ops_data_portal import CiRcaEvidenceDispute

        result = CiRcaEvidenceDispute.model_validate(_VALID_DISPUTE_PAYLOAD)
        assert result.parent_rec_id == "rec-1234"
        assert result.disputed_field == "earliest_viable_gate"

    def test_bad_parent_rec_id_raises(self) -> None:
        """A parent_rec_id that does not match ^rec-\\d+$ raises ValidationError."""
        from scripts.ops_data_portal import CiRcaEvidenceDispute

        bad = {**_VALID_DISPUTE_PAYLOAD, "parent_rec_id": "REC-1234"}
        with pytest.raises(ValidationError):
            CiRcaEvidenceDispute.model_validate(bad)

    def test_out_of_enum_disputed_field_raises(self) -> None:
        """A disputed_field not in {earliest_viable_gate, actual_gate_that_caught_it} raises ValidationError."""
        from scripts.ops_data_portal import CiRcaEvidenceDispute

        bad = {**_VALID_DISPUTE_PAYLOAD, "disputed_field": "gap_explanation"}
        with pytest.raises(ValidationError):
            CiRcaEvidenceDispute.model_validate(bad)

    def test_too_short_evidence_raises(self) -> None:
        """evidence_for_dispute shorter than 120 chars raises ValidationError."""
        from scripts.ops_data_portal import CiRcaEvidenceDispute

        bad = {**_VALID_DISPUTE_PAYLOAD, "evidence_for_dispute": "Too short."}
        with pytest.raises(ValidationError):
            CiRcaEvidenceDispute.model_validate(bad)

    def test_both_disputed_field_values_accepted(self) -> None:
        """All allowed disputed_field enum values pass schema validation (incl. failure_category)."""
        from scripts.ops_data_portal import CiRcaEvidenceDispute

        for value in ("earliest_viable_gate", "actual_gate_that_caught_it", "failure_category"):
            payload = {**_VALID_DISPUTE_PAYLOAD, "disputed_field": value}
            result = CiRcaEvidenceDispute.model_validate(payload)
            assert result.disputed_field == value

    def test_file_rec_carve_out_bypasses_ci_rca_checks(self, tmp_path: Path) -> None:
        """file_rec(source=ci_rca_evidence_dispute) bypasses ci_rca checks 1-7: no why_chain, no source_file required."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-5001"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rec_id = p.file_rec(dict(_DISPUTE_FIELDS), context_v2_json=_VALID_DISPUTE_PAYLOAD)
        assert rec_id == "rec-5001"
        entry = json.loads(recs_file.read_text(encoding="utf-8").splitlines()[0])
        assert "context_v2_json" in entry
        stored = json.loads(entry["context_v2_json"])
        assert stored["parent_rec_id"] == "rec-1234"

    def test_file_rec_carve_out_no_ci_rca_context_required(self, tmp_path: Path) -> None:
        """Dispute rec filed without CiRcaContext fields (no why_chain, detection_gap, etc.) does not raise."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-5002"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rec_id = p.file_rec(dict(_DISPUTE_FIELDS), context_v2_json=_VALID_DISPUTE_PAYLOAD)
        assert rec_id == "rec-5002"

    def test_file_rec_malformed_dispute_hard_raises_in_warn_mode(self, tmp_path: Path) -> None:
        """Malformed dispute payload raises ValueError even when CI_RCA_STRICT_MODE=warn (mode-independent)."""
        import scripts.ops_data_portal as p

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: warn\n", encoding="utf-8")
        bad_payload = {**_VALID_DISPUTE_PAYLOAD, "disputed_field": "invalid_field_name"}
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="ci_rca_evidence_dispute"):
                p.file_rec(dict(_DISPUTE_FIELDS), context_v2_json=bad_payload)

    def test_file_rec_dispute_missing_context_v2_raises(self) -> None:
        """source=ci_rca_evidence_dispute without context_v2_json raises ValueError."""
        import scripts.ops_data_portal as p

        with pytest.raises(ValueError, match="context_v2_json"):
            p.file_rec(dict(_DISPUTE_FIELDS))

    def test_write_guidance_returns_all_five_dispute_fields(self) -> None:
        """get_rec_write_guidance(source='ci_rca_evidence_dispute') returns all five dispute fields as top-level keys."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca_evidence_dispute")
        for field in ("parent_rec_id", "disputed_field", "agent_value", "bundle_value", "evidence_for_dispute"):
            assert field in guidance, f"guidance missing top-level key {field!r}"
            assert "description" in guidance[field], f"guidance[{field!r}] missing 'description'"
            assert "semantics" in guidance[field], f"guidance[{field!r}] missing 'semantics'"

    def test_dispute_source_registered(self) -> None:
        """validate_source('ci_rca_evidence_dispute') does not raise -- the source is registered."""
        from scripts.executor.rec_write_guidance import validate_source

        validate_source("ci_rca_evidence_dispute")  # should not raise


class TestCiRcaCrossCheckSpine:
    """c10: _run_ci_rca_cross_check() and _load_and_verify_bundle() contract tests."""

    def _make_bundle(self, tmp_path, **overrides):
        """Write a valid bundle JSON to tmp_path/logs/.ci-rca-evidence-pending/<sha>.json."""
        import hashlib as _hashlib
        import json as _json

        bundle_data = {
            "earliest_viable_gate": "pre",
            "escape_mode": "tier_misplaced",
            "vacuous_pass": False,
        }
        bundle_data.update(overrides)
        payload = {k: v for k, v in bundle_data.items() if k != "sha256"}
        sha = _hashlib.sha256(
            _json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        bundle_data["sha256"] = sha
        pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{sha}.json").write_bytes(
            _json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        )
        return sha, bundle_data

    def _ctx_v2(self, **detection_gap_overrides):
        """Return a minimal valid context_v2_json dict."""
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": "test gap explanation with enough chars for the field",
        }
        dg.update(detection_gap_overrides)
        return {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }

    def test_no_evidence_bundle_ref_skips_cross_check(self, tmp_path):
        """Cross-check is skipped when evidence_bundle_ref is absent -- no issues raised."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        p._run_ci_rca_cross_check(ctx)  # should not raise

    def test_bundle_not_found_skips_cross_check(self, tmp_path):
        """Cross-check is skipped when the bundle file is not found locally."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # should not raise

    def test_sha256_mismatch_always_loud_fails(self, tmp_path):
        """SHA-256 mismatch raises ValueError regardless of CI_RCA_STRICT_MODE."""
        import json as _json

        import scripts.ops_data_portal as p

        sha = "a" * 64
        pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{sha}.json").write_bytes(
            _json.dumps({"earliest_viable_gate": "pre", "sha256": sha}, sort_keys=True, separators=(",", ":")).encode()
        )
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            with pytest.raises(ValueError, match="SHA-256 mismatch"):
                p._run_ci_rca_cross_check(ctx)

    def test_check1_bundle_undetermined_agent_must_mirror(self, tmp_path):
        """Check-1: bundle.earliest_viable_gate='undetermined' but agent set 'pre' -> warn/raise."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path, earliest_viable_gate="undetermined")
        ctx = self._ctx_v2(earliest_viable_gate="pre")
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-1"):
                p._run_ci_rca_cross_check(ctx)

    def test_check2_bundle_wins_on_evg_mismatch(self, tmp_path):
        """Check-2: agent earliest_viable_gate differs from bundle -> warn/raise."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path, earliest_viable_gate="CI")
        ctx = self._ctx_v2(earliest_viable_gate="pre")
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-2"):
                p._run_ci_rca_cross_check(ctx)

    def test_check3_escape_mode_bundle_wins(self, tmp_path):
        """Check-3: agent escape_mode differs from bundle -> warn/raise."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path, escape_mode="no_premerge_gate_by_design")
        ctx = self._ctx_v2()
        ctx["detection_gap"]["escape_mode"] = "tier_misplaced"
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-3"):
                p._run_ci_rca_cross_check(ctx)

    def test_check4_vacuous_pass_author_discipline_rejection(self, tmp_path):
        """Check-4: vacuous_pass=true + author-discipline attribution -> warn/raise."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path, vacuous_pass=True, escape_mode="undetermined")
        ctx = self._ctx_v2()
        ctx["detection_gap"]["gap_explanation"] = "author did not run the tests before merging"
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-4"):
                p._run_ci_rca_cross_check(ctx)

    def test_matching_values_no_issues(self, tmp_path):
        """When agent mirrors the bundle, no warnings or raises occur."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path, earliest_viable_gate="pre", escape_mode="tier_misplaced", vacuous_pass=False)
        ctx = self._ctx_v2(earliest_viable_gate="pre")
        ctx["detection_gap"]["escape_mode"] = "tier_misplaced"
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # must not raise

    def test_emit_dir_reachable_when_absent_from_pending_dir(self, tmp_path, monkeypatch):
        """CIRCA-01: a bundle present ONLY in CI_RCA_BUNDLE_EMIT_DIR (absent from the pending
        dir) is still reachable -- a deliberate earliest_viable_gate mismatch stamps
        cross_check_check_2 in warn mode and raises ValueError in strict mode.
        """
        import hashlib as _hashlib
        import json as _json

        import scripts.ops_data_portal as p

        emit_dir = tmp_path / "emit"
        emit_dir.mkdir(parents=True, exist_ok=True)
        bundle_data = {"earliest_viable_gate": "CI", "escape_mode": "tier_misplaced", "vacuous_pass": False}
        payload = {k: v for k, v in bundle_data.items() if k != "sha256"}
        sha = _hashlib.sha256(
            _json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        bundle_data["sha256"] = sha
        (emit_dir / f"{sha}.json").write_bytes(
            _json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        )
        # Confirm the pending dir genuinely has no bundle -- this is the CI layout under test.
        pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
        assert not (pending_dir / f"{sha}.json").exists()

        monkeypatch.setenv("CI_RCA_BUNDLE_EMIT_DIR", str(emit_dir))
        ctx = self._ctx_v2(earliest_viable_gate="pre")  # deliberately disagrees with bundle's "CI"
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # warn mode: must not raise
        assert ctx["warn_mode_reject"]["reasons"] == ["cross_check_check_2"]

        ctx2 = self._ctx_v2(earliest_viable_gate="pre")
        ctx2["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-2"):
                p._run_ci_rca_cross_check(ctx2)


class TestCiRcaFingerprintDedup:
    """CIRCA-03: find_open_ci_rca_rec_by_fingerprint(), the write-time backstop, and the
    bundle-derived fingerprint/failure_category stamp inside _run_ci_rca_cross_check()."""

    _FINGERPRINT = "a" * 64

    def _make_bundle(self, tmp_path, **overrides):
        import hashlib as _hashlib
        import json as _json

        bundle_data = {
            "earliest_viable_gate": "pre",
            "escape_mode": "tier_misplaced",
            "vacuous_pass": False,
            "fingerprint": self._FINGERPRINT,
            "failure_category": "sloc_violation",
        }
        bundle_data.update(overrides)
        payload = {k: v for k, v in bundle_data.items() if k != "sha256"}
        sha = _hashlib.sha256(
            _json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        bundle_data["sha256"] = sha
        pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{sha}.json").write_bytes(
            _json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        )
        return sha, bundle_data

    def _ctx_v2(self, **detection_gap_overrides):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": "test gap explanation with enough chars for the field",
        }
        dg.update(detection_gap_overrides)
        return {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }

    # -- find_open_ci_rca_rec_by_fingerprint --------------------------------------------------

    def test_hit_returns_matching_open_rec_id(self):
        import scripts.ops_data_portal as p

        rows = [
            {"id": "rec-1", "status": "closed", "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT})},
            {"id": "rec-2", "status": "open", "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT})},
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == "rec-2"
        reader.current_state.assert_called_once_with("ops_recommendations", row_filter="source = 'ci_rca'")

    def test_miss_returns_none(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.return_value = [
            {"id": "rec-3", "status": "open", "context_v2_json": json.dumps({"fingerprint": "b" * 64})}
        ]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    def test_no_rows_returns_none(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.return_value = []
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    def test_reader_unreachable_fails_open(self, caplog):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("ducklake_reader 'read_ops_current' failed (HTTP 503): ...")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with caplog.at_level(logging.WARNING):
                result = p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result is None
        assert any("reader unreachable" in rec.message.lower() for rec in caplog.records)

    def test_unexpected_reader_error_raises(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("boom -- unrelated to connectivity")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with pytest.raises(RuntimeError, match="boom"):
                p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT)

    def test_non_runtime_error_raises(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.side_effect = ValueError("bad row_filter")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with pytest.raises(ValueError, match="bad row_filter"):
                p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT)

    def test_malformed_context_v2_json_skipped_not_raised(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.return_value = [
            {"id": "rec-4", "status": "open", "context_v2_json": "not-json"},
            {"id": "rec-5", "status": "open", "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT})},
        ]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_open_ci_rca_rec_by_fingerprint(self._FINGERPRINT) == "rec-5"

    # -- bundle-derived stamp in _run_ci_rca_cross_check --------------------------------------

    def test_cross_check_stamps_fingerprint_and_failure_category(self, tmp_path: Path):
        import scripts.ops_data_portal as p

        sha, bundle_data = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)
        assert ctx["fingerprint"] == bundle_data["fingerprint"]
        assert ctx["failure_category"] == bundle_data["failure_category"]

    def test_cross_check_no_bundle_leaves_fingerprint_unset(self, tmp_path: Path):
        """No evidence_bundle_ref -> cross-check returns before any bundle load -- no stamp."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2(earliest_viable_gate="undetermined")
        ctx["rca_confidence"] = "undetermined"
        p._run_ci_rca_cross_check(ctx)
        assert "fingerprint" not in ctx

    # -- write-time backstop (file_rec) -------------------------------------------------------

    def test_file_rec_backstop_returns_existing_id_on_fingerprint_hit(self, tmp_path: Path, monkeypatch):
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value="rec-999") as mock_find,
            patch.object(p, "_ducklake_write") as mock_write,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-999"
        mock_find.assert_called_once_with(self._FINGERPRINT, profile=None)
        mock_write.assert_not_called()

    def test_file_rec_backstop_inserts_on_fingerprint_miss(self, tmp_path: Path, monkeypatch):
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value=None) as mock_find,
            patch.object(p, "_ducklake_write", return_value={"key": "rec-800"}) as mock_write,
            patch.object(p, "RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.sync_ops.upsert_cache_row"),
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-800"
        mock_find.assert_called_once()
        mock_write.assert_called_once()

    def test_file_rec_force_rca_bypasses_backstop(self, tmp_path: Path, monkeypatch):
        """CI_RCA_FORCE_RCA=true skips the dedup lookup entirely and always inserts."""
        import scripts.ops_data_portal as p

        monkeypatch.setenv("CI_RCA_FORCE_RCA", "true")
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint") as mock_find,
            patch.object(p, "_ducklake_write", return_value={"key": "rec-801"}),
            patch.object(p, "RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.sync_ops.upsert_cache_row"),
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-801"
        mock_find.assert_not_called()

    def test_file_rec_backstop_does_not_bump_occurrence(self, tmp_path: Path, monkeypatch):
        """The write-time backstop returns the existing id but never calls update_rec (no bump)."""
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value="rec-999"),
            patch.object(p, "update_rec") as mock_update,
        ):
            p.file_rec(dict(fields), context_v2_json=ctx)

        mock_update.assert_not_called()

    # -- schema: portal-derived fields live in context_v2_json, not a new column --------------

    def test_no_new_ops_recommendations_column(self):
        """fingerprint/failure_category/occurrence_count/last_seen are CiRcaContext fields,
        NOT Recommendation (ops_recommendations row) fields -- Decision 103 / 84 I-2."""
        from scripts.executor.jsonl_store import Recommendation

        rec_fields = set(Recommendation.model_fields)
        for name in ("fingerprint", "occurrence_count", "last_seen"):
            assert name not in rec_fields, f"{name} must not be a top-level ops_recommendations column"

    def test_ci_rca_context_carries_dedup_fields(self):
        from scripts.ops_data_portal import CiRcaContext

        fields = set(CiRcaContext.model_fields)
        assert {"fingerprint", "failure_category", "occurrence_count", "last_seen"} <= fields

    # -- bump_ci_rca_occurrence ----------------------------------------------------------------

    def test_bump_ci_rca_occurrence_increments_and_stamps_last_seen(self):
        import scripts.ops_data_portal as p

        existing_ctx = json.dumps({"fingerprint": self._FINGERPRINT, "occurrence_count": 1})
        with (
            patch.object(p, "_fetch_rec_from_reader", return_value={"id": "rec-9", "context_v2_json": existing_ctx}),
            patch.object(p, "update_rec", return_value=True) as mock_update,
        ):
            new_count = p.bump_ci_rca_occurrence("rec-9")

        assert new_count == 2
        mock_update.assert_called_once()
        call_args, call_kwargs = mock_update.call_args
        assert call_args[0] == "rec-9"
        updated_ctx = json.loads(call_args[1]["context_v2_json"])
        assert updated_ctx["occurrence_count"] == 2
        assert "last_seen" in updated_ctx

    def test_bump_ci_rca_occurrence_raises_on_missing_rec(self):
        import scripts.ops_data_portal as p

        with patch.object(p, "_fetch_rec_from_reader", return_value=None):
            with pytest.raises(RuntimeError, match="does not exist"):
                p.bump_ci_rca_occurrence("rec-nope")

    def test_bump_ci_rca_occurrence_defaults_missing_count_to_one(self):
        """A rec with no prior occurrence_count starts at 1 (implicit first filing) -> bumps to 2."""
        import scripts.ops_data_portal as p

        with (
            patch.object(p, "_fetch_rec_from_reader", return_value={"id": "rec-10", "context_v2_json": json.dumps({})}),
            patch.object(p, "update_rec", return_value=True) as mock_update,
        ):
            new_count = p.bump_ci_rca_occurrence("rec-10")

        assert new_count == 2
        mock_update.assert_called_once()


class TestCiRcaStrictLegacyReject:
    """CIRCA-02: strict mode rejects a source=ci_rca write with context_v2_json=None."""

    def test_strict_mode_rejects_legacy_no_context(self, tmp_path: Path) -> None:
        import scripts.ops_data_portal as p

        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_STRICT_MODE=strict"):
                p.file_rec(dict(_CI_RCA_FIELDS))

    def test_warn_mode_still_files_legacy_with_deprecation_warning(self, tmp_path: Path, caplog) -> None:
        """Warn mode keeps accepting the legacy no-context_v2_json path (rollout window)."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9201"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS))
        assert rec_id == "rec-9201"
        assert any("legacy free-text" in r.message for r in caplog.records)


class TestEvidenceBundleRefConditional:
    """CIRCA-06: _EvidenceBundleRef.s3_uri is required iff upload_status=='ok'."""

    def test_upload_failed_permits_empty_s3_uri(self) -> None:
        import scripts.ops_data_portal as p

        ref = p._EvidenceBundleRef(sha256="a" * 64, s3_uri="", upload_status="upload_failed")
        assert ref.s3_uri == ""

    def test_ok_with_empty_s3_uri_fails(self) -> None:
        import scripts.ops_data_portal as p

        with pytest.raises(ValidationError):
            p._EvidenceBundleRef(sha256="a" * 64, s3_uri="", upload_status="ok")

    def test_ok_with_non_s3_uri_fails(self) -> None:
        import scripts.ops_data_portal as p

        with pytest.raises(ValidationError):
            p._EvidenceBundleRef(sha256="a" * 64, s3_uri="https://example.com/x", upload_status="ok")

    def test_ok_with_valid_s3_uri_passes(self) -> None:
        import scripts.ops_data_portal as p

        ref = p._EvidenceBundleRef(sha256="a" * 64, s3_uri="s3://bucket/key.json", upload_status="ok")
        assert ref.upload_status == "ok"


class TestTerminusOverrideTyped:
    """CIRCA-08: why_chain_terminus_override is a typed sub-model (reason: str, 80-400 chars)."""

    def _ctx_v2(self, **overrides):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": (
                "test gap explanation with enough chars for the field to satisfy the minimum length "
                "floor, citing scripts/validate.py:1 for reference."
            ),
        }
        ctx = {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "no systemic keyword or citation here at all really"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }
        ctx.update(overrides)
        return ctx

    def test_bad_dict_shape_fails(self) -> None:
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2(why_chain_terminus_override={"x": 1})
        with pytest.raises(ValidationError):
            p.CiRcaContext.model_validate(ctx)

    def test_reason_too_short_fails(self) -> None:
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2(why_chain_terminus_override={"reason": "x" * 79})
        with pytest.raises(ValidationError):
            p.CiRcaContext.model_validate(ctx)

    def test_reason_too_long_fails(self) -> None:
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2(why_chain_terminus_override={"reason": "x" * 401})
        with pytest.raises(ValidationError):
            p.CiRcaContext.model_validate(ctx)

    def test_conformant_reason_validates_and_bypasses_terminus(self) -> None:
        """A conformant terminus override validates even though the why_chain final entry
        deliberately lacks a systemic keyword and a file:line citation (the terminus floor)."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2(why_chain_terminus_override={"reason": "x" * 80})
        parsed = p.CiRcaContext.model_validate(ctx)
        assert parsed.why_chain_terminus_override is not None
        assert parsed.why_chain_terminus_override.reason == "x" * 80

    def test_no_override_still_enforces_terminus_floor(self) -> None:
        """Sanity: without an override, the deliberately-noncompliant final entry still fails."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        with pytest.raises(ValidationError):
            p.CiRcaContext.model_validate(ctx)


class TestWarnModePerRuleStamping:
    """CIRCA-04 (portal half): per-rule schema deficiency stamping."""

    def test_why_chain_too_long_stamps_specific_tag(self, tmp_path: Path) -> None:
        import scripts.ops_data_portal as p

        deficient_ctx = {
            **_VALID_CONTEXT_V2,
            "why_chain": [
                "a " * 25,
                "b " * 25,
                "c " * 130 + "systemic scripts/validate.py:1",  # > 250 chars, schema_version=1
            ],
            "rca_confidence": "undetermined",  # isolate from bundle-absent
        }
        recs_file = tmp_path / "recs.jsonl"
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9301"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=deficient_ctx)
        assert rec_id == "rec-9301"
        entry = json.loads(recs_file.read_text(encoding="utf-8").splitlines()[0])
        stored = json.loads(entry["context_v2_json"])
        assert stored["warn_mode_reject"]["reasons"] == ["schema_why_chain_too_long"]

    def test_unmapped_deficiency_falls_back_to_bare_tag(self) -> None:
        import scripts.ops_data_portal as p

        assert p._classify_schema_deficiency("recurrence_class must be one of [...]") == "schema_deficiency"


class TestWhyChainCeilingVersioned:
    """CIRCA-04 ceiling: why_chain per-entry length ceiling is version-gated (v1=250, v2=400)."""

    def _ctx_v2(self, why_chain_last_entry: str, schema_version: int):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": (
                "test gap explanation with enough chars for the field to satisfy the minimum length "
                "floor, citing scripts/validate.py:1 for reference."
            ),
        }
        return {
            "schema_version": schema_version,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, why_chain_last_entry],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }

    @staticmethod
    def _entry_of_length(total_len: int) -> str:
        """Build a why_chain final entry of EXACTLY total_len chars, preserving the trailing
        systemic keyword + file:line citation the terminus check requires."""
        suffix = "this is a systemic gap at scripts/validate.py:1"
        filler_len = total_len - len(suffix) - 1  # -1 for the joining space
        assert filler_len > 0
        filler = ("c" * filler_len)[:filler_len]
        entry = f"{filler} {suffix}"
        assert len(entry) == total_len, len(entry)
        return entry

    def test_v2_accepts_300_char_entry(self) -> None:
        import scripts.ops_data_portal as p

        entry = self._entry_of_length(300)
        ctx = self._ctx_v2(entry, schema_version=2)
        parsed = p.CiRcaContext.model_validate(ctx)
        assert parsed.schema_version == 2

    def test_v1_rejects_same_300_char_entry(self) -> None:
        import scripts.ops_data_portal as p

        entry = self._entry_of_length(300)
        ctx = self._ctx_v2(entry, schema_version=1)
        with pytest.raises(ValidationError, match="max 250"):
            p.CiRcaContext.model_validate(ctx)

    def test_v1_default_250_ceiling_unaffected_for_historical_rows(self) -> None:
        """A 250-char entry (the pre-existing ceiling) still validates at schema_version=1 --
        no historical row is newly rejected by the version-gated loosening."""
        import scripts.ops_data_portal as p

        entry = self._entry_of_length(250)  # exactly the pre-existing ceiling
        ctx = self._ctx_v2(entry, schema_version=1)
        parsed = p.CiRcaContext.model_validate(ctx)
        assert parsed.schema_version == 1


class TestDetectionGapUnknownGate:
    """CIRCA-09 (enum half): 'unknown' is accepted by _DetectionGap.actual_gate_that_caught_it."""

    def test_unknown_validates(self) -> None:
        import scripts.ops_data_portal as p

        gap = p._DetectionGap(
            earliest_viable_gate="pre",
            actual_gate_that_caught_it="unknown",
            gap_explanation=(
                "not_a_gate workflow -- terraform-apply-sandbox has no CI-gate concept to report, so the "
                "bundle emits null and the agent mirrors 'unknown' at scripts/validate.py:1."
            ),
        )
        assert gap.actual_gate_that_caught_it == "unknown"

    def test_still_rejects_out_of_enum_value(self) -> None:
        import scripts.ops_data_portal as p

        with pytest.raises(ValidationError):
            p._DetectionGap(
                earliest_viable_gate="pre",
                actual_gate_that_caught_it="not_a_real_gate",
                gap_explanation=(
                    "explanation with enough chars and a citation at scripts/validate.py:1 to satisfy "
                    "the 120-character minimum length floor for this field."
                ),
            )

    def test_guidance_documents_unknown_and_mirror_instruction(self) -> None:
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca")
        detection_gap_doc = guidance["context_v2_json"]["schema_fields"]["detection_gap"]
        assert "unknown" in detection_gap_doc
        assert "mirror" in detection_gap_doc.lower()


class TestProposeOrCloseRec:
    """Tests for propose_or_close_rec (T3.8 / CD.36 close_proposed lifecycle support)."""

    def test_deterministic_satisfied_auto_closes(self, monkeypatch) -> None:
        """Deterministic satisfied => update_rec called with status=closed and proof in resolution."""
        import scripts.ops_data_portal as p

        calls: list[dict] = []
        monkeypatch.setattr(
            p, "update_rec", lambda rec_id, updates, profile=None: calls.append({"rec_id": rec_id, "updates": updates})
        )

        result = p.propose_or_close_rec("rec-001", "satisfied", "acceptance probe passed: echo ok", deterministic=True)
        assert result is None
        assert len(calls) == 1
        assert calls[0]["rec_id"] == "rec-001"
        assert calls[0]["updates"]["status"] == "closed"
        assert "acceptance probe passed" in calls[0]["updates"]["resolution"]

    def test_semantic_satisfied_yields_proposal_not_auto_close(self, monkeypatch) -> None:
        """Semantic satisfied => proposal string returned, update_rec NOT called."""
        import scripts.ops_data_portal as p

        calls: list[dict] = []
        monkeypatch.setattr(p, "update_rec", lambda rec_id, updates, profile=None: calls.append(rec_id))

        result = p.propose_or_close_rec(
            "rec-001", "satisfied", "semantic: file foo.py modified in abc12345", deterministic=False
        )
        assert result is not None
        assert "rec-001" in result
        assert "--status closed" in result
        assert len(calls) == 0

    def test_superseded_yields_proposal(self, monkeypatch) -> None:
        """Semantic superseded => proposal string, update_rec NOT called."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        result = p.propose_or_close_rec("rec-002", "superseded", "semantic: closed sibling rec-001 title similarity >= 0.5")
        assert result is not None
        assert "rec-002" in result
        assert "superseded" in result

    def test_duplicate_yields_proposal(self, monkeypatch) -> None:
        """Duplicate verdict => proposal string."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        result = p.propose_or_close_rec("rec-003", "duplicate", "semantic: open duplicate rec-999 title similarity >= 0.7")
        assert result is not None
        assert "duplicate" in result

    def test_contradicted_yields_proposal(self, monkeypatch) -> None:
        """Contradicted verdict => proposal string."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        result = p.propose_or_close_rec("rec-004", "contradicted", "Decision 5 is superseded")
        assert result is not None
        assert "contradicted" in result

    def test_stale_target_yields_proposal(self, monkeypatch) -> None:
        """Stale target verdict => proposal string (not auto-close)."""
        import scripts.ops_data_portal as p

        calls: list[dict] = []
        monkeypatch.setattr(p, "update_rec", lambda rec_id, updates, profile=None: calls.append(rec_id))
        result = p.propose_or_close_rec("rec-005", "stale_target", "target file absent: scripts/old.py")
        assert result is not None
        assert "stale_target" in result
        assert len(calls) == 0

    def test_blocked_by_decision_yields_proposal(self, monkeypatch) -> None:
        """Blocked verdict => proposal string."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        result = p.propose_or_close_rec("rec-006", "blocked_by_decision", "Decision 7 is pending")
        assert result is not None
        assert "blocked_by_decision" in result

    def test_relevant_returns_none(self, monkeypatch) -> None:
        """Relevant verdict => no action (None returned)."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        assert p.propose_or_close_rec("rec-007", "relevant", "no resolution signals detected") is None

    def test_unknown_returns_none(self, monkeypatch) -> None:
        """Unknown verdict => no action (None returned)."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        assert p.propose_or_close_rec("rec-008", "unknown", "no signals available") is None

    def test_evidence_with_quotes_escaped_in_proposal(self, monkeypatch) -> None:
        """Evidence string with quotes is shell-safe in the proposal command."""
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "update_rec", lambda *a, **k: None)
        result = p.propose_or_close_rec("rec-009", "superseded", 'evidence with "quotes" inside')
        assert result is not None
        assert '\\"quotes\\"' in result


class TestBundleAbsentFailLoud:
    """c12(ii): _run_ci_rca_cross_check bundle-absent fail-loud (ops_data_portal.py)."""

    def _ctx_v2(self, **overrides):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": "test gap explanation with enough chars for the field",
        }
        ctx = {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }
        ctx.update(overrides)
        return ctx

    def test_strict_rejects_bundle_absent_without_undetermined(self, tmp_path) -> None:
        """No evidence_bundle_ref and rca_confidence != undetermined -> strict rejects."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()  # no evidence_bundle_ref, no rca_confidence
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_BUNDLE_ABSENT"):
                p._run_ci_rca_cross_check(ctx)

    def test_strict_accepts_bundle_absent_with_undetermined(self, tmp_path, caplog) -> None:
        """No evidence_bundle_ref but rca_confidence=undetermined -> strict accepts (human-route)."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["rca_confidence"] = "undetermined"
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            p._run_ci_rca_cross_check(ctx)  # must not raise
        assert any("routed to mandatory human review" in r.message for r in caplog.records)

    def test_warn_accepts_bundle_absent_and_logs_gauge(self, caplog) -> None:
        """Warn mode (default) accepts a bundle-absent rec but logs the CI_RCA_BUNDLE_ABSENT gauge."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        with caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"):
            p._run_ci_rca_cross_check(ctx)  # must not raise
        assert any("CI_RCA_BUNDLE_ABSENT" in r.message for r in caplog.records)


class TestEvidenceS3Existence:
    """c5 / INTENT Section 4 check 7: S3-object-existence verification (ops_data_portal.py)."""

    _S3_URI = "s3://agent-platform-data-lake/ci-rca-evidence/" + "a" * 64 + ".json"

    def _ctx_v2(self, **overrides):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": "test gap explanation with enough chars for the field",
        }
        ctx = {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }
        ctx.update(overrides)
        return ctx

    def test_object_present_accepts(self, tmp_path) -> None:
        """upload_status=ok and head_object succeeds -> accepted, S3 verified."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": self._S3_URI, "upload_status": "ok"}
        mock_client = MagicMock()
        mock_client.head_object.return_value = {}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)  # must not raise
        mock_client.head_object.assert_called_once()

    def test_object_missing_strict_rejects(self, tmp_path) -> None:
        """upload_status=ok but head_object 404s -> strict mode rejects."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": self._S3_URI, "upload_status": "ok"}
        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("404 NoSuchKey")
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="CI_RCA_EVIDENCE_S3_MISSING"):
                p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)

    def test_object_missing_warn_warns(self, tmp_path, caplog) -> None:
        """upload_status=ok but head_object 404s -> warn mode accepts + logs."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": self._S3_URI, "upload_status": "ok"}
        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("404 NoSuchKey")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)  # must not raise
        assert any("CI_RCA_EVIDENCE_S3_MISSING" in r.message for r in caplog.records)

    def test_upload_failed_takes_degraded_path_no_s3_call(self, tmp_path, caplog) -> None:
        """upload_status=upload_failed -> degraded accept, no head_object call made."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": self._S3_URI, "upload_status": "upload_failed"}
        mock_client = MagicMock()
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)  # must not raise
        mock_client.head_object.assert_not_called()
        assert any("CI_RCA_EVIDENCE_S3_DEGRADED" in r.message for r in caplog.records)

    def test_s3_permission_error_fails_open(self, tmp_path, caplog) -> None:
        """A non-404 S3 client error (e.g. AccessDenied) fails open with a warning, even in strict mode."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": "a" * 64, "s3_uri": self._S3_URI, "upload_status": "ok"}
        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("AccessDenied: permission denied")
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
            caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
        ):
            p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)  # must not raise
        assert any("CI_RCA_EVIDENCE_S3_FAIL_OPEN" in r.message for r in caplog.records)


class TestWarnModeRejectMarker:
    """c3 enabler: warn-mode would-reject stamp on source=ci_rca recs (T1.13 Section 7.2 gauge)."""

    def _ctx_v2(self, **overrides):
        dg = {
            "earliest_viable_gate": "pre",
            "actual_gate_that_caught_it": "CI",
            "gap_explanation": "test gap explanation with enough chars for the field",
        }
        ctx = {
            "schema_version": 2,
            "proximate_cause": "x" * 100,
            "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
            "detection_gap": dg,
            "recurrence_class": "novel",
            "corrective_action": "x" * 100,
            "preventive_action": "x" * 100,
        }
        ctx.update(overrides)
        return ctx

    def test_schema_deficiency_warn_stamps_marker(self, tmp_path: Path) -> None:
        """Warn mode accepts a schema-deficient write and stamps warn_mode_reject.reasons."""
        import scripts.ops_data_portal as p

        recs_file = tmp_path / "recs.jsonl"
        deficient_ctx = {
            **_VALID_CONTEXT_V2,
            "why_chain": ["short", "also short", "still short"],
            "rca_confidence": "undetermined",  # isolate the schema-deficiency stamp from bundle-absent
        }
        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-9101"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            rec_id = p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=deficient_ctx)
        assert rec_id == "rec-9101"
        entry = json.loads(recs_file.read_text(encoding="utf-8").splitlines()[0])
        stored = json.loads(entry["context_v2_json"])
        # CIRCA-04: per-rule stamping -- a too-short why_chain entry stamps the specific
        # schema_why_chain_too_short tag, not the bare "schema_deficiency" bucket.
        assert stored["warn_mode_reject"]["reasons"] == ["schema_why_chain_too_short"]
        assert stored["warn_mode_reject"]["mode_at_write"] == "warn"

    def test_schema_deficiency_strict_raises_no_rec(self, tmp_path: Path) -> None:
        """Strict mode raises on a schema-deficient write -- no rec is created, no marker exists."""
        import scripts.ops_data_portal as p

        deficient_ctx = {**_VALID_CONTEXT_V2, "why_chain": ["short", "also short", "still short"]}
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_STRICT_MODE=strict"):
                p.file_rec(dict(_CI_RCA_FIELDS), context_v2_json=deficient_ctx)
        assert "warn_mode_reject" not in deficient_ctx

    def test_bundle_absent_warn_stamps_marker(self) -> None:
        """Warn mode accepts a bundle-absent write and stamps warn_mode_reject.reasons."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()  # no evidence_bundle_ref, no rca_confidence
        p._run_ci_rca_cross_check(ctx)  # must not raise
        assert ctx["warn_mode_reject"]["reasons"] == ["bundle_absent"]
        assert ctx["warn_mode_reject"]["mode_at_write"] == "warn"

    def test_bundle_absent_strict_raises_no_marker(self, tmp_path: Path) -> None:
        """Strict mode raises on a bundle-absent write -- no marker is stamped."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file):
            with pytest.raises(ValueError, match="CI_RCA_STRICT_MODE=strict"):
                p._run_ci_rca_cross_check(ctx)
        assert "warn_mode_reject" not in ctx

    def test_s3_missing_warn_stamps_marker(self, tmp_path: Path) -> None:
        """Warn mode accepts an S3-missing write and stamps warn_mode_reject.reasons."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {
            "sha256": "a" * 64,
            "s3_uri": "s3://agent-platform-data-lake/ci-rca-evidence/" + "a" * 64 + ".json",
            "upload_status": "ok",
        }
        mock_client = MagicMock()
        mock_client.head_object.side_effect = Exception("404 NoSuchKey")
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx, s3_client_factory=lambda: mock_client)  # must not raise
        assert ctx["warn_mode_reject"]["reasons"] == ["s3_missing"]

    def test_cross_check_disagreement_warn_stamps_marker(self, tmp_path: Path) -> None:
        """Warn mode accepts a check-2 cross-check disagreement and stamps warn_mode_reject.reasons."""
        import hashlib as _hashlib
        import json as _json

        import scripts.ops_data_portal as p

        bundle_data = {"earliest_viable_gate": "CI", "escape_mode": "tier_misplaced", "vacuous_pass": False}
        payload = {k: v for k, v in bundle_data.items() if k != "sha256"}
        sha = _hashlib.sha256(
            _json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        bundle_data["sha256"] = sha
        pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / f"{sha}.json").write_bytes(
            _json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        )
        ctx = self._ctx_v2(earliest_viable_gate="pre")
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # must not raise
        assert ctx["warn_mode_reject"]["reasons"] == ["cross_check_check_2"]

    def test_conformant_warn_write_carries_no_marker(self) -> None:
        """A fully-conformant warn-mode write carries NO warn_mode_reject marker (absent, not empty)."""
        import scripts.ops_data_portal as p

        ctx = self._ctx_v2()  # no evidence_bundle_ref, rca_confidence=undetermined routes cleanly
        ctx["rca_confidence"] = "undetermined"
        p._run_ci_rca_cross_check(ctx)  # must not raise
        assert "warn_mode_reject" not in ctx

    def test_marker_survives_ci_rca_context_round_trip(self) -> None:
        """A stamped warn_mode_reject marker survives a CiRcaContext model parse round-trip."""
        import scripts.ops_data_portal as p

        ctx = dict(_VALID_CONTEXT_V2)
        p._stamp_warn_mode_reject(ctx, ["schema_deficiency", "bundle_absent"])
        parsed = p.CiRcaContext.model_validate(ctx)
        assert parsed.warn_mode_reject == {
            "reasons": ["schema_deficiency", "bundle_absent"],
            "mode_at_write": "warn",
        }
