"""CLAUDE.md pointer invariant check (root CLAUDE.md must be exactly '@AGENTS.md\\n')."""

from __future__ import annotations

from pathlib import Path

from scripts.checks import _common, registry


def check_claude_md_pointer_invariant(path: str = "CLAUDE.md") -> bool:
    """Return True iff the file at path contains exactly '@AGENTS.md\n'."""
    p = Path(path)
    if not p.is_absolute():
        p = _common.ROOT / p
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return content == "@AGENTS.md\n"


@registry.register("validate_claude_md_pointer_invariant", owner="platform")
def validate_claude_md_pointer_invariant(failed: list[str]) -> None:
    """Fail if root CLAUDE.md is anything other than exactly '@AGENTS.md\n'."""
    print("\n=== CLAUDE.md pointer invariant ===")
    if not check_claude_md_pointer_invariant():
        print("  FAIL: CLAUDE.md must contain exactly '@AGENTS.md\\n'. Content diverges from expected pointer.")
        failed.append("CLAUDE.md pointer invariant")
    else:
        print("  PASS: CLAUDE.md is exactly '@AGENTS.md\\n'.")
