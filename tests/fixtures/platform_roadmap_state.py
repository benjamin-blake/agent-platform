"""Shared fixture helpers for tests/platform_roadmap_state/ (mirror package, Decision 131).

Migrated from the retired tests/test_platform_roadmap_state.py monolith (Decision 128
decompose-don't-raise). This module's names never start with `test_`, so it is exempt from the
cross-test-import guard (validate_no_cross_test_imports) by construction -- every mirror module
imports these helpers from here rather than from a sibling test_*.py file.

PATH-DEPTH NOTE: _LIVE_ROADMAP is computed repo-root-anchored from THIS file's location
(tests/fixtures/, depth-2 under tests/), not from a migrated test module's own __file__ (which
would sit at tests/platform_roadmap_state/, also depth-2, but with a different relative
resolution). Every migrated live-roadmap reference imports _LIVE_ROADMAP from here instead of
recomputing `Path(__file__).parent.parent` locally -- that recomputation is exactly what broke on
the monolith-to-package move (parent.parent from a depth-2 test file resolves to tests/docs/...,
not docs/...).
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import yaml

from scripts.roadmap.platform_roadmap import PlatformRoadmapState, RoadmapDocument

_BASE_DOC: dict = {
    "document": {
        "id": "ROADMAP-TEST",
        "version": 1,
        "status": "draft",
        "filed_via": "pending_log_decision_lambda",
        "gate_helpers": [
            {"name": "tier_complete", "arity": 1},
            {"name": "all_in_tier_with_status", "arity": 2},
            {"name": "grace_period_elapsed", "arity": 2},
            {"name": "item_field_eq", "arity": 3},
        ],
    },
    "tier_items": [],
    "candidate_decisions": [],
    "cross_tier_gates": [],
}

# Repo-root-anchored (NOT a recomputed `Path(__file__).parent.parent`, which depth-2 test
# locations resolve incorrectly -- see module docstring). tests/fixtures/ -> tests/ -> repo root.
_LIVE_ROADMAP = Path(__file__).resolve().parents[2] / "docs" / "ROADMAP-PLATFORM.yaml"


def _doc(**overrides) -> dict:
    d = copy.deepcopy(_BASE_DOC)
    d.update(overrides)
    return d


def _item(
    item_id: str,
    tier: str = "T0",
    depends_on: list | None = None,
    status: str = "not_started",
    strategic: bool = False,
) -> dict:
    return {
        "id": item_id,
        "tier": tier,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": strategic,
        "status": status,
    }


def _make_state(items: list[dict]) -> PlatformRoadmapState:
    doc = RoadmapDocument.model_validate(_doc(tier_items=items))
    return PlatformRoadmapState(doc)


def _write_fixture_yaml(items: list[dict]) -> Path:
    """Write a minimal valid roadmap YAML to a temp file and return its path."""
    data = _doc(tier_items=items)
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8")
    yaml.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def _cd(
    cd_id: str,
    state: str = "pending",
    gates: list | None = None,
    realization_evidence: str | None = None,
    detail: str | None = None,
) -> dict:
    """Build a minimal candidate_decision dict. `detail` is an optional param (extended for the
    realization_candidates() fixtures -- the superseded-prose and [Realized-marker edge cases)."""
    d = {"id": cd_id, "title": f"Decision {cd_id}", "state": state, "gates": gates or []}
    if realization_evidence is not None:
        d["realization_evidence"] = realization_evidence
    if detail is not None:
        d["detail"] = detail
    return d


def _state_from_doc(doc_dict: dict) -> PlatformRoadmapState:
    return PlatformRoadmapState(RoadmapDocument.model_validate(doc_dict))
