"""validate / pre-commit-sanity / commit-retry concern: tests/session/postflight/test_validate_commit.py
(rec-2709 Wave 10).

Split from the former tests/test_session_postflight.py monolith: TestValidateMode,
TestPreCommitSanity, TestCommitRetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_postflight_module import postflight as _postflight


class TestValidateMode:
    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "Validation passed"
        result.stderr = ""
        with patch("scripts.postflight._common._run", return_value=result):
            rc = _postflight.run_validate()
        assert rc == 0

    def test_returns_nonzero_on_failure(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 1
        result.stdout = "ERROR: something failed"
        result.stderr = ""
        with patch("scripts.postflight._common._run", return_value=result):
            rc = _postflight.run_validate()
        assert rc == 1


class TestPreCommitSanity:
    def test_main_branch_returns_fail(self, capsys: pytest.CaptureFixture) -> None:
        with patch("scripts.postflight._common._current_branch", return_value="main"):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "FAIL"
        assert rc == 1

    def test_scope_comparison_detects_unplanned(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        plan_file = tmp_path / "PLAN-test.md"
        scope_content = (
            "## Scope\n\n| File | Action | Purpose |\n"
            "|------|--------|------|\n"
            "| `scripts/foo.py` | Create | test |\n\n## Next\n"
        )
        plan_file.write_text(scope_content, encoding="utf-8")
        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=plan_file),
            patch("session_postflight._get_changed_files", return_value=["scripts/foo.py", "scripts/unplanned.py"]),
            patch("scripts.postflight._common._run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        ):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "WARN"
        assert "scripts/unplanned.py" in data["unplanned"]
        assert rc == 0

    def test_clean_scope_returns_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        plan_file = tmp_path / "PLAN-test.md"
        scope_content = (
            "## Scope\n\n| File | Action | Purpose |\n"
            "|------|--------|------|\n"
            "| `scripts/foo.py` | Create | test |\n\n## Next\n"
        )
        plan_file.write_text(scope_content, encoding="utf-8")
        with (
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common.find_plan_file", return_value=plan_file),
            patch("session_postflight._get_changed_files", return_value=["scripts/foo.py"]),
            patch("scripts.postflight._common._run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        ):
            rc = _postflight.run_pre_commit_sanity()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "PASS"
        assert rc == 0


class TestCommitRetry:
    def test_succeeds_on_first_attempt(self, capsys: pytest.CaptureFixture) -> None:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "1 file changed"
        result.stderr = ""
        with patch("scripts.postflight._common._run", return_value=result):
            rc = _postflight.run_commit("feat: test commit")
        assert rc == 0

    def test_retries_on_pre_commit_failure_then_succeeds(self) -> None:
        call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            result.stderr = ""
            cmd_str = " ".join(str(c) for c in cmd)
            if "commit" in cmd_str:
                call_count += 1
                if call_count <= 2:
                    result.returncode = 1
                    result.stdout = "pre-commit hook failed"
                else:
                    result.returncode = 0
                    result.stdout = "1 file changed"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("scripts.postflight._common._run", side_effect=mock_run):
            rc = _postflight.run_commit("feat: retry test")
        assert rc == 0
        assert call_count == 3

    def test_fails_after_max_retries(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 1
            result.stdout = "pre-commit hook failed"
            result.stderr = ""
            return result

        with patch("scripts.postflight._common._run", side_effect=mock_run):
            rc = _postflight.run_commit("feat: always fail")
        assert rc == 1
