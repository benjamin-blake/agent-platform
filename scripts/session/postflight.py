#!/usr/bin/env python3
"""Post-session deterministic automation: validate, pre-commit-sanity, commit, push, merge.

Thin CLI facade over the scripts/postflight package (SLOC decomposition, PLAN-sloc-session-postflight).
Replaces pre-commit-sanity.agent.md and session_close.prompt.md automation.

Modes:
    --validate           Run scripts/validate.py and return exit code
    --pre-commit-sanity  Check branch, scope, orphaned TODOs; output JSON
    --commit "message"   Run git add + commit with pre-commit retry (max 3)
    --push               Push, create PR, poll CI, auto-merge; output JSON
    --metrics            Run session/metrics.py + roadmap/plan_audit.py; return combined output
    --close              Intent verification + SESSION_LOG entry + pre-commit sanity; output JSON
    --log-housekeeping   Commit and push uncommitted JSONL log files
    --close-session      Finalise the active telemetry session opened by --open-session
    --auto "message"     Full session close in one command: validate -> close -> metrics -> commit -> push -> log-housekeeping

Usage:
    python scripts/session/postflight.py --validate
    python scripts/session/postflight.py --pre-commit-sanity
    python scripts/session/postflight.py --commit "feat: implement something"
    python scripts/session/postflight.py --push
    python scripts/session/postflight.py --metrics
    python scripts/session/postflight.py --close
    python scripts/session/postflight.py --log-housekeeping
    python scripts/session/postflight.py --close-session --outcome success
    python scripts/session/postflight.py --auto "feat: implement something" --steps-total 10 --steps-friction 2
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess  # noqa: F401  (kept: facade byte-stable namespace surface, mirrors decision-80/104 precedent)
import sys
import time  # noqa: F401  (kept so session.postflight.time.{sleep,time} navigation patches still resolve)
from pathlib import Path

# Bootstrap the repo root onto sys.path BEFORE importing the scripts.postflight package: run_close
# self-reinvokes this file by FILE PATH (`scripts/session/postflight.py --pre-commit-sanity`, not
# `-m scripts.session.postflight`), and a direct file-path invocation puts sys.path[0] at this
# file's own directory (scripts/), not the repo root -- without this, `from scripts.postflight
# import ...` would fail with ModuleNotFoundError under that invocation mode.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.postflight import _common, housekeeping, remote  # noqa: E402

# Facade re-exports (Decision 80/104 pattern): every public function and every test-referenced
# private symbol from the pre-decomposition module, so `from scripts.session.postflight import X`
# and getattr(session_postflight, X) keep resolving. Consolidated in ONE block per source module
# (tests/CLAUDE.md -- ruff format silently drops symbols from a second block of the same module's
# imports).
from scripts.postflight._common import (  # noqa: E402, F401
    _PRUNE_SKIP_NAMES,
    _SSO_PROFILE,
    ARCHIVE_DIR,
    CI_POLL_INTERVAL_SECONDS,
    CI_POLL_TIMEOUT_SECONDS,
    DEFAULT_MAX_AGE_DAYS,
    LOGS_DIR,
    MAX_COMMIT_RETRIES,
    PYTHON,
    ROOT,
    TELEMETRY_ACTIVE_SESSION_FILE,
    _current_branch,
    _run,
    clear_checkpoint,
    find_plan_file,
    logger,
)
from scripts.postflight.housekeeping import (  # noqa: E402, F401
    _load_max_age_days,
    _stage_document_derived_tables,
    close_telemetry_session,
    prune_telemetry_logs,
    run_log_housekeeping,
    run_metrics,
)
from scripts.postflight.remote import run_push  # noqa: E402, F401


def _parse_scope_table(plan_content: str) -> dict[str, str]:
    scope_match = re.search(r"## Scope\s*\n(.*?)(?=\n##|\Z)", plan_content, re.DOTALL)
    if not scope_match:
        return {}
    planned: dict[str, str] = {}
    for line in scope_match.group(1).splitlines():
        row_match = re.match(r"^\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|", line)
        if row_match:
            file_path = row_match.group(1).strip().strip("`")
            action = row_match.group(2).strip()
            if re.match(r"^[-\s]*File[-\s]*$", file_path) or file_path == "File":
                continue
            planned[file_path] = action
    return planned


def _get_changed_files() -> list[str]:
    result = _common._run(["git", "diff", "--name-only", "origin/main"])
    if result.returncode == 0 and result.stdout.strip():
        return [f for f in result.stdout.strip().splitlines() if f]
    result = _common._run(["git", "diff", "--name-only", "HEAD"])
    return [f for f in result.stdout.strip().splitlines() if f] if result.returncode == 0 else []


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _paths_match(a: str, b: str) -> bool:
    na, nb = _normalize_path(a), _normalize_path(b)
    return na == nb or na.endswith(f"/{nb}") or nb.endswith(f"/{na}")


def run_validate() -> int:
    """Run the full presubmit gate (no flags) to match remote CI exactly and return its exit code."""
    result = _common._run([_common.PYTHON, "-m", "scripts.validate"])
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def run_pre_commit_sanity() -> int:
    """Check branch, scope drift, orphaned TODOs. Output JSON."""
    branch = _common._current_branch()

    if branch == "main":
        output = {"status": "FAIL", "branch": branch, "reason": "On main branch - cannot commit"}
        print(json.dumps(output, indent=2))
        return 1

    plan_file = _common.find_plan_file()
    planned: dict[str, str] = {}
    plan_found = False
    if plan_file and plan_file.exists():
        planned = _parse_scope_table(plan_file.read_text(encoding="utf-8"))
        plan_found = True

    changed = _get_changed_files()

    unplanned: list[str] = []
    if plan_found:
        for cf in changed:
            if not any(_paths_match(cf, pf) for pf in planned):
                unplanned.append(cf)

    # Scan for orphaned TODOs/FIXMEs in diff
    diff_result = _common._run(["git", "diff", "origin/main"])
    if diff_result.returncode != 0:
        diff_result = _common._run(["git", "diff", "HEAD"])
    orphaned_todos: list[str] = []
    for line in (diff_result.stdout or "").splitlines():
        if re.match(r"^\+.*\b(TODO|FIXME)\b", line):
            orphaned_todos.append(line[1:].strip())

    status = "PASS"
    if unplanned:
        status = "WARN"
    if branch == "main":
        status = "FAIL"

    output: dict = {
        "status": status,
        "branch": branch,
        "planned": len(planned),
        "changed": len(changed),
        "unplanned": unplanned,
        "orphaned_todos": orphaned_todos,
    }
    print(json.dumps(output, indent=2))
    return 0


def run_commit(message: str) -> int:
    """Run git add + commit with pre-commit retry up to MAX_COMMIT_RETRIES."""
    for attempt in range(1, _common.MAX_COMMIT_RETRIES + 1):
        add_result = _common._run(["git", "add", "."])
        if add_result.returncode != 0:
            print(f"git add failed: {add_result.stderr}", file=sys.stderr)
            return 1

        commit_result = _common._run(["git", "commit", "-m", message])
        if commit_result.returncode == 0:
            print(f"Committed on attempt {attempt}: {message}")
            print(commit_result.stdout)
            return 0

        # Pre-commit may have modified files -- check if that's the case
        stdout_lower = commit_result.stdout.lower()
        if "hook" in stdout_lower or "pre-commit" in stdout_lower or attempt < _common.MAX_COMMIT_RETRIES:
            print(f"Commit attempt {attempt} failed (pre-commit may have modified files). Retrying...")
            print(commit_result.stdout)
            continue

        # Non-retryable failure
        print(f"Commit failed: {commit_result.stdout}", file=sys.stderr)
        print(commit_result.stderr, file=sys.stderr)
        return 1

    print(f"Commit failed after {_common.MAX_COMMIT_RETRIES} attempts.", file=sys.stderr)
    return 1


def run_close() -> int:
    """Intent verification, SESSION_LOG entry, and pre-commit sanity in one shot.

    Returns JSON with keys:
      intent_achieved  – True/False or None (no plan)
      session_log_entry – Markdown string ready to prepend to SESSION_LOG.md
      sanity_status     – "PASS" | "WARN" | "FAIL"
      details           – dict with raw sub-results
    """
    # ── 1. Intent verification ────────────────────────────────────────────────
    plan_file = _common.find_plan_file()
    intent_text: str = ""
    intent_achieved: bool | None = None

    if plan_file and plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
        intent_match = re.search(r"## Intent\s*\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if intent_match:
            intent_text = intent_match.group(1).strip()

    diff_stat = _common._run(["git", "diff", "--stat", "origin/main"])
    diff_summary = diff_stat.stdout.strip() if diff_stat.returncode == 0 else "(git diff unavailable)"

    if intent_text:
        # Simple heuristic: if there are changed files, mark intent as achieved
        has_changes = bool(diff_summary and "changed" in diff_summary)
        intent_achieved = has_changes

    # ── 2. SESSION_LOG entry template ─────────────────────────────────────────
    today = _dt.date.today().isoformat()
    branch = _common._current_branch()
    plan_name = plan_file.name if plan_file else "PLAN.md"

    session_log_entry = (
        f"## [{today}] — {branch}\n\n"
        f"**Plan:** {plan_name}  \n"
        f"**Intent:** {intent_text or '(see plan file)'}  \n"
        f"**Done:** <!-- fill in -->\n\n"
        f"### Changes\n\n"
        f"```\n{diff_summary}\n```\n"
    )

    # ── 3. Pre-commit sanity ───────────────────────────────────────────────────
    sanity_result = _common._run([_common.PYTHON, "scripts/session/postflight.py", "--pre-commit-sanity"])
    sanity_status = "FAIL"
    if sanity_result.returncode == 0:
        try:
            sanity_data = json.loads(sanity_result.stdout)
            sanity_status = sanity_data.get("status", "FAIL")
        except (json.JSONDecodeError, KeyError):
            sanity_status = "FAIL"

    output: dict = {
        "intent_achieved": intent_achieved,
        "session_log_entry": session_log_entry,
        "sanity_status": sanity_status,
        "details": {
            "intent_text": intent_text,
            "diff_summary": diff_summary,
            "plan_file": str(plan_file) if plan_file else None,
        },
    }
    print(json.dumps(output, indent=2))
    return 0


def run_auto(commit_message: str, steps_total: int = 0, steps_friction: int = 0) -> int:
    """Full session close: validate -> close -> metrics -> commit -> push -> log-housekeeping.

    Returns combined JSON status printed to stdout. Stops at first non-zero exit
    code except for log-housekeeping (best-effort, failure does not affect rc).

    Output JSON fields::

        {
          "validate": "PASS" | "FAIL",
          "close_exit": int,
          "sanity_status": "PASS" | "FAIL" | "UNKNOWN",
          "intent_achieved": bool | null,
          "session_log_entry": str,
          "commit": "PASS" | "FAIL",
          "status": "merged" | "validate_failed" | "sanity_failed"
                    | "commit_failed" | "ci_failed" | "ci_timeout"
                    | "push_failed" | "unknown",
          "pr_url": str,
          "error_summary": str
        }
    """
    import contextlib
    import io

    if not commit_message.strip():
        print(json.dumps({"status": "commit_failed", "error_summary": "commit_message is empty"}))
        return 1

    results: dict = {}

    # 1. Validate
    print("[auto] Running --validate...", flush=True)
    rc = run_validate()
    results["validate"] = "PASS" if rc == 0 else "FAIL"
    if rc != 0:
        results["status"] = "validate_failed"
        print(json.dumps(results, indent=2))
        return rc

    # 2. Close (capture output so we can surface key fields)
    print("[auto] Running --close...", flush=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_close()
    close_raw = buf.getvalue().strip()
    results["close_exit"] = rc
    try:
        close_data = json.loads(close_raw)
        results["sanity_status"] = close_data.get("sanity_status", "UNKNOWN")
        results["intent_achieved"] = close_data.get("intent_achieved")
        results["session_log_entry"] = close_data.get("session_log_entry", "")
    except (json.JSONDecodeError, ValueError):
        results["sanity_status"] = "UNKNOWN"
    print(close_raw)
    if results.get("sanity_status") == "FAIL":
        results["status"] = "sanity_failed"
        print(json.dumps(results, indent=2))
        return 1

    # 3. Metrics
    print("[auto] Running --metrics...", flush=True)
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        housekeeping.run_metrics(steps_total, steps_friction)
    print(buf2.getvalue().strip())

    # 4. Commit
    print(f"[auto] Running --commit '{commit_message}'...", flush=True)
    rc = run_commit(commit_message)
    results["commit"] = "PASS" if rc == 0 else "FAIL"
    if rc != 0:
        results["status"] = "commit_failed"
        print(json.dumps(results, indent=2))
        return rc

    # 5. Push
    print("[auto] Running --push...", flush=True)
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        rc = remote.run_push()
    push_raw = buf3.getvalue().strip()
    print(push_raw)
    try:
        push_data = json.loads(push_raw)
        results["status"] = push_data.get("status", "unknown")
        results["pr_url"] = push_data.get("pr_url", "")
        results["error_summary"] = push_data.get("error_summary", "")
    except (json.JSONDecodeError, ValueError):
        results["status"] = "push_failed" if rc != 0 else "unknown"

    # 6. Log housekeeping (best-effort, don't fail auto on this)
    print("[auto] Running --log-housekeeping (best-effort)...", flush=True)
    housekeeping.run_log_housekeeping()

    # 7b. (retired) The pending-outbox drain was removed with the outbox itself (Decision 84 I-4):
    # file_rec/file_decision now fail loudly at the call site instead of queueing.

    # 8. Refresh the local read-cache from the DuckLake reader
    try:
        from scripts.ops_data_portal import sync as _portal_sync  # noqa: PLC0415

        _portal_sync()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Ops sync skipped (non-critical): {exc}", file=sys.stderr)

    print(json.dumps(results, indent=2))
    return 0 if results.get("status") == "merged" else rc


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-session automation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true", help="Run validate.py")
    group.add_argument("--pre-commit-sanity", action="store_true", dest="pre_commit_sanity", help="Scope and branch check")
    group.add_argument("--commit", metavar="MESSAGE", help="Commit with message")
    group.add_argument("--push", action="store_true", help="Push, create PR, poll CI, merge")
    group.add_argument("--metrics", action="store_true", help="Run session metrics + plan audit")
    group.add_argument("--close", action="store_true", help="Intent verification + SESSION_LOG entry + pre-commit sanity")
    group.add_argument(
        "--log-housekeeping",
        action="store_true",
        dest="log_housekeeping",
        help="Commit uncommitted JSONL logs",
    )
    group.add_argument(
        "--close-session",
        action="store_true",
        dest="close_session",
        help="Finalise the active telemetry session opened by --open-session",
    )
    group.add_argument(
        "--auto",
        metavar="MESSAGE",
        help="Full session close: validate->close->metrics->commit->push->log-housekeeping",
    )
    parser.add_argument(
        "--steps-total",
        type=int,
        default=0,
        metavar="N",
        help="Total Ordered Execution Steps (forwarded to session_metrics.py).",
    )
    parser.add_argument(
        "--steps-friction",
        type=int,
        default=0,
        metavar="M",
        help="Steps with retro-lite friction (forwarded to session_metrics.py).",
    )
    parser.add_argument(
        "--outcome",
        default="success",
        help="Session outcome for --close-session (success|failure|cancelled)",
    )
    parser.add_argument(
        "--files-changed",
        type=int,
        default=0,
        dest="files_changed",
        help="Files changed (used with --close-session)",
    )

    args = parser.parse_args()

    if args.validate:
        return run_validate()
    if args.pre_commit_sanity:
        return run_pre_commit_sanity()
    if args.commit:
        return run_commit(args.commit)
    if args.push:
        return remote.run_push()
    if args.metrics:
        return housekeeping.run_metrics(args.steps_total, args.steps_friction)
    if args.close:
        return run_close()
    if args.log_housekeeping:
        return housekeeping.run_log_housekeeping()
    if args.close_session:
        housekeeping.close_telemetry_session(outcome=args.outcome, files_changed=args.files_changed)
        print(f"[close-session] outcome={args.outcome}")
        return 0
    if args.auto:
        return run_auto(args.auto, args.steps_total, args.steps_friction)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
