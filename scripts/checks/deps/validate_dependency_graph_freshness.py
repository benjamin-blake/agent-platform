"""Dependency-graph export freshness validation (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_dependency_graph_freshness", owner="platform")
def validate_dependency_graph_freshness(failed: list[str]) -> None:
    """Fail if docs/dependency-graph.json exists and has drifted from the current graph.

    No-op when no committed export is present. Full tier only (Decision 73 non-wedging).
    Delegates to scripts.dependency_graph.check_export_freshness (Decision 80).
    """
    print("\n=== Dependency graph freshness ===")
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.dependency_graph import check_export_freshness  # noqa: PLC0415

        before = len(failed)
        check_export_freshness(failed)
        if len(failed) == before:
            print("  PASS: dependency graph export is current (or no committed export).")
    except ImportError as exc:
        print(f"  ERROR: Could not import dependency_graph: {exc}")
        failed.append("Dependency graph freshness")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
