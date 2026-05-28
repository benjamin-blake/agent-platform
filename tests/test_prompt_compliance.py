"""Tests for scripts/prompt_compliance.py."""

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "prompt_compliance.py"
_spec = importlib.util.spec_from_file_location("prompt_compliance", _SCRIPT_PATH)
_compliance = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_compliance)  # type: ignore[union-attr]
sys.modules["prompt_compliance"] = _compliance

parse_invariants = _compliance.parse_invariants
parse_retro_lite_log = _compliance.parse_retro_lite_log
parse_execution_state = _compliance.parse_execution_state
check_retro_lite_compliance = _compliance.check_retro_lite_compliance
check_plan_compliance = _compliance.check_plan_compliance


class TestParseInvariants:
    """Tests for parse_invariants()."""

    def test_parses_invariants_from_prompt(self, tmp_path: Path) -> None:
        """Valid ## Behavioural Invariants YAML block is parsed correctly."""
        prompt = tmp_path / "implement.prompt.md"
        prompt.write_text(
            "## Intent\n\nDo stuff.\n\n"
            "## Behavioural Invariants\n\n"
            "```yaml\n"
            "retro_lite_per_step: true\n"
            "checkpoint_per_step: true\n"
            "```\n\n"
            "## Step 1\n",
            encoding="utf-8",
        )
        result = parse_invariants(prompt)
        assert result == {"retro_lite_per_step": True, "checkpoint_per_step": True}

    def test_returns_empty_dict_when_no_section(self, tmp_path: Path) -> None:
        """Prompt without Behavioural Invariants returns empty dict."""
        prompt = tmp_path / "other.prompt.md"
        prompt.write_text("## Intent\n\nNo invariants here.\n", encoding="utf-8")
        result = parse_invariants(prompt)
        assert result == {}

    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path) -> None:
        """Missing file returns empty dict (no exception)."""
        result = parse_invariants(tmp_path / "nonexistent.prompt.md")
        assert result == {}

    def test_returns_empty_dict_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Malformed YAML in invariants block returns empty dict."""
        prompt = tmp_path / "bad.prompt.md"
        prompt.write_text(
            "## Behavioural Invariants\n\n```yaml\n: : bad yaml\n```\n",
            encoding="utf-8",
        )
        result = parse_invariants(prompt)
        assert result == {}

    def test_boolean_coercion(self, tmp_path: Path) -> None:
        """YAML true/false values are coerced to Python bool."""
        prompt = tmp_path / "coerce.prompt.md"
        prompt.write_text(
            "## Behavioural Invariants\n\n```yaml\nfoo: true\nbar: false\n```\n",
            encoding="utf-8",
        )
        result = parse_invariants(prompt)
        assert result["foo"] is True
        assert result["bar"] is False


class TestParseRetroLiteLog:
    """Tests for parse_retro_lite_log()."""

    def test_parses_valid_jsonl(self, tmp_path: Path) -> None:
        """Valid JSONL entries are parsed and returned."""
        log = tmp_path / ".retro-lite-log.jsonl"
        log.write_text(
            '{"timestamp": "2026-01-01T00:00:00Z", "session": "agent/foo", "friction": "none"}\n'
            '{"timestamp": "2026-01-02T00:00:00Z", "session": "agent/bar", "friction": "retry"}\n',
            encoding="utf-8",
        )
        result = parse_retro_lite_log(log)
        assert len(result) == 2
        assert result[0]["session"] == "agent/foo"

    def test_session_filter(self, tmp_path: Path) -> None:
        """session_filter returns only matching entries."""
        log = tmp_path / ".retro-lite-log.jsonl"
        log.write_text(
            '{"session": "agent/foo", "friction": "none"}\n{"session": "agent/bar", "friction": "retry"}\n',
            encoding="utf-8",
        )
        result = parse_retro_lite_log(log, session_filter="agent/foo")
        assert len(result) == 1
        assert result[0]["session"] == "agent/foo"

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed JSON lines are skipped without raising an exception."""
        log = tmp_path / ".retro-lite-log.jsonl"
        log.write_text(
            '{"session": "agent/foo", "friction": "none"}\nthis is not json\n{"session": "agent/bar", "friction": "retry"}\n',
            encoding="utf-8",
        )
        result = parse_retro_lite_log(log)
        assert len(result) == 2

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Missing log file returns empty list (no exception)."""
        result = parse_retro_lite_log(tmp_path / "nonexistent.jsonl")
        assert result == []


class TestParseExecutionState:
    """Tests for parse_execution_state()."""

    def test_parses_valid_json(self, tmp_path: Path) -> None:
        """Valid execution state JSON is parsed and returned as dict."""
        state = tmp_path / ".execution-state.json"
        state.write_text(
            json.dumps({"branch": "agent/foo", "current_step": 3, "total_steps": 5}),
            encoding="utf-8",
        )
        result = parse_execution_state(state)
        assert result is not None
        assert result["current_step"] == 3
        assert result["total_steps"] == 5

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Missing state file returns None (no exception)."""
        result = parse_execution_state(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        """Invalid JSON in state file returns None."""
        state = tmp_path / ".execution-state.json"
        state.write_text("not json", encoding="utf-8")
        result = parse_execution_state(state)
        assert result is None


class TestCheckRetroLiteCompliance:
    """Tests for check_retro_lite_compliance()."""

    def test_passes_when_entry_count_matches_steps(self) -> None:
        """No violations when retro-lite entry count equals total_steps."""
        invariants = {"retro_lite_per_step": True}
        entries = [
            {"session": "agent/foo"},
            {"session": "agent/foo"},
            {"session": "agent/foo"},
        ]
        state = {"total_steps": 3, "current_step": 3, "status": "COMPLETE"}
        violations = check_retro_lite_compliance(invariants, entries, state)
        assert violations == []

    def test_fails_when_entries_less_than_steps(self) -> None:
        """Violation raised when fewer retro entries than total_steps."""
        invariants = {"retro_lite_per_step": True}
        entries = [{"session": "agent/foo"}]
        state = {"total_steps": 3, "current_step": 1, "status": "IN_PROGRESS"}
        violations = check_retro_lite_compliance(invariants, entries, state)
        assert len(violations) == 1
        assert "retro_lite_per_step" in violations[0]

    def test_passes_when_invariant_not_set(self) -> None:
        """No violations when retro_lite_per_step is not in invariants."""
        invariants: dict = {}
        violations = check_retro_lite_compliance(invariants, [], None)
        assert violations == []

    def test_no_violations_when_state_is_none(self) -> None:
        """No violations when execution state is None (cannot check)."""
        invariants = {"retro_lite_per_step": True}
        violations = check_retro_lite_compliance(invariants, [], None)
        assert violations == []


class TestCheckPlanCompliance:
    """Tests for check_plan_compliance()."""

    def test_passes_for_completed_session(self, tmp_path: Path) -> None:
        """No violations when SESSION_LOG.md contains a table row (completed session)."""
        session_log = tmp_path / "SESSION_LOG.md"
        session_log.write_text(
            "# Session Log\n\n| Date | Branch | Done |\n|------|--------|------|\n| 2026-01-01 | agent/foo | Yes |\n",
            encoding="utf-8",
        )
        invariants = {"preflight_run": True}
        violations = check_plan_compliance(invariants, session_log)
        assert violations == []

    def test_violation_when_no_session_log(self, tmp_path: Path) -> None:
        """Violation raised when SESSION_LOG.md does not exist."""
        invariants = {"preflight_run": True}
        violations = check_plan_compliance(invariants, tmp_path / "missing_SESSION_LOG.md")
        assert len(violations) == 1
        assert "preflight_run" in violations[0]

    def test_passes_when_no_plan_invariants(self, tmp_path: Path) -> None:
        """No violations when none of the plan invariants are declared."""
        invariants = {"retro_lite_per_step": True}  # not a plan invariant
        violations = check_plan_compliance(invariants, tmp_path / "log.md")
        assert violations == []
