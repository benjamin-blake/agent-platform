#!/usr/bin/env python3
"""Single source of truth for plan file resolution.

Given an optional explicit path or the current git branch, resolves to the correct
PLAN-{slug}.yaml file, falls back to the deprecated PLAN-{slug}.md / legacy PLAN.md,
or returns None if no plan exists.

Usage:
    bin/venv-python scripts/find_plan.py [docs/plans/PLAN-slug.yaml]
    # Prints the plan file path, or NOT_FOUND if no plan exists.
    # Always exits 0.
    # With an explicit path: returns that path if it exists, NOT_FOUND otherwise (no fallback).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

_MD_DEPRECATION = (
    "Resolved a markdown plan (%s). PLAN-*.md is deprecated (T1.11 / CD.22): author new plans as "
    "PLAN-{slug}.yaml validated by scripts/plan_document.py. The .md path is removed after one release cycle."
)


def find_plan_file(explicit: str | None = None) -> Path | None:
    """Find plan file by explicit path, current branch, or legacy fallback.

    Branch-based resolution prefers PLAN-{slug}.yaml; the PLAN-{slug}.md and legacy
    PLAN.md fallbacks emit a deprecation warning (as does an explicit .md path).

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
        if candidate.exists() and candidate.suffix == ".md":
            logger.warning(_MD_DEPRECATION, candidate)
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
            branch_plan_yaml = ROOT / "docs" / "plans" / f"PLAN-{slug}.yaml"
            if branch_plan_yaml.exists():
                return branch_plan_yaml
            branch_plan_md = ROOT / "docs" / "plans" / f"PLAN-{slug}.md"
            if branch_plan_md.exists():
                logger.warning(_MD_DEPRECATION, branch_plan_md)
                return branch_plan_md
    # Fallback to legacy
    legacy = ROOT / "docs" / "plans" / "PLAN.md"
    if legacy.exists():
        logger.warning(_MD_DEPRECATION, legacy)
        return legacy
    return None


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
