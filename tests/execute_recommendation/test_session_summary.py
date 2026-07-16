"""clean_slate, session-status, and write_run_summary tests (rec-2709 Wave 2)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from scripts.execute_recommendation import (
    clean_slate,
    print_session_status,
    write_run_summary,
)


class TestCleanSlate:
    """Tests for clean_slate() idempotent retry cleanup."""

    @patch("scripts.execute_recommendation.load_recommendation")
    @patch("scripts.execute_recommendation._reset_rec_status")
    @patch("scripts.execute_recommendation.load_checkpoint")
    @patch("scripts.execute_recommendation.clear_checkpoint")
    @patch("scripts.execute_recommendation.subprocess.run")
    def test_happy_path_full_cleanup(self, mock_run, mock_clear_cp, mock_load_cp, mock_reset, mock_load_rec):
        """When rec has failed status and stale checkpoint, all cleanup steps run."""
        mock_run.return_value = MagicMock(returncode=0, stdout="  agent/rec-371\n", stderr="")
        mock_load_cp.return_value = {"plan_file": "rec-371"}
        mock_load_rec.return_value = {
            "id": "rec-371",
            "status": "failed",
        }

        clean_slate("rec-371")

        # Local branch listed then deleted
        assert mock_run.call_count >= 3
        # Checkpoint cleared
        mock_clear_cp.assert_called_once()
        # Status reset
        mock_reset.assert_called_once_with("rec-371")

    @patch("scripts.execute_recommendation.load_recommendation")
    @patch("scripts.execute_recommendation._reset_rec_status")
    @patch("scripts.execute_recommendation.load_checkpoint")
    @patch("scripts.execute_recommendation.clear_checkpoint")
    @patch("scripts.execute_recommendation.subprocess.run")
    def test_no_reset_when_status_not_failed(self, mock_run, mock_clear_cp, mock_load_cp, mock_reset, mock_load_rec):
        """Status is NOT reset when rec status is 'open' (not 'failed')."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_load_cp.return_value = None
        mock_load_rec.return_value = {
            "id": "rec-371",
            "status": "open",
        }

        clean_slate("rec-371")

        mock_reset.assert_not_called()
        mock_clear_cp.assert_not_called()

    @patch("scripts.execute_recommendation.load_recommendation")
    @patch("scripts.execute_recommendation._reset_rec_status")
    @patch("scripts.execute_recommendation.load_checkpoint")
    @patch("scripts.execute_recommendation.clear_checkpoint")
    @patch("scripts.execute_recommendation.subprocess.run")
    def test_checkpoint_only_cleared_for_matching_rec(self, mock_run, mock_clear_cp, mock_load_cp, mock_reset, mock_load_rec):
        """Checkpoint is NOT cleared when it references a different rec."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_load_cp.return_value = {"plan_file": "rec-999"}
        mock_load_rec.return_value = {
            "id": "rec-371",
            "status": "open",
        }

        clean_slate("rec-371")

        mock_clear_cp.assert_not_called()

    @patch("scripts.execute_recommendation.load_recommendation")
    @patch("scripts.execute_recommendation._reset_rec_status")
    @patch("scripts.execute_recommendation.load_checkpoint")
    @patch("scripts.execute_recommendation.clear_checkpoint")
    @patch("scripts.execute_recommendation.subprocess.run")
    def test_tolerates_subprocess_errors(self, mock_run, mock_clear_cp, mock_load_cp, mock_reset, mock_load_rec):
        """Subprocess failures are logged but do not raise."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)
        mock_load_cp.side_effect = Exception("disk error")
        mock_load_rec.side_effect = Exception("store error")

        # Should not raise
        clean_slate("rec-371")


class TestSessionStatus:
    """Tests for print_session_status() dashboard."""

    @patch("scripts.execute_recommendation.subprocess.run")
    def test_dashboard_with_run_summaries(self, mock_run, tmp_path, capsys):
        """Dashboard prints expected lines when run files exist."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        run_dir = tmp_path / "logs" / "runs"
        run_dir.mkdir(parents=True)

        s1 = {
            "rec_id": "rec-001",
            "outcome": "success",
            "timestamp_start": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / f"rec-001-{today}T100000.json").write_text(json.dumps(s1))

        s2 = {
            "rec_id": "rec-002",
            "outcome": "failure",
            "timestamp_start": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / f"rec-002-{today}T110000.json").write_text(json.dumps(s2))

        recs_jsonl = tmp_path / "logs" / ".recommendations-log.jsonl"
        today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        friction_entry = json.dumps(
            {
                "id": "rec-900",
                "source": "executor-supervision",
                "date": today_dash,
            }
        )
        recs_jsonl.write_text(friction_entry + "\n")

        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234 hotfix fix\n")

        print_session_status(root=tmp_path)

        out = capsys.readouterr().out
        assert "Recs attempted" in out
        assert "Friction" in out
        assert "closed: 1" in out
        assert "failed: 1" in out

    @patch("scripts.execute_recommendation.subprocess.run")
    def test_dashboard_zero_state(self, mock_run, tmp_path, capsys):
        """Dashboard works when no run files exist for today."""
        (tmp_path / "logs" / "runs").mkdir(parents=True)
        (tmp_path / "logs" / ".recommendations-log.jsonl").write_text("")

        mock_run.return_value = MagicMock(returncode=0, stdout="")

        print_session_status(root=tmp_path)

        out = capsys.readouterr().out
        assert "Recs attempted: 0" in out
        assert "Friction recs drafted: 0" in out
        assert "n/a" in out

    @patch("scripts.execute_recommendation.subprocess.run")
    def test_machinery_failure_ratio(self, mock_run, tmp_path, capsys):
        """Machinery failure ratio computed correctly."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        run_dir = tmp_path / "logs" / "runs"
        run_dir.mkdir(parents=True)

        for i, outcome in enumerate(["success", "success", "failure"]):
            s = {
                "rec_id": f"rec-{i:03d}",
                "outcome": outcome,
                "timestamp_start": datetime.now(timezone.utc).isoformat(),
            }
            fname = f"rec-{i:03d}-{today}T{10 + i}0000.json"
            (run_dir / fname).write_text(json.dumps(s))

        (tmp_path / "logs" / ".recommendations-log.jsonl").write_text("")

        mock_run.return_value = MagicMock(returncode=0, stdout="")

        print_session_status(root=tmp_path)

        out = capsys.readouterr().out
        assert "Machinery failure ratio: 1/3" in out


class TestWriteRunSummary:
    """Tests for the write_run_summary function."""

    def test_pytest_guard_skips_write(self, tmp_path, monkeypatch, _patch_write_run_summary):
        """PYTEST_CURRENT_TEST env var causes early return with no file I/O."""
        # _patch_write_run_summary is the autouse fixture; stop it so we
        # exercise the real function.
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_x.py::t")

            write_run_summary(
                rec_id="rec-999",
                branch="agent/rec-999",
                outcome="success",
                failure_reason=None,
                steps_completed=1,
                total_steps=1,
            )

            run_dir = tmp_path / "logs" / "runs"
            assert not run_dir.exists(), "logs/runs/ should not be created under PYTEST_CURRENT_TEST"
        finally:
            _patch_write_run_summary.start()

    def test_writes_json_without_guard(self, tmp_path, monkeypatch, _patch_write_run_summary):
        """Without PYTEST_CURRENT_TEST the summary JSON is written."""
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

            write_run_summary(
                rec_id="rec-500",
                branch="agent/rec-500",
                outcome="success",
                failure_reason=None,
                steps_completed=3,
                total_steps=3,
            )

            run_dir = tmp_path / "logs" / "runs"
            assert run_dir.exists(), "logs/runs/ directory should be created"
            files = list(run_dir.glob("rec-500-*.json"))
            assert len(files) == 1, f"Expected 1 summary file, found {len(files)}"

            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert data["rec_id"] == "rec-500"
            assert data["outcome"] == "success"
            assert data["steps_completed"] == 3
        finally:
            _patch_write_run_summary.start()

    def test_reads_step_telemetry(self, tmp_path, monkeypatch, _patch_write_run_summary):
        """Step telemetry entries for the rec are included in the summary."""
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            telemetry = logs_dir / ".execution-step-telemetry.jsonl"
            entries = [
                json.dumps(
                    {
                        "rec_id": "rec-600",
                        "step_n": 1,
                        "outcome": "pass",
                        "model": "gpt-5-mini",
                    }
                ),
                json.dumps(
                    {
                        "rec_id": "rec-other",
                        "step_n": 1,
                        "outcome": "pass",
                        "model": "gpt-5-mini",
                    }
                ),
            ]
            telemetry.write_text("\n".join(entries) + "\n")

            write_run_summary(
                rec_id="rec-600",
                branch="agent/rec-600",
                outcome="success",
                failure_reason=None,
                steps_completed=1,
                total_steps=1,
            )

            run_dir = tmp_path / "logs" / "runs"
            files = list(run_dir.glob("rec-600-*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert len(data["per_step_outcomes"]) == 1
            assert data["per_step_outcomes"][0]["step_n"] == 1
            assert data["per_step_outcomes"][0]["model"] == "gpt-5-mini"
        finally:
            _patch_write_run_summary.start()

    def test_postflight_validation_included(
        self,
        tmp_path,
        monkeypatch,
        _patch_write_run_summary,
    ):
        """postflight_validation dict is serialized into summary JSON."""
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

            pf_meta = {
                "mode": "presubmit",
                "result": "pass",
                "returncode": 0,
            }
            write_run_summary(
                rec_id="rec-700",
                branch="agent/rec-700",
                outcome="success",
                failure_reason=None,
                steps_completed=1,
                total_steps=1,
                postflight_validation=pf_meta,
            )

            run_dir = tmp_path / "logs" / "runs"
            files = list(run_dir.glob("rec-700-*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert data["postflight_validation"] == pf_meta
        finally:
            _patch_write_run_summary.start()

    def test_postflight_validation_omitted_when_none(
        self,
        tmp_path,
        monkeypatch,
        _patch_write_run_summary,
    ):
        """When postflight_validation is None the key is absent."""
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

            write_run_summary(
                rec_id="rec-701",
                branch="agent/rec-701",
                outcome="success",
                failure_reason=None,
                steps_completed=1,
                total_steps=1,
            )

            run_dir = tmp_path / "logs" / "runs"
            files = list(run_dir.glob("rec-701-*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert "postflight_validation" not in data
        finally:
            _patch_write_run_summary.start()

    def test_acceptance_output_included_when_provided(
        self,
        tmp_path,
        monkeypatch,
        _patch_write_run_summary,
    ):
        """acceptance_output is serialized into summary JSON when provided."""
        _patch_write_run_summary.stop()
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

            write_run_summary(
                rec_id="rec-702",
                branch="agent/rec-702",
                outcome="acceptance_fail",
                failure_reason="post-validation acceptance check failed",
                steps_completed=1,
                total_steps=1,
                acceptance_output="stdout line\nstderr line",
            )

            run_dir = tmp_path / "logs" / "runs"
            files = list(run_dir.glob("rec-702-*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert data["acceptance_output"] == "stdout line\nstderr line"
        finally:
            _patch_write_run_summary.start()
