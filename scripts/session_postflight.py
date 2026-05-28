#!/usr/bin/env python3
# complexity-waiver: decision-43
"""Post-session deterministic automation: validate, pre-commit-sanity, commit, push, merge.

Replaces pre-commit-sanity.agent.md and session_close.prompt.md automation.

Modes:
    --validate           Run scripts/validate.py and return exit code
    --pre-commit-sanity  Check branch, scope, orphaned TODOs; output JSON
    --commit "message"   Run git add + commit with pre-commit retry (max 3)
    --push               Push, create PR, poll CI, auto-merge; output JSON
    --metrics            Run session_metrics.py + plan_audit.py; return combined output
    --close              Intent verification + SESSION_LOG entry + pre-commit sanity; output JSON
    --log-housekeeping   Commit and push uncommitted JSONL log files
    --close-session      Finalise the active telemetry session opened by --open-session
    --auto "message"     Full session close in one command: validate -> close -> metrics -> commit -> push -> log-housekeeping

Usage:
    python scripts/session_postflight.py --validate
    python scripts/session_postflight.py --pre-commit-sanity
    python scripts/session_postflight.py --commit "feat: implement something"
    python scripts/session_postflight.py --push
    python scripts/session_postflight.py --metrics
    python scripts/session_postflight.py --close
    python scripts/session_postflight.py --log-housekeeping
    python scripts/session_postflight.py --close-session --outcome success
    python scripts/session_postflight.py --auto "feat: implement something" --steps-total 10 --steps-friction 2
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
_SSO_PROFILE = "agent_platform"
MAX_COMMIT_RETRIES = 3
CI_POLL_INTERVAL_SECONDS = 30
CI_POLL_TIMEOUT_SECONDS = 600  # 10 minutes (CI takes ~4min; allow for startup + buffer)
DEFAULT_MAX_AGE_DAYS = 90
LOGS_DIR = ROOT / "logs"
ARCHIVE_DIR = LOGS_DIR / "archive"
TELEMETRY_ACTIVE_SESSION_FILE = ROOT / "logs" / ".telemetry-active-session.json"
_PRUNE_SKIP_NAMES = frozenset(
    {
        "transcripts",
        "debug",
        "archive",
    }
)

logger = logging.getLogger(__name__)

# Import find_plan_file from the canonical module
sys.path.insert(0, str(ROOT))
from scripts.execution_state import clear_checkpoint  # noqa: E402
from scripts.find_plan import find_plan_file  # noqa: E402


def _run(cmd: list[str], cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd or ROOT,
    )


def _current_branch() -> str:
    result = _run(["git", "branch", "--show-current"])
    return result.stdout.strip() if result.returncode == 0 else "unknown"


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
    result = _run(["git", "diff", "--name-only", "origin/main"])
    if result.returncode == 0 and result.stdout.strip():
        return [f for f in result.stdout.strip().splitlines() if f]
    result = _run(["git", "diff", "--name-only", "HEAD"])
    return [f for f in result.stdout.strip().splitlines() if f] if result.returncode == 0 else []


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _paths_match(a: str, b: str) -> bool:
    na, nb = _normalize_path(a), _normalize_path(b)
    return na == nb or na.endswith(f"/{nb}") or nb.endswith(f"/{na}")


def run_validate() -> int:
    """Run the full presubmit gate (no flags) to match remote CI exactly and return its exit code."""
    result = _run([PYTHON, "-m", "scripts.validate"])
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def run_pre_commit_sanity() -> int:
    """Check branch, scope drift, orphaned TODOs. Output JSON."""
    branch = _current_branch()

    if branch == "main":
        output = {"status": "FAIL", "branch": branch, "reason": "On main branch - cannot commit"}
        print(json.dumps(output, indent=2))
        return 1

    plan_file = find_plan_file()
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
    diff_result = _run(["git", "diff", "origin/main"])
    if diff_result.returncode != 0:
        diff_result = _run(["git", "diff", "HEAD"])
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
    for attempt in range(1, MAX_COMMIT_RETRIES + 1):
        add_result = _run(["git", "add", "."])
        if add_result.returncode != 0:
            print(f"git add failed: {add_result.stderr}", file=sys.stderr)
            return 1

        commit_result = _run(["git", "commit", "-m", message])
        if commit_result.returncode == 0:
            print(f"Committed on attempt {attempt}: {message}")
            print(commit_result.stdout)
            return 0

        # Pre-commit may have modified files -- check if that's the case
        stdout_lower = commit_result.stdout.lower()
        if "hook" in stdout_lower or "pre-commit" in stdout_lower or attempt < MAX_COMMIT_RETRIES:
            print(f"Commit attempt {attempt} failed (pre-commit may have modified files). Retrying...")
            print(commit_result.stdout)
            continue

        # Non-retryable failure
        print(f"Commit failed: {commit_result.stdout}", file=sys.stderr)
        print(commit_result.stderr, file=sys.stderr)
        return 1

    print(f"Commit failed after {MAX_COMMIT_RETRIES} attempts.", file=sys.stderr)
    return 1


def run_push() -> int:
    """Push branch, create PR, poll CI, auto-merge on green."""
    branch = _current_branch()

    # Push (set upstream if needed)
    push_result = _run(["git", "push", "--set-upstream", "origin", branch])
    if push_result.returncode != 0:
        output = {"status": "push_failed", "error": push_result.stderr.strip()}
        print(json.dumps(output, indent=2))
        return 1

    # Get PR intent from plan file
    pr_title = branch
    pr_body = f"Automated PR for branch `{branch}`."
    plan_file = find_plan_file()
    if plan_file and plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
        intent_match = re.search(r"## Intent\s*\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if intent_match:
            intent = intent_match.group(1).strip()
            slug = branch[len("agent/") :] if branch.startswith("agent/") else branch
            pr_title = f"feat: {slug}"
            pr_body = intent[:300]

    # Create PR
    pr_result = _run(["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "main"])
    if pr_result.returncode != 0:
        # PR may already exist
        if "already exists" not in pr_result.stderr.lower():
            output = {"status": "pr_failed", "error": pr_result.stderr.strip()}
            print(json.dumps(output, indent=2))
            return 1

    # Get PR URL
    pr_view = _run(["gh", "pr", "view", "--json", "url,number"])
    pr_url = ""
    pr_number = ""
    if pr_view.returncode == 0:
        try:
            pr_data = json.loads(pr_view.stdout)
            pr_url = pr_data.get("url", "")
            pr_number = str(pr_data.get("number", ""))
        except (json.JSONDecodeError, KeyError):
            pass

    # Poll CI — wait for ALL required PR checks to complete before merging.
    # Uses gh pr view --json statusCheckRollup: gives per-check status (COMPLETED/IN_PROGRESS)
    # and conclusion (SUCCESS/FAILURE/NEUTRAL/etc.) — works reliably on this repo's gh version.
    # This prevents merging when only the fastest check (e.g. Pre-commit, 47s) passes while
    # slower checks (e.g. CI validate-python, ~4min) are still running.
    deadline = time.time() + CI_POLL_TIMEOUT_SECONDS
    run_id = ""
    _OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
    while time.time() < deadline:
        sr_result = _run(["gh", "pr", "view", pr_number, "--json", "statusCheckRollup"])
        if sr_result.returncode == 0 and sr_result.stdout.strip():
            try:
                sr_data = json.loads(sr_result.stdout)
                checks = sr_data.get("statusCheckRollup", [])
                if checks:
                    # Best-effort run ID for the failure report
                    runs_result = _run(["gh", "run", "list", "--branch", branch, "--json", "databaseId", "--limit", "5"])
                    if runs_result.returncode == 0 and runs_result.stdout.strip():
                        runs = json.loads(runs_result.stdout)
                        if runs:
                            run_id = str(runs[0].get("databaseId", ""))

                    pending = [c for c in checks if c.get("status", "") != "COMPLETED"]
                    failures = [
                        c for c in checks if c.get("status") == "COMPLETED" and c.get("conclusion", "") not in _OK_CONCLUSIONS
                    ]

                    if pending:
                        pass  # Some checks still running — keep polling
                    elif failures:
                        failed_names = [c.get("workflowName", c.get("name", "?")) for c in failures]
                        clear_checkpoint()
                        output = {
                            "status": "ci_failed",
                            "run_id": run_id,
                            "error_summary": f"Failed checks: {', '.join(failed_names)}",
                            "pr_url": pr_url,
                        }
                        print(json.dumps(output, indent=2))
                        return 1
                    else:
                        # All checks completed with passing conclusions — safe to merge
                        merge_result = _run(["gh", "pr", "merge", pr_number, "--squash", "--auto", "--delete-branch"])
                        clear_checkpoint()
                        if merge_result.returncode == 0:
                            output = {"status": "merged", "pr_url": pr_url, "run_id": run_id}
                        else:
                            output = {"status": "merge_failed", "pr_url": pr_url, "error": merge_result.stderr.strip()}
                        print(json.dumps(output, indent=2))
                        return 0 if merge_result.returncode == 0 else 1
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        time.sleep(CI_POLL_INTERVAL_SECONDS)

    # Timeout — clear checkpoint so the next session isn't blocked
    clear_checkpoint()
    output = {
        "status": "ci_timeout",
        "run_id": run_id,
        "pr_url": pr_url,
        "error_summary": f"CI did not complete within {CI_POLL_TIMEOUT_SECONDS}s",
    }
    print(json.dumps(output, indent=2))
    return 1


def close_telemetry_session(
    outcome: str,
    files_changed: int = 0,
    lines_added: int = 0,
    lines_removed: int = 0,
) -> None:
    """Finalise the active telemetry session opened by ``--open-session``.

    Reads ``logs/.telemetry-active-session.json`` to retrieve the session_id.
    Calls ``scripts.executor.telemetry.close_session()`` to emit the record,
    then removes the state file.  If the state file is missing a warning is
    logged and the function returns without error so session close is never
    blocked.
    """
    if not TELEMETRY_ACTIVE_SESSION_FILE.exists():
        print(
            f"WARNING: close_telemetry_session: no active session file found ({TELEMETRY_ACTIVE_SESSION_FILE}). Skipping.",
            file=sys.stderr,
        )
        return

    try:
        state = json.loads(TELEMETRY_ACTIVE_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: could not read state file: {exc}",
            file=sys.stderr,
        )
        return

    try:
        from scripts.executor.telemetry import close_session, get_context  # noqa: PLC0415

        ctx = get_context()
        # Restore session_id so close_session emits with the correct ID
        ctx.session_id = state.get("session_id")
        ctx.workflow = state.get("workflow", "manual")
        ctx.branch = state.get("branch", "")
        close_session(
            outcome=outcome,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: telemetry.close_session failed: {exc}",
            file=sys.stderr,
        )

    try:
        TELEMETRY_ACTIVE_SESSION_FILE.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: could not remove state file: {exc}",
            file=sys.stderr,
        )


def _load_max_age_days() -> int:
    """Read telemetry.max_age_days from config/config.yaml.

    Falls back to DEFAULT_MAX_AGE_DAYS when the key is missing or
    the file cannot be parsed.
    """
    config_path = ROOT / "config" / "config.yaml"
    if not config_path.exists():
        return DEFAULT_MAX_AGE_DAYS
    try:
        import yaml  # lazy -- optional dep

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            telemetry = data.get("telemetry")
            if isinstance(telemetry, dict):
                val = telemetry.get("max_age_days")
                if isinstance(val, int) and val > 0:
                    return val
    except Exception:  # noqa: BLE001
        logger.debug("Could not read config.yaml; using default")
    return DEFAULT_MAX_AGE_DAYS


def prune_telemetry_logs(
    max_age_days: int | None = None,
) -> dict[str, list[str]]:
    """Rotate old JSONL entries from logs/ into logs/archive/.

    Each JSONL file in ``logs/`` that is not in ``_PRUNE_SKIP_NAMES``
    is scanned line-by-line. Lines whose ``"date"`` or ``"timestamp"``
    field is older than *max_age_days* are moved to
    ``logs/archive/{stem}-{today}.jsonl``.

    Returns a dict ``{"pruned": [...], "skipped": [...]}``.
    """
    if max_age_days is None:
        max_age_days = _load_max_age_days()

    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=max_age_days)
    cutoff_str = cutoff.isoformat()

    result: dict[str, list[str]] = {
        "pruned": [],
        "skipped": [],
    }

    if not LOGS_DIR.is_dir():
        return result

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for jsonl_file in sorted(LOGS_DIR.glob("*.jsonl")):
        if jsonl_file.name in _PRUNE_SKIP_NAMES:
            result["skipped"].append(jsonl_file.name)
            continue

        try:
            lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            result["skipped"].append(jsonl_file.name)
            continue

        keep: list[str] = []
        archive: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                keep.append(line)
                continue
            ts = entry.get("date") or entry.get("timestamp", "")
            date_part = str(ts)[:10]
            if len(date_part) == 10 and date_part < cutoff_str:
                archive.append(line)
            else:
                keep.append(line)

        if not archive:
            result["skipped"].append(jsonl_file.name)
            continue

        archive_name = f"{jsonl_file.stem}-{today.isoformat()}.jsonl"
        archive_path = ARCHIVE_DIR / archive_name
        with open(archive_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(archive) + "\n")

        jsonl_file.write_text(
            "\n".join(keep) + ("\n" if keep else ""),
            encoding="utf-8",
        )
        result["pruned"].append(jsonl_file.name)
        logger.info(
            "Pruned %d entries from %s -> %s",
            len(archive),
            jsonl_file.name,
            archive_name,
        )

    return result


def run_metrics(steps_total: int = 0, steps_friction: int = 0) -> int:
    """Run session_metrics.py, plan_audit.py, and telemetry pruning."""
    metrics_cmd = [PYTHON, "scripts/session_metrics.py"]
    if steps_total or steps_friction:
        metrics_cmd += ["--steps-total", str(steps_total), "--steps-friction", str(steps_friction)]
    metrics_result = _run(metrics_cmd)
    audit_result = _run([PYTHON, "scripts/plan_audit.py"])

    prune_result = prune_telemetry_logs()

    combined = {
        "metrics": metrics_result.stdout.strip(),
        "plan_audit": audit_result.stdout.strip(),
        "metrics_exit_code": metrics_result.returncode,
        "audit_exit_code": audit_result.returncode,
        "telemetry_pruning": prune_result,
    }
    print(json.dumps(combined, indent=2))
    return 0


def run_close() -> int:
    """Intent verification, SESSION_LOG entry, and pre-commit sanity in one shot.

    Returns JSON with keys:
      intent_achieved  – True/False or None (no plan)
      session_log_entry – Markdown string ready to prepend to SESSION_LOG.md
      sanity_status     – "PASS" | "WARN" | "FAIL"
      details           – dict with raw sub-results
    """
    # ── 1. Intent verification ────────────────────────────────────────────────
    plan_file = find_plan_file()
    intent_text: str = ""
    intent_achieved: bool | None = None

    if plan_file and plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
        intent_match = re.search(r"## Intent\s*\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if intent_match:
            intent_text = intent_match.group(1).strip()

    diff_stat = _run(["git", "diff", "--stat", "origin/main"])
    diff_summary = diff_stat.stdout.strip() if diff_stat.returncode == 0 else "(git diff unavailable)"

    if intent_text:
        # Simple heuristic: if there are changed files, mark intent as achieved
        has_changes = bool(diff_summary and "changed" in diff_summary)
        intent_achieved = has_changes

    # ── 2. SESSION_LOG entry template ─────────────────────────────────────────
    today = _dt.date.today().isoformat()
    branch = _current_branch()
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
    sanity_result = _run([PYTHON, "scripts/session_postflight.py", "--pre-commit-sanity"])
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
        run_metrics(steps_total, steps_friction)
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
        rc = run_push()
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
    run_log_housekeeping()

    # 7b. Drain pending outbox recs (best-effort, before compaction + sync)
    try:
        from scripts.sync_ops import check_sso as _check_sso  # noqa: PLC0415

        if not _check_sso(_SSO_PROFILE):
            subprocess.run(["aws", "sso", "login", "--profile", _SSO_PROFILE], check=False, timeout=300)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: SSO re-check before drain skipped: {exc}", file=sys.stderr)

    try:
        from scripts.ops_data_portal import drain_pending  # noqa: PLC0415

        drain_result = drain_pending(profile=_SSO_PROFILE)
        if drain_result.get("drained", 0) > 0:
            print(f"[auto] Drained {drain_result['drained']} pending rec(s)", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: drain_pending skipped: {exc}", file=sys.stderr)

    try:
        from scripts.ops_data_portal import drain_pending_decisions  # noqa: PLC0415

        dec_drain = drain_pending_decisions(profile=_SSO_PROFILE)
        if dec_drain.get("drained", 0) > 0:
            print(f"[auto] Drained {dec_drain['drained']} pending decision(s)", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: drain_pending_decisions skipped: {exc}", file=sys.stderr)

    # 8. Sync ops Iceberg tables (compact + refresh views + pull local cache)
    try:
        from scripts.ops_data_portal import sync as _portal_sync  # noqa: PLC0415

        _portal_sync()
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Ops sync skipped (non-critical): {exc}", file=sys.stderr)

    print(json.dumps(results, indent=2))
    return 0 if results.get("status") == "merged" else rc


def _stage_document_derived_tables() -> None:
    """Postflight ETL bypass neutered in Phase 0+1 of ops-decisions-graduation arc."""
    logger.warning("ops_decisions postflight ETL bypass neutered per Phase 0+1 of ops-decisions-graduation arc")


def run_log_housekeeping() -> int:
    """Commit and push uncommitted JSONL log files."""
    logs_dir = ROOT / "logs"
    if not logs_dir.exists():
        print("No logs/ directory found.")
        return 0

    status_result = _run(["git", "status", "--porcelain", "logs/"])
    if not status_result.stdout.strip():
        print("No uncommitted log files found.")
        return 0

    uncommitted_logs = [
        line.split()[-1]
        for line in status_result.stdout.splitlines()
        if line.strip() and line.strip().split()[-1].endswith(".jsonl")
    ]

    if not uncommitted_logs:
        print("No uncommitted JSONL files in logs/.")
        return 0

    add_result = _run(["git", "add"] + uncommitted_logs)
    if add_result.returncode != 0:
        print(f"git add failed: {add_result.stderr}", file=sys.stderr)
        return 1

    commit_result = _run(["git", "commit", "-m", "chore: session log updates"])
    if commit_result.returncode != 0:
        print(f"Commit failed: {commit_result.stdout}", file=sys.stderr)
        return 1

    push_result = _run(["git", "push"])
    if push_result.returncode != 0:
        print(f"Push failed: {push_result.stderr}", file=sys.stderr)
        return 1

    print(f"Committed and pushed {len(uncommitted_logs)} log file(s).")
    return 0


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
        return run_push()
    if args.metrics:
        return run_metrics(args.steps_total, args.steps_friction)
    if args.close:
        return run_close()
    if args.log_housekeeping:
        return run_log_housekeeping()
    if args.close_session:
        close_telemetry_session(outcome=args.outcome, files_changed=args.files_changed)
        print(f"[close-session] outcome={args.outcome}")
        return 0
    if args.auto:
        return run_auto(args.auto, args.steps_total, args.steps_friction)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
