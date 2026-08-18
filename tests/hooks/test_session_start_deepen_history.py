"""Unit tests for .claude/hooks/session_start_deepen_history.sh.

Hermeticity note (AGENTS.md): pyproject's --disable-socket addopts (tests/conftest.py)
patches only the pytest process, not git subprocesses, so hermeticity here is a design
discipline the guard cannot enforce. Every fixture below talks only to a throwaway local
origin created under tmp_path and cloned over a file:// URL -- never the network.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
_HOOK_SOURCE = _REPO_ROOT / ".claude/hooks/session_start_deepen_history.sh"


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


@pytest.fixture()
def isolated_git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate HOME and GIT_CONFIG_GLOBAL so fixture commits never touch the real --global
    config, per tests/hooks/test_session_start_commit_signing.py precedent. commit.gpgsign
    must be disabled because the container signs commits globally, which would otherwise
    break fixture commits; init.defaultBranch is dropped by this same isolation, so origin
    repos below use `git init -b main` explicitly rather than relying on the default.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    subprocess.run(["git", "config", "--global", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "config", "--global", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "config", "--global", "user.name", "Test"], check=True)
    return home


def _make_origin(tmp_path: Path) -> Path:
    """Throwaway origin: c1 creates old.txt; c2..c10 touch only filler.txt. old.txt is never
    touched again, so a --depth=1 clone of HEAD grafts a parentless commit that LOOKS like it
    created old.txt -- the confidently-wrong-answer class this hook exists to fix.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["init", "-b", "main"], cwd=origin)
    (origin / "old.txt").write_text("c1\n", encoding="utf-8")
    _git(["add", "old.txt"], cwd=origin)
    _git(["commit", "-m", "c1"], cwd=origin)
    filler = origin / "filler.txt"
    for i in range(2, 11):
        filler.write_text(f"line{i}\n", encoding="utf-8")
        _git(["add", "filler.txt"], cwd=origin)
        _git(["commit", "-m", f"c{i}"], cwd=origin)
    return origin


def _clone_with_hook(origin: Path, dest: Path, *, depth1: bool) -> Path:
    """Clone `origin` into `dest` (shallow iff depth1) and copy the real hook into
    <dest>/.claude/hooks/ so its BASH_SOURCE resolution finds a repo root inside the
    fixture instead of the real one.
    """
    args = ["clone", f"file://{origin}", str(dest)]
    if depth1:
        args[1:1] = ["--depth=1"]
    _git(args, cwd=dest.parent)
    hook_dir = dest / ".claude" / "hooks"
    hook_dir.mkdir(parents=True)
    hook_dest = hook_dir / "session_start_deepen_history.sh"
    hook_dest.write_text(_HOOK_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    hook_dest.chmod(0o755)
    return hook_dest


def _run_hook(hook_path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    # Merge, never replace: os.environ carries HOME/GIT_CONFIG_GLOBAL/PATH from the
    # isolated_git_env fixture's monkeypatch.setenv calls -- passing a bare override dict
    # to subprocess.run's env= replaces the whole environment, which would silently break
    # both git config resolution and PATH lookup for bash/git/timeout.
    env = {**os.environ, "DEEPEN_HISTORY_TIMEOUT_S": "10"}
    return subprocess.run(
        ["bash", str(hook_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def _last_touch_subject(repo: Path) -> str:
    return _git(["log", "-1", "--format=%s", "--", "old.txt"], cwd=repo).stdout.strip()


def test_hook_registered_adjacent_to_sync_main() -> None:
    """.claude/settings.json registers the hook in SessionStart, directly after
    session_start_sync_main.sh -- a readability grouping convention, not an execution-order
    guarantee (SessionStart hooks in one matcher block run in parallel).
    """
    settings = json.loads((_REPO_ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    commands = [item["command"] for item in settings["hooks"]["SessionStart"][0]["hooks"]]
    assert "bash .claude/hooks/session_start_deepen_history.sh" in commands
    assert (
        commands.index("bash .claude/hooks/session_start_deepen_history.sh")
        == commands.index("bash .claude/hooks/session_start_sync_main.sh") + 1
    )


def test_shallow_clone_reproduces_wrong_answer_then_hook_fixes_it(isolated_git_env: Path, tmp_path: Path) -> None:
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone"
    hook_path = _clone_with_hook(origin, clone, depth1=True)

    # Reproduce the wrong-answer class FIRST: the shallow graft (env DEEPEN_HISTORY_TIMEOUT_S
    # isn't involved yet) makes old.txt look like c10 added it, not c1.
    assert _git(["rev-parse", "--is-shallow-repository"], cwd=clone).stdout.strip() == "true"
    assert _git(["rev-list", "--count", "HEAD"], cwd=clone).stdout.strip() == "1"
    assert _last_touch_subject(clone) == "c10"

    result = _run_hook(hook_path, cwd=clone)

    assert result.returncode == 0
    assert "clone completed: 1 -> 10 commits" in result.stdout
    assert _git(["rev-parse", "--is-shallow-repository"], cwd=clone).stdout.strip() == "false"
    assert not (clone / ".git" / "shallow").exists()
    assert _last_touch_subject(clone) == "c1"


def test_already_complete_clone_is_noop(isolated_git_env: Path, tmp_path: Path) -> None:
    """A full (non-shallow) clone must no-op without ever invoking --unshallow, since that
    is a fatal git error (rc=128) on an already-complete repository.
    """
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone"
    hook_path = _clone_with_hook(origin, clone, depth1=False)
    assert _git(["rev-parse", "--is-shallow-repository"], cwd=clone).stdout.strip() == "false"

    result = _run_hook(hook_path, cwd=clone)

    assert result.returncode == 0
    assert "clone already complete; no-op" in result.stdout


def test_unreachable_remote_fails_open(isolated_git_env: Path, tmp_path: Path) -> None:
    """A broken remote must exit 0 (advisory, never blocks session start), leave the clone
    shallow, and print a WARNING naming what is now unreliable.
    """
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone"
    hook_path = _clone_with_hook(origin, clone, depth1=True)
    _git(["remote", "set-url", "origin", f"file://{tmp_path}/does-not-exist"], cwd=clone)

    result = _run_hook(hook_path, cwd=clone)

    assert result.returncode == 0
    assert result.stdout.count("WARNING") == 2
    assert "non-fatal" in result.stdout
    assert _git(["rev-parse", "--is-shallow-repository"], cwd=clone).stdout.strip() == "true"
    assert (clone / ".git" / "shallow").exists()
