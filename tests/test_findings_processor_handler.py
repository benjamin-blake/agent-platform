"""Unit tests for src/data/handlers/findings_processor_handler.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.data.handlers.findings_processor_handler as proc_mod
from src.data.handlers.findings_processor_handler import _next_agent_rec_id, handler


class TestNextAgentRecId:
    """Tests for _next_agent_rec_id()."""

    def test_returns_agent_001_for_empty_list(self) -> None:
        assert _next_agent_rec_id([]) == "agent-001"

    def test_returns_next_sequential_id(self) -> None:
        recs = [{"id": "agent-001"}, {"id": "agent-002"}, {"id": "agent-003"}]
        assert _next_agent_rec_id(recs) == "agent-004"

    def test_skips_non_agent_ids(self) -> None:
        recs = [{"id": "rec-001"}, {"id": "rec-002"}]
        assert _next_agent_rec_id(recs) == "agent-001"

    def test_handles_mixed_ids(self) -> None:
        recs = [{"id": "rec-001"}, {"id": "agent-005"}, {"id": "rec-010"}]
        assert _next_agent_rec_id(recs) == "agent-006"

    def test_handles_malformed_ids(self) -> None:
        recs = [{"id": "agent-xyz"}, {"id": "agent-002"}]
        assert _next_agent_rec_id(recs) == "agent-003"


class TestHandlerStep1DeterministicUnion:
    """Tests for the deterministic union step (Step 1)."""

    def test_unifies_all_findings_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Step 1 writes unified.jsonl when no S3 bucket is configured."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)

        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        findings = [{"title": "stale doc", "source": "doc-freshness/ts"}]

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=findings),
            patch.object(proc_mod, "_get_github_pat", return_value=""),
            patch("scripts.s3_log_store._LOGS_DIR", log_dir),
        ):
            result = handler({}, None)

        assert result["unified_count"] == 1
        unified_path = log_dir / "findings" / "unified.jsonl"
        assert unified_path.exists()
        data = json.loads(unified_path.read_text(encoding="utf-8").strip())
        assert data["title"] == "stale doc"

    def test_skips_comparison_when_no_pat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[]),
            patch.object(proc_mod, "_get_github_pat", return_value=""),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
        ):
            # Patch open to avoid file write errors for empty findings
            with patch("builtins.open", MagicMock()):
                result = handler({}, None)

        assert result["skipped_comparison"] is True
        assert result["new_rec_count"] == 0


class TestHandlerStep2AgentComparison:
    """Tests for the agent comparison step (Step 2)."""

    def _make_comparison_response(self, duplicate_ids: list[str], new_recs: list[dict]) -> dict:
        content = json.dumps({"duplicate_ids": duplicate_ids, "new_recommendations": new_recs})
        return {"choices": [{"message": {"content": content}}]}

    def test_appends_new_recommendations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")

        new_rec = {
            "title": "Fix stale ARCHITECTURE.md",
            "file": "docs/ARCHITECTURE.md",
            "context": "File not updated in 30 days",
            "acceptance": "Update doc to match current code",
            "priority": "medium",
            "effort": "low",
            "automatable": False,
            "risk": "low",
            "source_findings": ["doc-freshness/ts"],
        }
        api_response = self._make_comparison_response([], [new_rec])

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[{"title": "stale"}]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch("scripts.s3_log_store.append_jsonl", return_value=True),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["new_rec_count"] == 1
        assert result["duplicate_count"] == 0

    def test_records_duplicate_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")
        api_response = self._make_comparison_response(["agent-001", "agent-002"], [])
        existing = [{"id": "agent-001"}, {"id": "agent-002"}]

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[{"title": "stale"}]),
            patch("scripts.s3_log_store.read_jsonl", return_value=existing),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["duplicate_count"] == 2
        assert result["new_rec_count"] == 0

    def test_assigns_agent_namespace_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")

        new_rec = {
            "title": "New finding",
            "file": "src/foo.py",
            "context": "ctx",
            "acceptance": "acc",
            "priority": "low",
            "effort": "low",
            "automatable": False,
            "risk": "low",
            "source_findings": [],
        }
        api_response = self._make_comparison_response([], [new_rec])
        appended_entries: list[dict] = []

        def capture_append(key: str, entry: dict) -> bool:
            appended_entries.append(entry)
            return True

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[{"title": "f"}]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch("scripts.s3_log_store.append_jsonl", side_effect=capture_append),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
            patch("builtins.open", MagicMock()),
        ):
            handler({}, None)

        assert len(appended_entries) == 1
        assert appended_entries[0]["id"].startswith("agent-")
        assert appended_entries[0]["status"] == "open"
        assert appended_entries[0]["source"] == "agent-cron"

    def test_handles_api_error_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")
        api_response = {"error": True, "message": "Rate limit exceeded"}

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[{"title": "f"}]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert "error" in result
        assert result["new_rec_count"] == 0

    def test_handles_markdown_fenced_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")
        fenced_content = '```json\n{"duplicate_ids": [], "new_recommendations": []}\n```'
        api_response = {"choices": [{"message": {"content": fenced_content}}]}

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("scripts.s3_log_store._LOGS_DIR", Path("/tmp/__nonexistent")),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["new_rec_count"] == 0
        assert "error" not in result


class TestHandlerPriorityQueueRouting:
    """Tests for priority-queue-entry extraction and routing."""

    def test_priority_queue_entries_routed_to_overwrite_jsonl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Findings with type priority-queue-entry are written via overwrite_jsonl."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)

        queue_entry = {"type": "priority-queue-entry", "rank": 1, "rec_id": "rec-001", "status": "queued"}
        written_calls: list = []

        def capture_overwrite(key: str, entries: list) -> bool:
            written_calls.append((key, entries))
            return True

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[queue_entry]),
            patch.object(proc_mod, "_get_github_pat", return_value=""),
            patch("scripts.s3_log_store.overwrite_jsonl", side_effect=capture_overwrite),
            patch("builtins.open", MagicMock()),
        ):
            handler({}, None)

        assert len(written_calls) == 1
        key, entries = written_calls[0]
        assert key == "priority-queue/.priority-queue.jsonl"
        assert entries == [queue_entry]

    def test_priority_queue_entries_excluded_from_comparison_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """priority-queue-entry findings are not passed to the agent comparison."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")

        queue_entry = {"type": "priority-queue-entry", "rank": 1, "rec_id": "rec-001", "status": "queued"}
        normal_entry = {"type": "cluster", "title": "Some finding"}
        api_response = {"choices": [{"message": {"content": '{"duplicate_ids": [], "new_recommendations": []}'}}]}
        prompt_received: list[str] = []

        def capture_chat(prompt: str, model: str, api_key: str) -> dict:
            prompt_received.append(prompt)
            return api_response

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[queue_entry, normal_entry]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch("scripts.s3_log_store.overwrite_jsonl", return_value=True),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", side_effect=capture_chat),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["queue_entries_written"] == 1
        # The comparison prompt should only see the normal finding
        assert len(prompt_received) == 1
        assert "priority-queue-entry" not in prompt_received[0]

    def test_normal_findings_unaffected_by_queue_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Findings without type priority-queue-entry continue through the existing path."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)

        normal_finding = {"type": "cluster", "title": "Some cluster finding"}
        overwrite_calls: list = []

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[normal_finding]),
            patch.object(proc_mod, "_get_github_pat", return_value=""),
            patch("scripts.s3_log_store.overwrite_jsonl", side_effect=lambda k, e: overwrite_calls.append((k, e)) or True),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["unified_count"] == 1
        assert result["queue_entries_written"] == 0
        # overwrite_jsonl should not have been called
        assert overwrite_calls == []

    def test_mixed_findings_correctly_split(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mixed findings: queue entries routed, remaining passed to comparison."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")

        queue_entry = {"type": "priority-queue-entry", "rank": 1, "rec_id": "rec-001", "status": "queued"}
        normal_entry = {"type": "root-cause-rec", "title": "Fix something"}
        api_response = {"choices": [{"message": {"content": '{"duplicate_ids": [], "new_recommendations": []}'}}]}

        with (
            patch(
                "scripts.s3_log_store.read_all_agent_findings",
                return_value=[queue_entry, normal_entry],
            ),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch("scripts.s3_log_store.overwrite_jsonl", return_value=True),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare prompt"),
            patch("scripts.llm.github_models_client.chat_completion", return_value=api_response),
            patch("builtins.open", MagicMock()),
        ):
            result = handler({}, None)

        assert result["unified_count"] == 1  # only normal_entry reaches comparison
        assert result["queue_entries_written"] == 1


class TestHandlerTelemetry:
    """Tests that findings_processor_handler emits telemetry correctly."""

    def _make_comparison_response(self) -> dict:
        content = '{"duplicate_ids": [], "new_recommendations": []}'
        return {"choices": [{"message": {"content": content}}]}

    def test_record_model_call_emitted_when_comparison_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """record_model_call is called when the comparison step runs."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "ghp_test")

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[]),
            patch("scripts.s3_log_store.read_jsonl", return_value=[]),
            patch.object(proc_mod, "_get_github_pat", return_value="ghp_test"),
            patch.object(proc_mod, "_load_compare_prompt", return_value="compare"),
            patch(
                "scripts.llm.github_models_client.chat_completion",
                return_value=self._make_comparison_response(),
            ),
            patch("builtins.open", MagicMock()),
            patch("src.data.handlers.agent_telemetry.open_invocation") as mock_open,
            patch("src.data.handlers.agent_telemetry.record_model_call") as mock_record,
            patch("src.data.handlers.agent_telemetry.close_invocation") as mock_close,
        ):
            result = handler({}, None)

        mock_open.assert_called_once()
        mock_record.assert_called_once()
        record_kwargs = mock_record.call_args.kwargs
        assert record_kwargs.get("provider") == "github-models"
        assert record_kwargs.get("purpose") == "comparison"
        mock_close.assert_called_once()
        assert result["new_rec_count"] == 0

    def test_record_model_call_not_emitted_when_comparison_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """record_model_call is NOT called when PAT is unavailable (comparison skipped)."""
        monkeypatch.delenv("S3_LOG_BUCKET", raising=False)
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        monkeypatch.delenv("GITHUB_PAT_SECRET_ARN", raising=False)

        with (
            patch("scripts.s3_log_store.read_all_agent_findings", return_value=[]),
            patch.object(proc_mod, "_get_github_pat", return_value=""),
            patch("builtins.open", MagicMock()),
            patch("src.data.handlers.agent_telemetry.open_invocation"),
            patch("src.data.handlers.agent_telemetry.record_model_call") as mock_record,
            patch("src.data.handlers.agent_telemetry.close_invocation"),
        ):
            result = handler({}, None)

        mock_record.assert_not_called()
        assert result.get("skipped_comparison") is True
