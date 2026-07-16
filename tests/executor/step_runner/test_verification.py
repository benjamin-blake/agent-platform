"""step_runner verification / step-telemetry / venv-resolution / implementation-model-selection
tests: run_verification, get_implementation_model, escalate_implementation_model (rec-2709 Wave 5).
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.executor.step_runner as sr_mod
import scripts.llm.model_registry as model_registry_mod
from scripts.executor.step_runner import (
    OPUS_FALLBACK,
    StepOutcome,
    escalate_implementation_model,
    get_implementation_model,
    get_last_verification_output,
    get_step_timeout_secs,
    implement_step,
    run_verification,
)


class TestImplementationModelSelection:
    """Tests for get_implementation_model() and escalate_implementation_model()."""

    def test_xs_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-flash-preview") as mock_resolve:
            result = get_implementation_model("XS")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="")
        assert result == "gemini-3-flash-preview"

    def test_l_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("L")
        mock_resolve.assert_called_once_with("implementation", "L", file_path="")
        assert result == "gemini-3-pro-preview"

    def test_executor_file_passes_file_path_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XS", "scripts/executor/plan.py")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="scripts/executor/plan.py")
        assert result == "gemini-3-pro-preview"

    def test_validate_file_passes_file_path_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XS", "scripts/validate.py")
        mock_resolve.assert_called_once_with("implementation", "XS", file_path="scripts/validate.py")
        assert result == "gemini-3-pro-preview"

    def test_env_override_takes_precedence_via_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_MODEL_EXECUTION", "my-override-model")
        result = get_implementation_model("XS")
        assert result == "my-override-model"

    def test_returns_none_for_auto_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value=None):
            result = get_implementation_model("S")
        assert result is None

    def test_opus_fallback_constant_retained(self) -> None:
        # OPUS_FALLBACK is retained for backwards compatibility with external importers.
        assert OPUS_FALLBACK == "claude-opus-4.6"

    def test_escalate_under_threshold_returns_current(self) -> None:
        rec_id = "rec-impl-escalate-01"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        # Use 'auto' tier (threshold=3) to stay under threshold on first call
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, None)  # auto mode, None model
        mock_esc.assert_not_called()
        assert result is None  # returned current_model (None for auto mode)

    def test_escalate_flash_tier_triggers_after_1_failure(self) -> None:
        rec_id = "rec-impl-escalate-02"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="flash"),
            patch.object(model_registry_mod, "escalate_model", return_value=None) as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_called_once_with("implementation", "flash")
        assert result is None  # auto mode (flash -> auto = None in Gemini config)

    def test_escalate_auto_tier_does_not_trigger_after_1_failure(self) -> None:
        rec_id = "rec-impl-escalate-03"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="auto"),
            patch.object(model_registry_mod, "escalate_model") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, None)  # auto mode
        mock_esc.assert_not_called()
        assert result is None  # count=1, threshold for non-flash = 3

    def test_escalate_at_pro_returns_none_top_of_hierarchy(self) -> None:
        rec_id = "rec-impl-escalate-04"
        sr_mod._IMPL_FAILURE_COUNT[rec_id] = 2  # next hit = 3 (threshold for non-flash)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="pro"),
            patch.object(model_registry_mod, "escalate_model", return_value=None),
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-pro-preview")
        assert result is None

    def test_escalate_delegates_to_resolver(self) -> None:
        rec_id = "rec-impl-escalate-05"
        sr_mod._IMPL_FAILURE_COUNT.pop(rec_id, None)
        with (
            patch.object(model_registry_mod, "get_model_tier", return_value="flash"),
            patch.object(model_registry_mod, "escalate_model", return_value="gemini-3-pro-preview") as mock_esc,
        ):
            result = escalate_implementation_model(rec_id, "gemini-3-flash-preview")
        mock_esc.assert_called_once_with("implementation", "flash")
        assert result == "gemini-3-pro-preview"

    def test_l_executor_instructions_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("L", "config/agent/executor/instructions/executor-planning.instructions.md")
        mock_resolve.assert_called_once_with(
            "implementation",
            "L",
            file_path="config/agent/executor/instructions/executor-planning.instructions.md",
        )
        assert result == "gemini-3-pro-preview"

    def test_xl_github_agents_delegates_to_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)
        with patch("scripts.llm.model_registry.resolve_model", return_value="gemini-3-pro-preview") as mock_resolve:
            result = get_implementation_model("XL", ".github/agents/code-review.agent.md")
        mock_resolve.assert_called_once_with(
            "implementation",
            "XL",
            file_path=".github/agents/code-review.agent.md",
        )
        assert result == "gemini-3-pro-preview"

    def test_step_timeout_defaults_to_900(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COPILOT_STEP_TIMEOUT_SECS", raising=False)
        assert get_step_timeout_secs() == 900

    def test_step_timeout_invalid_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_STEP_TIMEOUT_SECS", "invalid")
        assert get_step_timeout_secs() == 900


class TestRunVerification:
    """Tests for run_verification()."""

    def test_returns_skipped_for_empty_string(self) -> None:
        result = run_verification("")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_skipped_for_whitespace(self) -> None:
        result = run_verification("   ")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_skipped_for_unparseable_prose(self) -> None:
        result = run_verification("The system should work correctly.")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_passed_when_command_exits_zero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("ok\n", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_verification("`echo ok`")
        assert result["passed"] is True
        assert result["skipped"] is False
        assert result["rejected"] is False
        assert get_last_verification_output() == "ok"

    def test_returns_failed_when_command_exits_nonzero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("", "error\n")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", return_value=mock_proc):
            result = run_verification("`grep -q 'missing' file.py`")
        assert result["passed"] is False
        assert result["skipped"] is False
        assert result["error"] == "exit 1"
        assert get_last_verification_output() == "error"

    def test_rejects_python_c_one_liner(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_verification('`python -c "import sys"`')
        assert result["passed"] is False
        assert result["rejected"] is True
        mock_popen.assert_not_called()

    def test_rejects_python_c_single_quotes(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen") as mock_popen:
            result = run_verification("`python -c 'import sys'`")
        assert result["passed"] is False
        assert result["rejected"] is True
        mock_popen.assert_not_called()

    def test_returns_skipped_when_bash_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            result = run_verification("`echo hello`")
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_returns_failed_on_timeout(self) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=300)
        mock_proc.pid = 12345
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("shutil.which", return_value="/usr/bin/bash"),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("scripts.executor.step_runner.kill_process_tree"),
        ):
            result = run_verification("`sleep 999`")
        assert result["passed"] is False
        assert result["skipped"] is False
        assert "timed out" in result["error"].lower()

    def test_normalises_python_script_to_module(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")
        mock_proc.__enter__ = lambda self: self
        mock_proc.__exit__ = MagicMock(return_value=False)

        captured_cmd: list[str] = []

        def capture_popen(args, **kwargs):
            captured_cmd.extend(args)
            return mock_proc

        with patch("shutil.which", return_value="/usr/bin/bash"), patch("subprocess.Popen", side_effect=capture_popen):
            run_verification("`python scripts/foo.py --check`")

        bash_c_arg = captured_cmd[-1] if captured_cmd else ""
        assert "-m scripts.foo" in bash_c_arg


class TestEmitStepTelemetry:
    """Verify emit_step is called from implement_step's finally block."""

    def _make_step(self, file: str = "src/module.py", action: str = "modify") -> dict:
        return {"n": 1, "title": "telemetry test step", "file": file, "action": action, "description": "d", "acceptance": ""}

    def test_emit_step_called_on_success(self) -> None:
        """emit_step is called with outcome=SUCCESS.value after a successful implement_step."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.5
        mock_result.session_id = "sess-tel"

        mock_val_proc = MagicMock()
        mock_val_proc.returncode = 0
        mock_val_proc.communicate.return_value = ("ok", "")
        mock_val_proc.__enter__ = lambda self: self
        mock_val_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_format", return_value=True),
            patch("subprocess.Popen", return_value=mock_val_proc),
            patch("scripts.executor.step_runner.emit_step") as mock_emit_step,
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
        ):
            outcome, reqs, _, _ = implement_step(step, "rec-tel-001", 1, 1)

        assert outcome == StepOutcome.SUCCESS
        mock_emit_step.assert_called_once()
        assert mock_emit_step.call_args.kwargs.get("outcome") == StepOutcome.SUCCESS.value

    def test_emit_step_called_on_ruff_error(self) -> None:
        """emit_step is called even when implement_step returns RUFF_ERROR."""
        step = self._make_step()

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.model = "test-model"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 0
        mock_result.cost_usd = 0.5

        with (
            patch("scripts.executor.step_runner.llm_call", return_value=mock_result),
            patch("scripts.executor.step_runner.auto_format_test_files", return_value=True),
            patch("scripts.executor.step_runner._run_ruff_fix", return_value=False),
            patch("scripts.executor.step_runner.emit_step") as mock_emit_step,
            patch("scripts.executor.step_runner.emit_transcript"),
            patch("scripts.executor.step_runner.emit_process_event"),
        ):
            outcome, _, _, _ = implement_step(step, "rec-tel-002", 1, 1)

        assert outcome == StepOutcome.RUFF_ERROR
        mock_emit_step.assert_called_once()
        assert mock_emit_step.call_args.kwargs.get("outcome") == StepOutcome.RUFF_ERROR.value


class TestVenvPythonResolution:
    """Verify Linux-first venv resolution in step_runner.py module-level globals."""

    @pytest.fixture(autouse=True)
    def _restore_module_state(self) -> None:
        # Snapshot the original module dict before any reloads so teardown can
        # restore it exactly. A plain reload in teardown creates a new StepOutcome
        # class that breaks module-level `from ... import StepOutcome` bindings in
        # other test classes running after this one (order-dependent failure).
        original_dict = dict(sr_mod.__dict__)
        importlib.reload(sr_mod)
        yield
        sr_mod.__dict__.clear()
        sr_mod.__dict__.update(original_dict)

    def test_linux_layout_preferred_when_both_present(self) -> None:
        with patch.object(Path, "exists", return_value=True):
            importlib.reload(sr_mod)
        assert sr_mod._PROJECT_PYTHON.endswith("bin/python")

    def test_windows_fallback_when_linux_missing(self) -> None:
        def _exists(self: Path) -> bool:
            return "python.exe" in str(self) or "ruff.exe" in str(self)

        with patch.object(Path, "exists", _exists):
            importlib.reload(sr_mod)
        assert "python.exe" in sr_mod._PROJECT_PYTHON
