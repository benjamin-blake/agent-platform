"""Constants and helpers shared by the ci_guards checks within this package only."""

from __future__ import annotations

import sys

from scripts.checks import _common


def _ensure_root_on_path() -> bool:
    """Inject ROOT into sys.path if absent; return True if injection was performed."""
    root_str = str(_common.ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        return True
    return False
