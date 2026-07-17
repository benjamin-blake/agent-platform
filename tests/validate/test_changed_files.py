"""get_changed_files() origin/main + deleted-path tests -- orchestrator residue (rec-2709 Wave 1).

Also covers get_status_aware_diff() (Decision affected-set-selection): the NEW status-aware
diff primitive added ALONGSIDE get_changed_files() -- deletions + untracked new files (rec-2638),
never replacing get_changed_files()'s own contract for its existing callers.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures.validate_module import _validate

get_changed_files = _validate.get_changed_files
get_status_aware_diff = _validate.get_status_aware_diff
ROOT = _validate.ROOT


class TestGetChangedFilesOriginMain:
    """Tests for the get_changed_files() origin/main semantics."""

    def test_uses_origin_main_on_success(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/validate.py\ntests/conftest.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert "tests/conftest.py" in files
        assert any("origin/main" in c for c in calls[0])

    def test_falls_back_to_head_on_nonzero(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            if "origin/main" in cmd:
                result.returncode = 1
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = "scripts/validate.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert any("origin/main" in c for c in calls[0])
        assert any("HEAD" in c for c in calls[1])

    def test_empty_result_returns_empty_list(self) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert files == []


class TestGetChangedFilesDeletedPaths:
    """Assert get_changed_files() drops deleted (non-existent) paths before returning."""

    def test_drops_deleted_file(self, tmp_path: Path) -> None:
        """A file listed by git diff but absent on disk is excluded from the result."""
        existing = tmp_path / "scripts" / "exists.py"
        existing.parent.mkdir()
        existing.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/exists.py\nscripts/deleted_gone.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert "scripts/exists.py" in files
        assert "scripts/deleted_gone.py" not in files

    def test_all_deleted_returns_empty(self, tmp_path: Path) -> None:
        """When all listed files are deleted, the result is an empty list."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/migrate_ops_iceberg_to_ducklake.py\ntests/test_migrate_ops_iceberg_to_ducklake.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert files == []

    def test_existing_files_all_returned(self, tmp_path: Path) -> None:
        """When all listed files exist on disk, none are filtered out."""
        for name in ("a.py", "b.py"):
            f = tmp_path / name
            f.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "a.py\nb.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert sorted(files) == ["a.py", "b.py"]


def _make_status_diff_mock(merge_base_out: str = "deadbeef\n", diff_out: str = "", ls_out: str = ""):
    def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        if cmd[:2] == ["git", "merge-base"]:
            result.stdout = merge_base_out
        elif cmd[:2] == ["git", "diff"]:
            result.stdout = diff_out
        elif cmd[:2] == ["git", "ls-files"]:
            result.stdout = ls_out
        else:
            result.stdout = ""
        return result

    return mock_run


class TestGetStatusAwareDiff:
    """get_status_aware_diff() (Decision affected-set-selection): status-aware diff vs the
    origin/main merge-base, PLUS untracked new files -- a NEW primitive alongside
    get_changed_files(), never replacing its contract."""

    def test_modified_and_added_existing_files_included(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("x = 2\n", encoding="utf-8")
        mock_run = _make_status_diff_mock(diff_out="M\ta.py\nA\tb.py\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert ("M", "a.py") in entries
        assert ("A", "b.py") in entries

    def test_deleted_path_included_without_existence_check(self, tmp_path: Path) -> None:
        """A deleted path cannot exist on disk by definition -- it must NOT be filtered out
        (Incident B: the data-edge channel needs deleted .py bytes visible)."""
        mock_run = _make_status_diff_mock(diff_out="D\tscripts/gone.py\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert ("D", "scripts/gone.py") in entries

    def test_modified_path_not_existing_on_disk_is_dropped(self, tmp_path: Path) -> None:
        """Non-deleted statuses stay existence-filtered, mirroring get_changed_files()."""
        mock_run = _make_status_diff_mock(diff_out="M\tnonexistent.py\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert entries == []

    def test_untracked_new_file_included_when_it_exists(self, tmp_path: Path) -> None:
        (tmp_path / "new_thing.py").write_text("x = 1\n", encoding="utf-8")
        mock_run = _make_status_diff_mock(ls_out="new_thing.py\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert ("??", "new_thing.py") in entries

    def test_untracked_nonexistent_path_excluded(self, tmp_path: Path) -> None:
        mock_run = _make_status_diff_mock(ls_out="ghost.py\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert entries == []

    def test_malformed_diff_lines_ignored(self, tmp_path: Path) -> None:
        """A line with no tab (e.g. a mocking/parsing artifact) is skipped, not a crash."""
        mock_run = _make_status_diff_mock(diff_out="not-a-valid-status-line\n")
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert entries == []

    def test_no_renames_flag_present_in_diff_command(self, tmp_path: Path) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            get_status_aware_diff()

        diff_cmds = [c for c in captured_cmds if c[:2] == ["git", "diff"]]
        assert diff_cmds and "--no-renames" in diff_cmds[0]

    def test_falls_back_to_head_when_merge_base_fails(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            if cmd[:2] == ["git", "merge-base"]:
                result.returncode = 1
                result.stdout = ""
            elif cmd[:2] == ["git", "diff"]:
                result.returncode = 0
                result.stdout = "M\ta.py\n"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()

        assert ("M", "a.py") in entries
        diff_cmds = [c for c in captured_cmds if c[:2] == ["git", "diff"]]
        assert diff_cmds and diff_cmds[0][-1] == "HEAD"

    def test_empty_when_nothing_changed(self, tmp_path: Path) -> None:
        mock_run = _make_status_diff_mock()
        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = get_status_aware_diff()
        assert entries == []
