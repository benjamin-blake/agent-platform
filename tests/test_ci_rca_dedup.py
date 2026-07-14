"""Unit tests for scripts.ci_rca.dedup (100% coverage).

All tests inject finder/bumper callables -- no live DuckLake reader or portal writes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ci_rca.convergence_dedup import (
    ConvergenceCauseHit,
    _default_commit_status_checker,
    find_open_convergence_cause_rec,
)
from scripts.ci_rca.convergence_dedup import main as convergence_main
from scripts.ci_rca.dedup import BundleVerdict, DedupResult, _load_fingerprints, decide, main


class TestDecide:
    def test_all_bundles_matched_dedupes(self):
        finder = MagicMock(side_effect=lambda fp: {"fp-a": "rec-1", "fp-b": "rec-2"}[fp])
        bumper = MagicMock()
        result = decide(["fp-a", "fp-b"], finder=finder, bumper=bumper)

        assert result.run_agent is False
        assert result.deduped is True
        assert bumper.call_count == 2
        bumper.assert_any_call("rec-1")
        bumper.assert_any_call("rec-2")

    def test_novel_fingerprint_always_runs_agent(self):
        """Decision 55 guard: a genuinely-novel fingerprint always results in run-agent."""
        finder = MagicMock(return_value=None)
        bumper = MagicMock()
        result = decide(["fp-novel"], finder=finder, bumper=bumper)

        assert result.run_agent is True
        assert result.deduped is False
        bumper.assert_not_called()

    def test_mixed_set_runs_agent_but_still_bumps_matched(self):
        """A matched bundle is skipped+bumped independently of a co-occurring novel bundle --
        the fix for the all-or-nothing bug (a single miss no longer skips bumping the rest)."""
        finder = MagicMock(side_effect=lambda fp: {"fp-matched": "rec-1", "fp-novel": None}[fp])
        bumper = MagicMock()
        result = decide(["fp-matched", "fp-novel"], finder=finder, bumper=bumper)

        assert result.run_agent is True
        bumper.assert_called_once_with("rec-1")
        verdicts = {v.fingerprint: v for v in result.verdicts}
        assert verdicts["fp-matched"].run_agent is False
        assert verdicts["fp-matched"].matched_rec_id == "rec-1"
        assert verdicts["fp-novel"].run_agent is True
        assert verdicts["fp-novel"].matched_rec_id is None

    def test_force_rca_bypasses_all_lookups(self):
        finder = MagicMock()
        bumper = MagicMock()
        result = decide(["fp-a", "fp-b"], force_rca=True, finder=finder, bumper=bumper)

        assert result.run_agent is True
        assert result.force_rca is True
        finder.assert_not_called()
        bumper.assert_not_called()

    def test_empty_fingerprint_list_fails_closed(self):
        """Zero evidence bundles at all -- fail closed (Decision 55), run the agent."""
        finder = MagicMock()
        result = decide([], finder=finder)

        assert result.run_agent is True
        assert result.verdicts == []
        finder.assert_not_called()

    def test_missing_fingerprint_string_treated_as_novel(self):
        finder = MagicMock()
        bumper = MagicMock()
        result = decide([""], finder=finder, bumper=bumper)

        assert result.run_agent is True
        finder.assert_not_called()
        bumper.assert_not_called()
        assert result.verdicts[0].matched_rec_id is None

    def test_default_finder_and_bumper_used_when_not_injected(self):
        """No finder/bumper injected -- falls back to the real ci_rca_runtime helpers."""
        import scripts.ci_rca.dedup as dedup_mod

        with (
            pytest.MonkeyPatch.context() as mp,
        ):
            mock_find = MagicMock(return_value="rec-9")
            mock_bump = MagicMock()
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: mock_find(fp))
            mp.setattr(dedup_mod, "_default_bumper", lambda rec_id, profile=None: mock_bump(rec_id))
            result = decide(["fp-a"])

        assert result.deduped is True
        mock_find.assert_called_once_with("fp-a")
        mock_bump.assert_called_once_with("rec-9")


class TestLoadFingerprints:
    def test_reads_fingerprint_from_each_bundle(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))
        (tmp_path / "b.json").write_text(json.dumps({"fingerprint": "fp-b"}))

        fps = _load_fingerprints(tmp_path)

        assert sorted(fps) == ["fp-a", "fp-b"]

    def test_missing_fingerprint_key_yields_empty_string(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"failure_category": "unknown"}))

        fps = _load_fingerprints(tmp_path)

        assert fps == [""]

    def test_malformed_json_yields_empty_string(self, tmp_path: Path):
        (tmp_path / "a.json").write_text("not-json{")

        fps = _load_fingerprints(tmp_path)

        assert fps == [""]

    def test_no_bundle_files_yields_empty_list(self, tmp_path: Path):
        assert _load_fingerprints(tmp_path) == []


class TestMain:
    def test_deduped_true_when_all_matched(self, tmp_path: Path, capsys):
        import scripts.ci_rca.dedup as dedup_mod

        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: "rec-1")
            mp.setattr(dedup_mod, "_default_bumper", lambda rec_id, profile=None: None)
            rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=true" in out
        assert "matches open rec-1" in out

    def test_deduped_false_on_novel(self, tmp_path: Path, capsys):
        import scripts.ci_rca.dedup as dedup_mod

        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-novel"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: None)
            rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "has no open match" in out

    def test_force_rca_flag(self, tmp_path: Path, capsys):
        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))

        rc = main(["--bundles-dir", str(tmp_path), "--force-rca"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "force_rca=true" in out

    def test_missing_bundles_dir_treated_as_no_evidence(self, tmp_path: Path, capsys):
        rc = main(["--bundles-dir", str(tmp_path / "nonexistent")])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "No evidence bundles found" in out

    def test_bundle_with_no_fingerprint_prints_marker(self, tmp_path: Path, capsys):
        (tmp_path / "a.json").write_text(json.dumps({"failure_category": "unknown"}))

        rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "Bundle has no fingerprint" in out


class TestDataclasses:
    def test_bundle_verdict_fields(self):
        v = BundleVerdict(fingerprint="fp-a", matched_rec_id="rec-1", run_agent=False)
        assert v.fingerprint == "fp-a"
        assert v.matched_rec_id == "rec-1"
        assert v.run_agent is False


class TestFindOpenConvergenceCauseRec:
    """Cause-aware CONVERGENCE_RED dedup decision (PLAN-ci-rca-convergence-dedup,
    acceptance criterion 2). All lookups injected -- no live DuckLake reader or gh call."""

    def test_drift_red_matches_open_tf_drift_rec_by_url(self):
        record = {"status": "red", "commit_sha": "ed22aa46", "drift_run_url": "https://x/runs/999"}
        drift_finder = MagicMock(return_value="rec-2695")
        status_checker = MagicMock()

        hit = find_open_convergence_cause_rec(record, drift_rec_finder=drift_finder, commit_status_checker=status_checker)

        assert hit == ConvergenceCauseHit(cause_rec="rec-2695", cause_kind="tf_drift")
        drift_finder.assert_called_once_with("https://x/runs/999")
        status_checker.assert_not_called()

    def test_drift_red_no_match_returns_none_without_checking_commit_status(self):
        """Drift-red and apply-failure-red are mutually exclusive branches -- a drift_run_url
        that fails to match never falls through to the commit-status check."""
        record = {"status": "red", "commit_sha": "ed22aa46", "drift_run_url": "https://x/runs/999"}
        drift_finder = MagicMock(return_value=None)
        status_checker = MagicMock()

        hit = find_open_convergence_cause_rec(record, drift_rec_finder=drift_finder, commit_status_checker=status_checker)

        assert hit is None
        status_checker.assert_not_called()

    def test_apply_failure_red_matches_prior_non_convergence_status(self):
        record = {"status": "red", "commit_sha": "50f3a90"}
        drift_finder = MagicMock()
        status_checker = MagicMock(return_value="rec-2690")

        hit = find_open_convergence_cause_rec(record, drift_rec_finder=drift_finder, commit_status_checker=status_checker)

        assert hit == ConvergenceCauseHit(cause_rec="rec-2690", cause_kind="ci_rca")
        drift_finder.assert_not_called()
        status_checker.assert_called_once_with("50f3a90")

    def test_neither_backed_key_matches_returns_none(self):
        record = {"status": "red", "commit_sha": "deadbeef"}

        hit = find_open_convergence_cause_rec(
            record,
            drift_rec_finder=MagicMock(return_value=None),
            commit_status_checker=MagicMock(return_value=None),
        )

        assert hit is None

    def test_no_commit_sha_and_no_drift_url_returns_none(self):
        hit = find_open_convergence_cause_rec({}, drift_rec_finder=MagicMock(), commit_status_checker=MagicMock())
        assert hit is None


class TestDefaultDriftRecFinder:
    """Real (non-injected) tf_drift lookup: open source=tf_drift recs whose context embeds
    drift_run_url, via the closed DuckLake reader boundary (Decision 84 I-3, no caller SQL)."""

    def test_matches_open_rec_by_url_embed(self):
        from scripts.ci_rca.convergence_dedup import _default_drift_rec_finder

        url = "https://github.com/x/y/actions/runs/999"
        rows = [
            {"id": "rec-1", "status": "closed", "context": f"drift run {url}"},
            {"id": "rec-2695", "status": "open", "context": f"Review the drift in GitHub Actions run {url}."},
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            result = _default_drift_rec_finder(url)
        assert result == "rec-2695"
        reader.current_state.assert_called_once_with("ops_recommendations", row_filter="source = 'tf_drift'")

    def test_no_match_returns_none(self):
        from scripts.ci_rca.convergence_dedup import _default_drift_rec_finder

        reader = MagicMock()
        reader.current_state.return_value = [{"id": "rec-1", "status": "open", "context": "unrelated"}]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert _default_drift_rec_finder("https://x/runs/999") is None

    def test_closed_rec_with_matching_url_not_returned(self):
        from scripts.ci_rca.convergence_dedup import _default_drift_rec_finder

        url = "https://x/runs/999"
        reader = MagicMock()
        reader.current_state.return_value = [{"id": "rec-1", "status": "closed", "context": f"run {url}"}]
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert _default_drift_rec_finder(url) is None

    def test_reader_unreachable_fails_open(self, caplog):
        """A transient DuckLake reader outage must not crash the ci-rca.yml Dedup guard step --
        fails open (returns None) so the refusal files as the fallback red-surface, mirroring
        find_open_ci_rca_rec_by_fingerprint's contract (ci_rca_runtime.py)."""
        from scripts.ci_rca.convergence_dedup import _default_drift_rec_finder

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("ducklake_reader 'read_ops_current' failed (HTTP 503): ...")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with caplog.at_level(logging.WARNING):
                result = _default_drift_rec_finder("https://x/runs/999")
        assert result is None
        assert any("reader unreachable" in rec.message.lower() for rec in caplog.records)

    def test_unexpected_reader_error_raises(self):
        """Any OTHER exception is NOT reader-unreachable and must propagate (Decision 55)."""
        from scripts.ci_rca.convergence_dedup import _default_drift_rec_finder

        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("boom -- unrelated to connectivity")
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            with pytest.raises(RuntimeError, match="boom"):
                _default_drift_rec_finder("https://x/runs/999")


class TestDefaultCommitStatusChecker:
    """Real (non-injected) commit-status matcher: never matches ONLY on backed keys -- a
    non-convergence_refused ci-rca/terraform-apply-sandbox/* SUCCESS status, rec id parsed from
    the same description string ci-rca.yml's mark_rca step posts (ci-rca.yml:358-369)."""

    def test_matches_non_convergence_success_status(self):
        statuses = [
            {
                "context": "ci-rca/terraform-apply-sandbox/convergence_refused",
                "state": "success",
                "description": "ci-rca filed rec-9999 for this failure",
            },
            {
                "context": "ci-rca/terraform-apply-sandbox/environment",
                "state": "success",
                "description": "ci-rca filed rec-2690 for this failure",
            },
        ]
        assert _default_commit_status_checker("50f3a90", statuses) == "rec-2690"

    def test_convergence_refused_context_never_matches(self):
        """Risk A: the check must NOT re-match the refusal's own category -- only a DIFFERENT,
        non-convergence category anchors the apply-failure branch."""
        statuses = [
            {
                "context": "ci-rca/terraform-apply-sandbox/convergence_refused",
                "state": "success",
                "description": "ci-rca filed rec-9999 for this failure",
            }
        ]
        assert _default_commit_status_checker("50f3a90", statuses) is None

    def test_pending_state_does_not_match(self):
        statuses = [
            {
                "context": "ci-rca/terraform-apply-sandbox/environment",
                "state": "pending",
                "description": "ci-rca filed rec-2690 for this failure",
            }
        ]
        assert _default_commit_status_checker("50f3a90", statuses) is None

    def test_unrelated_context_prefix_ignored(self):
        statuses = [
            {"context": "some-other-check/foo", "state": "success", "description": "ci-rca filed rec-1 for this failure"}
        ]
        assert _default_commit_status_checker("50f3a90", statuses) is None

    def test_no_statuses_returns_none(self):
        assert _default_commit_status_checker("50f3a90", []) is None

    def test_description_without_marker_yields_none(self):
        statuses = [
            {"context": "ci-rca/terraform-apply-sandbox/environment", "state": "success", "description": "unrelated text"}
        ]
        assert _default_commit_status_checker("50f3a90", statuses) is None


class TestConvergenceDedupMain:
    def test_drift_hit_prints_already_filed_true(self, tmp_path: Path, capsys):
        import scripts.ci_rca.convergence_dedup as conv_mod

        record_path = tmp_path / "record.json"
        record_path.write_text(json.dumps({"status": "red", "commit_sha": "ed22aa46", "drift_run_url": "https://x/runs/999"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(conv_mod, "_default_drift_rec_finder", lambda url, profile=None: "rec-2695")
            rc = convergence_main(["--record", str(record_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "already_filed=true" in out
        assert "cause_rec=rec-2695" in out
        assert "cause_kind=tf_drift" in out

    def test_no_hit_prints_already_filed_false(self, tmp_path: Path, capsys):
        import scripts.ci_rca.convergence_dedup as conv_mod

        record_path = tmp_path / "record.json"
        record_path.write_text(json.dumps({"status": "red", "commit_sha": "deadbeef"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(conv_mod, "_default_drift_rec_finder", lambda url, profile=None: None)
            rc = convergence_main(["--record", str(record_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "already_filed=false" in out

    def test_apply_failure_hit_via_commit_statuses_file(self, tmp_path: Path, capsys):
        record_path = tmp_path / "record.json"
        record_path.write_text(json.dumps({"status": "red", "commit_sha": "50f3a90"}))
        statuses_path = tmp_path / "statuses.json"
        statuses_path.write_text(
            json.dumps(
                [
                    {
                        "context": "ci-rca/terraform-apply-sandbox/environment",
                        "state": "success",
                        "description": "ci-rca filed rec-2690 for this failure",
                    }
                ]
            )
        )

        rc = convergence_main(["--record", str(record_path), "--commit-statuses", str(statuses_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "already_filed=true" in out
        assert "cause_rec=rec-2690" in out
        assert "cause_kind=ci_rca" in out

    def test_missing_commit_statuses_file_treated_as_empty(self, tmp_path: Path, capsys):
        record_path = tmp_path / "record.json"
        record_path.write_text(json.dumps({"status": "red", "commit_sha": "50f3a90"}))

        rc = convergence_main(["--record", str(record_path), "--commit-statuses", str(tmp_path / "nonexistent.json")])

        out = capsys.readouterr().out
        assert rc == 0
        assert "already_filed=false" in out

    def test_dedup_result_deduped_property(self):
        assert DedupResult(run_agent=True).deduped is False
        assert DedupResult(run_agent=False).deduped is True
