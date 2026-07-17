"""Tests for find_open_ci_rca_rec_by_fingerprint(), the file_rec() write-time dedup backstop
(open-match bump path), and the bundle-derived fingerprint/failure_category stamp inside
_run_ci_rca_cross_check() (CIRCA-03).

Split out of the former tests/test_ops_data_portal.py monolith (rec-2709 Wave 3). This class
was 501 SLOC (OVER the 500-SLOC budget) and is resolved by a PRIMARY concern-split into two
sibling classes across two modules (Decision 128 forbids a raise; Wave 1 OPEN-RISK-1
precedent) rather than a config/sloc_budgets.yaml raise marker: TestCiRcaFingerprintDedup here
keeps the guard/fingerprint/backstop/bump cohort. The closed-head regression-vs-drop cohort
(ci-rca-identity-lifecycle, Decision 136 -- formerly the rec-2644 close-then-recur cohort) lives
in the sibling class TestCiRcaClosedHeadRegression in test_ci_rca_close_then_recur.py. The rec-2707
backstop-reader guard (_guard_live_reader, autouse) formerly duplicated verbatim into both sibling
classes has since been retired (rec-2484): the global L1/L2 hermetic-AWS guard in the root
tests/conftest.py now supersedes it class-wide.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

duckdb = pytest.importorskip("duckdb")

from scripts.ops_portal import ci_rca_schema as _ci_rca_schema_mod  # noqa: E402
from tests.fixtures.ops_portal_records import VALID_FIELDS as _VALID_FIELDS  # noqa: E402


class TestCiRcaFingerprintDedup:
    """CIRCA-03: find_open_ci_rca_rec_by_fingerprint(), the write-time backstop, and the
    bundle-derived fingerprint/failure_category stamp inside _run_ci_rca_cross_check().

    The former per-class _guard_live_reader autouse fixture (rec-2707 backstop-reader guard)
    is retired: the global L1/L2 hermetic-AWS guard in the root tests/conftest.py (rec-2484)
    now blocks any un-mocked src.common.iceberg_reader.make_reader() -> boto3 client path
    class-wide, so the per-class duplicate is redundant. Its own behavior test lives in
    tests/test_conftest_hermeticity.py, not here.
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

    def test_cross_check_stamps_affected_nodeids_and_escape_class(self, tmp_path: Path):
        """ci-rca-identity-lifecycle: affected_nodeids/escape_class are stamped from the
        VERIFIED bundle, mirroring fingerprint/failure_category -- never agent-authored."""
        import scripts.ops_data_portal as p

        sha, bundle_data = self._make_bundle(
            tmp_path, affected_nodeids=["tests/test_a.py::test_a"], escape_class="capped"
        )
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)
        assert ctx["affected_nodeids"] == bundle_data["affected_nodeids"]
        assert ctx["escape_class"] == bundle_data["escape_class"]

    def test_cross_check_no_affected_nodeids_or_escape_class_leaves_unset(self, tmp_path: Path):
        """A bundle carrying neither field (e.g. no junit report, no selection manifest) never
        stamps them -- absence is not itself a signal."""
        import scripts.ops_data_portal as p

        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)
        assert "affected_nodeids" not in ctx
        assert "escape_class" not in ctx

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
            patch.object(p, "bump_ci_rca_occurrence") as mock_bump,
            patch.object(p, "_ducklake_write") as mock_write,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-999"
        mock_find.assert_called_once_with(self._FINGERPRINT, profile=None)
        mock_bump.assert_called_once_with("rec-999", profile=None)
        mock_write.assert_not_called()

    def test_file_rec_backstop_inserts_on_fingerprint_miss(self, tmp_path: Path, monkeypatch):
        """No open match AND no closed head at all (genuinely novel fingerprint) -- normal insert.
        ci-rca-identity-lifecycle: the rec-2644 recency-finder revive check is retired; the
        closed-head path is now closed_head_of_chain (see
        tests/ops_data_portal/test_ci_rca_close_then_recur.py for its full coverage)."""
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value=None) as mock_find,
            patch.object(p, "closed_head_of_chain", return_value=None),
            patch.object(p, "_ducklake_write", return_value={"key": "rec-800"}) as mock_write,
            patch.object(p, "RECS_JSONL", tmp_path / "recs.jsonl"),
            patch("scripts.sync.ops.upsert_cache_row"),
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
            patch("scripts.sync.ops.upsert_cache_row"),
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-801"
        mock_find.assert_not_called()

    def test_file_rec_backstop_bumps_occurrence(self, tmp_path: Path, monkeypatch):
        """The write-time backstop returns the existing id AND bumps occurrence_count/last_seen
        via bump_ci_rca_occurrence -- CIRCA-03(c): both dedup paths now record recurrence.

        file_rec is facade-resident (Decision 124 case (a)): patch bump_ci_rca_occurrence's
        transitive deps (_fetch_rec_from_reader / update_rec) at the FACADE scripts.ops_data_portal
        namespace -- bump_ci_rca_occurrence does a deferred `from scripts.ops_data_portal import
        _fetch_rec_from_reader, update_rec` at call time, so patching at scripts.ops_portal.ci_rca_runtime
        would not intercept it.
        """
        import scripts.ops_data_portal as p

        monkeypatch.delenv("CI_RCA_FORCE_RCA", raising=False)
        sha, _ = self._make_bundle(tmp_path)
        ctx = self._ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        fields = {**_VALID_FIELDS, "source": "ci_rca"}
        existing_ctx = json.dumps({"fingerprint": self._FINGERPRINT, "occurrence_count": 1})

        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch.object(p, "find_open_ci_rca_rec_by_fingerprint", return_value="rec-999"),
            patch.object(p, "_fetch_rec_from_reader", return_value={"id": "rec-999", "context_v2_json": existing_ctx}),
            patch.object(p, "update_rec", return_value=True) as mock_update,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-999"
        mock_update.assert_called_once()
        call_args, call_kwargs = mock_update.call_args
        assert call_args[0] == "rec-999"
        updated_ctx = json.loads(call_args[1]["context_v2_json"])
        assert updated_ctx["occurrence_count"] == 2
        assert "last_seen" in updated_ctx

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
