"""Unit tests for .claude/hooks/fresh_branch_base.py."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

_HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "fresh_branch_base.py"
_spec = importlib.util.spec_from_file_location("fresh_branch_base", _HOOK_PATH)
_hook_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_hook_mod)  # type: ignore[union-attr]


def _run(command: str, branch_override: str | None) -> int:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    env_patch = {"CLAUDE_HOOK_BRANCH_OVERRIDE": branch_override} if branch_override is not None else {}
    with (
        patch.dict("os.environ", env_patch, clear=False),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
    ):
        return _hook_mod.main()


class TestExtractBranchCreation:
    """Parser: identifies branch-creation commands and their start-point."""

    def test_checkout_dash_b_explicit_start(self) -> None:
        assert _hook_mod.extract_branch_creation("git checkout -b foo main") == ("foo", "main")

    def test_checkout_dash_capital_b_explicit_start(self) -> None:
        assert _hook_mod.extract_branch_creation("git checkout -B foo main") == ("foo", "main")

    def test_checkout_dash_b_implicit_start(self) -> None:
        assert _hook_mod.extract_branch_creation("git checkout -b foo") == ("foo", None)

    def test_switch_dash_c_explicit_start(self) -> None:
        assert _hook_mod.extract_branch_creation("git switch -c foo main") == ("foo", "main")

    def test_branch_two_positional_args(self) -> None:
        assert _hook_mod.extract_branch_creation("git branch foo main") == ("foo", "main")

    def test_branch_one_positional_arg_implicit_start(self) -> None:
        assert _hook_mod.extract_branch_creation("git branch foo") == ("foo", None)

    def test_branch_delete_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("git branch -d foo") is None

    def test_branch_list_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("git branch") is None

    def test_branch_show_current_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("git branch --show-current") is None

    def test_checkout_without_dash_b_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("git checkout main") is None

    def test_status_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("git status") is None

    def test_non_git_command_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("ls -la") is None

    def test_empty_segment_is_not_creation(self) -> None:
        assert _hook_mod.extract_branch_creation("") is None

    def test_env_prefixed_command(self) -> None:
        assert _hook_mod.extract_branch_creation("GIT_DIR=foo git checkout -b bar main") == ("bar", "main")


class TestDecide:
    """Decision logic: block / refresh / passthrough, keyed on start-point only."""

    def test_explicit_main_start_off_main_refreshes(self) -> None:
        assert _hook_mod.decide("git checkout -b foo main", "claude/session-branch") == "refresh"

    def test_switch_explicit_main_start_off_main_refreshes(self) -> None:
        assert _hook_mod.decide("git switch -c foo main", "claude/session-branch") == "refresh"

    def test_branch_explicit_main_start_off_main_refreshes(self) -> None:
        assert _hook_mod.decide("git branch foo main", "claude/session-branch") == "refresh"

    def test_implicit_start_on_main_blocks(self) -> None:
        assert _hook_mod.decide("git checkout -b foo", "main") == "block"

    def test_explicit_main_start_on_main_blocks(self) -> None:
        assert _hook_mod.decide("git checkout -b foo main", "main") == "block"

    def test_explicit_origin_main_start_passes_through(self) -> None:
        assert _hook_mod.decide("git checkout -b foo origin/main", "claude/session-branch") == "passthrough"

    def test_explicit_feature_branch_start_passes_through(self) -> None:
        assert _hook_mod.decide("git checkout -b foo some-other-branch", "claude/session-branch") == "passthrough"

    def test_implicit_start_off_main_passes_through(self) -> None:
        """Branching off the current session branch (not main) never fires."""
        assert _hook_mod.decide("git checkout -b foo", "claude/session-branch") == "passthrough"

    def test_non_branch_git_command_passes_through(self) -> None:
        assert _hook_mod.decide("git status", "claude/session-branch") == "passthrough"

    def test_empty_command_passes_through(self) -> None:
        assert _hook_mod.decide("", "main") == "passthrough"

    def test_keyed_on_start_point_not_new_branch_name(self) -> None:
        """A branch literally named 'main' with an explicit non-main start never fires."""
        assert _hook_mod.decide("git checkout -b main some-feature-branch", "claude/session-branch") == "passthrough"

    def test_compound_command_with_cd_still_detected(self) -> None:
        assert _hook_mod.decide("cd /tmp && git checkout -b foo main", "claude/session-branch") == "refresh"


class TestMain:
    """End-to-end main() behaviour via stdin/env, with git side effects mocked."""

    def test_non_bash_tool_is_noop(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {}}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            assert _hook_mod.main() == 0

    def test_malformed_json_is_safe_noop(self) -> None:
        with patch("sys.stdin", io.StringIO("not json")):
            assert _hook_mod.main() == 0

    def test_missing_command_is_safe_noop(self) -> None:
        payload = {"tool_name": "Bash", "tool_input": {}}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            assert _hook_mod.main() == 0

    def test_on_main_block_path_exits_2(self) -> None:
        assert _run("git checkout -b foo main", branch_override="main") == 2

    def test_off_main_refresh_path_exits_0(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            result = _run("git checkout -b foo main", branch_override="claude/session-branch")
        assert result == 0
        assert mock_run.called

    def test_off_main_refresh_calls_fetch_then_force_branch(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            _run("git checkout -b foo main", branch_override="claude/session-branch")
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert ["git", "fetch", "origin", "main", "--quiet"] in commands
        assert ["git", "branch", "-f", "main", "origin/main"] in commands

    def test_fetch_failure_is_non_fatal(self) -> None:
        """A network-blocked fetch must never fail or block the branch-cut."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15)):
            result = _run("git checkout -b foo main", branch_override="claude/session-branch")
        assert result == 0

    def test_passthrough_path_makes_no_git_calls(self) -> None:
        with patch("subprocess.run") as mock_run:
            result = _run("git checkout -b foo origin/main", branch_override="claude/session-branch")
        assert result == 0
        mock_run.assert_not_called()
