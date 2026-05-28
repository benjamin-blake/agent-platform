"""Tests for scripts.tool_runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.tool_runtime import _MAX_OUTPUT_BYTES, ToolRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> ToolRuntime:
    return ToolRuntime(working_dir=tmp_path)


class TestReadFile:
    def test_reads_full_file(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = runtime.read_file("hello.txt")
        assert "line1" in result
        assert "line3" in result

    def test_reads_line_range(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        f = tmp_path / "range.txt"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        result = runtime.read_file("range.txt", start_line=2, end_line=4)
        assert result == "b\nc\nd\n"

    def test_path_traversal_rejected(self, runtime: ToolRuntime) -> None:
        with pytest.raises(ValueError, match="traversal"):
            runtime.read_file("../../etc/passwd")


class TestEditFile:
    def test_replaces_single_occurrence(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = runtime.edit_file("edit.txt", "hello", "goodbye")
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == "goodbye world"

    def test_fails_on_missing_string(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = runtime.edit_file("edit.txt", "missing", "replacement")
        assert "not found" in result

    def test_fails_on_multiple_occurrences(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        f = tmp_path / "dup.txt"
        f.write_text("aa bb aa", encoding="utf-8")
        result = runtime.edit_file("dup.txt", "aa", "cc")
        assert "2 times" in result


class TestCreateFile:
    def test_creates_new_file(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        result = runtime.create_file("new.txt", "content")
        assert "Created" in result
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "content"

    def test_fails_on_existing_file(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        (tmp_path / "exists.txt").write_text("old", encoding="utf-8")
        result = runtime.create_file("exists.txt", "new")
        assert "already exists" in result

    def test_creates_parent_dirs(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        result = runtime.create_file("sub/dir/file.txt", "nested")
        assert "Created" in result
        assert (tmp_path / "sub" / "dir" / "file.txt").exists()


class TestBash:
    def test_runs_command(self, runtime: ToolRuntime) -> None:
        result = runtime.bash("echo hello")
        assert "hello" in result

    def test_timeout_enforcement(self, runtime: ToolRuntime) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sleep 10", timeout=1)):
            result = runtime.bash("sleep 10", timeout=1)
        assert "timed out" in result

    def test_output_truncation(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        big_file = tmp_path / "big.txt"
        big_file.write_text("x" * (_MAX_OUTPUT_BYTES + 1000), encoding="utf-8")
        # Use a portable command or mock for truncation test
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["cat", str(big_file)],
                returncode=0,
                stdout="x" * (_MAX_OUTPUT_BYTES + 1000),
                stderr="",
            )
            result = runtime.bash(f"cat {big_file}")
        assert "truncated" in result


class TestListDir:
    def test_lists_directory(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        result = runtime.list_dir(".")
        assert "file.txt" in result
        assert "subdir/" in result

    def test_not_a_directory(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        (tmp_path / "file.txt").touch()
        result = runtime.list_dir("file.txt")
        assert "not a directory" in result


class TestGrepSearch:
    def test_finds_matching_lines(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        (tmp_path / "search.py").write_text("def hello():\n    pass\n", encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["grep", "-rn", "--include=*.py", "-i", "hello", "."],
                returncode=0,
                stdout="./search.py:1:def hello():\n",
                stderr="",
            )
            result = runtime.grep_search("hello")
        assert "hello" in result
        assert "search.py" in result


class TestToolSchemas:
    def test_returns_six_tools(self, runtime: ToolRuntime) -> None:
        schemas = runtime.tool_schemas()
        assert len(schemas) >= 6

    def test_all_have_tool_spec(self, runtime: ToolRuntime) -> None:
        schemas = runtime.tool_schemas()
        for schema in schemas:
            assert "toolSpec" in schema
            assert "name" in schema["toolSpec"]
            assert "inputSchema" in schema["toolSpec"]

    def test_tool_names(self, runtime: ToolRuntime) -> None:
        schemas = runtime.tool_schemas()
        names = {s["toolSpec"]["name"] for s in schemas}
        assert names == {"read_file", "edit_file", "create_file", "bash", "list_dir", "grep_search"}


class TestExecute:
    def test_dispatches_known_tool(self, runtime: ToolRuntime, tmp_path: Path) -> None:
        (tmp_path / "dispatch.txt").write_text("test", encoding="utf-8")
        result = runtime.execute("read_file", {"path": "dispatch.txt"})
        assert "test" in result

    def test_unknown_tool_returns_error(self, runtime: ToolRuntime) -> None:
        result = runtime.execute("nonexistent", {})
        assert "unknown tool" in result
