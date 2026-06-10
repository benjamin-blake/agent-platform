"""Tests for scripts/ops_data_portal.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

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


@pytest.fixture(autouse=True)
def _default_iceberg_backend(monkeypatch):
    """Pin the legacy write/read tests to the iceberg (rollback) path.

    T2.19 flipped the DEFAULT ops backend iceberg -> ducklake (signed off 2026-06-09). The tests in
    this module that assert the OpsWriter()/DuckDBIcebergReader (iceberg) path predate the flip; pin
    them to iceberg so they exercise the (still-live) rollback path explicitly. Tests that need the
    ducklake transport override via `monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")`; the
    default-value test (`test_ops_backend_default_and_flag`) `delenv`s first to see the true default.
    """
    monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")


class TestFileRec:
    """Tests for file_rec()."""

    def test_file_rec_success(self, tmp_path: Path) -> None:
        """file_rec() returns allocated ID, routes rec to DuckLake, appends to local JSONL."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-600"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS))

        assert result == "rec-600"
        mock_dl_write.assert_called_once()
        call_table, call_rec = mock_dl_write.call_args[0]
        assert call_table == "ops_recommendations"
        assert call_rec["id"] == "rec-600"
        assert call_rec["status"] == "open"
        # write-through: local JSONL has new entry
        lines = recs_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["id"] == "rec-600"

    def test_file_rec_offline(self, tmp_path: Path) -> None:
        """file_rec() queues to pending outbox when DynamoDB is unreachable."""
        pending_dir = tmp_path / "pending"

        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("DynamoDB unreachable")),
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS))

        assert result.startswith("pending-")
        pending_files = list(pending_dir.glob("*.json"))
        assert len(pending_files) == 1
        queued = json.loads(pending_files[0].read_text(encoding="utf-8"))
        assert "id" not in queued  # no ID yet
        assert queued["title"] == _VALID_FIELDS["title"]

    def test_file_rec_invalid_schema(self, tmp_path: Path) -> None:
        """file_rec() raises ValidationError when rec fields fail Pydantic validation."""
        # Missing required 'status' field -- Recommendation.model_validate will raise
        invalid_fields = dict(_VALID_FIELDS)
        invalid_fields.pop("status")

        with patch("scripts.ops_data_portal._next_id", return_value="rec-601"):
            from scripts.ops_data_portal import file_rec

            with pytest.raises((ValidationError, Exception)):
                file_rec(invalid_fields)

    def test_file_rec_date_added_if_missing(self, tmp_path: Path) -> None:
        """file_rec() adds today's date to the record if not supplied."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        fields = dict(_VALID_FIELDS)
        fields.pop("status", None)  # will default to "open" via fields copy

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-602"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS))

        assert result == "rec-602"
        entry = json.loads(recs_file.read_text(encoding="utf-8").strip().splitlines()[0])
        assert entry.get("date") is not None  # date was added

    def test_file_rec_rejects_unregistered_source(self, tmp_path: Path) -> None:
        """file_rec() raises ValueError when source is not in the registry."""
        fields = dict(_VALID_FIELDS)
        fields["source"] = "ghost-agent"

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-999"),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
        ):
            from scripts.ops_data_portal import file_rec

            with pytest.raises(ValueError, match="Unknown source 'ghost-agent'"):
                file_rec(fields)

    def test_file_rec_accepts_registered_source(self, tmp_path: Path) -> None:
        """file_rec() succeeds when source is a registered canonical_id."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        fields = dict(_VALID_FIELDS)
        fields["source"] = "planning"

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-998"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(fields)

        assert result == "rec-998"


class TestUpdateRec:
    """Tests for update_rec()."""

    def test_update_rec_success(self, tmp_path: Path) -> None:
        """update_rec() reads from Athena, merges updates, routes recs to DuckLake, appends to local JSONL."""
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
        # write-through: local JSONL appended
        lines = recs_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 2  # original + appended update

    def test_update_rec_invalid_status(self) -> None:
        """update_rec() raises ValueError for invalid status values (before Athena read)."""
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="Invalid status"):
            update_rec("rec-042", {"status": "done"})

    def test_update_rec_absent_rec_loud_fails(self, tmp_path: Path) -> None:
        """update_rec() loud-fails on an absent rec (referential, CD.33 cl.8 / D-5).

        The prior permissive upsert-on-absent (`existing or {}`) is GONE: an update of a record
        that does not exist in the current projection raises RuntimeError and never silently
        creates a partial row.
        """
        recs_file = tmp_path / ".recommendations-log.jsonl"
        updates = {**_VALID_FIELDS, "id": "rec-042", "status": "closed"}

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=None),
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            with pytest.raises(RuntimeError, match="does not exist"):
                update_rec("rec-042", updates)

        # No write was staged -- the absent rec was rejected before any write path.
        mock_opswriter.return_value.write.assert_not_called()


class TestStorageBackendTransport:
    """The OPS_STORAGE_BACKEND flag swaps transport only; the caller surface is unchanged."""

    def test_file_rec_ducklake_invokes_writer_not_opswriter(self, tmp_path: Path, monkeypatch) -> None:
        """backend=ducklake routes file_rec through the writer Function URL, not OpsWriter (Iceberg)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        recs_file = tmp_path / ".recommendations-log.jsonl"
        fields = {**_VALID_FIELDS}

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-900"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            rec_id = file_rec(fields)

        assert rec_id == "rec-900"
        mock_write.assert_called_once()
        assert mock_write.call_args[0][0] == "ops_recommendations"
        assert mock_write.call_args.kwargs["action"] == "write_ops"
        mock_opswriter.return_value.write.assert_not_called()

    def test_file_rec_routes_to_ducklake_regardless_of_backend(self, tmp_path: Path, monkeypatch) -> None:
        """recs always route to DuckLake even when backend=iceberg (Decision 81 cl.7 / T2.19 -- no iceberg escape)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")
        recs_file = tmp_path / ".recommendations-log.jsonl"
        fields = {**_VALID_FIELDS}

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-901"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(fields)

        mock_write.assert_called_once()
        assert mock_write.call_args[0][0] == "ops_recommendations"
        mock_opswriter.return_value.write.assert_not_called()

    def test_update_rec_ducklake_invokes_writer_update_ops(self, tmp_path: Path, monkeypatch) -> None:
        """backend=ducklake routes update_rec through update_ops (the in-tx referential write)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        existing = {**_VALID_FIELDS, "id": "rec-042"}
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            assert update_rec("rec-042", {"status": "closed"}) is True

        assert mock_write.call_args.kwargs["action"] == "update_ops"
        mock_opswriter.return_value.write.assert_not_called()

    def test_file_decision_stays_iceberg_on_ducklake_backend(self, tmp_path: Path, monkeypatch) -> None:
        """Recs-first slice: decisions are DEFERRED -- file_decision uses OpsWriter (Iceberg) even when
        OPS_STORAGE_BACKEND=ducklake (NOT the DuckLake writer)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        with (
            patch("scripts.ops_data_portal._next_id", return_value=57),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            file_decision({"title": "D", "status": "open", "rationale": "x"})

        mock_opswriter.return_value.write.assert_called_once()
        mock_dl.assert_not_called()

    def test_update_decision_stays_iceberg_on_ducklake_backend(self, tmp_path: Path, monkeypatch) -> None:
        """update_decision stays on OpsWriter (Iceberg) even on the ducklake backend (decisions deferred)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        existing = {
            "id": "dec-042",
            "title": "D",
            "status": "open",
            "created_timestamp": "2026-05-01T00:00:00+00:00",
            "last_updated_timestamp": "2026-05-01T00:00:00+00:00",
        }
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        with (
            patch("scripts.ops_data_portal._fetch_decision_from_athena", return_value=dict(existing)),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import update_decision

            assert update_decision("dec-042", {"status": "closed"}) is True

        mock_opswriter.return_value.write.assert_called_once()
        mock_dl.assert_not_called()

    def test_portal_exposes_no_import_bypass_write_surface(self) -> None:
        """The ONLY ops write surface is file_rec/update_rec (+ file_decision/update_decision for the
        deferred Iceberg path). No import/bootstrap/bypass writer is exposed on the portal (Decision 81;
        the one-time recs move is the operational maintenance seed, not a portal/agent surface)."""
        import scripts.ops_data_portal as portal

        forbidden = [
            n
            for n in dir(portal)
            if any(k in n.lower() for k in ("import_rec", "bootstrap", "bypass", "seed_rec", "raw_write", "import_ops"))
        ]
        assert forbidden == []


class TestFileDecision:
    """Tests for file_decision()."""

    def test_file_decision_success(self, tmp_path: Path) -> None:
        """file_decision() returns dec-NNN string and dual-writes id + decision_id."""
        decisions_jsonl = tmp_path / ".decisions-index.jsonl"
        with (
            patch("scripts.ops_data_portal._next_id", return_value=56),
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal.DECISIONS_JSONL", decisions_jsonl),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision({"title": "Test decision", "status": "open", "rationale": "For testing"})

        assert result == "dec-056"
        call_table, call_rec = mock_opswriter.return_value.write.call_args[0]
        assert call_table == "ops_decisions"
        assert call_rec["decision_id"] == 56
        assert call_rec["id"] == "dec-056"

    def test_file_decision_offline(self, tmp_path: Path) -> None:
        """file_decision() returns pending-UUID and queues to outbox when DynamoDB unavailable."""
        pending_dir = tmp_path / "pending"
        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("unreachable")),
            patch("scripts.ops_data_portal._DECISIONS_PENDING_OUTBOX", pending_dir),
        ):
            from scripts.ops_data_portal import file_decision

            result = file_decision({"title": "Offline decision", "status": "open", "rationale": "test"})

        assert result.startswith("pending-")


class TestDrainPending:
    """Tests for drain_pending()."""

    def test_drain_pending_success(self, tmp_path: Path) -> None:
        """drain_pending() drains queued files and routes recs to DuckLake (T2.19)."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        pending_fields = {**_VALID_FIELDS}
        pending_fields.pop("id", None)
        (pending_dir / "abc123.json").write_text(json.dumps(pending_fields), encoding="utf-8")
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-601"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        assert result["skipped"] == 0
        mock_dl_write.assert_called_once()
        assert mock_dl_write.call_args[0][0] == "ops_recommendations"
        # pending file should be deleted
        assert not (pending_dir / "abc123.json").exists()
        # appended to local JSONL
        lines = recs_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["id"] == "rec-601"

    def test_drain_pending_routes_to_writer_on_ducklake_backend(self, tmp_path: Path, monkeypatch) -> None:
        """On the ducklake backend, drain_pending() routes the drained rec through the writer (closed boundary).

        T2.19 sign-off: the offline-outbox drain must honour the active backend, not unconditionally
        stage to Iceberg -- otherwise an offline-queued rec resurfaces in Iceberg post-cutover.
        """
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        pending_fields = {**_VALID_FIELDS}
        pending_fields.pop("id", None)
        (pending_dir / "abc123.json").write_text(json.dumps(pending_fields), encoding="utf-8")
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-601"),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl_write,
            patch("scripts.ops_data_portal.OpsWriter") as mock_opswriter,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        mock_dl_write.assert_called_once()
        assert mock_dl_write.call_args[0][0] == "ops_recommendations"
        mock_opswriter.return_value.write.assert_not_called()

    def test_drain_pending_dynamo_still_down(self, tmp_path: Path) -> None:
        """drain_pending() leaves files untouched when DynamoDB is still unreachable."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        (pending_dir / "xyz999.json").write_text(json.dumps(_VALID_FIELDS), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("still down")),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 0
        assert result["skipped"] == 1
        # file still exists
        assert (pending_dir / "xyz999.json").exists()

    def test_drain_pending_empty_dir(self, tmp_path: Path) -> None:
        """drain_pending() returns zero counts when outbox is empty."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)

        with patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 0
        assert result["skipped"] == 0
        assert result["deduped"] == 0

    def test_drain_passes_sso_profile_to_next_id(self, tmp_path: Path) -> None:
        """drain_pending() with no args passes _SSO_PROFILE to _next_id."""
        from scripts.ops_data_portal import _SSO_PROFILE

        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        pending_fields = {**_VALID_FIELDS}
        pending_fields.pop("id", None)
        (pending_dir / "test.json").write_text(json.dumps(pending_fields), encoding="utf-8")
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-900") as mock_next_id,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import drain_pending

            drain_pending()

        mock_next_id.assert_called_once_with("recommendations", profile=_SSO_PROFILE)

    def test_drain_pending_no_outbox_dir(self, tmp_path: Path) -> None:
        """drain_pending() returns zero counts when outbox directory does not exist."""
        missing_dir = tmp_path / "does_not_exist"

        with patch("scripts.ops_data_portal._PENDING_OUTBOX", missing_dir):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 0
        assert result["skipped"] == 0
        assert result["deduped"] == 0

    def test_drain_applies_compute_risk_when_file_and_effort_present(self, tmp_path: Path) -> None:
        """drain_pending() applies compute_risk when pending record has file and effort."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        pending_fields = {**_VALID_FIELDS, "risk": "low"}
        pending_fields.pop("id", None)
        (pending_dir / "cr_test.json").write_text(json.dumps(pending_fields), encoding="utf-8")
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-901"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_data_portal.compute_risk", return_value="medium") as mock_cr,
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        mock_cr.assert_called_once_with(pending_fields["file"], pending_fields["effort"])
        entry = json.loads(recs_file.read_text(encoding="utf-8").strip().splitlines()[0])
        assert entry["risk"] == "medium"

    def test_drain_skips_compute_risk_when_file_missing(self, tmp_path: Path) -> None:
        """drain_pending() skips compute_risk when pending record lacks file field."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        no_file_fields = {k: v for k, v in _VALID_FIELDS.items() if k != "file"}
        no_file_fields.pop("id", None)
        (pending_dir / "nf_test.json").write_text(json.dumps(no_file_fields), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-902"),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / ".recs.jsonl"),
            patch("scripts.ops_data_portal.compute_risk") as mock_cr,
        ):
            from scripts.ops_data_portal import drain_pending

            drain_pending()

        mock_cr.assert_not_called()

    def test_drain_pending_skips_entry_with_missing_source_key(self, tmp_path: Path) -> None:
        """drain_pending() skips outbox entries where the source key is absent (no KeyError)."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        recs_file = tmp_path / "recs.jsonl"

        no_source_entry = {k: v for k, v in _VALID_FIELDS.items() if k != "source"}
        valid_entry = dict(_VALID_FIELDS)
        valid_entry["source"] = "planning"

        (pending_dir / "aaa_no_source.json").write_text(json.dumps(no_source_entry), encoding="utf-8")
        (pending_dir / "bbb_valid.json").write_text(json.dumps(valid_entry), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-701"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        assert result["skipped"] == 1
        assert (pending_dir / "aaa_no_source.json").exists()
        assert not (pending_dir / "bbb_valid.json").exists()

    def test_drain_pending_rejects_unregistered_source(self, tmp_path: Path) -> None:
        """drain_pending() skips outbox entries with unregistered source; valid entries still drain."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        recs_file = tmp_path / "recs.jsonl"

        invalid_entry = dict(_VALID_FIELDS)
        invalid_entry["source"] = "ghost-agent"
        valid_entry = dict(_VALID_FIELDS)
        valid_entry["source"] = "planning"

        (pending_dir / "aaa_invalid.json").write_text(json.dumps(invalid_entry), encoding="utf-8")
        (pending_dir / "bbb_valid.json").write_text(json.dumps(valid_entry), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-700"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        assert result["skipped"] == 1
        assert (pending_dir / "aaa_invalid.json").exists()
        assert not (pending_dir / "bbb_valid.json").exists()


class TestEnqueueFindings:
    """Tests for enqueue_findings()."""

    def test_enqueue_findings_offline_bulk(self, tmp_path: Path) -> None:
        """enqueue_findings() writes one outbox file per valid entry when DynamoDB is unreachable."""
        pending_dir = tmp_path / "pending"
        jsonl_file = tmp_path / "findings.jsonl"
        entry = {**_VALID_FIELDS, "source": "cc-scheduled-agent-test"}
        jsonl_file.write_text("\n".join([json.dumps(entry)] * 3) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("offline")),
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
        ):
            from scripts.ops_data_portal import enqueue_findings

            result = enqueue_findings(jsonl_file)

        assert result == {"enqueued": 3, "invalid": 0, "skipped": 0}
        assert len(list(pending_dir.glob("*.json"))) == 3

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
            patch("scripts.ops_data_portal._next_id", side_effect=["rec-801", "rec-802"]),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
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


class TestPostmortemDedupe:
    """Tests for find_open_postmortem_for, drain_pending dedupe, and purge_postmortems_for."""

    def test_find_open_postmortem_for_returns_match(self, tmp_path: Path) -> None:
        recs_file = tmp_path / "recs.jsonl"
        postmortem = {
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
        }
        recs_file.write_text(json.dumps(postmortem) + "\n", encoding="utf-8")

        with patch("scripts.ops_data_portal.RECS_JSONL", recs_file):
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

        with patch("scripts.ops_data_portal.RECS_JSONL", recs_file):
            from scripts.ops_data_portal import find_open_postmortem_for

            result = find_open_postmortem_for("rec-100")

        assert result is None

    def test_find_open_postmortem_for_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        missing_file = tmp_path / "missing.jsonl"
        with patch("scripts.ops_data_portal.RECS_JSONL", missing_file):
            from scripts.ops_data_portal import find_open_postmortem_for

            result = find_open_postmortem_for("rec-100")

        assert result is None

    def test_drain_pending_dedupes_existing_postmortem(self, tmp_path: Path) -> None:
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        recs_file = tmp_path / "recs.jsonl"

        existing_postmortem = {
            **_VALID_FIELDS,
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
            "context": "Executor failed for rec-100.",
        }
        recs_file.write_text(json.dumps(existing_postmortem) + "\n", encoding="utf-8")

        pending_fields = {
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
            "context": "Second postmortem attempt.",
            "status": "open",
            "effort": "S",
            "priority": "High",
            "automatable": False,
            "risk": "low",
            "file": "scripts/execute_recommendation.py",
            "acceptance": "grep -q 'rec-100' logs/.recommendations-log.jsonl",
        }
        pending_file = pending_dir / "dup-uuid.json"
        pending_file.write_text(json.dumps(pending_fields), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_data_portal._next_id") as mock_next_id,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing_postmortem)),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["deduped"] == 1
        assert result["drained"] == 0
        mock_next_id.assert_not_called()
        mock_dl_write.assert_called_once()
        write_table, write_rec = mock_dl_write.call_args[0]
        assert write_table == "ops_recommendations"
        assert write_rec["id"] == "rec-529"
        assert not pending_file.exists()

    def test_purge_postmortems_for_dry_run(self, tmp_path: Path) -> None:
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        recs_file = tmp_path / "recs.jsonl"

        postmortem = {
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
        }
        recs_file.write_text(json.dumps(postmortem) + "\n", encoding="utf-8")
        pending_fields = {"source": "executor-postmortem", "title": "Investigate executor failure for rec-100"}
        pending_file = pending_dir / "abc.json"
        pending_file.write_text(json.dumps(pending_fields), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import purge_postmortems_for

            result = purge_postmortems_for("rec-100", dry_run=True)

        assert result["pending_files"] == 1
        assert result["jsonl_entries"] == 1
        assert pending_file.exists()
        assert "rec-529" in recs_file.read_text(encoding="utf-8")

    def test_purge_postmortems_for_executes_full_cleanup(self, tmp_path: Path) -> None:
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        recs_file = tmp_path / "recs.jsonl"

        rec_100 = {**_VALID_FIELDS, "id": "rec-100", "date": "2026-01-01", "title": "target rec"}
        postmortem = {
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-100",
        }
        recs_file.write_text(
            json.dumps(rec_100) + "\n" + json.dumps(postmortem) + "\n",
            encoding="utf-8",
        )

        pending_fields = {"source": "executor-postmortem", "title": "Investigate executor failure for rec-100"}
        pending_file = pending_dir / "abc.json"
        pending_file.write_text(json.dumps(pending_fields), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_data_portal._delete_postmortems_from_iceberg", return_value=-1) as mock_iceberg,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(rec_100)),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import purge_postmortems_for

            result = purge_postmortems_for("rec-100", dry_run=False)

        assert result["pending_files"] == 1
        assert result["jsonl_entries"] == 1
        assert result["iceberg_delete_attempted"] is True
        mock_iceberg.assert_called_once_with("rec-100", profile=None)
        assert not pending_file.exists()
        remaining = recs_file.read_text(encoding="utf-8")
        assert "rec-529" not in remaining


class TestCLI:
    """Tests for the CLI entrypoint."""

    def test_cli_file_rec_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec prints the allocated rec ID to stdout."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-700"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
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


class TestWriteTimeDispatch:
    """Tests for _load_write_time_validators, _derive_computed_fields, and related drain/file_rec paths."""

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

    def test_drain_pending_computes_automatable(self, tmp_path: Path) -> None:
        """drain_pending() derives and sets automatable for outbox entries that lack it."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        recs_file = tmp_path / "recs.jsonl"

        fields_no_automatable = {k: v for k, v in _VALID_FIELDS.items() if k != "automatable"}
        fields_no_automatable.pop("id", None)
        (pending_dir / "test_auto.json").write_text(json.dumps(fields_no_automatable), encoding="utf-8")

        written_records: list[dict] = []

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-950"),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_data_portal._write_time_validators_cache", {}),
        ):
            mock_dl_write.side_effect = lambda _t, rec, **kw: written_records.append(rec)
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1, f"Expected drained=1, got {result}"
        assert len(written_records) == 1
        assert written_records[0].get("automatable") is not None, "automatable should be derived and non-null"

    def test_drain_pending_created_timestamp_full_precision(self, tmp_path: Path) -> None:
        """drain_pending() sets created_timestamp with a time component, not a date-only midnight fallback."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        recs_file = tmp_path / "recs.jsonl"

        fields = dict(_VALID_FIELDS)
        fields.pop("id", None)
        fields.pop("created_timestamp", None)
        (pending_dir / "test_ts.json").write_text(json.dumps(fields), encoding="utf-8")

        written_records: list[dict] = []

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id", return_value="rec-951"),
            patch("scripts.ops_data_portal._ducklake_write") as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
            patch("scripts.ops_data_portal._write_time_validators_cache", {}),
        ):
            mock_dl_write.side_effect = lambda _t, rec, **kw: written_records.append(rec)
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1, f"Expected drained=1, got {result}"
        assert len(written_records) == 1
        ts = written_records[0].get("created_timestamp", "")
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
        pending_dir = tmp_path / "pending"
        from scripts.ops_data_portal import file_rec

        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("DynamoDB unreachable")),
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
        ):
            result = file_rec(fields)
        assert result.startswith("pending-")


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
            patch("scripts.ops_data_portal._COVERAGE_XML", coverage_xml),
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

            # C=12, S=0.1 (XS), M=0.1 -> R = 1.2*0.1/0.1 = wait, R=(12*0.1)/0.1=12 -> medium
            assert compute_risk("file.py", "XS") == "medium"


class TestPipelineConsolidation:
    """Tests for the ops pipeline consolidation changes (Decision 69)."""

    def test_update_rec_reads_from_athena_not_jsonl(self, tmp_path: Path) -> None:
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

    def test_update_rec_post_sync(self, tmp_path: Path) -> None:
        """update_rec() triggers _sync_table after writing."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        existing = dict(_VALID_FIELDS, id="rec-042", status="open")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=existing),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import update_rec

            update_rec("rec-042", {"status": "closed"})

        mock_sync.assert_called_once_with("ops_recommendations")

    def test_file_rec_post_sync(self, tmp_path: Path) -> None:
        """file_rec() triggers _sync_table after writing."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-700"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(dict(_VALID_FIELDS))

        mock_sync.assert_called_once_with("ops_recommendations")

    def test_sync_returns_report(self) -> None:
        """sync() returns a structured report with compacted, pulled, and views_refreshed keys."""
        with (
            patch("scripts.ops_data_portal.OpsWriter") as mock_writer,
            patch("scripts.ops_data_portal.sync") as _,  # prevent re-import collision
        ):
            mock_writer.return_value.compact.return_value = 5
            mock_writer.return_value._refresh_view.return_value = None

            import sys

            sys.modules.pop("scripts.ops_data_portal", None)

        with (
            patch("scripts.ops_data_portal.OpsWriter") as mock_writer,
            patch("scripts.sync_ops.drain", return_value={}),
            patch("scripts.sync_ops._pull_single_table", return_value=10),
        ):
            mock_writer.return_value.compact.return_value = 5
            mock_writer.return_value._refresh_view.return_value = None

            from scripts.ops_data_portal import sync

            result = sync(["ops_recommendations"])

        assert "compacted" in result
        assert "pulled" in result
        assert "views_refreshed" in result
        assert result["compacted"]["ops_recommendations"] == 5
        assert result["pulled"]["ops_recommendations"] == 10
        assert "ops_recommendations" in result["views_refreshed"]

    def test_update_rec_raises_on_athena_unreachable(self, tmp_path: Path) -> None:
        """update_rec() propagates RuntimeError when _fetch_rec_from_reader raises."""
        import pytest

        with (
            patch(
                "scripts.ops_data_portal._fetch_rec_from_reader",
                side_effect=RuntimeError("Athena unreachable"),
            ),
        ):
            from scripts.ops_data_portal import update_rec

            with pytest.raises(RuntimeError, match="Athena unreachable"):
                update_rec("rec-042", {"status": "closed"})


class TestMigrationParams:
    """Tests for the private migration params on file_rec / file_decision / drain_pending."""

    def test_file_rec_migration_int_id_pads_to_three_digits(self, tmp_path: Path) -> None:
        """_migration_int_id bypasses _next_id and pads to rec-NNN (FK-compatible)."""
        with (
            patch("scripts.ops_data_portal._next_id") as mock_next_id,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS), _migration_int_id=5, _migration_mode=True, _skip_sync=True)

        assert result == "rec-005"
        mock_next_id.assert_not_called()

    def test_file_rec_skip_sync_suppresses_sync_table(self, tmp_path: Path) -> None:
        """_skip_sync=True defers the per-row _sync_table flush."""
        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-700"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import file_rec

            file_rec(dict(_VALID_FIELDS), _skip_sync=True)
            mock_sync.assert_not_called()

            file_rec(dict(_VALID_FIELDS))
            mock_sync.assert_called_once()

    def test_file_rec_migration_mode_bypasses_content_validators(self, tmp_path: Path) -> None:
        """_migration_mode lets a historical row that fails content rules import; the schema still applies."""
        thin = {**_VALID_FIELDS, "context": "too short", "acceptance": ""}

        with (
            patch("scripts.ops_data_portal._next_id", return_value="rec-701"),
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

    def test_file_rec_migration_id_bypasses_next_id_even_when_dynamo_down(self, tmp_path: Path) -> None:
        """A migration row never goes to the portal outbox: _migration_int_id skips _next_id entirely."""
        pending_dir = tmp_path / "pending"
        with (
            patch("scripts.ops_data_portal._next_id", side_effect=RuntimeError("unreachable")),
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.ops_data_portal._sync_table"),
        ):
            from scripts.ops_data_portal import file_rec

            result = file_rec(dict(_VALID_FIELDS), _migration_int_id=42, _migration_mode=True, _skip_sync=True)

        assert result == "rec-042"
        assert not pending_dir.exists() or not list(pending_dir.glob("*.json"))

    def test_file_decision_skip_sync_suppresses_sync_table(self, tmp_path: Path) -> None:
        """_skip_sync=True on file_decision defers the per-row flush."""
        with (
            patch("scripts.ops_data_portal._next_id", return_value=77),
            patch("scripts.ops_data_portal.OpsWriter"),
            patch("scripts.ops_data_portal.DECISIONS_JSONL", tmp_path / "dec.jsonl"),
            patch("scripts.ops_data_portal._load_write_time_validators", return_value=[]),
            patch("scripts.ops_data_portal._sync_table") as mock_sync,
        ):
            from scripts.ops_data_portal import file_decision

            file_decision({"title": "d", "status": "open"}, _skip_sync=True)
            mock_sync.assert_not_called()

    def test_drain_pending_honors_migration_int_id(self, tmp_path: Path) -> None:
        """A pending rec carrying migration markers drains to the preserved padded id, no _next_id."""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir(parents=True)
        payload = {**_VALID_FIELDS, "context": "short", "_migration_int_id": 8, "_migration_mode": True}
        payload.pop("id", None)
        (pending_dir / "m.json").write_text(json.dumps(payload), encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal._next_id") as mock_next_id,
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", tmp_path / "recs.jsonl"),
        ):
            from scripts.ops_data_portal import drain_pending

            result = drain_pending()

        assert result["drained"] == 1
        mock_next_id.assert_not_called()
        _, call_rec = mock_dl_write.call_args[0]
        assert call_rec["id"] == "rec-008"


class TestFetchRecFromAthena:
    """Tests for _fetch_rec_from_reader reader path (Decision 69 / CD.8)."""

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

    def test_reader_path_returns_record(self) -> None:
        """DuckDBIcebergReader success -> returns sanitised record without Athena."""
        with patch("src.common.iceberg_reader.DuckDBIcebergReader") as MockReader:
            MockReader.return_value.current_state.return_value = [dict(self._REC_ROW)]

            from scripts.ops_data_portal import _fetch_rec_from_reader

            result = _fetch_rec_from_reader("rec-042")

        assert result is not None
        assert result["id"] == "rec-042"
        assert result["status"] == "open"
        MockReader.return_value.current_state.assert_called_once()

    def test_reader_raises_loud_fail_no_athena_fallback(self) -> None:
        """Iceberg-backend reader failure loud-fails directly -- no Athena fallback (view dropped at T2.7)."""
        with patch("src.common.iceberg_reader.DuckDBIcebergReader") as MockReader:
            MockReader.return_value.current_state.side_effect = RuntimeError("reader broken")

            # boto3 must never be touched (the Athena fallback was removed with the view drop).
            import boto3

            with patch.object(
                boto3,
                "Session",
                lambda *a, **k: (_ for _ in ()).throw(AssertionError("Athena fallback used")),
            ):
                from scripts.ops_data_portal import _fetch_rec_from_reader

                with pytest.raises(RuntimeError, match="Iceberg reader failed"):
                    _fetch_rec_from_reader("rec-042")

    def test_reader_returns_none_when_row_not_found(self) -> None:
        """Reader returns empty list -> function returns None without calling Athena."""
        with patch("src.common.iceberg_reader.DuckDBIcebergReader") as MockReader:
            MockReader.return_value.current_state.return_value = []

            with patch("scripts.ops_data_portal.resolve_aws_profile") as mock_profile:
                from scripts.ops_data_portal import _fetch_rec_from_reader

                result = _fetch_rec_from_reader("rec-999")

            mock_profile.assert_not_called()

        assert result is None

    def test_invalid_rec_id_raises_value_error(self) -> None:
        """Malformed rec_id raises ValueError before any reader or Athena call (security guard)."""
        from scripts.ops_data_portal import _fetch_rec_from_reader

        with pytest.raises(ValueError, match="invalid rec_id"):
            _fetch_rec_from_reader("'; DROP TABLE ops_recommendations; --")


class TestDuckLakeTransportHelpers:
    """Coverage for the DuckLake transport helpers (T2.19): URL resolve, projection, SigV4 write."""

    def test_ops_backend_default_and_flag(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        # T2.19 cutover (signed off 2026-06-09): the default flipped iceberg -> ducklake.
        monkeypatch.delenv("OPS_STORAGE_BACKEND", raising=False)
        assert p._ops_backend() == "ducklake"
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ICEBERG")
        assert p._ops_backend() == "iceberg"
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "DUCKLAKE")
        assert p._ops_backend() == "ducklake"

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
        captured: dict = {}

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

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "key": "rec-1"}

        import boto3
        import requests
        from botocore.auth import SigV4Auth

        monkeypatch.setattr(boto3, "Session", _Session)
        monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)

        def _post(url, data=None, headers=None, timeout=None):
            captured["body"] = json.loads(data)
            return _Resp()

        monkeypatch.setattr(requests, "post", _post)
        out = p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "open"}, action="write_ops")
        assert out["ok"] is True
        assert captured["body"]["action"] == "write_ops"
        assert captured["body"]["table"] == "ops_recommendations"

    def test_ducklake_write_referential_409_maps_to_runtimeerror(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "_resolve_writer_url", lambda *a, **k: "https://w.example")

        class _Resp:
            status_code = 409
            text = "absent"

        self._patch_sig(monkeypatch, _Resp())
        with pytest.raises(RuntimeError, match="referential"):
            p._ducklake_write("ops_recommendations", {"id": "rec-x", "status": "closed"}, action="update_ops")

    def test_ducklake_write_schema_422_maps_to_valueerror(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setattr(p, "_resolve_writer_url", lambda *a, **k: "https://w.example")

        class _Resp:
            status_code = 422
            text = "bad field"

        self._patch_sig(monkeypatch, _Resp())
        with pytest.raises(ValueError, match="schema-gate"):
            p._ducklake_write("ops_recommendations", {"id": "rec-1", "status": "open"}, action="write_ops")

    @staticmethod
    def _patch_sig(monkeypatch, resp) -> None:
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

        import boto3
        import requests
        from botocore.auth import SigV4Auth

        monkeypatch.setattr(boto3, "Session", _Session)
        monkeypatch.setattr(SigV4Auth, "add_auth", lambda self, req: None)
        monkeypatch.setattr(requests, "post", lambda *a, **k: resp)


class TestSyncBackendAware:
    """sync()/_sync_table cache-pull behaviour per backend (T2.19)."""

    def test_sync_table_ducklake_pull_only(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        calls: list[str] = []
        monkeypatch.setattr("scripts.sync_ops._pull_single_table", lambda t: calls.append(t) or 0)
        with patch("scripts.ops_data_portal.OpsWriter") as mock_ow:
            p._sync_table("ops_recommendations")
        mock_ow.return_value.compact.assert_not_called()
        assert calls == ["ops_recommendations"]

    def test_sync_ducklake_no_outbox_drain(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        monkeypatch.setattr("scripts.sync_ops._pull_single_table", lambda t: 3)
        result = p.sync(["ops_recommendations"])
        assert result == {"compacted": {}, "pulled": {"ops_recommendations": 3}, "views_refreshed": []}


class TestSelftests:
    """--selftest-read / --selftest-roundtrip portal probes (VP14/15)."""

    def test_selftest_read(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")

        class _Reader:
            def current_state(self, table, **kw):
                return [{"id": "rec-1"}]

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        out = p.selftest_read()
        assert out["backend"] == "iceberg" and out["row_count"] == 1 and out["sample_id"] == "rec-1"

    def test_selftest_roundtrip_ducklake(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        written: dict = {}
        monkeypatch.setattr(p, "_ducklake_write", lambda t, r, *, action, profile=None: written.update(id=r["id"]))

        class _Reader:
            def current_state(self, table, *, row_filter=None, **kw):
                return [{"id": written["id"]}]

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        out = p.selftest_roundtrip()
        assert out["read_back"] is True and out["backend"] == "ducklake"

    def test_selftest_roundtrip_loud_fails_when_not_read_back(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")
        # selftest_roundtrip always calls _ducklake_write for recs (T2.19); mock it to no-op
        monkeypatch.setattr(p, "_ducklake_write", lambda *a, **k: {"ok": True})

        class _Reader:
            def current_state(self, table, *, row_filter=None, **kw):
                return []

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        with pytest.raises(RuntimeError, match="read-back"):
            p.selftest_roundtrip()


class TestPurgePostmortemsLoudFailDuckLake:
    """purge_postmortems_for() must raise NotImplementedError on the ducklake backend (Step 8)."""

    def test_raises_not_implemented_on_ducklake_backend(self, monkeypatch) -> None:
        """DuckLake backend -> NotImplementedError before any side effects (Step 8 guard)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        from scripts.ops_data_portal import purge_postmortems_for

        with pytest.raises(NotImplementedError, match="purge_postmortems_for"):
            purge_postmortems_for("rec-100")

    def test_error_message_mentions_iceberg_rollback_path(self, monkeypatch) -> None:
        """Error message includes guidance to use OPS_STORAGE_BACKEND=iceberg rollback."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")
        from scripts.ops_data_portal import purge_postmortems_for

        with pytest.raises(NotImplementedError, match="OPS_STORAGE_BACKEND=iceberg"):
            purge_postmortems_for("rec-100")

    def test_does_not_raise_on_iceberg_backend(self, tmp_path: Path, monkeypatch) -> None:
        """Iceberg backend -> no guard fires (existing tests cover full cleanup path)."""
        monkeypatch.setenv("OPS_STORAGE_BACKEND", "iceberg")
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        recs_file = tmp_path / "recs.jsonl"
        recs_file.write_text("", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._PENDING_OUTBOX", pending_dir),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import purge_postmortems_for

            result = purge_postmortems_for("rec-100", dry_run=True)

        assert isinstance(result, dict)
        assert result["pending_files"] == 0


class TestClosedBoundaryNoAthenaFallback:
    """On the ducklake backend a reader failure must NOT fall back to Athena (OQ.7, code-review #review)."""

    def test_fetch_rec_ducklake_no_athena_fallback(self, monkeypatch) -> None:
        import scripts.ops_data_portal as p

        monkeypatch.setenv("OPS_STORAGE_BACKEND", "ducklake")

        class _Reader:
            def current_state(self, table, **kw):
                raise RuntimeError("reader down")

        monkeypatch.setattr("src.common.iceberg_reader.make_reader", lambda **kw: _Reader())
        # boto3 must never be touched (no Athena escape hatch). Make it explode if constructed.
        import boto3

        monkeypatch.setattr(boto3, "Session", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Athena fallback used")))
        with pytest.raises(RuntimeError, match="reader down"):
            p._fetch_rec_from_reader("rec-1")
