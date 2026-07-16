"""postflight commits-ahead / scope-drift / code-review-gate / scope-file-parse /
coverage-predicate tests: _commits_ahead_of_main, _scope_drift_check, _code_review_gate,
_parse_scope_files (rec-2709 Wave 5).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from scripts.executor.postflight import (
    _code_review_gate,
    _commits_ahead_of_main,
    _parse_scope_files,
    _run_verifiers_gate,
    _scope_drift_check,
)


class TestCommitsAheadOfMain:
    """Tests for _commits_ahead_of_main()."""

    def test_returns_commit_count(self) -> None:
        mock_result = MagicMock(returncode=0, stdout="3\n")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            count = _commits_ahead_of_main()
        assert count == 3
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["git", "rev-list", "--count", "main..HEAD"]

    def test_returns_zero_on_git_error(self) -> None:
        with patch("subprocess.run", side_effect=OSError("no git")):
            count = _commits_ahead_of_main()
        assert count == 0

    def test_returns_zero_on_timeout(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            count = _commits_ahead_of_main()
        assert count == 0

    def test_returns_zero_on_nonzero_returncode(self) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            count = _commits_ahead_of_main()
        assert count == 0


class TestScopeDriftCheck:
    """Tests for _scope_drift_check()."""

    def _run(self, changed_files: list[str], plan_steps: list[dict]) -> list[str]:
        mock_result = MagicMock(returncode=0, stdout="\n".join(changed_files) + "\n")
        with patch("subprocess.run", return_value=mock_result):
            return _scope_drift_check(plan_steps)

    def test_returns_empty_when_all_files_in_plan(self) -> None:
        steps = [
            {"file": "scripts/executor/errors.py"},
            {"file": "tests/test_executor_errors.py"},
        ]
        unplanned = self._run(
            ["scripts/executor/errors.py", "tests/test_executor_errors.py"],
            steps,
        )
        assert unplanned == []

    def test_returns_unplanned_files(self) -> None:
        steps = [{"file": "scripts/executor/errors.py"}]
        unplanned = self._run(
            ["scripts/executor/errors.py", "scripts/unplanned_file.py"],
            steps,
        )
        assert "scripts/unplanned_file.py" in unplanned
        assert "scripts/executor/errors.py" not in unplanned

    def test_excludes_logs_prefix(self) -> None:
        steps: list[dict] = []
        unplanned = self._run(["logs/.execution-step-telemetry.jsonl", "logs/some.log"], steps)
        assert unplanned == []

    def test_excludes_pycache(self) -> None:
        steps: list[dict] = []
        unplanned = self._run(["__pycache__/foo.cpython-312.pyc"], steps)
        assert unplanned == []

    def test_excludes_jsonl_extension(self) -> None:
        steps: list[dict] = []
        unplanned = self._run(["logs/.recommendations-log.jsonl"], steps)
        assert unplanned == []

    def test_returns_empty_on_git_diff_failure(self) -> None:
        mock_fail = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", return_value=mock_fail):
            result = _scope_drift_check([])
        assert result == []

    def test_returns_empty_on_timeout(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = _scope_drift_check([])
        assert result == []

    def test_excludes_execute_recommendation_py(self) -> None:
        """execute_recommendation.py is always excluded (it's the thin entrypoint)."""
        steps: list[dict] = []
        unplanned = self._run(["scripts/execute_recommendation.py"], steps)
        assert unplanned == []


class TestCodeReviewGateEffortRouting:
    """Tests for effort-threaded review model resolution in _code_review_gate()."""

    def test_code_review_gate_receives_effort(self) -> None:
        """_code_review_gate with effort=XS calls resolve_model with ('review', 'XS') not ('review', 'M')."""
        mock_copilot_result = MagicMock(
            exit_code=0,
            content="No issues found.\nGATE: PASSED",
            cost_usd=0.1,
        )

        with (
            patch(
                "scripts.executor.postflight.load_prompt",
                return_value=("Review: {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}", "hash"),
            ),
            patch("scripts.executor.postflight.build_context_path", return_value=None),
            patch("scripts.executor.postflight.llm_call", return_value=mock_copilot_result),
            patch("scripts.executor.postflight.emit_process_event"),
            patch("scripts.executor.postflight.model_registry") as mock_registry,
        ):
            mock_registry.resolve_model.return_value = "gemini-3-flash-preview"
            rec = {"id": "rec-xs-001", "title": "Test", "acceptance": "grep ..."}
            from scripts.executor.plan import ExecutionPlan

            plan = ExecutionPlan(
                rec_id="rec-xs-001",
                slug="test",
                revision=1,
                timestamp="2026-01-01T00:00:00Z",
                status="approved",
                model="test",
                tokens_used=0,
                steps=[],
                plan_text="",
            )
            _code_review_gate(rec, plan, [], effort="XS")

        mock_registry.resolve_model.assert_called_once_with("review", "XS")

    def test_code_review_gate_defaults_to_m_when_no_effort(self) -> None:
        """_code_review_gate with no effort defaults to resolve_model('review', 'M')."""
        mock_copilot_result = MagicMock(
            exit_code=0,
            content="No issues found.\nGATE: PASSED",
            cost_usd=0.1,
        )

        with (
            patch(
                "scripts.executor.postflight.load_prompt",
                return_value=("Review: {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}", "hash"),
            ),
            patch("scripts.executor.postflight.build_context_path", return_value=None),
            patch("scripts.executor.postflight.llm_call", return_value=mock_copilot_result),
            patch("scripts.executor.postflight.emit_process_event"),
            patch("scripts.executor.postflight.model_registry") as mock_registry,
        ):
            mock_registry.resolve_model.return_value = None
            rec = {"id": "rec-default-001", "title": "Test", "acceptance": "grep ..."}
            from scripts.executor.plan import ExecutionPlan

            plan = ExecutionPlan(
                rec_id="rec-default-001",
                slug="test",
                revision=1,
                timestamp="2026-01-01T00:00:00Z",
                status="approved",
                model="test",
                tokens_used=0,
                steps=[],
                plan_text="",
            )
            _code_review_gate(rec, plan, [])

        mock_registry.resolve_model.assert_called_once_with("review", "M")


# ---------------------------------------------------------------------------
# Coverage-based gate predicate tests (Gap 6)
# ---------------------------------------------------------------------------


def _make_plan_text(scope_files: list[str], tier: str = "V2") -> str:
    rows = "\n".join(f"| {f} | Modify | test |" for f in scope_files)
    return f"## Verification Tier\n\n{tier}\n\n## Scope\n\n| File | Action | Purpose |\n|------|--------|------|\n{rows}\n"


class TestParseScopeFiles:
    def test_extracts_paths(self):
        text = _make_plan_text(["scripts/foo.py", "config/bar.yaml"])
        assert _parse_scope_files(text) == ["scripts/foo.py", "config/bar.yaml"]

    def test_returns_empty_when_no_scope_table(self):
        assert _parse_scope_files("## Intent\n\nNo scope here.\n") == []


class TestCoveragePredicate:
    """Tests for the coverage-based gate predicate in _run_verifiers_gate()."""

    def _make_fail_result(self, covers: list[str]):
        from scripts.verifiers.harness import VerifierResult, VerifierSeverity, VerifierStatus

        return VerifierResult(
            name="DataQualityVerifier",
            status=VerifierStatus.FAIL,
            message="stale",
            severity=VerifierSeverity.HARD_GATE,
            covers=covers,
        )

    def _patch_verifiers(self, results_list):
        """Return a context manager that patches run_all_verifiers to return results_list."""

        expected = results_list

        async def _fake_run_all(**_kwargs):
            return expected

        return patch("scripts.verifiers.run_all_verifiers", _fake_run_all)

    def test_v2_intersecting_scope_is_gated(self):
        """V2 plan + scope intersecting DQ covers -> gate returns False."""
        mock_plan = MagicMock()
        mock_plan.plan_text = _make_plan_text(["scripts/ops_data_portal.py"], tier="V2")
        dq_fail = self._make_fail_result(["scripts/ops_data_portal.py", "config/agent/data_quality/**"])

        with (
            patch("scripts.executor.plan.get_latest_plan", return_value=mock_plan),
            self._patch_verifiers([dq_fail]),
        ):
            result = _run_verifiers_gate("some-rec")

        assert result is False

    def test_v1_non_intersecting_scope_passes(self):
        """V1 plan + scope outside DQ covers -> gate returns True (advisory)."""
        mock_plan = MagicMock()
        mock_plan.plan_text = _make_plan_text(["docs/foo.md"], tier="V1")
        dq_fail = self._make_fail_result(["scripts/ops_data_portal.py", "config/agent/data_quality/**"])

        with (
            patch("scripts.executor.plan.get_latest_plan", return_value=mock_plan),
            self._patch_verifiers([dq_fail]),
        ):
            result = _run_verifiers_gate("some-rec")

        assert result is True

    def test_integration_v2_blocked(self):
        """Integration: V2 plan with covered scope blocked when DQ FAIL."""
        mock_plan = MagicMock()
        mock_plan.plan_text = _make_plan_text(["scripts/ops_data_portal.py", "config/agent/data_quality/ops.yaml"], tier="V2")
        dq_fail = self._make_fail_result(
            ["config/agent/data_quality/**", "scripts/data_quality_runner.py", "scripts/ops_data_portal.py"]
        )

        with (
            patch("scripts.executor.plan.get_latest_plan", return_value=mock_plan),
            self._patch_verifiers([dq_fail]),
        ):
            result = _run_verifiers_gate("some-rec")

        assert result is False
