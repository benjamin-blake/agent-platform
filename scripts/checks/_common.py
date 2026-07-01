"""Sole source of the shared primitives every extracted check depends on (Decision 104).

Extracted check modules reference these via the module object (``_common.run``,
``_common.ROOT``, etc.) rather than importing the bare names, so a single patch
target (``scripts.checks._common.run`` / ``.ROOT`` / ...) intercepts every moved
body. No scripts/checks module may recompute ROOT locally.

Has no dependency on scripts.validate (avoids an import cycle: validate.py
imports from scripts.checks.*, so scripts.checks.* must not import validate.py
at module scope).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable  # Use same interpreter that's running this script


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


def invoke_step(name: str, cmd: list[str], failed: list[str], cwd: Path | None = None) -> None:
    print(f"\n=== {name} ===")
    result = run(cmd, cwd=cwd or ROOT)
    if result.returncode != 0:
        failed.append(name)


def get_changed_files() -> list[str]:
    """Get files changed vs origin/main, falling back to HEAD. Excludes deleted paths."""
    result = run(["git", "diff", "--name-only", "origin/main"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if result.returncode == 0:
        files = result.stdout.strip().splitlines()
    else:
        result = run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        files = result.stdout.strip().splitlines()
    return [f for f in files if f and (ROOT / f).exists()]
