"""Constants and helpers shared by the contracts checks within this package only."""

from __future__ import annotations

import importlib.util
import sys

from scripts.checks import _common


def _load_prompt_compliance():
    """Lazy-load prompt_compliance to avoid import-time subprocess calls."""
    compliance_path = _common.ROOT / "scripts" / "prompt_compliance.py"
    if not compliance_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("prompt_compliance", compliance_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    # Ensure repo root is in sys.path so intra-package imports resolve
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    return mod
