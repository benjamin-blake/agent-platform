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
import json
import os
import re
import subprocess
import sys
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


def _count_recommendations_reader() -> tuple[int, int, int, list[dict]] | str:
    """Return open recommendation counts from the DuckLake reader.

    Returns the tally tuple on success, or the string "reader_unreachable" on any
    reader failure (Decision 55 / Decision 81 cl.7: loud degraded signal, never a
    false zero; no Athena fallback on the ducklake backend).
    """
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


def read_priority_queue(max_items: int = 5, creds_status: str = "ok") -> list[dict]:
    """Read the priority queue via the priority_queue_current read verb (DuckLake reader).

    Decision 70: the verb's correlated subquery returns ALL entries of the latest
    curator run -- the generic latest-per-key current projection would silently
    change these semantics.

    When *creds_status* is not "ok" credentials are unavailable: fall back to the
    local read-cache with a staleness warning (empty-with-warning when absent; never
    crash -- T2.5 graceful-degradation requirement).

    When credentials ARE "ok" and the verb fails, that is a genuine infrastructure
    fault -- hard-exit with code 1 rather than masking it (Decision 60).

    Returns a list of dicts shaped as {rank, rec_id, rationale, north_star_impact}.
    Returns [] if the queue is empty.
    """
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


def _fetch_ci_rca_recs() -> list[dict]:
    """Return up to 5 open CI-RCA recs from the DuckLake reader.

    Returns [] with a loud warning on reader failure (Decision 55 / Decision 81 cl.7:
    no Athena fallback; loud degraded signal).
    """
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


def _check_non_automatable_softcap(non_auto_count: int) -> bool:
    """Return True when non-automatable rec count exceeds the soft cap."""
    return non_auto_count > _NON_AUTOMATABLE_SOFTCAP


def _fetch_ci_rca_recs_since(ts: str) -> list[dict]:
    """Return ci_rca recs created after *ts* from the DuckLake reader.

    Returns [] on any failure (Decision 81 cl.7: no Athena fallback).
    """
    try:
        return _make_reader().named("ci_rca_since", since_ts=ts)
    except Exception:  # noqa: BLE001
        pass
    return []


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
        rows = _make_reader().named("forward_fix_recursion", since_ts=cutoff)
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

    return None


def _check_budget_bypass_alert() -> dict | None:
    """Return alert dict when >= 3 budget_bypass recs were filed in the last 7 days.

    Returns None when count < 3 or the warehouse is unreachable.
    """
    try:
        rows = _make_reader().named("budget_bypass_recent")
        if rows is not None:
            if len(rows) < 3:
                return None
            return {"count": len(rows), "entries": rows}
    except Exception:  # noqa: BLE001
        pass

    return None


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


def correlate_ci_rca_with_main(recs: list[dict], commits: list[dict]) -> dict[str, list[dict]]:
    """Classify open ci_rca recs as LIKELY-RESOLVED or UNRESOLVED.

    A rec is LIKELY-RESOLVED when any commit on origin/main whose date is
    AFTER the rec's created_timestamp either:
      - modified the rec's ``file`` field (path prefix match), or
      - mentions the rec's ``id`` in its subject line.

    Recs whose file/id cannot be correlated with any newer main commit retain
    the HARD BLOCK designation (UNRESOLVED).

    Args:
        recs:    Open ci_rca recs from _fetch_ci_rca_recs().
        commits: Recent main commits from _get_recent_main_commits().

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

            # Only consider commits that landed AFTER the rec was created.
            if rec_created_dt is not None and commit_dt is not None:
                if commit_dt <= rec_created_dt:
                    continue

            # Check subject for explicit rec id mention.
            subject_lower = (commit.get("subject") or "").lower()
            if rec_id and rec_id in subject_lower:
                correlated = True
                break

            # Check changed files for the rec's source file.
            if rec_file:
                for changed in commit.get("files") or []:
                    if rec_file in changed or changed in rec_file:
                        correlated = True
                        break
            if correlated:
                break

        if correlated:
            likely_resolved.append(rec)
        else:
            unresolved.append(rec)

    return {"likely_resolved": likely_resolved, "unresolved": unresolved}


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

    # recommendations_count: reader-only via the open_recs verb (Decision 84 I-3)
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
    """Return the max decision last_updated_timestamp via the decisions_max_updated verb, or None."""
    try:
        rows = _make_reader(table="ops_decisions").named("decisions_max_updated")
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    ts = rows[0].get("ts") or ""
    return str(ts) if ts else None


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

    # Rebuild the local read cache from the warehouse (best-effort): all migrated
    # tables via the DuckLake reader (Decision 84 I-1; no fallback).
    try:
        recommendation_sync = _sync_ops_pull()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"WARNING: sync_ops.pull failed: {exc}", file=sys.stderr)
        recommendation_sync = {}

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
                    f"Ops sync: drained {drained} outbox entries, pulled {pulled} rows from the warehouse",
                    file=sys.stderr,
                )
        except Exception:  # noqa: BLE001
            pass  # sync is best-effort

    last_session = parse_last_session()
    _rec_result = _count_recommendations_reader()
    recs_read_status: str
    if _rec_result == "reader_unreachable":
        recs_read_status = "reader_unreachable"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = 0, 0, 0, []
    else:
        recs_read_status = "ok"
        open_recommendations, aging_recommendations, non_automatable_count, non_automatable_details = _rec_result  # type: ignore[misc]
    ci_rca_recs = _fetch_ci_rca_recs()
    recent_main_commits = _get_recent_main_commits()
    correlation = correlate_ci_rca_with_main(ci_rca_recs, recent_main_commits)
    if ci_rca_recs:
        print_ci_rca_recs(ci_rca_recs, correlation=correlation)
    priority_queue = read_priority_queue(creds_status=creds_status)
    print_priority_queue(priority_queue)
    _print_recent_main_commits(recent_main_commits)
    if not ci_rca_recs:
        print_ci_rca_recs(ci_rca_recs, correlation=None)
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
        "priority_queue_source": "ducklake_reader" if creds_status == "ok" else "cache",
        "recs_read_status": recs_read_status,
        "ci_rca_recs": ci_rca_recs,
        "ci_rca_unresolved_recs": correlation.get("unresolved") or [],
        "ci_rca_likely_resolved_recs": correlation.get("likely_resolved") or [],
        "recent_main_commits": recent_main_commits,
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
    recs_status = report.get("recs_read_status", "ok")
    recs_status_suffix = "" if recs_status == "ok" else f" [DEGRADED: recs_read_status={recs_status}]"
    ci_rca_unresolved = len(report.get("ci_rca_unresolved_recs") or [])
    ci_rca_likely = len(report.get("ci_rca_likely_resolved_recs") or [])
    if ci_rca_unresolved or ci_rca_likely:
        ci_rca_summary = f"ci_rca_unresolved={ci_rca_unresolved} ci_rca_likely_resolved={ci_rca_likely}"
    else:
        ci_rca_summary = "ci_rca=0"
    return (
        f"Preflight OK -> {report_path}\n"
        f"  venv={report.get('venv_ok')} creds={report.get('creds_status')} "
        f"branch={report.get('branch')} main=({behind} behind, {ahead} ahead)\n"
        f"  open_recs={report.get('open_recommendations')} "
        f"non_automatable={report.get('non_automatable_recommendations')} "
        f"{ci_rca_summary}{recs_status_suffix}\n"
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
