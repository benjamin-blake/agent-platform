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

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable  # Use same interpreter that's running this script

PLAN_PATH_RE = re.compile(r"^docs/plans/PLAN-([^/]+)\.yaml$")
_FEAT_COMMIT_RE = re.compile(r"^feat\(([^)]+)\):")


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


def get_status_aware_diff() -> list[tuple[str, str]]:
    """Status-aware diff vs the origin/main merge-base, PLUS untracked new files.

    A NEW primitive alongside get_changed_files() (Decision affected-set-selection,
    amends Decision 73) -- it does not replace or change get_changed_files()'s own
    contract (deleted-path filtering) for that function's existing callers. This is the
    sole extra diff surface the live affected-set derivation
    (scripts/checks/deps/affected_tests.py) consumes.

    Returns a list of (status, path) tuples:
      - "A" / "M" for added/modified tracked paths (git diff --name-status --no-renames
        against the merge-base with origin/main, falling back to HEAD if the merge-base
        lookup fails) -- existence-filtered, like get_changed_files().
      - "D" for deleted tracked paths -- NEVER existence-filtered (a deleted path cannot
        exist on disk by definition; dropping it here would silently blind the Incident-B
        deleted-.py-bytes data-edge channel).
      - "??" for untracked new files (git ls-files --others --exclude-standard) --
        existence-filtered (rec-2638: local --pre under-checking of new, never-added
        files; a CI checkout only ever contains committed files, so this leg is
        primarily a local-session fix).

    --no-renames keeps the output to the plain A/M/D three-letter vocabulary (no R100
    two-path rename records) -- this function's callers reason about single-path status
    entries only.
    """
    entries: list[tuple[str, str]] = []

    merge_base_result = run(
        ["git", "merge-base", "origin/main", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT
    )
    base_ref = (
        merge_base_result.stdout.strip() if merge_base_result.returncode == 0 and merge_base_result.stdout.strip() else None
    )

    diff_result = run(
        ["git", "diff", "--name-status", "--no-renames", base_ref or "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    if diff_result.returncode == 0:
        for line in diff_result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            status_raw, path = parts[0].strip(), parts[1].strip()
            if not status_raw or not path:
                continue
            status = status_raw[0]
            if status not in ("A", "M", "D"):
                continue
            if status == "D" or (ROOT / path).exists():
                entries.append((status, path))

    untracked_result = run(
        ["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT
    )
    if untracked_result.returncode == 0:
        for line in untracked_result.stdout.strip().splitlines():
            path = line.strip()
            if path and (ROOT / path).exists():
                entries.append(("??", path))

    return entries


def plan_paths_from_changed(changed_files: list[str]) -> list[str]:
    return sorted(f for f in changed_files if PLAN_PATH_RE.match(f))


def load_plan(rel_path: str, root: Path):
    """Load a PlanDocument via scripts.roadmap.plan_document.load(), injecting repo root onto sys.path."""
    root_str = str(root)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.plan_document import load  # noqa: PLC0415

        return load(root / rel_path)
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)


def feat_commit_slugs(root: Path) -> list[str]:
    """Ordered, de-duplicated slugs from feat({slug}) commit subjects in origin/main..HEAD."""
    result = run(
        ["git", "log", "origin/main..HEAD", "--format=%s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return []
    slugs: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.strip().splitlines():
        match = _FEAT_COMMIT_RE.match(line.strip())
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            slugs.append(match.group(1))
    return slugs


def origin_main_reachable(root: Path) -> bool:
    result = run(
        ["git", "rev-parse", "--verify", "-q", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    return result.returncode == 0
