"""Unit tests for scripts/execute_recommendation.py"""

import json
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.execute_recommendation import (
    AcceptanceFeasibility,
    ExecutionPlan,
    FailureSummary,
    _check_acceptance_on_main,
    _check_jsonl_clean,
    _checkout_main_safely,
    _code_review_gate,
    _get_quarantined_validation_failures,
    _handle_failure,
    _infer_failure_class,
    _scope_drift_check,
    clean_slate,
    commit_step,
    emit_failure_summary,
    execute_recommendation,
    generate_initial_plan,
    lint_acceptance_command,
    load_prompt,
    main,
    print_session_status,
    validate_acceptance_feasibility,
    write_run_summary,
)
from scripts.executor.step_runner import StepOutcome
from scripts.llm.utils import LLMResponseError

# ============================================================================
# New feature tests: CI wait, merge, cleanup, finalize auto-merge,
# checkpointing, batch orchestration, topological sort
# ============================================================================


# ============================================================================
# New feature tests: prompt hashing, diff capture, failure cleanup
# ============================================================================


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


class TestFailureCleanup:
    """Tests for _handle_failure() branch push + draft PR creation."""

    def _rec(self) -> dict:
        return {"id": "rec-100", "title": "Add caching layer"}

    def test_handle_failure_pushes_branch(self):
        """_handle_failure calls git push --set-upstream origin agent/rec-100."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _handle_failure("rec-100", rec, 2, "step 2 failed", 1, 5)

        calls = [c.args[0] for c in mock_run.call_args_list]
        push_call = next((c for c in calls if "push" in c), None)
        assert push_call is not None, "Expected push command to be called"
        assert "--set-upstream" in push_call, "Expected --set-upstream in push command"
        assert "origin" in push_call, "Expected origin in push command"
        assert "agent/rec-100" in push_call, "Expected agent/rec-100 in push command"

    def test_handle_failure_creates_draft_pr(self):
        """_handle_failure calls gh pr create --draft with [FAILED] title."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _handle_failure("rec-100", rec, 2, "step 2 failed", 1, 5)

        calls = [c.args[0] for c in mock_run.call_args_list]
        pr_call = next((c for c in calls if "pr" in c and "create" in c), None)
        assert pr_call is not None, "Expected 'pr create' command to be called"
        assert "--draft" in pr_call, "Expected --draft in pr create command"
        assert "--title" in pr_call, "Expected --title in pr create command"

        # Verify the title argument contains [FAILED]
        title_idx = pr_call.index("--title")
        title_value = pr_call[title_idx + 1]
        assert "[FAILED]" in title_value, f"Expected [FAILED] in title, got {title_value}"
        assert "rec-100" in title_value, f"Expected rec-100 in title, got {title_value}"

    def test_handle_failure_tolerates_push_error(self):
        """Push failure is logged but does not raise; draft PR is skipped."""
        rec = self._rec()

        with patch("scripts.execute_recommendation.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="could not read from remote")

            # Must not raise
            try:
                _handle_failure("rec-100", rec, 1, "push test", 0, 3)
            except Exception as exc:
                pytest.fail(f"_handle_failure raised unexpectedly: {exc}")

        # Only the push call should have been attempted (PR creation skipped on push failure)
        calls = [c.args[0] for c in mock_run.call_args_list]
        pr_calls = [c for c in calls if "pr" in c and "create" in c]
        assert len(pr_calls) == 0, f"Expected no PR create calls after push failure, got {len(pr_calls)}"

    def test_handle_failure_tolerates_pr_error(self):
        """PR creation failure is logged but does not raise."""
        rec = self._rec()
        call_count = 0

        def run_side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "push" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            # gh pr create fails
            raise subprocess.CalledProcessError(1, "gh", stderr="already exists")

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=run_side_effect):
            try:
                _handle_failure("rec-100", rec, 1, "test", 0, 3)
            except Exception as exc:
                pytest.fail(f"_handle_failure raised unexpectedly: {exc}")


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


class TestScopeDriftCheck:
    """Tests for _scope_drift_check()."""

    def test_no_drift_when_all_files_planned(self):
        """Returns empty list when all changed files match plan steps."""
        steps = [
            {"n": 1, "file": "scripts/foo.py", "action": "modify"},
            {"n": 2, "file": "tests/test_foo.py", "action": "modify"},
        ]
        diff_output = "scripts/foo.py\ntests/test_foo.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_unplanned_file_flagged(self):
        """Returns unplanned files that appear in the diff."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nscripts/unplanned.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert "scripts/unplanned.py" in result

    def test_logs_prefix_excluded(self):
        """Files under logs/ are always excluded from drift."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nlogs/.execution-state.json\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_requirements_txt_excluded(self):
        """requirements.txt is always excluded from drift (side-effect of dep changes)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nrequirements.txt\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_jsonl_files_excluded(self):
        """Any .jsonl file is always excluded (telemetry side-effects)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nlogs/.recommendations-log.jsonl\nsome-other.jsonl\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_execute_recommendation_script_excluded(self):
        """scripts/execute_recommendation.py is always excluded (self-modifications)."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        diff_output = "scripts/foo.py\nscripts/execute_recommendation.py\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=diff_output)
            result = _scope_drift_check(steps)
        assert result == []

    def test_git_failure_returns_empty(self):
        """Returns empty list (non-blocking) when git diff fails."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _scope_drift_check(steps)
        assert result == []

    def test_git_timeout_returns_empty(self):
        """Returns empty list (non-blocking) when git diff times out."""
        steps = [{"n": 1, "file": "scripts/foo.py", "action": "modify"}]
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = _scope_drift_check(steps)
        assert result == []


class TestCodeReviewGate:
    """Tests for _code_review_gate()."""

    def _make_plan(self, steps=None):
        return ExecutionPlan(
            rec_id="rec-test",
            slug="rec-test",
            revision=1,
            timestamp="2026-04-02T00:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=steps or [],
            plan_text="## Step 1\nModify foo.py",
        )

    def test_passed_when_no_blocking_findings(self, tmp_path):
        """Returns (True, []) when model reports no CRITICAL/HIGH issues."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="MEDIUM: minor style issue\nGATE: PASSED",
            model="claude-haiku-4.5",
            session_id="",
            cost_usd=0.33,
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True
        assert cost == pytest.approx(0.33)  # haiku multiplier
        assert blocking == []

    def test_failed_when_critical_finding(self, tmp_path):
        """Returns (False, cost, findings) when model reports CRITICAL issue."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="CRITICAL: scripts/foo.py: SQL injection risk\nGATE: FAILED â€” 1 blocking issue",
            session_id="",
        )

        _tmpl = "template {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"
        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) >= 1
        assert any("CRITICAL" in b.upper() for b in blocking)

    def test_failed_when_high_finding(self, tmp_path):
        """Returns (False, ...) when model reports HIGH issue."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="HIGH: tests/test_foo.py: missing test coverage for new function\nGATE: FAILED â€” 1 blocking issue",
            session_id="",
        )

        _tmpl = "template {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"
        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False

    def test_passes_when_prompt_missing(self):
        """Returns (True, 0, []) without raising when prompt file not found."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()

        with patch("scripts.executor.postflight.load_prompt", side_effect=FileNotFoundError("not found")):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True
        assert cost == 0.0
        assert blocking == []

    def test_passes_when_cli_fails(self):
        """Returns (True, ...) without raising when llm_call returns non-zero exit."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(exit_code=1, content="", session_id="")
        _tmpl = "t {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True

    def test_rejects_false_positives_in_prose(self):
        """Rejects lines containing CRITICAL: or HIGH: as substring in prose."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=(
                "Critical Issue Check: Review the following areas\n"
                "CRITICAL Issues Found: None\n"
                "Perfect! The telemetry structure is correct.\n"
                "CRITICAL: Missing error handling in src/foo.py"
            ),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 1
        assert "Missing error handling" in blocking[0]

    def test_accepts_properly_formatted_findings(self):
        """Accepts findings starting with CRITICAL: or HIGH: at line start."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=(
                "CRITICAL: Missing bounds check in src/validator.py\n"
                "**HIGH**: Unescaped user input in src/api.py\n"
                "  CRITICAL: Potential SQL injection"
            ),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 3
        assert any("Missing bounds check" in b for b in blocking)
        assert any("Unescaped user input" in b for b in blocking)
        assert any("SQL injection" in b for b in blocking)

    def test_rejects_all_caps_section_headers(self):
        """Rejects all-caps lines without file paths (section headers)."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=("CRITICAL ISSUES FOUND\nHIGH PRIORITY ITEMS\nCRITICAL: scripts/auth.py: Missing authentication\n"),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 1
        assert "Missing authentication" in blocking[0]


class TestPlanningContextInjection:
    """Tests for planning-time file context injection in generate_initial_plan()."""

    def _make_result(self):
        _stdout = (
            "### Step 1: Edit file\n**File**: scripts/foo.py\n**Action**: modify\n"
            "**Description**: Do it\n**Acceptance**: grep -q foo scripts/foo.py"
        )
        return MagicMock(
            exit_code=0,
            content=_stdout,
            tokens_in=100,
            tokens_out=0,
            model="test-model",
            session_id="ses-001",
        )

    def test_file_content_injected_into_prompt(self, tmp_path):
        """generate_initial_plan passes file_content_section to the planning prompt."""
        rec = {
            "id": "rec-xy",
            "title": "Add docstring",
            "context": "ctx",
            "file": "scripts/foo.py",
            "acceptance": "grep -q docstring scripts/foo.py",
            "dependencies": [],
            "effort": "XS",
        }

        captured_prompts = []

        def fake_llm_call(prompt, **kwargs):
            captured_prompts.append(prompt)
            return self._make_result()

        with (
            patch(
                "scripts.executor.plan.load_prompt",
                return_value=(
                    "{file_content_section}{test_content_section}"
                    "{rec_id}{title}{context}{file}{acceptance}{dependencies}{effort}",
                    "hash123",
                ),
            ),
            patch("scripts.executor.step_runner.gather_step_context") as mock_ctx,
            patch("scripts.executor.plan.llm_call", side_effect=fake_llm_call),
            patch("scripts.executor.plan.os.getenv", return_value="true"),
        ):
            mock_ctx.return_value = {
                "file_content": "def foo(): pass",
                "test_content": "",
                "pattern_content": "",
            }
            generate_initial_plan(rec)

        assert len(captured_prompts) == 1
        assert "def foo(): pass" in captured_prompts[0]

    def test_empty_context_does_not_fail(self, tmp_path):
        """generate_initial_plan handles missing file gracefully (no file_content)."""
        rec = {
            "id": "rec-xy",
            "title": "New feature",
            "context": "ctx",
            "file": "scripts/new.py",
            "acceptance": "test -f scripts/new.py",
            "dependencies": [],
            "effort": "S",
        }

        _new_file_result = MagicMock(
            exit_code=0,
            content=(
                "### Step 1: Create file\n**File**: scripts/new.py\n**Action**: create\n"
                "**Description**: Create new module\n**Acceptance**: test -f scripts/new.py"
            ),
            tokens_in=100,
            tokens_out=0,
            model="test-model",
            session_id="ses-002",
        )
        with (
            patch(
                "scripts.executor.plan.load_prompt",
                return_value=(
                    "{file_content_section}{test_content_section}"
                    "{rec_id}{title}{context}{file}{acceptance}{dependencies}{effort}",
                    "hash456",
                ),
            ),
            patch("scripts.executor.step_runner.gather_step_context") as mock_ctx,
            patch("scripts.executor.plan.llm_call", return_value=_new_file_result),
            patch("scripts.executor.plan.os.getenv", return_value="false"),
        ):
            mock_ctx.return_value = {"file_content": "", "test_content": "", "pattern_content": ""}
            plan = generate_initial_plan(rec)

        assert plan is not None
        assert len(plan.steps) > 0


class TestPostflightValidationQuarantineParsing:
    """Tests for explicit postflight validation quarantine parsing."""

    def test_recognizes_known_baseline_test_as_quarantined(self):
        output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "    - Unit tests + coverage\n\n"
            "Fix all failures before committing.\n"
        )

        quarantined = _get_quarantined_validation_failures(output)

        assert quarantined == [
            "tests/test_execute_recommendation.py::TestPlanningContextInjection::test_empty_context_does_not_fail"
        ]

    def test_rejects_validation_output_with_additional_failed_checks(self):
        output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "    - Unit tests + coverage\n"
            "    - Lint (ruff check)\n\n"
            "Fix all failures before committing.\n"
        )

        assert _get_quarantined_validation_failures(output) == []


@patch("shutil.which", return_value=None)
class TestLintAcceptanceCommand:
    """Test acceptance command validation."""

    def test_empty_command_is_valid(self, mock_shutil):
        """Empty or whitespace-only commands should be valid."""
        ok, error = lint_acceptance_command("")
        assert ok is True
        assert error is None

        ok, error = lint_acceptance_command("   ")
        assert ok is True
        assert error is None

    def test_reject_python_c_one_liner(self, mock_shutil):
        """Reject python -c one-liners."""
        cmd = 'python -c "import sys; print(sys.version)"'
        ok, error = lint_acceptance_command(cmd)
        assert ok is False
        assert error is not None
        assert "python -c" in error.lower()

    def test_reject_python_m_with_quotes(self, mock_shutil):
        """Reject python -m patterns with immediate quotes."""
        cmd = 'python -m "pytest"'
        ok, error = lint_acceptance_command(cmd)
        assert ok is False
        assert error is not None
        assert "python" in error.lower()

    def test_accept_valid_pytest_command(self, mock_shutil):
        """Accept valid pytest commands without quotes."""
        cmd = "python -m pytest tests/test_file.py::TestClass -q"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_accept_valid_grep_command(self, mock_shutil):
        """Accept valid single-pattern grep commands."""
        cmd = "grep -q 'def function_name' src/file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_warn_multi_word_grep_pattern(self, mock_shutil, capsys):
        """Detect and warn about multi-word grep patterns with regex operators."""
        cmd = "grep -E 'word1.*word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_with_pipe_operator(self, mock_shutil, capsys):
        """Detect multi-word grep with pipe operator."""
        cmd = "grep -E 'pattern1|pattern2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        if "grep" in cmd:
            assert "WARNING" in captured.out or len(captured.out) > 0

    def test_reject_invalid_bash_syntax(self, mock_shutil):
        """Reject commands with invalid bash syntax."""
        cmd = "grep -q 'test' file.py &&& invalid"
        # Since shutil.which is None, this will return True!
        # I need to mock shutil.which to return a path and subprocess.run to fail
        with patch("shutil.which", return_value="/bin/bash"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
                ok, error = lint_acceptance_command(cmd)
                assert ok is False
                assert error is not None
                assert "syntax" in error.lower() or "bash" in error.lower()

    def test_accept_valid_bash_syntax(self, mock_shutil):
        """Accept commands with valid bash syntax."""
        cmd = "grep -q 'test' file.py && echo 'found'"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None


@patch("shutil.which", return_value=None)
class TestValidateAcceptanceFeasibility:
    """Test acceptance command feasibility validation."""

    def test_pytest_target_nonexistent_file(self, mock_shutil):
        """Test that pytest commands are FEASIBLE even when test file doesn't exist yet."""
        acceptance = "python -m pytest tests/test_pysr_factory.py::TestPySRFactory -q"

        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(acceptance)

        assert feasibility == AcceptanceFeasibility.FEASIBLE, (
            "Expected FEASIBLE for pytest command when test file doesn't exist yet"
        )
        assert message == "", f"Expected empty message for FEASIBLE result, got: {message}"

    def test_infeasible_handler_updates_status_with_dict(self, mock_shutil):
        """Test INFEASIBLE exit path in _execute_recommendation_inner updates status with dict."""
        from scripts.execute_recommendation import _execute_recommendation_inner

        with patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True):
            with patch("scripts.execute_recommendation.load_checkpoint", return_value=None):
                with patch(
                    "scripts.execute_recommendation.load_recommendation",
                    return_value={"id": "rec-test", "acceptance": "grep file.py"},
                ):
                    with patch(
                        "scripts.execute_recommendation.validate_acceptance_feasibility",
                        return_value=(
                            AcceptanceFeasibility.INFEASIBLE,
                            "grep target file does not exist: src/no.py",
                        ),
                    ):
                        with patch("scripts.execute_recommendation.is_eligible", return_value=True):
                            with patch("scripts.execute_recommendation.write_run_summary"):
                                with patch("scripts.execute_recommendation.update_recommendation_status") as mock_update:
                                    result = _execute_recommendation_inner("rec-test", None, True)
                                    assert result is False, "Expected False when acceptance is INFEASIBLE"
                                    mock_update.assert_called_once_with("rec-test", {"status": "failed"})

    def test_accept_complex_valid_command(self, mock_shutil):
        """Accept complex but valid multi-command bash."""
        cmd = "git status --short && python -m pytest tests/ -q"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        assert error is None

    def test_error_message_includes_command(self, mock_shutil):
        """Error messages should include the problematic command."""
        cmd = 'python -c "bad"'
        # Re-patch within method to simulate bash failure
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
            ok, error = lint_acceptance_command(cmd)
            assert ok is False
            assert cmd in error

    def test_rejection_returns_false_tuple(self, mock_shutil):
        """Rejection should return (False, error_msg) tuple."""
        cmd = "invalid &&& bash"
        # Re-patch within method to simulate bash failure
        with (
            patch("shutil.which", return_value="/bin/bash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
            ok, error = lint_acceptance_command(cmd)
            assert isinstance(ok, bool)
            assert ok is False
            assert isinstance(error, str)

    def test_acceptance_returns_true_tuple(self, mock_shutil):
        """Acceptance should return (True, None) tuple."""
        cmd = "grep -q 'test' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert isinstance(ok, bool)
        assert ok is True
        assert error is None

    def test_warn_grep_q_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -q flag and co-location pattern."""
        cmd = "grep -q 'word1.*word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_qi_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -qi flags and co-location pattern."""
        cmd = "grep -qi 'word1|word2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_warn_grep_qE_co_location(self, mock_shutil, capsys):
        """Detect multi-word grep with -qE flags and co-location pattern."""
        cmd = "grep -qE 'pattern1.*pattern2' file.py"
        ok, error = lint_acceptance_command(cmd)
        assert ok is True
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "Multi-word" in captured.out

    def test_backtick_delimited_with_and_operator_real_file(self, mock_shutil):
        """Test backtick-delimited acceptance with && operator and real file resolves to FEASIBLE."""
        acceptance = "`grep -q 'import json' scripts/execute_recommendation.py && echo 'ok'`"

        feasibility, message = validate_acceptance_feasibility(acceptance)

        assert feasibility == AcceptanceFeasibility.FEASIBLE, (
            f"Expected FEASIBLE for backtick-delimited command with &&, got: {feasibility}"
        )
        assert message == "", f"Expected empty message for FEASIBLE result, got: {message}"


class TestCheckJsonlClean:
    """Regression tests for _check_jsonl_clean() preflight guard.

    The guard uses ``git diff HEAD --quiet -- logs/.recommendations-log.jsonl``
    (pathspec-scoped) so staged and unstaged edits to this one tracked file
    trigger an abort. Tests cover both the standalone (ensure_feature_branch)
    and compound (_ensure_compound_branch) execution surfaces.
    """

    # ------------------------------------------------------------------
    # Unit tests for the helper itself
    # ------------------------------------------------------------------

    def test_clean_returns_true(self):
        """git diff HEAD --quiet exits 0 (clean) => helper returns True."""
        clean = MagicMock(returncode=0, stdout="", stderr="")
        with patch("scripts.execute_recommendation.subprocess.run", return_value=clean) as mock_run:
            result = _check_jsonl_clean()
        assert result is True
        called_cmd = mock_run.call_args[0][0]
        assert "diff" in called_cmd
        assert "HEAD" in called_cmd
        assert "--quiet" in called_cmd
        assert "logs/.recommendations-log.jsonl" in called_cmd

    def test_dirty_returns_false(self):
        """git diff HEAD --quiet exits 1 (dirty) => helper returns False."""
        dirty = MagicMock(returncode=1, stdout="", stderr="")
        with patch("scripts.execute_recommendation.subprocess.run", return_value=dirty):
            result = _check_jsonl_clean()
        assert result is False

    def test_timeout_returns_false(self):
        """Timeout during git diff => helper returns False without raising."""
        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git diff", timeout=10),
        ):
            result = _check_jsonl_clean()
        assert result is False

    def test_unexpected_exception_returns_false(self):
        """Unexpected exception => helper returns False without raising."""
        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            result = _check_jsonl_clean()
        assert result is False

    # ------------------------------------------------------------------
    # Standalone execution surface: ensure_feature_branch
    # ------------------------------------------------------------------

    def test_standalone_aborts_when_jsonl_dirty(self):
        """ensure_feature_branch returns False and skips branch creation when JSONL is dirty."""
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")
        dirty = MagicMock(returncode=1, stdout="", stderr="")

        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=[branch_result, dirty],
        ) as mock_run:
            from scripts.execute_recommendation import ensure_feature_branch

            result = ensure_feature_branch("rec-394")

        assert result is False
        # Only 2 calls: branch --show-current + git diff; no fetch or checkout
        assert mock_run.call_count == 2

    def test_standalone_proceeds_when_jsonl_clean(self):
        """ensure_feature_branch continues to branch creation when JSONL is clean."""
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")
        clean = MagicMock(returncode=0, stdout="", stderr="")
        fetch_ok = MagicMock(returncode=0, stdout="", stderr="")
        checkout_ok = MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "scripts.execute_recommendation.subprocess.run",
            side_effect=[branch_result, clean, fetch_ok, checkout_ok],
        ):
            from scripts.execute_recommendation import ensure_feature_branch

            result = ensure_feature_branch("rec-394")

        assert result is True

    # ------------------------------------------------------------------
    # Compound execution surface: execute_compound
    # ------------------------------------------------------------------

    def test_compound_aborts_when_jsonl_dirty(self):
        """execute_compound returns early with all-failed summary when JSONL is dirty."""
        from scripts.execute_recommendation import execute_compound

        # _ensure_compound_branch internally checks _check_jsonl_clean (deferred import).
        # Simulate: on main branch, then dirty JSONL -> branch creation fails -> all fail.
        branch_result = MagicMock(returncode=0, stdout="main\n", stderr="")

        with (
            patch(
                "scripts.executor.batch.subprocess.run",
                return_value=branch_result,
            ),
            patch(
                "scripts.execute_recommendation._check_jsonl_clean",
                return_value=False,
            ),
        ):
            result = execute_compound(["rec-394", "rec-395"])

        assert result["succeeded"] == 0
        assert result["failed"] == 2

    def test_compound_proceeds_when_jsonl_clean(self):
        """execute_compound calls _ensure_compound_branch and proceeds when JSONL is clean."""
        from scripts.execute_recommendation import execute_compound

        with patch(
            "scripts.executor.batch._ensure_compound_branch",
            return_value=True,
        ) as mock_branch:
            with patch("scripts.executor.jsonl_store.load_recommendation", return_value=None):
                result = execute_compound(["rec-394"])

        mock_branch.assert_called_once_with("agent/compound-rec-394")
        # rec not found => failed, but compound branch creation was attempted
        assert result["attempted"] == 1
        assert result["failed"] == 1


class TestCheckAcceptanceOnMain:
    """Test _check_acceptance_on_main function."""

    def test_acceptance_passes_on_main(self):
        """Test acceptance passes on main -> return True."""
        mock_subprocess_calls = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            mock_subprocess_calls.append(cmd)
            result = MagicMock()
            if "git" in cmd and "log" in cmd:
                result.stdout = "abc123 Test commit\n"
            else:
                result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                        assert result is True, "Expected True when acceptance passes on main"
                        mock_update.assert_called_once()
                        call_args = mock_update.call_args[0]
                        assert call_args[0] == "rec-test"
                        assert call_args[1]["status"] == "closed"
                        assert call_args[1]["execution_result"] == "already_implemented"

        # 1 (branch) + 3 (checkout_main no-restore) + 1 (git log) + 4 (finally restore) = 9
        expected = 9
        assert len(mock_subprocess_calls) == expected, (
            f"Expected {expected} subprocess calls, got {len(mock_subprocess_calls)}"
        )

    def test_acceptance_fails_on_main(self):
        """Test acceptance fails on main -> return False."""
        mock_subprocess_calls = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            mock_subprocess_calls.append(cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=False):
                with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                    result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                    assert result is False, "Expected False when acceptance fails on main"
                    mock_update.assert_not_called()

        # 1 (branch) + 3 (checkout_main no-restore) + 4 (finally restore) = 8, no git log call
        expected = 8
        assert len(mock_subprocess_calls) == expected, (
            f"Expected {expected} subprocess calls, got {len(mock_subprocess_calls)}"
        )

    def test_empty_acceptance_command(self):
        """Test empty acceptance command -> return False."""
        with patch("scripts.executor.acceptance_lint.subprocess.run") as mock_run:
            result = _check_acceptance_on_main("rec-test", "", "agent/rec-test")
            assert result is False, "Expected False for empty acceptance command"
            mock_run.assert_not_called()

    def test_whitespace_only_acceptance(self):
        """Test whitespace-only acceptance command -> return False."""
        with patch("scripts.executor.acceptance_lint.subprocess.run") as mock_run:
            result = _check_acceptance_on_main("rec-test", "   \n   ", "agent/rec-test")
            assert result is False, "Expected False for whitespace-only acceptance"
            mock_run.assert_not_called()

    def test_git_checkout_main_fails(self):
        """Test git checkout main fails -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if cmd and "checkout" in cmd and "main" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
            assert result is False, "Expected False when git checkout to main fails"

    def test_git_checkout_branch_fails(self):
        """Test git checkout back to branch fails inside _checkout_main_safely -> return False."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 4:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.update_recommendation_status"):
                    result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                    assert result is False, "Expected False when checkout back to branch fails"

    def test_acceptance_check_timeout(self):
        """Test subprocess timeout during acceptance check -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if cmd and "branch" in cmd and "--show-current" in cmd:
                return MagicMock(stdout="agent/rec-test", returncode=0)
            raise subprocess.TimeoutExpired("git", 5)

        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
            assert result is False, "Expected False on subprocess timeout"

    def test_branch_switching_sequence(self):
        """Verify correct branch switching sequence within _checkout_main_safely."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.stdout = "agent/rec-test"
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status"):
                        _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")

        assert len(call_sequence) >= 5, f"Expected at least 5 subprocess calls, got {len(call_sequence)}"
        assert any("branch --show-current" in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git branch --show-current' in call sequence"
        )
        assert any("stash" in " ".join(cmd) and "pop" not in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git stash' (without pop) in call sequence"
        )
        assert any("checkout main" in " ".join(cmd) for cmd in call_sequence), "Expected 'git checkout main' in call sequence"
        assert any("checkout agent/rec-test" in " ".join(cmd) for cmd in call_sequence), (
            "Expected 'git checkout agent/rec-test' in call sequence"
        )
        assert any("stash pop" in " ".join(cmd) for cmd in call_sequence), "Expected 'git stash pop' in call sequence"

    def test_acceptance_ambiguous_zero_commits(self):
        """Test acceptance passes on main but zero commits since rec date -> return False."""

        def mock_subprocess_run(*args, **kwargs):
            _cmd = args[0] if args else []
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                        assert result is False, "Expected False when no commits found since rec date"
                        mock_update.assert_not_called()

    def test_acceptance_ambiguous_with_env_override(self):
        """Test zero commits but ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED=true -> return True."""

        def mock_subprocess_run(*args, **kwargs):
            _cmd = args[0] if args else []
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0
            return result

        rec_data = {"id": "rec-test", "date": "2026-01-01", "file": "scripts/test_file.py"}
        env_override = {"ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED": "true"}
        with patch("scripts.executor.acceptance_lint.subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.executor.step_runner.run_acceptance", return_value=True):
                with patch("scripts.executor.jsonl_store.load_recommendation", return_value=rec_data):
                    with patch("scripts.executor.jsonl_store.update_recommendation_status") as mock_update:
                        with patch.dict("os.environ", env_override):
                            result = _check_acceptance_on_main("rec-test", "grep -q 'test' file.py", "agent/rec-test")
                            assert result is True, "Expected True when ALLOW_AMBIGUOUS_ALREADY_IMPLEMENTED=true"
                            mock_update.assert_called_once()
                            call_args = mock_update.call_args[0]
                            assert call_args[1]["execution_result"] == "already_implemented"


class TestCheckoutMainSafely:
    """Test _checkout_main_safely function."""

    def test_no_restore_branch(self):
        """Test checkout to main without restore_branch - stash pop happens on main."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

        assert len(call_sequence) == 3, f"Expected 3 calls, got {len(call_sequence)}"
        assert call_sequence[0] == ["git", "stash"], "Expected git stash"
        assert call_sequence[1] == ["git", "checkout", "main"], "Expected git checkout main"
        assert call_sequence[2] == ["git", "stash", "pop"], "Expected git stash pop"

    def test_with_restore_branch(self):
        """Test with restore_branch - stash pop happens after branch restoration."""
        call_sequence = []

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_sequence.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely("agent/rec-test")

        assert len(call_sequence) == 4, f"Expected 4 calls, got {len(call_sequence)}"
        assert call_sequence[0] == ["git", "stash"], "Expected git stash"
        assert call_sequence[1] == ["git", "checkout", "main"], "Expected git checkout main"
        assert call_sequence[2] == ["git", "checkout", "agent/rec-test"], "Expected checkout to restore_branch"
        assert call_sequence[3] == ["git", "stash", "pop"], "Expected git stash pop after restore"

    def test_stash_fails(self):
        """Test git stash failure raises CalledProcessError."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if "stash" in cmd and len(cmd) == 2:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely()

    def test_checkout_main_fails(self):
        """Test git checkout main failure raises CalledProcessError."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 2:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely()

    def test_checkout_restore_branch_fails(self):
        """Test checkout to restore_branch failure raises CalledProcessError."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 3:
                raise subprocess.CalledProcessError(1, cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.CalledProcessError):
                _checkout_main_safely("agent/rec-test")

    def test_stash_pop_does_not_raise(self):
        """Test stash pop failure does not raise (check=False not set, but capture_output is)."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            result = MagicMock()
            result.returncode = 1 if call_count[0] == 3 else 0
            if result.returncode != 0 and kwargs.get("check"):
                raise subprocess.CalledProcessError(result.returncode, cmd)
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

    def test_timeout_during_stash(self):
        """Test timeout during git stash raises TimeoutExpired."""

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            if "stash" in cmd and len(cmd) == 2:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.TimeoutExpired):
                _checkout_main_safely()

    def test_timeout_during_checkout_main(self):
        """Test timeout during git checkout main raises TimeoutExpired."""
        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else []
            call_count[0] += 1
            if call_count[0] == 2:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            with pytest.raises(subprocess.TimeoutExpired):
                _checkout_main_safely()

    def test_encoding_and_error_handling(self):
        """Verify text=True, encoding=utf-8, errors=replace are used."""
        call_kwargs_list = []

        def mock_subprocess_run(*args, **kwargs):
            call_kwargs_list.append(kwargs)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("scripts.execute_recommendation.subprocess.run", side_effect=mock_subprocess_run):
            _checkout_main_safely()

        for kwargs in call_kwargs_list:
            assert kwargs.get("text") is True, "Expected text=True"
            assert kwargs.get("encoding") == "utf-8", "Expected encoding=utf-8"
            assert kwargs.get("errors") == "replace", "Expected errors=replace"


class TestPostValidationAcceptancePath:
    """Test _execute_recommendation_inner when post-validation acceptance succeeds."""

    def test_acceptance_success_calls_finalize_once_and_returns_true(self):
        """finalize() is called exactly once and execution returns True when post-validation acceptance passes."""
        from contextlib import ExitStack

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "scripts/__init__.py",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        git_ok = MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch("scripts.execute_recommendation.load_checkpoint", return_value=None),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan", return_value=None),
            patch("scripts.execute_recommendation.generate_initial_plan", return_value=plan),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "session-1"),
            ),
            patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.25, [])),
            patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.execute_recommendation.run_acceptance", return_value=True),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.lint_acceptance_command", return_value=(True, "")),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
            }
            result = execute_recommendation("rec-100", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()


class TestPostAcceptanceVerificationGate:
    """Test verification gate between acceptance pass and finalize()."""

    def _build_patches(self, mock_val_proc, git_ok, plan, verification_result):
        """Build the standard ExitStack patch list for the verification gate tests."""
        return [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch("scripts.execute_recommendation.load_checkpoint", return_value=None),
            patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0),
            patch("scripts.execute_recommendation.get_latest_plan", return_value=None),
            patch("scripts.execute_recommendation.generate_initial_plan", return_value=plan),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "session-1"),
            ),
            patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch("scripts.execute_recommendation._scope_drift_check", return_value=[]),
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.25, [])),
            patch("scripts.execute_recommendation.subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.execute_recommendation.run_acceptance", return_value=True),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.lint_acceptance_command", return_value=(True, "")),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch("scripts.execute_recommendation.subprocess.run", return_value=git_ok),
            patch("scripts.execute_recommendation.run_verification", return_value=verification_result),
        ]

    def _make_plan(self):
        return ExecutionPlan(
            rec_id="rec-200",
            slug="rec-200",
            revision=1,
            timestamp="2026-04-01T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "scripts/__init__.py",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

    def _make_val_proc(self):
        mock_val_proc = MagicMock()
        mock_val_proc.communicate.return_value = ("", "")
        mock_val_proc.returncode = 0
        mock_val_proc.__enter__ = MagicMock(return_value=mock_val_proc)
        mock_val_proc.__exit__ = MagicMock(return_value=False)
        return mock_val_proc

    def _make_git_ok(self):
        return MagicMock(returncode=0, stdout="scripts/execute_recommendation.py\n", stderr="")

    def test_verification_pass_still_calls_finalize(self):
        """When verification passes, finalize() is called and execution succeeds."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {"passed": True, "output": "ok", "skipped": False, "rejected": False, "error": ""}
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_telemetry = mocks[18]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": "python -m scripts.some_check --verify",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        # Telemetry should include verification_pass outcome
        telemetry_calls = [c for c in mock_telemetry.call_args_list if c.kwargs.get("outcome") == "verification_pass"]
        assert len(telemetry_calls) >= 1

    def test_verification_fail_still_calls_finalize(self):
        """When verification fails, finalize() is STILL called (advisory failure)."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {
            "passed": False,
            "output": "error output",
            "skipped": False,
            "rejected": False,
            "error": "exit 1",
        }
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_telemetry = mocks[18]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": "python -m scripts.some_check --verify",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        # Telemetry should include verification_warning outcome
        telemetry_calls = [c for c in mock_telemetry.call_args_list if c.kwargs.get("outcome") == "verification_warning"]
        assert len(telemetry_calls) >= 1

    def test_no_verification_field_skips_gate(self):
        """When rec has no verification field, the gate is skipped entirely."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {"passed": True, "output": "", "skipped": True, "rejected": False, "error": ""}
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_run_verification = mocks[24]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()
        mock_run_verification.assert_not_called()

    def test_verification_rejected_still_calls_finalize(self):
        """When verification is rejected (python -c), finalize() is still called."""
        from contextlib import ExitStack

        plan = self._make_plan()
        verification_result = {
            "passed": False,
            "output": "rejected",
            "skipped": False,
            "rejected": True,
            "error": "python -c banned",
        }
        patches = self._build_patches(self._make_val_proc(), self._make_git_ok(), plan, verification_result)

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_load.return_value = {
                "id": "rec-200",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
                "verification": 'python -c "import sys"',
            }
            result = execute_recommendation("rec-200", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once()


class TestResumePostflight:
    """Tests for IMPL_COMPLETE checkpoint and --resume-postflight flag."""

    def _eligible_rec(self, rec_id: str = "rec-100") -> dict:
        return {
            "id": rec_id,
            "title": "Test rec",
            "risk": "low",
            "automatable": True,
            "effort": "S",
            "file": "scripts/some_file.py",
        }

    def _approved_plan(self, rec_id: str = "rec-100") -> ExecutionPlan:
        return ExecutionPlan(
            rec_id=rec_id,
            slug=rec_id,
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "Step 1",
                    "file": "",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                },
                {
                    "n": 2,
                    "title": "Step 2",
                    "file": "",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                },
            ],
            plan_text="",
        )

    def test_impl_complete_checkpoint_saved_after_all_steps(self):
        """save_checkpoint is called with status=IMPL_COMPLETE after all steps."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.save_checkpoint") as mock_save_ck,
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.critique_plan") as mock_critique,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.0, []),
            ),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_gen.return_value = self._approved_plan()
            mock_critique.return_value = {
                "verdict": "approved",
                "suggestions": [],
                "tokens_used": 10,
            }
            mock_impl.return_value = (
                StepOutcome.SUCCESS,
                0.01,
                "abc123def456",  # pragma: allowlist secret
                "ses-step",
            )
            mock_commit.return_value = (True, "1 file changed")

            execute_recommendation("rec-100", skip_critique=True)

        # Last save_checkpoint call must be IMPL_COMPLETE
        impl_complete_calls = [
            c
            for c in mock_save_ck.call_args_list
            if c.kwargs.get("status") == "IMPL_COMPLETE" or (len(c.args) > 4 and c.args[4] == "IMPL_COMPLETE")
        ]
        assert len(impl_complete_calls) == 1
        impl_call = impl_complete_calls[0]
        assert impl_call == call(
            branch="agent/rec-100",
            plan_file="rec-100",
            current_step=2,
            total_steps=2,
            status="IMPL_COMPLETE",
        )

    def test_resume_postflight_skips_plan_and_impl(self):
        """resume_postflight=True skips plan generation and implementation."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 2,
            "total_steps": 2,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch("scripts.execute_recommendation.generate_initial_plan") as mock_gen,
            patch("scripts.execute_recommendation.get_latest_plan") as mock_latest,
            patch("scripts.execute_recommendation.critique_plan") as mock_critique,
            patch("scripts.execute_recommendation.save_plan"),
            patch("scripts.execute_recommendation.implement_step") as mock_impl,
            patch("scripts.execute_recommendation.commit_step") as mock_commit,
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/pr/1",
            ) as mock_finalize,
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.0, []),
            ),
            patch("scripts.execute_recommendation.subprocess.Popen") as mock_popen,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
            mock_popen.return_value.__exit__ = MagicMock(return_value=False)
            mock_popen.return_value.communicate.return_value = ("", "")
            mock_popen.return_value.returncode = 0
            mock_load.return_value = self._eligible_rec()
            mock_latest.return_value = self._approved_plan()

            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is True
        # Plan generation and implementation should never be called
        mock_gen.assert_not_called()
        mock_critique.assert_not_called()
        mock_impl.assert_not_called()
        mock_commit.assert_not_called()
        # Postflight (finalize) should be called
        mock_finalize.assert_called_once()

    def test_resume_postflight_without_plan_fails(self):
        """resume_postflight=True requires an existing saved execution plan."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 2,
            "total_steps": 2,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._eligible_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ) as mock_summary,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
        ):
            result = execute_recommendation(
                "rec-100",
                resume_postflight=True,
            )

        assert result is False
        assert mock_summary.call_count == 1
        assert mock_summary.call_args.args[3] == "resume-postflight requires an existing plan for checkpointed recommendation"

    def test_resume_postflight_without_checkpoint_fails(self):
        """resume_postflight=True without IMPL_COMPLETE checkpoint returns False."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False

    def test_resume_postflight_with_wrong_status_checkpoint_fails(self):
        """resume_postflight=True rejects same-rec checkpoint unless status is IMPL_COMPLETE."""
        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 2,
            "status": "in_progress",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch("scripts.execute_recommendation.write_run_summary") as mock_summary,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False
        assert mock_summary.call_count == 1
        assert mock_summary.call_args.args[3] == "resume-postflight without IMPL_COMPLETE checkpoint"

    def test_resume_postflight_with_foreign_checkpoint_clears_then_fails(self):
        """resume_postflight=True clears stale foreign checkpoint and reports resume-postflight error."""
        checkpoint = {
            "plan_file": "rec-999",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-999",
            "last_updated": "2026-04-15T00:00:00+00:00",
        }
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("scripts.execute_recommendation.load_recommendation") as mock_load,
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=checkpoint,
            ),
            patch("scripts.execute_recommendation.save_checkpoint"),
            patch("scripts.execute_recommendation.clear_checkpoint") as mock_clear,
            patch("scripts.execute_recommendation._is_checkpoint_branch_merged") as mock_is_merged,
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("builtins.print") as mock_print,
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
        ):
            mock_load.return_value = self._eligible_rec()
            result = execute_recommendation("rec-100", resume_postflight=True)

        assert result is False
        mock_clear.assert_called_once()
        mock_is_merged.assert_not_called()
        printed = " ".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
        assert "--resume-postflight requires an IMPL_COMPLETE checkpoint" in printed
        assert "Checkpoint exists for different rec" not in printed


class TestWarmBaseAndAutoResume:
    """Tests for XS/S warm_base skip and --auto-resume dispatch logic."""

    def _eligible_rec(self, effort: str = "XS") -> dict:
        return {"id": "rec-100", "title": "Test rec", "risk": "low", "automatable": True, "effort": effort}

    def _approved_plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {"n": 1, "title": "Step 1", "file": "", "action": "modify", "description": "", "acceptance": ""},
            ],
            plan_text="",
        )

    def _common_patches(self, stack, checkpoint=None, *, latest_plan_ret=None, rec=None):
        """Enter common patches into an ExitStack and return a dict of mock references."""
        mock_val = MagicMock(returncode=0, stdout="", stderr="")
        mocks = {}
        mocks["load_rec"] = stack.enter_context(
            patch("scripts.execute_recommendation.load_recommendation", return_value=rec or self._eligible_rec())
        )
        mocks["ensure"] = stack.enter_context(patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True))
        mocks["load_ck"] = stack.enter_context(
            patch("scripts.execute_recommendation.load_checkpoint", return_value=checkpoint)
        )
        stack.enter_context(patch("scripts.execute_recommendation.save_checkpoint"))
        stack.enter_context(patch("scripts.execute_recommendation.clear_checkpoint"))
        stack.enter_context(patch("scripts.execute_recommendation._commits_ahead_of_main", return_value=0))
        mocks["gen"] = stack.enter_context(patch("scripts.execute_recommendation.generate_initial_plan"))
        mocks["latest"] = stack.enter_context(
            patch("scripts.execute_recommendation.get_latest_plan", return_value=latest_plan_ret)
        )
        mocks["critique"] = stack.enter_context(patch("scripts.execute_recommendation.critique_plan"))
        stack.enter_context(patch("scripts.execute_recommendation.save_plan"))
        mocks["impl"] = stack.enter_context(patch("scripts.execute_recommendation.implement_step"))
        stack.enter_context(patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file")))
        stack.enter_context(patch("scripts.execute_recommendation._append_step_telemetry"))
        mocks["finalize"] = stack.enter_context(
            patch("scripts.execute_recommendation.finalize", return_value="https://github.com/pr/1")
        )
        stack.enter_context(patch("scripts.execute_recommendation.update_recommendation_status"))
        stack.enter_context(patch("scripts.execute_recommendation._scope_drift_check", return_value=[]))
        mocks["review"] = stack.enter_context(
            patch("scripts.execute_recommendation._code_review_gate", return_value=(True, 0.0, []))
        )
        mock_popen = stack.enter_context(patch("scripts.execute_recommendation.subprocess.Popen"))
        mock_popen.return_value.__enter__ = MagicMock(return_value=mock_popen.return_value)
        mock_popen.return_value.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value.communicate.return_value = ("", "")
        mock_popen.return_value.returncode = 0
        stack.enter_context(patch("scripts.execute_recommendation.subprocess.run", return_value=mock_val))
        return mocks

    def test_xs_effort_skips_seed_session(self):
        """execute_recommendation with effort=XS must NOT call _seed_gemini_session."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            mocks = self._common_patches(stack)
            mock_seed = stack.enter_context(patch("scripts.execute_recommendation._seed_gemini_session"))
            stack.enter_context(patch("scripts.llm.model_registry.resolve_provider", return_value="gemini"))
            mocks["gen"].return_value = self._approved_plan()
            mocks["critique"].return_value = {"verdict": "approved", "suggestions": [], "tokens_used": 10}
            mocks["impl"].return_value = (StepOutcome.SUCCESS, 0.01, "abc123def456", "ses-step")  # pragma: allowlist secret

            execute_recommendation("rec-100", skip_critique=True)

        mock_seed.assert_not_called()

    def test_auto_resume_from_impl_complete(self):
        """auto_resume=True with IMPL_COMPLETE checkpoint skips plan/impl and runs postflight."""
        from contextlib import ExitStack

        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 1,
            "status": "IMPL_COMPLETE",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-27T00:00:00+00:00",
        }
        with ExitStack() as stack:
            mocks = self._common_patches(stack, checkpoint=checkpoint, latest_plan_ret=self._approved_plan())

            result = execute_recommendation("rec-100", auto_resume=True)

        assert result is True
        mocks["gen"].assert_not_called()
        mocks["critique"].assert_not_called()
        mocks["impl"].assert_not_called()
        mocks["finalize"].assert_called_once()
        # Code review should run (skip_to_finalize is False for IMPL_COMPLETE)
        mocks["review"].assert_called_once()

    def test_auto_resume_from_ci_pending(self):
        """auto_resume=True with CI_PENDING checkpoint skips plan/impl/review and runs finalize."""
        from contextlib import ExitStack

        checkpoint = {
            "plan_file": "rec-100",
            "current_step": 1,
            "total_steps": 1,
            "status": "CI_PENDING",
            "branch": "agent/rec-100",
            "last_updated": "2026-04-27T00:00:00+00:00",
        }
        with ExitStack() as stack:
            mocks = self._common_patches(stack, checkpoint=checkpoint, latest_plan_ret=self._approved_plan())

            result = execute_recommendation("rec-100", auto_resume=True)

        assert result is True
        mocks["gen"].assert_not_called()
        mocks["critique"].assert_not_called()
        mocks["impl"].assert_not_called()
        mocks["finalize"].assert_called_once()
        # Code review must be skipped (skip_to_finalize=True for CI_PENDING)
        mocks["review"].assert_not_called()


class TestDocOnlyValidationFallback:
    """Test that doc-only diffs trigger --scope auto validation fallback."""

    def test_doc_only_diff_triggers_scope_auto(self):
        """When full validation fails and diff has no .py files, fallback uses --scope auto."""
        from contextlib import ExitStack

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "docs/README.md",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

        # First Popen: full validation -- fails (returncode=1)
        full_val_proc = MagicMock()
        full_val_proc.communicate.return_value = ("fail output", "")
        full_val_proc.returncode = 1
        full_val_proc.__enter__ = MagicMock(return_value=full_val_proc)
        full_val_proc.__exit__ = MagicMock(return_value=False)

        # Second Popen: quick validation fallback -- succeeds
        quick_val_proc = MagicMock()
        quick_val_proc.communicate.return_value = ("ok", "")
        quick_val_proc.returncode = 0
        quick_val_proc.__enter__ = MagicMock(return_value=quick_val_proc)
        quick_val_proc.__exit__ = MagicMock(return_value=False)

        popen_calls = []
        popen_side_effects = [full_val_proc, quick_val_proc]

        def popen_tracker(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return popen_side_effects.pop(0)

        # subprocess.run for git diff returns only non-.py files
        git_diff_result = MagicMock(
            returncode=0,
            stdout="docs/README.md\nconfig/settings.yaml\n",
            stderr="",
        )

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                return_value=plan,
            ),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "s-1"),
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.25, []),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.Popen",
                side_effect=popen_tracker,
            ),
            patch(
                "scripts.execute_recommendation.run_acceptance",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation.lint_acceptance_command",
                return_value=(True, ""),
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=git_diff_result,
            ),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "docs/README.md",
                "acceptance": "grep -q 'pattern' docs/README.md",
            }
            execute_recommendation("rec-100", skip_critique=True)

        # Second Popen call should be the --scope prompts fallback
        assert len(popen_calls) >= 2, f"Expected at least 2 Popen calls, got {len(popen_calls)}"
        second_call_args = popen_calls[1][0][0]
        assert "--scope" in second_call_args, f"Expected '--scope' in fallback argv: {second_call_args}"
        scope_idx = second_call_args.index("--scope")
        assert second_call_args[scope_idx + 1] == "prompts", (
            f"Expected '--scope prompts', got '--scope {second_call_args[scope_idx + 1]}'"
        )


class TestPostflightValidationQuarantine:
    """Tests for quarantined baseline validation failures in postflight."""

    def test_known_baseline_failure_allows_finalize(self, monkeypatch):
        """A known baseline-red test failure is recorded and does not block finalize."""
        from contextlib import ExitStack

        monkeypatch.setenv("SKIP_CI_WAIT", "true")

        plan = ExecutionPlan(
            rec_id="rec-100",
            slug="rec-100",
            revision=1,
            timestamp="2026-04-15T10:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "title": "step",
                    "file": "scripts/__init__.py",
                    "action": "modify",
                    "description": "",
                    "acceptance": "",
                }
            ],
            plan_text="",
        )

        full_val_output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "  - Unit tests + coverage\n\n"
            "Fix all failures before committing.\n"
        )

        full_val_proc = MagicMock()
        full_val_proc.communicate.return_value = (full_val_output, "")
        full_val_proc.returncode = 1
        full_val_proc.__enter__ = MagicMock(return_value=full_val_proc)
        full_val_proc.__exit__ = MagicMock(return_value=False)

        patches = [
            patch("scripts.execute_recommendation.load_recommendation"),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch("scripts.execute_recommendation.prune_merged_agent_branches"),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.get_latest_plan",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                return_value=plan,
            ),
            patch("scripts.execute_recommendation.save_plan"),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=(StepOutcome.SUCCESS, 0.25, "abc123", "s-1"),
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch("scripts.execute_recommendation._append_step_telemetry"),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._code_review_gate",
                return_value=(True, 0.25, []),
            ),
            patch(
                "scripts.execute_recommendation.subprocess.Popen",
                return_value=full_val_proc,
            ),
            patch(
                "scripts.execute_recommendation.run_acceptance",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value="https://github.com/example/pr/1",
            ),
            patch("scripts.execute_recommendation.update_recommendation_status"),
            patch("scripts.execute_recommendation._handle_failure"),
            patch("scripts.execute_recommendation._capture_executor_telemetry"),
            patch("scripts.execute_recommendation.write_run_summary"),
            patch("scripts.execute_recommendation.clear_checkpoint"),
            patch(
                "scripts.execute_recommendation.lint_acceptance_command",
                return_value=(True, ""),
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(AcceptanceFeasibility.FEASIBLE, ""),
            ),
        ]

        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            mock_load = mocks[0]
            mock_finalize = mocks[15]
            mock_update = mocks[16]
            mock_summary = mocks[19]
            mock_load.return_value = {
                "id": "rec-100",
                "title": "Test rec",
                "risk": "low",
                "automatable": True,
                "effort": "S",
                "file": "scripts/__init__.py",
                "acceptance": "grep -q 'pattern' scripts/execute_recommendation.py",
            }

            result = execute_recommendation("rec-100", skip_critique=True)

        assert result is True
        mock_finalize.assert_called_once_with("rec-100", no_merge=False)
        assert mock_update.call_args_list[-1].args[1]["status"] == "closed"
        pf_meta = mock_summary.call_args.kwargs["postflight_validation"]
        assert pf_meta["result"] == "pass_with_quarantine"
        assert pf_meta["quarantined_tests"] == [
            "tests/test_execute_recommendation.py::TestPlanningContextInjection::test_empty_context_does_not_fail"
        ]


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


class TestPreflightSideEffectFree:
    """Regression: rejected read-only preflight gates must not
    call ensure_feature_branch() or clean_slate()."""

    def test_not_found_skips_branch_and_cleanup(self):
        """Missing rec rejects before any git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-missing",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_ineligible_skips_branch_and_cleanup(self):
        """Ineligible rec rejects before any git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-bad",
                    "risk": "high",
                    "automatable": False,
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-bad",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_infeasible_acceptance_skips_branch_and_cleanup(self):
        """Infeasible acceptance rejects before git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-inf",
                    "acceptance": "grep missing.py",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.validate_acceptance_feasibility",
                return_value=(
                    AcceptanceFeasibility.INFEASIBLE,
                    "file not found",
                ),
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-inf",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_foreign_checkpoint_skips_branch_and_cleanup(self):
        """Foreign unmerged checkpoint rejects before git ops."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        ck = {
            "plan_file": "rec-other",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-other",
            "last_updated": "2026-04-17T00:00:00+00:00",
        }
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-new",
                    "title": "New",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=ck,
            ),
            patch(
                "scripts.execute_recommendation._is_checkpoint_branch_merged",
                return_value=False,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-new",
                None,
                True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_resume_postflight_foreign_skips_branch(self):
        """resume_postflight with foreign checkpoint rejects
        before git side effects."""
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        ck = {
            "plan_file": "rec-foreign",
            "current_step": 1,
            "total_steps": 2,
            "status": "IN_PROGRESS",
            "branch": "agent/rec-foreign",
            "last_updated": "2026-04-17T00:00:00+00:00",
        }
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-new",
                    "title": "New",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=ck,
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = _execute_recommendation_inner(
                "rec-new",
                None,
                True,
                resume_postflight=True,
            )

        assert result is False
        mock_branch.assert_not_called()
        mock_clean.assert_not_called()

    def test_success_path_calls_branch_and_cleanup(self):
        """Once read-only gates pass, ensure_feature_branch and
        clean_slate are called for a stale-state rec."""
        mock_val = MagicMock(
            returncode=0,
            stdout="0\n",
            stderr="",
        )
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value={
                    "id": "rec-ok",
                    "title": "Good",
                    "risk": "low",
                    "automatable": True,
                    "effort": "S",
                    "file": "src/ok.py",
                    "execution_result": "failure",
                },
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ) as mock_branch,
            patch(
                "scripts.execute_recommendation.clean_slate",
            ) as mock_clean,
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation._commits_ahead_of_main",
                return_value=0,
            ),
            patch(
                "scripts.execute_recommendation.generate_initial_plan",
                side_effect=LLMResponseError("stop"),
            ),
            patch(
                "scripts.execute_recommendation.escalate_planning_model",
                return_value="",
            ),
            patch(
                "scripts.execute_recommendation.subprocess.run",
                return_value=mock_val,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = execute_recommendation("rec-ok")

        assert result is False
        mock_branch.assert_called_once()
        mock_clean.assert_called_once()


class TestFastMode:
    """Tests for --fast mode plan delivery and phase skipping."""

    def _base_rec(self):
        return {
            "id": "rec-413",
            "title": "Fast test",
            "risk": "low",
            "automatable": True,
            "file": "scripts/example.py",
            "effort": "XS",
            "acceptance": "echo ok",
        }

    def _fast_plan_json(self):
        return json.dumps(
            [
                {
                    "n": 1,
                    "title": "Apply fix",
                    "file": "scripts/example.py",
                    "action": "modify",
                    "description": "Fix the thing",
                    "acceptance": "grep -q 'x' scripts/example.py",
                }
            ]
        )

    def _patch_run_acceptance(self):
        return patch("scripts.execute_recommendation.run_acceptance", return_value=True)

    def _inner(self):
        from scripts.execute_recommendation import (
            _execute_recommendation_inner,
        )

        return _execute_recommendation_inner

    def test_fast_cli_parses_fast_and_plan_json(self):
        """--fast and --plan-json are recognised by argparse."""
        plan = self._fast_plan_json()
        with (
            patch(
                "scripts.execute_recommendation.check_recursion_guard",
            ),
            patch(
                "scripts.execute_recommendation.check_process_killswitch",
            ),
            patch(
                "scripts.execute_recommendation._assign_job_object",
            ),
            patch(
                "scripts.execute_recommendation.execute_recommendation",
                return_value=True,
            ) as mock_exec,
            patch(
                "scripts.execute_recommendation.sys.argv",
                [
                    "execute_recommendation",
                    "rec-413",
                    "--fast",
                    "--plan-json",
                    plan,
                ],
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        mock_exec.assert_called_once()
        _, kwargs = mock_exec.call_args
        assert kwargs["fast_mode"] is True
        assert kwargs["plan_json"] == plan

    def test_fast_mode_rejects_empty_plan_json(self):
        """Fast mode returns False when plan JSON is empty."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json="",
            )

        assert result is False

    def test_fast_mode_rejects_invalid_json(self):
        """Fast mode returns False for malformed JSON."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json="{not valid json",
            )

        assert result is False

    def test_fast_mode_rejects_empty_steps(self):
        """Fast mode returns False when JSON has no steps."""
        inner = self._inner()
        with (
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch("subprocess.run") as mock_run,
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=json.dumps({"steps": []}),
            )

        assert result is False

    def test_fast_mode_skips_planning_critique_review(self):
        """Fast mode skips generate_initial_plan, critique, review."""
        from contextlib import ExitStack

        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with ExitStack() as stack:
            stack.enter_context(self._patch_run_acceptance())
            stack.enter_context(patch("scripts.execute_recommendation.load_recommendation", return_value=self._base_rec()))
            stack.enter_context(patch("scripts.execute_recommendation.load_checkpoint", return_value=None))
            stack.enter_context(patch("scripts.execute_recommendation.ensure_feature_branch", return_value=True))
            stack.enter_context(patch("scripts.execute_recommendation.prune_merged_agent_branches"))
            stack.enter_context(patch("scripts.execute_recommendation.clean_slate"))
            mock_gen_plan = stack.enter_context(patch("scripts.execute_recommendation.generate_initial_plan"))
            mock_critique = stack.enter_context(patch("scripts.execute_recommendation.critique_plan"))
            mock_review = stack.enter_context(patch("scripts.execute_recommendation._code_review_gate"))
            mock_impl = stack.enter_context(
                patch("scripts.execute_recommendation.implement_step", return_value=mock_step_result)
            )
            stack.enter_context(patch("scripts.execute_recommendation.commit_step", return_value=(True, "1 file changed")))
            stack.enter_context(patch("scripts.execute_recommendation._append_step_telemetry"))
            stack.enter_context(patch("scripts.execute_recommendation.save_checkpoint"))
            stack.enter_context(patch("scripts.execute_recommendation.save_plan"))
            stack.enter_context(patch("scripts.execute_recommendation.finalize", return_value=True))
            stack.enter_context(patch("scripts.execute_recommendation.update_recommendation_status"))
            stack.enter_context(patch("scripts.execute_recommendation._scope_drift_check", return_value=[]))
            stack.enter_context(patch("scripts.execute_recommendation._capture_executor_telemetry"))
            stack.enter_context(patch("scripts.execute_recommendation.write_run_summary"))
            stack.enter_context(patch("scripts.execute_recommendation.clear_checkpoint"))
            mock_run = stack.enter_context(patch("subprocess.run"))

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_gen_plan.assert_not_called()
        mock_critique.assert_not_called()
        mock_review.assert_not_called()
        mock_impl.assert_called_once()

    def test_fast_mode_still_runs_implement_and_finalize(self):
        """Fast mode runs implementation and finalize."""
        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ) as mock_impl,
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ) as mock_finalize,
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_impl.assert_called_once()
        mock_finalize.assert_called_once()

    def test_fast_mode_reads_stdin_when_no_plan_json(self):
        """Fast mode reads stdin when --plan-json is None."""
        inner = self._inner()
        plan_json = self._fast_plan_json()
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ),
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.sys.stdin",
            ) as mock_stdin,
            patch("subprocess.run") as mock_run,
        ):
            mock_stdin.read.return_value = plan_json
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=None,
            )

        assert result is True
        mock_stdin.read.assert_called_once()

    def test_fast_mode_accepts_dict_with_steps_key(self):
        """Fast mode accepts {\"steps\": [...]} format."""
        inner = self._inner()
        plan_json = json.dumps(
            {
                "steps": [
                    {
                        "n": 1,
                        "title": "Fix",
                        "file": "f.py",
                        "action": "modify",
                        "description": "d",
                        "acceptance": "grep -q x f.py",
                    }
                ]
            }
        )
        mock_step_result = (
            StepOutcome.SUCCESS,
            1.0,
            "hash",
            "sess",
        )
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=self._base_rec(),
            ),
            patch(
                "scripts.execute_recommendation.load_checkpoint",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.ensure_feature_branch",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.prune_merged_agent_branches",
            ),
            patch(
                "scripts.execute_recommendation.clean_slate",
            ),
            patch(
                "scripts.execute_recommendation.implement_step",
                return_value=mock_step_result,
            ) as mock_impl,
            patch(
                "scripts.execute_recommendation.commit_step",
                return_value=(True, "1 file changed"),
            ),
            patch(
                "scripts.execute_recommendation._append_step_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.save_checkpoint",
            ),
            patch(
                "scripts.execute_recommendation.save_plan",
            ),
            patch(
                "scripts.execute_recommendation.finalize",
                return_value=True,
            ),
            patch(
                "scripts.execute_recommendation.update_recommendation_status",
            ),
            patch(
                "scripts.execute_recommendation._scope_drift_check",
                return_value=[],
            ),
            patch(
                "scripts.execute_recommendation._capture_executor_telemetry",
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
            patch(
                "scripts.execute_recommendation.clear_checkpoint",
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="0\n",
                stderr="",
            )
            result = inner(
                "rec-413",
                step_limit=None,
                skip_critique=False,
                fast_mode=True,
                plan_json=plan_json,
            )

        assert result is True
        mock_impl.assert_called_once()

    def test_default_args_unchanged_non_fast(self):
        """Existing callers work with default fast_mode=False."""
        inner = self._inner()
        with (
            self._patch_run_acceptance(),
            patch(
                "scripts.execute_recommendation.load_recommendation",
                return_value=None,
            ),
            patch(
                "scripts.execute_recommendation.write_run_summary",
            ),
        ):
            result = inner(
                "rec-000",
                step_limit=None,
                skip_critique=True,
            )

        assert result is False


class TestFailureSummary:
    """Tests for FailureSummary dataclass and emit_failure_summary."""

    _VALID_PHASES = {
        "planning",
        "critique",
        "implementation",
        "validation",
        "postflight",
        "acceptance",
        "preflight",
        "finalize",
    }
    _VALID_CLASSES = {
        "cli_timeout",
        "parse_error",
        "test_failure",
        "scope_creep",
        "ghost_step",
        "acceptance_mismatch",
        "unknown",
    }

    def test_emit_writes_valid_json(self, tmp_path, monkeypatch):
        """emit_failure_summary writes a JSON file with all keys."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        out_dir = tmp_path / "logs" / "failure-summaries"

        mock_git = MagicMock()
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="file.py | 5 ++---",
        )

        with (
            patch(
                "scripts.execute_recommendation.subprocess.run",
                mock_git,
            ),
            patch(
                "scripts.execute_recommendation._latest_transcript_path",
                return_value="logs/transcripts/rec-fs-001.md",
            ),
            patch(
                "scripts.execute_recommendation.Path",
                side_effect=lambda p: tmp_path / p,
            ),
        ):
            emit_failure_summary(
                rec_id="rec-fs",
                failure_phase="validation",
                failure_reason="full CI validation failed",
                validation_output="FAILED tests/test_foo.py",
            )

        written = list(out_dir.glob("rec-fs-*.json"))
        assert len(written) == 1, f"Expected 1 file, found {len(written)}"
        data = json.loads(
            written[0].read_text(encoding="utf-8"),
        )

        required_keys = {
            "rec_id",
            "attempt",
            "failure_phase",
            "failure_class",
            "last_transcript_path",
            "git_diff_stat",
            "validation_output",
            "acceptance_output",
            "failure_reason",
        }
        assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"
        assert data["rec_id"] == "rec-fs"
        assert data["failure_phase"] in self._VALID_PHASES
        assert data["failure_class"] in self._VALID_CLASSES
        assert data["failure_class"] == "test_failure"

    def test_emit_noop_when_pytest_env_set(
        self,
        tmp_path,
        monkeypatch,
    ):
        """emit_failure_summary is a no-op under PYTEST_CURRENT_TEST."""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
        out_dir = tmp_path / "logs" / "failure-summaries"
        out_dir.mkdir(parents=True, exist_ok=True)

        emit_failure_summary(
            rec_id="rec-noop",
            failure_phase="preflight",
            failure_reason="should not write",
        )

        written = list(out_dir.glob("*.json"))
        assert written == [], f"Expected no files when PYTEST_CURRENT_TEST set, found {written}"

    def test_failure_phase_and_class_valid_values(self):
        """failure_phase and failure_class contain valid values."""
        summary: FailureSummary = {
            "rec_id": "rec-enum",
            "attempt": 2,
            "failure_phase": "implementation",
            "failure_class": "cli_timeout",
            "last_transcript_path": "",
            "git_diff_stat": "",
            "validation_output": "",
            "acceptance_output": "",
            "failure_reason": "timed out",
        }
        assert summary["failure_phase"] in self._VALID_PHASES
        assert summary["failure_class"] in self._VALID_CLASSES

    def test_infer_failure_class_timeout(self):
        """_infer_failure_class detects timeout patterns."""
        result = _infer_failure_class(
            "validation",
            "timed out after 600s",
        )
        assert result == "cli_timeout"

    def test_infer_failure_class_parse_error(self):
        """_infer_failure_class detects parse/json patterns."""
        result = _infer_failure_class(
            "preflight",
            "invalid JSON: Expecting value",
        )
        assert result == "parse_error"

    def test_infer_failure_class_test_failure(self):
        """_infer_failure_class detects test failure patterns."""
        result = _infer_failure_class(
            "validation",
            "full CI validation failed",
        )
        assert result == "test_failure"

    def test_infer_failure_class_acceptance(self):
        """_infer_failure_class detects acceptance patterns."""
        result = _infer_failure_class(
            "postflight",
            "post-validation acceptance check failed",
        )
        assert result == "acceptance_mismatch"

    def test_infer_failure_class_unknown(self):
        """_infer_failure_class falls back to unknown."""
        result = _infer_failure_class(
            "preflight",
            "something weird happened",
        )
        assert result == "unknown"

    def test_infer_failure_class_scope(self):
        """_infer_failure_class detects scope drift."""
        result = _infer_failure_class(
            "postflight",
            "scope drift detected",
        )
        assert result == "scope_creep"


class TestValidateAcceptanceFeasibilityActionAware:
    """Regression tests for action-aware validate_acceptance_feasibility() (rec-461, rec-401)."""

    def test_grep_nonexistent_file_create_action_is_feasible(self):
        """Pattern 1: grep on a nonexistent file is FEASIBLE when action='create'."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "grep -q 'def my_func' nonexistent.md",
                action="create",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE
        assert message == ""

    def test_grep_nonexistent_file_no_action_is_infeasible(self):
        """Pattern 1: grep on a nonexistent file is INFEASIBLE when no action is given."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "grep -q 'def my_func' nonexistent.md",
            )
        assert feasibility == AcceptanceFeasibility.INFEASIBLE
        assert "nonexistent.md" in message

    def test_python_m_nonexistent_module_is_feasible(self):
        """Pattern 3 (rec-401): python -m for a nonexistent module is FEASIBLE (module-creation recs)."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "python -m scripts.new_nonexistent_module",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE
        assert message == ""

    def test_test_f_nonexistent_file_create_action_is_feasible(self):
        """test -f on a nonexistent file is FEASIBLE when action='create' (no Pattern 1 match, falls through)."""
        with patch("pathlib.Path.exists", return_value=False):
            feasibility, message = validate_acceptance_feasibility(
                "test -f nonexistent.md",
                action="create",
            )
        assert feasibility == AcceptanceFeasibility.FEASIBLE


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
