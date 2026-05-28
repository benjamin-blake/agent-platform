"""Unit tests for scripts/executor/jsonl_store.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import scripts.executor.jsonl_store as store_mod
import scripts.s3_log_store as s3_mod
from scripts.executor.jsonl_store import (
    Recommendation,
    _atomic_write,
    _create_postmortem_recommendation,
    _reset_rec_status,
    load_all_recommendations,
    load_recommendation,
    update_recommendation_status,
)


def _write_recs(path: Path, entries: list[dict]) -> None:
    """Helper: write a list of dicts as JSONL to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(e) + "\n" for e in entries)
    path.write_text(lines, encoding="utf-8")


class TestLoadRecommendation:
    """Tests for load_recommendation()."""

    def test_finds_matching_entry(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        _write_recs(recs, [{"id": "rec-001", "status": "open"}, {"id": "rec-002", "status": "done"}])
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-001")
        assert result is not None
        assert result["id"] == "rec-001"
        assert result["status"] == "open"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        _write_recs(recs, [{"id": "rec-001", "status": "open"}])
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-999")
        assert result is None

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        recs = tmp_path / "missing.jsonl"
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-001")
        assert result is None

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        recs.parent.mkdir(parents=True, exist_ok=True)
        recs.write_text(
            '# schema comment\n{"id": "rec-001", "status": "open"}\n',
            encoding="utf-8",
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-001")
        assert result is not None
        assert result["id"] == "rec-001"

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        recs.parent.mkdir(parents=True, exist_ok=True)
        recs.write_text(
            '\n\n{"id": "rec-002", "status": "open"}\n',
            encoding="utf-8",
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-002")
        assert result is not None

    def test_skips_invalid_json_lines(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        recs.parent.mkdir(parents=True, exist_ok=True)
        recs.write_text(
            'NOT_JSON\n{"id": "rec-003", "status": "open"}\n',
            encoding="utf-8",
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-003")
        assert result is not None

    def test_last_entry_wins_for_duplicate_ids(self, tmp_path: Path) -> None:
        """When multiple entries share the same ID, the last one is returned."""
        recs = tmp_path / "recs.jsonl"
        _write_recs(
            recs,
            [
                {"id": "rec-010", "status": "open", "acceptance": "grep first file.py"},
                {"id": "rec-010", "status": "closed", "acceptance": "grep second file.py"},
            ],
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_recommendation("rec-010")
        assert result is not None
        assert result["acceptance"] == "grep second file.py"
        assert result["status"] == "closed"


class TestLoadAllRecommendations:
    """Tests for load_all_recommendations()."""

    def test_returns_dict_keyed_by_id(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        _write_recs(
            recs,
            [
                {"id": "rec-001", "status": "open"},
                {"id": "rec-002", "status": "done"},
            ],
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_all_recommendations()
        assert "rec-001" in result
        assert "rec-002" in result
        assert result["rec-001"]["status"] == "open"

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        recs = tmp_path / "missing.jsonl"
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_all_recommendations()
        assert result == {}

    def test_skips_comment_and_blank_lines(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        recs.parent.mkdir(parents=True, exist_ok=True)
        recs.write_text(
            '# comment\n\nNOT JSON\n{"id": "rec-005", "status": "open"}\n',
            encoding="utf-8",
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_all_recommendations()
        assert list(result.keys()) == ["rec-005"]

    def test_last_entry_wins_for_duplicate_ids(self, tmp_path: Path) -> None:
        recs = tmp_path / "recs.jsonl"
        _write_recs(
            recs,
            [
                {"id": "rec-001", "status": "open"},
                {"id": "rec-001", "status": "done"},
            ],
        )
        with patch.object(store_mod, "RECS_JSONL", recs):
            result = load_all_recommendations()
        assert result["rec-001"]["status"] == "done"


class TestUpdateRecommendationStatus:
    """Tests for update_recommendation_status() -- delegates to ops_data_portal.update_rec."""

    def test_delegates_to_update_rec(self) -> None:
        """update_recommendation_status calls ops_data_portal.update_rec and returns its result."""
        with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
            ok = update_recommendation_status("rec-001", {"status": "closed"})
        mock_update.assert_called_once_with("rec-001", {"status": "closed"})
        assert ok is True

    def test_propagates_false_result(self) -> None:
        """Returns False when update_rec returns False."""
        with patch("scripts.ops_data_portal.update_rec", return_value=False):
            ok = update_recommendation_status("rec-002", {"execution_result": "success"})
        assert ok is False

    def test_rejects_invalid_status(self) -> None:
        """Invalid status raises ValueError (checked inside update_rec)."""
        with patch(
            "scripts.ops_data_portal.update_rec",
            side_effect=ValueError("Invalid status 'done'"),
        ):
            with pytest.raises(ValueError, match="Invalid status"):
                update_recommendation_status("rec-001", {"status": "done"})


class TestAtomicWrite:
    """Tests for _atomic_write()."""

    def test_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "output.jsonl"
        _atomic_write(target, '{"id": "rec-001"}\n')
        assert target.read_text(encoding="utf-8") == '{"id": "rec-001"}\n'

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        target = tmp_path / "output.jsonl"
        target.write_text("old content", encoding="utf-8")
        _atomic_write(target, "new content\n")
        assert target.read_text(encoding="utf-8") == "new content\n"

    def test_no_temp_file_remains(self, tmp_path: Path) -> None:
        target = tmp_path / "output.jsonl"
        _atomic_write(target, "data\n")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_appends_trailing_newline_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "output.jsonl"
        _atomic_write(target, "no newline")
        assert target.read_text(encoding="utf-8").endswith("\n")

    def test_retries_on_permission_error_succeeds_on_third_attempt(self, tmp_path: Path) -> None:
        """Verify retry logic succeeds after PermissionError on first two attempts."""
        target = tmp_path / "output.jsonl"
        call_count = [0]

        def mock_replace(self, other):
            call_count[0] += 1
            if call_count[0] < 3:
                raise PermissionError("File is in use")
            # On third call, do nothing (success)

        with patch.object(Path, "replace", mock_replace):
            _atomic_write(target, "data\n")
        assert call_count[0] == 3

    def test_raises_after_three_failed_permission_errors(self, tmp_path: Path) -> None:
        """Verify that OSError is raised after 3 failed PermissionError attempts."""
        target = tmp_path / "output.jsonl"

        def mock_replace(self, other):
            raise PermissionError("File is in use")

        with patch.object(Path, "replace", mock_replace):
            with pytest.raises(OSError, match="Failed to replace"):
                _atomic_write(target, "data\n")


class TestResetRecStatus:
    """Tests for _reset_rec_status() -- now delegates to ops_data_portal.update_rec."""

    def test_resets_status_to_open(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
            _reset_rec_status("rec-001")
        mock_update.assert_called_once()
        call_updates = mock_update.call_args[0][1]
        assert call_updates["status"] == "open"

    def test_removes_failure_fields(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
            _reset_rec_status("rec-001")
        call_updates = mock_update.call_args[0][1]
        # Each _FAILURE_FIELDS entry is set to None in the update dict
        from scripts.executor.jsonl_store import _FAILURE_FIELDS

        for f in _FAILURE_FIELDS:
            assert f in call_updates

    def test_silently_skips_on_error(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.update_rec", side_effect=Exception("portal error")):
            _reset_rec_status("rec-001")  # must not raise

    def test_silently_skips_missing_rec(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.update_rec", return_value=False):
            _reset_rec_status("rec-999")  # must not raise


class TestCreatePostmortemRecommendation:
    """Tests for _create_postmortem_recommendation() -- delegates to ops_data_portal.file_rec."""

    def test_appends_postmortem_entry(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-999") as mock_file_rec:
            _create_postmortem_recommendation("rec-001", "agent/rec-001", ci_attempts=2)
        mock_file_rec.assert_called_once()
        call_fields = mock_file_rec.call_args[0][0]
        assert call_fields["source"] == "executor-postmortem"
        assert call_fields["status"] == "open"
        assert "rec-001" in call_fields["title"]

    def test_silently_skips_on_portal_error(self, tmp_path: Path) -> None:
        with patch("scripts.ops_data_portal.file_rec", side_effect=Exception("portal error")):
            _create_postmortem_recommendation("rec-001", "agent/rec-001", ci_attempts=1)
            # must not raise

    def test_dedupes_when_open_postmortem_exists(self, tmp_path: Path) -> None:
        existing = {
            "id": "rec-529",
            "status": "open",
            "source": "executor-postmortem",
            "title": "Investigate executor failure for rec-001",
            "context": "Executor failed for rec-001.",
        }
        with (
            patch("scripts.ops_data_portal.find_open_postmortem_for", return_value=existing),
            patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update,
            patch("scripts.ops_data_portal.file_rec") as mock_file_rec,
        ):
            _create_postmortem_recommendation("rec-001", "agent/rec-001", ci_attempts=2)

        mock_update.assert_called_once()
        update_id, update_fields = mock_update.call_args[0]
        assert update_id == "rec-529"
        assert "; attempt 2 at " in update_fields["context"]
        assert "last_updated_timestamp" in update_fields
        mock_file_rec.assert_not_called()

    def test_files_new_when_no_open_postmortem_exists(self, tmp_path: Path) -> None:
        with (
            patch("scripts.ops_data_portal.find_open_postmortem_for", return_value=None),
            patch("scripts.ops_data_portal.file_rec", return_value="rec-999") as mock_file_rec,
        ):
            _create_postmortem_recommendation("rec-001", "agent/rec-001", ci_attempts=1)

        mock_file_rec.assert_called_once()
        call_fields = mock_file_rec.call_args[0][0]
        assert call_fields["source"] == "executor-postmortem"
        assert "rec-001" in call_fields["title"]


class TestS3Backend:
    """Tests for S3 backend in load_recommendation() and load_all_recommendations()."""

    def test_load_recommendation_uses_s3_when_backend_s3(self) -> None:
        """load_recommendation() returns entry from S3 when S3 backend is active."""
        s3_entries = [{"id": "rec-001", "status": "open"}, {"id": "rec-002", "status": "closed"}]
        with patch.object(s3_mod, "get_backend", return_value="s3"):
            with patch.object(s3_mod, "_get_s3_client") as mock_client:
                body = "".join(json.dumps(e) + "\n" for e in s3_entries).encode()
                mock_client.return_value.get_object.return_value = {"Body": type("B", (), {"read": lambda self: body})()}
                with patch.dict("os.environ", {"S3_LOG_BUCKET": "test-bucket"}):
                    result = load_recommendation("rec-001")
        assert result is not None
        assert result["id"] == "rec-001"

    def test_load_recommendation_returns_none_for_missing_s3_entry(self) -> None:
        """load_recommendation() returns None when rec not in S3."""
        s3_entries = [{"id": "rec-001", "status": "open"}]
        with patch.object(s3_mod, "get_backend", return_value="s3"):
            with patch.object(s3_mod, "_get_s3_client") as mock_client:
                body = "".join(json.dumps(e) + "\n" for e in s3_entries).encode()
                mock_client.return_value.get_object.return_value = {"Body": type("B", (), {"read": lambda self: body})()}
                with patch.dict("os.environ", {"S3_LOG_BUCKET": "test-bucket"}):
                    result = load_recommendation("rec-999")
        assert result is None

    def test_load_all_recommendations_uses_s3_when_backend_s3(self) -> None:
        """load_all_recommendations() returns dict from S3 when S3 backend is active."""
        s3_entries = [
            {"id": "rec-001", "status": "open"},
            {"id": "rec-002", "status": "closed"},
        ]
        with patch.object(s3_mod, "get_backend", return_value="s3"):
            with patch.object(s3_mod, "_get_s3_client") as mock_client:
                body = "".join(json.dumps(e) + "\n" for e in s3_entries).encode()
                mock_client.return_value.get_object.return_value = {"Body": type("B", (), {"read": lambda self: body})()}
                with patch.dict("os.environ", {"S3_LOG_BUCKET": "test-bucket"}):
                    result = load_all_recommendations()
        assert "rec-001" in result
        assert "rec-002" in result
        assert result["rec-001"]["status"] == "open"

    def test_load_recommendation_last_wins_s3(self) -> None:
        """load_recommendation() returns last matching entry from S3 when duplicate IDs exist."""
        s3_entries = [
            {"id": "rec-005", "status": "open", "acceptance": "grep first file.py"},
            {"id": "rec-005", "status": "closed", "acceptance": "grep second file.py"},
        ]
        with patch.object(store_mod, "get_backend", return_value="s3"):
            with patch.object(store_mod, "read_jsonl", return_value=s3_entries):
                result = load_recommendation("rec-005")
        assert result is not None
        assert result["acceptance"] == "grep second file.py"
        assert result["status"] == "closed"


class TestRecommendationSchema:
    """Tests for Recommendation Pydantic schema validation."""

    def test_valid_minimal_recommendation(self) -> None:
        """Valid recommendation with only required fields."""
        data = {
            "id": "rec-001",
            "date": "2026-04-09",
            "title": "Test recommendation",
            "source": "code-review",
            "effort": "S",
            "priority": "High",
            "status": "open",
            "automatable": True,
            "risk": "low",
            "file": "src/test.py",
            "context": "This is a test",
            "acceptance": "grep -q 'pattern' file.py",
        }
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-001"
        assert rec.status == "open"

    def test_valid_complete_recommendation(self) -> None:
        """Valid recommendation with all fields."""
        data = {
            "id": "rec-042",
            "date": "2026-04-09",
            "title": "Complete recommendation",
            "source": "executor-supervision",
            "effort": "M",
            "priority": "Critical",
            "status": "closed",
            "automatable": True,
            "risk": "high",
            "file": "scripts/executor/plan.py",
            "context": "Full context here",
            "acceptance": "test command",
            "dependencies": ["rec-001", "rec-002"],
            "tags": ["critical", "executor"],
            "resolution": "Implemented successfully",
            "execution_result": "success",
            "execution_date": "2026-04-09T20:00:00Z",
            "execution_branch": "agent/rec-042",
            "execution_pr_url": "https://github.com/org/repo/pull/123",
            "execution_steps": 3,
            "failure_step": None,
            "failure_reason": None,
            "execution_steps_attempted": 3,
            "execution_steps_total": 3,
        }
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-042"
        assert rec.status == "closed"

    def test_rejects_dec_id_format(self) -> None:
        """Reject IDs starting with dec- prefix."""
        data = {
            "id": "dec-001",
            "status": "open",
        }
        with pytest.raises(ValidationError, match="Invalid ID prefix: dec-001"):
            Recommendation.model_validate(data)

    def test_rejects_invalid_status_value(self) -> None:
        """Rejects status values outside the enforced Literal domain."""
        for bad_status in ("done", "Decided", "Unknown", ""):
            data = {"id": "rec-001", "status": bad_status}
            with pytest.raises(ValidationError):
                Recommendation.model_validate(data)

    def test_accepts_valid_status_values(self) -> None:
        """Accepts all five valid lifecycle states."""
        for status in ("open", "closed", "failed", "declined", "superseded"):
            rec = Recommendation.model_validate({"id": "rec-001", "status": status})
            assert rec.status == status

    def test_accepts_any_effort_value(self) -> None:
        """Accepts any effort string for legacy compatibility."""
        data = {
            "id": "rec-001",
            "status": "open",
            "effort": "HUGE",
        }
        rec = Recommendation.model_validate(data)
        assert rec.effort == "HUGE"

    def test_accepts_any_priority_value(self) -> None:
        """Accepts any priority string for legacy compatibility."""
        data = {
            "id": "rec-001",
            "status": "open",
            "priority": "Urgent",
        }
        rec = Recommendation.model_validate(data)
        assert rec.priority == "Urgent"

    def test_accepts_any_risk_value(self) -> None:
        """Accepts any risk string for legacy compatibility."""
        data = {
            "id": "rec-001",
            "status": "open",
            "risk": "extreme",
        }
        rec = Recommendation.model_validate(data)
        assert rec.risk == "extreme"

    def test_rejects_missing_status(self) -> None:
        """Rejects when required status field is missing."""
        data = {
            "id": "rec-001",
        }
        with pytest.raises(ValidationError):
            Recommendation.model_validate(data)

    def test_ignores_extra_fields(self) -> None:
        """Extra fields are silently ignored (extra='ignore') for backward compat with legacy Iceberg rows."""
        data = {
            "id": "rec-001",
            "status": "open",
            "foo": "unknown field",
            "legacy_field": 123,
        }
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-001"
        assert not hasattr(rec, "foo")

    def test_accepts_scd2_timestamp_fields(self) -> None:
        """Accepts SCD2 timestamp metadata fields (view-only dedup columns must not be present)."""
        data = {
            "id": "rec-001",
            "status": "open",
            "created_timestamp": "2026-05-01 21:00:16.050000",
            "last_updated_timestamp": "2026-05-01 21:05:17.351000",
        }
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-001"
        assert rec.created_timestamp == "2026-05-01 21:00:16.050000"

    def test_ignores_row_num_field(self) -> None:
        """row_num is a view-only SCD2 artifact; model ignores it (extra='ignore')."""
        data = {"id": "rec-001", "status": "open", "row_num": 1}
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-001"
        assert not hasattr(rec, "row_num")

    def test_ignores_rn_alias_field(self) -> None:
        """_rn is a view-only SCD2 artifact; model ignores it (extra='ignore')."""
        data = {"id": "rec-001", "status": "open", "_rn": "1"}
        rec = Recommendation.model_validate(data)
        assert rec.id == "rec-001"
        assert not hasattr(rec, "_rn")

    def test_accepts_long_title(self) -> None:
        """Accepts long titles for legacy compatibility."""
        data = {
            "id": "rec-001",
            "status": "open",
            "title": "x" * 200,
        }
        rec = Recommendation.model_validate(data)
        assert len(rec.title) == 200
