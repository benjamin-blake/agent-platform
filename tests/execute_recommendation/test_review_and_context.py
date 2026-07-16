"""Code-review gate, planning-context injection, and postflight-quarantine parsing tests (rec-2709 Wave 2)."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.execute_recommendation import (
    ExecutionPlan,
    _code_review_gate,
    _get_quarantined_validation_failures,
    generate_initial_plan,
)


class TestCodeReviewGate:
    """Tests for _code_review_gate()."""

    def _make_plan(self, steps=None):
        return ExecutionPlan(
            rec_id="rec-test",
            slug="rec-test",
            revision=1,
            timestamp="2026-04-02T00:00:00Z",
            status="approved",
            model="test",
            tokens_used=100,
            steps=steps or [],
            plan_text="## Step 1\nModify foo.py",
        )

    def test_passed_when_no_blocking_findings(self, tmp_path):
        """Returns (True, []) when model reports no CRITICAL/HIGH issues."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="MEDIUM: minor style issue\nGATE: PASSED",
            model="claude-haiku-4.5",
            session_id="",
            cost_usd=0.33,
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True
        assert cost == pytest.approx(0.33)  # haiku multiplier
        assert blocking == []

    def test_failed_when_critical_finding(self, tmp_path):
        """Returns (False, cost, findings) when model reports CRITICAL issue."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="CRITICAL: scripts/foo.py: SQL injection risk\nGATE: FAILED â€” 1 blocking issue",
            session_id="",
        )

        _tmpl = "template {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"
        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) >= 1
        assert any("CRITICAL" in b.upper() for b in blocking)

    def test_failed_when_high_finding(self, tmp_path):
        """Returns (False, ...) when model reports HIGH issue."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content="HIGH: tests/test_foo.py: missing test coverage for new function\nGATE: FAILED â€” 1 blocking issue",
            session_id="",
        )

        _tmpl = "template {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"
        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False

    def test_passes_when_prompt_missing(self):
        """Returns (True, 0, []) without raising when prompt file not found."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()

        with patch("scripts.executor.postflight.load_prompt", side_effect=FileNotFoundError("not found")):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True
        assert cost == 0.0
        assert blocking == []

    def test_passes_when_cli_fails(self):
        """Returns (True, ...) without raising when llm_call returns non-zero exit."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(exit_code=1, content="", session_id="")
        _tmpl = "t {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is True

    def test_rejects_false_positives_in_prose(self):
        """Rejects lines containing CRITICAL: or HIGH: as substring in prose."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=(
                "Critical Issue Check: Review the following areas\n"
                "CRITICAL Issues Found: None\n"
                "Perfect! The telemetry structure is correct.\n"
                "CRITICAL: Missing error handling in src/foo.py"
            ),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 1
        assert "Missing error handling" in blocking[0]

    def test_accepts_properly_formatted_findings(self):
        """Accepts findings starting with CRITICAL: or HIGH: at line start."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=(
                "CRITICAL: Missing bounds check in src/validator.py\n"
                "**HIGH**: Unescaped user input in src/api.py\n"
                "  CRITICAL: Potential SQL injection"
            ),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 3
        assert any("Missing bounds check" in b for b in blocking)
        assert any("Unescaped user input" in b for b in blocking)
        assert any("SQL injection" in b for b in blocking)

    def test_rejects_all_caps_section_headers(self):
        """Rejects all-caps lines without file paths (section headers)."""
        rec = {"id": "rec-test", "title": "T", "acceptance": "AC"}
        plan = self._make_plan()
        mock_result = MagicMock(
            exit_code=0,
            content=("CRITICAL ISSUES FOUND\nHIGH PRIORITY ITEMS\nCRITICAL: scripts/auth.py: Missing authentication\n"),
            model="claude-haiku-4.5",
            session_id="",
        )
        _tmpl = "Review {rec_id} {title} {acceptance} {plan_steps} {changed_files} {files_block}"

        with (
            patch("scripts.executor.postflight.load_prompt", return_value=(_tmpl, "abc")),
            patch("scripts.executor.postflight.llm_call", return_value=mock_result),
        ):
            passed, cost, blocking = _code_review_gate(rec, plan, [])

        assert passed is False
        assert len(blocking) == 1
        assert "Missing authentication" in blocking[0]


class TestPlanningContextInjection:
    """Tests for planning-time file context injection in generate_initial_plan()."""

    def _make_result(self):
        _stdout = (
            "### Step 1: Edit file\n**File**: scripts/foo.py\n**Action**: modify\n"
            "**Description**: Do it\n**Acceptance**: grep -q foo scripts/foo.py"
        )
        return MagicMock(
            exit_code=0,
            content=_stdout,
            tokens_in=100,
            tokens_out=0,
            model="test-model",
            session_id="ses-001",
        )

    def test_file_content_injected_into_prompt(self, tmp_path):
        """generate_initial_plan passes file_content_section to the planning prompt."""
        rec = {
            "id": "rec-xy",
            "title": "Add docstring",
            "context": "ctx",
            "file": "scripts/foo.py",
            "acceptance": "grep -q docstring scripts/foo.py",
            "dependencies": [],
            "effort": "XS",
        }

        captured_prompts = []

        def fake_llm_call(prompt, **kwargs):
            captured_prompts.append(prompt)
            return self._make_result()

        with (
            patch(
                "scripts.executor.plan.load_prompt",
                return_value=(
                    "{file_content_section}{test_content_section}"
                    "{rec_id}{title}{context}{file}{acceptance}{dependencies}{effort}",
                    "hash123",
                ),
            ),
            patch("scripts.executor.step_runner.gather_step_context") as mock_ctx,
            patch("scripts.executor.plan.llm_call", side_effect=fake_llm_call),
            patch("scripts.executor.plan.os.getenv", return_value="true"),
        ):
            mock_ctx.return_value = {
                "file_content": "def foo(): pass",
                "test_content": "",
                "pattern_content": "",
            }
            generate_initial_plan(rec)

        assert len(captured_prompts) == 1
        assert "def foo(): pass" in captured_prompts[0]

    def test_empty_context_does_not_fail(self, tmp_path):
        """generate_initial_plan handles missing file gracefully (no file_content)."""
        rec = {
            "id": "rec-xy",
            "title": "New feature",
            "context": "ctx",
            "file": "scripts/new.py",
            "acceptance": "test -f scripts/new.py",
            "dependencies": [],
            "effort": "S",
        }

        _new_file_result = MagicMock(
            exit_code=0,
            content=(
                "### Step 1: Create file\n**File**: scripts/new.py\n**Action**: create\n"
                "**Description**: Create new module\n**Acceptance**: test -f scripts/new.py"
            ),
            tokens_in=100,
            tokens_out=0,
            model="test-model",
            session_id="ses-002",
        )
        with (
            patch(
                "scripts.executor.plan.load_prompt",
                return_value=(
                    "{file_content_section}{test_content_section}"
                    "{rec_id}{title}{context}{file}{acceptance}{dependencies}{effort}",
                    "hash456",
                ),
            ),
            patch("scripts.executor.step_runner.gather_step_context") as mock_ctx,
            patch("scripts.executor.plan.llm_call", return_value=_new_file_result),
            patch("scripts.executor.plan.os.getenv", return_value="false"),
        ):
            mock_ctx.return_value = {"file_content": "", "test_content": "", "pattern_content": ""}
            plan = generate_initial_plan(rec)

        assert plan is not None
        assert len(plan.steps) > 0


class TestPostflightValidationQuarantineParsing:
    """Tests for explicit postflight validation quarantine parsing."""

    def test_recognizes_known_baseline_test_as_quarantined(self):
        output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "    - Unit tests + coverage\n\n"
            "Fix all failures before committing.\n"
        )

        quarantined = _get_quarantined_validation_failures(output)

        assert quarantined == [
            "tests/test_execute_recommendation.py::TestPlanningContextInjection::test_empty_context_does_not_fail"
        ]

    def test_rejects_validation_output_with_additional_failed_checks(self):
        output = (
            "FAILED tests\\test_execute_recommendation.py::"
            "TestPlanningContextInjection::test_empty_context_does_not_fail"
            " - planner error\n"
            "=== Validation Summary (scope: python) ===\n"
            "Failed checks:\n"
            "    - Unit tests + coverage\n"
            "    - Lint (ruff check)\n\n"
            "Fix all failures before committing.\n"
        )

        assert _get_quarantined_validation_failures(output) == []
