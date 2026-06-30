"""Tests for .claude/hooks/edit_scope_guard.py -- 100% coverage."""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
from unittest.mock import patch

# The hook lives outside the normal package tree; import by path.
_HOOK_PATH = Path(__file__).parent.parent / ".claude" / "hooks" / "edit_scope_guard.py"
_SPEC = importlib.util.spec_from_file_location("edit_scope_guard", _HOOK_PATH)
_MOD = importlib.util.module_from_spec(_SPEC)  # type: ignore[arg-type]
_SPEC.loader.exec_module(_MOD)  # type: ignore[union-attr]

_active_plan_path = _MOD._active_plan_path
_scope_from_plan = _MOD._scope_from_plan
_file_is_in_scope = _MOD._file_is_in_scope
main = _MOD.main


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_main(payload: dict, *, env_plan: str | None = None, marker: Path | None = None) -> tuple[int, str]:
    """Invoke main() with the given payload dict; return (exit_code, stderr)."""
    stdin_text = json.dumps(payload)
    stderr_buf = io.StringIO()

    env_patch = {"CLAUDE_ACTIVE_PLAN": env_plan} if env_plan is not None else {}
    # Always clear CLAUDE_ACTIVE_PLAN from the real environment unless explicitly set.
    if env_plan is None:
        env_patch["CLAUDE_ACTIVE_PLAN"] = ""

    marker_path = marker if marker is not None else Path("/nonexistent/__marker__")

    with (
        patch("sys.stdin", io.StringIO(stdin_text)),
        patch("sys.stderr", stderr_buf),
        patch.dict("os.environ", env_patch),
        patch.object(_MOD, "_MARKER_FILE", marker_path),
    ):
        code = main()

    return code, stderr_buf.getvalue()


# ---------------------------------------------------------------------------
# main() -- malformed JSON input
# ---------------------------------------------------------------------------


class TestMainMalformedJson:
    def test_defensive_allow_on_bad_json(self) -> None:
        """Malformed JSON input -> exit 0 ALLOW (defensive, per never_on_main precedent)."""
        with (
            patch("sys.stdin", io.StringIO("not-json!!!")),
            patch.dict("os.environ", {"CLAUDE_ACTIVE_PLAN": ""}),
            patch.object(_MOD, "_MARKER_FILE", Path("/nonexistent/__marker__")),
        ):
            code = main()
        assert code == 0


# ---------------------------------------------------------------------------
# main() -- non-mutating tools always allowed
# ---------------------------------------------------------------------------


class TestMainNonMutatingTool:
    def test_bash_always_allowed(self) -> None:
        """Non-mutating tool (Bash) passes even when an active plan is set."""
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        code, _ = _run_main(payload, env_plan="/nonexistent/PLAN.yaml")
        assert code == 0

    def test_read_always_allowed(self) -> None:
        """Read tool is not a mutating tool; must always allow."""
        payload = {"tool_name": "Read", "tool_input": {"file_path": "scripts/validate.py"}}
        code, _ = _run_main(payload, env_plan="/nonexistent/PLAN.yaml")
        assert code == 0


# ---------------------------------------------------------------------------
# main() -- no active plan -> allow all edits
# ---------------------------------------------------------------------------


class TestMainNoActivePlan:
    def test_allow_edit_when_no_env_and_no_marker(self, tmp_path: Path) -> None:
        """No CLAUDE_ACTIVE_PLAN env and no marker file -> allow every edit."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, stderr = _run_main(payload)  # env_plan=None -> CLAUDE_ACTIVE_PLAN=""
        assert code == 0
        assert "BLOCKED" not in stderr

    def test_allow_write_when_no_env_and_no_marker(self) -> None:
        """No plan declared -> Write tool is also unconditionally allowed."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "docs/new_doc.md"},
        }
        code, _ = _run_main(payload)
        assert code == 0


# ---------------------------------------------------------------------------
# main() -- active plan, file in scope -> allow
# ---------------------------------------------------------------------------


class TestMainFileInScope:
    def test_allow_file_in_scope_dict_entry(self, tmp_path: Path) -> None:
        """File matching a dict scope entry (with 'file' key) -> exit 0 ALLOW."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - file: scripts/validate.py\n",
            encoding="utf-8",
        )
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, stderr = _run_main(payload, env_plan=str(plan))
        assert code == 0
        assert "BLOCKED" not in stderr

    def test_allow_file_in_scope_string_entry(self, tmp_path: Path) -> None:
        """File matching a plain-string scope entry -> exit 0 ALLOW."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - scripts/import_governance.py\n",
            encoding="utf-8",
        )
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/import_governance.py"},
        }
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 0

    def test_allow_file_under_scoped_directory(self, tmp_path: Path) -> None:
        """File beneath a scoped directory prefix -> exit 0 ALLOW."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - tests/\n",
            encoding="utf-8",
        )
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "tests/test_validate.py"},
        }
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 0

    def test_allow_multiline_scope(self, tmp_path: Path) -> None:
        """Multiple scope entries: file matches the second entry."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - file: scripts/validate.py\n  - file: scripts/import_governance.py\n",
            encoding="utf-8",
        )
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/import_governance.py"},
        }
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 0

    def test_allow_no_file_path_in_payload(self, tmp_path: Path) -> None:
        """Active plan set, but payload has no file_path -> allow (nothing to check)."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("scope:\n  - scripts/validate.py\n", encoding="utf-8")
        payload = {"tool_name": "Edit", "tool_input": {}}
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 0


# ---------------------------------------------------------------------------
# main() -- active plan, file NOT in scope -> deny (exit 2)
# ---------------------------------------------------------------------------


class TestMainFileOutOfScope:
    def test_deny_file_outside_scope(self, tmp_path: Path) -> None:
        """File not in scope -> exit 2 DENY with BLOCKED message."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - file: scripts/validate.py\n",
            encoding="utf-8",
        )
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/execute_recommendation.py"},
        }
        code, stderr = _run_main(payload, env_plan=str(plan))
        assert code == 2
        assert "BLOCKED" in stderr

    def test_deny_multiedit_out_of_scope(self, tmp_path: Path) -> None:
        """MultiEdit on out-of-scope file -> exit 2."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("scope:\n  - scripts/validate.py\n", encoding="utf-8")
        payload = {
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": "scripts/ops_data_portal.py"},
        }
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 2

    def test_deny_notebook_edit_out_of_scope(self, tmp_path: Path) -> None:
        """NotebookEdit on out-of-scope file -> exit 2."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("scope:\n  - notebooks/\n", encoding="utf-8")
        payload = {
            "tool_name": "NotebookEdit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, _ = _run_main(payload, env_plan=str(plan))
        assert code == 2


# ---------------------------------------------------------------------------
# main() -- active plan unreadable/unparseable -> fail-closed deny
# ---------------------------------------------------------------------------


class TestMainFailClosed:
    def test_deny_when_plan_file_missing(self) -> None:
        """Plan path set but file doesn't exist -> fail-closed exit 2."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, stderr = _run_main(payload, env_plan="/nonexistent/PLAN-does-not-exist.yaml")
        assert code == 2
        assert "BLOCKED" in stderr

    def test_deny_when_plan_is_invalid_yaml(self, tmp_path: Path) -> None:
        """Plan file contains invalid YAML -> fail-closed exit 2."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("not: valid: yaml: :\n", encoding="utf-8")
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, stderr = _run_main(payload, env_plan=str(plan))
        assert code == 2
        assert "BLOCKED" in stderr

    def test_deny_when_plan_is_not_a_dict(self, tmp_path: Path) -> None:
        """Plan YAML is a list (not a dict) -> fail-closed exit 2."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("- item1\n- item2\n", encoding="utf-8")
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, stderr = _run_main(payload, env_plan=str(plan))
        assert code == 2
        assert "BLOCKED" in stderr


# ---------------------------------------------------------------------------
# main() -- marker file path (no env var)
# ---------------------------------------------------------------------------


class TestMainMarkerFile:
    def test_marker_file_activates_plan(self, tmp_path: Path) -> None:
        """Active plan path read from .claude/active_plan marker file."""
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("scope:\n  - scripts/validate.py\n", encoding="utf-8")
        marker = tmp_path / "active_plan"
        marker.write_text(str(plan), encoding="utf-8")

        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/execute_recommendation.py"},
        }
        code, stderr = _run_main(payload, marker=marker)
        assert code == 2
        assert "BLOCKED" in stderr

    def test_empty_marker_file_means_no_plan(self, tmp_path: Path) -> None:
        """Empty marker file content -> treated as no active plan."""
        marker = tmp_path / "active_plan"
        marker.write_text("   \n", encoding="utf-8")  # whitespace only

        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "scripts/validate.py"},
        }
        code, _ = _run_main(payload, marker=marker)
        assert code == 0


# ---------------------------------------------------------------------------
# _active_plan_path
# ---------------------------------------------------------------------------


class TestActivePlanPath:
    def test_returns_none_when_neither_env_nor_marker(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"CLAUDE_ACTIVE_PLAN": ""}),
            patch.object(_MOD, "_MARKER_FILE", tmp_path / "nonexistent_marker"),
        ):
            assert _active_plan_path() is None

    def test_env_absolute_path_returned_as_is(self, tmp_path: Path) -> None:
        abs_path = str(tmp_path / "PLAN.yaml")
        with patch.dict("os.environ", {"CLAUDE_ACTIVE_PLAN": abs_path}):
            result = _active_plan_path()
        assert result == Path(abs_path)

    def test_env_relative_path_resolved_from_root(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"CLAUDE_ACTIVE_PLAN": "docs/plans/PLAN-foo.yaml"}),
            patch.object(_MOD, "_ROOT", tmp_path),
        ):
            result = _active_plan_path()
        assert result == tmp_path / "docs" / "plans" / "PLAN-foo.yaml"

    def test_marker_file_relative_resolved_from_root(self, tmp_path: Path) -> None:
        marker = tmp_path / "active_plan"
        marker.write_text("docs/plans/PLAN-bar.yaml", encoding="utf-8")
        with (
            patch.dict("os.environ", {"CLAUDE_ACTIVE_PLAN": ""}),
            patch.object(_MOD, "_MARKER_FILE", marker),
            patch.object(_MOD, "_ROOT", tmp_path),
        ):
            result = _active_plan_path()
        assert result == tmp_path / "docs" / "plans" / "PLAN-bar.yaml"


# ---------------------------------------------------------------------------
# _scope_from_plan
# ---------------------------------------------------------------------------


class TestScopeFromPlan:
    def test_dict_entries_with_file_key(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - file: scripts/validate.py\n  - file: tests/test_validate.py\n",
            encoding="utf-8",
        )
        result = _scope_from_plan(plan)
        assert result == ["scripts/validate.py", "tests/test_validate.py"]

    def test_string_entries(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("scope:\n  - scripts/validate.py\n  - tests/\n", encoding="utf-8")
        result = _scope_from_plan(plan)
        assert result == ["scripts/validate.py", "tests/"]

    def test_mixed_entries(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - file: scripts/validate.py\n  - tests/\n",
            encoding="utf-8",
        )
        result = _scope_from_plan(plan)
        assert result == ["scripts/validate.py", "tests/"]

    def test_dict_entry_without_file_key_skipped(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text(
            "scope:\n  - reason: no file key here\n  - file: scripts/validate.py\n",
            encoding="utf-8",
        )
        result = _scope_from_plan(plan)
        assert result == ["scripts/validate.py"]

    def test_returns_empty_list_when_scope_absent(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("title: A plan with no scope\n", encoding="utf-8")
        result = _scope_from_plan(plan)
        assert result == []

    def test_returns_none_on_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "PLAN-nonexistent.yaml"
        assert _scope_from_plan(missing) is None

    def test_returns_none_on_invalid_yaml(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("not: valid: yaml: :\n", encoding="utf-8")
        assert _scope_from_plan(plan) is None

    def test_returns_none_when_yaml_is_not_dict(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.yaml"
        plan.write_text("- just\n- a\n- list\n", encoding="utf-8")
        assert _scope_from_plan(plan) is None


# ---------------------------------------------------------------------------
# _file_is_in_scope
# ---------------------------------------------------------------------------


class TestFileIsInScope:
    def test_exact_match(self) -> None:
        assert _file_is_in_scope("scripts/validate.py", ["scripts/validate.py"])

    def test_prefix_match_with_trailing_slash(self) -> None:
        assert _file_is_in_scope("tests/test_validate.py", ["tests/"])

    def test_prefix_match_without_trailing_slash(self) -> None:
        assert _file_is_in_scope("tests/test_validate.py", ["tests"])

    def test_no_match_returns_false(self) -> None:
        assert not _file_is_in_scope("scripts/other.py", ["scripts/validate.py"])

    def test_leading_slash_stripped(self) -> None:
        assert _file_is_in_scope("/scripts/validate.py", ["/scripts/validate.py"])

    def test_partial_name_not_a_match(self) -> None:
        """'scripts/validate' should NOT match 'scripts/validate_extra.py'."""
        assert not _file_is_in_scope("scripts/validate_extra.py", ["scripts/validate"])

    def test_empty_scope_always_false(self) -> None:
        assert not _file_is_in_scope("scripts/validate.py", [])
