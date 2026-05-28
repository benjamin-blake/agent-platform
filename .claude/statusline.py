#!/usr/bin/env python3
"""Claude Code statusline. Shows current git branch, with a loud warning on main.

Output format examples:
    agent/foo (3 changed)
    main [WARNING: ON MAIN - DO NOT EDIT]
    (detached)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=2,
            encoding="utf-8",
            errors="replace",
            cwd=_REPO_ROOT,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def main() -> None:
    branch = _run(["git", "branch", "--show-current"]) or "(detached)"
    porcelain = _run(["git", "status", "--porcelain"])
    changed = sum(1 for line in porcelain.splitlines() if line.strip())

    suffix = f" ({changed} changed)" if changed else ""

    if branch == "main":
        line = f"main [WARNING: ON MAIN - DO NOT EDIT]{suffix}"
    else:
        line = f"{branch}{suffix}"

    sys.stdout.write(line)


if __name__ == "__main__":
    main()
