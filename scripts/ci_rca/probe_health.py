"""CI-RCA sustained low-confidence RCA rate sensor (T1.13 c12(i)).

Detects when a sustained share of source=ci_rca recs self-rate rca_confidence low or
undetermined (undetermined mirrored from evidence_bundle_ref.earliest_viable_gate; low is the
agent's own confidence rating) and files a deduped source=ci_rca_probe_health rec so the
self-improving loop cannot silently accumulate unsound RCA output unnoticed.

Mirrors scripts/convergence_health/escalate.py's idempotent escalation pattern (file/update/close
exactly one rec per episode). Reads ONLY the warm recommendation cache injected by the
caller (Decision 88 -- zero new reader egress); writes ONLY via scripts.ops_data_portal
(Decision 84 -- the warm cache is a read source, never a write source). Unlike
convergence_health._fetch_open_recs, this module never constructs a DuckLake reader --
open_recs must be supplied by the caller (the preflight warm cache).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

ABSTENTION_RATE_THRESHOLD: float = 0.3
ABSTENTION_MIN_SAMPLE: int = 5
DEFAULT_WINDOW_DAYS: int = 14


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _parse_ts_utc(ts: str) -> Optional[datetime]:
    """Parse an ISO-like timestamp string into a UTC-aware datetime, or None on failure."""
    ts = (ts or "").strip()
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


def _row_ts(row: dict, field: str = "created_timestamp") -> Optional[datetime]:
    """Parse a row timestamp field (ISO string or datetime) into a UTC-aware datetime, or None."""
    val = row.get(field)
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if hasattr(val, "isoformat"):
        try:
            return datetime.fromisoformat(val.isoformat()).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    return _parse_ts_utc(str(val))


def _row_rca_confidence(row: dict) -> Optional[str]:
    """Extract context_v2_json.rca_confidence from a warm-cache row, or None if absent/malformed."""
    import json  # noqa: PLC0415

    ctx_raw = row.get("context_v2_json") or ""
    if not ctx_raw:
        return None
    try:
        ctx = json.loads(ctx_raw)
    except (TypeError, ValueError):
        return None
    return ctx.get("rca_confidence")


# ---------------------------------------------------------------------------
# Abstention rate
# ---------------------------------------------------------------------------


def compute_abstention_rate(
    cache_rows: list[dict],
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: Optional[datetime] = None,
) -> tuple[int, int, float]:
    """Return (undetermined_count, total_count, rate) for source=ci_rca recs in the trailing window,
    counting rca_confidence in {low, undetermined} -- a self-rated-low-confidence RCA is not sound
    either, not just a literal abstention.

    Counts every source=ci_rca row created within the trailing window_days, regardless of status
    (open/closed) -- this counts the recorded classification at filing time, not the rec's current
    lifecycle state. rate is 0.0 when total_count is 0 (zero-total guard).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    undetermined_count = 0
    total_count = 0
    for row in cache_rows:
        if row.get("source") != "ci_rca":
            continue
        ts = _row_ts(row)
        if ts is None or ts < cutoff:
            continue
        total_count += 1
        if _row_rca_confidence(row) in ("low", "undetermined"):
            undetermined_count += 1

    rate = (undetermined_count / total_count) if total_count else 0.0
    return undetermined_count, total_count, rate


# ---------------------------------------------------------------------------
# Escalation decision (pure; identical truth table to convergence_health.escalation_action)
# ---------------------------------------------------------------------------


def find_open_probe_health_rec(rows: list[dict]) -> Optional[dict]:
    """Return the first open source=ci_rca_probe_health rec from a list of recs, or None."""
    for rec in rows:
        if rec.get("source") == "ci_rca_probe_health" and rec.get("status") == "open":
            return rec
    return None


def escalation_action(over_threshold: bool, open_rec_exists: bool) -> str:
    """Return the action to take given abstention-rate state and existing-rec state.

    Returns:
        "file"   -- new rec should be filed (over threshold, no open rec yet)
        "update" -- existing open rec should be updated (still over threshold)
        "close"  -- existing open rec should be closed (under threshold)
        "none"   -- nothing to do (under threshold, no open rec)
    """
    if over_threshold and not open_rec_exists:
        return "file"
    if over_threshold and open_rec_exists:
        return "update"
    if not over_threshold and open_rec_exists:
        return "close"
    return "none"


def _build_context(undetermined_count: int, total_count: int, rate: float, window_days: int) -> str:
    return (
        f"{undetermined_count}/{total_count} ({rate:.0%}) source=ci_rca recs filed in the trailing "
        f"{window_days} days self-rated rca_confidence low or undetermined, at or above the "
        f"{ABSTENTION_RATE_THRESHOLD:.0%} escalation threshold. A sustained low-confidence rate means a "
        "meaningful share of recent RCA output is not sound -- treat each flagged rec as advisory, not "
        "verified, until reviewed (see the CI-RCA Abstention Review preflight section). This is not by "
        "itself proof of a deterministic evidence-probe defect: review the flagged recs' individual "
        "proximate_cause / detection_gap fields for a common failure shape (a missing log field, a new CI "
        "step the probe doesn't parse, genuinely ambiguous evidence) before assuming the probe itself is "
        "broken. This rec closes automatically once the rate returns under threshold (escalate() runs the "
        "close branch on the next session preflight tick)."
    )


def _build_rec_fields(undetermined_count: int, total_count: int, rate: float, window_days: int) -> dict[str, Any]:
    return {
        "title": "CI-RCA sustained low-confidence/undetermined RCA rate -- review flagged recs before trusting them",
        "file": "scripts/ci_rca/probe_health.py",
        "status": "open",
        "source": "ci_rca_probe_health",
        "priority": "High",
        "effort": "M",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_context(undetermined_count, total_count, rate, window_days),
        "acceptance": "bin/venv-python -m scripts.ci_rca.probe_health --assert-clear",
    }


def escalate(
    undetermined_count: int,
    total_count: int,
    rate: float,
    open_recs: list[dict],
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    threshold: float = ABSTENTION_RATE_THRESHOLD,
    min_sample: int = ABSTENTION_MIN_SAMPLE,
    window_days: int = DEFAULT_WINDOW_DAYS,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent escalation: file/update/close exactly one ci_rca_probe_health rec per episode.

    Args:
        undetermined_count, total_count, rate: output of compute_abstention_rate.
        open_recs:     REQUIRED caller-supplied list of open recs (the warm preflight cache).
                       This function never constructs a DuckLake reader -- the critical divergence
                       from convergence_health._fetch_open_recs's live make_reader() fallback
                       (Decision 88: zero new reader egress).
        portal_caller: Injected callable(action, fields) for testability. When None, uses
                       scripts.ops_data_portal.file_rec / update_rec directly.
        threshold:     Abstention-rate threshold triggering escalation.
        min_sample:    Minimum total_count required before over_threshold can be True (avoids
                       escalating on a single early sample).
        window_days:   Trailing window used in the rec context/acceptance text.
        profile:       AWS profile for the portal.

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped", "rec_id": str|None}
    """
    existing = find_open_probe_health_rec(open_recs)
    open_rec_exists = existing is not None
    over_threshold = total_count >= min_sample and rate >= threshold

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = _build_rec_fields(undetermined_count, total_count, rate, window_days)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = {"context": _build_context(undetermined_count, total_count, rate, window_days)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = {
            "status": "closed",
            "resolution": (
                f"Abstention rate returned to {rate:.0%} (below the {threshold:.0%} threshold); probe-health episode resolved."
            ),
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}


# ---------------------------------------------------------------------------
# Exit-code CLI (Decision 103 relevance oracle): credential-free, reads only the local
# recommendations cache -- never constructs a DuckLake reader (mirrors the module docstring's
# zero-new-reader-egress contract).
# ---------------------------------------------------------------------------


def assert_clear_exit_code(
    cache_rows: list[dict],
    threshold: float = ABSTENTION_RATE_THRESHOLD,
    min_sample: int = ABSTENTION_MIN_SAMPLE,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: Optional[datetime] = None,
) -> int:
    """Return 0 when the abstention rate is below threshold (clear), 1 while it holds."""
    _undetermined_count, total_count, rate = compute_abstention_rate(cache_rows, window_days=window_days, now=now)
    over_threshold = total_count >= min_sample and rate >= threshold
    return 1 if over_threshold else 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CI-RCA probe-health exit-code CLI.")
    parser.add_argument(
        "--assert-clear",
        action="store_true",
        help="Exit 0 if the abstention rate is below threshold, non-zero while it holds. "
        "Reads only the local recommendations cache; no AWS credentials required.",
    )
    args = parser.parse_args(argv)

    if args.assert_clear:
        from scripts.executor.jsonl_store import RECS_JSONL  # noqa: PLC0415

        cache_rows: list[dict] = []
        if RECS_JSONL.exists():
            for line in RECS_JSONL.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    cache_rows.append(json.loads(line))
        return assert_clear_exit_code(cache_rows)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
