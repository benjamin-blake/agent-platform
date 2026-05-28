"""Tests for scripts/test_coverage_checker.py."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "test_coverage_checker.py"
_spec = importlib.util.spec_from_file_location("test_coverage_checker", _SCRIPT_PATH)
_checker = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_checker)  # type: ignore[union-attr]
sys.modules["test_coverage_checker"] = _checker

extract_definitions = _checker.extract_definitions
map_source_to_test = _checker.map_source_to_test
check_test_file_exists = _checker.check_test_file_exists
get_changed_source_files = _checker.get_changed_source_files
ROOT = _checker.ROOT


class TestExtractDefinitions:
    """Tests for extract_definitions()."""

    def test_extracts_top_level_function(self, tmp_path: Path) -> None:
        """Module-level function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("def my_func():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "my_func" in result

    def test_extracts_top_level_async_function(self, tmp_path: Path) -> None:
        """Module-level async function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("async def fetch_data():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "fetch_data" in result

    def test_extracts_top_level_class(self, tmp_path: Path) -> None:
        """Module-level class names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("class MyClass:\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "MyClass" in result

    def test_skips_private_functions(self, tmp_path: Path) -> None:
        """Private functions (starting with _) are skipped."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def public_func():\n    pass\n\ndef _private_func():\n    pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "public_func" in result
        assert "_private_func" not in result

    def test_skips_nested_functions(self, tmp_path: Path) -> None:
        """Nested functions inside other functions are not extracted."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def outer():\n    def inner():\n        pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "outer" in result
        assert "inner" not in result

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []

    def test_returns_empty_for_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error returns empty list (no exception raised)."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []


class TestMapSourceToTest:
    """Tests for map_source_to_test()."""

    def test_maps_src_nested_to_test(self) -> None:
        """src/common/config.py maps to tests/test_config.py."""
        source = ROOT / "src" / "common" / "config.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_config.py"

    def test_maps_scripts_to_test(self) -> None:
        """scripts/validate.py maps to tests/test_validate.py."""
        source = ROOT / "scripts" / "validate.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_validate.py"

    def test_returns_none_for_unmapped_path(self, tmp_path: Path) -> None:
        """Paths not under src/ or scripts/ return None."""
        source = tmp_path / "docs" / "README.py"
        result = map_source_to_test(source)
        assert result is None

    def test_returns_none_for_tests_dir(self) -> None:
        """Paths under tests/ return None (not mapped to themselves)."""
        source = ROOT / "tests" / "test_config.py"
        result = map_source_to_test(source)
        assert result is None

    def test_maps_src_flat_to_test(self) -> None:
        """src/data/pipeline.py maps to tests/test_pipeline.py."""
        source = ROOT / "src" / "data" / "pipeline.py"
        result = map_source_to_test(source)
        assert result is not None
        assert result == ROOT / "tests" / "test_pipeline.py"


class TestCheckTestFileExists:
    """Tests for check_test_file_exists()."""

    def test_returns_true_when_test_file_exists(self, tmp_path: Path) -> None:
        """Returns (True, ...) when the expected test file is present."""
        with (
            patch("test_coverage_checker.map_source_to_test") as mock_map,
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            test_file = tmp_path / "tests" / "test_config.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("# tests", encoding="utf-8")
            mock_map.return_value = test_file

            source = tmp_path / "src" / "config.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "found" in msg

    def test_returns_false_when_test_file_missing(self, tmp_path: Path) -> None:
        """Returns (False, ...) when the expected test file is absent."""
        with patch("test_coverage_checker.map_source_to_test") as mock_map:
            test_file = tmp_path / "tests" / "test_missing.py"
            mock_map.return_value = test_file

            source = tmp_path / "src" / "missing.py"
            ok, msg = check_test_file_exists(source)

        assert ok is False
        assert "missing" in msg

    def test_returns_true_for_unmapped_path(self, tmp_path: Path) -> None:
        """Returns (True, skipped) for files that don't map to tests."""
        with patch("test_coverage_checker.map_source_to_test", return_value=None):
            source = tmp_path / "docs" / "something.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "skipped" in msg


class TestGetChangedSourceFiles:
    """Tests for get_changed_source_files()."""

    def test_filters_to_src_and_scripts(self) -> None:
        """Only files under src/ or scripts/ are returned."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "src/data/pipeline.py\nscripts/validate.py\ndocs/README.md\nterraform/main.tf\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        rel_parts = [str(p.relative_to(ROOT)).replace("\\", "/") for p in result]
        assert any("src/data/pipeline.py" in r for r in rel_parts)
        assert any("scripts/validate.py" in r for r in rel_parts)
        assert not any("docs" in r for r in rel_parts)
        assert not any(".tf" in r for r in rel_parts)

    def test_excludes_init_and_conftest(self) -> None:
        """__init__.py and conftest.py are excluded from results."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "src/data/__init__.py\nsrc/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "__init__.py" not in names

    def test_excludes_test_files(self) -> None:
        """Files starting with test_ are excluded."""
        mock_merge_base = MagicMock()
        mock_merge_base.returncode = 0
        mock_merge_base.stdout = "abc123\n"

        mock_diff = MagicMock()
        mock_diff.returncode = 0
        mock_diff.stdout = "tests/test_pipeline.py\nsrc/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "test_pipeline.py" not in names

    def test_uses_explicit_files_list(self) -> None:
        """When --files is provided, git diff is not called."""
        explicit = [str(ROOT / "scripts" / "validate.py")]
        with patch("test_coverage_checker.subprocess.run") as mock_run:
            result = get_changed_source_files(files=explicit)
            mock_run.assert_not_called()

        assert any("validate.py" in str(p) for p in result)

    def test_fallback_when_merge_base_fails(self) -> None:
        """Falls back to HEAD diff when merge-base against origin/main fails."""
        mock_fail = MagicMock()
        mock_fail.returncode = 128

        mock_head_diff = MagicMock()
        mock_head_diff.returncode = 0
        mock_head_diff.stdout = "src/data/pipeline.py\n"

        with patch("test_coverage_checker.subprocess.run", side_effect=[mock_fail, mock_head_diff]):
            result = get_changed_source_files()

        assert any("pipeline.py" in str(p) for p in result)
