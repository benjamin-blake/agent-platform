"""Plan document schema validation (Decision 104)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scripts.checks import _common, registry

_NON_BEHAVIOR_PREFIXES = ("tests/", "docs/plans/", ".claude/skills/")
_NON_BEHAVIOR_SUFFIXES = {".md", ".rst", ".txt"}


def _behavior_scope_files(doc: Any) -> list[str]:
    return [
        entry.file
        for entry in doc.scope
        if entry.action != "Delete"
        and not entry.file.startswith(_NON_BEHAVIOR_PREFIXES)
        and Path(entry.file).suffix.lower() not in _NON_BEHAVIOR_SUFFIXES
    ]


def _test_obligation_failures(path: Path, doc: Any) -> list[str]:
    if doc.schema_version < 4 or doc.plan_type != "IMPLEMENTATION":
        return []
    behavior_files = _behavior_scope_files(doc)
    if not behavior_files or doc.test_obligation_waiver_reason:
        return []
    covered = {obligation.source for obligation in doc.test_obligations}
    return [
        f"{path.name}: behavior-changing scope {source!r} lacks a linked test obligation or explicit waiver"
        for source in behavior_files
        if source not in covered
    ]


@registry.register("validate_plan_documents", owner="platform")
def validate_plan_documents(failed: list[str], plans_dir: Path | None = None) -> None:
    """Validate every docs/plans/PLAN-*.yaml against the PlanDocument Pydantic schema (T1.11 / CD.22).

    Runs in BOTH --pre and full presubmit: pure Python over a handful of YAML files,
    well under the Decision 60 fast-tier budget, and PLAN-*.yaml is an active editing
    surface (same placement rationale as validate_product_roadmap). Historical PLAN-*.md
    files are out of scope -- only the YAML artefact class is schema-governed.

    plans_dir overrides the scanned directory (test seam for malformed-fixture proofs).
    """
    print("\n=== Plan document schema validation ===")

    target_dir = plans_dir if plans_dir is not None else _common.ROOT / "docs" / "plans"
    plan_paths = sorted(target_dir.glob("PLAN-*.yaml"))
    if not plan_paths:
        print("  PASS: no PLAN-*.yaml files to validate.")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.plan_document import load, validate_paths  # noqa: PLC0415

        failures = validate_paths(plan_paths)
        for path, error in failures:
            print(f"  FAIL: {path.name}: {error}")
        obligation_failures: list[str] = []
        for path in plan_paths:
            if path not in {failed_path for failed_path, _ in failures}:
                obligation_failures.extend(_test_obligation_failures(path, load(path)))
        for error in obligation_failures:
            print(f"  FAIL: {error}")
        if failures or obligation_failures:
            failed.append("Plan document schema validation")
        else:
            print(f"  PASS: {len(plan_paths)} plan document(s) validate against PlanDocument schema.")
    except ImportError as exc:
        print(f"  ERROR: Could not import plan_document: {exc}")
        failed.append("Plan document schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
