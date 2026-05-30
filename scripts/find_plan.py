#!/usr/bin/env python3
"""Single source of truth for plan file resolution.

Given an optional explicit path or the current git branch, resolves to the correct
PLAN-{slug}.md file, falls back to legacy PLAN.md, or returns None if no plan exists.

Usage:
    bin/venv-python scripts/find_plan.py [docs/plans/PLAN-slug.md]
    # Prints the plan file path, or NOT_FOUND if no plan exists.
    # Always exits 0.
    # With an explicit path: returns that path if it exists, NOT_FOUND otherwise (no fallback).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_plan_file(explicit: str | None = None) -> Path | None:
    """Find plan file by explicit path, current branch, or legacy fallback.

    Args:
        explicit: If provided, return this path if it exists; return None if it does not
                  (an explicit-but-missing path never falls back to legacy).

    Returns:
        Path to the plan file, or None if no plan file exists.
    """
    if explicit is not None:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate if candidate.exists() else None

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
    explicit = sys.argv[1] if len(sys.argv) > 1 else None
    plan = find_plan_file(explicit)
    if plan is None:
        print("NOT_FOUND")
    else:
        print(str(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
