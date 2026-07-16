"""Prompt-hash, diff-capture, and step/session telemetry tests (rec-2709 Wave 2)."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    ExecutionPlan,
    commit_step,
    execute_recommendation,
    generate_initial_plan,
    load_prompt,
)
from scripts.executor.step_runner import StepOutcome


class TestPromptHashing:
    """Tests for load_prompt() tuple return and SHA-256 hash."""

    def test_load_prompt_returns_tuple(self, tmp_path):
        """load_prompt returns a (str, str) tuple."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "demo.prompt.md").write_text("# Demo prompt", encoding="utf-8")

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            result = load_prompt("demo")

        assert isinstance(result, tuple), f"load_prompt should return tuple, got {type(result)}"
        assert len(result) == 2, f"Expected tuple of length 2, got {len(result)}"
        template, prompt_hash = result
        assert isinstance(template, str), f"Template should be str, got {type(template)}"
        assert isinstance(prompt_hash, str), f"Hash should be str, got {type(prompt_hash)}"

    def test_prompt_hash_is_deterministic(self, tmp_path):
        """Same content always produces the same hash."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "stable.prompt.md").write_text("Stable content", encoding="utf-8")

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            _, hash1 = load_prompt("stable")
            _, hash2 = load_prompt("stable")

        assert hash1 == hash2, f"Same content should produce same hash, got {hash1} != {hash2}"

    def test_prompt_hash_is_12_chars(self, tmp_path):
        """Hash is exactly 12 hex characters."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "any.prompt.md").write_text("Any content here", encoding="utf-8")

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            _, prompt_hash = load_prompt("any")

        assert len(prompt_hash) == 12, f"Hash length should be 12, got {len(prompt_hash)}"
        assert all(c in "0123456789abcdef" for c in prompt_hash), f"Hash should be hex, got {prompt_hash}"

    def test_different_content_produces_different_hash(self, tmp_path):
        """Different file contents produce different hashes."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "v1.prompt.md").write_text("Version 1", encoding="utf-8")
        (prompts_dir / "v2.prompt.md").write_text("Version 2", encoding="utf-8")

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            _, hash1 = load_prompt("v1")
            _, hash2 = load_prompt("v2")

        assert hash1 != hash2, f"Different content should produce different hashes, got {hash1} == {hash2}"

    def test_execution_plan_stores_prompt_hash(self, tmp_path):
        """ExecutionPlan.prompt_hash is populated from generate_initial_plan()."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "planning.prompt.md").write_text(
            "Plan for {rec_id} {title} {context} {file} {acceptance} {dependencies} {effort}",
            encoding="utf-8",
        )

        rec = {"id": "rec-test", "title": "Test", "slug": "test"}
        plan_output = "### Step 1: Do thing\n**File**: src/x.py\n**Action**: modify\n**Description**: test\n"

        with (
            patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir),
            patch("scripts.executor.plan.llm_call") as mock_call,
        ):
            mock_call.return_value = MagicMock(exit_code=0, content=plan_output, tokens_in=10, tokens_out=0, model="test")
            plan = generate_initial_plan(rec)

        assert isinstance(plan.prompt_hash, str), f"prompt_hash should be str, got {type(plan.prompt_hash)}"
        assert len(plan.prompt_hash) == 12, f"prompt_hash length should be 12, got {len(plan.prompt_hash)}"


class TestDiffCapture:
    """Tests for commit_step() diff stat capture."""

    def test_commit_step_returns_diff_stat(self):
        """Successful commit captures and returns diff stat string."""
        step = {"n": 1, "title": "Add feature", "file": "scripts/foo.py"}

        def run_side_effect(cmd, **kwargs):
            m = MagicMock(returncode=0, stdout="", stderr="")
            if cmd[0] == "git" and cmd[1] == "diff":
                m.stdout = " scripts/foo.py | 5 +++++\n 1 file changed, 5 insertions(+)"
            return m

        with (
            patch(
                "scripts.executor.step_runner._enforce_step_scope",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                side_effect=run_side_effect,
            ),
        ):
            success, diff_stat = commit_step(step, "rec-test", 1)

        assert success is True, f"commit_step should succeed, got {success}"
        assert "file changed" in diff_stat, f"diff_stat should contain 'file changed', got {diff_stat}"

    def test_commit_step_diff_fallback_on_error(self):
        """If git diff fails, diff_stat is empty string and commit still succeeds."""
        step = {"n": 1, "title": "Add feature", "file": "scripts/foo.py"}
        call_count = 0

        def run_side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock(returncode=0, stdout="", stderr="")
            if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "diff":
                m.returncode = 128
                m.stdout = ""
            return m

        with (
            patch(
                "scripts.executor.step_runner._enforce_step_scope",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                side_effect=run_side_effect,
            ),
        ):
            success, diff_stat = commit_step(step, "rec-test", 1)

        assert success is True, f"commit_step should succeed even if diff fails, got {success}"
        assert diff_stat == "", f"diff_stat should be empty on diff failure, got {diff_stat}"

    def test_commit_step_nothing_to_commit_returns_empty_diff(self):
        """'Nothing to commit' CalledProcessError returns (True, '')."""
        step = {"n": 1, "title": "No-op step", "file": "scripts/foo.py"}

        with (
            patch(
                "scripts.executor.step_runner._enforce_step_scope",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
            ) as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(
                1,
                "git",
                stderr="nothing to commit, working tree clean",
            )
            success, diff_stat = commit_step(step, "rec-test", 1)

        assert success is True, f"'Nothing to commit' should be success, got {success}"
        assert diff_stat == "", f"diff_stat should be empty for 'nothing to commit', got {diff_stat}"


class TestStepTelemetryPersistence:
    """Tests for _append_step_telemetry() JSONL persistence."""

    def test_step_telemetry_writes_to_jsonl(self, tmp_path):
        """_append_step_telemetry writes a valid JSON entry to the telemetry file."""
        from scripts.execute_recommendation import _append_step_telemetry

        telemetry_file = tmp_path / "logs" / ".execution-step-telemetry.jsonl"
        telemetry_file.parent.mkdir(parents=True)

        with patch("scripts.executor.step_runner.STEP_TELEMETRY_JSONL", telemetry_file):
            _append_step_telemetry(
                rec_id="rec-100",
                step_n=1,
                total_steps=3,
                prompt_hash="abc123def456",  # pragma: allowlist secret
                diff_stat="1 file changed, 5 insertions(+)",
                model="claude-haiku-4.5",
            )

        lines = [ln for ln in telemetry_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1, f"Expected 1 line in telemetry file, got {len(lines)}"
        entry = json.loads(lines[0])
        assert entry["rec_id"] == "rec-100", f"Expected rec_id='rec-100', got {entry['rec_id']}"
        assert entry["step_n"] == 1, f"Expected step_n=1, got {entry['step_n']}"
        assert entry["total_steps"] == 3, f"Expected total_steps=3, got {entry['total_steps']}"
        assert entry["prompt_hash"] == "abc123def456", (  # pragma: allowlist secret
            f"Expected prompt_hash='abc123def456', got {entry['prompt_hash']}"  # pragma: allowlist secret
        )
        assert entry["diff_stat"] == "1 file changed, 5 insertions(+)", (
            f"Expected diff_stat='1 file changed, 5 insertions(+)', got {entry['diff_stat']}"
        )
        assert entry["model"] == "claude-haiku-4.5", f"Expected model='claude-haiku-4.5', got {entry['model']}"
        assert "timestamp" in entry, "Expected 'timestamp' in telemetry entry"

    def test_step_telemetry_appends_multiple_steps(self, tmp_path):
        """Multiple calls append multiple lines (one per step)."""
        from scripts.execute_recommendation import _append_step_telemetry

        telemetry_file = tmp_path / "logs" / ".execution-step-telemetry.jsonl"
        telemetry_file.parent.mkdir(parents=True)

        with patch("scripts.executor.step_runner.STEP_TELEMETRY_JSONL", telemetry_file):
            _append_step_telemetry("rec-100", 1, 2, "hash1", "", "claude-haiku-4.5")
            _append_step_telemetry("rec-100", 2, 2, "hash2", "2 files changed", "claude-haiku-4.5")

        lines = [ln for ln in telemetry_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2, f"Expected 2 lines in telemetry file, got {len(lines)}"
        e1 = json.loads(lines[0])
        e2 = json.loads(lines[1])
        assert e1["step_n"] == 1, f"Expected first entry step_n=1, got {e1['step_n']}"
        assert e2["step_n"] == 2, f"Expected second entry step_n=2, got {e2['step_n']}"
        assert e2["diff_stat"] == "2 files changed", (
            f"Expected second entry diff_stat='2 files changed', got {e2['diff_stat']}"
        )

    def test_step_telemetry_os_error_does_not_raise(self, tmp_path):
        """OSError on write is caught and logged â€” does not raise."""
        from scripts.execute_recommendation import _append_step_telemetry

        # Point to a path that cannot be created (file as parent)
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("block", encoding="utf-8")
        bad_path = blocker / ".execution-step-telemetry.jsonl"

        with patch("scripts.executor.step_runner.STEP_TELEMETRY_JSONL", bad_path):
            try:
                _append_step_telemetry("rec-100", 1, 1, "", "", "")
            except Exception as exc:
                pytest.fail(f"_append_step_telemetry raised unexpectedly: {exc}")

    def test_execution_loop_persists_telemetry_per_step(self, tmp_path):
        """Full execution loop calls _append_step_telemetry once per completed step."""
        plans_file = tmp_path / "logs" / ".execution-plans.jsonl"
        plans_file.parent.mkdir(parents=True)
        plans_file.write_text("")

        approved_plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {"n": 1, "title": "Step 1", "file": "", "action": "modify", "description": "", "acceptance": ""},
                {"n": 2, "title": "Step 2", "file": "", "action": "modify", "description": "", "acceptance": ""},
            ],
            plan_text="",
        )

        mock_validate = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch("scripts.execute_recommendation.ensure_feature_branch") as mock_branch,
            patch("scripts.execute_recommendation.load_checkpoint") as mock_load_ck,
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry") as mock_telemetry,
            patch("scripts.execute_recommendation.finalize") as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, [])),
            patch("scripts.execute_recommendation.subprocess.run", return_value=mock_validate),
        ):
            mock_load.return_value = {"id": "rec-100", "title": "Test", "risk": "low", "automatable": True, "effort": "S"}
            mock_branch.return_value = True
            mock_load_ck.return_value = None
            mock_latest.return_value = None
            mock_gen.return_value = approved_plan
            mock_impl.return_value = (StepOutcome.SUCCESS, 0.33, "abc123def456", "ses-step")  # pragma: allowlist secret
            mock_commit.return_value = (True, "1 file changed")
            mock_finalize.return_value = "https://github.com/pr/1"

            execute_recommendation("rec-100", skip_critique=True)

        # Telemetry written once per step (2 steps)
        assert mock_telemetry.call_count == 2
        call1 = mock_telemetry.call_args_list[0]
        assert call1.kwargs["rec_id"] == "rec-100"
        assert call1.kwargs["step_n"] == 1
        assert call1.kwargs["prompt_hash"] == "abc123def456"  # pragma: allowlist secret
        assert call1.kwargs["diff_stat"] == "1 file changed"


class TestSessionTelemetry:
    """Verify session/phase telemetry calls in _execute_recommendation_inner."""

    def _base_patches(self):
        return (
            patch("scripts.execute_recommendation.open_session"),
            patch("scripts.execute_recommendation.close_session"),
            patch("scripts.execute_recommendation.open_phase"),
            patch("scripts.execute_recommendation.close_phase"),
            patch("scripts.execute_recommendation.emit_process_event"),
            patch("scripts.execute_recommendation.load_recommendation", return_value=None),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.emit_failure_summary"),
        )

    def test_session_opened_on_entry(self) -> None:
        """open_session is called with workflow='executor' on entering _execute_recommendation_inner."""
        with (
            patch("scripts.execute_recommendation.open_session") as mock_open_session,
            patch("scripts.execute_recommendation.close_session"),
            patch("scripts.execute_recommendation.open_phase"),
            patch("scripts.execute_recommendation.close_phase"),
            patch("scripts.execute_recommendation.emit_process_event"),
            patch("scripts.execute_recommendation.load_recommendation", return_value=None),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.emit_failure_summary"),
        ):
            execute_recommendation("rec-tel-001")

        mock_open_session.assert_called_once()
        assert mock_open_session.call_args.kwargs.get("workflow") == "executor"

    def test_session_closed_with_failed_outcome_on_early_failure(self) -> None:
        """close_session is called with outcome='failed' when a Phase 1 gate fails."""
        with (
            patch("scripts.execute_recommendation.open_session"),
            patch("scripts.execute_recommendation.close_session") as mock_close_session,
            patch("scripts.execute_recommendation.open_phase"),
            patch("scripts.execute_recommendation.close_phase"),
            patch("scripts.execute_recommendation.emit_process_event"),
            patch("scripts.execute_recommendation.load_recommendation", return_value=None),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.emit_failure_summary"),
        ):
            execute_recommendation("rec-tel-002")

        mock_close_session.assert_called_once()
        assert mock_close_session.call_args.kwargs.get("outcome") == "failed"

    def test_phase_opened_with_preflight_on_entry(self) -> None:
        """open_phase is called with phase='preflight' at the start of Phase 1."""
        with (
            patch("scripts.execute_recommendation.open_session"),
            patch("scripts.execute_recommendation.close_session"),
            patch("scripts.execute_recommendation.open_phase") as mock_open_phase,
            patch("scripts.execute_recommendation.close_phase"),
            patch("scripts.execute_recommendation.emit_process_event"),
            patch("scripts.execute_recommendation.load_recommendation", return_value=None),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.emit_failure_summary"),
        ):
            execute_recommendation("rec-tel-003")

        mock_open_phase.assert_called_once()
        assert mock_open_phase.call_args.kwargs.get("phase") == "preflight"
