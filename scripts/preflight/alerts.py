"""Recurrence and bypass alert concern for session_preflight."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.preflight import _common


def _derive_forward_fix_recursion(rows: list[dict], since_ts: str) -> list[dict]:
    """Client-side `forward_fix_recursion` verb: files with >=3 ci_rca recs since *since_ts*."""
    cutoff = _common._parse_ts_utc(since_ts)
    if cutoff is None:
        return []
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("source") != "ci_rca":
            continue
        ts = _common._row_ts(r)
        if ts is None or ts <= cutoff:
            continue
        counts[r.get("file") or ""] = counts.get(r.get("file") or "", 0) + 1
    return [{"file": f, "cnt": c} for f, c in counts.items() if c >= 3]


def _check_forward_fix_recursion(cache_rows: object = _common._READER_SENTINEL) -> dict | None:
    """Return alert dict when >=3 ci-rca recs targeting the same file appear in the last 24h.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_forward_fix_recursion (zero reader call); a supplied None -> degrade to None. Omitted
    (sentinel) -> reader path. Returns None when no recursion is detected or the warehouse is
    unreachable.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    if cache_rows is not _common._READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_forward_fix_recursion(cache_rows, cutoff)  # type: ignore[arg-type]
    else:
        try:
            rows = _common._make_reader().named("forward_fix_recursion", since_ts=cutoff)
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


def _derive_budget_bypass_recent(rows: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Client-side `budget_bypass_recent` verb: budget_bypass recs in the last 7 days, newest first, <=10."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=7)
    matched = []
    for r in rows:
        if r.get("source") != "budget_bypass":
            continue
        ts = _common._row_ts(r)
        if ts is not None and ts > cutoff:
            matched.append(r)
    matched.sort(key=lambda r: _common._row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [
        {"id": r.get("id", ""), "context": r.get("context", ""), "created_timestamp": r.get("created_timestamp")}
        for r in matched[:10]
    ]


def _check_budget_bypass_alert(cache_rows: object = _common._READER_SENTINEL) -> dict | None:
    """Return alert dict when >= 3 budget_bypass recs were filed in the last 7 days.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via
    _derive_budget_bypass_recent (zero reader call); a supplied None -> degrade to None. Omitted
    (sentinel) -> reader path. Returns None when count < 3 or the warehouse is unreachable.
    """
    if cache_rows is not _common._READER_SENTINEL:
        if cache_rows is None:
            return None
        rows = _derive_budget_bypass_recent(cache_rows)  # type: ignore[arg-type]
    else:
        try:
            rows = _common._make_reader().named("budget_bypass_recent")
        except Exception:  # noqa: BLE001
            return None

    if rows is None or len(rows) < 3:
        return None
    return {"count": len(rows), "entries": rows}
