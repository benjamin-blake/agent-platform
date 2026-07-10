"""Context-document and health concern for session_preflight."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.preflight import _common


def parse_last_session() -> str:
    """Return the most recent session header from SESSION_LOG.md, or empty string."""
    if not _common.SESSION_LOG_FILE.exists():
        return ""
    content = _common.SESSION_LOG_FILE.read_text(encoding="utf-8")
    matches = re.findall(r"## \[\d{4}-\d{2}-\d{2}\][^\n]*", content)
    return matches[-1] if matches else ""


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
    if _common.ROADMAP_FILE.exists():
        content = _common.ROADMAP_FILE.read_text(encoding="utf-8")
        # Look for "## Phase X.Y: ..." headers that are not completed/archived
        phase_matches = re.findall(r"^## (Phase [^\n]+)", content, re.MULTILINE)
        if phase_matches:
            roadmap_phase = phase_matches[0].strip()

    # open_decisions_count: count ## Decision headers not marked Decided/Resolved/Closed
    open_decisions_count = 0
    if _common.DECISIONS_FILE.exists():
        content = _common.DECISIONS_FILE.read_text(encoding="utf-8")
        decision_headers = re.findall(r"^## Decision \d+[^\n]*", content, re.MULTILINE)
        for header in decision_headers:
            if not re.search(r"\(Decided\)|\(Resolved\)|\(Closed\)|\(Done\)", header, re.IGNORECASE):
                open_decisions_count += 1

    # recent_sessions: last 5 session entries from SESSION_LOG.md
    recent_sessions: list[str] = []
    if _common.SESSION_LOG_FILE.exists():
        content = _common.SESSION_LOG_FILE.read_text(encoding="utf-8")
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
    if _common.SESSION_LOG_FILE.exists():
        content = _common.SESSION_LOG_FILE.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc)
        cutoff = now.replace(tzinfo=timezone.utc)
        date_matches = re.finditer(r"## \[(\d{4}-\d{2}-\d{2})\]", content)
        for match in date_matches:
            try:
                session_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (cutoff - session_date).days
                if age_days <= _common.STRATEGIC_REVIEW_LOOKBACK_DAYS:
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
            recommendations_count = len(_common._make_reader().named("open_recs"))
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
    dq_dir = _common.ROOT / "config" / "data_quality"
    last_run_file = _common.ROOT / "logs" / "debug" / "dq-latest.json"

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


def _check_endstate_drift() -> dict:
    """Advisory drift check: compare the sha256 fingerprint stamped in PROJECT_CONTEXT.md
    against the current sha256 of the sorted ROADMAP-PLATFORM.yaml tier_item ID set.

    Returns a dict {stale, synthesized_hash, current_hash, new_ids}.
    Fail-open: any parse/IO error returns a non-stale result with a soft note.
    Never raises, never changes the preflight exit code.
    """
    try:
        import yaml  # noqa: PLC0415

        context_text = (_common.ROOT / "docs" / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
        stamp_match = re.search(r"roadmap_tier_id_set sha256:\s*([a-f0-9]{64})", context_text)
        if not stamp_match:
            return {"stale": False, "synthesized_hash": None, "current_hash": None, "new_ids": [], "note": "stamp absent"}
        stamped_hash = stamp_match.group(1)

        roadmap = yaml.safe_load((_common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
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
                    cwd=str(_common.ROOT),
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

    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
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
