"""Tests for validate_sys_executable()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.hygiene.validate_sys_executable import validate_sys_executable


class TestValidateSysExecutable:
    """Tests for validate_sys_executable()."""

    validate_sys_executable = staticmethod(validate_sys_executable)

    def test_passes_when_sys_executable_used(self, tmp_path: Path) -> None:
        """No failure when sys.executable is used."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run([sys.executable, "-m", "pytest"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert failed == []

    def test_fails_when_bare_python_used(self, tmp_path: Path) -> None:
        """Fails when bare 'python' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text("subprocess.run(['python', '-m', 'pytest'])\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed

    def test_fails_when_bare_pip_used(self, tmp_path: Path) -> None:
        """Fails when bare 'pip' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_pip.py").write_text('subprocess.run(["pip", "install", "boto3"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed
