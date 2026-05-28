#!/usr/bin/env python3
"""Single source of truth for plan file resolution.

Given the current git branch, resolves to the correct PLAN-{slug}.md file,
falls back to legacy PLAN.md, or returns None if no plan exists.

Usage:
    python scripts/find_plan.py
    # Prints the plan file path, or NOT_FOUND if no plan exists.
    # Always exits 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_plan_file() -> Path | None:
    """Find plan file for current branch or fall back to legacy PLAN.md.

    Returns:
        Path to the plan file, or None if no plan file exists.
    """
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if result.returncode == 0:
        branch = result.stdout.strip()
        # Detached HEAD returns empty string -- skip branch-specific lookup
        if branch and branch.startswith("agent/"):
            slug = branch[len("agent/") :]
            branch_plan = ROOT / "docs" / "plans" / f"PLAN-{slug}.md"
            if branch_plan.exists():
                return branch_plan
    # Fallback to legacy
    legacy = ROOT / "docs" / "plans" / "PLAN.md"
    return legacy if legacy.exists() else None


def main() -> int:
    plan = find_plan_file()
    if plan is None:
        print("NOT_FOUND")
    else:
        print(str(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
