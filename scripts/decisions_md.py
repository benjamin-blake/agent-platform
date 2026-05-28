"""Utilities for parsing DECISIONS.md and reading local JSONL log files.

Extracted from backfill_ops_tables.py (deleted in dq-ops-rec-enforcement).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DECISIONS_MD_PATHS = [
    _REPO_ROOT / "docs" / "DECISIONS.md",
    _REPO_ROOT / "docs" / "DECISIONS_ARCHIVE.md",
]

_DECISION_HEADING_RE = re.compile(
    r"^#{2,3}\s+Decision\s+(\d+):\s*(.+)$",
    re.MULTILINE,
)


def _extract_section(text: str, *keys: str) -> str:
    for key in keys:
        single = re.search(
            rf"\*\*{re.escape(key)}:\*\*\s*(.+?)(?=\n\*\*|\n---|\.?$)",
            text,
            re.DOTALL,
        )
        if single:
            return single.group(1).strip()
    return ""


def _extract_multiline_section(text: str, *keys: str) -> str:
    for key in keys:
        pat = re.compile(
            rf"\*\*{re.escape(key)}:\*\*\s*\n(.*?)(?=\n\*\*\w|\n---|\.?\Z)",
            re.DOTALL,
        )
        m = pat.search(text)
        if m:
            return m.group(1).strip()
        inline = re.search(
            rf"\*\*{re.escape(key)}:\*\*\s*(.+?)(?=\n\*\*\w|\n---|\.?\Z)",
            text,
            re.DOTALL,
        )
        if inline:
            return inline.group(1).strip()
    return ""


def _extract_related_decisions(text: str) -> list[int]:
    m = re.search(r"\*\*Related:\*\*(.+?)(?=\n\*\*|\n---|\Z)", text, re.DOTALL)
    if not m:
        return []
    return [int(n) for n in re.findall(r"Decision\s+(\d+)", m.group(1))]


def _extract_decided_date(text: str) -> str:
    date_m = re.search(r"\*\*Date:\*\*\s*(.+)", text)
    if date_m:
        return date_m.group(1).strip()
    status_m = re.search(r"\*\*Status:\*\*.*?--\s*(.+)", text)
    if status_m:
        return status_m.group(1).strip()
    return ""


def parse_decisions_md(paths: Optional[list[Path]] = None) -> list[dict]:
    """Parse DECISIONS.md (and optionally DECISIONS_ARCHIVE.md) into a list of dicts."""
    if paths is None:
        paths = _DECISIONS_MD_PATHS

    now_iso = datetime.now(timezone.utc).isoformat()
    seen: dict[int, dict] = {}

    for md_path in paths:
        if not md_path.exists():
            continue
        content = md_path.read_text(encoding="utf-8", errors="replace")
        headings = list(_DECISION_HEADING_RE.finditer(content))
        for i, m in enumerate(headings):
            decision_id = int(m.group(1))
            if decision_id in seen:
                continue
            raw_title = m.group(2).strip()
            title = re.sub(r"\s*\(.*?\)\s*$", "", raw_title).strip()
            block_start = m.end()
            block_end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            block = content[block_start:block_end]
            status_m = re.search(r"\*\*Status:\*\*\s*(.+)", block)
            if status_m:
                status = status_m.group(1).strip().split("--")[0].strip()
            else:
                paren_m = re.search(r"\(([^)]+)\)\s*$", raw_title)
                status = paren_m.group(1).strip() if paren_m else ""
            seen[decision_id] = {
                "decision_id": decision_id,
                "title": title,
                "status": status,
                "problem": _extract_multiline_section(block, "Problem", "Trigger"),
                "decision_text": _extract_multiline_section(block, "Decision"),
                "context": _extract_multiline_section(block, "Rationale", "Key details", "Context"),
                "decided_date": _extract_decided_date(block),
                "related_decisions": _extract_related_decisions(block),
                "created_timestamp": now_iso,
                "last_updated_timestamp": now_iso,
            }

    return sorted(seen.values(), key=lambda r: r["decision_id"])


def read_jsonl(path: Path) -> list[dict]:
    """Read valid JSONL entries from path, skipping blanks, comments, and schema lines."""
    if not path.exists():
        print(f"  WARNING: {path} not found -- skipping", file=sys.stderr)
        return []
    entries: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith('{"_schema'):
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"  WARNING: skipping malformed JSON at {path}:{lineno}: {exc}", file=sys.stderr)
    return entries
