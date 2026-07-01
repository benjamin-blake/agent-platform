from __future__ import annotations

import re
import shutil

from scripts.checks import _common, registry

# CLI tools that may appear in prompt/agent files and must be in PATH
_KNOWN_CLI_TOOLS = {"aws", "gh", "terraform", "docker", "psql", "pip-audit"}

# CLI tools intentionally absent on the Claude Code web harness (GitHub ops use the
# GitHub MCP tools, Decision 76). The .github/prompts/ and .github/agents/ directories
# survive for live scheduled-agent surfaces; a missing optional tool is a skip, not a failure.
_OPTIONAL_CLI_TOOLS = {"gh"}


@registry.register("validate_cli_tools_in_prompts", owner="platform")
def validate_cli_tools_in_prompts(failed: list[str]) -> None:
    """Scan prompt and agent files for CLI tool references and verify each is in PATH."""
    print("\n=== CLI tool verification (prompt/agent files) ===")
    search_dirs = [
        _common.ROOT / ".github" / "prompts",
        _common.ROOT / ".github" / "agents",
    ]
    errors: list[str] = []
    referenced: dict[str, str] = {}  # tool -> first file that references it

    for directory in search_dirs:
        if not directory.exists():
            continue
        for md_file in directory.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            # Extract fenced code blocks (bash or unspecified language)
            code_blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", content, re.DOTALL)
            for block in code_blocks:
                for line in block.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    first_word = line.split()[0]
                    if first_word in _KNOWN_CLI_TOOLS and first_word not in referenced:
                        referenced[first_word] = md_file.name

    for tool, source_file in referenced.items():
        if shutil.which(tool) is None:
            if tool in _OPTIONAL_CLI_TOOLS:
                print(f"  note: optional CLI tool '{tool}' not in PATH (referenced in {source_file}); skipped (Decision 76)")
                continue
            errors.append(f"CLI tool '{tool}' referenced in {source_file} but not found in PATH")

    if errors:
        print("CLI tool verification errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("CLI tool verification")
    else:
        checked = list(referenced.keys())
        print(f"All {len(checked)} CLI tool(s) found in PATH: {', '.join(sorted(checked)) or 'none referenced'}.")
