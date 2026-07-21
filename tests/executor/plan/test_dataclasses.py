"""plan dataclass + persistence + no-change/all-done tests: ExecutionPlan, PlanStep, save_plan,
get_latest_plan, _looks_like_no_changes (rec-2709 Wave 5).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.executor.plan as plan_mod
from scripts.executor.plan import ExecutionPlan, PlanStep, _looks_like_no_changes, get_latest_plan, save_plan


class TestExecutionPlanDataclass:
    """Tests for ExecutionPlan dataclass."""

    def _make_plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            rec_id="rec-001",
            slug="refactor-foo",
            revision=1,
            timestamp="2026-01-01T00:00:00+00:00",
            status="draft",
            model="claude-sonnet-4-5",
            tokens_used=1000,
            steps=[{"n": 1, "title": "do it", "file": "f.py", "action": "modify", "description": "", "acceptance": ""}],
        )

    def test_to_dict_returns_dict(self) -> None:
        plan = self._make_plan()
        d = plan.to_dict()
        assert isinstance(d, dict)
        assert d["rec_id"] == "rec-001"
        assert d["status"] == "draft"

    def test_to_dict_includes_steps(self) -> None:
        plan = self._make_plan()
        d = plan.to_dict()
        assert len(d["steps"]) == 1
        assert d["steps"][0]["n"] == 1

    def test_to_dict_includes_critique_history(self) -> None:
        plan = self._make_plan()
        d = plan.to_dict()
        assert "critique_history" in d
        assert d["critique_history"] == []

    def test_round_trip_via_json(self) -> None:
        plan = self._make_plan()
        serialised = json.dumps(plan.to_dict())
        data = json.loads(serialised)
        assert data["rec_id"] == "rec-001"


class TestPlanStep:
    """Tests for PlanStep dataclass."""

    def test_all_fields_present(self) -> None:
        step = PlanStep(n=1, title="Do it", file="f.py", action="create", description="desc", acceptance="cmd")
        assert step.n == 1
        assert step.title == "Do it"
        assert step.file == "f.py"
        assert step.action == "create"
        assert step.description == "desc"
        assert step.acceptance == "cmd"


class TestSavePlanAndGetLatestPlan:
    """Tests for save_plan() and get_latest_plan()."""

    def _make_plan(self, rec_id: str = "rec-001", revision: int = 1) -> ExecutionPlan:
        return ExecutionPlan(
            rec_id=rec_id,
            slug="my-slug",
            revision=revision,
            timestamp="2026-01-01T00:00:00+00:00",
            status="approved",
            model="claude",
            tokens_used=None,
            steps=[],
        )

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        plans_jsonl = tmp_path / "plans.jsonl"
        plan = self._make_plan()
        with (
            patch.object(plan_mod, "PLANS_JSONL", plans_jsonl),
            patch("scripts.ops_portal.execution_plans.save_execution_plan") as mock_save,
        ):
            save_plan(plan)
            result = get_latest_plan("rec-001")
        mock_save.assert_called_once_with(plan.to_dict())
        assert result is not None
        assert result.rec_id == "rec-001"
        assert result.status == "approved"

    def test_get_latest_returns_highest_revision(self, tmp_path: Path) -> None:
        plans_jsonl = tmp_path / "plans.jsonl"
        plan1 = self._make_plan(revision=1)
        plan2 = self._make_plan(revision=3)
        plan_low = self._make_plan(revision=2)
        with (
            patch.object(plan_mod, "PLANS_JSONL", plans_jsonl),
            patch("scripts.ops_portal.execution_plans.save_execution_plan"),
        ):
            save_plan(plan1)
            save_plan(plan_low)
            save_plan(plan2)
            result = get_latest_plan("rec-001")
        assert result is not None
        assert result.revision == 3

    def test_get_latest_returns_none_when_no_file(self, tmp_path: Path) -> None:
        plans_jsonl = tmp_path / "missing.jsonl"
        with patch.object(plan_mod, "PLANS_JSONL", plans_jsonl):
            result = get_latest_plan("rec-001")
        assert result is None

    def test_get_latest_returns_none_for_different_rec(self, tmp_path: Path) -> None:
        plans_jsonl = tmp_path / "plans.jsonl"
        plan = self._make_plan("rec-001")
        with (
            patch.object(plan_mod, "PLANS_JSONL", plans_jsonl),
            patch("scripts.ops_portal.execution_plans.save_execution_plan"),
        ):
            save_plan(plan)
            result = get_latest_plan("rec-999")
        assert result is None


class TestLooksLikeNoChanges:
    """Tests for _looks_like_no_changes()."""

    def test_returns_false_for_short_text(self) -> None:
        assert _looks_like_no_changes("already done") is False

    def test_returns_false_for_non_matching_long_text(self) -> None:
        long_text = "This is a proper plan with steps " + "x " * 200
        assert _looks_like_no_changes(long_text) is False

    def test_returns_true_for_long_already_implemented(self) -> None:
        long_text = "The requirement is already implemented. " * 10
        assert _looks_like_no_changes(long_text) is True

    def test_returns_true_for_no_changes_needed(self) -> None:
        long_text = "no changes are required here. " * 10
        assert _looks_like_no_changes(long_text) is True

    def test_case_insensitive(self) -> None:
        long_text = "ALREADY IMPLEMENTED - nothing to do here. " * 10
        assert _looks_like_no_changes(long_text) is True

    def test_short_prescribed_token_exact(self) -> None:
        """Prescribed ALREADY_IMPLEMENTED token is detected even though it is short."""
        assert _looks_like_no_changes("ALREADY_IMPLEMENTED") is True

    def test_short_prescribed_token_lowercase(self) -> None:
        assert _looks_like_no_changes("already_implemented") is True

    def test_short_prescribed_token_with_whitespace(self) -> None:
        assert _looks_like_no_changes("  ALREADY_IMPLEMENTED  ") is True

    def test_short_keyword_only_still_false(self) -> None:
        """Single keyword word without prescribed token is too short to match."""
        assert _looks_like_no_changes("already") is False


class TestAllStepsAlreadyDone:
    """Tests for _all_steps_already_done()."""

    @pytest.mark.parametrize(
        "steps,expected",
        [
            # Case 1: all titles contain "Already" (mixed case)
            (
                [
                    {
                        "n": 1,
                        "title": "Already implemented feature X",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "ALREADY done feature Y",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 2: all titles end with checkmark ✓
            (
                [
                    {
                        "n": 1,
                        "title": "Feature X ✓",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "Feature Y ✔",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 3: mixed "Already" and checkmark titles
            (
                [
                    {
                        "n": 1,
                        "title": "Already feature X",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "Feature Y ✓",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 4: single step that's already done
            (
                [
                    {
                        "n": 1,
                        "title": "Already implemented ✓",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                True,
            ),
            # Case 5: empty steps list returns False
            ([], False),
            # Case 6: partial "Already" titles (some match, some don't)
            (
                [
                    {
                        "n": 1,
                        "title": "Already implemented",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "Feature Y (new work)",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                False,
            ),
            # Case 7: no titles match pattern
            (
                [
                    {
                        "n": 1,
                        "title": "Create new feature",
                        "file": "f.py",
                        "action": "create",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                False,
            ),
            # Case 8: step with empty title
            (
                [
                    {
                        "n": 1,
                        "title": "",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                False,
            ),
            # Case 9: case insensitivity for "Already"
            (
                [
                    {
                        "n": 1,
                        "title": "aLrEaDy work done",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                True,
            ),
            # Case 10: U+2705 emoji (✅) prefix detection
            (
                [
                    {
                        "n": 1,
                        "title": "✅ Feature X",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "✅ Already done feature Y",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 11: line-reference pattern "(lines N-M)"
            (
                [
                    {
                        "n": 1,
                        "title": "✅ Verify changes (lines 242-326)",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                True,
            ),
            # Case 12: line-reference pattern "(line N)"
            (
                [
                    {
                        "n": 1,
                        "title": "Verification only (line 550)",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                True,
            ),
            # Case 13: line-reference pattern "Lines N-M:"
            (
                [
                    {
                        "n": 1,
                        "title": "Lines 1-10: Review complete",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "Already done ✓",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 14: mixed patterns with emoji, line references, and already
            (
                [
                    {
                        "n": 1,
                        "title": "✅ Feature update",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 2,
                        "title": "Lines 15-25: Verified",
                        "file": "g.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                    {
                        "n": 3,
                        "title": "Already fixed (line 100)",
                        "file": "h.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    },
                ],
                True,
            ),
            # Case 15: line reference with no matching pattern fails
            (
                [
                    {
                        "n": 1,
                        "title": "Feature at line 50",
                        "file": "f.py",
                        "action": "modify",
                        "description": "",
                        "acceptance": "",
                    }
                ],
                False,
            ),
        ],
    )
    def test_all_steps_already_done(self, steps: list[dict], expected: bool) -> None:
        from scripts.executor.plan import _all_steps_already_done

        result = _all_steps_already_done(steps)
        assert result is expected
