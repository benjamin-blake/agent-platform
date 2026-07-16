"""Eligibility, rec-status, and rec loading tests (rec-2709 Wave 2)."""

import json
from unittest.mock import patch

import pytest

from scripts.execute_recommendation import (
    _is_poisoned_rec,
    is_eligible,
    load_all_recommendations,
    update_recommendation_status,
)


class TestIsEligible:
    """Test eligibility filtering."""

    def test_is_eligible_true(self):
        """Test eligible recommendation."""
        rec = {"risk": "low", "automatable": True, "effort": "XS"}
        assert is_eligible(rec) is True, "Expected is_eligible to return True for low-risk automatable recommendation"

    def test_is_eligible_false_high_risk(self):
        """Test ineligible recommendation - high risk."""
        rec = {"risk": "high", "automatable": True}
        assert is_eligible(rec) is False, "Expected is_eligible to return False for high-risk recommendation"

    def test_is_eligible_false_not_automatable(self):
        """Test ineligible recommendation - not automatable."""
        rec = {"risk": "low", "automatable": False}
        assert is_eligible(rec) is False, "Expected is_eligible to return False for non-automatable recommendation"

    def test_is_eligible_false_both(self):
        """Test ineligible recommendation - both conditions."""
        rec = {"risk": "medium", "automatable": False}
        assert is_eligible(rec) is False, "Expected is_eligible to return False for medium-risk non-automatable recommendation"


class TestIsPoisonedRec:
    """Unit tests for the _is_poisoned_rec() PYTEST_CURRENT_TEST guard."""

    def test_poisoned_rec_pytest_guard(self, monkeypatch):
        """Guard returns False during pytest runs; real postmortem lookup returns True without it."""
        import scripts.ops_data_portal as _portal

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_execute_recommendation.py::t")
        monkeypatch.delenv("ALLOW_POISONED_RECS", raising=False)
        assert _is_poisoned_rec("rec-100") is False

        fake = {"id": "rec-606", "status": "open", "title": "Investigate executor failure for rec-100"}
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr(_portal, "find_open_postmortem_for", lambda rec_id: fake)
        assert _is_poisoned_rec("rec-100") is True


class TestIsEligibleStatus:
    """Test is_eligible() with closed/failed status."""

    def test_is_eligible_false_status_closed(self):
        """Closed recs must not be re-executed."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "status": "closed"}
        assert is_eligible(rec) is False

    def test_is_eligible_false_status_failed(self):
        """Failed recs must not be re-executed."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "status": "failed"}
        assert is_eligible(rec) is False

    def test_is_eligible_true_status_open(self):
        """Open recs with correct attributes are eligible."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "status": "open"}
        assert is_eligible(rec) is True

    def test_is_eligible_true_no_status_field(self):
        """Missing status field defaults to open (eligible)."""
        rec = {"risk": "low", "automatable": True, "effort": "S"}
        assert is_eligible(rec) is True

    def test_is_eligible_rejects_m_effort(self):
        """Effort gate: M-effort recs are not eligible."""
        rec = {"risk": "low", "automatable": True, "effort": "M", "status": "open"}
        assert is_eligible(rec) is False

    def test_is_eligible_rejects_large_file(self, tmp_path):
        """SLOC gate: files over 800 SLOC are not eligible."""
        big_file = tmp_path / "big_module.py"
        big_file.write_text("\n".join(f"x = {i}" for i in range(801)), encoding="utf-8")
        rec = {
            "risk": "low",
            "automatable": True,
            "effort": "S",
            "status": "open",
            "file": str(big_file),
        }
        assert is_eligible(rec) is False

    def test_is_eligible_accepts_xs_small_file(self, tmp_path):
        """Positive case: XS effort targeting a small file is eligible."""
        small_file = tmp_path / "tiny_module.py"
        small_file.write_text("\n".join(f"y = {i}" for i in range(50)), encoding="utf-8")
        rec = {
            "risk": "low",
            "automatable": True,
            "effort": "XS",
            "status": "open",
            "file": str(small_file),
        }
        assert is_eligible(rec) is True


class TestUpdateRecommendationStatus:
    """Test update_recommendation_status() -- delegates to ops_data_portal.update_rec."""

    def test_delegates_to_update_rec(self) -> None:
        """update_recommendation_status calls ops_data_portal.update_rec and returns its result."""
        with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
            result = update_recommendation_status("rec-100", {"status": "closed", "execution_result": "success"})
        mock_update.assert_called_once_with("rec-100", {"status": "closed", "execution_result": "success"})
        assert result is True

    def test_propagates_false_when_not_found(self) -> None:
        """Returns False when update_rec indicates rec was not found."""
        with patch("scripts.ops_data_portal.update_rec", return_value=False):
            result = update_recommendation_status("rec-999", {"status": "closed"})
        assert result is False

    def test_rejects_invalid_status(self) -> None:
        """Invalid status raises ValueError (raised by update_rec)."""
        with patch(
            "scripts.ops_data_portal.update_rec",
            side_effect=ValueError("Invalid status"),
        ):
            with pytest.raises(ValueError, match="Invalid status"):
                update_recommendation_status("rec-100", {"status": "done"})


class TestLoadAllRecommendations:
    """Test load_all_recommendations() helper."""

    def _make_recs_file(self, tmp_path: object, entries: list[dict]) -> object:
        recs_file = tmp_path / "logs" / ".recommendations-log.jsonl"
        recs_file.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Schema: {id, title, risk, automatable, status}\n"]
        for entry in entries:
            lines.append(json.dumps(entry) + "\n")
        recs_file.write_text("".join(lines), encoding="utf-8")
        return recs_file

    def test_load_all_returns_dict_keyed_by_id(self, tmp_path):
        """All entries are returned in a dict keyed by id."""
        recs_file = self._make_recs_file(
            tmp_path,
            [
                {"id": "rec-001", "title": "First", "status": "open"},
                {"id": "rec-002", "title": "Second", "status": "closed"},
            ],
        )
        with patch("scripts.executor.jsonl_store.RECS_JSONL", recs_file):
            result = load_all_recommendations()
        assert "rec-001" in result
        assert "rec-002" in result
        assert result["rec-001"]["title"] == "First"
        assert result["rec-002"]["status"] == "closed"

    def test_load_all_empty_file(self, tmp_path):
        """An empty/schema-only file returns empty dict."""
        recs_file = tmp_path / "logs" / ".recommendations-log.jsonl"
        recs_file.parent.mkdir(parents=True, exist_ok=True)
        recs_file.write_text("# Schema: {id}\n", encoding="utf-8")
        with patch("scripts.executor.jsonl_store.RECS_JSONL", recs_file):
            result = load_all_recommendations()
        assert result == {}

    def test_load_all_missing_file(self, tmp_path):
        """Missing JSONL returns empty dict without raising."""
        missing = tmp_path / "logs" / ".recommendations-log.jsonl"
        with patch("scripts.executor.jsonl_store.RECS_JSONL", missing):
            result = load_all_recommendations()
        assert result == {}


class TestIsEligibleDependencies:
    """Test is_eligible() dependency resolution."""

    def test_no_dependencies_field_eligible(self):
        """Rec with no dependencies key is eligible (when other conditions met)."""
        rec = {"risk": "low", "automatable": True, "effort": "S"}
        assert is_eligible(rec) is True

    def test_empty_dependencies_eligible(self):
        """Rec with empty dependencies list is eligible."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "dependencies": []}
        assert is_eligible(rec) is True

    def test_all_dependencies_closed_eligible(self):
        """Rec is eligible when all dependencies have status == closed."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "dependencies": ["rec-001", "rec-002"]}
        recs_by_id = {
            "rec-001": {"id": "rec-001", "status": "closed"},
            "rec-002": {"id": "rec-002", "status": "closed"},
        }
        assert is_eligible(rec, recs_by_id=recs_by_id) is True

    def test_one_dependency_open_ineligible(self):
        """Rec is ineligible when one dependency is still open."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "dependencies": ["rec-001", "rec-002"]}
        recs_by_id = {
            "rec-001": {"id": "rec-001", "status": "closed"},
            "rec-002": {"id": "rec-002", "status": "open"},
        }
        assert is_eligible(rec, recs_by_id=recs_by_id) is False

    def test_missing_dependency_id_ineligible(self):
        """Rec is ineligible when a dependency ID is not found (conservative)."""
        rec = {"risk": "low", "automatable": True, "effort": "S", "dependencies": ["rec-999"]}
        recs_by_id: dict = {}  # rec-999 not present
        assert is_eligible(rec, recs_by_id=recs_by_id) is False
