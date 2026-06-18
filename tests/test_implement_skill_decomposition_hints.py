"""Content-assertion and live-data tests for the decomposition-hint exemption
inheritance rule added to .claude/skills/implement/SKILL.md (T-1.12 subset g).

The inheritance rule is pure methodology prose -- there is no production function
that computes it.  resolve_inherited_exemption() below is an in-test executable
model of the documented rule, not new production code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.platform_roadmap import RoadmapDocument, load
from scripts.prompt_compliance import parse_invariants

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "implement" / "SKILL.md"
ROADMAP_PATH = REPO_ROOT / "docs" / "ROADMAP-PLATFORM.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _item(
    item_id: str,
    *,
    tier: str = "T0",
    bootstrap_completion_exempt: bool = False,
    decomposition_hints: dict | None = None,
) -> dict:
    d: dict = {
        "id": item_id,
        "tier": tier,
        "name": f"Synthetic item {item_id}",
        "depends_on": [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": False,
        "status": "not_started",
        "bootstrap_completion_exempt": bootstrap_completion_exempt,
    }
    if decomposition_hints is not None:
        d["decomposition_hints"] = decomposition_hints
    return d


def _doc(*items: dict) -> dict:
    import copy

    d = copy.deepcopy(_BASE_DOC)
    d["tier_items"] = list(items)
    return d


def _bookkeeping_section(text: str) -> str:
    """Return the slice of text from '## Tier_item bookkeeping' up to the next
    top-level '\\n## ' header, or to end-of-file if none follows."""
    start_marker = "## Tier_item bookkeeping"
    start = text.find(start_marker)
    if start == -1:
        return ""
    # Find the next top-level section after the start
    next_section = text.find("\n## ", start + len(start_marker))
    if next_section == -1:
        return text[start:]
    return text[start:next_section]


def assert_inheritance_documented(text: str) -> None:
    """Raise AssertionError if the bookkeeping section does not contain the
    decomposition-hint inheritance subsection with all required tokens.

    Required: header "### Decomposition-hint exemption inheritance" AND all of
    "decomposition_hints", "atomic_plans", "bootstrap_completion_exempt",
    "read-only", "inherit" (case-insensitive), "T-1.12", and "T1.12" within
    that section.
    """
    section = _bookkeeping_section(text)
    assert section, "Bookkeeping section not found in SKILL.md"

    header = "### Decomposition-hint exemption inheritance"
    assert header in section, f"Header '{header}' not found in bookkeeping section"

    required_tokens = [
        "decomposition_hints",
        "atomic_plans",
        "bootstrap_completion_exempt",
        "read-only",
        "T-1.12",
        "T1.12",
    ]
    section_lower = section.lower()
    for token in required_tokens:
        assert token.lower() in section_lower, (
            f"Required token '{token}' missing from the decomposition-hint exemption subsection"
        )

    # "inherit" case-insensitive (token requirement from plan spec)
    assert "inherit" in section_lower, "Required token 'inherit' missing from the subsection"


def resolve_inherited_exemption(roadmap_doc: RoadmapDocument, plan_slug: str) -> bool | None:
    """In-test model of the documented inheritance rule.

    Scans roadmap_doc.tier_items for an item whose decomposition_hints.atomic_plans[]
    contains an entry whose head token (entry.strip().split()[0]) equals
    f"PLAN-{plan_slug}".  Returns the matched parent's bootstrap_completion_exempt
    value, or None if no parent matches.
    """
    target_token = f"PLAN-{plan_slug}"
    for item in roadmap_doc.tier_items:
        if item.decomposition_hints is None:
            continue
        atomic_plans = item.decomposition_hints.get("atomic_plans") or []
        for entry in atomic_plans:
            head = entry.strip().split()[0] if entry.strip() else ""
            if head == target_token:
                return item.bootstrap_completion_exempt
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInheritanceClausePresent:
    def test_inheritance_clause_present_in_live_skill(self) -> None:
        """The full inheritance subsection is present in the live SKILL.md."""
        assert_inheritance_documented(SKILL_PATH.read_text(encoding="utf-8"))

    def test_clause_co_located_in_bookkeeping_section(self) -> None:
        """The subsection header appears INSIDE the bookkeeping section, not
        merely somewhere else in the file."""
        text = SKILL_PATH.read_text(encoding="utf-8")
        section = _bookkeeping_section(text)
        assert section, "Bookkeeping section not found"
        assert "### Decomposition-hint exemption inheritance" in section, (
            "Header found in file but not inside the bookkeeping section"
        )

    def test_assertion_helper_has_teeth(self) -> None:
        """Strip the subsection from the SKILL.md text; assert_inheritance_documented
        must raise AssertionError on the mutated text (proves non-vacuity)."""
        text = SKILL_PATH.read_text(encoding="utf-8")
        # Remove from the subsection header up to the next "###" or "## " boundary
        stripped = re.sub(
            r"### Decomposition-hint exemption inheritance.*?(?=\n###|\n## )",
            "",
            text,
            flags=re.DOTALL,
        )
        with pytest.raises(AssertionError):
            assert_inheritance_documented(stripped)


class TestBehaviouralInvariantsIntegrity:
    def test_behavioural_invariants_block_still_parses(self) -> None:
        """The SKILL.md edit must not have corrupted the ## Behavioural Invariants
        YAML block that prompt_compliance.py checks."""
        invariants = parse_invariants(SKILL_PATH)
        required_keys = {"preflight_run", "never_on_main", "review_as_scope", "auto_review_and_commit"}
        missing = required_keys - set(invariants.keys())
        assert not missing, f"Missing invariant keys after SKILL.md edit: {missing}"


class TestResolveInheritedExemption:
    def test_resolution_exempt_parent(self) -> None:
        """A parent with bootstrap_completion_exempt=True propagates True to child."""
        doc = RoadmapDocument.model_validate(
            _doc(
                _item(
                    "T-parent",
                    tier="T-1",
                    bootstrap_completion_exempt=True,
                    decomposition_hints={
                        "split_by": "subsystem",
                        "atomic_plans": ["PLAN-child-x -- first child (subset a)"],
                        "rationale": "split for test",
                    },
                )
            )
        )
        assert resolve_inherited_exemption(doc, "child-x") is True

    def test_resolution_non_exempt_parent(self) -> None:
        """A parent with bootstrap_completion_exempt=False propagates False to child."""
        doc = RoadmapDocument.model_validate(
            _doc(
                _item(
                    "T1.parent",
                    tier="T1",
                    bootstrap_completion_exempt=False,
                    decomposition_hints={
                        "split_by": "per_lambda",
                        "atomic_plans": ["PLAN-child-y -- second child (subset b)"],
                        "rationale": "split for test",
                    },
                )
            )
        )
        result = resolve_inherited_exemption(doc, "child-y")
        assert result is False

    def test_resolution_no_parent_returns_none(self) -> None:
        """When no parent names the slug, None is returned."""
        doc = RoadmapDocument.model_validate(
            _doc(
                _item(
                    "T0.unrelated",
                    decomposition_hints={
                        "split_by": "subsystem",
                        "atomic_plans": ["PLAN-other-plan -- not our slug"],
                        "rationale": "unrelated parent",
                    },
                )
            )
        )
        assert resolve_inherited_exemption(doc, "nonexistent-slug") is None


class TestLiveRoadmapInheritance:
    def test_live_roadmap_this_plan_inherits_from_t_1_12(self) -> None:
        """The live ROADMAP-PLATFORM.yaml must resolve PLAN-implement-skill-
        decomposition-hints to bootstrap_completion_exempt=True via parent T-1.12."""
        doc = load(ROADMAP_PATH)
        result = resolve_inherited_exemption(doc, "implement-skill-decomposition-hints")
        assert result is True, (
            f"Expected inherited True from T-1.12, got {result!r}. "
            "Check that T-1.12's decomposition_hints.atomic_plans still names "
            "PLAN-implement-skill-decomposition-hints."
        )
        # Also verify the matched parent is T-1.12 specifically
        matched_parent_id: str | None = None
        for item in doc.tier_items:
            if item.decomposition_hints is None:
                continue
            for entry in (item.decomposition_hints.get("atomic_plans") or []):
                head = entry.strip().split()[0] if entry.strip() else ""
                if head == "PLAN-implement-skill-decomposition-hints":
                    matched_parent_id = item.id
                    break
            if matched_parent_id is not None:
                break
        assert matched_parent_id == "T-1.12", (
            f"Expected parent id 'T-1.12', matched '{matched_parent_id}'"
        )
