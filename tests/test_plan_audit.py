"""Tests for scripts/plan_audit.py -- plan file detection, scope audit, and PR URL audit."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "plan_audit.py"
_spec = importlib.util.spec_from_file_location("plan_audit", _SCRIPT_PATH)
_plan_audit = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_plan_audit)  # type: ignore[union-attr]
sys.modules["plan_audit"] = _plan_audit  # register so patch() can find it

find_plan_file = _plan_audit.find_plan_file
parse_scope = _plan_audit.parse_scope
parse_scope_table = _plan_audit.parse_scope_table
get_changed_files = _plan_audit.get_changed_files
file_existed_on_main = _plan_audit.file_existed_on_main
normalise = _plan_audit.normalise
paths_match = _plan_audit.paths_match
audit_pr_urls = _plan_audit.audit_pr_urls
_verify_rec_in_git = _plan_audit._verify_rec_in_git
_run_scope_drift_audit = _plan_audit._run_scope_drift_audit
main = _plan_audit.main
ROOT = _plan_audit.ROOT
RECS_LOG = _plan_audit.RECS_LOG


class TestFindPlanFile:
    """Tests that plan_audit.py delegates to find_plan_file correctly.

    The find_plan_file logic is unit-tested in test_find_plan.py.
    These tests verify plan_audit.py imports and uses find_plan_file.
    """

    def test_find_plan_file_returns_path_when_plan_exists(self, tmp_path: Path) -> None:
        """plan_audit.find_plan_file() returns the plan path when one exists."""
        plan_file = tmp_path / "PLAN-test.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        with patch("plan_audit.find_plan_file", return_value=plan_file):
            result = _plan_audit.find_plan_file()

        assert result == plan_file

    def test_find_plan_file_returns_none_when_no_plan(self, tmp_path: Path) -> None:
        """plan_audit.find_plan_file() returns None when no plan exists."""
        with patch("plan_audit.find_plan_file", return_value=None):
            result = _plan_audit.find_plan_file()

        assert result is None


class TestParseScopeTable:
    """Tests for parse_scope_table function."""

    def test_parse_scope_table_valid(self) -> None:
        """Test parsing a valid scope table."""
        plan_content = """
# Plan

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/config.py` | Modify | Update config |
| `tests/test_config.py` | Create | Add tests |

## Next Section
"""
        result = parse_scope_table(plan_content)
        assert result == {
            "src/config.py": "Modify",
            "tests/test_config.py": "Create",
        }

    def test_parse_scope_table_empty(self) -> None:
        """Test parsing when no Scope table exists."""
        plan_content = "# Plan\n\n## Other Section\nSome content"
        result = parse_scope_table(plan_content)
        assert result == {}

    def test_parse_scope_table_malformed(self) -> None:
        """Test parsing malformed table (missing pipes)."""
        plan_content = """
## Scope
| File | Action | Purpose |
| src/config.py Modify Update
"""
        result = parse_scope_table(plan_content)
        # Malformed rows should be skipped
        assert result == {}


class TestGetChangedFiles:
    """Tests for get_changed_files function."""

    def test_get_changed_files_from_origin_main(self) -> None:
        """Test getting changed files against origin/main."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "src/config.py\ntests/test_config.py\n"

        with patch("plan_audit.subprocess.run", return_value=mock_result) as mock_run:
            result = get_changed_files()

            assert result == ["src/config.py", "tests/test_config.py"]
            # Verify origin/main was used
            call_args = mock_run.call_args_list[0]
            assert "origin/main" in str(call_args)

    def test_get_changed_files_fallback_to_head(self) -> None:
        """Test fallback to HEAD when origin/main fails."""
        mock_fail = MagicMock()
        mock_fail.returncode = 128  # git error
        mock_success = MagicMock()
        mock_success.returncode = 0
        mock_success.stdout = "src/config.py\n"

        with patch("plan_audit.subprocess.run", side_effect=[mock_fail, mock_success]) as mock_run:
            result = get_changed_files()

            assert result == ["src/config.py"]
            # Verify both origin/main and HEAD were tried
            assert mock_run.call_count == 2


class TestFileExistedOnMain:
    """Tests for file_existed_on_main function."""

    def test_file_existed_on_main_true(self) -> None:
        """Test when file exists on origin/main."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("plan_audit.subprocess.run", return_value=mock_result):
            result = file_existed_on_main("src/config.py")

            assert result is True

    def test_file_existed_on_main_false(self) -> None:
        """Test when file doesn't exist on origin/main."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: path 'src/config.py' does not exist"

        with patch("plan_audit.subprocess.run", return_value=mock_result):
            result = file_existed_on_main("src/config.py")

            assert result is False


class TestNormalise:
    """Tests for normalise function."""

    def test_normalise_backslashes(self) -> None:
        """Test conversion of backslashes to forward slashes."""
        assert normalise("src\\config.py") == "src/config.py"

    def test_normalise_mixed_slashes(self) -> None:
        """Test conversion of mixed slash types."""
        assert normalise("src\\data/feature_engine.py") == "src/data/feature_engine.py"

    def test_normalise_already_forward_slashes(self) -> None:
        """Test that forward slashes are unchanged."""
        assert normalise("src/config.py") == "src/config.py"


class TestPathsMatch:
    """Tests for paths_match function."""

    def test_paths_match_exact(self) -> None:
        """Test exact path match."""
        assert paths_match("src/config.py", "src/config.py") is True

    def test_paths_match_with_normalization(self) -> None:
        """Test match after normalization."""
        assert paths_match("src\\config.py", "src/config.py") is True

    def test_paths_match_partial(self) -> None:
        """Test partial path match (one ends with the other)."""
        assert paths_match("config.py", "src/config.py") is True
        assert paths_match("src/config.py", "config.py") is True

    def test_paths_no_match(self) -> None:
        """Test non-matching paths."""
        assert paths_match("src/config.py", "tests/test_config.py") is False


class TestMainArgparse:
    """Tests for argparse-based CLI routing in main()."""

    def test_no_flags_runs_scope_drift(self) -> None:
        """No flags delegates to _run_scope_drift_audit."""
        with (
            patch("plan_audit.sys.argv", ["plan_audit"]),
            patch("plan_audit._run_scope_drift_audit") as mock_scope,
        ):
            main()
            mock_scope.assert_called_once()

    def test_check_pr_urls_flag_runs_audit(self) -> None:
        """--check-pr-urls delegates to audit_pr_urls."""
        with (
            patch(
                "plan_audit.sys.argv",
                ["plan_audit", "--check-pr-urls"],
            ),
            patch("plan_audit.audit_pr_urls") as mock_audit,
        ):
            main()
            mock_audit.assert_called_once()


class TestVerifyRecInGit:
    """Tests for _verify_rec_in_git helper."""

    def test_verified_when_commit_found(self) -> None:
        """Returns True when git log finds a matching commit."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234 close rec-100\n"

        with patch("plan_audit.subprocess.run", return_value=mock_result) as mock_run:
            assert _verify_rec_in_git("rec-100") is True
            cmd = mock_run.call_args[0][0]
            assert "--grep=rec-100" in cmd
            assert "origin/main" in cmd

    def test_missing_when_no_commit(self) -> None:
        """Returns False when git log returns empty output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("plan_audit.subprocess.run", return_value=mock_result):
            assert _verify_rec_in_git("rec-999") is False

    def test_missing_when_git_fails(self) -> None:
        """Returns False when git log exits non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("plan_audit.subprocess.run", return_value=mock_result):
            assert _verify_rec_in_git("rec-999") is False


class TestAuditPrUrls:
    """Tests for audit_pr_urls classification and report."""

    @staticmethod
    def _make_recs_file(tmp_path: Path, recs: list[dict[str, object]]) -> Path:
        """Write a temporary recommendations JSONL file."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        lines = [json.dumps(r) for r in recs]
        recs_file.write_text("\n".join(lines), encoding="utf-8")
        return recs_file

    def test_safe_compound_branch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Compound execution_result is classified as SAFE."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-200",
                    "status": "closed",
                    "execution_result": "compound",
                },
            ],
        )
        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "=== PR URL Audit Report ===" in out
        assert "SAFE: 1" in out

    def test_verified_when_git_finds_commit(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Success rec verified via git log is VERIFIED."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-301",
                    "status": "closed",
                    "execution_result": "success",
                },
            ],
        )
        mock_git = MagicMock()
        mock_git.returncode = 0
        mock_git.stdout = "aaa1111 implement rec-301\n"

        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            patch(
                "plan_audit.subprocess.run",
                return_value=mock_git,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "VERIFIED: 1" in out
        assert "rec-301" in out

    def test_missing_when_no_git_evidence(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Success rec with no git evidence is MISSING."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-302",
                    "status": "closed",
                    "execution_result": "success",
                },
            ],
        )
        mock_git = MagicMock()
        mock_git.returncode = 0
        mock_git.stdout = ""

        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            patch(
                "plan_audit.subprocess.run",
                return_value=mock_git,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "MISSING: 1" in out
        assert "rec-302" in out

    def test_skips_recs_with_existing_pr_url(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Recs that already have execution_pr_url are not candidates."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-400",
                    "status": "closed",
                    "execution_result": "success",
                    "execution_pr_url": "https://github.com/o/r/pull/1",
                },
            ],
        )
        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Candidates: 0" in out

    def test_skips_non_closed_recs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Open recs are not candidates."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-500",
                    "status": "open",
                    "execution_result": "success",
                },
            ],
        )
        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Candidates: 0" in out

    def test_no_recs_file_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Missing recs file prints message and exits 0."""
        missing = tmp_path / "nonexistent.jsonl"
        with (
            patch.object(_plan_audit, "RECS_LOG", missing),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "No recommendations log found" in out

    def test_mixed_candidates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Mix of compound, verified, and missing in one run."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {
                    "id": "rec-600",
                    "status": "closed",
                    "execution_result": "compound",
                },
                {
                    "id": "rec-601",
                    "status": "closed",
                    "execution_result": "success",
                },
                {
                    "id": "rec-602",
                    "status": "closed",
                    "execution_result": "success",
                },
            ],
        )

        def _git_side_effect(*args: object, **kwargs: object) -> MagicMock:
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            grep_flag = [c for c in cmd if str(c).startswith("--grep=")]
            if grep_flag and "rec-601" in grep_flag[0]:
                result.stdout = "bbb2222 implement rec-601\n"
            else:
                result.stdout = ""
            return result

        with (
            patch.object(_plan_audit, "RECS_LOG", recs_file),
            patch(
                "plan_audit.subprocess.run",
                side_effect=_git_side_effect,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            audit_pr_urls()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "SAFE: 1" in out
        assert "VERIFIED: 1" in out
        assert "MISSING: 1" in out


class TestRunScopeDriftAudit:
    """Regression tests for the no-flag scope-drift path."""

    def test_scope_drift_no_plan_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No plan file prints skip message and exits 0."""
        with (
            patch("plan_audit.find_plan_file", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_scope_drift_audit()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "No plan file found" in out

    def test_scope_drift_clean_run(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Clean run with matching scope reports no drift."""
        plan_file = tmp_path / "PLAN-test.md"
        plan_file.write_text(
            "## Scope\n| File | Action |\n|------|--------|\n| `src/app.py` | Modify |\n",
            encoding="utf-8",
        )
        mock_git_diff = MagicMock()
        mock_git_diff.returncode = 0
        mock_git_diff.stdout = "src/app.py\n"

        mock_git_show = MagicMock()
        mock_git_show.returncode = 0
        mock_git_show.stderr = ""

        mock_branch = MagicMock()
        mock_branch.returncode = 0
        mock_branch.stdout = "agent/test"

        with (
            patch("plan_audit.find_plan_file", return_value=plan_file),
            patch(
                "plan_audit.subprocess.run",
                side_effect=[
                    mock_git_diff,
                    mock_git_show,
                    mock_branch,
                ],
            ),
            patch("plan_audit.append_jsonl"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_scope_drift_audit()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "=== Plan Audit Report ===" in out
        assert "No drift detected" in out


class TestParseScope:
    """Tests for the format-dispatching parse_scope (T1.11 / CD.22)."""

    def test_yaml_plan_scope_parsed(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN-test.yaml"
        plan.write_text(
            "slug: test\n"
            "scope:\n"
            "  - file: src/config.py\n"
            "    action: Modify\n"
            "    purpose: Update config\n"
            "  - file: tests/test_config.py\n"
            "    action: Create\n"
            "    purpose: Add tests\n",
            encoding="utf-8",
        )
        assert parse_scope(plan) == {
            "src/config.py": "Modify",
            "tests/test_config.py": "Create",
        }

    def test_yaml_plan_non_dict_returns_empty(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN-test.yaml"
        plan.write_text("- just\n- a\n- list\n", encoding="utf-8")
        assert parse_scope(plan) == {}

    def test_yaml_plan_skips_malformed_entries(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN-test.yaml"
        plan.write_text(
            "scope:\n  - file: src/a.py\n    action: Modify\n  - not-a-dict\n  - purpose: missing keys\n",
            encoding="utf-8",
        )
        assert parse_scope(plan) == {"src/a.py": "Modify"}

    def test_md_plan_falls_back_with_deprecation_warning(self, tmp_path: Path, caplog) -> None:
        plan = tmp_path / "PLAN-test.md"
        plan.write_text(
            "# Plan\n\n## Scope\n| File | Action | Purpose |\n|------|--------|---------|\n"
            "| `src/config.py` | Modify | Update config |\n",
            encoding="utf-8",
        )
        with caplog.at_level("WARNING", logger="plan_audit"):
            result = parse_scope(plan)
        assert result == {"src/config.py": "Modify"}
        assert any("deprecated" in r.message for r in caplog.records)
