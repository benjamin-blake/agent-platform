"""Environment and git concern for session_preflight."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.preflight import _common


def _print_activate_hint() -> None:
    if sys.platform == "win32":
        print("Run: source .venv/Scripts/activate  # CD.3 -- Git Bash on Windows compute-node")
    else:
        print("Run: source .venv/bin/activate")


def check_venv() -> bool:
    """Return True if sys.executable is the correct venv for this repo.

    Primary check: resolve sys.executable's parent chain to find a .venv directory
    and compare it against ROOT / ".venv". Accepts any platform venv layout
    (`bin/python` on Linux/macOS (CD.2 primary), `Scripts/python.exe` on Windows (CD.3 compute-node)).

    Fallback: accepts any venv whose path contains the repo folder name, preserving
    the worktree scenario where the venv lives at the main-repo root rather than CWD.
    """
    exe = Path(sys.executable).resolve()
    # Walk parents to find the enclosing .venv directory
    for parent in exe.parents:
        if parent.name == ".venv":
            if parent == (_common.ROOT / ".venv").resolve():
                return True
            break
    # Fallback: accept if ROOT has its own venv. This is name-independent -- the on-disk
    # directory name may stay "agent-platform" (or anything) after a GitHub rename, so a
    # match against the repo/directory name is unreliable.
    return (_common.ROOT / ".venv" / "pyvenv.cfg").exists()


def is_worktree() -> bool:
    """Return True if the current working directory is a git worktree, not the main repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=None,  # use actual cwd so the result reflects where we are
    )
    if result.returncode != 0:
        return False
    toplevel = Path(result.stdout.strip()).resolve()
    cwd = Path.cwd().resolve()
    return toplevel != cwd


def get_git_status() -> tuple[str, bool, list[str]]:
    """Return (branch, has_uncommitted_changes, stash_entries)."""
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    uncommitted = bool(status_result.stdout.strip()) if status_result.returncode == 0 else False

    stash_result = subprocess.run(
        ["git", "stash", "list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    stash_lines = [line.strip() for line in stash_result.stdout.splitlines() if line.strip()]

    return branch, uncommitted, stash_lines


def check_main_freshness() -> dict:
    """Fetch origin/main and report divergence vs the current branch HEAD.

    Best-effort: never raises on network/git failure. Returns a dict with:
        status: "ok" | "fetch_failed" | "diff_failed"
        fetched_at: ISO8601 timestamp of the fetch attempt
        commits_behind: int | None  -- commits in origin/main not in HEAD
        commits_ahead: int | None   -- commits in HEAD not in origin/main
        main_files_changed_since_branch: list[str] -- files touched on
            origin/main since the branch's merge-base with main

    Consumers: planning/implement skills read this to detect stale branches
    before launching critique subagents and before code-review diffs.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", "main", "--quiet"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=_common.ROOT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "fetch_failed",
            "fetched_at": fetched_at,
            "error": str(exc)[:300],
            "commits_behind": None,
            "commits_ahead": None,
            "main_files_changed_since_branch": [],
        }

    if fetch_result.returncode != 0:
        return {
            "status": "fetch_failed",
            "fetched_at": fetched_at,
            "error": fetch_result.stderr.strip()[:300],
            "commits_behind": None,
            "commits_ahead": None,
            "main_files_changed_since_branch": [],
        }

    counts_result = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    if counts_result.returncode != 0:
        return {
            "status": "diff_failed",
            "fetched_at": fetched_at,
            "commits_behind": None,
            "commits_ahead": None,
            "main_files_changed_since_branch": [],
        }
    parts = counts_result.stdout.strip().split()
    commits_behind = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 0
    commits_ahead = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0

    files_changed: list[str] = []
    if commits_behind > 0:
        merge_base_result = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=_common.ROOT,
        )
        if merge_base_result.returncode == 0:
            merge_base = merge_base_result.stdout.strip()
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", f"{merge_base}..origin/main"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=_common.ROOT,
            )
            if diff_result.returncode == 0:
                files_changed = [line for line in diff_result.stdout.splitlines() if line.strip()]

    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "commits_behind": commits_behind,
        "commits_ahead": commits_ahead,
        "main_files_changed_since_branch": files_changed,
    }


def _get_recent_main_commits(n: int = 5) -> list[dict]:
    """Return the last *n* commits on origin/main as structured dicts.

    Each dict has keys: sha, date (ISO), subject, files (list of changed paths).
    Returns [] on subprocess failure or when origin/main is unreachable.
    Does NOT call git fetch -- relies on origin/main already being fresh from
    check_main_freshness().
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "origin/main",
                f"-n{n * 3 + 5}",
                "--format=COMMIT:%H|%aI|%s",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            cwd=_common.ROOT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if result.returncode != 0:
        return []

    commits: list[dict] = []
    current: dict | None = None
    for line in result.stdout.splitlines():
        if line.startswith("COMMIT:"):
            if current is not None and len(commits) < n:
                commits.append(current)
            parts = line[7:].split("|", 2)
            current = {
                "sha": parts[0] if len(parts) > 0 else "",
                "date": parts[1] if len(parts) > 1 else "",
                "subject": parts[2] if len(parts) > 2 else "",
                "files": [],
            }
        elif line.strip() and current is not None:
            current["files"].append(line.strip())
    if current is not None and len(commits) < n:
        commits.append(current)
    return commits


def run_log_sync() -> dict:
    """Auto-commit and push log files when on main and only log files are dirty.

    Returns a dict with keys: status, files, and optionally error.
    status values:
      "skipped"   – not on main, or non-log files are dirty (existing flow handles it)
      "clean"     – on main but no log files are dirty
      "committed" – log files were staged, committed, and pushed successfully
      "conflict"  – push failed (conflict or auth error)
    """
    # Only run on main branch (post-merge state)
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    if branch != "main":
        return {"status": "skipped", "files": []}

    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    if status_result.returncode != 0:
        return {"status": "skipped", "files": []}

    import re as _re

    log_files: list[str] = []
    other_files: list[str] = []
    for line in status_result.stdout.splitlines():
        if not line.strip():
            continue
        # porcelain format: "XY filename" (XY are status codes, may include space)
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        file_path = parts[1].strip()
        if _re.match(r"logs/[^/]+\.(jsonl|json)$", file_path):
            log_files.append(file_path)
        else:
            other_files.append(file_path)

    if other_files:
        # Non-log files are dirty: existing uncommitted_changes handling takes over
        return {"status": "skipped", "files": []}

    if not log_files:
        return {"status": "clean", "files": []}

    # Stage and commit log files
    add_result = subprocess.run(
        ["git", "add"] + log_files,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    if add_result.returncode != 0:
        return {"status": "conflict", "files": log_files, "error": add_result.stderr.strip()}

    commit_result = subprocess.run(
        ["git", "commit", "-m", "chore: sync session logs [auto]"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    if commit_result.returncode != 0:
        return {"status": "conflict", "files": log_files, "error": commit_result.stderr.strip()}

    push_result = subprocess.run(
        ["git", "push"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_common.ROOT,
    )
    if push_result.returncode != 0 or "conflict" in push_result.stderr.lower():
        return {
            "status": "conflict",
            "files": log_files,
            "error": push_result.stderr.strip(),
        }

    return {"status": "committed", "files": log_files}


def _print_recent_main_commits(commits: list[dict]) -> None:
    """Print the Recent main commits context block."""
    print("\n--- Recent main commits ---")
    if not commits:
        print("  (none fetched -- offline or origin/main unreachable)")
    else:
        for c in commits:
            sha_short = (c.get("sha") or "")[:8]
            date_part = (c.get("date") or "")[:10]
            subject = c.get("subject") or ""
            print(f"  {date_part} {sha_short} {subject}")
    print()
