"""Pure commit-trailer parser for Resolves: rec-NNNN trailer lines.

No I/O.  Import and call parse_resolves_trailer(message) -> list[str].
"""

from __future__ import annotations

import re

_TRAILER_RE = re.compile(r"^resolves\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TOKEN_RE = re.compile(r"\brec-\d+\b", re.IGNORECASE)


def parse_resolves_trailer(message: str) -> list[str]:
    """Return a deduplicated list of rec-<digits> ids from Resolves: trailers.

    Handles comma- or space-separated lists, is case-insensitive on the
    keyword and the rec- token, and ignores malformed tokens (anything not
    matching rec-<digits>).

    Args:
        message: A git commit message body (may contain multiple lines).

    Returns:
        Deduplicated list of lowercase rec-<digits> ids in first-seen order.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for match in _TRAILER_RE.finditer(message):
        for token in _TOKEN_RE.findall(match.group(1)):
            normalised = token.lower()
            if normalised not in seen:
                seen.add(normalised)
                ids.append(normalised)
    return ids
