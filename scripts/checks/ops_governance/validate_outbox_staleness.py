"""Ops outbox staleness warning (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_outbox_staleness", owner="platform")
def validate_outbox_staleness(failed: list[str]) -> None:
    """Warn if ops outbox has files older than 24 hours."""
    print("\n=== Ops outbox staleness check ===")
    outbox_dir = _common.ROOT / "logs" / ".ops-outbox"
    if not outbox_dir.exists():
        print("  No outbox directory -- OK")
        return
    import time

    now = time.time()
    stale_count = 0
    for table_dir in outbox_dir.iterdir():
        if not table_dir.is_dir():
            continue
        for f in table_dir.glob("*.jsonl"):
            age_hours = (now - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_count += 1
    if stale_count > 0:
        msg = f"  WARNING: {stale_count} outbox entries older than 24h -- run: python -m scripts.sync.ops sync"
        print(msg)
        # Warning only, not a hard failure (SSO may be legitimately unavailable).
    else:
        total = sum(1 for _ in outbox_dir.rglob("*.jsonl"))
        print(f"  {total} outbox entries, none stale -- OK")
