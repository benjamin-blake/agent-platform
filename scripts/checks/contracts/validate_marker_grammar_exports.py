"""Marker-grammar binding-surface parity check (rec-3059 first-wave enforcer build).

Asserts scripts/checks/_marker_guard.py's __all__ equals docs/contracts/marker-grammar.yaml's
binding_surface.exports -- promotes the routed debt record (evaluator.none_grandfathered) to a
machine-enforced check that catches the shared raise-marker mechanism's public surface drifting
from what the contract documents.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_NAME = "marker-grammar.yaml"


def _dig(data: object, *keys: str) -> object:
    """Walk nested mappings by `keys`; returns None the moment any level is not a mapping."""
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


@registry.register("validate_marker_grammar_exports", owner="platform")
def validate_marker_grammar_exports(failed: list[str], *, contracts_dir: Path | None = None) -> None:
    """Fail if marker-grammar.yaml's declared exports diverge from _marker_guard.__all__."""
    print("\n=== Marker-grammar export parity ===")
    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    path = target_dir / _CONTRACT_NAME

    if not path.is_file():
        failed.append(f"Marker-grammar export parity: {path} not found")
        registry.skipped(f"{_CONTRACT_NAME} not found")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Marker-grammar export parity: could not read/parse {path}: {exc}")
        registry.skipped(f"{_CONTRACT_NAME} not parseable")
        return

    exports = _dig(data, "binding_surface", "exports")
    if not isinstance(exports, list) or not exports:
        failed.append(f"Marker-grammar export parity: {path} missing or empty 'binding_surface.exports'")
        registry.skipped(f"{_CONTRACT_NAME} missing or empty 'binding_surface.exports'")
        return

    from scripts.checks import _marker_guard  # noqa: PLC0415

    live = list(_marker_guard.__all__)
    registry.examined(len(live), unit="exports")
    if list(exports) != live:
        failed.append(
            f"Marker-grammar export parity: {_CONTRACT_NAME} declares exports={exports} but "
            f"scripts/checks/_marker_guard.py.__all__ is {live}"
        )
        return

    print(f"  PASS: {_CONTRACT_NAME} binding_surface.exports matches _marker_guard.__all__ ({len(live)} names).")
