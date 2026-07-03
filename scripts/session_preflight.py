# complexity-waiver: decision-43
#!/usr/bin/env python3
# complexity-waiver: decision-43
"""Pre-session environment and context check.

Outputs JSON to logs/.preflight-report.json for use by plan.prompt.md.
Exits 1 on critical failure (wrong venv), 0 otherwise.

Usage:
    bin/venv-python -m scripts.session_preflight
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts import platform_roadmap
from scripts import product_roadmap as product_roadmap_module
from scripts.aws_profile import resolve_aws_profile
from scripts.s3_log_store import get_backend, read_jsonl
from scripts.sync_ops import _rebuild_local_cache as _sync_ops_pull  # noqa: F401  (kept for back-compat test patch targets)
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


def check_terraform_pending() -> tuple[bool | None, dict | None]:
    """Read the sandbox convergence record and derive pending-change state.

    Replaces the retired ``terraform -chdir=terraform plan`` invocation (CD.21:
    the terraform/ root is no longer applied; the personal/ sandbox root is
    managed by the CD pipeline). The convergence record at
    convergence/personal/sandbox.json is the authoritative truth for the
    applied-vs-code delta.

    Returns a tuple (pending, convergence_health) where:
      - pending: bool | None
          True  = record is red or unapplied_backlog > 0 (changes pending)
          False = record is green with no backlog
          None  = unavailable (S3 read failed / no credentials)
      - convergence_health: dict | None
          Sub-object surfaced in the preflight report:
          {status, red_age_hours, unapplied_backlog, stuck_approvals, severity}
          or None when the record cannot be fetched.
    """
    try:
        import boto3  # noqa: PLC0415

        from scripts.convergence_health import (  # noqa: PLC0415
            assess_health,
            derive_red_since,
            find_stuck_gated_approvals,
            read_convergence_record,
        )

        profile = resolve_aws_profile()
        session = boto3.Session(profile_name=profile)
        s3 = session.client("s3")

        record = read_convergence_record(s3)
        stuck = find_stuck_gated_approvals()
        verdict = assess_health(record, stuck_approvals=stuck)

        health: dict = {
            "status": verdict.status,
            "red_age_hours": verdict.red_age_hours,
            "unapplied_backlog": verdict.unapplied_backlog,
            "stuck_approvals": len(verdict.stuck_approvals),
            "severity": verdict.severity,
        }

        # PLAN-gated-apply-rca-trigger: carry the record's identity fields so
        # _check_convergence_rca_gap can match on the red episode's start
        # TIMESTAMP (ci_rca recs carry no commit_sha field) while still
        # surfacing commit_sha to the operator in the alert payload. Reuses
        # convergence_health.derive_red_since (the SAME fallback logic
        # red_age_hours() itself is computed from) rather than re-deriving it.
        if record and verdict.status == "red":
            health["commit_sha"] = record.get("commit_sha", "")
            health["run_url"] = record.get("run_url", "")
            health["red_since"] = derive_red_since(record).strftime("%Y-%m-%dT%H:%M:%SZ")

        if verdict.status == "unknown":
            pending = None
        elif verdict.status == "red" or verdict.unapplied_backlog > 0:
            pending = True
        else:
            pending = False

        return pending, health

    except Exception:  # noqa: BLE001
        return None, None


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


def _prime_reader_url(creds_status: str) -> None:
    """Resolve the DuckLake reader URL once and cache it in DUCKLAKE_READER_URL.

    Subsequent _make_reader() calls find the env override and skip SSM
    (Decision 79 first-priority resolution). Non-fatal on failure: if URL
    resolution raises, the env var stays unset and each reader falls through
    to its own SSM resolution as before.
    """
    if creds_status != "ok":
        return
    if os.environ.get("DUCKLAKE_READER_URL"):
        return  # already primed (CI override or earlier call)
    try:
        url = _make_reader()._reader_url()  # type: ignore[union-attr]
        if isinstance(url, str) and url:
            os.environ["DUCKLAKE_READER_URL"] = url
    except Exception as exc:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415

        _log.getLogger(__name__).warning("session_preflight._prime_reader_url: URL resolution failed: %s", exc)


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
            "       warehouse reads (DuckLake reader for recs; Iceberg/Athena for deferred tables)\n"
            "       fall back to the local cache or empty results.",
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


# ---------------------------------------------------------------------------
# Cache-serving derivations (neon-egress-reduction D4).
#
# The Phase-A warm-up sync (sync_ops.warm_sync) pulls ops_recommendations / ops_decisions /
# ops_priority_queue ONCE and returns the rows in-memory. Each Phase-B signal is then DERIVED from
# those rows here -- a client-side re-expression of the corresponding ducklake_reader named verb --
# so Phase B issues ZERO additional reader calls (was ~6-9). The derivations are kept equivalent to
# the canonical verb SQL (src.common.ducklake_scd2_schema.NAMED_READS) by the VP-step-1 equivalence
# test, which runs each verb's SQL over a fixture in-process and asserts it equals the derivation.
#
# Boundary note (Decision 84 I-3): this reads LOCAL rows only; it never issues caller SQL across the
# reader boundary. The rows themselves came from the warm-up sync's named-verb / current_state pulls.
# ---------------------------------------------------------------------------

# Sentinel default distinguishing "no cache rows supplied -> use the reader (back-compat / tests)"
# from "cache rows supplied but None -> reader pull failed -> degrade" (a real None is meaningful).
_READER_SENTINEL: object = object()


def _row_ts(row: dict, field: str = "created_timestamp") -> datetime | None:
    """Parse a row timestamp field (ISO string or datetime) into a UTC-aware datetime, or None."""
    val = row.get(field)
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if hasattr(val, "isoformat"):  # date / other temporal
        try:
            return datetime.fromisoformat(val.isoformat()).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    return _parse_ts_utc(str(val))


def _derive_open_recs(rows: list[dict]) -> list[dict]:
    """Client-side `open_recs` verb: open rows projected to the tally columns, ordered by id."""
    open_rows = [
        {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "context": r.get("context", ""),
            "created_timestamp": r.get("created_timestamp"),
            "automatable": r.get("automatable"),
        }
        for r in rows
        if r.get("status") == "open"
    ]
    return sorted(open_rows, key=lambda r: r.get("id") or "")


def _derive_ci_rca_open(rows: list[dict]) -> list[dict]:
    """Client-side `ci_rca_open` verb: open/in-progress ci_rca recs, newest first, capped at 5."""
    matched = [r for r in rows if r.get("source") == "ci_rca" and r.get("status") in ("open", "in_progress")]
    matched.sort(key=lambda r: _row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [
        {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "priority": r.get("priority", ""),
            "created_timestamp": r.get("created_timestamp"),
            "file": r.get("file", ""),
        }
        for r in matched[:5]
    ]


def _derive_ci_rca_dispute_open(rows: list[dict]) -> list[dict]:
    """Client-side derive: open/in-progress ci_rca_evidence_dispute recs, newest first, capped at 5."""
    matched = [r for r in rows if r.get("source") == "ci_rca_evidence_dispute" and r.get("status") in ("open", "in_progress")]
    matched.sort(key=lambda r: _row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [
        {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "priority": r.get("priority", ""),
            "created_timestamp": r.get("created_timestamp"),
        }
        for r in matched[:5]
    ]


def _derive_ci_rca_undetermined_open(cache_rows: list[dict]) -> list[dict]:
    """Return open source=ci_rca recs with rca_confidence=undetermined from warm cache rows."""
    import json as _json  # noqa: PLC0415

    results = []
    for row in cache_rows:
        if row.get("source") != "ci_rca":
            continue
        if row.get("status") != "open":
            continue
        ctx_raw = row.get("context_v2_json") or ""
        if not ctx_raw:
            continue
        try:
            ctx = _json.loads(ctx_raw)
        except Exception:
            continue
        if ctx.get("rca_confidence") == "undetermined":
            results.append(row)
    return results[:5]


def _fetch_ci_rca_undetermined_recs(cache_rows: object = _READER_SENTINEL) -> list[dict]:
    """Return up to 5 open ci_rca recs with rca_confidence=undetermined -- from warm cache only."""
    if cache_rows is not _READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_undetermined_open(cache_rows)  # type: ignore[arg-type]
    return []


def print_ci_rca_undetermined_recs(recs: list[dict]) -> None:
    """Print mandatory human review section for rca_confidence=undetermined recs."""
    print("\n--- CI-RCA Mandatory Human Review (rca_confidence=undetermined) ---")
    if not recs:
        print("  (none)")
        print()
        return
    print("  [MANDATORY HUMAN REVIEW] Evidence bundle abstained on these recs.")
    print("  Review the proximate cause manually -- the deterministic probe could not classify.")
    for rec in recs:
        rec_id = rec.get("id", "unknown")
        title = rec.get("title", "")
        priority = rec.get("priority", "")
        created = rec.get("created_timestamp", "")
        print(f"  {rec_id} [{priority}] {created}: {title}")
    print()


def _compute_ci_rca_abstention(cache_rows: list[dict] | None, window_days: int = 14) -> dict | None:
    """Compute the CI-RCA probe abstention gauge from the warm cache (T1.13 c12(i)).

    Returns None when the warm cache is unavailable (reader unreachable / offline) --
    zero new reader egress (Decision 88), computed entirely from already-loaded rows.
    """
    if cache_rows is None:
        return None
    from scripts.ci_rca_probe_health import compute_abstention_rate  # noqa: PLC0415

    undetermined_count, total_count, rate = compute_abstention_rate(cache_rows, window_days=window_days)
    return {
        "undetermined_count": undetermined_count,
        "total_count": total_count,
        "rate": rate,
        "window_days": window_days,
    }


def _escalate_ci_rca_probe_health(
    creds_status: str,
    cache_rows: list[dict] | None,
    gauge: dict | None,
) -> dict | None:
    """Idempotently file/update/close a source=ci_rca_probe_health rec on the warm-cache path.

    Skips (returns None) when creds are unavailable or the warm cache did not load -- degraded
    offline sessions never attempt a portal write. This is the deterministic preflight trigger
    that substitutes for a cron until Lambda scheduled agents re-enable (AGENTS.md runbook).
    """
    if creds_status != "ok" or cache_rows is None or gauge is None:
        return None
    try:
        from scripts.ci_rca_probe_health import escalate  # noqa: PLC0415

        open_recs = [r for r in cache_rows if r.get("status") == "open"]
        return escalate(
            gauge["undetermined_count"],
            gauge["total_count"],
            gauge["rate"],
            open_recs,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] preflight: ci_rca_probe_health.escalate() failed: {exc}", file=sys.stderr)
        return None


def print_ci_rca_abstention_gauge(gauge: dict | None) -> None:
    """Print the CI-RCA probe abstention-rate gauge line."""
    if gauge is None:
        return
    print(
        f"CI-RCA probe abstention (last {gauge['window_days']}d): "
        f"{gauge['undetermined_count']}/{gauge['total_count']} undetermined ({gauge['rate']:.0%})"
    )


def _derive_ci_rca_closed(rows: list[dict]) -> list[dict]:
    """Client-side derive: closed ci_rca recs projected to the sibling-cluster fields."""
    matched = [r for r in rows if r.get("source") == "ci_rca" and r.get("status") == "closed"]
    return [
        {
            "id": r.get("id", ""),
            "file": r.get("file", ""),
            "title": r.get("title", ""),
            "last_updated_timestamp": r.get("last_updated_timestamp"),
        }
        for r in matched
    ]


def _derive_ci_rca_since(rows: list[dict], since_ts: str) -> list[dict]:
    """Client-side `ci_rca_since` verb: ci_rca rec ids created strictly after *since_ts*."""
    cutoff = _parse_ts_utc(since_ts)
    if cutoff is None:
        return []
    out: list[dict] = []
    for r in rows:
        if r.get("source") != "ci_rca":
            continue
        ts = _row_ts(r)
        if ts is not None and ts > cutoff:
            out.append({"id": r.get("id", "")})
    return out


def _derive_forward_fix_recursion(rows: list[dict], since_ts: str) -> list[dict]:
    """Client-side `forward_fix_recursion` verb: files with >=3 ci_rca recs since *since_ts*."""
    cutoff = _parse_ts_utc(since_ts)
    if cutoff is None:
        return []
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("source") != "ci_rca":
            continue
        ts = _row_ts(r)
        if ts is None or ts <= cutoff:
            continue
        counts[r.get("file") or ""] = counts.get(r.get("file") or "", 0) + 1
    return [{"file": f, "cnt": c} for f, c in counts.items() if c >= 3]


def _derive_budget_bypass_recent(rows: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Client-side `budget_bypass_recent` verb: budget_bypass recs in the last 7 days, newest first, <=10."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=7)
    matched = []
    for r in rows:
        if r.get("source") != "budget_bypass":
            continue
        ts = _row_ts(r)
        if ts is not None and ts > cutoff:
            matched.append(r)
    matched.sort(key=lambda r: _row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [
        {"id": r.get("id", ""), "context": r.get("context", ""), "created_timestamp": r.get("created_timestamp")}
        for r in matched[:10]
    ]


def _derive_decisions_max_updated(rows: list[dict]) -> list[dict]:
    """Client-side `decisions_max_updated` verb: [{ts: max(last_updated_timestamp)}] (mirrors the verb row)."""
    stamps = [_row_ts(r, "last_updated_timestamp") for r in rows]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return [{"ts": None}]
    newest = max(stamps)
    # Echo the original string form when present (the verb returns the stored value, not a re-format).
    for r in rows:
        if _row_ts(r, "last_updated_timestamp") == newest:
            return [{"ts": r.get("last_updated_timestamp")}]
    return [{"ts": newest.isoformat()}]


def _count_recommendations_reader(cache_rows: object = _READER_SENTINEL) -> tuple[int, int, int, list[dict]] | str:
    """Return open recommendation counts -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): when supplied, the count is DERIVED from the warm-up sync's
    already-pulled rows (zero reader call). A supplied None means the warm-up recs pull FAILED ->
    "reader_unreachable" (Decision 55: loud degraded signal, never a false zero). When omitted
    (sentinel) the function falls back to its own reader call -- the back-compat path for standalone
    callers and tests.

    Returns the tally tuple on success, or the string "reader_unreachable" on reader failure.
    """
    if cache_rows is not _READER_SENTINEL:
        if cache_rows is None:
            return "reader_unreachable"
        return _tally_rec_counts(_derive_open_recs(cache_rows), source="cache")  # type: ignore[arg-type]

    try:
        rows = _make_reader().named("open_recs")
        return _tally_rec_counts(rows, source="reader")
    except Exception as exc:  # noqa: BLE001
        import logging as _log  # noqa: PLC0415

        _log.getLogger(__name__).warning("session_preflight._count_recommendations_reader: reader unreachable: %s", exc)

    return "reader_unreachable"


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
        # Reader rows carry native Python bools; rows migrated from the legacy Athena path may
        # still serialise booleans as the strings "true"/"false" -- normalise both forms.
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

    Reads from the DuckLake reader first (Decision 81 cl.7 / T2.19 cutover); there is
    no Athena fallback. On reader failure, emits a LOUD reader_unreachable warning
    (Decision 55: never a silent false zero) and degrades to counting from the local
    read cache (S3 backend or logs/.recommendations-log.jsonl), which may be stale.

    Note: main() does not call this function -- it calls _count_recommendations_reader()
    directly and reports the sentinel (0,0,0,[]) plus recs_read_status=reader_unreachable
    on failure. This cache-counting fallback is retained for non-main consumers.
    """
    result = _count_recommendations_reader()
    if result != "reader_unreachable":
        print("  (recommendations sourced from DuckLake reader)")
        return result  # type: ignore[return-value]

    print(
        "[WARN] session_preflight: recs reader unreachable -- recs counts are DEGRADED "
        "(recs_read_status=reader_unreachable). Run `aws sts get-caller-identity --profile "
        "agent_platform` to verify credentials. The ops loop is impaired until the reader "
        "is reachable.",
        file=sys.stderr,
    )
    # Return sentinel -- callers must check recs_read_status in the report
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
    """Normalise rows into the {rank, rec_id, rationale, north_star_impact} shape, rank-sorted.

    Sort BEFORE slicing: with more rows than max_items, slice-then-sort presented an arbitrary
    subset as the top N (unparseable ranks sort last).
    """

    def _rank_key(row: dict) -> tuple:
        try:
            return (False, int(row.get("rank", 0)))
        except (ValueError, TypeError):
            return (True, 0)

    result = []
    for row in sorted(rows, key=_rank_key)[:max_items]:
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


def read_priority_queue(max_items: int = 5, creds_status: str = "ok", cache_rows: object = _READER_SENTINEL) -> list[dict]:
    """Read the priority queue via the priority_queue_current read verb (DuckLake reader).

    Decision 70: the verb's correlated subquery returns ALL entries of the latest
    curator run -- the generic latest-per-key current projection would silently
    change these semantics.

    cache_rows (neon-egress-reduction D4): when supplied, the queue is served from the warm-up
    sync's already-pulled priority_queue_current rows (zero reader call) -- the local cache IS that
    verb's output, so no re-derivation is needed, only shaping. A supplied None means the warm-up
    pull FAILED: degrade to the local read-cache with a staleness warning (the warm-up sync already
    surfaced the reader failure loudly; preflight completes in degraded mode, Decision 60). When
    omitted (sentinel) the function uses the reader directly -- the back-compat path below.

    When *creds_status* is not "ok" credentials are unavailable: fall back to the
    local read-cache with a staleness warning (empty-with-warning when absent; never
    crash -- T2.5 graceful-degradation requirement).

    When credentials ARE "ok" and the verb fails, that is a genuine infrastructure
    fault -- hard-exit with code 1 rather than masking it (Decision 60).

    Returns a list of dicts shaped as {rank, rec_id, rationale, north_star_impact}.
    Returns [] if the queue is empty.
    """
    if cache_rows is not _READER_SENTINEL:
        if cache_rows is None:
            return _read_priority_queue_cache(max_items)
        shaped = _shape_priority_queue_rows(cache_rows, max_items)  # type: ignore[arg-type]
        shaped.sort(key=lambda r: (r.get("rank") is None, r.get("rank", 0)))
        return shaped

    if creds_status != "ok":
        return _read_priority_queue_cache(max_items)

    # Decision 70 semantics (all entries of the LATEST curator run) are preserved inside the
    # priority_queue_current verb's correlated subquery -- not by the generic current projection.
    try:
        reader_rows = _make_reader(table="ops_priority_queue").named("priority_queue_current")
        shaped = _shape_priority_queue_rows(reader_rows, max_items)
        shaped.sort(key=lambda r: (r.get("rank") is None, r.get("rank", 0)))
        return shaped
    except Exception as exc:  # noqa: BLE001
        print(
            f"[ERROR] priority_queue_current verb failed ({exc}) -- infrastructure problem, "
            "not masking with fallback (Decision 60)",
            file=sys.stderr,
        )
        sys.exit(1)


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


def _fetch_ci_rca_recs(cache_rows: object = _READER_SENTINEL) -> list[dict]:
    """Return up to 5 open CI-RCA recs -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via _derive_ci_rca_open
    (zero reader call); a supplied None means the warm-up pull failed -> [] (degraded). Omitted
    (sentinel) -> reader path (back-compat / tests). Returns [] with a loud warning on reader failure
    (Decision 55 / Decision 81 cl.7: no Athena fallback; loud degraded signal).
    """
    if cache_rows is not _READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_open(cache_rows)  # type: ignore[arg-type]

    _reader_exc: Exception | None = None
    try:
        return _make_reader().named("ci_rca_open")
    except Exception as exc:  # noqa: BLE001
        _reader_exc = exc

    print(
        f"[WARN] preflight: ci_rca recs reader unreachable ({_reader_exc}) -- CI RCA Recs "
        "section degraded (recs_read_status=reader_unreachable). No Athena fallback (Decision 81 cl.7).",
        file=sys.stderr,
    )
    return []


def _fetch_ci_rca_dispute_recs(cache_rows: object = _READER_SENTINEL) -> list[dict]:
    """Return up to 5 open ci_rca_evidence_dispute recs -- from the warm-pulled cache rows only.

    cache_rows (neon-egress-reduction D4 / Decision 88 egress invariant): a supplied row list is
    served via _derive_ci_rca_dispute_open (zero reader call); a supplied None means the warm-up
    pull failed -> []. Omitted (sentinel) -> [] (no new DuckLake reader named-verb for dispute recs;
    the dispute section derives from the same warm cache used by _fetch_ci_rca_recs).
    """
    if cache_rows is not _READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_dispute_open(cache_rows)  # type: ignore[arg-type]
    return []


def print_ci_rca_dispute_recs(recs: list[dict]) -> None:
    """Print the CI-RCA Dispute Recs section to terminal."""
    print("\n--- CI-RCA Dispute Recs (open) ---")
    if not recs:
        print("  (none)")
        print()
        return
    for rec in recs:
        rec_id = rec.get("id", "unknown")
        title = rec.get("title", "")
        priority = rec.get("priority", "")
        created = rec.get("created_timestamp", "")
        print(f"  {rec_id} [{priority}] {created}: {title}")
    print()


def _check_non_automatable_softcap(non_auto_count: int) -> bool:
    """Return True when non-automatable rec count exceeds the soft cap."""
    return non_auto_count > _NON_AUTOMATABLE_SOFTCAP


def _fetch_ci_rca_recs_since(ts: str, cache_rows: object = _READER_SENTINEL) -> list[dict]:
    """Return ci_rca recs created after *ts* -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via _derive_ci_rca_since
    (zero reader call); a supplied None -> []. Omitted (sentinel) -> reader path (back-compat).
    Returns [] on any failure (Decision 81 cl.7: no Athena fallback).
    """
    if cache_rows is not _READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_since(cache_rows, ts)  # type: ignore[arg-type]
    try:
        return _make_reader().named("ci_rca_since", since_ts=ts)
    except Exception:  # noqa: BLE001
        pass
    return []


def _check_ci_rca_liveness(creds_status: str, cache_rows: object = _READER_SENTINEL) -> dict | None:
    """Return alert dict when main CI has been red with no ci-rca rec for >30 min.

    Calls `gh run list` to determine the latest push-to-main ci.yml result.
    Returns None when credentials are unavailable, gh call fails, or conditions are not met.

    cache_rows (neon-egress-reduction D4) is threaded to _fetch_ci_rca_recs_since so the "any ci_rca
    rec since the red run?" check is served from the warm-pulled rows (zero reader call). The gh CLI
    call is unaffected (it is the CI-status source, not a warehouse read).
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

    if _fetch_ci_rca_recs_since(created_at, cache_rows=cache_rows):
        return None

    return {"run_url": run.get("url", ""), "elapsed_minutes": round(elapsed_minutes, 1)}


_CONVERGENCE_RCA_GAP_GRACE_MINUTES = 30


def _check_convergence_rca_gap(convergence_health: dict | None, cache_rows: object = _READER_SENTINEL) -> dict | None:
    """Return alert dict when the convergence record is red beyond grace with no ci_rca rec since.

    Generalises _check_ci_rca_liveness (which only inspects ci.yml push-to-main failures) to the
    convergence-record surface: PLAN-gated-apply-rca-trigger's confirmed gap (run 28379330706,
    gated-apply, run_attempt=2) wrote a red record with zero RCA signal and was invisible to
    _check_ci_rca_liveness. Matches on the red episode's start TIMESTAMP (red_since) vs
    ci_rca rec creation time -- NOT commit_sha, which ci_rca recs carry no structured field for
    (a commit match would fire a permanent false-positive even after a valid rec is filed).
    commit_sha rides the alert payload for the operator only. Degrades to None on any error or
    missing data (rec-2027 pattern -- never crashes preflight).
    """
    try:
        if not convergence_health or convergence_health.get("status") != "red":
            return None

        red_since = convergence_health.get("red_since")
        if not red_since:
            return None

        red_age_hours = convergence_health.get("red_age_hours") or 0.0
        if (red_age_hours * 60.0) <= _CONVERGENCE_RCA_GAP_GRACE_MINUTES:
            return None

        if _fetch_ci_rca_recs_since(red_since, cache_rows=cache_rows):
            return None

        return {
            "commit_sha": convergence_health.get("commit_sha", ""),
            "run_url": convergence_health.get("run_url", ""),
            "red_age_hours": round(red_age_hours, 2),
            "red_since": red_since,
        }
    except Exception:  # noqa: BLE001
        return None


def _check_forward_fix_recursion(cache_rows: object = _READER_SENTINEL) -> dict | None:
    """Return alert dict when >=3 ci-rca recs targeting the same file appear in the last 24h.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_forward_fix_recursion (zero reader call); a supplied None -> degrade to None. Omitted
    (sentinel) -> reader path. Returns None when no recursion is detected or the warehouse is
    unreachable.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    if cache_rows is not _READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_forward_fix_recursion(cache_rows, cutoff)  # type: ignore[arg-type]
    else:
        try:
            rows = _make_reader().named("forward_fix_recursion", since_ts=cutoff)
        except Exception:  # noqa: BLE001
            return None

    if not rows:
        return None
    first = rows[0]
    try:
        count = int(first.get("cnt", 3))
    except (ValueError, TypeError):
        count = 3
    return {"file": first.get("file", ""), "count": count, "threshold": 3}


def _check_budget_bypass_alert(cache_rows: object = _READER_SENTINEL) -> dict | None:
    """Return alert dict when >= 3 budget_bypass recs were filed in the last 7 days.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_budget_bypass_recent (zero reader call); a supplied None -> degrade to None. Omitted
    (sentinel) -> reader path. Returns None when count < 3 or the warehouse is unreachable.
    """
    if cache_rows is not _READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_budget_bypass_recent(cache_rows)  # type: ignore[arg-type]
    else:
        try:
            rows = _make_reader().named("budget_bypass_recent")
        except Exception:  # noqa: BLE001
            return None

    if rows is None or len(rows) < 3:
        return None
    return {"count": len(rows), "entries": rows}


def _parse_ts_utc(ts: str) -> datetime | None:
    """Parse an ISO-like timestamp string into a UTC-aware datetime, or None on failure."""
    ts = ts.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


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
            cwd=ROOT,
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


_CI_TITLE_STOPWORDS: frozenset[str] = frozenset({"ci", "failure", "failed", "error", "lint", "test", "fix", "rca"})


def _title_jaccard(title_a: str, title_b: str) -> float:
    """Lowercased alphanumeric-token Jaccard between two titles, with common CI stopwords removed."""

    def _tokens(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _CI_TITLE_STOPWORDS}

    set_a = _tokens(title_a)
    set_b = _tokens(title_b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _file_paths_correlate(rec_file: str, changed: str) -> bool:
    """Return True when rec_file and changed refer to the same repository file.

    Matches on exact equality or a trailing path-component suffix match: split
    both on "/" and compare the last N components (N = min of the two lengths).
    A bare basename rec file therefore matches any changed path that ends with
    that basename, but a substring that crosses a component boundary does not.
    """
    if rec_file == changed:
        return True
    parts_rec = rec_file.split("/")
    parts_changed = changed.split("/")
    n = min(len(parts_rec), len(parts_changed))
    return parts_rec[-n:] == parts_changed[-n:]


def correlate_recs_with_commits(
    recs: list[dict],
    commits: list[dict],
    closed_recs: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """Classify open recs as LIKELY-RESOLVED or UNRESOLVED from commit history.

    General engine for all rec sources (generalised from the ci_rca path, T3.8).
    Served from the already-warmed read-cache; never performs a warehouse re-fetch
    or acceptance-command execution (Decision 88).

    A rec is LIKELY-RESOLVED when any commit on origin/main whose date is
    AFTER the rec's created_timestamp either:
      - modified the rec's ``file`` field (path-suffix / basename match), or
      - mentions the rec's ``id`` in its subject line.

    When ``closed_recs`` is provided (cache path only), a rec that is
    still uncorrelated after the commit loop is also classified LIKELY-RESOLVED
    when a closed sibling on the same file has a sufficiently similar
    title and was closed at/after this rec's creation (window-independent
    closed-sibling cluster signal). The matched sibling id is recorded on the
    rec as ``_resolved_reason`` for the operator's verify-and-close prompt.

    Args:
        recs:         Open recs to classify.
        commits:      Recent main commits from _get_recent_main_commits().
        closed_recs:  Closed recs (cache path), or None to skip cluster detection.

    Returns:
        Dict with keys ``likely_resolved`` and ``unresolved``, each a list of recs.
    """
    if not recs:
        return {"likely_resolved": [], "unresolved": []}

    likely_resolved: list[dict] = []
    unresolved: list[dict] = []

    for rec in recs:
        rec_id = (rec.get("id") or "").lower()
        rec_file = (rec.get("file") or "").strip()
        rec_created_dt = _parse_ts_utc(rec.get("created_timestamp") or "")

        correlated = False
        for commit in commits:
            commit_dt = _parse_ts_utc(commit.get("date") or "")

            if rec_created_dt is not None and commit_dt is not None:
                if commit_dt <= rec_created_dt:
                    continue

            subject_lower = (commit.get("subject") or "").lower()
            if rec_id and rec_id in subject_lower:
                correlated = True
                break

            if rec_file:
                for changed in commit.get("files") or []:
                    if _file_paths_correlate(rec_file, changed):
                        correlated = True
                        break
            if correlated:
                break

        # Closed-sibling cluster: window-independent signal (Decision 88 invariant ii --
        # served from the already-pulled cache, never a fresh reader call).
        if not correlated and closed_recs and rec_file:
            for sibling in closed_recs:
                sib_file = (sibling.get("file") or "").strip()
                if not sib_file:
                    continue
                if not _file_paths_correlate(rec_file, sib_file):
                    continue
                if _title_jaccard(rec.get("title") or "", sibling.get("title") or "") < 0.5:
                    continue
                sib_closed_dt = _row_ts(sibling, "last_updated_timestamp")
                if sib_closed_dt is None:
                    continue
                if rec_created_dt is not None and sib_closed_dt < rec_created_dt:
                    continue
                rec = {**rec, "_resolved_reason": f"likely resolved by sibling {sibling.get('id', '')}"}
                correlated = True
                break

        if correlated:
            likely_resolved.append(rec)
        else:
            unresolved.append(rec)

    return {"likely_resolved": likely_resolved, "unresolved": unresolved}


def correlate_ci_rca_with_main(
    recs: list[dict],
    commits: list[dict],
    closed_ci_rca_recs: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """Classify open ci_rca recs as LIKELY-RESOLVED or UNRESOLVED.

    Thin wrapper around correlate_recs_with_commits() for backward compatibility.
    See that function for signal documentation.

    Args:
        recs:              Open ci_rca recs from _fetch_ci_rca_recs().
        commits:           Recent main commits from _get_recent_main_commits().
        closed_ci_rca_recs: Closed ci_rca recs from _derive_ci_rca_closed() (cache path).

    Returns:
        Dict with keys ``likely_resolved`` and ``unresolved``, each a list of recs.
    """
    return correlate_recs_with_commits(recs, commits, closed_recs=closed_ci_rca_recs)


def surface_queue_relevance_triage(
    cache_rows: list[dict],
    commits: list[dict],
    *,
    exclude_sources: frozenset[str] = frozenset({"ci_rca"}),
    cap: int = 10,
) -> list[dict]:
    """Return queue-wide likely-resolved recs for operator triage (read-cache only, Decision 88).

    Runs cheap commit-file correlation on all open recs EXCEPT those in ``exclude_sources``
    (ci_rca has its own dedicated triage block). Never calls the warehouse reader and never
    executes acceptance probes -- surfacing-only per Decision 55.

    Args:
        cache_rows:      All rows from the warmed read-cache (logs/.recommendations-log.jsonl).
        commits:         Recent main commits already fetched by the caller.
        exclude_sources: Source tags that have their own triage block (default: ci_rca).
        cap:             Maximum recs returned.

    Returns:
        Likely-resolved recs (up to ``cap``), newest first.
    """
    open_non_ci = [r for r in cache_rows if r.get("status") == "open" and (r.get("source") or "") not in exclude_sources]
    closed_recs = [
        {
            "id": r.get("id", ""),
            "file": r.get("file", ""),
            "title": r.get("title", ""),
            "last_updated_timestamp": r.get("last_updated_timestamp"),
        }
        for r in cache_rows
        if r.get("status") == "closed" and (r.get("source") or "") not in exclude_sources
    ]
    result = correlate_recs_with_commits(open_non_ci, commits, closed_recs=closed_recs)
    likely = result.get("likely_resolved") or []
    likely.sort(key=lambda r: _row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return likely[:cap]


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


def print_ci_rca_recs(recs: list[dict], correlation: dict[str, list[dict]] | None = None) -> None:
    """Print the CI RCA Recs section to terminal.

    When ``correlation`` is provided, recs are split into LIKELY-RESOLVED
    (soft verify+close prompt) and UNRESOLVED (HARD BLOCK retained).
    When ``correlation`` is None all recs are treated as UNRESOLVED (backward compat).
    """
    print("\n--- CI RCA Recs (open) ---")
    if not recs:
        print("  (none)")
        print()
        return

    if correlation is None:
        # Backward-compat path: all recs are HARD BLOCK.
        print("  [HARD BLOCK] /plan cannot scope unrelated work while these recs are open.")
        for rec in recs:
            rec_id = rec.get("id", "unknown")
            title = rec.get("title", "")
            priority = rec.get("priority", "")
            created = rec.get("created_timestamp", "")
            print(f"  {rec_id} [{priority}] {created}: {title}")
        print()
        return

    likely_resolved = correlation.get("likely_resolved") or []
    unresolved = correlation.get("unresolved") or []

    if likely_resolved:
        print(
            "  [SOFT -- LIKELY RESOLVED] A recent main commit appears to have fixed these recs. Verify and close before /plan:"
        )
        for rec in likely_resolved:
            rec_id = rec.get("id", "unknown")
            title = rec.get("title", "")
            priority = rec.get("priority", "")
            created = rec.get("created_timestamp", "")
            print(f"  {rec_id} [{priority}] {created}: {title}")
            print(
                f"    -> bin/venv-python -m scripts.ops_data_portal --update-rec {rec_id}"
                ' --status closed --resolution "Verified resolved by main commit"'
            )

    if unresolved:
        print("  [HARD BLOCK] /plan cannot scope unrelated work while these recs remain open.")
        for rec in unresolved:
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


def read_context_files(open_recs_count: int | None = None) -> dict:
    """Read key context documents and return a summary dict for plan.prompt.md.

    Args:
        open_recs_count: Pre-computed open-recs count from the caller. When provided,
            the open_recs verb query is skipped (dedup: avoids a second named() call
            when main() has already fetched the count via _count_recommendations_reader).
            Standalone callers (e.g. tests) may omit it; the function falls back to
            its own open_recs query in that case.

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

    # recommendations_count: use pre-computed count when available (avoids a second
    # open_recs verb call when main() already fetched the count in Phase B).
    if open_recs_count is not None:
        recommendations_count = open_recs_count
    else:
        recommendations_count = 0
        try:
            recommendations_count = len(_make_reader().named("open_recs"))
        except Exception:  # noqa: BLE001
            pass

    return {
        "roadmap_phase": roadmap_phase,
        "open_decisions_count": open_decisions_count,
        "recent_sessions": recent_sessions,
        "strategic_review_due": strategic_review_due,
        "recommendations_count": recommendations_count,
    }


def check_telemetry_health() -> dict:
    """Telemetry health stub: the Athena telemetry tables died with the 2026-05-28 account
    migration, so the previous implementation polled TABLE_NOT_FOUND for ~a minute every
    session. Telemetry re-lands on DuckLake in consolidation Phase 4 (Decision 84); until
    then this reports not_migrated WITHOUT issuing any query.

    Returns a dict compatible with ``print_telemetry_health()``.
    """
    return {
        "overall": "unknown",
        "checks": [{"check": "telemetry-store", "value": "not migrated (Phase 4)", "severity": "unknown"}],
        "friction_patterns": [],
    }


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
                "unavailable": data.get("unavailable", 0),
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
            unavail_str = f"/{lr.get('unavailable', 0)}U" if lr.get("unavailable", 0) else ""
            verdict_tag = " [DEGRADED -- backend unavailable]" if lr["verdict"] == "DEGRADED" else ""
            print(
                f"  Last run: {lr['verdict']}{verdict_tag} "
                f"({lr['passed']}P/{lr['failed']}F/{lr['warned']}W{unavail_str}) at {lr['timestamp']}"
            )
        else:
            print("  Last run: never (run: python -m scripts.data_quality_runner)")
    print()


def _get_latest_decision_ts(cache_rows: object = _READER_SENTINEL) -> str | None:
    """Return the max decision last_updated_timestamp -- from the warm-pulled rows, else the verb.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_decisions_max_updated (zero reader call); a supplied None -> None. Omitted (sentinel) ->
    decisions_max_updated verb (back-compat / tests).
    """
    if cache_rows is not _READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_decisions_max_updated(cache_rows)  # type: ignore[arg-type]
    else:
        try:
            rows = _make_reader(table="ops_decisions").named("decisions_max_updated")
        except Exception:  # noqa: BLE001
            return None
    if not rows:
        return None
    ts = rows[0].get("ts") or ""
    return str(ts) if ts else None


def _check_endstate_drift() -> dict:
    """Advisory drift check: compare the sha256 fingerprint stamped in PROJECT_CONTEXT.md
    against the current sha256 of the sorted ROADMAP-PLATFORM.yaml tier_item ID set.

    Returns a dict {stale, synthesized_hash, current_hash, new_ids}.
    Fail-open: any parse/IO error returns a non-stale result with a soft note.
    Never raises, never changes the preflight exit code.
    """
    try:
        import yaml  # noqa: PLC0415

        context_text = (ROOT / "docs" / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
        stamp_match = re.search(r"roadmap_tier_id_set sha256:\s*([a-f0-9]{64})", context_text)
        if not stamp_match:
            return {"stale": False, "synthesized_hash": None, "current_hash": None, "new_ids": [], "note": "stamp absent"}
        stamped_hash = stamp_match.group(1)

        roadmap = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        _items = roadmap.get("tier_items", [])
        current_ids = sorted({str(i["id"]) for i in _items if isinstance(i, dict) and "id" in i})
        current_hash = hashlib.sha256("\n".join(current_ids).encode()).hexdigest()

        if current_hash == stamped_hash:
            return {"stale": False, "synthesized_hash": current_hash, "current_hash": current_hash, "new_ids": []}

        commit_match = re.search(r"ROADMAP-PLATFORM\.yaml\s*@\s*([0-9a-f]{7,40})", context_text)
        new_ids: list[str] = []
        if commit_match:
            ref = commit_match.group(1)
            try:
                result = subprocess.run(
                    ["git", "show", f"{ref}:docs/ROADMAP-PLATFORM.yaml"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    cwd=str(ROOT),
                )
                if result.returncode == 0:
                    old_roadmap = yaml.safe_load(result.stdout)
                    _old_items = old_roadmap.get("tier_items", [])
                    old_ids = sorted({str(i["id"]) for i in _old_items if isinstance(i, dict) and "id" in i})
                    if hashlib.sha256("\n".join(old_ids).encode()).hexdigest() == stamped_hash:
                        new_ids = sorted(set(current_ids) - set(old_ids))
            except Exception:  # noqa: BLE001
                pass

        return {"stale": True, "synthesized_hash": stamped_hash, "current_hash": current_hash, "new_ids": new_ids}
    except Exception:  # noqa: BLE001
        return {"stale": False, "synthesized_hash": None, "current_hash": None, "new_ids": [], "note": "parse error"}


def main(roadmap_detail: str = "slim") -> int:
    session_start = datetime.now(timezone.utc).isoformat()

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

    # Phase A: run credential check, git freshness, and terraform check concurrently.
    # creds_status and main_freshness must be resolved before Phase B starts.
    with ThreadPoolExecutor(max_workers=3) as phase_a:
        fut_creds = phase_a.submit(check_credentials)
        fut_freshness = phase_a.submit(check_main_freshness)
        fut_terraform = phase_a.submit(check_terraform_pending)
        creds_result = fut_creds.result()
        main_freshness = fut_freshness.result()
        terraform_result = fut_terraform.result()

    # check_terraform_pending now returns (bool|None, dict|None)
    if isinstance(terraform_result, tuple):
        terraform_pending, convergence_health_data = terraform_result
    else:
        terraform_pending, convergence_health_data = terraform_result, None

    creds_status = _handle_credentials_startup(creds_result)
    s3_log_bucket_set = bool(os.environ.get("S3_LOG_BUCKET", "").strip())

    # Prime the DuckLake reader URL once so all subsequent named() calls skip SSM
    # (Decision 79 first-priority resolution). The remaining reader fan-out in Phase B
    # then hits the Lambda URL directly rather than re-resolving SSM on each call.
    _prime_reader_url(creds_status)

    # Single warm-up sync: drain outbox then pull every migrated ops table ONCE, holding the rows
    # in-memory. This is the one serial reader touch that absorbs the Neon cold-resume before the
    # Phase B work; every Phase-B signal is then DERIVED from these rows -- ZERO additional reader
    # calls (neon-egress-reduction D4: catalog egress was self-inflicted by a ~9-10-call fan-out).
    # (The cold-resume warm-up is NOT attributable to Decision 82 -- that Decision concerns the
    # DIRECT-vs-pooled endpoint basis and the EC8 churn-gate N=8->4 frame, audit F-033; the warm
    # connection reuse / egress-budget rationale is the neon-egress-reduction Decision.)
    outbox: dict = {}
    recommendation_sync: dict = {}
    warm_rows: dict[str, list[dict] | None] = {}
    warm_reader_ok: dict[str, bool] = {}
    try:
        from scripts.sync_ops import outbox_summary  # noqa: PLC0415

        outbox = outbox_summary()
        if outbox:
            total = sum(outbox.values())
            print(f"Ops outbox: {total} pending entries ({outbox})", file=sys.stderr)
    except Exception:  # noqa: BLE001
        outbox = {}

    if creds_status == "ok":
        try:
            from scripts.sync_ops import warm_sync  # noqa: PLC0415

            warm = warm_sync()
            recommendation_sync = warm.get("pulled", {})  # type: ignore[assignment]
            warm_rows = warm.get("rows", {})  # type: ignore[assignment]
            warm_reader_ok = warm.get("reader_ok", {})  # type: ignore[assignment]
            drained = sum((warm.get("drained") or {}).values())  # type: ignore[union-attr]
            pulled = sum((warm.get("pulled") or {}).values())  # type: ignore[union-attr]
            if drained or pulled:
                print(
                    f"Ops sync: drained {drained} outbox entries, pulled {pulled} rows from the warehouse",
                    file=sys.stderr,
                )
        except Exception:  # noqa: BLE001
            pass  # sync is best-effort

    last_session = parse_last_session()

    # Resolve the per-table warm-pull outcome. cache_rows semantics (D4): a list => serve from it;
    # None => that table's reader pull FAILED (degrade loudly); never the reader sentinel here, so
    # NO Phase-B signal re-touches the reader. creds-down also yields None (degraded read-cache).
    recs_cache = warm_rows.get("ops_recommendations") if warm_reader_ok.get("ops_recommendations") else None
    pq_cache = warm_rows.get("ops_priority_queue") if warm_reader_ok.get("ops_priority_queue") else None
    dec_cache = warm_rows.get("ops_decisions") if warm_reader_ok.get("ops_decisions") else None

    # Phase B: the Neon reader fan-out is gone (D4) -- signals are derived from the warm-up rows
    # above. The executor now fans out only the independent SUBPROCESS calls (git log, gh run list)
    # plus the cheap local derivations. Cap at <=4 concurrent workers to avoid Neon connect p95
    # inflation (Decision 82). Retrieve every future via .result() so exceptions and SystemExit
    # re-raise in the main thread (Decision 55/81).
    with ThreadPoolExecutor(max_workers=4) as phase_b:
        fut_rec_count = phase_b.submit(_count_recommendations_reader, recs_cache)
        fut_ci_rca = phase_b.submit(_fetch_ci_rca_recs, recs_cache)
        fut_ci_rca_dispute = phase_b.submit(_fetch_ci_rca_dispute_recs, recs_cache)
        fut_ci_rca_undetermined = phase_b.submit(_fetch_ci_rca_undetermined_recs, recs_cache)
        fut_pq = phase_b.submit(read_priority_queue, 5, creds_status, pq_cache)
        fut_commits = phase_b.submit(_get_recent_main_commits)
        fut_decision_ts = phase_b.submit(_get_latest_decision_ts, dec_cache)
        fut_ci_liveness = phase_b.submit(_check_ci_rca_liveness, creds_status, recs_cache)
        fut_convergence_rca_gap = phase_b.submit(_check_convergence_rca_gap, convergence_health_data, recs_cache)
        fut_forward_fix = phase_b.submit(_check_forward_fix_recursion, recs_cache)
        fut_budget = phase_b.submit(_check_budget_bypass_alert, recs_cache)

        _rec_result = fut_rec_count.result()
        ci_rca_recs = fut_ci_rca.result()
        ci_rca_dispute_recs = fut_ci_rca_dispute.result()
        ci_rca_undetermined_recs = fut_ci_rca_undetermined.result()
        priority_queue = fut_pq.result()
        recent_main_commits = fut_commits.result()
        latest_decision_ts = fut_decision_ts.result()
        ci_rca_liveness_alert = fut_ci_liveness.result()
        convergence_rca_gap_alert = fut_convergence_rca_gap.result()
        forward_fix_alert = fut_forward_fix.result()
        budget_bypass_alert = fut_budget.result()

    recs_read_status: str
    if _rec_result == "reader_unreachable":
        recs_read_status = "reader_unreachable"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = 0, 0, 0, []
    else:
        recs_read_status = "ok"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = _rec_result  # type: ignore[misc]

    closed_ci_rca_recs = _derive_ci_rca_closed(recs_cache) if recs_cache is not None else None
    correlation = correlate_ci_rca_with_main(ci_rca_recs, recent_main_commits, closed_ci_rca_recs=closed_ci_rca_recs)
    print_ci_rca_recs(ci_rca_recs, correlation=correlation)
    print_ci_rca_dispute_recs(ci_rca_dispute_recs)
    print_ci_rca_undetermined_recs(ci_rca_undetermined_recs)

    ci_rca_abstention_gauge = _compute_ci_rca_abstention(recs_cache)
    ci_rca_probe_health_escalation = _escalate_ci_rca_probe_health(creds_status, recs_cache, ci_rca_abstention_gauge)
    print_ci_rca_abstention_gauge(ci_rca_abstention_gauge)

    print_priority_queue(priority_queue)
    _print_recent_main_commits(recent_main_commits)

    # Scan provisional contracts inline (reads only local docs/contracts/ -- no creds, no ThreadPoolExecutor).
    # The default per-contract provider computes a deterministic days-since-first-production-invocation
    # metric from each contract's provisional_v0 date; production_invocations stays dormant (T2.36).
    provisional_contracts_due = _scan_provisional_contracts()

    print("\n--- Provisional contracts due ---")
    if provisional_contracts_due:
        for contract_id in provisional_contracts_due:
            print(f"  {contract_id}: re_ratification_trigger fired -- ratification review required")
    else:
        print("  (none)")
    print()

    # Dedupe open_recs: count already computed in Phase B; pass to read_context_files
    # to skip the second open_recs verb call (Decision 84 I-3: closed named-verb boundary).
    open_recs_count = open_recommendations if recs_read_status == "ok" else None
    context = read_context_files(open_recs_count=open_recs_count)

    # Dedupe decisions_max_updated: timestamp fetched once in Phase B; reuse for both
    # roadmap compute_state_dict calls rather than re-issuing the verb.
    platform_roadmap_state = platform_roadmap.compute_state_dict(ROADMAP_PLATFORM_PATH, latest_decision_ts=latest_decision_ts)
    product_roadmap_state = product_roadmap_module.compute_state_dict(
        ROADMAP_PRODUCT_PATH,
        platform_yaml_path=ROADMAP_PLATFORM_PATH,
        latest_decision_ts=latest_decision_ts,
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
        "convergence_health": convergence_health_data,
        "last_session": last_session,
        "open_recommendations": open_recommendations,
        "aging_recommendations": aging_recommendations,
        "non_automatable_recommendations": non_automatable_count,
        "priority_queue": priority_queue,
        "priority_queue_source": "ducklake_reader" if creds_status == "ok" else "cache",
        "recs_read_status": recs_read_status,
        "ci_rca_recs": ci_rca_recs,
        "ci_rca_unresolved_recs": correlation.get("unresolved") or [],
        "ci_rca_likely_resolved_recs": correlation.get("likely_resolved") or [],
        "ci_rca_dispute_recs": ci_rca_dispute_recs,
        "ci_rca_undetermined_recs": ci_rca_undetermined_recs,
        "ci_rca_abstention_gauge": ci_rca_abstention_gauge,
        "ci_rca_probe_health_escalation": ci_rca_probe_health_escalation,
        "recent_main_commits": recent_main_commits,
        "friction_patterns": telemetry_health.get("friction_patterns", []),
        "log_sync_result": log_sync_result,
        "recommendation_sync": recommendation_sync,
        "telemetry_health": telemetry_health,
        "data_quality": check_data_quality_coverage(),
        "context": context,
        "platform_roadmap": _slim_roadmap_state(platform_roadmap_state, full=(roadmap_detail == "full")),
        "product_roadmap": _slim_roadmap_state(product_roadmap_state),
        "session_start": session_start,
    }

    report["provisional_contracts_due"] = provisional_contracts_due
    report["non_automatable_softcap_breached"] = _check_non_automatable_softcap(non_automatable_count)
    report["ci_rca_liveness_alert"] = ci_rca_liveness_alert
    report["convergence_rca_gap_alert"] = convergence_rca_gap_alert
    if convergence_rca_gap_alert is not None:
        print(
            f"Convergence RCA gap alert: record red {convergence_rca_gap_alert['red_age_hours']}h "
            f"(commit {convergence_rca_gap_alert.get('commit_sha', '')[:8]}) with no matching ci_rca rec filed "
            "since the red episode began -- file one manually or dispatch ci-rca.yml.",
            file=sys.stderr,
        )
    report["forward_fix_recursion_alert"] = forward_fix_alert
    report["budget_bypass_alert"] = budget_bypass_alert
    if budget_bypass_alert is not None:
        print(
            f"Budget bypass alert: {budget_bypass_alert['count']} --ignore-budget invocations in the last 7 days."
            " Repeated bypass indicates fast-tier drift -- consider a planning session to revisit the budget.",
            file=sys.stderr,
        )

    endstate_drift = _check_endstate_drift()
    report["endstate_drift"] = endstate_drift
    if endstate_drift.get("stale"):
        new_ids = endstate_drift.get("new_ids") or []
        ids_note = f" (new ids: {new_ids})" if new_ids else ""
        _msg = f"Advisory: Platform End-State fingerprint stale -- roadmap has new tier_item IDs since the stamp.{ids_note}"
        print(_msg, file=sys.stderr)

    # Ensure logs/ directory exists
    PREFLIGHT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    PREFLIGHT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(_format_preflight_summary(report, PREFLIGHT_REPORT))

    return 0 if venv_ok else 1


def _slim_roadmap_state(state: dict, full: bool = False) -> dict:
    """Return actionable roadmap subsets for session workflows.

    slim (full=False, default -- used by /plan): next_eligible + strategic_pending only.
    Keeps the planning agent's payload lean; blocked_on_cd and gate_evaluations are absent.

    full (full=True -- used by /orient): entire computed state including in_progress, blocked,
    active_tier, blocked_on_cd, ratifiable_cds, and gate_evaluations. Uses .get() defaults so
    product_roadmap (no candidate_decisions / cross_tier_gates) is unaffected (Decision 93).
    """
    if full:
        return {
            "next_eligible": state.get("next_eligible", []),
            "strategic_pending": state.get("strategic_pending", []),
            "in_progress": state.get("in_progress", []),
            "blocked": state.get("blocked", []),
            "active_tier": state.get("active_tier"),
            "blocked_on_cd": state.get("blocked_on_cd", []),
            "ratifiable_cds": state.get("ratifiable_cds", []),
            "realized_but_pending_cds": state.get("realized_but_pending_cds", []),
            "gate_evaluations": state.get("gate_evaluations", []),
        }
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
    recs_status = report.get("recs_read_status", "ok")
    recs_status_suffix = "" if recs_status == "ok" else f" [DEGRADED: recs_read_status={recs_status}]"
    ci_rca_unresolved = len(report.get("ci_rca_unresolved_recs") or [])
    ci_rca_likely = len(report.get("ci_rca_likely_resolved_recs") or [])
    if ci_rca_unresolved or ci_rca_likely:
        ci_rca_summary = f"ci_rca_unresolved={ci_rca_unresolved} ci_rca_likely_resolved={ci_rca_likely}"
    else:
        ci_rca_summary = "ci_rca=0"
    convergence_rca_gap = report.get("convergence_rca_gap_alert")
    convergence_rca_gap_suffix = (
        f" convergence_rca_gap_alert=red_{convergence_rca_gap['red_age_hours']}h" if convergence_rca_gap else ""
    )
    return (
        f"Preflight OK -> {report_path}\n"
        f"  venv={report.get('venv_ok')} creds={report.get('creds_status')} "
        f"branch={report.get('branch')} main=({behind} behind, {ahead} ahead)\n"
        f"  open_recs={report.get('open_recommendations')} "
        f"non_automatable={report.get('non_automatable_recommendations')} "
        f"{ci_rca_summary}{recs_status_suffix}{convergence_rca_gap_suffix}\n"
        f"  Read the report file for full constraint detail."
    )


def _scan_provisional_contracts(
    contracts_dir: Path | None = None,
    metrics_provider: Callable[[Any], dict[str, Any] | None] | None = None,
) -> list[str]:
    """Return contract ids whose provisional_v0 re_ratification_trigger is met.

    Reads local docs/contracts/ files only -- no warehouse reader, no credentials.
    ``metrics_provider`` is called PER CONTRACT with the doc to obtain a metrics dict;
    when absent (default), default_provisional_metrics supplies the live days-since metric.
    """
    from scripts.contracts import load_all_contracts  # noqa: PLC0415
    from scripts.contracts_enforcement import default_provisional_metrics, evaluate_provisional_trigger  # noqa: PLC0415

    target_dir = contracts_dir if contracts_dir is not None else ROOT / "docs" / "contracts"
    due: list[str] = []
    try:
        for contract_id, doc in load_all_contracts(target_dir).items():
            metrics = metrics_provider(doc) if metrics_provider else default_provisional_metrics(doc)
            met, _ = evaluate_provisional_trigger(doc, metrics)
            if met:
                due.append(contract_id)
    except Exception:  # noqa: BLE001
        pass
    return due


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
    parser.add_argument(
        "--roadmap-detail",
        choices=["slim", "full"],
        default="slim",
        dest="roadmap_detail",
        help=(
            "Roadmap projection depth written to platform_roadmap in the preflight report. "
            "'slim' (default, used by /plan): next_eligible + strategic_pending only. "
            "'full' (used by /orient): adds in_progress, blocked, active_tier, blocked_on_cd, gate_evaluations."
        ),
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

    sys.exit(main(roadmap_detail=args.roadmap_detail))
