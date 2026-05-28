"""One-time idempotent cleanup of noisy log entries.

Archives originals, then removes:
  - session-telemetry entries from agent/test + manual + 0 files_changed
  - duplicate session-telemetry entries (same rec_id + outcome within same minute)
  - duplicate retro-lite entries (same session + friction text)
"""

import argparse
import json
import shutil
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
ARCHIVE_DIR = LOGS_DIR / "archive"

TELEMETRY_FILE = LOGS_DIR / ".session-telemetry.jsonl"
RETRO_FILE = LOGS_DIR / ".retro-lite-log.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, returning a list of dicts."""
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                entries.append(json.loads(stripped))
    return entries


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    """Write entries to a JSONL file with trailing newline."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            f.write(json.dumps(entry, separators=(",", ": ")) + "\n")


def _archive(src: Path) -> bool:
    """Copy src to archive with -pre-purge suffix. Returns False if exists."""
    if not src.exists():
        return False
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / (src.stem + "-pre-purge" + src.suffix)
    if dest.exists():
        return False
    shutil.copy2(src, dest)
    return True


def _telemetry_dedup_key(entry: dict) -> str:
    """Key for minute-level deduplication of telemetry entries."""
    rec_id = entry.get("rec_id") or ""
    outcome = entry.get("outcome") or ""
    end_time = (entry.get("end_time") or "")[:16]
    return f"{rec_id}|{outcome}|{end_time}"


def _is_test_leakage(entry: dict) -> bool:
    """True if entry is agent/test noise."""
    return entry.get("branch") == "agent/test" and entry.get("workflow") == "manual" and entry.get("files_changed") == 0


def purge_telemetry(
    entries: list[dict],
) -> tuple[list[dict], int, int]:
    """Remove test leakage and minute-level duplicates.

    Returns (cleaned, leakage_count, dup_count).
    """
    leakage_removed = 0
    after_leakage: list[dict] = []
    for entry in entries:
        if _is_test_leakage(entry):
            leakage_removed += 1
        else:
            after_leakage.append(entry)

    seen: dict[str, int] = {}
    dup_indices: set[int] = set()
    for i, entry in enumerate(after_leakage):
        key = _telemetry_dedup_key(entry)
        if key in seen:
            dup_indices.add(i)
        else:
            seen[key] = i

    cleaned = [e for i, e in enumerate(after_leakage) if i not in dup_indices]
    return cleaned, leakage_removed, len(dup_indices)


def _retro_dedup_key(entry: dict) -> str:
    """Key for session+friction deduplication of retro entries."""
    session = entry.get("session") or ""
    friction = entry.get("friction") or ""
    return f"{session}|{friction}"


def purge_retro(entries: list[dict]) -> tuple[list[dict], int]:
    """Deduplicate retro-lite by (session, friction), keep earliest.

    Returns (cleaned, dup_count).
    """
    seen: dict[str, int] = {}
    dup_indices: set[int] = set()
    for i, entry in enumerate(entries):
        key = _retro_dedup_key(entry)
        if key in seen:
            dup_indices.add(i)
        else:
            seen[key] = i

    cleaned = [e for i, e in enumerate(entries) if i not in dup_indices]
    return cleaned, len(dup_indices)


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge noise from JSONL log files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without modifying files",
    )
    args = parser.parse_args()

    telemetry_entries = _read_jsonl(TELEMETRY_FILE)
    retro_entries = _read_jsonl(RETRO_FILE)

    cleaned_tel, leakage, tel_dups = purge_telemetry(telemetry_entries)
    cleaned_retro, retro_dups = purge_retro(retro_entries)

    total_removed = leakage + tel_dups + retro_dups

    if args.dry_run:
        print(f"would remove {total_removed} entries total:")
        print(f"  telemetry test leakage: {leakage}")
        print(f"  telemetry duplicates:   {tel_dups}")
        print(f"  retro-lite duplicates:  {retro_dups}")
        return

    _archive(TELEMETRY_FILE)
    _archive(RETRO_FILE)

    _write_jsonl(TELEMETRY_FILE, cleaned_tel)
    print(
        f"session-telemetry: removed {leakage} leakage"
        f" + {tel_dups} duplicates"
        f" ({len(telemetry_entries)} -> {len(cleaned_tel)})"
    )

    _write_jsonl(RETRO_FILE, cleaned_retro)
    print(f"retro-lite: removed {retro_dups} duplicates ({len(retro_entries)} -> {len(cleaned_retro)})")


if __name__ == "__main__":
    main()
