# complexity-waiver: decision-43
#!/usr/bin/env python3
# complexity-waiver: decision-43
"""Pre-session environment and context check.

Outputs JSON to logs/.preflight-report.json for use by plan.prompt.md.
Exits 1 on critical failure (wrong venv), 0 otherwise.

Usage:
    python scripts/session_preflight.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import platform_roadmap
from scripts import product_roadmap as product_roadmap_module
from scripts.aws_profile import resolve_aws_profile
from scripts.s3_log_store import get_backend, read_jsonl
from scripts.sync_ops import _rebuild_local_cache as _sync_ops_pull
from src.common.iceberg_reader import DuckDBIcebergReader as _DuckDBIcebergReader  # noqa: F401  (kept for back-compat refs)
from src.common.iceberg_reader import make_reader as _make_reader

ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT_REPORT = ROOT / "logs" / ".preflight-report.json"
TERRAFORM_DIR = ROOT / "terraform"
SESSION_LOG_FILE = ROOT / "docs" / "SESSION_LOG.md"
RECOMMENDATIONS_FILE = ROOT / "logs" / ".recommendations-log.jsonl"
ROADMAP_FILE = ROOT / "docs" / "ROADMAP-PRODUCT.md"
ROADMAP_PLATFORM_PATH = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
ROADMAP_PRODUCT_PATH = ROOT / "docs" / "ROADMAP-PRODUCT.yaml"
DECISIONS_FILE = ROOT / "docs" / "DECISIONS.md"
STRATEGIC_REVIEW_LOOKBACK_DAYS = 30

PRIORITY_QUEUE_FILE = ROOT / "logs" / "priority-queue" / ".priority-queue.jsonl"

TELEMETRY_ACTIVE_SESSION_FILE = ROOT / "logs" / ".telemetry-active-session.json"

_ATHENA_DATABASE = "agent_platform"
_ATHENA_WORKGROUP = "agent-platform-production"
_ATHENA_OUTPUT_LOCATION = "s3://agent-platform-data-lake/athena-results/"
_ATHENA_POLL_TIMEOUT_SECONDS = 10
_NON_AUTOMATABLE_SOFTCAP = 250


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
            if parent == (ROOT / ".venv").resolve():
                return True
            break
    # Fallback: accept if ROOT has its own venv. This is name-independent -- the on-disk
    # directory name may stay "agent-platform" (or anything) after a GitHub rename, so a
    # match against the repo/directory name is unreliable.
    return (ROOT / ".venv" / "pyvenv.cfg").exists()


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
        cwd=ROOT,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    uncommitted = bool(status_result.stdout.strip()) if status_result.returncode == 0 else False

    stash_result = subprocess.run(
        ["git", "stash", "list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
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
            cwd=ROOT,
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
        cwd=ROOT,
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
            cwd=ROOT,
        )
        if merge_base_result.returncode == 0:
            merge_base = merge_base_result.stdout.strip()
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", f"{merge_base}..origin/main"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
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


def check_terraform_pending() -> bool | None:
    """Return True if terraform has pending changes, False if clean, None if unavailable.

    Runs ``terraform -chdir=terraform plan -detailed-exitcode`` and interprets:
    - exit code 0: no changes pending
    - exit code 2: changes pending
    - exit code 1 or FileNotFoundError: terraform not available or plan error
    """
    try:
        result = subprocess.run(
            ["terraform", "-chdir=terraform", "plan", "-detailed-exitcode", "-no-color"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=ROOT,
        )
        if result.returncode == 0:
            return False
        if result.returncode == 2:
            return True
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def check_credentials() -> str:
    """Non-blocking credential check for the static-key assume-role chain.

    Runs `aws sts get-caller-identity` with the resolved profile (or the boto3
    default chain on Lambda/CI when resolve_aws_profile returns None). Returns
    "ok" on a clean exit, else "unavailable". There is no "expired" state: the
    static-key chain has no interactive login token -- the PlatformDev/PlatformAdmin
    STS session auto-refreshes from the long-lived agent_static key.
    """
    profile = resolve_aws_profile()
    cmd = ["aws", "sts", "get-caller-identity"]
    if profile:
        cmd += ["--profile", profile]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            cwd=ROOT,
        )
        return "ok" if result.returncode == 0 else "unavailable"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unavailable"


def _handle_credentials_startup(creds_status: str) -> str:
    """Report credential health at preflight startup -- non-fatal (Decision 60).

    The static-key model has no interactive login step: the agent_static IAM key is a
    long-lived secret and the PlatformDev/PlatformAdmin STS sessions auto-refresh
    from it. When credentials are unavailable we cannot "log in" to recover, so we
    emit loud, actionable guidance and CONTINUE in degraded mode rather than exiting
    (Decision 60: skip with actionable guidance, never silently weaken a gate).
    Returns *creds_status* unchanged.
    """
    if creds_status != "ok":
        profile = resolve_aws_profile() or "<default-chain>"
        print(
            "[WARN] AWS credentials unavailable (static-key assume-role chain did not resolve).\n"
            f"       Verify the chain: aws sts get-caller-identity --profile {profile}\n"
            "       There is no interactive login to recover; if the agent_static\n"
            "       key was rotated, refresh ~/.aws/credentials. Continuing in DEGRADED mode:\n"
            "       Athena-backed reads fall back to the local cache or empty results.",
            file=sys.stderr,
        )
    return creds_status


def parse_last_session() -> str:
    """Return the most recent session header from SESSION_LOG.md, or empty string."""
    if not SESSION_LOG_FILE.exists():
        return ""
    content = SESSION_LOG_FILE.read_text(encoding="utf-8")
    matches = re.findall(r"## \[\d{4}-\d{2}-\d{2}\][^\n]*", content)
    return matches[-1] if matches else ""


def _run_athena_query(sql: str) -> list[dict] | None:
    """Execute *sql* against the Athena ops views and return rows as dicts.

    Returns ``None`` on any failure (timeout, unavailable credentials, missing
    CLI) so callers can fall back to local file reads.  Each row is a dict keyed
    by column name with string values (Athena ``get-query-results`` returns
    everything as VarChar).
    """
    profile = resolve_aws_profile()
    profile_args = ["--profile", profile] if profile else []
    cmd_start = [
        "aws",
        "athena",
        "start-query-execution",
        "--query-string",
        sql,
        "--work-group",
        _ATHENA_WORKGROUP,
        "--query-execution-context",
        f"Database={_ATHENA_DATABASE}",
        "--result-configuration",
        f"OutputLocation={_ATHENA_OUTPUT_LOCATION}",
        *profile_args,
        "--output",
        "text",
        "--query",
        "QueryExecutionId",
    ]
    try:
        result = subprocess.run(
            cmd_start,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            return None
        execution_id = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return None

    # Poll for completion (up to ~30 s)
    for _ in range(15):
        time.sleep(2)
        cmd_status = [
            "aws",
            "athena",
            "get-query-execution",
            "--query-execution-id",
            execution_id,
            *profile_args,
            "--output",
            "text",
            "--query",
            "QueryExecution.Status.State",
        ]
        try:
            sr = subprocess.run(
                cmd_status,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            state = sr.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            continue
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            return None
    else:
        return None

    # Fetch results as JSON
    cmd_results = [
        "aws",
        "athena",
        "get-query-results",
        "--query-execution-id",
        execution_id,
        *profile_args,
        "--output",
        "json",
    ]
    try:
        rr = subprocess.run(
            cmd_results,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if rr.returncode != 0:
            return None
        payload = json.loads(rr.stdout)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return None

    rows_raw = payload.get("ResultSet", {}).get("Rows", [])
    if len(rows_raw) < 2:
        return []

    # First row is the header
    headers = [col.get("VarCharValue", "") for col in rows_raw[0].get("Data", [])]
    results: list[dict] = []
    for row in rows_raw[1:]:
        values = [col.get("VarCharValue", "") for col in row.get("Data", [])]
        results.append(dict(zip(headers, values)))
    return results


def _count_recommendations_athena() -> tuple[int, int, int, list[dict]] | None:
    """Return open recommendation counts from the warehouse.

    Tries DuckDBIcebergReader first (with predicate + projection pushdown),
    falls back to the Athena CLI on reader failure.

    Returns ``None`` if both paths fail, allowing the caller to fall back to
    the local JSONL file (graceful degradation, T2.5 exit criterion).
    """
    # -- DuckDB reader path --
    try:
        reader = _make_reader()
        rows = reader.current_state(
            "ops_recommendations",
            row_filter="status = 'open'",
            selected_fields=("id", "title", "context", "created_timestamp", "automatable"),
        )
        if rows is not None:
            return _tally_rec_counts(rows, source="reader")
    except Exception as exc:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415

        _log.getLogger(__name__).warning("session_preflight._count_recommendations_athena: reader failed: %s", exc)

    # -- Athena fallback --
    sql = "SELECT id, title, context, created_timestamp, automatable FROM ops_recommendations_current WHERE status = 'open'"
    rows_raw = _run_athena_query(sql)
    if rows_raw is None:
        return None
    return _tally_rec_counts(rows_raw, source="athena")


def _tally_rec_counts(
    rows: list[dict],
    source: str = "reader",
) -> tuple[int, int, int, list[dict]]:
    """Compute (open_count, aging_count, non_auto_count, non_auto_details) from a row list."""
    now = datetime.now(timezone.utc)
    open_count = len(rows)
    aging_count = 0
    non_auto_count = 0
    non_auto_details: list[dict] = []

    for entry in rows:
        date_str = entry.get("created_timestamp", "")
        if date_str:
            try:
                if isinstance(date_str, str):
                    entry_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                else:
                    import datetime as _dt  # noqa: PLC0415

                    if hasattr(date_str, "timestamp"):
                        entry_date = _dt.datetime.fromtimestamp(date_str.timestamp(), tz=timezone.utc)
                    else:
                        entry_date = now
                if (now - entry_date).days > 30:
                    aging_count += 1
            except (ValueError, AttributeError, TypeError):
                pass
        # Athena returns booleans as strings "true"/"false"; reader returns Python bool or string
        raw_auto = entry.get("automatable", True)
        if isinstance(raw_auto, bool):
            automatable = raw_auto
        else:
            automatable = str(raw_auto).lower() != "false"
        if not automatable:
            non_auto_count += 1
            if len(non_auto_details) < 10:
                context = entry.get("context", "")
                non_auto_details.append(
                    {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", ""),
                        "context_excerpt": (context[:200] if isinstance(context, str) else ""),
                    }
                )

    return open_count, aging_count, non_auto_count, non_auto_details


def count_recommendations() -> tuple[int, int, int, list[dict]]:
    """Count open, aging (>30 days), and non-automatable recommendations.

    Tries the ops_recommendations_current Athena view first when credentials are
    available.  Falls back to the local JSONL file if the query fails.
    """
    # Try Athena view first (authoritative source per Decision 50)
    athena_result = _count_recommendations_athena()
    if athena_result is not None:
        print("  (recommendations sourced from Athena ops_recommendations_current view)")
        return athena_result

    open_count = 0
    aging_count = 0
    non_auto_count = 0
    non_auto_details: list[dict] = []
    now = datetime.now(timezone.utc)
    try:
        if get_backend() == "s3":
            entries = read_jsonl(".recommendations-log.jsonl")
        elif not RECOMMENDATIONS_FILE.exists():
            return 0, 0, 0, []
        else:
            entries = []
            for line in RECOMMENDATIONS_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        for entry in entries:
            if entry.get("status", "").lower() != "open":
                continue
            open_count += 1
            date_str = entry.get("date", "")
            if date_str:
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if (now - entry_date).days > 30:
                        aging_count += 1
                except ValueError:
                    pass
            if not entry.get("automatable", True):
                non_auto_count += 1
                if len(non_auto_details) < 10:
                    context = entry.get("context", "")
                    non_auto_details.append(
                        {
                            "id": entry.get("id", ""),
                            "title": entry.get("title", ""),
                            "context_excerpt": context[:200] if context else "",
                        }
                    )
    except IOError:
        return 0, 0, 0, []

    return open_count, aging_count, non_auto_count, non_auto_details


def _shape_priority_queue_rows(rows: list[dict], max_items: int) -> list[dict]:
    """Normalise raw rows into the {rank, rec_id, rationale, north_star_impact} shape."""
    result = []
    for row in rows[:max_items]:
        try:
            rank = int(row.get("rank", 0))
        except (ValueError, TypeError):
            rank = 0
        result.append(
            {
                "rank": rank,
                "rec_id": row.get("rec_id", ""),
                "rationale": row.get("rationale", ""),
                "north_star_impact": row.get("north_star_impact", ""),
            }
        )
    return result


def _read_priority_queue_cache(max_items: int) -> list[dict]:
    """Read priority-queue rows from the local read-cache (degraded-mode fallback).

    Returns [] (with a loud warning) when the cache file is absent. There is no
    in-repo producer for PRIORITY_QUEUE_FILE today, so in practice this commonly
    degrades to empty rather than restoring rows -- acceptable under Decision 60.
    READ-ONLY: it never restages or writes the cache (warehouse-as-source-of-truth;
    no resurrection loop).
    """
    if not PRIORITY_QUEUE_FILE.exists():
        print(
            "[WARN] priority queue unavailable: credentials down and no local cache at "
            f"{PRIORITY_QUEUE_FILE}; returning empty (sync after creds restored).",
            file=sys.stderr,
        )
        return []
    mtime = datetime.fromtimestamp(PRIORITY_QUEUE_FILE.stat().st_mtime, tz=timezone.utc)
    print(
        f"[WARN] priority queue read from local cache (creds unavailable); may be stale as of "
        f"{mtime.isoformat()}; sync after creds restored.",
        file=sys.stderr,
    )
    rows: list[dict] = []
    for line in PRIORITY_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return _shape_priority_queue_rows(rows, max_items)


def read_priority_queue(max_items: int = 5, creds_status: str = "ok") -> list[dict]:
    """Read the priority queue from the warehouse (DuckDB reader, Athena fallback).

    Decision 70: priority queue uses the correlated-subquery current-state pattern
    (all entries from the latest curator run); DuckDBIcebergReader handles this
    internally.

    When *creds_status* is not "ok" credentials are unavailable: fall back to the
    local read-cache with a staleness warning (empty-with-warning when absent; never
    crash -- T2.5 graceful-degradation requirement).

    When credentials ARE "ok" but both reader and Athena return None, that is a
    genuine infrastructure fault -- hard-exit with code 1 rather than masking it
    (Decision 60: source of truth; never silently weaken a gate).

    Returns a list of dicts shaped as {rank, rec_id, rationale, north_star_impact}.
    Returns [] if the queue is empty.
    """
    if creds_status != "ok":
        return _read_priority_queue_cache(max_items)

    # -- DuckDB reader path (Decision 70: correlated subquery applied internally) --
    try:
        reader = _make_reader()
        reader_rows = reader.current_state("ops_priority_queue")
        if reader_rows is not None:
            shaped = _shape_priority_queue_rows(reader_rows, max_items)
            shaped.sort(key=lambda r: (r.get("rank") is None, r.get("rank", 0)))
            return shaped
    except Exception as exc:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415

        _log.getLogger(__name__).warning("session_preflight.read_priority_queue: reader failed: %s", exc)

    # -- Athena fallback --
    rows = _run_athena_query(
        "SELECT rec_id, rank, rationale, north_star_impact "
        f"FROM {_ATHENA_DATABASE}.ops_priority_queue_current "
        "ORDER BY CAST(rank AS INTEGER)"
    )
    if rows is None:
        print(
            "[ERROR] ops_priority_queue_current query failed -- infrastructure problem, not masking with fallback",
            file=sys.stderr,
        )
        sys.exit(1)

    return _shape_priority_queue_rows(rows, max_items)


def print_priority_queue(items: list[dict]) -> None:
    """Print the priority queue section to terminal."""
    print("\n--- Priority Queue (top 5) ---")
    if not items:
        print("  (empty)")
    else:
        for item in items:
            rank = item.get("rank", 0)
            rec_id = item.get("rec_id", "unknown")
            impact = item.get("north_star_impact", "")
            rationale = item.get("rationale", "")
            print(f"  #{rank} {rec_id}: [impact={impact}] -- {rationale}")
    print()


def _fetch_ci_rca_recs() -> list[dict]:
    """Return up to 5 open CI-RCA recs from the warehouse. Returns [] on any failure."""
    sql = (
        "SELECT id, title, priority, created_timestamp "
        "FROM {tbl} "
        "WHERE source = ? AND status IN (?, ?) "
        "ORDER BY created_timestamp DESC LIMIT 5"
    )
    try:
        reader = _make_reader()
        rows = reader.query("ops_recommendations", sql, params=("ci_rca", "open", "in_progress"))
        if rows is not None:
            return rows
    except Exception:  # noqa: BLE001
        pass

    # Athena fallback
    athena_sql = (
        "SELECT id, title, priority, created_timestamp "
        "FROM ops_recommendations_current "
        "WHERE source = 'ci_rca' AND status IN ('open', 'in_progress') "
        "ORDER BY created_timestamp DESC LIMIT 5"
    )
    rows_raw = _run_athena_query(athena_sql)
    if rows_raw is None:
        print("[WARNING] preflight: ci_rca query failed -- CI RCA Recs section may be incomplete", file=sys.stderr)
        return []
    return rows_raw


def _check_non_automatable_softcap(non_auto_count: int) -> bool:
    """Return True when non-automatable rec count exceeds the soft cap."""
    return non_auto_count > _NON_AUTOMATABLE_SOFTCAP


def _fetch_ci_rca_recs_since(ts: str) -> list[dict]:
    """Return ci_rca recs created after *ts*. Returns [] on any failure."""
    try:
        reader = _make_reader()
        rows = reader.query(
            "ops_recommendations",
            "SELECT id FROM {tbl} WHERE source = ? AND created_timestamp > ?",
            params=("ci_rca", ts),
        )
        if rows is not None:
            return rows
    except Exception:  # noqa: BLE001
        pass

    # Athena fallback
    sql = f"SELECT id FROM ops_recommendations_current WHERE source = 'ci_rca' AND created_timestamp > '{ts}'"
    rows_raw = _run_athena_query(sql)
    if rows_raw is None:
        return []
    return rows_raw


def _check_ci_rca_liveness(creds_status: str) -> dict | None:
    """Return alert dict when main CI has been red with no ci-rca rec for >30 min.

    Calls `gh run list` to determine the latest push-to-main ci.yml result.
    Returns None when credentials are unavailable, gh call fails, or conditions are not met.
    """
    if creds_status != "ok":
        return None
    try:
        result = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                "main",
                "--workflow",
                "ci.yml",
                "--event",
                "push",
                "--limit",
                "1",
                "--json",
                "conclusion,createdAt,url",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        runs = json.loads(result.stdout)
        if not runs:
            return None
        run = runs[0]
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, IndexError):
        return None

    if run.get("conclusion") != "failure":
        return None

    created_at = run.get("createdAt", "")
    if not created_at:
        return None

    try:
        run_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - run_ts).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None

    if elapsed_minutes <= 30:
        return None

    if _fetch_ci_rca_recs_since(created_at):
        return None

    return {"run_url": run.get("url", ""), "elapsed_minutes": round(elapsed_minutes, 1)}


def _check_forward_fix_recursion() -> dict | None:
    """Return alert dict when >=3 ci-rca recs targeting the same file appear in the last 24h.

    Returns None when no recursion is detected or the warehouse is unreachable.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        reader = _make_reader()
        rows = reader.query(
            "ops_recommendations",
            "SELECT file, COUNT(*) AS cnt FROM {tbl} "
            "WHERE source = ? AND created_timestamp > ? "
            "GROUP BY file HAVING COUNT(*) >= 3",
            params=("ci_rca", cutoff),
        )
        if rows is not None:
            if not rows:
                return None
            first = rows[0]
            try:
                count = int(first.get("cnt", 3))
            except (ValueError, TypeError):
                count = 3
            return {"file": first.get("file", ""), "count": count, "threshold": 3}
    except Exception:  # noqa: BLE001
        pass

    # Athena fallback
    athena_sql = (
        "SELECT file, COUNT(*) AS cnt "
        "FROM ops_recommendations_current "
        f"WHERE source = 'ci_rca' AND created_timestamp > '{cutoff}' "
        "GROUP BY file HAVING COUNT(*) >= 3"
    )
    rows_raw = _run_athena_query(athena_sql)
    if not rows_raw:
        return None
    first = rows_raw[0]
    try:
        count = int(first.get("cnt", 3))
    except (ValueError, TypeError):
        count = 3
    return {"file": first.get("file", ""), "count": count, "threshold": 3}


def _check_budget_bypass_alert() -> dict | None:
    """Return alert dict when >= 3 budget_bypass recs were filed in the last 7 days.

    Returns None when count < 3 or the warehouse is unreachable.
    """
    try:
        reader = _make_reader()
        rows = reader.query(
            "ops_recommendations",
            "SELECT id, context, created_timestamp FROM {tbl} WHERE source = ? "
            "AND created_timestamp > (current_timestamp - INTERVAL 7 DAY) "
            "ORDER BY created_timestamp DESC LIMIT 10",
            params=("budget_bypass",),
        )
        if rows is not None:
            if len(rows) < 3:
                return None
            return {"count": len(rows), "entries": rows}
    except Exception:  # noqa: BLE001
        pass

    # Athena fallback
    try:
        athena_sql = (
            "SELECT id, context, created_timestamp "
            "FROM ops_recommendations_current "
            "WHERE source = 'budget_bypass' "
            "AND created_timestamp > (current_timestamp - INTERVAL '7' DAY) "
            "ORDER BY created_timestamp DESC "
            "LIMIT 10"
        )
        rows_raw = _run_athena_query(athena_sql)
        if rows_raw is None:
            return None
        if len(rows_raw) < 3:
            return None
        return {"count": len(rows_raw), "entries": rows_raw}
    except Exception:  # noqa: BLE001
        import logging as _logging  # noqa: PLC0415

        _logging.getLogger(__name__).warning("_check_budget_bypass_alert: query failed; degrading to None")
        return None


def print_ci_rca_recs(recs: list[dict]) -> None:
    """Print the CI RCA Recs section to terminal."""
    print("\n--- CI RCA Recs (open) ---")
    if not recs:
        print("  (none)")
    else:
        print("  [HARD BLOCK] /plan cannot scope unrelated work while these recs are open.")
        for rec in recs:
            rec_id = rec.get("id", "unknown")
            title = rec.get("title", "")
            priority = rec.get("priority", "")
            created = rec.get("created_timestamp", "")
            print(f"  {rec_id} [{priority}] {created}: {title}")
    print()


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
        cwd=ROOT,
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
        cwd=ROOT,
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
        cwd=ROOT,
    )
    if add_result.returncode != 0:
        return {"status": "conflict", "files": log_files, "error": add_result.stderr.strip()}

    commit_result = subprocess.run(
        ["git", "commit", "-m", "chore: sync session logs [auto]"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if commit_result.returncode != 0:
        return {"status": "conflict", "files": log_files, "error": commit_result.stderr.strip()}

    push_result = subprocess.run(
        ["git", "push"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    if push_result.returncode != 0 or "conflict" in push_result.stderr.lower():
        return {
            "status": "conflict",
            "files": log_files,
            "error": push_result.stderr.strip(),
        }

    return {"status": "committed", "files": log_files}


def read_context_files() -> dict:
    """Read key context documents and return a summary dict for plan.prompt.md.

    Returns:
        Dict with keys: roadmap_phase, open_decisions_count, recent_sessions,
        strategic_review_due, recommendations_count.
    """
    # roadmap_phase: extract current phase header from ROADMAP.md
    roadmap_phase = "unknown"
    if ROADMAP_FILE.exists():
        content = ROADMAP_FILE.read_text(encoding="utf-8")
        # Look for "## Phase X.Y: ..." headers that are not completed/archived
        phase_matches = re.findall(r"^## (Phase [^\n]+)", content, re.MULTILINE)
        if phase_matches:
            roadmap_phase = phase_matches[0].strip()

    # open_decisions_count: count ## Decision headers not marked Decided/Resolved/Closed
    open_decisions_count = 0
    if DECISIONS_FILE.exists():
        content = DECISIONS_FILE.read_text(encoding="utf-8")
        decision_headers = re.findall(r"^## Decision \d+[^\n]*", content, re.MULTILINE)
        for header in decision_headers:
            if not re.search(r"\(Decided\)|\(Resolved\)|\(Closed\)|\(Done\)", header, re.IGNORECASE):
                open_decisions_count += 1

    # recent_sessions: last 5 session entries from SESSION_LOG.md
    recent_sessions: list[str] = []
    if SESSION_LOG_FILE.exists():
        content = SESSION_LOG_FILE.read_text(encoding="utf-8")
        # Match ## [YYYY-MM-DD] headers and capture the Done line
        session_blocks = re.findall(
            r"(## \[\d{4}-\d{2}-\d{2}\][^\n]*)(?:\n\*\*Done:\*\* ([^\n]+))?",
            content,
        )
        for header, done_line in session_blocks[-5:]:
            entry = header.strip()
            if done_line:
                entry += f" -- {done_line.strip()}"
            recent_sessions.append(entry)

    # strategic_review_due: check last 30 days of SESSION_LOG for "strategic review"
    strategic_review_due = True  # default: assume due until found
    if SESSION_LOG_FILE.exists():
        content = SESSION_LOG_FILE.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc)
        cutoff = now.replace(tzinfo=timezone.utc)
        date_matches = re.finditer(r"## \[(\d{4}-\d{2}-\d{2})\]", content)
        for match in date_matches:
            try:
                session_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (cutoff - session_date).days
                if age_days <= STRATEGIC_REVIEW_LOOKBACK_DAYS:
                    # Check if there's a strategic review mention near this entry
                    pos = match.start()
                    snippet = content[pos : pos + 500].lower()
                    if "strategic review" in snippet:
                        strategic_review_due = False
                        break
            except ValueError:
                continue

    # recommendations_count: try Athena view first, fall back to local JSONL
    recommendations_count = 0
    athena_rows = _run_athena_query("SELECT COUNT(*) AS cnt FROM ops_recommendations_current WHERE status = 'open'")
    if athena_rows is not None and athena_rows:
        try:
            recommendations_count = int(athena_rows[0].get("cnt", "0"))
        except (ValueError, IndexError):
            recommendations_count = 0
    elif RECOMMENDATIONS_FILE.exists():
        for line in RECOMMENDATIONS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            try:
                entry = json.loads(line)
                if entry.get("status", "").lower() == "open":
                    recommendations_count += 1
            except json.JSONDecodeError:
                pass

    return {
        "roadmap_phase": roadmap_phase,
        "open_decisions_count": open_decisions_count,
        "recent_sessions": recent_sessions,
        "strategic_review_due": strategic_review_due,
        "recommendations_count": recommendations_count,
    }


def sync_copilot_instructions() -> None:
    """Check that the two instructions files are not accidentally identical.

    copilot_instructions.md (underscore) — loaded by VS Code Copilot Chat.
      Full developer context: rules, workflow checklists, AWS details, all gotchas.

    copilot-instructions.md (hyphen) — loaded by the `gh copilot` CLI.
      Lean task-execution context: code style rules, File Router, coding gotchas.
      Does NOT contain pre-implementation checklists or branch-check workflows,
      because each CLI call is a single-shot self-contained task.

    These two files serve different purposes and must NOT be kept in sync.
    This function emits a warning if they are accidentally made identical again.
    """
    src = ROOT / ".github" / "copilot_instructions.md"
    dst = ROOT / ".github" / "copilot-instructions.md"
    if src.exists() and dst.exists():
        if src.read_bytes() == dst.read_bytes():
            print(
                "WARNING: .github/copilot_instructions.md and .github/copilot-instructions.md "
                "are identical. They serve different purposes (VS Code vs gh copilot CLI) and "
                "should have separate content. The CLI version should NOT contain "
                "pre-implementation checklists or branch-check workflows."
            )


def _athena_run_query(client: object, sql: str, *, poll_timeout: int = _ATHENA_POLL_TIMEOUT_SECONDS) -> list[list[str]]:
    """Execute a SQL query via Athena and return rows as lists of string values.

    Polls for completion up to *poll_timeout* seconds.  Returns an empty list
    on timeout; raises on execution error.  The first row is always the column
    header row and is included in the return value.
    """
    response = client.start_query_execution(  # type: ignore[union-attr]
        QueryString=sql,
        WorkGroup=_ATHENA_WORKGROUP,
        QueryExecutionContext={"Database": _ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": _ATHENA_OUTPUT_LOCATION},
    )
    execution_id = response["QueryExecutionId"]
    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline:
        status = client.get_query_execution(QueryExecutionId=execution_id)  # type: ignore[union-attr]
        state = status["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED",):
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {state}: {reason}")
        time.sleep(0.5)
    else:
        return []  # timeout -- treat as empty result

    results = client.get_query_results(QueryExecutionId=execution_id)  # type: ignore[union-attr]
    rows: list[list[str]] = []
    for row in results.get("ResultSet", {}).get("Rows", []):
        rows.append([datum.get("VarCharValue", "") for datum in row.get("Data", [])])
    return rows


def check_telemetry_health() -> dict:
    """Query Athena for telemetry session metrics and return health dict.

    Uses ``agent_platform.telemetry_sessions_current`` (7-day window) to
    compute session count, success rate, and latest session staleness.  Also
    queries ``telemetry_process_events`` for the top-5 recent friction patterns.

    Telemetry tables were NOT migrated to the personal account (public-migration,
    2026-05-28); these queries therefore fail with TABLE_NOT_FOUND and are caught
    below, degrading to a non-fatal warning rather than raising.

    Degrades gracefully when credentials are unavailable or Athena is unreachable --
    returns ``overall: "unknown"`` with a single ``athena-query`` check entry.

    Returns a dict compatible with ``print_telemetry_health()``.
    """
    checks: list[dict] = []
    friction_patterns: list[dict] = []
    has_warning = False
    has_critical = False

    try:
        import boto3  # noqa: PLC0415

        session = boto3.Session(profile_name=resolve_aws_profile())
        client = session.client("athena", region_name="eu-west-2")

        # -- Session count + success rate + latest session staleness --
        sessions_sql = (
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success_count, "
            "MAX(started_at) AS latest "
            f"FROM {_ATHENA_DATABASE}.telemetry_sessions_current "
            "WHERE trade_date >= CURRENT_DATE - INTERVAL '7' DAY"
        )
        try:
            rows = _athena_run_query(client, sessions_sql)
            if len(rows) >= 2:
                _header, data_row = rows[0], rows[1]
                total = int(data_row[0]) if data_row[0].isdigit() else 0
                success_count = int(data_row[1]) if data_row[1].isdigit() else 0
                latest_ts_str = data_row[2] if len(data_row) > 2 else ""

                checks.append({"check": "sessions-7d", "value": str(total), "severity": "ok"})
                if total > 0:
                    success_rate = success_count / total
                    rate_display = f"{success_rate:.0%}"
                    rate_severity = "ok"
                    if success_rate < 0.5:
                        rate_severity = "warning"
                        has_warning = True
                    checks.append({"check": "success-rate-7d", "value": rate_display, "severity": rate_severity})

                if latest_ts_str:
                    try:
                        latest_ts = datetime.fromisoformat(latest_ts_str.replace("Z", "+00:00"))
                        if latest_ts.tzinfo is None:
                            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                        now = datetime.now(timezone.utc)
                        staleness_h = (now - latest_ts).total_seconds() / 3600.0
                        stale_display = f"{staleness_h:.1f}h"
                        stale_severity = "ok"
                        if staleness_h >= 168:
                            stale_severity = "critical"
                            has_critical = True
                        elif staleness_h >= 72:
                            stale_severity = "warning"
                            has_warning = True
                        checks.append(
                            {
                                "check": "latest-session-staleness",
                                "value": stale_display,
                                "severity": stale_severity,
                            }
                        )
                    except (ValueError, TypeError):
                        pass
            else:
                checks.append({"check": "sessions-7d", "value": "0", "severity": "ok"})
        except Exception as exc:  # noqa: BLE001
            checks.append({"check": "sessions-query", "value": str(exc)[:60], "severity": "warning"})
            has_warning = True

        # -- Top-5 friction patterns from process events --
        friction_sql = (
            "SELECT category, description, COUNT(*) AS occurrences "
            f"FROM {_ATHENA_DATABASE}.telemetry_process_events "
            "WHERE trade_date >= CURRENT_DATE - INTERVAL '7' DAY "
            "GROUP BY category, description "
            "ORDER BY occurrences DESC LIMIT 5"
        )
        try:
            fp_rows = _athena_run_query(client, friction_sql)
            for row in fp_rows[1:]:  # skip header row
                if len(row) >= 3:
                    friction_patterns.append(
                        {"category": row[0], "description": row[1], "occurrences": int(row[2]) if row[2].isdigit() else 0}
                    )
        except Exception:  # noqa: BLE001
            pass  # friction patterns are informational; failure is non-critical

    except Exception:  # noqa: BLE001
        # credentials unavailable, boto3 missing, or other connectivity failure -- degrade gracefully
        checks.append({"check": "athena-query", "value": "unavailable", "severity": "unknown"})
        return {"overall": "unknown", "checks": checks, "friction_patterns": friction_patterns}

    overall = "ok"
    if has_critical:
        overall = "critical"
    elif has_warning:
        overall = "warning"

    return {"overall": overall, "checks": checks, "friction_patterns": friction_patterns}


def check_data_quality_coverage() -> dict:
    """Report data quality check coverage from config/agent/data_quality/ YAML files.

    This does NOT execute checks against Athena (that is slow and requires AWS).
    It reports: how many checks are defined, which tables are covered, and
    whether a recent run result exists in logs/debug/dq-latest.json.

    Returns a dict with:
        tables_covered: int
        checks_defined: int
        last_run: dict | None (verdict, passed, failed, timestamp from last run)
    """
    dq_dir = ROOT / "config" / "data_quality"
    last_run_file = ROOT / "logs" / "debug" / "dq-latest.json"

    tables_covered = 0
    checks_defined = 0

    try:
        from scripts.data_quality_runner import load_checks  # noqa: PLC0415

        for yf in sorted(dq_dir.glob("*.yaml")):
            checks, _ = load_checks(yf)
            if checks:
                tables_in_file = len({c.table for c in checks})
                tables_covered += tables_in_file
                checks_defined += len(checks)
    except Exception:  # noqa: BLE001
        pass

    last_run: dict | None = None
    if last_run_file.exists():
        try:
            data = json.loads(last_run_file.read_text(encoding="utf-8"))
            last_run = {
                "verdict": data.get("verdict", "unknown"),
                "passed": data.get("passed", 0),
                "failed": data.get("failed", 0),
                "warned": data.get("warned", 0),
                "timestamp": data.get("timestamp", ""),
            }
        except Exception:  # noqa: BLE001
            pass

    return {
        "tables_covered": tables_covered,
        "checks_defined": checks_defined,
        "last_run": last_run,
    }


def print_telemetry_health(health: dict) -> None:
    """Print a compact summary table of telemetry health checks."""
    severity_markers = {
        "ok": "  OK ",
        "warning": " WARN",
        "critical": " CRIT",
    }
    print("\n--- Telemetry Health ---")
    print(f"{'Check':<35} {'Value':<15} {'Status':<6}")
    print("-" * 58)
    for c in health["checks"]:
        marker = severity_markers.get(c["severity"], "  ?  ")
        print(f"{c['check']:<35} {c['value']:<15} {marker}")
    overall_marker = severity_markers.get(health["overall"], "  ?  ")
    print("-" * 58)
    print(f"{'Overall':<35} {'':<15} {overall_marker}")

    # Data quality coverage summary
    dq = check_data_quality_coverage()
    if dq["checks_defined"] > 0:
        print(f"\n  Data quality: {dq['checks_defined']} checks across {dq['tables_covered']} tables")
        if dq["last_run"]:
            lr = dq["last_run"]
            print(f"  Last run: {lr['verdict']} ({lr['passed']}P/{lr['failed']}F/{lr['warned']}W) at {lr['timestamp']}")
        else:
            print("  Last run: never (run: python -m scripts.data_quality_runner)")
    print()


def _get_latest_decision_ts() -> str | None:
    """Return the max last_updated_timestamp from ops_decisions_current, or None on any failure."""
    rows = _run_athena_query("SELECT max(last_updated_timestamp) AS ts FROM ops_decisions_current")
    if not rows:
        return None
    ts = rows[0].get("ts", "")
    return ts if ts else None


def main() -> int:
    session_start = datetime.now(timezone.utc).isoformat()

    sync_copilot_instructions()

    # Telemetry health runs early so it appears in output
    telemetry_health = check_telemetry_health()
    print_telemetry_health(telemetry_health)

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        os.environ.setdefault("S3_LOG_BUCKET", "agent-platform-data-lake")

    venv_ok = check_venv()
    if not venv_ok:
        print(f"CRITICAL: Wrong virtual environment. sys.executable={sys.executable}")
        print(f"Expected the venv at '{ROOT / '.venv'}'.")
        _print_activate_hint()

    # Run log sync before git_status so a successful sync clears the dirty tree
    log_sync_result = run_log_sync()

    branch, uncommitted, stash_entries = get_git_status()

    # If log sync committed and pushed, the working tree is now clean
    if log_sync_result.get("status") == "committed":
        uncommitted = False

    main_freshness = check_main_freshness()

    terraform_pending = check_terraform_pending()
    creds_status = _handle_credentials_startup(check_credentials())
    s3_log_bucket_set = bool(os.environ.get("S3_LOG_BUCKET", "").strip())

    # Pull ops_recommendations (and all ops tables) from Athena into local cache (best-effort)
    try:
        recommendation_sync = _sync_ops_pull()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"WARNING: sync_ops.pull failed: {exc}", file=sys.stderr)
        recommendation_sync = {}

    try:
        from scripts.ops_data_portal import drain_pending  # noqa: PLC0415

        _drain = drain_pending()
        if _drain.get("drained", 0) > 0:
            print(f"[preflight] Drained {_drain['drained']} pending rec(s)", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass

    # Outbox summary (always available, even without credentials)
    try:
        from scripts.sync_ops import outbox_summary  # noqa: PLC0415
        from scripts.sync_ops import sync as sync_ops_sync

        outbox = outbox_summary()
        if outbox:
            total = sum(outbox.values())
            print(f"Ops outbox: {total} pending entries ({outbox})", file=sys.stderr)
    except Exception:  # noqa: BLE001
        outbox = {}

    # Drain outbox + pull fresh data if credentials are available
    if creds_status == "ok":
        try:
            result = sync_ops_sync()
            drained = sum(result.get("drained", {}).values())
            pulled = sum(result.get("pulled", {}).values())
            if drained or pulled:
                print(
                    f"Ops sync: drained {drained} outbox entries, pulled {pulled} rows from Athena",
                    file=sys.stderr,
                )
        except Exception:  # noqa: BLE001
            pass  # sync is best-effort

    last_session = parse_last_session()
    open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = count_recommendations()
    ci_rca_recs = _fetch_ci_rca_recs()
    if ci_rca_recs:
        print_ci_rca_recs(ci_rca_recs)
    priority_queue = read_priority_queue(creds_status=creds_status)
    print_priority_queue(priority_queue)
    if not ci_rca_recs:
        print_ci_rca_recs(ci_rca_recs)
    context = read_context_files()
    platform_roadmap_state = platform_roadmap.compute_state_dict(
        ROADMAP_PLATFORM_PATH, latest_decision_ts=_get_latest_decision_ts()
    )
    product_roadmap_state = product_roadmap_module.compute_state_dict(
        ROADMAP_PRODUCT_PATH,
        platform_yaml_path=ROADMAP_PLATFORM_PATH,
        latest_decision_ts=_get_latest_decision_ts(),
    )

    report: dict = {
        "venv_ok": venv_ok,
        "branch": branch,
        "uncommitted_changes": uncommitted,
        "stash_entries": stash_entries,
        "main_freshness": main_freshness,
        "creds_status": creds_status,
        "s3_log_bucket_set": s3_log_bucket_set,
        "ops_outbox": outbox,
        "terraform_pending": terraform_pending,
        "last_session": last_session,
        "open_recommendations": open_recommendations,
        "aging_recommendations": aging_recommendations,
        "non_automatable_recommendations": non_automatable_count,
        "priority_queue": priority_queue,
        "priority_queue_source": "athena" if creds_status == "ok" else "cache",
        "ci_rca_recs": ci_rca_recs,
        "friction_patterns": telemetry_health.get("friction_patterns", []),
        "log_sync_result": log_sync_result,
        "recommendation_sync": recommendation_sync,
        "telemetry_health": telemetry_health,
        "data_quality": check_data_quality_coverage(),
        "context": context,
        "platform_roadmap": _slim_roadmap_state(platform_roadmap_state),
        "product_roadmap": _slim_roadmap_state(product_roadmap_state),
        "session_start": session_start,
    }

    report["non_automatable_softcap_breached"] = _check_non_automatable_softcap(non_automatable_count)
    report["ci_rca_liveness_alert"] = _check_ci_rca_liveness(creds_status)
    report["forward_fix_recursion_alert"] = _check_forward_fix_recursion()
    budget_bypass_alert = _check_budget_bypass_alert()
    report["budget_bypass_alert"] = budget_bypass_alert
    if budget_bypass_alert is not None:
        print(
            f"Budget bypass alert: {budget_bypass_alert['count']} --ignore-budget invocations in the last 7 days."
            " Repeated bypass indicates fast-tier drift -- consider a planning session to revisit the budget.",
            file=sys.stderr,
        )

    # Ensure logs/ directory exists
    PREFLIGHT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    PREFLIGHT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(_format_preflight_summary(report, PREFLIGHT_REPORT))

    return 0 if venv_ok else 1


def _slim_roadmap_state(state: dict) -> dict:
    """Keep only the actionable subsets the workflows actually consume.

    The full state from compute_state_dict() includes in_progress, blocked,
    active_tier/layer, and consumer maps -- ~8k tokens combined across both
    roadmaps. Workflows only branch on next_eligible and strategic_pending.
    Dropping the rest is recoverable: call platform_roadmap.compute_state_dict()
    or product_roadmap.compute_state_dict() directly if a session needs detail.
    """
    return {
        "next_eligible": state.get("next_eligible", []),
        "strategic_pending": state.get("strategic_pending", []),
    }


def _format_preflight_summary(report: dict, report_path: Path) -> str:
    """One-line summary for stdout. The full JSON is on disk -- duplicating it here
    forces every consuming agent to pay ~12-15k tokens for a payload already
    available via file read."""
    mf = report.get("main_freshness", {}) or {}
    behind = mf.get("commits_behind", "?")
    ahead = mf.get("commits_ahead", "?")
    return (
        f"Preflight OK -> {report_path}\n"
        f"  venv={report.get('venv_ok')} creds={report.get('creds_status')} "
        f"branch={report.get('branch')} main=({behind} behind, {ahead} ahead)\n"
        f"  open_recs={report.get('open_recommendations')} "
        f"non_automatable={report.get('non_automatable_recommendations')} "
        f"ci_rca={len(report.get('ci_rca_recs') or [])}\n"
        f"  Read the report file for full constraint detail."
    )


def open_telemetry_session(workflow: str, branch: str) -> str:
    """Open a telemetry session and record state to the active-session file.

    Writes ``logs/.telemetry-active-session.json`` containing the session_id,
    workflow, branch, and started_at timestamp.  Returns the session_id UUID.

    On any error the function logs a warning and returns a generated UUID so
    that callers can still proceed; the telemetry record will simply be partial.
    """
    try:
        from scripts.executor.telemetry import open_session  # noqa: PLC0415

        session_id = open_session(workflow=workflow, branch=branch, model_primary="manual")
    except Exception as exc:  # noqa: BLE001
        import uuid  # noqa: PLC0415

        session_id = str(uuid.uuid4())
        print(f"WARNING: telemetry.open_session failed ({exc}); using local UUID", file=sys.stderr)

    state = {
        "session_id": session_id,
        "workflow": workflow,
        "branch": branch,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    TELEMETRY_ACTIVE_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    TELEMETRY_ACTIVE_SESSION_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return session_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-session environment and context check",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help=("Run only the telemetry health check. Exits non-zero on critical threshold."),
    )
    parser.add_argument(
        "--open-session",
        action="store_true",
        dest="open_session",
        help="Open a telemetry session and write state to logs/.telemetry-active-session.json",
    )
    parser.add_argument(
        "--workflow",
        default="manual",
        help="Workflow name for telemetry (used with --open-session)",
    )
    parser.add_argument(
        "--branch",
        default="",
        help="Branch name for telemetry (used with --open-session; defaults to current git branch)",
    )
    args = parser.parse_args()

    if args.health:
        health = check_telemetry_health()
        print_telemetry_health(health)
        sys.exit(1 if health["overall"] == "critical" else 0)

    if args.open_session:
        branch = args.branch
        if not branch:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
            )
            branch = result.stdout.strip() if result.returncode == 0 else "unknown"
        sid = open_telemetry_session(workflow=args.workflow, branch=branch)
        print(sid)
        sys.exit(0)

    sys.exit(main())
