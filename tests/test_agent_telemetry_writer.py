"""Unit tests for scripts/agent_telemetry_writer.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add repo root so the module's OpsWriter import resolves
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_WRITER_PATH = _ROOT / "scripts" / "agent_telemetry_writer.py"
_spec = importlib.util.spec_from_file_location("agent_telemetry_writer", _WRITER_PATH)
_writer_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_writer_mod)  # type: ignore[union-attr]

parse_json_output = _writer_mod.parse_json_output
parse_findings = _writer_mod.parse_findings
emit_telemetry = _writer_mod.emit_telemetry


class TestParseJsonOutput:
    """Tests for parse_json_output()."""

    def test_parses_usage_and_metadata(self, tmp_path: Path) -> None:
        """Extracts tokens, session_id, and model from a valid output file."""
        output_file = tmp_path / "agent-output.json"
        output_file.write_text(
            json.dumps(
                {
                    "usage": {"input_tokens": 1500, "output_tokens": 300},
                    "session_id": "sess-abc123",
                    "model": "claude-opus-4-7",
                }
            ),
            encoding="utf-8",
        )
        tokens_in, tokens_out, session_id, model = parse_json_output(output_file)
        assert tokens_in == 1500
        assert tokens_out == 300
        assert session_id == "sess-abc123"
        assert model == "claude-opus-4-7"

    def test_missing_usage_defaults_to_zero(self, tmp_path: Path) -> None:
        """Missing .usage field results in zero token counts, no exception."""
        output_file = tmp_path / "agent-output.json"
        output_file.write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
        tokens_in, tokens_out, session_id, model = parse_json_output(output_file)
        assert tokens_in == 0
        assert tokens_out == 0
        assert session_id == "s1"

    def test_missing_file_defaults_to_zeros(self, tmp_path: Path) -> None:
        """Non-existent file returns zero tokens and a default model."""
        tokens_in, tokens_out, session_id, model = parse_json_output(tmp_path / "missing.json")
        assert tokens_in == 0
        assert tokens_out == 0
        assert session_id is None
        assert model == "claude-opus-4-7"

    def test_malformed_json_defaults_to_zeros(self, tmp_path: Path) -> None:
        """Malformed JSON returns zero tokens, no exception raised."""
        output_file = tmp_path / "bad.json"
        output_file.write_text("not json", encoding="utf-8")
        tokens_in, tokens_out, session_id, model = parse_json_output(output_file)
        assert tokens_in == 0
        assert tokens_out == 0


class TestParseFindings:
    """Tests for parse_findings()."""

    def test_counts_findings_and_queue_entries(self, tmp_path: Path) -> None:
        """Counts total rows and priority-queue-entry rows correctly."""
        findings_file = tmp_path / "findings.jsonl"
        findings_file.write_text(
            "\n".join(
                [
                    json.dumps({"type": "cluster", "timestamp": "2026-05-09T08:00:00Z"}),
                    json.dumps({"type": "priority-queue-entry", "timestamp": "2026-05-09T08:00:00Z", "rank": 1}),
                    json.dumps({"type": "priority-queue-entry", "timestamp": "2026-05-09T08:00:00Z", "rank": 2}),
                ]
            ),
            encoding="utf-8",
        )
        findings_count, queue_entries = parse_findings(findings_file)
        assert findings_count == 3
        assert queue_entries == 2

    def test_queue_entries_written_counts_only_priority_queue_type(self, tmp_path: Path) -> None:
        """Only rows with type 'priority-queue-entry' count toward queue_entries_written."""
        findings_file = tmp_path / "findings.jsonl"
        findings_file.write_text(
            "\n".join(
                [
                    json.dumps({"type": "root-cause-rec", "timestamp": "2026-05-09T08:00:00Z"}),
                    json.dumps({"type": "cluster", "timestamp": "2026-05-09T08:00:00Z"}),
                ]
            ),
            encoding="utf-8",
        )
        findings_count, queue_entries = parse_findings(findings_file)
        assert findings_count == 2
        assert queue_entries == 0

    def test_empty_findings_file_returns_zeros(self, tmp_path: Path) -> None:
        """Empty file returns findings_count=0 and queue_entries_written=0."""
        findings_file = tmp_path / "empty.jsonl"
        findings_file.write_text("", encoding="utf-8")
        findings_count, queue_entries = parse_findings(findings_file)
        assert findings_count == 0
        assert queue_entries == 0

    def test_missing_file_returns_zeros(self, tmp_path: Path) -> None:
        """Missing file returns zeros without raising."""
        findings_count, queue_entries = parse_findings(tmp_path / "missing.jsonl")
        assert findings_count == 0
        assert queue_entries == 0


class TestEmitTelemetry:
    """Tests for emit_telemetry()."""

    def test_emits_invocation_and_model_call_rows(self, tmp_path: Path) -> None:
        """emit_telemetry() calls OpsWriter.emit twice with correct table names."""
        output_file = tmp_path / "output.json"
        output_file.write_text(
            json.dumps({"usage": {"input_tokens": 100, "output_tokens": 50}, "session_id": "s1"}),
            encoding="utf-8",
        )
        findings_file = tmp_path / "findings.jsonl"
        findings_file.write_text(
            json.dumps({"type": "priority-queue-entry", "timestamp": "2026-05-09T08:00:00Z"}),
            encoding="utf-8",
        )

        mock_writer = MagicMock()
        with patch.object(_writer_mod, "OpsWriter", return_value=mock_writer):
            emit_telemetry(
                agent_name="rec-curator",
                trigger="cron_workflow",
                provider="anthropic_max",
                json_output_path=output_file,
                findings_path=findings_file,
                workflow_run_id="9876543210",
            )

        assert mock_writer.emit.call_count == 2
        table_names = [call.args[0] for call in mock_writer.emit.call_args_list]
        assert "telemetry_agent_invocations" in table_names
        assert "telemetry_model_calls" in table_names

    def test_invocation_record_shape(self, tmp_path: Path) -> None:
        """telemetry_agent_invocations row has correct field values."""
        output_file = tmp_path / "output.json"
        output_file.write_text(
            json.dumps({"usage": {"input_tokens": 200, "output_tokens": 75}}),
            encoding="utf-8",
        )
        findings_file = tmp_path / "findings.jsonl"
        findings_file.write_text(
            "\n".join(
                [
                    json.dumps({"type": "priority-queue-entry", "timestamp": "2026-05-09T08:00:00Z"}),
                    json.dumps({"type": "cluster", "timestamp": "2026-05-09T08:00:00Z"}),
                ]
            ),
            encoding="utf-8",
        )

        mock_writer = MagicMock()
        with patch.object(_writer_mod, "OpsWriter", return_value=mock_writer):
            emit_telemetry(
                agent_name="rec-curator",
                trigger="cron_workflow",
                provider="anthropic_max",
                json_output_path=output_file,
                findings_path=findings_file,
                workflow_run_id="42",
            )

        invocation_call = next(c for c in mock_writer.emit.call_args_list if c.args[0] == "telemetry_agent_invocations")
        record = invocation_call.args[1]
        assert record["agent_name"] == "rec-curator"
        assert record["trigger"] == "cron_workflow"
        assert record["provider"] == "anthropic_max"
        assert record["tokens_input"] == 200
        assert record["tokens_output"] == 75
        assert record["findings_count"] == 2
        assert record["queue_entries_written"] == 1
        assert record["workflow_run_id"] == "42"
        assert record["outcome"] == "success"
