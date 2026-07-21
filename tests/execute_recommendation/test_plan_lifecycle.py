"""Plan/rec loading and plan authoring tests (rec-2709 Wave 2)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    ExecutionPlan,
    critique_plan,
    generate_initial_plan,
    load_prompt,
    load_recommendation,
    parse_steps_from_plan,
    save_plan,
)
from scripts.llm.utils import LLMResponseError


class TestLoadPrompt:
    """Test prompt loading from files."""

    def test_load_prompt_success(self, tmp_path):
        """Test loading a prompt file that exists."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test.prompt.md"
        prompt_file.write_text("Hello {name}!")

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            template, prompt_hash = load_prompt("test")
            assert template == "Hello {name}!", "Template content mismatch: expected 'Hello {name}!'"
            assert template.format(name="World") == "Hello World!", "Template formatting failed"
            assert isinstance(prompt_hash, str), "Prompt hash is not a string"
            assert len(prompt_hash) == 12, f"Prompt hash length is {len(prompt_hash)}, expected 12"

    def test_load_prompt_not_found(self, tmp_path):
        """Test loading a prompt that doesn't exist."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        with patch("scripts.executor.plan.PROMPTS_DIR", prompts_dir):
            with pytest.raises(FileNotFoundError, match="Prompt not found"):
                load_prompt("nonexistent")

    def test_load_prompt_real_files(self):
        """Test that real prompt files exist and load."""
        # Test actual prompt files exist
        for name in ["planning", "critique", "refine", "implement-step"]:
            template, prompt_hash = load_prompt(name)
            assert len(template) > 0, f"Template for {name} is empty"
            assert isinstance(template, str), f"Template for {name} is not a string"
            assert isinstance(prompt_hash, str), f"Hash for {name} is not a string"
            assert len(prompt_hash) == 12, f"Hash length for {name} is {len(prompt_hash)}, expected 12"


class TestLoadRecommendation:
    """Test recommendation loading."""

    def test_load_recommendation_found(self, tmp_path, monkeypatch):
        """Test loading a recommendation that exists."""
        monkeypatch.chdir(tmp_path)

        recs_file = tmp_path / "logs" / ".recommendations-log.jsonl"
        recs_file.parent.mkdir(parents=True)

        schema = "# Schema: test"
        entry1 = json.dumps({"id": "rec-100", "title": "Test", "risk": "low", "automatable": True, "effort": "S"})
        entry2 = json.dumps({"id": "rec-101", "title": "Other", "risk": "high", "automatable": False})

        recs_file.write_text(f"{schema}\n{entry1}\n{entry2}\n")

        with patch("scripts.execute_recommendation.RECS_JSONL", recs_file):
            rec = load_recommendation("rec-100")
            assert rec["id"] == "rec-100", f"Expected rec['id'] to be 'rec-100', got {rec['id']}"
            assert rec["title"] == "Test", f"Expected rec['title'] to be 'Test', got {rec['title']}"

    def test_load_recommendation_not_found(self, tmp_path, monkeypatch):
        """Test loading a recommendation that doesn't exist."""
        monkeypatch.chdir(tmp_path)

        recs_file = tmp_path / "logs" / ".recommendations-log.jsonl"
        recs_file.parent.mkdir(parents=True)

        schema = "# Schema: test"
        entry1 = json.dumps({"id": "rec-100", "title": "Test", "risk": "low"})

        recs_file.write_text(f"{schema}\n{entry1}\n")

        with patch("scripts.execute_recommendation.RECS_JSONL", recs_file):
            rec = load_recommendation("rec-999")
            assert rec is None, "Expected None for non-existent recommendation, got non-None value"


class TestParseStepsFromPlan:
    """Test plan step parsing."""

    def test_parse_structured_steps(self):
        """Test parsing structured step format."""
        plan_text = """
### Step 1: Create module
**File**: src/module.py
**Action**: create
**Description**: Create the new module with base classes
**Acceptance**: python -c "from src.module import X"

### Step 2: Add tests
**File**: tests/test_module.py
**Action**: create
**Description**: Add unit tests for the module
**Acceptance**: pytest tests/test_module.py
"""
        steps = parse_steps_from_plan(plan_text)
        assert len(steps) == 2, f"Expected 2 steps, got {len(steps)}"
        assert steps[0]["n"] == 1, f"Expected step 0 number to be 1, got {steps[0]['n']}"
        assert steps[0]["file"] == "src/module.py", f"Expected step 0 file to be 'src/module.py', got {steps[0]['file']}"
        assert steps[0]["action"] == "create", f"Expected step 0 action to be 'create', got {steps[0]['action']}"
        assert steps[1]["n"] == 2, f"Expected step 1 number to be 2, got {steps[1]['n']}"
        assert "tests" in steps[1]["file"], f"Expected 'tests' in step 1 file, got {steps[1]['file']}"

    def test_parse_numbered_list_fallback(self):
        """Test fallback to numbered list parsing."""
        plan_text = """
1. Create the config file
2. Update the main module
3. Run validation
"""
        steps = parse_steps_from_plan(plan_text)
        assert len(steps) == 3, f"Expected 3 steps, got {len(steps)}"
        assert steps[0]["n"] == 1, f"Expected step 0 number to be 1, got {steps[0]['n']}"
        assert "config" in steps[0]["title"].lower(), f"Expected 'config' in step 0 title, got {steps[0]['title']}"

    def test_parse_empty_plan(self):
        """Test parsing empty plan."""
        steps = parse_steps_from_plan("")
        assert steps == [], f"Expected empty list for empty plan, got {steps}"


class TestSavePlan:
    """Test plan saving to JSONL."""

    def test_save_plan(self, tmp_path, monkeypatch):
        """Test saving plan to JSONL."""
        plans_file = tmp_path / "logs" / ".execution-plans.jsonl"
        plans_file.parent.mkdir(parents=True)
        plans_file.write_text("")

        plan = ExecutionPlan(
            rec_id="rec-test",
            slug="test-slug",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="draft",
            model="test-model",
            tokens_used=100,
            steps=[{"n": 1, "title": "Test step"}],
            plan_text="Test plan",
        )

        with (
            patch("scripts.executor.plan.PLANS_JSONL", plans_file),
            patch("scripts.ops_portal.execution_plans.save_execution_plan"),
        ):
            save_plan(plan)

        content = plans_file.read_text()
        assert "rec-test" in content
        assert "test-slug" in content


class TestGenerateInitialPlan:
    """Test initial plan generation."""

    def test_generate_initial_plan_success(self, tmp_path):
        """Test successful plan generation."""
        rec = {"id": "rec-test", "title": "Test recommendation", "slug": "test"}

        plan_output = """
### Step 1: Create file
**File**: src/test.py
**Action**: create
**Description**: Create test file
**Acceptance**: python -m py_compile src/test.py
"""

        with patch("scripts.executor.plan.llm_call") as mock_call:
            mock_call.return_value = MagicMock(
                exit_code=0,
                content=plan_output,
                tokens_in=100,
                tokens_out=0,
                model="test-model",
            )
            plan = generate_initial_plan(rec)
            assert plan is not None
            assert plan.rec_id == "rec-test"
            assert plan.status == "draft"
            assert len(plan.steps) == 1

    def test_generate_initial_plan_failure(self):
        """Test plan generation failure raises LLMResponseError."""
        rec = {"id": "rec-test", "title": "Test"}

        with patch("scripts.executor.plan.llm_call") as mock_call:
            mock_call.return_value = MagicMock(exit_code=1, content="")
            with pytest.raises(LLMResponseError, match="CLI exited 1"):
                generate_initial_plan(rec)


class TestCritiquePlan:
    """Test plan critique."""

    def test_critique_plan_approved(self):
        """Test critique that approves plan."""
        plan = ExecutionPlan(
            rec_id="rec-test",
            slug="test",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="draft",
            model="test",
            tokens_used=100,
            steps=[],
            plan_text="Test plan",
        )

        with patch("scripts.executor.plan.llm_call") as mock_call:
            mock_call.return_value = MagicMock(
                exit_code=0,
                content="VERDICT: APPROVED\nPlan looks good.",
                tokens_in=50,
                tokens_out=0,
            )
            critique = critique_plan(plan)
            assert critique["verdict"] == "approved"

    def test_critique_plan_needs_revision(self):
        """Test critique that requests revision."""
        plan = ExecutionPlan(
            rec_id="rec-test",
            slug="test",
            revision=1,
            timestamp="2026-03-31T10:00:00Z",
            status="draft",
            model="test",
            tokens_used=100,
            steps=[],
            plan_text="Test plan",
        )

        with patch("scripts.executor.plan.llm_call") as mock_call:
            mock_call.return_value = MagicMock(
                exit_code=0,
                content="VERDICT: NEEDS_REVISION\n- Add error handling\n- Missing tests",
                tokens_in=50,
                tokens_out=0,
            )
            critique = critique_plan(plan)
            assert critique["verdict"] == "needs_revision"
            assert len(critique["suggestions"]) >= 1
