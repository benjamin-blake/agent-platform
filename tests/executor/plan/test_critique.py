"""plan critique tests: critique instructions hard-fail rule, _detect_critique_cycling,
parse_steps_from_plan structured-step emission (rec-2709 Wave 5).
"""

from __future__ import annotations

from scripts.executor.plan import _detect_critique_cycling, parse_steps_from_plan


class TestCritiqueRejectsEmptyAcceptance:
    """Verify the critique instructions contain the empty-acceptance hard-fail rule."""

    def test_critique_rejects_empty_acceptance(self) -> None:
        import pathlib

        instructions_text = pathlib.Path("config/agent/executor/instructions/executor-critique.instructions.md").read_text(
            encoding="utf-8"
        )
        assert "Empty acceptance commands are forbidden" in instructions_text


class TestCritiqueCycling:
    """Tests for _detect_critique_cycling()."""

    def _make_history(self, suggestions_per_iter: list[list[str]]) -> list[dict]:
        return [
            {"iteration": i + 1, "verdict": "needs_revision", "suggestions": sug} for i, sug in enumerate(suggestions_per_iter)
        ]

    def test_no_cycling_when_history_too_short(self) -> None:
        history = self._make_history([["Violation 3: Step 1 has empty acceptance"]])
        assert _detect_critique_cycling(history) is False

    def test_no_cycling_when_violations_differ(self) -> None:
        history = self._make_history(
            [
                ["Violation 3: Step 1 has redundant steps"],
                ["Violation 2: Step 2 acceptance is a pre-condition"],
            ]
        )
        assert _detect_critique_cycling(history) is False

    def test_cycling_detected_same_step_same_rule(self) -> None:
        history = self._make_history(
            [
                ["Violation 5: Step 2 uses line-number in acceptance"],
                ["Violation 5: Step 2 still uses line-number in acceptance"],
            ]
        )
        assert _detect_critique_cycling(history) is True

    def test_cycling_detected_multiple_shared_pairs(self) -> None:
        history = self._make_history(
            [
                ["Violation 3: Step 1 redundant", "Violation 5: Step 2 line-number"],
                ["Violation 3: Step 1 still redundant", "Violation 5: Step 2 still line-number"],
            ]
        )
        assert _detect_critique_cycling(history) is True

    def test_no_cycling_when_empty_history(self) -> None:
        assert _detect_critique_cycling([]) is False

    def test_cycling_uses_only_last_two_iterations(self) -> None:
        history = self._make_history(
            [
                ["Violation 3: Step 1 redundant"],
                ["Violation 2: Step 2 pre-condition"],
                ["Violation 2: Step 2 still pre-condition"],
            ]
        )
        assert _detect_critique_cycling(history) is True

    def test_no_cycling_when_suggestions_lack_step_rule_pairs(self) -> None:
        history = self._make_history(
            [
                ["The plan looks mostly good but could be improved"],
                ["Consider merging steps for clarity"],
            ]
        )
        assert _detect_critique_cycling(history) is False


class TestPlanningEmitsStructuredStepsNotImplementations:
    """Tests that planning model emits structured steps without attempting to implement code."""

    def test_planning_emits_structured_steps_not_implementations(self) -> None:
        """Verify planning generates structured ## Step N: output, not agentic tool use."""
        structured_response = """\
### Step 1: Update imports
**File**: scripts/foo.py
**Action**: modify
**Description**: Add new import for the feature.
**Acceptance**: `grep -q "from bar import baz" scripts/foo.py`

### Step 2: Add handler function
**File**: scripts/foo.py
**Action**: modify
**Description**: Create the handler function.
**Acceptance**: `grep -q "def handle_request" scripts/foo.py`

### Step 3: Add tests
**File**: tests/test_foo.py
**Action**: create
**Description**: Create test file for the new handler.
**Acceptance**: `python -m pytest tests/test_foo.py -q`

### Step 4: Update documentation
**File**: docs/API.md
**Action**: modify
**Description**: Document the new handler in the API guide.
**Acceptance**: `grep -q "handle_request" docs/API.md`

### Step 5: Validate changes
**File**: scripts/validate.py
**Action**: (no file change)
**Description**: Run validate to ensure all changes are correct.
**Acceptance**: `python -m scripts.validate --scope all`
"""
        steps = parse_steps_from_plan(structured_response)

        assert len(steps) == 5, "Should parse all 5 steps from structured response"
        assert all(step.get("n") for step in steps), "All steps should have step numbers"
        assert all(step.get("title") for step in steps), "All steps should have titles"
        assert all(step.get("file") or step.get("n") in [5] for step in steps), "All steps except final should have file paths"
        assert all(step.get("acceptance") for step in steps), "All steps should have acceptance criteria"

        assert steps[0]["file"] == "scripts/foo.py"
        assert steps[0]["action"] == "modify"
        assert steps[0]["n"] == 1

        assert steps[2]["file"] == "tests/test_foo.py"
        assert steps[2]["action"] == "create"
        assert steps[2]["n"] == 3
