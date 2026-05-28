#!/usr/bin/env python3
"""Scan SESSION_LOG.md for North Star alignment patterns and momentum scoring.

Informational only -- exits 0 always.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.s3_log_store import append_jsonl

ROOT = Path(__file__).parent.parent
JSONL_LOG = ROOT / "logs" / ".north-star-log.jsonl"

CATEGORIES: dict[str, str] = {
    "feature": r"feature|add|implement|creat|new",
    "fix": r"fix|bug|patch|resolv|correct",
    "refactor": r"refactor|cleanup|simplif|restructur",
    "docs": r"doc|readme|comment|changelog|architecture",
    "infra": r"infra|workflow|meta|agent|prompt|script|ci|pipeline|tooling|monitor",
}


def parse_session_log(content: str, cutoff_days: int = 30) -> list[str]:
    cutoff = datetime.now() - timedelta(days=cutoff_days)
    entry_pattern = re.compile(r"## \[(\d{4}-\d{2}-\d{2})\].*?(?=## \[|\Z)", re.DOTALL)
    recent: list[str] = []
    for match in entry_pattern.finditer(content):
        try:
            entry_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if entry_date >= cutoff:
                recent.append(match.group(0))
        except ValueError:
            pass
    return recent


def categorise_session(entry: str) -> str:
    done_match = re.search(r"\*\*Done:\*\*\s*(.+)", entry)
    if not done_match:
        return "other"
    done_line = done_match.group(1).lower()
    for category, pattern in CATEGORIES.items():
        if re.search(pattern, done_line):
            return category
    return "other"


def main() -> None:
    session_log_path = ROOT / "docs" / "SESSION_LOG.md"
    if not session_log_path.exists():
        print("SESSION_LOG.md not found. Skipping North Star tracker.")
        sys.exit(0)

    content = session_log_path.read_text(encoding="utf-8")
    recent_entries = parse_session_log(content)

    counts: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    counts["other"] = 0

    for entry in recent_entries:
        cat = categorise_session(entry)
        counts[cat] = counts.get(cat, 0) + 1

    total = len(recent_entries)
    productivity = counts["feature"] + counts["fix"]
    momentum = round((productivity / total) * 100) if total else 0
    infra_ratio = round((counts["infra"] / total) * 100) if total else 0

    print()
    print("=== North Star Tracker (Last 30 Days) ===")
    print(f"Total sessions : {total}")
    print(f"  Feature      : {counts['feature']}")
    print(f"  Fix          : {counts['fix']}")
    print(f"  Refactor     : {counts['refactor']}")
    print(f"  Docs         : {counts['docs']}")
    print(f"  Infra / Meta : {counts['infra']}")
    print(f"  Other        : {counts['other']}")
    print()
    print(f"North Star momentum : {momentum}% (feature + fix sessions / total)")

    if infra_ratio > 40:
        print()
        print(f"WARN - Infra/Meta sessions are {infra_ratio}% of recent total (threshold: 40%).")
        print("       Risk: meta-work is crowding out product work toward the North Star.")
    else:
        print(f"OK   - Infra/Meta ratio {infra_ratio}% is within the 40% threshold.")

    print("=========================================")
    print()

    # Append JSONL record for trending
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "period_days": 30,
        "sessions_total": total,
        "feature_count": counts["feature"],
        "fix_count": counts["fix"],
        "infra_count": counts["infra"],
        "momentum_pct": momentum,
        "infra_ratio_pct": infra_ratio,
    }
    JSONL_LOG.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(".north-star-log.jsonl", record)

    sys.exit(0)


if __name__ == "__main__":
    main()
