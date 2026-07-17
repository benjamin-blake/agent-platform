"""source=ci_rca STATUS-AWARE CHAIN + LIFECYCLE (fingerprint v2, Decision 142).

Owner-concern: fingerprint-chain resolution, the regression-vs-drop ancestry classification, the
fix-linked / timestamp-based-inactivity / flake auto-close split, and the escape-attribution
helper. Decomposed out of ci_rca_runtime.py (Decision 128 SLOC budget) -- this module replaces the
rec-2644 close-then-recur revive path (its status-flip mutator and READ-ONLY recency finder, both
now REMOVED from ci_rca_runtime.py) with a chain model where a CLOSED head is NEVER mutated: a
recurrence against a closed head is either dropped (proven stale-code rerun via git ancestry) or
filed as a brand-new REGRESSION record, never a closed->open status flip (Decision 55, citing
Decision 103's closure-proof clause -- a closed rec carries a fixed_by_sha proof; reopening it
would discard that proof without evidence it no longer holds).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Fail-closed default: a legacy closed head with no fixed_by_sha (every rec closed before this
# change; manual closures) cannot run the ancestry check -- so it always classifies as a
# REGRESSION, never a silent drop (Decision 55).
_CLASSIFY_DROP = "drop"
_CLASSIFY_REGRESSION = "regression"

# Flake escalation: a chain reaching this length is a recurring flake, not a fresh incident.
_FLAKE_CHAIN_LENGTH = 3

# Timestamp-based inactivity-close bounds (purely deterministic; Decision 103 boundary).
_INACTIVITY_WINDOW_DAYS = 30
_INACTIVITY_MIN_AGE_DAYS = 14


@dataclass(frozen=True)
class ChainRecord:
    rec_id: str
    status: str
    fixed_by_sha: Optional[str]
    last_touched: str


def _all_ci_rca_rows(profile: Optional[str] = None) -> list[dict]:
    """Named-verb read (Decision 84 I-3 / Decision 88): every source=ci_rca row (any status),
    context_v2_json parsed into "_ctx". No ad-hoc warehouse re-fetch, no caller SQL beyond the
    single structural source='ci_rca' row_filter."""
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    rows = make_reader(profile=profile).current_state("ops_recommendations", row_filter="source = 'ci_rca'") or []
    parsed: list[dict] = []
    for row in rows:
        ctx_raw = row.get("context_v2_json")
        ctx: dict = {}
        if ctx_raw:
            try:
                loaded = json.loads(ctx_raw) if isinstance(ctx_raw, str) else ctx_raw
                if isinstance(loaded, dict):
                    ctx = loaded
            except (json.JSONDecodeError, TypeError):
                ctx = {}
        parsed.append({**row, "_ctx": ctx})
    return parsed


def _rows_matching_fingerprint(fingerprint: str, profile: Optional[str] = None) -> list[dict]:
    """Every parsed source=ci_rca row whose context_v2_json.fingerprint matches."""
    return [row for row in _all_ci_rca_rows(profile=profile) if row["_ctx"].get("fingerprint") == fingerprint]


def list_open_ci_rca_recs(profile: Optional[str] = None) -> list[dict]:
    """Every OPEN source=ci_rca row (id, created_timestamp, parsed context_v2_json under "_ctx")
    -- the inactivity sweep's read surface. Named-verb read, same boundary as resolve_chain."""
    return [row for row in _all_ci_rca_rows(profile=profile) if row.get("status") == "open"]


def resolve_chain(fingerprint: str, profile: Optional[str] = None) -> list[ChainRecord]:
    """Every source=ci_rca record matching `fingerprint`, ordered NEWEST FIRST.

    Ordering key: last_updated_timestamp, falling back to created_timestamp -- mirrors the
    retired rec-2644 recency finder's ordering. An empty list means the fingerprint is
    genuinely novel (no chain exists yet).
    """
    rows = _rows_matching_fingerprint(fingerprint, profile=profile)
    records = [
        ChainRecord(
            rec_id=str(row.get("id")),
            status=str(row.get("status") or ""),
            fixed_by_sha=row["_ctx"].get("fixed_by_sha"),
            last_touched=str(row.get("last_updated_timestamp") or row.get("created_timestamp") or ""),
        )
        for row in rows
    ]
    records.sort(key=lambda r: r.last_touched, reverse=True)
    return records


def newest_open_in_chain(fingerprint: str, profile: Optional[str] = None) -> Optional[str]:
    """The chain's newest record's id IFF it is status=open, else None.

    Status-aware replacement for a scan-order-dependent "any open match" lookup: only the
    NEWEST record in a fingerprint's chain is ever eligible to absorb a recurrence."""
    chain = resolve_chain(fingerprint, profile=profile)
    if chain and chain[0].status == "open":
        return chain[0].rec_id
    return None


def closed_head_of_chain(fingerprint: str, profile: Optional[str] = None) -> Optional[ChainRecord]:
    """The chain's newest record IFF it is status=closed, else None."""
    chain = resolve_chain(fingerprint, profile=profile)
    if chain and chain[0].status == "closed":
        return chain[0]
    return None


def _is_ancestor(ancestor_sha: str, descendant_sha: str, cwd: Optional[str] = None) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    return result.returncode == 0


def current_commit_sha(cwd: Optional[str] = None) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def classify_closed_head(failing_sha: str, head: ChainRecord, cwd: Optional[str] = None) -> str:
    """'drop' when `failing_sha` is an ancestor of head.fixed_by_sha (stale-code rerun of an
    already-fixed commit); 'regression' otherwise.

    FAILS CLOSED (Decision 55): a legacy closed head with NO fixed_by_sha (every rec closed
    before this change; any manual closure) cannot run the ancestry check at all -- `git
    merge-base --is-ancestor <x> <None>` is meaningless -- so it always classifies as a
    REGRESSION rather than silently dropping a possibly-real recurrence.
    """
    if not head.fixed_by_sha:
        return _CLASSIFY_REGRESSION
    if not failing_sha:
        return _CLASSIFY_REGRESSION
    return _CLASSIFY_DROP if _is_ancestor(failing_sha, head.fixed_by_sha, cwd=cwd) else _CLASSIFY_REGRESSION


def file_regression_record(fields: dict, context_v2_json: dict, head_id: str) -> tuple[dict, dict]:
    """Mutate (fields, context_v2_json) so the CALLER's normal insert path files this as a
    REGRESSION of `head_id`, never a closed->open status flip: title gets a 'REGRESSION: '
    prefix, priority is forced to 'critical', and context_v2_json.regression_of is set.

    Returns the mutated (fields, context_v2_json) copies -- callers proceed to insert them via
    the ordinary file_rec() path (a brand-new rec row); this function performs no portal write
    itself.
    """
    new_fields = dict(fields)
    new_ctx = dict(context_v2_json)
    title = new_fields.get("title") or ""
    if not title.startswith("REGRESSION: "):
        new_fields["title"] = f"REGRESSION: {title}" if title else "REGRESSION"
    new_fields["priority"] = "Critical"
    new_ctx["regression_of"] = head_id
    return new_fields, new_ctx


def stamp_fixed_by_sha(rec_id: str, fixed_by_sha: str, profile: Optional[str] = None) -> None:
    """Record the fix commit into a (closed) rec's context_v2_json.fixed_by_sha via the portal.

    The importable helper rec-autoclose.yml calls at close time (Decision 142) --
    that SHA is what powers a future recurrence's regression-vs-drop ancestry check. Portal-only
    write (update_rec); never re-stages from a read cache.
    """
    from scripts.ops_data_portal import _fetch_rec_from_reader, update_rec  # noqa: PLC0415

    existing = _fetch_rec_from_reader(rec_id, profile=profile)
    if existing is None:
        raise RuntimeError(f"stamp_fixed_by_sha: {rec_id} does not exist in the current projection.")
    ctx_raw = existing.get("context_v2_json") or "{}"
    try:
        ctx = json.loads(ctx_raw) if isinstance(ctx_raw, str) else dict(ctx_raw or {})
    except (json.JSONDecodeError, TypeError):
        ctx = {}
    ctx["fixed_by_sha"] = fixed_by_sha
    update_rec(rec_id, {"context_v2_json": json.dumps(ctx)}, profile=profile)


def check_flake_escalation(fingerprint: str, profile: Optional[str] = None) -> bool:
    """True when the fingerprint's chain has reached (or exceeds) the flake-escalation length --
    the caller should tag flaky + quarantine instead of filing another fresh critical."""
    return len(resolve_chain(fingerprint, profile=profile)) >= _FLAKE_CHAIN_LENGTH


def is_inactive(
    context_v2_json: dict,
    created_timestamp: str,
    *,
    inactivity_window_days: int = _INACTIVITY_WINDOW_DAYS,
    min_age_days: int = _INACTIVITY_MIN_AGE_DAYS,
    now: Optional[datetime] = None,
) -> bool:
    """Purely TIMESTAMP-based deterministic inactivity predicate (Decision 103 boundary: a
    recorded proof licenses a direct close, no run-history data source needed).

    True iff BOTH: (a) last_seen (falling back to created_timestamp) is older than
    `inactivity_window_days`, AND (b) the rec's created-age is >= `min_age_days`. Both bounds
    must hold -- a rec that is merely old-since-last-seen but was only just created stays open
    (the age floor guards against closing something that never had a chance to recur yet).
    """
    reference = now if now is not None else datetime.now(timezone.utc)
    last_seen_raw = context_v2_json.get("last_seen") or created_timestamp
    last_seen = _parse_ts(last_seen_raw)
    created = _parse_ts(created_timestamp)
    if last_seen is None or created is None:
        return False
    inactive_enough = (reference - last_seen) > timedelta(days=inactivity_window_days)
    old_enough = (reference - created) >= timedelta(days=min_age_days)
    return inactive_enough and old_enough


def _parse_ts(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- escape-attribution (Decision 135 selection-manifest diff) -----------------------------

_ESCAPE_NO_EDGE = "no-edge"
_ESCAPE_CAPPED = "capped"
_ESCAPE_UNKNOWN_DATA_EDGE = "unknown-data-edge"


def _nodeid_test_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def compute_escape_class(failed_nodeid: str, selection_manifest: dict) -> str:
    """Tag a post-merge full-tier failure with WHY it escaped the --pre affected-set selection
    (Decision 135's selection-manifest, diffed against the failing nodeid's test file):

    - 'capped': the test file was identified as affected but DEFERRED over the cap (present in
      manifest['deferred']) -- --pre knew about it but ran out of budget.
    - 'no-edge': the test file was never selected at all (absent from manifest['selected']) --
      no reverse-dependency edge connected it to the diff, so --pre had no way to know.
    - 'unknown-data-edge': the test file WAS selected (and should have run under --pre) but
      still failed post-merge -- an escape --pre's channels could not explain (e.g. a data-edge
      dependency the precise quoted-token match did not catch, or a genuine environment
      difference); flagged for manual review rather than silently assumed benign.
    """
    test_file = _nodeid_test_file(failed_nodeid)
    deferred = set(selection_manifest.get("deferred", []))
    if test_file in deferred:
        return _ESCAPE_CAPPED
    selected = set(selection_manifest.get("selected", []))
    if test_file not in selected:
        return _ESCAPE_NO_EDGE
    return _ESCAPE_UNKNOWN_DATA_EDGE
