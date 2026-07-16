"""get_changed_files() origin/main + deleted-path tests -- orchestrator residue (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures.validate_module import _validate

get_changed_files = _validate.get_changed_files
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
