#!/usr/bin/env python3
"""Compare plan file Scope table against actual git diff to detect drift.

Also provides --check-pr-urls to audit closed recommendations for missing
PR URL metadata.

Always exits 0 -- informational only.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.s3_log_store import append_jsonl

ROOT = Path(__file__).parent.parent
logger = logging.getLogger(__name__)
logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.WARNING)
JSONL_LOG = ROOT / "logs" / ".plan-audit-log.jsonl"
RECS_LOG = ROOT / "logs" / ".recommendations-log.jsonl"

# Import find_plan_file from the canonical module
sys.path.insert(0, str(ROOT))
from scripts.find_plan import find_plan_file  # noqa: E402


def parse_scope_table(plan_content: str) -> dict[str, str]:
    """Extract file paths and actions from the Scope table in PLAN.md."""
    scope_match = re.search(r"## Scope\s*\n(.*?)(?=\n##|\Z)", plan_content, re.DOTALL)
    if not scope_match:
        return {}

    planned: dict[str, str] = {}
    for line in scope_match.group(1).splitlines():
        row_match = re.match(r"^\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|", line)
        if row_match:
            file_path = row_match.group(1).strip().strip("`")
            action = row_match.group(2).strip()
            # Skip header and separator rows
            if re.match(r"^[-\s]*File[-\s]*$", file_path) or file_path == "File":
                continue
            planned[file_path] = action
    return planned


def get_changed_files() -> list[str]:
    """Get files changed vs origin/main, falling back to HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    if result.returncode == 0:
        files = result.stdout.strip().splitlines()
    else:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        )
        files = result.stdout.strip().splitlines()
    return [f for f in files if f]


def file_existed_on_main(file_path: str) -> bool:
    """Check whether a file existed on origin/main."""
    result = subprocess.run(
        ["git", "show", f"origin/main:{file_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if result.returncode != 0 or "fatal" in result.stderr.lower():
        logger.debug("Remote origin/main not available: %s", result.stderr.strip())
        return False
    return True


def normalise(path: str) -> str:
    return path.replace("\\", "/")


def paths_match(a: str, b: str) -> bool:
    na, nb = normalise(a), normalise(b)
    return na == nb or na.endswith(f"/{nb}") or nb.endswith(f"/{na}")


def _verify_rec_in_git(rec_id: str) -> bool:
    """Check if a rec ID appears in commit messages on origin/main.

    Uses ``git log --oneline origin/main --grep='rec-NNN'`` per the
    git-log documentation: ``--grep=<pattern>`` limits output to commits
    whose log message matches the pattern, and ``origin/main`` selects
    the remote mainline revision (gitrevisions).  This is correct because
    we only need local commit-history evidence that the rec landed.
    """
    result = subprocess.run(
        [
            "git",
            "log",
            "--oneline",
            "origin/main",
            f"--grep={rec_id}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def audit_pr_urls() -> None:
    """Read recommendations log and report closed recs missing PR URLs."""
    if not RECS_LOG.exists():
        print("No recommendations log found. Nothing to audit.")
        sys.exit(0)

    candidates: list[dict[str, object]] = []
    for line in RECS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = rec.get("status", "")
        exec_result = rec.get("execution_result", "")
        if status != "closed":
            continue
        if exec_result not in ("success", "compound"):
            continue
        pr_url = rec.get("execution_pr_url") or ""
        if pr_url:
            continue
        candidates.append(rec)

    safe: list[str] = []
    verified: list[str] = []
    missing: list[str] = []

    for rec in candidates:
        rec_id = str(rec.get("id", ""))
        exec_result = rec.get("execution_result", "")
        if exec_result == "compound":
            safe.append(rec_id)
            continue
        if _verify_rec_in_git(rec_id):
            verified.append(rec_id)
        else:
            missing.append(rec_id)

    print()
    print("=== PR URL Audit Report ===")
    print(f"Candidates: {len(candidates)} | SAFE: {len(safe)} | VERIFIED: {len(verified)} | MISSING: {len(missing)}")
    print()

    if verified:
        print("VERIFIED (commit found on origin/main):")
        for rid in verified:
            print(f"  - {rid}")
        print()

    if missing:
        print("MISSING (no commit evidence on origin/main):")
        for rid in missing:
            print(f"  - {rid}")
        print()

    if not verified and not missing:
        print("OK - No actionable candidates found.")

    print("===========================")
    print()
    sys.exit(0)


def _run_scope_drift_audit() -> None:
    """Original scope-drift audit (no-flag default behaviour)."""
    plan_path = find_plan_file()
    if plan_path is None:
        print("No plan file found (checked PLAN-{slug}.md for current branch and legacy PLAN.md). Skipping audit.")
        sys.exit(0)

    plan_content = plan_path.read_text(encoding="utf-8")
    planned = parse_scope_table(plan_content)
    changed = get_changed_files()

    unplanned: list[str] = []
    missing_files: list[str] = []
    mismatches: list[str] = []

    for cf in changed:
        if not any(paths_match(cf, pf) for pf in planned):
            unplanned.append(cf)

    for pf in planned:
        if not any(paths_match(cf, pf) for cf in changed):
            missing_files.append(pf)

    for pf, action in planned.items():
        in_diff = any(paths_match(cf, pf) for cf in changed)
        if in_diff:
            existed = file_existed_on_main(pf)
            if action == "Create" and existed:
                mismatches.append(f"{pf} (Scope says Create but file already existed on main)")
            elif action == "Modify" and not existed:
                mismatches.append(f"{pf} (Scope says Modify but file is new)")

    print()
    print("=== Plan Audit Report ===")
    print(f"Planned: {len(planned)} | Changed: {len(changed)} | Unplanned: {len(unplanned)} | Missing: {len(missing_files)}")
    print()

    if unplanned:
        print("WARN - Unplanned files in diff (not in Scope table):")
        for f in unplanned:
            print(f"  - {f}")
        print()

    if missing_files:
        print("WARN - Missing files (in Scope table but not yet changed):")
        for f in missing_files:
            print(f"  - {f}")
        print()

    if mismatches:
        print("WARN - Action mismatches:")
        for m in mismatches:
            print(f"  - {m}")
        print()

    if not unplanned and not missing_files and not mismatches:
        print("OK - No drift detected. All changed files are in the Scope table.")

    print("=========================")
    print()

    # Append JSONL record for trending
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "branch": current_branch,
        "planned": len(planned),
        "changed": len(changed),
        "unplanned": len(unplanned),
        "missing": len(missing_files),
        "action_mismatches": len(mismatches),
    }
    JSONL_LOG.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(".plan-audit-log.jsonl", record)

    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan audit and PR URL audit tools.",
    )
    parser.add_argument(
        "--check-pr-urls",
        action="store_true",
        help="Audit closed recommendations for missing PR URLs.",
    )
    args = parser.parse_args()

    if args.check_pr_urls:
        audit_pr_urls()
    else:
        _run_scope_drift_audit()


if __name__ == "__main__":
    main()
