"""Unit tests for scripts/executor/plan.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.plan as plan_mod
import scripts.llm.model_registry as model_registry_mod
from scripts.executor.plan import (
    ExecutionPlan,
    PlanStep,
    _compute_step_scope,
    _detect_critique_cycling,
    _looks_like_no_changes,
    _validate_step_scope,
    critique_plan,
    escalate_planning_model,
    generate_initial_plan,
    get_latest_plan,
    get_plan_timeout_secs,
    get_planning_model,
    load_prompt,
    parse_steps_from_plan,
    refine_plan,
    save_plan,
)
from scripts.llm.client import LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAN_TEXT = """\
### Step 1: Create the module
**File**: scripts/executor/errors.py
**Action**: create
**Description**: Add error types for the executor package.
**Acceptance**: `python -c "from scripts.executor.errors import ExecutorError"`

### Step 2: Update init
**File**: scripts/executor/__init__.py
**Action**: modify
**Description**: Re-export all public symbols.
**Acceptance**: `python -c "import scripts.executor"`
"""


class TestLoadPrompt:
    """Tests for load_prompt()."""

    def test_loads_template_and_returns_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "planning.prompt.md"
        prompt_file.write_text("Hello {rec_id}", encoding="utf-8")

        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            template, prompt_hash = load_prompt("planning")

        assert template == "Hello {rec_id}"
        expected_hash = hashlib.sha256(b"Hello {rec_id}").hexdigest()[:12]
        assert prompt_hash == expected_hash

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        with patch.object(plan_mod, "PROMPTS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                load_prompt("nonexistent")

    def test_hash_is_12_hex_chars(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "p.prompt.md").write_text("content", encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h = load_prompt("p")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        content = "deterministic content"
        (prompts_dir / "q.prompt.md").write_text(content, encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h1 = load_prompt("q")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h2 = load_prompt("q")
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "a.prompt.md").write_text("content A", encoding="utf-8")
        (prompts_dir / "b.prompt.md").write_text("content B", encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h_a = load_prompt("a")
            _, h_b = load_prompt("b")
        assert h_a != h_b


class TestParseStepsFromPlan:
    """Tests for parse_steps_from_plan()."""

    def test_parses_two_steps(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert len(steps) == 2

    def test_step_numbers_correct(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["n"] == 1
        assert steps[1]["n"] == 2

    def test_step_titles_correct(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert "Create the module" in steps[0]["title"]
        assert "Update init" in steps[1]["title"]

    def test_step_files_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["file"] == "scripts/executor/errors.py"
        assert steps[1]["file"] == "scripts/executor/__init__.py"

    def test_step_actions_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["action"] == "create"
        assert steps[1]["action"] == "modify"

    def test_acceptance_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert "ExecutorError" in steps[0]["acceptance"]

    def test_empty_plan_returns_empty_list(self) -> None:
        assert parse_steps_from_plan("") == []

    def test_fallback_numbered_list(self) -> None:
        numbered = "1. First task\n2. Second task\n3. Third task\n"
        steps = parse_steps_from_plan(numbered)
        assert len(steps) == 3
        assert steps[0]["title"] == "First task"
        assert steps[0]["action"] == "modify"

    def test_steps_sorted_by_n(self) -> None:
        inverted = """\
### Step 3: Third
**File**: c.py
**Action**: modify
**Description**: desc c
**Acceptance**: ``

### Step 1: First
**File**: a.py
**Action**: create
**Description**: desc a
**Acceptance**: ``
"""
        steps = parse_steps_from_plan(inverted)
        assert steps[0]["n"] == 1
        assert steps[1]["n"] == 3

    def test_file_backticks_stripped(self) -> None:
        text = (
            "### Step 1: Setup\n"
            "**File**: `scripts/foo.py`\n"
            "**Action**: create\n"
            "**Description**: make\n"
            "**Acceptance**: `echo ok`\n"
        )
        steps = parse_steps_from_plan(text)
        assert steps[0]["file"] == "scripts/foo.py"

    def test_dedup_prefers_complete_over_empty(self) -> None:
        """When step N appears twice, prefer the one with file+acceptance populated."""
        text = """\
### Step 1: First attempt (incomplete)
**File**:
**Action**: create
**Description**: desc
**Acceptance**:

### Step 1: Second attempt (complete)
**File**: scripts/foo.py
**Action**: create
**Description**: desc
**Acceptance**: `echo ok`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        assert steps[0]["file"] == "scripts/foo.py"
        assert steps[0]["acceptance"] == "`echo ok`"

    def test_dedup_prefers_first_complete_over_later_complete(self) -> None:
        """When both duplicates are complete, keep the first one."""
        text = """\
### Step 1: First
**File**: scripts/first.py
**Action**: create
**Description**: first desc
**Acceptance**: `python first.py`

### Step 1: Second
**File**: scripts/second.py
**Action**: modify
**Description**: second desc
**Acceptance**: `python second.py`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        assert steps[0]["file"] == "scripts/first.py"
        assert steps[0]["acceptance"] == "`python first.py`"

    def test_dedup_empty_stays_empty_when_all_empty(self) -> None:
        """When all duplicates are empty, keep the first one."""
        text = """\
### Step 1: First
**File**:
**Action**: create
**Description**: desc
**Acceptance**:

### Step 1: Second
**File**:
**Action**: modify
**Description**: desc
**Acceptance**:
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        # When file is empty (just ": " with nothing), the regex captures nothing useful
        # and stripping returns empty string
        assert steps[0]["action"] == "create"  # Verify first one is kept

    def test_dedup_multiple_step_numbers(self) -> None:
        """Deduplication works independently for each step number."""
        text = """\
### Step 1: First attempt
**File**:
**Action**: create
**Description**: desc1
**Acceptance**:

### Step 1: Complete
**File**: foo.py
**Action**: create
**Description**: desc1
**Acceptance**: `python foo.py`

### Step 2: First attempt
**File**:
**Action**: modify
**Description**: desc2
**Acceptance**:

### Step 2: Complete
**File**: bar.py
**Action**: modify
**Description**: desc2
**Acceptance**: `python bar.py`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 2
        assert steps[0]["n"] == 1
        assert steps[0]["file"] == "foo.py"
        assert steps[1]["n"] == 2
        assert steps[1]["file"] == "bar.py"

    def test_rejects_malformed_file_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """File values with markdown bold markers are rejected and set to empty."""
        text = """\
### Step 1: Test malformed file detection
**File**: **Action**: create
**Action**: create
**Description**: This should be rejected due to malformed file value
**Acceptance**: `python test.py`

### Step 2: Test partial markdown artifact
**File**: path/to/**file**.py
**Action**: modify
**Description**: This should also be rejected due to bold markers in path
**Acceptance**: `python test2.py`

### Step 3: Valid file path
**File**: valid/path.py
**Action**: modify
**Description**: This should be accepted
**Acceptance**: `python valid.py`
"""
        with caplog.at_level("WARNING"):
            steps = parse_steps_from_plan(text)

        assert len(steps) == 3

        # Step 1: File value starting with ** should be rejected
        assert steps[0]["n"] == 1
        assert steps[0]["file"] == ""  # Should be empty due to malformed value

        # Step 2: File value containing ** should be rejected
        assert steps[1]["n"] == 2
        assert steps[1]["file"] == ""  # Should be empty due to bold markers

        # Step 3: Valid file path should be accepted
        assert steps[2]["n"] == 3
        assert steps[2]["file"] == "valid/path.py"

        # Check warning logs were generated
        assert len(caplog.records) == 2
        assert "malformed file value" in caplog.records[0].message.lower()
        assert "**Action**: create" in caplog.records[0].message
        assert "malformed file value" in caplog.records[1].message.lower()
        assert "**file**" in caplog.records[1].message


class TestComputeStepScope:
    """Tests for _compute_step_scope()."""

    def test_empty_file_returns_empty_scope(self) -> None:
        assert _compute_step_scope({"file": ""}) == set()

    def test_missing_file_key_returns_empty_scope(self) -> None:
        assert _compute_step_scope({}) == set()

    def test_whitespace_only_file_returns_empty_scope(self) -> None:
        assert _compute_step_scope({"file": "   "}) == set()

    def test_executor_module_scope(self) -> None:
        scope = _compute_step_scope({"file": "scripts/executor/plan.py"})
        assert scope == {
            "scripts/executor/plan.py",
            "tests/test_executor_plan.py",
        }

    def test_scripts_top_level_scope(self) -> None:
        scope = _compute_step_scope({"file": "scripts/validate.py"})
        assert scope == {
            "scripts/validate.py",
            "tests/test_validate.py",
        }

    def test_src_module_scope(self) -> None:
        scope = _compute_step_scope({"file": "src/data/pipeline.py"})
        assert scope == {
            "src/data/pipeline.py",
            "tests/test_pipeline.py",
        }

    def test_other_path_scope(self) -> None:
        scope = _compute_step_scope({"file": "foo/bar.py"})
        assert scope == {"foo/bar.py", "tests/test_bar.py"}


class TestValidateStepScope:
    """Tests for _validate_step_scope()."""

    def test_no_target_file_passes_all_steps(self) -> None:
        steps = [
            {"n": 1, "file": "any/file.py"},
            {"n": 2, "file": "other/file.py"},
        ]
        result = _validate_step_scope(steps, {"file": ""})
        assert result == steps

    def test_missing_file_key_passes_all_steps(self) -> None:
        steps = [{"n": 1, "file": "any/file.py"}]
        result = _validate_step_scope(steps, {})
        assert result == steps

    def test_in_scope_steps_kept(self) -> None:
        rec = {"file": "scripts/executor/plan.py"}
        steps = [
            {"n": 1, "file": "scripts/executor/plan.py"},
            {"n": 2, "file": "tests/test_executor_plan.py"},
        ]
        result = _validate_step_scope(steps, rec)
        assert len(result) == 2

    def test_out_of_scope_step_rejected(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        rec = {"file": "scripts/executor/plan.py"}
        steps = [
            {"n": 1, "file": "scripts/executor/plan.py"},
            {"n": 2, "file": "scripts/executor/step_runner.py"},
        ]
        with caplog.at_level("WARNING"):
            result = _validate_step_scope(steps, rec)
        assert len(result) == 1
        assert result[0]["file"] == "scripts/executor/plan.py"
        assert any("[SCOPE]" in r.message for r in caplog.records)

    def test_empty_file_step_always_kept(self) -> None:
        rec = {"file": "scripts/executor/plan.py"}
        steps = [
            {"n": 1, "file": ""},
            {"n": 2, "file": "scripts/executor/plan.py"},
        ]
        result = _validate_step_scope(steps, rec)
        assert len(result) == 2

    def test_all_steps_out_of_scope_returns_empty(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        rec = {"file": "scripts/executor/plan.py"}
        steps = [
            {"n": 1, "file": "unrelated/foo.py"},
            {"n": 2, "file": "unrelated/bar.py"},
        ]
        with caplog.at_level("WARNING"):
            result = _validate_step_scope(steps, rec)
        assert result == []


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
            patch.object(plan_mod, "OpsWriter") as mock_ops,
        ):
            save_plan(plan)
            result = get_latest_plan("rec-001")
        mock_ops.return_value.write.assert_called_once_with("ops_execution_plans", plan.to_dict())
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
            patch.object(plan_mod, "OpsWriter"),
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
            patch.object(plan_mod, "OpsWriter"),
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


class TestModelSelection:
    """Tests for get_planning_model() and escalate_planning_model()."""

    def test_get_planning_model_delegates_to_resolver(self) -> None:
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview") as mock_resolve:
            result = get_planning_model("XS")
        mock_resolve.assert_called_once_with("planning", "XS")
        assert result == "gemini-3-flash-preview"

    def test_get_planning_model_l_delegates_to_resolver(self) -> None:
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_planning_model("L")
        mock_resolve.assert_called_once_with("planning", "L")
        assert result == "gemini-3-pro-preview"

    def test_get_planning_model_returns_none_for_auto_mode(self) -> None:
        with patch("scripts.llm.model_registry.resolve_model", return_value=None):
            result = get_planning_model("S")
        assert result is None

    def test_env_override_takes_precedence_via_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_MODEL_PLANNING", "my-custom-model")
        result = get_planning_model("XS")
        assert result == "my-custom-model"

    def test_env_override_cleared_returns_resolver_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_PLANNING", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview"):
            result = get_planning_model("XS")
        assert result == "gemini-3-flash-preview"

    def test_escalate_under_threshold_returns_current(self) -> None:
        rec_id = "rec-escalate-plan-01"
        plan_mod._PLANNING_FAILURE_COUNT.pop(rec_id, None)
        with patch.object(model_registry_mod, "escalate_model") as mock_esc:
            result = escalate_planning_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_not_called()
        assert result == "gemini-3-flash-preview"

    def test_escalate_at_threshold_calls_resolver(self) -> None:
        rec_id = "rec-escalate-plan-02"
        plan_mod._PLANNING_FAILURE_COUNT[rec_id] = 1  # next call hits threshold
        with (
            patch.object(model_registry_mod, "escalate_model", return_value="gemini-3-pro-preview") as mock_esc,
            patch.object(model_registry_mod, "get_model_tier", return_value="flash") as mock_tier,
        ):
            result = escalate_planning_model(rec_id, "gemini-3-flash-preview")
        mock_tier.assert_called_once_with("gemini-3-flash-preview")
        mock_esc.assert_called_once_with("planning", "flash")
        assert result == "gemini-3-pro-preview"

    def test_escalate_returns_none_at_top_of_hierarchy(self) -> None:
        rec_id = "rec-escalate-plan-03"
        plan_mod._PLANNING_FAILURE_COUNT[rec_id] = 1
        with (
            patch.object(model_registry_mod, "escalate_model", return_value=None),
            patch.object(model_registry_mod, "get_model_tier", return_value="pro"),
        ):
            result = escalate_planning_model(rec_id, "gemini-3-pro-preview")
        assert result is None

    def test_escalate_resets_counter_on_escalation(self) -> None:
        rec_id = "rec-escalate-plan-04"
        plan_mod._PLANNING_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "escalate_model", return_value=None),
            patch.object(model_registry_mod, "get_model_tier", return_value="unknown"),
        ):
            escalate_planning_model(rec_id, "gpt-5-mini")
            escalate_planning_model(rec_id, "gpt-5-mini")  # triggers escalation + reset
        # After reset, next call should not escalate (threshold not reached)
        with patch.object(model_registry_mod, "escalate_model") as mock_esc:
            result = escalate_planning_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_not_called()
        assert result == "gemini-3-flash-preview"

    def test_get_plan_timeout_defaults_to_600(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLAN_TIMEOUT_SECS", raising=False)
        assert get_plan_timeout_secs() == 600

    def test_get_plan_timeout_invalid_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLAN_TIMEOUT_SECS", "not-a-number")
        assert get_plan_timeout_secs() == 600

    def test_failure_count_cleared_on_successful_generate(self, tmp_path: Path) -> None:
        """_PLANNING_FAILURE_COUNT entry is removed on successful generate_initial_plan call."""
        import scripts.executor.plan as _plan_mod
        from scripts.executor.plan import generate_initial_plan

        rec_id = "rec-failure-reset-001"
        _plan_mod._PLANNING_FAILURE_COUNT[rec_id] = 2  # pre-set

        rec = {
            "id": rec_id,
            "title": "Test rec",
            "effort": "S",
            "file": "",
            "context": "ctx",
            "acceptance": "grep -q x y",
            "dependencies": [],
        }
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = (
            "### Step 1: Do thing\n**File**: foo.py\n**Action**: modify\n**Description**: desc\n**Acceptance**: `echo ok`\n"
        )
        mock_result.model = "gpt-5.4"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0
        mock_result.session_id = ""

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _tmpl = (
            "{rec_id} {title} {context} {file} {acceptance}"
            " {dependencies} {effort} {file_content_section} {test_content_section}"
        )
        (prompts_dir / "planning.prompt.md").write_text(_tmpl, encoding="utf-8")

        with (
            patch.object(_plan_mod, "PROMPTS_DIR", prompts_dir),
            patch("scripts.executor.plan.llm_call", return_value=mock_result),
            patch(
                "scripts.executor.step_runner.gather_step_context",
                return_value={"file_content": "", "test_content": "", "pattern_content": ""},
            ),
        ):
            generate_initial_plan(rec)

        assert rec_id not in _plan_mod._PLANNING_FAILURE_COUNT


class TestPlanningContextFileMode:
    """Tests for workspace-file invocation in planning functions."""

    def test_generate_initial_plan_acceptance_challenge_fast_fails(self, tmp_path: Path) -> None:
        """Acceptance challenge output should update JSONL once and return fast-fail status."""
        test_rec = {
            "id": "rec-410",
            "title": "Test recommendation",
            "effort": "S",
            "source": "testing",
            "file": "tests/test_plan_audit.py",
            "context": "Target file already contains requested tests.",
            "acceptance": "python -m pytest tests/test_plan_audit.py::TestCheckPrUrls -x -q",
            "dependencies": [],
        }

        mock_result = LLMResult(
            exit_code=0,
            content=(
                "ACCEPTANCE_CHALLENGE: Target file already contains the requested tests.\n"
                "EVIDENCE: TestCheckPrUrls already exists in tests/test_plan_audit.py.\n"
                "SUGGESTED_FIX: `python -m pytest tests/test_plan_audit.py::TestAuditPrUrls -x -q`\n"
            ),
            tokens_in=500,
            tokens_out=0,
            model="gpt-5.4",
            cost_usd=0.0,
            session_id="",
        )

        mock_context = {"file_content": "", "test_content": "", "pattern_content": ""}

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        template = (
            "{rec_id} {title} {context} {file} {acceptance} "
            "{dependencies} {effort} {file_content_section} {test_content_section}"
        )
        (prompts_dir / "planning.prompt.md").write_text(template, encoding="utf-8")

        with (
            patch.object(plan_mod, "PROMPTS_DIR", prompts_dir),
            patch.object(plan_mod, "llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.gather_step_context", return_value=mock_context),
            patch("scripts.executor.jsonl_store.update_recommendation_status", return_value=True) as mock_update,
        ):
            result = generate_initial_plan(test_rec)

        assert result.status == "acceptance_challenged"
        mock_update.assert_called_once_with(
            "rec-410",
            {
                "status": "failed",
                "failure_reason": "acceptance_challenged: Target file already contains the requested tests.",
                "challenge_reason": "Target file already contains the requested tests.",
                "suggested_acceptance": "python -m pytest tests/test_plan_audit.py::TestAuditPrUrls -x -q",
            },
        )

    def test_generate_initial_plan_uses_context_file(self) -> None:
        """Verify generate_initial_plan passes context_file_path and inline_instruction."""
        test_rec = {
            "id": "rec-253",
            "title": "Test recommendation",
            "effort": "S",
            "source": "testing",
            "file": "test.py",
        }

        mock_result = LLMResult(
            exit_code=0,
            content="### Step 1: Test\n**File**: test.py\n**Action**: create\n"
            "**Description**: Test\n**Acceptance**: `python test.py`\n",
            tokens_in=500,
            tokens_out=0,
            model="claude-haiku-4.5",
            cost_usd=0.0,
            session_id="",
        )

        mock_context = {"file_content": "", "test_content": ""}

        with (
            patch.object(plan_mod, "llm_call", return_value=mock_result) as mock_call,
            patch("scripts.executor.step_runner.gather_step_context", return_value=mock_context),
        ):
            result = generate_initial_plan(test_rec)

            # Verify llm_call was called with context_file_path and inline_instruction
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert "context_file_path" in call_kwargs
            assert "plan-gen" in call_kwargs["context_file_path"]
            assert "inline_instruction" in call_kwargs
            assert "step-by-step plan" in call_kwargs["inline_instruction"]
            assert result.rec_id == "rec-253"

    def test_critique_plan_uses_context_file(self) -> None:
        """Verify critique_plan passes context_file_path and inline_instruction."""
        test_plan = ExecutionPlan(
            rec_id="rec-253",
            slug="test-slug",
            revision=1,
            timestamp="2026-04-11T20:00:00Z",
            status="draft",
            model="claude-haiku-4.5",
            tokens_used=500,
            steps=[{"n": 1, "file": "test.py", "action": "create"}],
            plan_text="### Step 1: Test\n**File**: test.py\n**Action**: create\n"
            "**Description**: Test\n**Acceptance**: `python test.py`\n",
        )

        mock_result = LLMResult(
            exit_code=0,
            content="VERDICT: APPROVED\n",
            tokens_in=300,
            tokens_out=0,
            model="claude-haiku-4.5",
            cost_usd=0.0,
            session_id="",
        )

        with (
            patch.object(plan_mod, "llm_call", return_value=mock_result) as mock_call,
            patch.object(plan_mod, "load_prompt", return_value=("template", "hash")),
        ):
            result = critique_plan(test_plan)

            # Verify llm_call was called with context_file_path and inline_instruction
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert "context_file_path" in call_kwargs
            assert "plan-critique" in call_kwargs["context_file_path"]
            assert "inline_instruction" in call_kwargs
            assert "VERDICT" in call_kwargs["inline_instruction"]
            assert result["verdict"] == "approved"

    def test_refine_plan_uses_context_file(self) -> None:
        """Verify refine_plan passes context_file_path and inline_instruction."""
        test_plan = ExecutionPlan(
            rec_id="rec-253",
            slug="test-slug",
            revision=1,
            timestamp="2026-04-11T20:00:00Z",
            status="critique",
            model="claude-haiku-4.5",
            tokens_used=500,
            steps=[{"n": 1, "file": "test.py", "action": "create"}],
            plan_text="### Step 1: Test\n**File**: test.py\n**Action**: create\n"
            "**Description**: Test\n**Acceptance**: `python test.py`\n",
            critique_history=[
                {
                    "revision": 1,
                    "verdict": "needs_revision",
                    "feedback": "needs work",
                }
            ],
        )
        test_critique = {
            "verdict": "needs_revision",
            "feedback": "needs work",
        }
        test_rec = {
            "id": "rec-253",
            "title": "Test recommendation",
            "context": "Test context",
            "file": "test.py",
            "acceptance": "python test.py",
            "dependencies": [],
            "effort": "S",
        }

        mock_result = LLMResult(
            exit_code=0,
            content="### Step 1: Refined\n**File**: test.py\n**Action**: create\n"
            "**Description**: Refined\n**Acceptance**: `python test.py`\n",
            tokens_in=400,
            tokens_out=0,
            model="claude-haiku-4.5",
            cost_usd=0.0,
            session_id="",
        )

        with (
            patch.object(plan_mod, "llm_call", return_value=mock_result) as mock_call,
            patch.object(plan_mod, "load_prompt", return_value=("template", "hash")),
        ):
            result = refine_plan(test_plan, test_critique, test_rec)

            # Verify llm_call was called with context_file_path and inline_instruction
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args[1]
            assert "context_file_path" in call_kwargs
            assert "plan-refine" in call_kwargs["context_file_path"]
            assert "inline_instruction" in call_kwargs
            assert "Refine" in call_kwargs["inline_instruction"]
            assert result.revision == 2


class TestScopeValidationIntegration:
    """Regression tests for step-scope filtering inside generate/refine."""

    # Template that satisfies all format placeholders used by
    # generate_initial_plan and refine_plan.
    _PLANNING_TMPL = (
        "{rec_id} {title} {context} {file} {acceptance}"
        " {dependencies} {effort} {file_content_section}"
        " {test_content_section}"
        " {acceptance_constraint} {complexity_warning}"
    )
    _REFINE_TMPL = (
        "{plan_text} {critique_text} {rec_id} {title} {context} {file} {acceptance} {dependencies} {effort} {scope_files}"
    )

    # -- generate_initial_plan tests --

    def test_generate_rejects_out_of_scope_step(self, tmp_path: Path) -> None:
        """Steps targeting files outside the rec scope are dropped."""
        rec = {
            "id": "rec-scope-gen-01",
            "title": "Scoped rec",
            "effort": "S",
            "file": "scripts/executor/plan.py",
            "context": "ctx",
            "acceptance": "grep -q x y",
            "dependencies": [],
        }
        # LLM returns two steps: one in scope, one out of scope
        stdout = (
            "### Step 1: Fix plan\n"
            "**File**: scripts/executor/plan.py\n"
            "**Action**: modify\n"
            "**Description**: fix\n"
            "**Acceptance**: `echo ok`\n"
            "\n"
            "### Step 2: Touch unrelated\n"
            "**File**: scripts/executor/step_runner.py\n"
            "**Action**: modify\n"
            "**Description**: bad scope\n"
            "**Acceptance**: `echo bad`\n"
        )
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = stdout
        mock_result.model = "gpt-5.4"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0
        mock_result.session_id = ""

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "planning.prompt.md").write_text(self._PLANNING_TMPL, encoding="utf-8")

        mock_ctx = {
            "file_content": "",
            "test_content": "",
            "pattern_content": "",
        }
        with (
            patch.object(plan_mod, "PROMPTS_DIR", prompts_dir),
            patch(
                "scripts.executor.plan.llm_call",
                return_value=mock_result,
            ),
            patch(
                "scripts.executor.step_runner.gather_step_context",
                return_value=mock_ctx,
            ),
        ):
            plan = generate_initial_plan(rec)

        assert plan.status == "draft"
        assert len(plan.steps) == 1
        assert plan.steps[0]["file"] == "scripts/executor/plan.py"

    def test_generate_keeps_all_when_no_target_file(self, tmp_path: Path) -> None:
        """Empty rec file means no scope filtering -- all steps kept."""
        rec = {
            "id": "rec-scope-gen-02",
            "title": "No-target rec",
            "effort": "S",
            "file": "",
            "context": "ctx",
            "acceptance": "echo done",
            "dependencies": [],
        }
        stdout = (
            "### Step 1: A\n"
            "**File**: any/file.py\n"
            "**Action**: modify\n"
            "**Description**: a\n"
            "**Acceptance**: `echo a`\n"
            "\n"
            "### Step 2: B\n"
            "**File**: other/file.py\n"
            "**Action**: modify\n"
            "**Description**: b\n"
            "**Acceptance**: `echo b`\n"
        )
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = stdout
        mock_result.model = "gpt-5.4"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0
        mock_result.session_id = ""

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "planning.prompt.md").write_text(self._PLANNING_TMPL, encoding="utf-8")

        mock_ctx = {
            "file_content": "",
            "test_content": "",
            "pattern_content": "",
        }
        with (
            patch.object(plan_mod, "PROMPTS_DIR", prompts_dir),
            patch(
                "scripts.executor.plan.llm_call",
                return_value=mock_result,
            ),
            patch(
                "scripts.executor.step_runner.gather_step_context",
                return_value=mock_ctx,
            ),
        ):
            plan = generate_initial_plan(rec)

        assert plan.status == "draft"
        assert len(plan.steps) == 2

    # -- refine_plan tests --

    def test_refine_rejects_out_of_scope_step(self, tmp_path: Path) -> None:
        """Refined plan steps outside rec scope are filtered out."""
        rec = {
            "id": "rec-scope-ref-01",
            "title": "Scoped refine",
            "context": "ctx",
            "file": "scripts/executor/plan.py",
            "acceptance": "echo ok",
            "dependencies": [],
            "effort": "S",
        }
        existing_plan = ExecutionPlan(
            rec_id="rec-scope-ref-01",
            slug="scope-ref",
            revision=1,
            timestamp="2026-04-17T00:00:00Z",
            status="critique",
            model="gpt-5.4",
            tokens_used=100,
            steps=[
                {
                    "n": 1,
                    "file": "scripts/executor/plan.py",
                    "action": "modify",
                }
            ],
            plan_text="### Step 1: X\n**File**: scripts/executor/plan.py\n",
            critique_history=[],
        )
        critique = {
            "verdict": "needs_revision",
            "suggestions": ["fix scope"],
        }
        # Refined output adds an out-of-scope step
        stdout = (
            "### Step 1: Fix plan\n"
            "**File**: scripts/executor/plan.py\n"
            "**Action**: modify\n"
            "**Description**: fix\n"
            "**Acceptance**: `echo ok`\n"
            "\n"
            "### Step 2: Stray edit\n"
            "**File**: scripts/executor/postflight.py\n"
            "**Action**: modify\n"
            "**Description**: out of scope\n"
            "**Acceptance**: `echo bad`\n"
        )
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = stdout
        mock_result.model = "gpt-5.4"
        mock_result.tokens_in = 200
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch.object(
                plan_mod,
                "load_prompt",
                return_value=(self._REFINE_TMPL, "abc123"),
            ),
            patch(
                "scripts.executor.plan.llm_call",
                return_value=mock_result,
            ),
            patch.object(plan_mod, "save_plan"),
        ):
            refined = refine_plan(existing_plan, critique, rec)

        assert refined.status == "draft"
        assert len(refined.steps) == 1
        assert refined.steps[0]["file"] == "scripts/executor/plan.py"

    def test_refine_keeps_all_when_no_target_file(self, tmp_path: Path) -> None:
        """Refine with empty rec file keeps all steps."""
        rec = {
            "id": "rec-scope-ref-02",
            "title": "No-target refine",
            "context": "ctx",
            "file": "",
            "acceptance": "echo ok",
            "dependencies": [],
            "effort": "S",
        }
        existing_plan = ExecutionPlan(
            rec_id="rec-scope-ref-02",
            slug="scope-ref-02",
            revision=1,
            timestamp="2026-04-17T00:00:00Z",
            status="critique",
            model="gpt-5.4",
            tokens_used=100,
            steps=[{"n": 1, "file": "x.py", "action": "modify"}],
            plan_text="### Step 1: X\n**File**: x.py\n",
            critique_history=[],
        )
        critique = {
            "verdict": "needs_revision",
            "suggestions": ["improve"],
        }
        stdout = (
            "### Step 1: A\n"
            "**File**: any/a.py\n"
            "**Action**: modify\n"
            "**Description**: a\n"
            "**Acceptance**: `echo a`\n"
            "\n"
            "### Step 2: B\n"
            "**File**: other/b.py\n"
            "**Action**: modify\n"
            "**Description**: b\n"
            "**Acceptance**: `echo b`\n"
        )
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.content = stdout
        mock_result.model = "gpt-5.4"
        mock_result.tokens_in = 200
        mock_result.tokens_out = 0
        mock_result.cost_usd = 1.0

        with (
            patch.object(
                plan_mod,
                "load_prompt",
                return_value=(self._REFINE_TMPL, "abc123"),
            ),
            patch(
                "scripts.executor.plan.llm_call",
                return_value=mock_result,
            ),
            patch.object(plan_mod, "save_plan"),
        ):
            refined = refine_plan(existing_plan, critique, rec)

        assert refined.status == "draft"
        assert len(refined.steps) == 2
