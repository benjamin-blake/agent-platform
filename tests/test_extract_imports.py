"""Tests for scripts/extract_imports.py — AST-based src.* import extraction."""

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "extract_imports.py"
_spec = importlib.util.spec_from_file_location("extract_imports", _SCRIPT_PATH)
_extract_imports = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_extract_imports)  # type: ignore[union-attr]
sys.modules["extract_imports"] = _extract_imports  # register so patch() can find it

extract_src_imports = _extract_imports.extract_src_imports


class TestExtractSrcImports:
    """Tests for extract_src_imports()."""

    def test_plain_import_src_module(self, tmp_path: Path) -> None:
        """``import src.common.config`` is extracted as ``src.common.config``."""
        f = tmp_path / "sample.py"
        f.write_text("import src.common.config\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.config"]

    def test_from_src_import(self, tmp_path: Path) -> None:
        """``from src.data.pipeline import DataPipeline`` yields ``src.data.pipeline``."""
        f = tmp_path / "sample.py"
        f.write_text("from src.data.pipeline import DataPipeline\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.data.pipeline"]

    def test_no_src_imports_returns_empty(self, tmp_path: Path) -> None:
        """A file with no src.* imports returns an empty list."""
        f = tmp_path / "sample.py"
        f.write_text("import os\nfrom pathlib import Path\n", encoding="utf-8")
        assert extract_src_imports(f) == []

    def test_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        """A file with a syntax error is skipped; returns an empty list."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n    pass\n", encoding="utf-8")
        assert extract_src_imports(f) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """A file that does not exist returns an empty list."""
        f = tmp_path / "nonexistent.py"
        assert extract_src_imports(f) == []

    def test_duplicate_imports_deduplicated(self, tmp_path: Path) -> None:
        """The same module imported twice appears only once in the output."""
        f = tmp_path / "sample.py"
        f.write_text("import src.common.config\nimport src.common.config\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.config"]

    def test_multiple_src_imports(self, tmp_path: Path) -> None:
        """Multiple distinct src.* imports are all returned."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import src.common.config\nfrom src.data.pipeline import DataPipeline\n",
            encoding="utf-8",
        )
        assert extract_src_imports(f) == ["src.common.config", "src.data.pipeline"]

    def test_non_src_import_ignored(self, tmp_path: Path) -> None:
        """Imports not starting with ``src`` are not returned."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import pandas\nfrom collections import defaultdict\nimport src.execution\n",
            encoding="utf-8",
        )
        assert extract_src_imports(f) == ["src.execution"]


class TestMain:
    """Tests for the CLI entry point."""

    def test_main_no_args_returns_zero(self) -> None:
        """main() with no file arguments exits with code 0 and prints nothing."""
        original_argv = sys.argv[:]
        try:
            sys.argv = ["extract_imports.py"]
            result = _extract_imports.main()
        finally:
            sys.argv = original_argv
        assert result == 0

    def test_main_outputs_imports(self, tmp_path: Path, capsys) -> None:
        """main() prints one import per line for each file argument."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import src.common.config\nfrom src.data.writer import Writer\n",
            encoding="utf-8",
        )
        original_argv = sys.argv[:]
        try:
            sys.argv = ["extract_imports.py", str(f)]
            _extract_imports.main()
        finally:
            sys.argv = original_argv
        captured = capsys.readouterr()
        assert captured.out.strip() == "src.common.config\nsrc.data.writer"
