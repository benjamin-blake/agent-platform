#!/usr/bin/env python3
"""Collect quantitative session data: files changed, lines delta, tests added, coverage.

Informational only -- exits 0 always.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.s3_log_store import append_jsonl as s3_append_jsonl
from scripts.s3_log_store import get_backend

ROOT = Path(__file__).parent.parent
PYTHON = sys.executable
METRICS_LOG = ROOT / "logs" / ".session-metrics-log.jsonl"
PREFLIGHT_REPORT = ROOT / "logs" / ".preflight-report.json"


def get_git_stats() -> tuple[int, int, int]:
    """Parse git diff --stat for files_changed, lines_added, lines_removed."""
    result = subprocess.run(
        ["git", "diff", "--stat", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )

    files_changed = lines_added = lines_removed = 0
    if result.stdout:
        lines = result.stdout.strip().splitlines()
        summary = lines[-1] if lines else ""
        if m := re.search(r"(\d+) files? changed", summary):
            files_changed = int(m.group(1))
        if m := re.search(r"(\d+) insertion", summary):
            lines_added = int(m.group(1))
        if m := re.search(r"(\d+) deletion", summary):
            lines_removed = int(m.group(1))
    return files_changed, lines_added, lines_removed


def count_test_functions_added() -> int:
    """Count test functions added vs main by comparing branch tests to main tests."""
    # Get test functions on current branch
    branch_result = subprocess.run(
        ["git", "grep", "-c", "def test_", "--", "tests/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    # Get test functions on main (using git show to list test files)
    main_result = subprocess.run(
        ["git", "show", "origin/main:tests/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )

    branch_count = 0
    for line in (branch_result.stdout or "").splitlines():
        # git grep -c output: filename:count
        parts = line.rsplit(":", 1)
        if len(parts) == 2:
            try:
                branch_count += int(parts[1])
            except ValueError:
                pass

    # Count test functions on main by reading each test file
    main_count = 0
    if main_result.returncode == 0:
        for test_file in main_result.stdout.splitlines():
            test_file = test_file.strip()
            if not test_file.startswith("test_") or not test_file.endswith(".py"):
                continue
            file_result = subprocess.run(
                ["git", "show", f"origin/main:tests/{test_file}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
            )
            if file_result.returncode == 0:
                for line in file_result.stdout.splitlines():
                    if re.match(r"^\s*def test_", line):
                        main_count += 1

    return max(0, branch_count - main_count)


def get_pytest_results() -> tuple[int, int]:
    """Run pytest -q and parse passed/failed counts."""
    result = subprocess.run(
        [PYTHON, "-m", "pytest", "tests/", "-q", "--tb=no", "--no-header"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    passed = failed = 0
    for line in result.stdout.splitlines():
        if re.search(r"\d+ passed", line):
            if m := re.search(r"(\d+) passed", line):
                passed = int(m.group(1))
            if m := re.search(r"(\d+) failed", line):
                failed = int(m.group(1))
    return passed, failed


def get_coverage() -> str:
    """Run coverage report and extract total percentage."""
    coverage_file = ROOT / ".coverage"
    if not coverage_file.exists():
        return "N/A"
    result = subprocess.run(
        [PYTHON, "-m", "coverage", "report", "--skip-empty"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    for line in result.stdout.splitlines():
        if line.startswith("TOTAL"):
            if m := re.search(r"(\d+)%", line):
                return f"{m.group(1)}%"
    return "N/A"


def get_current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def append_jsonl(entry: dict) -> None:
    if get_backend() == "s3":
        s3_append_jsonl(".session-metrics-log.jsonl", entry)
    else:
        with METRICS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def get_session_start() -> str | None:
    """Read session_start from preflight report if available."""
    if not PREFLIGHT_REPORT.exists():
        return None
    try:
        data = json.loads(PREFLIGHT_REPORT.read_text(encoding="utf-8"))
        return data.get("session_start")
    except (json.JSONDecodeError, OSError):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect quantitative session data.")
    parser.add_argument(
        "--steps-total",
        type=int,
        default=0,
        metavar="N",
        help="Total number of Ordered Execution Steps in the session plan.",
    )
    parser.add_argument(
        "--steps-friction",
        type=int,
        default=0,
        metavar="M",
        help="Number of steps that required retro-lite friction entries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    steps_total: int = args.steps_total
    steps_friction: int = args.steps_friction
    friction_rate: float = round(steps_friction / steps_total, 4) if steps_total > 0 else 0.0

    print()
    print("=== Session Metrics ===")

    session_end = datetime.now(timezone.utc).isoformat()
    session_start = get_session_start()

    files_changed, lines_added, lines_removed = get_git_stats()
    print(f"files_changed={files_changed}")
    print(f"lines_added={lines_added}")
    print(f"lines_removed={lines_removed}")

    test_funcs = count_test_functions_added()
    print(f"test_functions_added={test_funcs}")

    passed, failed = get_pytest_results()
    print(f"tests_total={passed + failed}")
    print(f"tests_passed={passed}")
    print(f"tests_failed={failed}")

    coverage = get_coverage()
    print(f"coverage={coverage}")

    # Session timing
    session_duration_minutes: float | None = None
    if session_start:
        try:
            start_dt = datetime.fromisoformat(session_start)
            end_dt = datetime.fromisoformat(session_end)
            session_duration_minutes = round((end_dt - start_dt).total_seconds() / 60, 1)
        except ValueError:
            pass

    print(f"session_start={session_start or 'N/A'}")
    print(f"session_end={session_end}")
    print(f"session_duration_minutes={session_duration_minutes or 'N/A'}")
    print(f"Steps: {steps_total} total, {steps_friction} with friction ({friction_rate * 100:.1f}%)")
    print("========================")
    print()

    branch = get_current_branch()
    entry: dict = {
        "timestamp": session_end,
        "branch": branch,
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "test_functions_added": test_funcs,
        "tests_total": passed + failed,
        "tests_passed": passed,
        "tests_failed": failed,
        "coverage": coverage,
        "session_start": session_start,
        "session_end": session_end,
        "session_duration_minutes": session_duration_minutes,
        "steps_total": steps_total,
        "steps_friction": steps_friction,
        "friction_rate": friction_rate,
    }
    append_jsonl(entry)
    print(f"Metrics appended to {METRICS_LOG.name}")

    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
