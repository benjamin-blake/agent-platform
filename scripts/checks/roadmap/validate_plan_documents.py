"""Plan document schema validation (Decision 104)."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.checks import _common, registry

_NON_BEHAVIOR_PREFIXES = ("tests/", "docs/plans/")
_DOCUMENTATION_SUFFIXES = {".md", ".rst", ".txt"}

# Schema version a freshly-authored plan must declare. The test-obligation gate below is
# v4-gated, so a new plan authored at v3 opts out of it silently -- this constant is what
# the canonical template in .claude/skills/planning/SKILL.md is pinned to.
_MIN_NEW_PLAN_SCHEMA_VERSION = 4


def _added_plan_names() -> set[str]:
    """Filenames of docs/plans/PLAN-*.yaml files ADDED (not modified) in this diff.

    Matching on filename rather than repo-relative path keeps the comparison valid under the
    plans_dir test seam, where the fixture directory is a tmp path; PLAN-*.yaml slugs are
    already globally unique because plan_path must equal docs/plans/PLAN-{slug}.yaml.
    """
    return {
        Path(path).name
        for status, path in _common.get_status_aware_diff()
        if status in ("A", "??") and _common.PLAN_PATH_RE.match(path)
    }


def _new_plan_version_failures(path: Path, doc: Any, added_names: set[str]) -> list[str]:
    """Refuse a brand-new plan authored below the current schema version.

    Historical plans keep the version they were authored at (1-3 all stay schema-valid); the
    gate binds only files new in this diff, which is what makes the v4-gated obligation check
    actually fire for the plans being written from now on.
    """
    if path.name not in added_names or doc.schema_version >= _MIN_NEW_PLAN_SCHEMA_VERSION:
        return []
    return [
        f"{path.name}: newly-added plans must declare schema_version {_MIN_NEW_PLAN_SCHEMA_VERSION} "
        f"(got {doc.schema_version}) -- the test-obligation gate only binds at "
        f"v{_MIN_NEW_PLAN_SCHEMA_VERSION}"
    ]


def _is_documentation(file: str) -> bool:
    """True for prose that carries no runtime or agent behavior.

    The suffix alone does not settle it: a prompt file is executable instruction text (Layer 5 of
    docs/contracts/instruction-architecture.yaml), so config/agent/executor/prompts/*.prompt.md
    and .github/prompts/**/*.prompt.md change behavior exactly the way a .py file does and never
    inherit the documentation exemption.
    """
    path = PurePosixPath(file)
    if path.suffix.lower() not in _DOCUMENTATION_SUFFIXES:
        return False
    return ".prompt" not in path.suffixes and "prompts" not in path.parts


def _behavior_scope_files(doc: Any) -> list[str]:
    return [
        entry.file
        for entry in doc.scope
        if entry.action != "Delete" and not entry.file.startswith(_NON_BEHAVIOR_PREFIXES) and not _is_documentation(entry.file)
    ]


def _test_obligation_failures(path: Path, doc: Any) -> list[str]:
    """Every behavior-capable scope row of a v4 IMPLEMENTATION plan needs its own obligation.

    Waivers are per-source (TestObligation.waiver_reason) by design: a single plan-level opt-out
    string would let one sentence disable the gate for every file in the plan.
    """
    if doc.schema_version < _MIN_NEW_PLAN_SCHEMA_VERSION or doc.plan_type != "IMPLEMENTATION":
        return []
    covered = {obligation.source for obligation in doc.test_obligations}
    return [
        f"{path.name}: behavior-changing scope {source!r} lacks a linked test obligation or per-source waiver"
        for source in _behavior_scope_files(doc)
        if source not in covered
    ]


@registry.register("validate_plan_documents", owner="platform")
def validate_plan_documents(
    failed: list[str], plans_dir: Path | None = None, added_plan_names: set[str] | None = None
) -> None:
    """Validate every docs/plans/PLAN-*.yaml against the PlanDocument Pydantic schema (T1.11 / CD.22).

    Runs in BOTH --pre and full presubmit: pure Python over a handful of YAML files,
    well under the Decision 60 fast-tier budget, and PLAN-*.yaml is an active editing
    surface (same placement rationale as validate_product_roadmap). Historical PLAN-*.md
    files are out of scope -- only the YAML artefact class is schema-governed.

    plans_dir overrides the scanned directory and added_plan_names overrides the git-derived
    new-plan set (test seams for malformed-fixture and new-plan proofs).
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
        from scripts.roadmap.plan_document import load  # noqa: PLC0415

        added_names = _added_plan_names() if added_plan_names is None else added_plan_names
        errors: list[str] = []
        for path in plan_paths:
            # One parse per plan feeds both the schema verdict and the semantic gates -- this
            # check rides the --pre tier, so a second load() per passing plan is pure waste.
            try:
                doc = load(path)
            except Exception as exc:  # noqa: BLE001 -- any parse/validation error is a failure verdict
                errors.append(f"{path.name}: {exc}")
                continue
            errors.extend(_new_plan_version_failures(path, doc, added_names))
            errors.extend(_test_obligation_failures(path, doc))
        for error in errors:
            print(f"  FAIL: {error}")
        if errors:
            failed.append("Plan document schema validation")
        else:
            print(f"  PASS: {len(plan_paths)} plan document(s) validate against PlanDocument schema.")
    except ImportError as exc:
        print(f"  ERROR: Could not import plan_document: {exc}")
        failed.append("Plan document schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
