"""Underscore instruction-file ghost-file guard (Decision 38)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_no_underscore_instructions", owner="platform")
def validate_no_underscore_instructions(failed: list[str]) -> None:
    """Fail if .github/copilot_instructions.md (underscore) exists.

    The underscore variant is a ghost file (Decision 38 deleted it); this check
    prevents re-creation.
    """
    print("\n=== Underscore instruction file check ===")
    underscore_path = _common.ROOT / ".github" / "copilot_instructions.md"
    if underscore_path.exists():
        print(f"  [FAIL] {underscore_path.relative_to(_common.ROOT)} exists -- delete it (Decision 38).")
        failed.append("Underscore instruction file check")
    else:
        print("No underscore instruction file found. OK.")
