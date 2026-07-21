"""Tests for scripts/ops_portal/execution_plans.py -- save_execution_plan() (T2.26 c9).

Covers the write_ops projection (dataclass -> registered columns), the steps/critique_history
JSON-blob serialization, the opaque planning_session_id carry, and the local read-cache upsert
(Decision 84 I-4: downstream of the writer, never a write source).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def _make_plan_dict(**overrides: object) -> dict:
    base = {
        "rec_id": "rec-042",
        "slug": "my-slug",
        "revision": 1,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "status": "approved",
        "model": "claude-sonnet-4-5",
        "tokens_used": 1000,
        "steps": [{"n": 1, "title": "do it", "file": "f.py", "action": "modify"}],
        "critique_history": [{"revision": 0, "verdict": "needs_revision"}],
        "plan_text": "### Step 1",
        "prompt_hash": "abc123",
        "planning_session_id": "smoke-session-ulid",
    }
    base.update(overrides)
    return base


class TestSaveExecutionPlan:
    def test_projects_scalars_and_json_dumps_blobs(self, tmp_path: Path) -> None:
        """save_execution_plan writes via write_ops with steps/critique_history JSON-serialized."""
        plan_dict = _make_plan_dict()
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch("scripts.ops_portal.execution_plans._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            result = save_execution_plan(plan_dict)

        assert result is True
        call_table, call_rec = mock_write.call_args[0]
        assert call_table == "ops_execution_plans"
        assert mock_write.call_args.kwargs["action"] == "write_ops"

        # Promoted scalars carried through unchanged.
        assert call_rec["rec_id"] == "rec-042"
        assert call_rec["revision"] == 1
        assert call_rec["status"] == "approved"
        assert call_rec["model"] == "claude-sonnet-4-5"
        assert call_rec["tokens_used"] == 1000
        assert call_rec["prompt_hash"] == "abc123"
        assert call_rec["slug"] == "my-slug"
        assert call_rec["plan_text"] == "### Step 1"

        # steps/critique_history are json.dumps'd onto their VARCHAR JSON columns.
        assert isinstance(call_rec["steps"], str)
        assert json.loads(call_rec["steps"]) == plan_dict["steps"]
        assert isinstance(call_rec["critique_history"], str)
        assert json.loads(call_rec["critique_history"]) == plan_dict["critique_history"]

    def test_planning_session_id_passes_through_opaque(self, tmp_path: Path) -> None:
        """planning_session_id is carried verbatim -- no UUID/ULID translation (session-id.yaml)."""
        plan_dict = _make_plan_dict(planning_session_id="11111111-2222-3333-4444-555555555555")
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch("scripts.ops_portal.execution_plans._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            save_execution_plan(plan_dict)

        _, call_rec = mock_write.call_args[0]
        assert call_rec["planning_session_id"] == "11111111-2222-3333-4444-555555555555"

    def test_does_not_mutate_json_blobs_already_serialized(self, tmp_path: Path) -> None:
        """A caller that already passed a JSON string for steps/critique_history is left untouched."""
        plan_dict = _make_plan_dict(steps="[]", critique_history="[]")
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch("scripts.ops_portal.execution_plans._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            save_execution_plan(plan_dict)

        _, call_rec = mock_write.call_args[0]
        assert call_rec["steps"] == "[]"
        assert call_rec["critique_history"] == "[]"

    def test_local_cache_upserted_by_rec_id(self, tmp_path: Path) -> None:
        """The local read-cache is upserted keyed on rec_id (aliased to 'id' for upsert_cache_row)."""
        plan_dict = _make_plan_dict()
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch("scripts.ops_portal.execution_plans._ducklake_write", return_value={"ok": True, "ulid": "01ULID"}),
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            save_execution_plan(plan_dict)

        cached = [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(cached) == 1
        assert cached[0]["rec_id"] == "rec-042"
        assert cached[0]["id"] == "rec-042"
        assert cached[0]["ulid"] == "01ULID"
        assert cached[0]["created_timestamp"] and cached[0]["last_updated_timestamp"]

    def test_cache_upsert_does_not_leak_id_alias_onto_the_wire_record(self, tmp_path: Path) -> None:
        """The 'id' cache-alias key is added AFTER the warehouse write -- never sent to _ducklake_write."""
        plan_dict = _make_plan_dict()
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch("scripts.ops_portal.execution_plans._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            save_execution_plan(plan_dict)

        _, call_rec = mock_write.call_args[0]
        assert "id" not in call_rec

    def test_fail_loud_on_writer_error(self, tmp_path: Path) -> None:
        """A writer failure propagates -- no offline outbox, no try/except-warn swallow (Decision 84 I-4)."""
        import pytest

        plan_dict = _make_plan_dict()
        cache_path = tmp_path / ".execution-plans-index.jsonl"

        with (
            patch(
                "scripts.ops_portal.execution_plans._ducklake_write",
                side_effect=RuntimeError("writer unreachable"),
            ),
            patch("scripts.ops_portal.execution_plans.EXECUTION_PLANS_JSONL", cache_path),
        ):
            from scripts.ops_portal.execution_plans import save_execution_plan

            with pytest.raises(RuntimeError, match="writer unreachable"):
                save_execution_plan(plan_dict)

        # No cache write should have happened -- the write never committed.
        assert not cache_path.exists()
