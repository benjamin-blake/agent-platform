"""CI-RCA back-validation sensor (T1.13 c12(iii)).

Detects when a preventive_action claimed by a CLOSED source=ci_rca rec did not hold: a
NEW OPEN source=ci_rca rec recurs on the same file. Surfaces the pairing for /plan
cross-check -- Decision 55 (surfacing-only, never remediates) and Decision 57 (control-plane
loop-closure: "proof a fix reduced the failure mode").

Reads ONLY the warm recommendation cache injected by the caller (Decision 88 -- zero new
reader egress); mirrors scripts/ci_rca_probe_health.py's structure and never constructs a
DuckLake reader.

Match key is FILE-ONLY (rec.file) plus the closed prior rec carrying a non-empty
preventive_action -- the roadmap c12(iii) "failed_check + failure_category (bundle-derived)"
match is a heavier heuristic, deferred until a failure_category field lands in
context_v2_json (a c9-style enrichment). File-only matching over-pairs on high-churn files
(e.g. scripts/validate.py); callers (/plan) MUST treat flags as CANDIDATES only, never a
confirmed regression or an automatic action.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_WINDOW_DAYS: int = 14


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


def _row_context_v2(row: dict) -> dict:
    """Parse context_v2_json from a warm-cache row; return {} if absent/malformed/non-dict."""
    ctx_raw = row.get("context_v2_json") or ""
    if not ctx_raw:
        return {}
    try:
        ctx = json.loads(ctx_raw)
    except (TypeError, ValueError):
        return {}
    return ctx if isinstance(ctx, dict) else {}


def find_preventive_regressions(
    cache_rows: list[dict],
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Flag OPEN source=ci_rca recs recurring on a file whose prior CLOSED source=ci_rca rec
    on the same file claimed a preventive_action (T1.13 c12(iii)).

    The window_days filter applies to the NEW (open, recurring) rec's created_timestamp --
    a preventive_action claimed further back than the window still counts as "did not hold"
    when the regression itself is recent.

    Args:
        cache_rows: Warm recommendation cache rows (caller-injected; never fetched here).
        window_days: Trailing window over the open rec's created_timestamp.
        now: Injected clock for deterministic tests; defaults to the real UTC now.

    Returns:
        A list of {new_rec_id, prior_rec_id, file, preventive_action_excerpt} dicts, one per
        matched pair, newest-open-rec-first. Surfacing-only (Decision 55): never files,
        updates, or closes a rec. Match key is FILE-ONLY -- a materially weaker heuristic
        than the roadmap's "failed_check + failure_category" spec (see module docstring) --
        so callers MUST treat these as candidates, not confirmed regressions.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    open_ci_rca: list[dict] = []
    closed_with_prevention: dict[str, list[dict]] = {}
    for row in cache_rows:
        if row.get("source") != "ci_rca":
            continue
        file_ = row.get("file") or ""
        if not file_:
            continue
        if row.get("status") == "open":
            ts = _row_ts(row)
            if ts is None or ts < cutoff:
                continue
            open_ci_rca.append(row)
        elif row.get("status") == "closed":
            ctx = _row_context_v2(row)
            if ctx.get("preventive_action"):
                closed_with_prevention.setdefault(file_, []).append(row)

    open_ci_rca.sort(key=lambda r: _row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    flags: list[dict] = []
    for new_row in open_ci_rca:
        file_ = new_row.get("file") or ""
        priors = closed_with_prevention.get(file_)
        if not priors:
            continue
        prior = max(
            priors,
            key=lambda r: _row_ts(r, field="last_updated_timestamp") or datetime.min.replace(tzinfo=timezone.utc),
        )
        preventive_action = _row_context_v2(prior).get("preventive_action", "")
        flags.append(
            {
                "new_rec_id": new_row.get("id", ""),
                "prior_rec_id": prior.get("id", ""),
                "file": file_,
                "preventive_action_excerpt": preventive_action[:200],
            }
        )
    return flags
