"""Unit tests for scripts/copilot_wrapper.py

DEPRECATED: copilot_wrapper.py is superseded by llm_client.py (Bedrock).
These tests are skipped. See tests/test_llm_client.py for active coverage.
"""

import pytest

pytestmark = pytest.mark.skip(reason="copilot_wrapper.py deprecated; see test_llm_client.py")

import json  # noqa: E402
import subprocess  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from scripts.copilot_wrapper import (  # noqa: E402
    CopilotResponseError,
    _parse_otel_metrics,
    build_context_path,
    check_process_killswitch,
    check_recursion_guard,
    copilot_call,
    count_python_processes,
    parse_jsonl_output,
)


def _make_jsonl_response(content: str = "test output") -> str:
    """Create a valid JSONL response string for use in subprocess mocks."""
    line_msg = json.dumps({"type": "assistant.message", "data": {"content": content}})
    line_result = json.dumps(
        {
            "type": "result",
            "sessionId": "test-session-id",
            "exitCode": 0,
            "usage": {"premiumRequests": 0, "totalApiDurationMs": 500},
        }
    )
    return line_msg + "\n" + line_result


class TestParseOtelMetrics:
    """Test OTel JSONL metric parsing."""

    def test_parse_otel_metrics_success(self, tmp_path):
        """Test successful parsing of OTel metrics.

        github.copilot.cost is an LLM turn count, not USD — cost_usd is always
        None. Tokens are summed from gen_ai.usage.* fields.
        """
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text(
            json.dumps({"attributes": {"gen_ai.usage.input_tokens": 200, "github.copilot.cost": 3}})
            + "\n"
            + json.dumps({"attributes": {"gen_ai.usage.output_tokens": 50}})
            + "\n"
        )
        tokens, cost = _parse_otel_metrics(str(otel_file))
        assert tokens == 250
        assert cost is None

    def test_parse_otel_metrics_file_not_found(self):
        """Test parsing when file doesn't exist."""
        tokens, cost = _parse_otel_metrics("/nonexistent/path.jsonl")
        assert tokens is None
        assert cost is None

    def test_parse_otel_metrics_malformed_json(self, tmp_path):
        """Test parsing malformed JSON."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("not valid json\n")
        tokens, cost = _parse_otel_metrics(str(otel_file))
        assert tokens is None
        assert cost is None

    def test_parse_otel_metrics_missing_fields(self, tmp_path):
        """Test parsing when fields are missing."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text(json.dumps({"attributes": {}}) + "\n")
        tokens, cost = _parse_otel_metrics(str(otel_file))
        assert tokens is None
        assert cost is None


class TestCopilotCall:
    """Test copilot_call function."""

    @pytest.fixture(autouse=True)
    def mock_copilot_which(self):
        """Ensure shutil.which('copilot') resolves in all CI environments."""
        with patch("shutil.which", return_value="/usr/local/bin/copilot"):
            yield

    def test_copilot_call_success(self, tmp_path, monkeypatch):
        """Test successful copilot call."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))
        # Isolate from any COPILOT_MODEL_EXECUTION set in the outer environment
        monkeypatch.delenv("COPILOT_MODEL_EXECUTION", raising=False)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("test output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = copilot_call("test prompt")
            assert result.exit_code == 0
            assert result.stdout == "test output"
            # model reflects whatever was passed; not asserting a specific value
            # since COPILOT_MODEL_EXECUTION may be set in the environment
            from scripts.copilot_wrapper import MODEL_EXECUTION

            assert result.model == (MODEL_EXECUTION or "")

    def test_copilot_call_missing_otel_path_uses_default(self, tmp_path, monkeypatch):
        """Test that a default OTel path is used when env var not set."""
        monkeypatch.delenv("COPILOT_OTEL_FILE_EXPORTER_PATH", raising=False)
        monkeypatch.chdir(tmp_path)  # Use tmp_path as cwd

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("test output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = copilot_call("test prompt")
            assert result.exit_code == 0
            # Verify env var was set to default (absolute path ends with the default)
            import os

            otel_path = os.environ.get("COPILOT_OTEL_FILE_EXPORTER_PATH", "")
            assert otel_path.endswith("logs\\.copilot-otel.jsonl") or otel_path.endswith("logs/.copilot-otel.jsonl")

    def test_copilot_call_timeout(self, tmp_path, monkeypatch):
        """Test timeout handling."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 10)
        mock_proc.pid = 12345
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("scripts.copilot_wrapper.kill_process_tree"):
                with pytest.raises(subprocess.TimeoutExpired):
                    copilot_call("test prompt", timeout=10)

    def test_copilot_call_with_model(self, tmp_path, monkeypatch):
        """Test copilot call with custom model."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            result = copilot_call("prompt", model="gpt-4-turbo")
            assert result.model == "gpt-4-turbo"

    def test_copilot_call_with_output_file(self, tmp_path, monkeypatch):
        """Test copilot call with output file."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))
        output_file = tmp_path / "output.txt"

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("test output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            copilot_call("test prompt", output_file=str(output_file))
            assert output_file.read_text() == "test output"

    def test_copilot_call_with_transcript_path(self, tmp_path, monkeypatch):
        """Test that --share flag is added to command when transcript_path is provided."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))
        transcript_path = str(tmp_path / "session.md")

        mock_popen = MagicMock()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_proc
        with patch("subprocess.Popen", mock_popen):
            result = copilot_call("test prompt", transcript_path=transcript_path)
            call_args = mock_popen.call_args[0][0]
            assert "--share" in call_args
            assert transcript_path in call_args
            assert result.transcript_path == transcript_path

    def test_copilot_call_model_unavailable(self, tmp_path, monkeypatch):
        """Test detection of model-unavailable error in stderr."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (
            "",  # Empty stdout
            "Error: Model gemini-2.0-flash from --model flag is not available.",
        )
        mock_proc.returncode = 0  # CLI exits 0 on model-not-found
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(CopilotResponseError) as exc_info:
                copilot_call("test prompt", check=True)
            assert "is not available" in str(exc_info.value)

    def test_copilot_call_propagates_executor_depth(self, tmp_path, monkeypatch):
        """Verify _EXECUTOR_DEPTH is incremented in child env."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))
        monkeypatch.setenv("_EXECUTOR_DEPTH", "0")

        mock_popen = MagicMock()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("ok"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_proc
        with patch("subprocess.Popen", mock_popen):
            copilot_call("test prompt")
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs["env"]["_EXECUTOR_DEPTH"] == "1"


class TestRecursionGuard:
    """Test check_recursion_guard()."""

    def test_allows_depth_zero(self, monkeypatch):
        """No exit when _EXECUTOR_DEPTH is 0 or unset."""
        monkeypatch.delenv("_EXECUTOR_DEPTH", raising=False)
        check_recursion_guard()  # should not raise

    def test_blocks_depth_one(self, monkeypatch):
        """Exits with code 98 when _EXECUTOR_DEPTH >= 1."""
        monkeypatch.setenv("_EXECUTOR_DEPTH", "1")
        with pytest.raises(SystemExit) as exc_info:
            check_recursion_guard()
        assert exc_info.value.code == 98

    def test_blocks_depth_two(self, monkeypatch):
        """Exits with code 98 when _EXECUTOR_DEPTH >= 1."""
        monkeypatch.setenv("_EXECUTOR_DEPTH", "2")
        with pytest.raises(SystemExit) as exc_info:
            check_recursion_guard()
        assert exc_info.value.code == 98


class TestProcessKillswitch:
    """Test check_process_killswitch()."""

    def test_allows_low_count(self):
        """No exit when Python process count is below threshold."""
        with patch("scripts.copilot_wrapper.count_python_processes", return_value=5):
            check_process_killswitch()  # should not raise

    def test_blocks_high_count(self):
        """Exits with code 99 when Python process count is over threshold."""
        with patch("scripts.copilot_wrapper.count_python_processes", return_value=100):
            with pytest.raises(SystemExit) as exc_info:
                check_process_killswitch()
            assert exc_info.value.code == 99

    def test_count_python_processes_returns_int(self):
        """count_python_processes returns a non-negative integer."""
        n = count_python_processes()
        assert isinstance(n, int)
        assert n >= 0


class TestParseJsonlOutput:
    """Tests for parse_jsonl_output()."""

    def test_extracts_content_from_single_assistant_message(self) -> None:
        """Verify content extraction from a single assistant.message event."""
        raw = json.dumps({"type": "assistant.message", "data": {"content": "Hello!"}})
        result = parse_jsonl_output(raw)
        assert result["content"] == "Hello!"

    def test_extracts_content_from_multiple_assistant_messages(self) -> None:
        """Content is concatenated from multiple assistant.message events."""
        line1 = json.dumps({"type": "assistant.message", "data": {"content": "Part 1"}})
        line2 = json.dumps({"type": "assistant.message", "data": {"content": "Part 2"}})
        result = parse_jsonl_output(line1 + "\n" + line2)
        assert result["content"] == "Part 1Part 2"

    def test_extracts_result_metadata(self) -> None:
        """Verify sessionId, exitCode, and premiumRequests extraction."""
        line_msg = json.dumps({"type": "assistant.message", "data": {"content": "ok"}})
        line_res = json.dumps(
            {
                "type": "result",
                "sessionId": "sess-abc",
                "exitCode": 0,
                "usage": {"premiumRequests": 3.5, "totalApiDurationMs": 800},
            }
        )
        result = parse_jsonl_output(line_msg + "\n" + line_res)
        assert result["session_id"] == "sess-abc"
        assert result["exit_code"] == 0

    def test_raises_on_malformed_json(self) -> None:
        """CopilotResponseError is raised when a line is not valid JSON."""
        with pytest.raises(CopilotResponseError, match="Failed to parse JSONL output line"):
            parse_jsonl_output("this is not json")

    def test_empty_string_returns_empty_content(self) -> None:
        """Empty input produces empty content."""
        result = parse_jsonl_output("")
        assert result["content"] == ""
        assert result["session_id"] == ""

    def test_ignores_non_content_event_types(self) -> None:
        """Event types other than assistant.message/result are ignored."""
        lines = "\n".join(
            [
                json.dumps({"type": "session.start", "sessionId": "x"}),
                json.dumps({"type": "user.message", "data": {"content": "prompt"}}),
                json.dumps({"type": "assistant.message", "data": {"content": "answer"}}),
                json.dumps({"type": "tool.execution_start", "tool": "bash"}),
                json.dumps({"type": "result", "sessionId": "s1", "exitCode": 0, "usage": {"premiumRequests": 1.0}}),
            ]
        )
        result = parse_jsonl_output(lines)
        assert result["content"] == "answer"
        assert result["session_id"] == "s1"

    def test_skips_empty_lines(self) -> None:
        """Empty lines between JSON objects are silently skipped."""
        raw = (
            json.dumps({"type": "assistant.message", "data": {"content": "x"}})
            + "\n\n\n"
            + json.dumps({"type": "result", "sessionId": "s", "exitCode": 0, "usage": {"premiumRequests": 0.0}})
        )
        result = parse_jsonl_output(raw)
        assert result["content"] == "x"

    def test_no_result_event_returns_defaults(self) -> None:
        """When no result event is present, metadata defaults are returned."""
        raw = json.dumps({"type": "assistant.message", "data": {"content": "hello"}})
        result = parse_jsonl_output(raw)
        assert result["content"] == "hello"
        assert result["session_id"] == ""
        assert result["exit_code"] == 0

    def test_missing_data_content_field_returns_empty_string(self) -> None:
        """assistant.message without data.content key contributes empty string."""
        raw = json.dumps({"type": "assistant.message", "data": {}})
        result = parse_jsonl_output(raw)
        assert result["content"] == ""

    def test_raises_on_invalid_premium_requests_type(self) -> None:
        pass  # premiumRequests validation removed (premium_requests metric superseded)


class TestCopilotCallJsonOutputFlag:
    """Verify --output-format json is added to the CLI command by default."""

    @pytest.fixture(autouse=True)
    def mock_copilot_which(self):
        with patch("shutil.which", return_value="/usr/local/bin/copilot"):
            yield

    def test_json_output_flag_added_by_default(self, tmp_path, monkeypatch) -> None:
        """copilot_call adds --output-format json to the command by default."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_popen = MagicMock()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("result"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_proc

        with patch("subprocess.Popen", mock_popen):
            result = copilot_call("test prompt")

        cmd = mock_popen.call_args[0][0]
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "json"
        assert result.stdout == "result"

    def test_text_output_flag_not_added_when_output_format_text(self, tmp_path, monkeypatch) -> None:
        """When output_format='text', --output-format is not added and stdout is raw."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_popen = MagicMock()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("raw text output", "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_proc

        with patch("subprocess.Popen", mock_popen):
            result = copilot_call("test prompt", output_format="text")

        cmd = mock_popen.call_args[0][0]
        assert "--output-format" not in cmd
        assert result.stdout == "raw text output"

    def test_premium_requests_populated_from_json(self, tmp_path, monkeypatch) -> None:
        pass  # premium_requests metric superseded by Gemini CLI migration

    def test_invalid_output_format_raises_valueerror(self) -> None:
        """ValueError is raised when output_format is not 'text' or 'json'."""
        with pytest.raises(ValueError, match="Invalid output_format.*Must be one of"):
            copilot_call("test prompt", output_format="jsno")  # typo: should be 'json'


class TestBuildContextPath:
    """Test build_context_path() helper function."""

    def test_build_context_path_without_step_n(self) -> None:
        """build_context_path generates correct path without step number."""
        path = build_context_path("planning", "rec-252")
        assert path == "logs/debug/planning-context-rec-252.md"

    def test_build_context_path_with_step_n(self) -> None:
        """build_context_path appends step number when provided."""
        path = build_context_path("implementation", "rec-252", step_n=1)
        assert path == "logs/debug/implementation-context-rec-252-step1.md"

    def test_build_context_path_with_step_n_two_digits(self) -> None:
        """build_context_path handles multi-digit step numbers."""
        path = build_context_path("refine", "rec-100", step_n=42)
        assert path == "logs/debug/refine-context-rec-100-step42.md"

    def test_build_context_path_with_step_n_zero(self) -> None:
        """build_context_path handles step_n=0."""
        path = build_context_path("testing", "rec-001", step_n=0)
        assert path == "logs/debug/testing-context-rec-001-step0.md"


class TestWorkspaceFileMode:
    """Test workspace file invocation mode in copilot_call."""

    @pytest.fixture(autouse=True)
    def mock_copilot_which(self):
        """Ensure shutil.which('copilot') resolves in all CI environments."""
        with patch("shutil.which", return_value="/usr/local/bin/copilot"):
            yield

    def test_context_file_path_and_inline_instruction_writes_prompt_to_file(self, tmp_path, monkeypatch) -> None:
        """When both context_file_path and inline_instruction are set,
        prompt is written to context file and instruction is passed via -p."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        context_file = tmp_path / "debug" / "planning-context-rec-252.md"
        prompt_content = "This is the full prompt content with context."
        inline_instr = "Analyze this and provide a plan."

        mock_popen = MagicMock()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("plan output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        mock_popen.return_value = mock_proc

        with patch("subprocess.Popen", mock_popen):
            result = copilot_call(
                prompt_content,
                context_file_path=str(context_file),
                inline_instruction=inline_instr,
            )

        assert result.stdout == "plan output"
        # Verify context file was created with prompt
        assert context_file.exists()
        assert context_file.read_text() == prompt_content
        # Verify CLI receives -p with inline instruction + @context_file in one arg
        cmd = mock_popen.call_args[0][0]
        assert "-p" in cmd
        idx = cmd.index("-p")
        p_arg = cmd[idx + 1]
        assert p_arg == f"{inline_instr} @{context_file}"
        # --share should NOT be used for context injection (only for transcripts)
        share_indices = [i for i, a in enumerate(cmd) if a == "--share"]
        for si in share_indices:
            assert cmd[si + 1] != str(context_file)

    def test_context_file_path_and_inline_instruction_creates_debug_dir(self, tmp_path, monkeypatch) -> None:
        """logs/debug/ directory is created if it doesn't exist."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        context_file = tmp_path / "logs" / "debug" / "test-context.md"

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("ok"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            copilot_call(
                "prompt",
                context_file_path=str(context_file),
                inline_instruction="instruction",
            )

        assert context_file.parent.exists()
        assert context_file.exists()

    def test_context_file_persists_after_call(self, tmp_path, monkeypatch) -> None:
        """Context file persists after the copilot call (not cleaned up)."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        context_file = tmp_path / "context.md"
        prompt_text = "Persistent prompt content"

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("result"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)

        with patch("subprocess.Popen", return_value=mock_proc):
            copilot_call(
                prompt_text,
                context_file_path=str(context_file),
                inline_instruction="instruction",
            )

        # Verify file still exists and has correct content
        assert context_file.exists()
        assert context_file.read_text() == prompt_text


class TestEmitModelCallTelemetry:
    """Verify _emit_model_call is invoked from copilot_call."""

    @pytest.fixture(autouse=True)
    def mock_copilot_which(self):
        with patch("shutil.which", return_value="/usr/local/bin/copilot"):
            yield

    def test_emit_model_call_invoked_with_provider_and_purpose(self, tmp_path, monkeypatch) -> None:
        """emit_model_call is called with provider='copilot_cli' and the given purpose."""
        otel_file = tmp_path / "otel.jsonl"
        otel_file.write_text("")
        monkeypatch.setenv("COPILOT_OTEL_FILE_EXPORTER_PATH", str(otel_file))

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (_make_jsonl_response("output"), "")
        mock_proc.returncode = 0
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("scripts.executor.telemetry.emit_model_call") as mock_emit,
        ):
            copilot_call("test prompt", purpose="planning")

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs.get("provider") == "copilot_cli"
        assert call_kwargs.get("purpose") == "planning"
