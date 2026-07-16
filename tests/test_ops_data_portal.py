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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

duckdb = pytest.importorskip("duckdb")

from scripts.ops_portal import ci_rca_schema as _ci_rca_schema_mod  # noqa: E402

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


_CI_RCA_FIELDS = {
    **_VALID_FIELDS,
    "source": "ci_rca",
    "context": ("CI RCA test rec with sufficient length to satisfy the 80-char minimum for the legacy context column field."),
}

_VALID_CONTEXT_V2 = {
    "schema_version": 1,
    "proximate_cause": (
        "validate_sloc_limits() raised: scripts/roadmap/product_roadmap.py is 810 SLOC, exceeds 500 limit "
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


class TestCiRcaFingerprintDedup:
    """CIRCA-03: find_open_ci_rca_rec_by_fingerprint(), the write-time backstop, and the
    bundle-derived fingerprint/failure_category stamp inside _run_ci_rca_cross_check()."""

    _FINGERPRINT = "a" * 64

    @pytest.fixture(autouse=True)
    def _guard_live_reader(self):
        """Class-scoped backstop: any dedup-path test that forgets to mock
        find_open_ci_rca_rec_by_fingerprint / find_recent_ci_rca_rec_by_fingerprint would
        otherwise fall through to a live src.common.iceberg_reader.make_reader() call. On this
        container that call SUCCEEDS (working assume-role creds) and silently masks the leak;
        on the GitHub-hosted CI runner (no ~/.aws profile) it raises ProfileNotFound instead.
        Fail the same way everywhere: turn any un-mocked call into a deterministic
        AssertionError naming the missing mock (rec-2707)."""

        def _unmocked_make_reader(*args, **kwargs):
            raise AssertionError(
                "src.common.iceberg_reader.make_reader() called without a mock -- add "
                "patch.object(p, 'find_open_ci_rca_rec_by_fingerprint', ...) and/or "
                "patch.object(p, 'find_recent_ci_rca_rec_by_fingerprint', ...) to this test's "
                "with-block (rec-2707)."
            )

        with patch("src.common.iceberg_reader.make_reader", side_effect=_unmocked_make_reader):
            yield

    def test_guard_blocks_unmocked_reader(self):
        """Self-verifying meta-test: proves _guard_live_reader is active and targets the right
        dotted path -- an un-mocked src.common.iceberg_reader.make_reader() call must raise
        AssertionError, not silently succeed."""
        import src.common.iceberg_reader as iceberg_reader

        with pytest.raises(AssertionError):
            iceberg_reader.make_reader()

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
            patch.object(p, "bump_ci_rca_occurrence") as mock_bump,
            patch.object(p, "_ducklake_write") as mock_write,
        ):
            result = p.file_rec(dict(fields), context_v2_json=ctx)

        assert result == "rec-999"
        mock_find.assert_called_once_with(self._FINGERPRINT, profile=None)
        mock_bump.assert_called_once_with("rec-999", profile=None)
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
            patch.object(p, "find_recent_ci_rca_rec_by_fingerprint", return_value=None),
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
