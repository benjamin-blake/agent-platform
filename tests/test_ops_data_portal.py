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
from pydantic import ValidationError  # noqa: E402

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
