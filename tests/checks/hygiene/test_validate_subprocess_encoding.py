"""Tests for validate_subprocess_encoding()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.hygiene.validate_subprocess_encoding import validate_subprocess_encoding


class TestValidateSubprocessEncoding:
    """Tests for validate_subprocess_encoding()."""

    validate_subprocess_encoding = staticmethod(validate_subprocess_encoding)

    def test_passes_when_encoding_present(self, tmp_path: Path) -> None:
        """No failure when subprocess.run with text=True also has encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run(["cmd"], text=True, encoding="utf-8")\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_fails_when_encoding_missing(self, tmp_path: Path) -> None:
        """Fails when subprocess.run with text=True has no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text('subprocess.run(["cmd"], capture_output=True, text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed

    def test_passes_when_no_text_true(self, tmp_path: Path) -> None:
        """No failure when subprocess.run does not use text=True."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ok.py").write_text('subprocess.run(["cmd"], capture_output=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_catches_popen_without_encoding(self, tmp_path: Path) -> None:
        """Fails for subprocess.Popen with text=True and no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_popen.py").write_text('subprocess.Popen(["cmd"], text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed
