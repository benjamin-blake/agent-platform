"""Parser for ci-rca agent filing signal.

Reads a `claude -p --output-format json` transcript file and extracts the
rec id from the agent's terminal `FILED: rec-NNN` marker. Never matches a
bare rec-NNN mention -- only the explicit marker counts as a real filing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Single ordered scan so the LAST marker wins (honours the "multiple markers -> last"
# contract). The `none` alternative is case-insensitive; rec ids are lowercase by the
# agent contract (file_rec emits lowercase ids), so rec matching stays case-sensitive.
_MARKER_PATTERN = re.compile(r"^[ \t]*FILED:[ \t]*(rec-\d+|[Nn][Oo][Nn][Ee])[ \t]*$", re.MULTILINE)


def extract_filed_rec_id(output_path: str | Path) -> str | None:
    """Return the rec id from the FILED: marker, or None if not found.

    Tries to parse the file as a JSON envelope (claude -p --output-format json)
    and extracts text from the 'result' field. Falls back to raw text on parse
    failure so stderr-polluted output is still searchable.

    Scans all FILED: markers in document order and returns the LAST one. A
    trailing `FILED: none` (or no marker at all) yields None; an earlier
    `FILED: none` does NOT suppress a later `FILED: rec-NNN`. Never matches a
    bare rec-NNN substring outside the marker.
    """
    path = Path(output_path)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    text = _extract_text(raw)

    matches = _MARKER_PATTERN.findall(text)
    if not matches:
        return None
    last = matches[-1]
    return None if last.lower() == "none" else last


def _extract_text(raw: str) -> str:
    """Try to extract 'result' string from JSON envelope; fall back to raw."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, str) and result:
            return result
    return raw


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ci_rca_filing.py <output_path>", file=sys.stderr)
        sys.exit(1)

    rec_id = extract_filed_rec_id(sys.argv[1])
    if rec_id is None:
        print("No FILED: rec-NNN marker found in output", file=sys.stderr)
        sys.exit(1)

    print(rec_id)


if __name__ == "__main__":
    main()
