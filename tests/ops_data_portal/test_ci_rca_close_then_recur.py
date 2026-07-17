"""Tests for find_recent_ci_rca_rec_by_fingerprint(), reopen_ci_rca_rec(), and the
close-then-recur write-time backstop routing in file_rec() (CIRCA-03, rec-2644).

Split out of the former tests/test_ops_data_portal.py monolith (rec-2709 Wave 3): the sibling
of TestCiRcaFingerprintDedup (test_ci_rca_fingerprint.py), separated at the OVER-500-class
concern-split boundary (the pre-move monolith's lineno 2566). TestCiRcaCloseThenRecur is a NEW
class name -- the class-qualifier rename on this cohort (methods verbatim, unchanged) is the
SOLE sanctioned test-id delta of rec-2709 Wave 3. The shared members this cohort references --
the _FINGERPRINT class attr and the _make_bundle / _ctx_v2 builders -- are DUPLICATED verbatim
from TestCiRcaFingerprintDedup (never imported between test_* modules, per the
no-cross-test-import guard). The autouse _guard_live_reader rec-2707 backstop-reader guard this
class formerly duplicated too has since been retired (rec-2484): the global L1/L2 hermetic-AWS
guard in the root tests/conftest.py now supersedes it class-wide.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

duckdb = pytest.importorskip("duckdb")

from scripts.ops_portal import ci_rca_schema as _ci_rca_schema_mod  # noqa: E402
from tests.fixtures.ops_portal_records import VALID_FIELDS as _VALID_FIELDS  # noqa: E402


class TestCiRcaCloseThenRecur:
    """CIRCA-03 (rec-2644 close-then-recur): find_recent_ci_rca_rec_by_fingerprint(),
    reopen_ci_rca_rec(), and the close-then-recur backstop routing in file_rec() -- the sibling
    of TestCiRcaFingerprintDedup (test_ci_rca_fingerprint.py) split out at the rec-2709 Wave 3
    OVER-500-class boundary. Duplicates (not imports) the shared _FINGERPRINT / _make_bundle /
    _ctx_v2 members from that sibling.

    The former per-class _guard_live_reader autouse fixture (rec-2707 backstop-reader guard)
    is retired: the global L1/L2 hermetic-AWS guard in the root tests/conftest.py (rec-2484)
    now blocks any un-mocked src.common.iceberg_reader.make_reader() -> boto3 client path
    class-wide, so the per-class duplicate is redundant.
    """

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

    # -- find_recent_ci_rca_rec_by_fingerprint (rec-2644 close-then-recur, READ-ONLY) ----------

    def test_close_then_recur_recent_closed_match_surfaced_with_was_closed_true(self):
        import scripts.ops_data_portal as p

        recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        rows = [
            {
                "id": "rec-1",
                "status": "closed",
                "last_updated_timestamp": recent,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            }
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == ("rec-1", True)

    def test_close_then_recur_out_of_window_closed_match_not_revived(self):
        import scripts.ops_data_portal as p

        stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rows = [
            {
                "id": "rec-1",
                "status": "closed",
                "last_updated_timestamp": stale,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            }
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result is None

    def test_close_then_recur_open_match_returns_was_closed_false(self):
        import scripts.ops_data_portal as p

        rows = [{"id": "rec-2", "status": "open", "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT})}]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == ("rec-2", False)

    def test_close_then_recur_no_match_returns_none(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.return_value = [
            {"id": "rec-3", "status": "closed", "context_v2_json": json.dumps({"fingerprint": "b" * 64})}
        ]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    def test_close_then_recur_row_without_context_v2_json_skipped(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.return_value = [{"id": "rec-9", "status": "closed", "context_v2_json": None}]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    def test_close_then_recur_malformed_context_v2_json_skipped_not_raised(self):
        import scripts.ops_data_portal as p

        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rows = [
            {"id": "rec-6", "status": "closed", "last_updated_timestamp": recent, "context_v2_json": "not-json"},
            {
                "id": "rec-7",
                "status": "closed",
                "last_updated_timestamp": recent,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            },
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == ("rec-7", True)

    def test_close_then_recur_naive_timestamp_treated_as_utc(self):
        """A last_updated_timestamp with no timezone offset is treated as UTC (not rejected)."""
        import scripts.ops_data_portal as p

        naive_recent = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()
        rows = [
            {
                "id": "rec-8",
                "status": "closed",
                "last_updated_timestamp": naive_recent,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            }
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == ("rec-8", True)

    def test_close_then_recur_failed_status_excluded_from_matches(self):
        """A 'failed'/'declined'/'superseded' rec is not a close-then-recur candidate."""
        import scripts.ops_data_portal as p

        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rows = [
            {
                "id": "rec-4",
                "status": "failed",
                "last_updated_timestamp": recent,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            }
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    def test_close_then_recur_newest_touched_row_wins_over_older_closed_match(self):
        import scripts.ops_data_portal as p

        older = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        newer = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rows = [
            {
                "id": "rec-old",
                "status": "closed",
                "last_updated_timestamp": older,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            },
            {
                "id": "rec-new",
                "status": "closed",
                "last_updated_timestamp": newer,
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            },
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result == ("rec-new", True)

    def test_close_then_recur_reader_unreachable_fails_open(self, caplog):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("ducklake_reader 'read_ops_current' failed (HTTP 503): ...")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with caplog.at_level(logging.WARNING):
                result = p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)
        assert result is None
        assert any("reader unreachable" in rec.message.lower() for rec in caplog.records)

    def test_close_then_recur_unexpected_reader_error_raises(self):
        import scripts.ops_data_portal as p

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("boom -- unrelated to connectivity")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with pytest.raises(RuntimeError, match="boom"):
                p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT)

    def test_close_then_recur_unparseable_timestamp_treated_as_no_match(self):
        import scripts.ops_data_portal as p

        rows = [
            {
                "id": "rec-5",
                "status": "closed",
                "last_updated_timestamp": "not-a-timestamp",
                "context_v2_json": json.dumps({"fingerprint": self._FINGERPRINT}),
            }
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert p.find_recent_ci_rca_rec_by_fingerprint(self._FINGERPRINT) is None

    # -- reopen_ci_rca_rec (rec-2644, SEPARATE single-writer) ----------------------------------

    def test_close_then_recur_reopen_flips_status_and_bumps_once(self):
        # reopen_ci_rca_rec is defined IN scripts.ops_portal.ci_rca_runtime and calls
        # bump_ci_rca_occurrence as a same-module global (not a deferred facade import), so the
        # bump patch must target that module directly -- patching the facade re-export
        # (scripts.ops_data_portal.bump_ci_rca_occurrence) would not intercept this call
        # (tests/CLAUDE.md namespace migration discipline).
        import scripts.ops_data_portal as p
        import scripts.ops_portal.ci_rca_runtime as rt_mod

        with (
            patch.object(p, "update_rec", return_value=True) as mock_update,
            patch.object(rt_mod, "bump_ci_rca_occurrence", return_value=2) as mock_bump,
        ):
            new_count = p.reopen_ci_rca_rec("rec-1")

        assert new_count == 2
        mock_update.assert_called_once_with("rec-1", {"status": "open"}, profile=None)
        mock_bump.assert_called_once_with("rec-1", profile=None)

    # -- file_rec write-time backstop routing (rec-2644 + fingerprint_bump no-double-count) ----

    def test_close_then_recur_backstop_reopens_recently_closed_match_once(self, tmp_path: Path, monkeypatch):
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value=None) as mock_find_open,
            patch.object(p, "find_recent_ci_rca_rec_by_fingerprint", return_value=("rec-777", True)) as mock_find_recent,
            patch.object(p, "reopen_ci_rca_rec", return_value=2) as mock_reopen,
            patch.object(p, "bump_ci_rca_occurrence") as mock_bump,
            patch.object(p, "_ducklake_write") as mock_write,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-777"
        mock_find_open.assert_called_once()
        mock_find_recent.assert_called_once_with(self._FINGERPRINT, profile=None)
        mock_reopen.assert_called_once_with("rec-777", profile=None)
        # fingerprint_bump no-double-count: the reopen path never ALSO calls the open-match
        # bumper directly -- reopen_ci_rca_rec owns its own single internal bump.
        mock_bump.assert_not_called()
        mock_write.assert_not_called()

    def test_close_then_recur_backstop_out_of_window_falls_through_to_insert(self, tmp_path: Path, monkeypatch):
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value=None),
            patch.object(p, "find_recent_ci_rca_rec_by_fingerprint", return_value=None) as mock_find_recent,
            patch.object(p, "reopen_ci_rca_rec") as mock_reopen,
            patch.object(p, "_ducklake_write", return_value={"key": "rec-888"}) as mock_write,
            patch.object(p, "RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.sync.ops.upsert_cache_row"),
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-888"
        mock_find_recent.assert_called_once()
        mock_reopen.assert_not_called()
        mock_write.assert_called_once()

    def test_fingerprint_bump_open_match_never_consults_recent_finder(self, tmp_path: Path, monkeypatch):
        """The open-match path and the recently-closed reopen path are mutually exclusive: an
        OPEN hit returns immediately via the existing single bump, never touching
        find_recent_ci_rca_rec_by_fingerprint / reopen_ci_rca_rec -- so occurrence can never
        double-count across the two paths (Risk B)."""
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value="rec-555"),
            patch.object(p, "bump_ci_rca_occurrence") as mock_bump,
            patch.object(p, "find_recent_ci_rca_rec_by_fingerprint") as mock_find_recent,
            patch.object(p, "reopen_ci_rca_rec") as mock_reopen,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-555"
        mock_bump.assert_called_once_with("rec-555", profile=None)
        mock_find_recent.assert_not_called()
        mock_reopen.assert_not_called()
