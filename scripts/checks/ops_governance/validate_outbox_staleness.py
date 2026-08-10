"""Ops outbox staleness warning (Decision 104), hardened for retired dirs (Decision 84 I-4)."""

from __future__ import annotations

from scripts.checks import _common, registry
from src.common.outbox_retirement import is_retired_dir


@registry.register("validate_outbox_staleness", owner="platform")
def validate_outbox_staleness(failed: list[str]) -> None:
    """Hard-fail on any file in a retired-outbox dir; warn only on >24h legacy staging files."""
    print("\n=== Ops outbox staleness check ===")
    outbox_dir = _common.ROOT / "logs" / ".ops-outbox"
    if not outbox_dir.exists():
        print("  No outbox directory -- OK")
        return
    import time

    now = time.time()
    stale_count = 0
    retired_hits: list[str] = []
    for table_dir in outbox_dir.iterdir():
        if not table_dir.is_dir():
            continue
        retired = is_retired_dir(table_dir.name)
        for f in table_dir.glob("*.jsonl"):
            if retired:
                retired_hits.append(str(f))
                continue
            age_hours = (now - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_count += 1
    if retired_hits:
        for path in retired_hits:
            print(
                f"  FAIL: {path} is in a retired outbox dir (Decision 84 I-4) -- retired dirs "
                "must never hold files; remove it and re-file via the ops portal."
            )
            failed.append(f"Ops outbox staleness: retired-dir file {path}")
    if stale_count > 0:
        msg = f"  WARNING: {stale_count} outbox entries older than 24h -- run: python -m scripts.sync.ops sync"
        print(msg)
        # Legacy staging dirs: warning only, not a hard failure (SSO may be legitimately unavailable).
    if not retired_hits and stale_count == 0:
        total = sum(1 for _ in outbox_dir.rglob("*.jsonl"))
        print(f"  {total} outbox entries, none stale -- OK")
