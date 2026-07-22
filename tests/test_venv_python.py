"""Wrapper-fallback tests for bin/venv-python (Trap B, Decision 148).

Invokes the real script via subprocess in a temp repo layout (tmp_path/bin/venv-python), so
REPO_ROOT resolves relative to the copy -- no real .venv or PATH state is touched. This is the
wrapper's own test home (a new home; unrelated to tests/test_verification_graduation.py's vg
materializer coverage).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_WRAPPER_SRC = Path(__file__).parent.parent / "bin" / "venv-python"
_EXEC_BITS = stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH


def _install_wrapper(repo: Path) -> Path:
    bin_dir = repo / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / "venv-python"
    shutil.copy(_WRAPPER_SRC, dest)
    dest.chmod(dest.stat().st_mode | _EXEC_BITS)
    return dest


def _make_fake_interpreter(path: Path, importable: bool) -> None:
    """A minimal shell shim standing in for a system python on PATH.

    When ``importable`` is True it delegates to the real interpreter running this test (so
    `exec "$PYTHON" "$@"` still runs real Python end-to-end); when False it always exits
    non-zero, simulating an interpreter that cannot import the sentinel dep.
    """
    if importable:
        script = f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n'
    else:
        script = "#!/usr/bin/env bash\nexit 1\n"
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | _EXEC_BITS)


class TestVenvPythonWrapper:
    def test_resolves_venv_when_present(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        os.symlink(sys.executable, venv_bin / "python")

        result = subprocess.run(
            [str(wrapper), "-c", "print('venv-resolved')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "venv-resolved" in result.stdout

    def test_falls_back_to_dep_bearing_system_interpreter_when_venv_absent(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_fake_interpreter(fake_path_dir / "python3", importable=True)

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run(
            [str(wrapper), "-c", "import pydantic; print('fallback-resolved')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 0
        assert "fallback-resolved" in result.stdout

    def test_fail_loud_when_no_interpreter_can_import_sentinel(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_fake_interpreter(fake_path_dir / "python3", importable=False)
        _make_fake_interpreter(fake_path_dir / "python", importable=False)

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run(
            [str(wrapper), "-c", "print('should not run')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        assert "pydantic" in result.stderr
        assert "should not run" not in result.stdout
