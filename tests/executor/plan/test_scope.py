"""plan step-scope compute/validate + scope-validation-integration tests: _compute_step_scope,
_validate_step_scope, generate_initial_plan, refine_plan (rec-2709 Wave 5).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.plan as plan_mod
from scripts.executor.plan import (
    ExecutionPlan,
    _compute_step_scope,
    _validate_step_scope,
    generate_initial_plan,
    refine_plan,
)


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
