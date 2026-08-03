"""Unit tests for .claude/hooks/session_start_commit_signing.py."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "session_start_commit_signing.py"
_spec = importlib.util.spec_from_file_location("session_start_commit_signing", _HOOK_PATH)
_hook_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_hook_mod)  # type: ignore[union-attr]

_ALLOWED_SIGNERS_RELATIVE = Path(".config") / "git" / "ccweb_allowed_signers"


@pytest.fixture()
def isolated_git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate both HOME and GIT_CONFIG_GLOBAL so tests never touch the real --global config."""
    home = tmp_path / "home"
    home.mkdir()
    global_config = tmp_path / "gitconfig"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    subprocess.run(["git", "config", "--global", "commit.gpgsign", "true"], check=True)
    subprocess.run(["git", "config", "--global", "gpg.format", "ssh"], check=True)
    return home


def _get_global(key: str) -> str:
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestGuards:
    """No-op unless commit.gpgsign is true AND gpg.format is ssh."""

    def test_gpgsign_false_writes_nothing(self, isolated_git_env: Path) -> None:
        subprocess.run(["git", "config", "--global", "commit.gpgsign", "false"], check=True)
        assert _hook_mod.main() == 0
        assert _get_global("gpg.ssh.allowedSignersFile") == ""
        assert not (isolated_git_env / _ALLOWED_SIGNERS_RELATIVE).exists()

    def test_gpg_format_not_ssh_writes_nothing(self, isolated_git_env: Path) -> None:
        subprocess.run(["git", "config", "--global", "gpg.format", "x509"], check=True)
        assert _hook_mod.main() == 0
        assert _get_global("gpg.ssh.allowedSignersFile") == ""
        assert not (isolated_git_env / _ALLOWED_SIGNERS_RELATIVE).exists()

    def test_gpgsign_unset_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
        assert _hook_mod.main() == 0
        assert _get_global("gpg.ssh.allowedSignersFile") == ""
        assert not (home / _ALLOWED_SIGNERS_RELATIVE).exists()


class TestHappyPath:
    """Both conditions true: create the file and point config at it."""

    def test_creates_file_with_header_and_sets_config(self, isolated_git_env: Path) -> None:
        assert _hook_mod.main() == 0
        configured = _get_global("gpg.ssh.allowedSignersFile")
        expected_path = isolated_git_env / _ALLOWED_SIGNERS_RELATIVE
        assert configured == str(expected_path)
        assert expected_path.is_file()
        assert expected_path.read_text(encoding="utf-8").startswith("#")

    def test_second_invocation_is_noop(self, isolated_git_env: Path) -> None:
        assert _hook_mod.main() == 0
        expected_path = isolated_git_env / _ALLOWED_SIGNERS_RELATIVE
        first_contents = expected_path.read_text(encoding="utf-8")
        first_mtime = expected_path.stat().st_mtime_ns

        assert _hook_mod.main() == 0

        assert expected_path.read_text(encoding="utf-8") == first_contents
        assert expected_path.stat().st_mtime_ns == first_mtime
        assert _get_global("gpg.ssh.allowedSignersFile") == str(expected_path)

    def test_already_configured_existing_file_is_noop(self, isolated_git_env: Path) -> None:
        pre_existing = isolated_git_env / "custom_signers"
        pre_existing.write_text("# pre-existing\n", encoding="utf-8")
        subprocess.run(["git", "config", "--global", "gpg.ssh.allowedSignersFile", str(pre_existing)], check=True)

        assert _hook_mod.main() == 0

        assert _get_global("gpg.ssh.allowedSignersFile") == str(pre_existing)
        assert pre_existing.read_text(encoding="utf-8") == "# pre-existing\n"
        assert not (isolated_git_env / _ALLOWED_SIGNERS_RELATIVE).exists()
