"""Unit tests for .claude/hooks/scheduled_agent_log_only.py."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

_HOOK_PATH = Path(__file__).parent.parent / ".claude" / "hooks" / "scheduled_agent_log_only.py"
_spec = importlib.util.spec_from_file_location("scheduled_agent_log_only", _HOOK_PATH)
_hook_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_hook_mod)  # type: ignore[union-attr]


def _run(payload: dict | str, agent_name: str | None = "rec-curator", override: bool = False) -> int:
    """Call hook main() with controlled stdin and env vars."""
    stdin_content = json.dumps(payload) if isinstance(payload, dict) else payload
    env_patch: dict[str, str] = {
        "CC_SCHEDULED_AGENT_NAME": agent_name if agent_name is not None else "",
        "CC_HOOK_AGENT_OVERRIDE": "1" if override else "",
    }
    with (
        patch.dict("os.environ", env_patch, clear=False),
        patch("sys.stdin", io.StringIO(stdin_content)),
    ):
        return _hook_mod.main()


class TestScheduledAgentLogOnlyHook:
    """Tests for .claude/hooks/scheduled_agent_log_only.py."""

    def test_no_agent_env_var_allows_any_tool(self) -> None:
        """Hook is fully inert when CC_SCHEDULED_AGENT_NAME is not set."""
        payload = {"tool_name": "Write", "tool_input": {"file_path": "src/data/pipeline.py", "content": "x"}}
        result = _run(payload, agent_name=None)
        assert result == 0

    def test_write_to_allowed_agent_path_exits_0(self) -> None:
        """Write to logs/agents/rec-curator/ is permitted."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "logs/agents/rec-curator/20260509T000000Z.jsonl",
                "content": "[]",
            },
        }
        result = _run(payload)
        assert result == 0

    def test_write_to_ops_outbox_exits_0(self) -> None:
        """Write to logs/.ops-outbox/ is permitted."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "logs/.ops-outbox/telemetry_agent_invocations/abc.jsonl",
                "content": "{}",
            },
        }
        result = _run(payload)
        assert result == 0

    def test_write_to_src_exits_2(self) -> None:
        """Write to src/ is blocked when agent env var is set."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/data/pipeline.py", "content": "x"},
        }
        result = _run(payload)
        assert result == 2

    def test_edit_to_scripts_exits_2(self) -> None:
        """Edit to scripts/ is blocked."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "scripts/validate.py",
                "old_string": "x",
                "new_string": "y",
            },
        }
        result = _run(payload)
        assert result == 2

    def test_read_tool_always_exits_0(self) -> None:
        """Non-mutating tools exit 0 regardless of path."""
        payload = {"tool_name": "Read", "tool_input": {"file_path": "src/data/pipeline.py"}}
        result = _run(payload)
        assert result == 0

    def test_bash_tool_always_exits_0(self) -> None:
        """Bash tool is not blocked -- --allowedTools handles Bash restrictions."""
        payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
        result = _run(payload)
        assert result == 0

    def test_hook_agent_override_bypasses_block(self) -> None:
        """CC_HOOK_AGENT_OVERRIDE=1 bypasses the hook for test environments."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/data/pipeline.py", "content": "x"},
        }
        result = _run(payload, override=True)
        assert result == 0

    def test_malformed_json_stdin_exits_0(self) -> None:
        """Malformed stdin exits 0 (defensive fail-open)."""
        result = _run("this is not json")
        assert result == 0

    def test_missing_file_path_exits_0(self) -> None:
        """Missing file_path in tool_input exits 0 (defensive)."""
        payload = {"tool_name": "Write", "tool_input": {"content": "x"}}
        result = _run(payload)
        assert result == 0

    def test_windows_path_separators_normalized(self) -> None:
        """Backslash-separated Windows paths are normalized before comparison."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "logs\\agents\\rec-curator\\20260509T000000Z.jsonl",
                "content": "[]",
            },
        }
        result = _run(payload)
        assert result == 0

    def test_different_agent_name_blocks_other_agent_path(self) -> None:
        """Paths for a different agent name are blocked."""
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "logs/agents/doc-freshness/20260509T000000Z.jsonl",
                "content": "[]",
            },
        }
        result = _run(payload, agent_name="rec-curator")
        assert result == 2
