"""plan model-selection + planning-context-file-mode tests: get_planning_model,
escalate_planning_model, generate_initial_plan, critique_plan, refine_plan (rec-2709 Wave 5).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.plan as plan_mod
import scripts.llm.model_registry as model_registry_mod
from scripts.executor.plan import (
    ExecutionPlan,
    critique_plan,
    escalate_planning_model,
    generate_initial_plan,
    get_plan_timeout_secs,
    get_planning_model,
    refine_plan,
)
from scripts.llm.client import LLMResult


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
