"""CI-RCA rec derivation, fetch, print, and liveness concern for session_preflight."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

from scripts.preflight import _common


def _derive_ci_rca_open(rows: list[dict]) -> list[dict]:
    """Client-side `ci_rca_open` verb: open/in-progress ci_rca recs, newest first, capped at 5."""
    matched = [r for r in rows if r.get("source") == "ci_rca" and r.get("status") in ("open", "in_progress")]
    matched.sort(key=lambda r: _common._row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
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
    matched.sort(key=lambda r: _common._row_ts(r) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
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
    """Return ALL open source=ci_rca recs, rca_confidence=undetermined (untruncated; CIRCA-10 moved the cap to print time)."""
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
    return results


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
    cutoff = _common._parse_ts_utc(since_ts)
    if cutoff is None:
        return []
    out: list[dict] = []
    for r in rows:
        if r.get("source") != "ci_rca":
            continue
        ts = _common._row_ts(r)
        if ts is not None and ts > cutoff:
            out.append({"id": r.get("id", "")})
    return out


def _fetch_ci_rca_undetermined_recs(cache_rows: object = _common._READER_SENTINEL) -> list[dict]:
    """Return all open ci_rca recs with rca_confidence=undetermined -- from warm cache only."""
    if cache_rows is not _common._READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_undetermined_open(cache_rows)  # type: ignore[arg-type]
    return []


def print_ci_rca_undetermined_recs(recs: list[dict]) -> None:
    """Print advisory abstention-review section (CIRCA-10): displays <=5, notes overflow past 5."""
    print("\n--- CI-RCA Abstention Review (advisory; rca_confidence=undetermined) ---")
    if not recs:
        print("  (none)")
        print()
        return
    print("  Evidence bundle abstained on these recs -- review the proximate cause manually.")
    print("  Advisory only: open ci_rca recs already hard-block /plan via Decision 73 L5.")
    for rec in recs[:5]:
        rec_id = rec.get("id", "unknown")
        title = rec.get("title", "")
        priority = rec.get("priority", "")
        created = rec.get("created_timestamp", "")
        print(f"  {rec_id} [{priority}] {created}: {title}")
    if len(recs) > 5:
        print(f"  ... showing 5 of {len(recs)} open undetermined recs")
    print()


def _fetch_ci_rca_recs(cache_rows: object = _common._READER_SENTINEL) -> list[dict]:
    """Return up to 5 open CI-RCA recs -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via _derive_ci_rca_open
    (zero reader call); a supplied None means the warm-up pull failed -> [] (degraded). Omitted
    (sentinel) -> reader path (back-compat / tests). Returns [] with a loud warning on reader failure
    (Decision 55 / Decision 81 cl.7: no Athena fallback; loud degraded signal).
    """
    if cache_rows is not _common._READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_open(cache_rows)  # type: ignore[arg-type]

    _reader_exc: Exception | None = None
    try:
        return _common._make_reader().named("ci_rca_open")
    except Exception as exc:  # noqa: BLE001
        _reader_exc = exc

    print(
        f"[WARN] preflight: ci_rca recs reader unreachable ({_reader_exc}) -- CI RCA Recs "
        "section degraded (recs_read_status=reader_unreachable). No Athena fallback (Decision 81 cl.7).",
        file=sys.stderr,
    )
    return []


def _fetch_ci_rca_dispute_recs(cache_rows: object = _common._READER_SENTINEL) -> list[dict]:
    """Return up to 5 open ci_rca_evidence_dispute recs -- from the warm-pulled cache rows only.

    cache_rows (neon-egress-reduction D4 / Decision 88 egress invariant): a supplied row list is
    served via _derive_ci_rca_dispute_open (zero reader call); a supplied None means the warm-up
    pull failed -> []. Omitted (sentinel) -> [] (no new DuckLake reader named-verb for dispute recs;
    the dispute section derives from the same warm cache used by _fetch_ci_rca_recs).
    """
    if cache_rows is not _common._READER_SENTINEL:
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


def _fetch_ci_rca_recs_since(ts: str, cache_rows: object = _common._READER_SENTINEL) -> list[dict]:
    """Return ci_rca recs created after *ts* -- from the warm-pulled cache rows, else the DuckLake reader.

    cache_rows (neon-egress-reduction D4): a supplied row list is served via _derive_ci_rca_since
    (zero reader call); a supplied None -> []. Omitted (sentinel) -> reader path (back-compat).
    Returns [] on any failure (Decision 81 cl.7: no Athena fallback).
    """
    if cache_rows is not _common._READER_SENTINEL:
        return [] if cache_rows is None else _derive_ci_rca_since(cache_rows, ts)  # type: ignore[arg-type]
    try:
        return _common._make_reader().named("ci_rca_since", since_ts=ts)
    except Exception:  # noqa: BLE001
        pass
    return []


def _check_ci_rca_liveness(creds_status: str, cache_rows: object = _common._READER_SENTINEL) -> dict | None:
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


def _check_convergence_rca_gap(convergence_health: dict | None, cache_rows: object = _common._READER_SENTINEL) -> dict | None:
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
