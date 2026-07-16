"""Utilities for parsing DECISIONS.md and reading local JSONL log files.

Extracted from backfill_ops_tables.py (deleted in dq-ops-rec-enforcement).

DAF-01 parity pass (PLAN-daf-etl-parity-fidelity): raw_block + content_hash carry the full
heading-inclusive section text as a parity backstop; reversal_conditions and superseded_by
are typed extractions; the Decision-marker regex tolerates decorated markers (e.g.
"**Decision (four invariants):**"); the related-decisions extractor accepts plural
"Decisions 69/78" cites and dedupes; the decided_date Status-suffix fallback is restricted
to ISO-shaped values.
"""

from __future__ import annotations

import hashlib
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

# ISO-shaped date prefix (YYYY-MM or YYYY-MM-DD). The decided_date Status-suffix fallback is
# restricted to this shape (DAF-01 fix: dec-067's fallback previously harvested the clause
# status line "remove when reversal condition is met" as a "date").
_ISO_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?")

# Canonical inline superseded-by marker (Decision 134 clause 4 / Plan 3 will formalize this
# spelling in docs/contracts/decision-entry.yaml -- keep it EXACTLY consistent):
#   **Superseded by: Decision N**
# Best-effort tolerance for the historical band's differently-shaped marker:
#   **Superseded by:** Decision N
_SUPERSEDED_BY_RE = re.compile(
    r"\*\*Superseded by:\s*Decision\s+(\d+)\*\*"
    r"|\*\*Superseded by:\*\*\s*Decision\s+(\d+)"
)

# The decision-body marker, tolerating decorated forms (e.g. "**Decision (four invariants):**")
# per Decision 134 clause 4 / audit finding DAF-01. Never widen past "Decision" as the leading
# word -- "**Decision Required By:**" (a different, non-decision-body field used in unheaded
# candidate sections) does not collide because parse_decisions_md only walks "## Decision N:"
# headed blocks.
_DECISION_MARKER_BODY = r"Decision\b[^:]*"


def _extract_by_marker_pattern(text: str, marker_body_pattern: str) -> str:
    """Extract the text following a bold marker whose inner span matches marker_body_pattern.

    marker_body_pattern is a raw (unescaped) regex fragment for the text between "**" and
    ":**" -- e.g. re.escape("Problem") for an exact key, or r"Decision\\b[^:]*" to tolerate
    decorated markers. Tries the multiline (marker on its own line, body on following lines)
    form first, then the inline (marker and body on the same line) form.
    """
    full_marker = rf"\*\*{marker_body_pattern}:\*\*"
    multi = re.search(full_marker + r"\s*\n(.*?)(?=\n\*\*\w|\n---|\.?\Z)", text, re.DOTALL)
    if multi:
        return multi.group(1).strip()
    inline = re.search(full_marker + r"\s*(.+?)(?=\n\*\*\w|\n---|\.?\Z)", text, re.DOTALL)
    if inline:
        return inline.group(1).strip()
    return ""


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
        result = _extract_by_marker_pattern(text, re.escape(key))
        if result:
            return result
    return ""


def _extract_decision_text(text: str) -> str:
    """Extract the decision body, tolerating decorated Decision markers (DAF-01 fix)."""
    return _extract_by_marker_pattern(text, _DECISION_MARKER_BODY)


def _extract_related_decisions(text: str) -> list[int]:
    """Extract related decision numbers, deduped, preserving first-occurrence order.

    Accepts both the singular "Decision N" form and the plural "Decisions N/M" form (DAF-01
    fix -- the plural form was previously invisible to the singular-only regex, e.g.
    "Decisions 69/78" in Decision 87's Related line).
    """
    m = re.search(r"\*\*Related:\*\*(.+?)(?=\n\*\*|\n---|\Z)", text, re.DOTALL)
    if not m:
        return []
    related_text = m.group(1)
    seen: set[int] = set()
    result: list[int] = []
    for cite in re.finditer(r"Decisions?\s+(\d+(?:\s*[/,]\s*\d+)*)", related_text):
        for n_str in re.findall(r"\d+", cite.group(1)):
            n = int(n_str)
            if n not in seen:
                seen.add(n)
                result.append(n)
    return result


def _extract_decided_date(text: str) -> str:
    date_m = re.search(r"\*\*Date:\*\*\s*(.+)", text)
    if date_m:
        return date_m.group(1).strip()
    status_m = re.search(r"\*\*Status:\*\*.*?--\s*(.+)", text)
    if status_m:
        candidate = status_m.group(1).strip()
        if _ISO_DATE_PREFIX_RE.match(candidate):
            return candidate
    return ""


def _extract_superseded_by(text: str) -> str:
    """Extract a superseded-by target as 'dec-NNN', best-effort for historical prose."""
    m = _SUPERSEDED_BY_RE.search(text)
    if not m:
        return ""
    n = m.group(1) or m.group(2)
    return f"dec-{int(n):03d}"


def _iter_decision_sections(content: str) -> list[tuple[re.Match[str], str]]:
    """Yield (heading_match, raw_block) pairs for every '## Decision N:' heading, in file
    order, WITHOUT dedup or sort -- unlike parse_decisions_md, which dedupes by decision_id
    (first-wins) and sorts by id.

    raw_block is heading-inclusive: it spans from the start of the heading line through (but
    not including) the start of the next heading, or through end-of-file for the last one.
    Concatenating a file's preamble (the text before its first heading) with every raw_block
    here, in order, byte-reconstructs the source file exactly -- the invariant the
    byte-reconstruction coverage test in tests/test_decisions_md.py asserts.
    """
    headings = list(_DECISION_HEADING_RE.finditer(content))
    sections: list[tuple[re.Match[str], str]] = []
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        sections.append((m, content[m.start() : end]))
    return sections


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
        for m, full_block in _iter_decision_sections(content):
            decision_id = int(m.group(1))
            if decision_id in seen:
                continue
            raw_title = m.group(2).strip()
            title = re.sub(r"\s*\(.*?\)\s*$", "", raw_title).strip()
            body = full_block[m.end() - m.start() :]
            status_m = re.search(r"\*\*Status:\*\*\s*(.+)", body)
            if status_m:
                status = status_m.group(1).strip().split("--")[0].strip()
            else:
                paren_m = re.search(r"\(([^)]+)\)\s*$", raw_title)
                status = paren_m.group(1).strip() if paren_m else ""
            raw_block = full_block.strip()
            content_hash = hashlib.sha256(raw_block.encode("utf-8")).hexdigest()
            seen[decision_id] = {
                "decision_id": decision_id,
                "title": title,
                "status": status,
                "problem": _extract_multiline_section(body, "Problem", "Trigger"),
                "decision_text": _extract_decision_text(body),
                "context": _extract_multiline_section(body, "Rationale", "Key details", "Context"),
                "decided_date": _extract_decided_date(body),
                "related_decisions": _extract_related_decisions(body),
                "reversal_conditions": _extract_multiline_section(body, "Reversal conditions", "Reversal condition"),
                "superseded_by": _extract_superseded_by(body),
                "raw_block": raw_block,
                "content_hash": content_hash,
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
