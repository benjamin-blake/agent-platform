"""Tests for Decision Pydantic model and reader API in scripts/executor/jsonl_store.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from scripts.executor.jsonl_store import DECISIONS_JSONL, Decision, load_all_decisions, load_decision

_VALID_DECISION = {
    "id": "dec-072",
    "decision_id": 72,
    "title": "Test Decision",
    "status": "Decided",
    "created_timestamp": "2026-05-13T12:00:00Z",
    "last_updated_timestamp": "2026-05-13T12:00:00Z",
}


class TestDecisionModel:
    """Tests for the Decision Pydantic model (D6)."""

    def test_valid_matched_pair(self) -> None:
        """Decision accepts matched id/decision_id pair."""
        d = Decision.model_validate(_VALID_DECISION)
        assert d.id == "dec-072"
        assert d.decision_id == 72

    def test_id_regex_valid(self) -> None:
        """dec-NNN format passes validation."""
        d = Decision.model_validate({**_VALID_DECISION, "id": "dec-001", "decision_id": 1})
        assert d.id == "dec-001"

    def test_id_regex_invalid(self) -> None:
        """Non-dec-NNN format raises ValidationError."""
        with pytest.raises(ValidationError):
            Decision.model_validate({**_VALID_DECISION, "id": "rec-001"})

    def test_id_regex_empty(self) -> None:
        """Empty id raises ValidationError."""
        with pytest.raises(ValidationError):
            Decision.model_validate({**_VALID_DECISION, "id": ""})

    def test_dual_write_invariant_mismatch_raises(self) -> None:
        """Mismatched id/decision_id raises ValidationError."""
        bad = {**_VALID_DECISION, "id": "dec-073", "decision_id": 72}
        with pytest.raises(ValidationError) as exc_info:
            Decision.model_validate(bad)
        assert "dual-write invariant" in str(exc_info.value).lower()

    def test_dual_write_invariant_match_passes(self) -> None:
        """Matched id/decision_id passes the validator."""
        d = Decision.model_validate({**_VALID_DECISION, "id": "dec-072", "decision_id": 72})
        assert d.id == "dec-072"
        assert d.decision_id == 72

    def test_no_decision_id_skips_invariant(self) -> None:
        """When decision_id is absent the dual-write invariant is skipped."""
        fields = {k: v for k, v in _VALID_DECISION.items() if k != "decision_id"}
        d = Decision.model_validate(fields)
        assert d.id == "dec-072"
        assert d.decision_id is None

    def test_extra_fields_ignored(self) -> None:
        """Unknown fields are silently dropped (extra=ignore)."""
        d = Decision.model_validate({**_VALID_DECISION, "_rn": 1, "trade_date": "2026-05-13"})
        assert not hasattr(d, "_rn")
        assert not hasattr(d, "trade_date")

    def test_optional_fields_default_none(self) -> None:
        """Optional fields default to None when absent."""
        d = Decision.model_validate(_VALID_DECISION)
        assert d.problem is None
        assert d.decision_text is None
        assert d.context is None
        assert d.decided_date is None
        assert d.related_decisions is None
        assert d.related_decisions_v2 is None

    def test_schema_roundtrip(self) -> None:
        """model_dump / model_validate round-trip preserves all fields."""
        d = Decision.model_validate(_VALID_DECISION)
        dumped = d.model_dump(exclude_none=True)
        d2 = Decision.model_validate(dumped)
        assert d2.id == d.id
        assert d2.decision_id == d.decision_id
        assert d2.title == d.title

    def test_dec_id_prefix_forbidden_on_rec_id(self) -> None:
        """rec- prefix fails the dec-NNN regex."""
        with pytest.raises(ValidationError):
            Decision.model_validate({**_VALID_DECISION, "id": "rec-072"})

    def test_decisions_jsonl_constant(self) -> None:
        """DECISIONS_JSONL constant points at the correct path."""
        assert DECISIONS_JSONL.as_posix() == "logs/.decisions-index.jsonl"


class TestLoadDecision:
    """Tests for load_decision() (D8)."""

    def test_load_by_string_id(self, tmp_path: Path) -> None:
        """load_decision('dec-072') returns matching entry."""
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(json.dumps(_VALID_DECISION) + "\n", encoding="utf-8")
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_decision("dec-072")
        assert result is not None
        assert result["id"] == "dec-072"

    def test_load_by_int_id(self, tmp_path: Path) -> None:
        """load_decision(72) resolves to dec-072."""
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(json.dumps(_VALID_DECISION) + "\n", encoding="utf-8")
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_decision(72)
        assert result is not None
        assert result["id"] == "dec-072"

    def test_load_last_wins(self, tmp_path: Path) -> None:
        """When the same id appears twice, the last entry wins."""
        first = {**_VALID_DECISION, "title": "First version"}
        second = {**_VALID_DECISION, "title": "Second version"}
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(
            json.dumps(first) + "\n" + json.dumps(second) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_decision("dec-072")
        assert result is not None
        assert result["title"] == "Second version"

    def test_load_not_found_returns_none(self, tmp_path: Path) -> None:
        """load_decision returns None when id is absent."""
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(json.dumps(_VALID_DECISION) + "\n", encoding="utf-8")
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_decision("dec-999")
        assert result is None

    def test_load_file_not_found_returns_none(self, tmp_path: Path) -> None:
        """load_decision returns None when JSONL file is absent."""
        missing = tmp_path / "missing.jsonl"
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", missing):
            result = load_decision("dec-001")
        assert result is None

    def test_load_skips_blank_and_comment_lines(self, tmp_path: Path) -> None:
        """Blank and comment lines in JSONL are skipped."""
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(
            "# comment\n\n" + json.dumps(_VALID_DECISION) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_decision("dec-072")
        assert result is not None


class TestLoadAllDecisions:
    """Tests for load_all_decisions() (D8)."""

    def test_load_all_keyed_by_id(self, tmp_path: Path) -> None:
        """load_all_decisions returns dict keyed by id."""
        entry2 = {**_VALID_DECISION, "id": "dec-073", "decision_id": 73, "title": "Second"}
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(
            json.dumps(_VALID_DECISION) + "\n" + json.dumps(entry2) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_all_decisions()
        assert "dec-072" in result
        assert "dec-073" in result
        assert result["dec-072"]["title"] == _VALID_DECISION["title"]

    def test_load_all_empty_on_missing_file(self, tmp_path: Path) -> None:
        """load_all_decisions returns empty dict when file is absent."""
        missing = tmp_path / "missing.jsonl"
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", missing):
            result = load_all_decisions()
        assert result == {}

    def test_load_all_last_wins(self, tmp_path: Path) -> None:
        """load_all_decisions uses last-wins semantics for duplicate ids."""
        first = {**_VALID_DECISION, "title": "First"}
        second = {**_VALID_DECISION, "title": "Second"}
        jsonl = tmp_path / ".decisions-index.jsonl"
        jsonl.write_text(
            json.dumps(first) + "\n" + json.dumps(second) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.executor.jsonl_store.DECISIONS_JSONL", jsonl):
            result = load_all_decisions()
        assert result["dec-072"]["title"] == "Second"
