"""Tool runtime for agentic LLM inference.

Provides file system and shell tools expressed in the Converse-style
``toolSpec`` schema format. The original consumer (the Bedrock transport)
was retired per CD.28; the schema shape is provider-neutral and is retained
for the T4.2 LiteLLM tool loop.

Each tool method returns a human-readable string result.  The ``execute()``
dispatcher routes tool names to methods and is the single integration point
for the tool loop.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 65_536  # 64 KB truncation limit for tool output
_DEFAULT_BASH_TIMEOUT = 60


class ToolRuntime:
    """File system and shell tools for agentic LLM inference.

    Args:
        working_dir: Root directory for all file operations and shell commands.
    """

    def __init__(self, working_dir: str | Path) -> None:
        self.working_dir = Path(working_dir).resolve()

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def read_file(self, path: str, start_line: int = 1, end_line: int = -1) -> str:
        """Read file contents, optionally a line range (1-indexed)."""
        resolved = self._resolve_path(path)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        if end_line == -1:
            end_line = len(lines)
        start_line = max(1, start_line)
        end_line = min(len(lines), end_line)
        return "".join(lines[start_line - 1 : end_line])

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        """Replace exactly one occurrence of *old_string* with *new_string*."""
        resolved = self._resolve_path(path)
        content = resolved.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return f"Error: old_string found {count} times in {path} (expected 1)"
        new_content = content.replace(old_string, new_string, 1)
        resolved.write_text(new_content, encoding="utf-8")
        return f"Successfully edited {path}"

    def create_file(self, path: str, content: str) -> str:
        """Create a new file.  Fails if the file already exists."""
        resolved = self._resolve_path(path)
        if resolved.exists():
            return f"Error: file already exists: {path}"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Created {path}"

    def bash(self, command: str, timeout: int = _DEFAULT_BASH_TIMEOUT) -> str:
        """Execute a shell command and return combined stdout+stderr."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.working_dir),
                timeout=timeout,
                env={**os.environ, "_EXECUTOR_DEPTH": "1"},
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            output = f"Command timed out after {timeout}s: {command}"
        return self._truncate(output)

    def list_dir(self, path: str = ".") -> str:
        """List directory contents.  Names ending with / are directories."""
        resolved = self._resolve_path(path)
        if not resolved.is_dir():
            return f"Error: not a directory: {path}"
        entries: list[str] = []
        for child in sorted(resolved.iterdir()):
            name = child.name + ("/" if child.is_dir() else "")
            entries.append(name)
        return "\n".join(entries)

    def grep_search(self, pattern: str, include_pattern: str | None = None) -> str:
        """Search for *pattern* in workspace files using ``grep -rn``."""
        cmd = ["grep", "-rn", "--include=*.py", "-i", pattern, "."]
        if include_pattern:
            cmd = ["grep", "-rn", f"--include={include_pattern}", "-i", pattern, "."]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.working_dir),
                timeout=30,
            )
            return self._truncate(result.stdout or "(no matches)")
        except subprocess.TimeoutExpired:
            return "Error: grep timed out after 30s"

    # ------------------------------------------------------------------
    # Schema and dispatch
    # ------------------------------------------------------------------

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return Converse-style ``toolSpec`` definitions for all tools."""
        return [
            {
                "toolSpec": {
                    "name": "read_file",
                    "description": "Read the contents of a file.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path relative to working directory."},
                                "start_line": {"type": "integer", "description": "1-based start line (default 1)."},
                                "end_line": {"type": "integer", "description": "1-based end line (default -1 for all)."},
                            },
                            "required": ["path"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "edit_file",
                    "description": "Replace exactly one occurrence of old_string with new_string in a file.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path."},
                                "old_string": {"type": "string", "description": "Exact text to find (must appear once)."},
                                "new_string": {"type": "string", "description": "Replacement text."},
                            },
                            "required": ["path", "old_string", "new_string"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "create_file",
                    "description": "Create a new file with the given content. Fails if file exists.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path to create."},
                                "content": {"type": "string", "description": "File content."},
                            },
                            "required": ["path", "content"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "bash",
                    "description": "Execute a shell command and return output.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to execute."},
                                "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)."},
                            },
                            "required": ["command"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "list_dir",
                    "description": "List contents of a directory.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Directory path (default '.')."},
                            },
                            "required": [],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "grep_search",
                    "description": "Search for a pattern in workspace files.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Search pattern (case-insensitive)."},
                                "include_pattern": {
                                    "type": "string",
                                    "description": "Glob pattern for files to search (e.g. '*.py').",
                                },
                            },
                            "required": ["pattern"],
                        }
                    },
                }
            },
        ]

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Dispatch a tool call by name.  Returns the tool result string."""
        dispatch = {
            "read_file": lambda: self.read_file(
                tool_input["path"],
                tool_input.get("start_line", 1),
                tool_input.get("end_line", -1),
            ),
            "edit_file": lambda: self.edit_file(
                tool_input["path"],
                tool_input["old_string"],
                tool_input["new_string"],
            ),
            "create_file": lambda: self.create_file(
                tool_input["path"],
                tool_input["content"],
            ),
            "bash": lambda: self.bash(
                tool_input["command"],
                tool_input.get("timeout", _DEFAULT_BASH_TIMEOUT),
            ),
            "list_dir": lambda: self.list_dir(tool_input.get("path", ".")),
            "grep_search": lambda: self.grep_search(
                tool_input["pattern"],
                tool_input.get("include_pattern"),
            ),
        }
        handler = dispatch.get(tool_name)
        if handler is None:
            return f"Error: unknown tool '{tool_name}'"
        try:
            return handler()
        except Exception as exc:  # noqa: BLE001
            return f"Error executing {tool_name}: {exc}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> Path:
        """Resolve *path* relative to working_dir, guarding traversal."""
        resolved = (self.working_dir / path).resolve()
        if not resolved.is_relative_to(self.working_dir):
            msg = f"Path traversal rejected: {path}"
            raise ValueError(msg)
        return resolved

    @staticmethod
    def _truncate(text: str) -> str:
        """Truncate text to ``_MAX_OUTPUT_BYTES``."""
        if len(text.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
            truncated = text.encode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            return truncated + "\n... (output truncated)"
        return text
