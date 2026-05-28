"""Unit tests for scripts/classify_risk.py"""

import json
from unittest.mock import MagicMock, patch

from scripts.classify_risk import classify_all_unclassified, classify_risk


class TestClassifyRisk:
    """Test risk classification functions."""

    def test_classify_risk_low(self, tmp_path, monkeypatch):
        """Test classification of low-risk recommendation."""
        monkeypatch.chdir(tmp_path)

        with patch("scripts.classify_risk.llm_call") as mock_call:
            mock_call.return_value = MagicMock(exit_code=0, content="LOW")
            result = classify_risk("rec-001", "Safe change", "Well-tested area")
            assert result == "low"

    def test_classify_risk_high(self, tmp_path, monkeypatch):
        """Test classification of high-risk recommendation."""
        monkeypatch.chdir(tmp_path)

        with patch("scripts.classify_risk.llm_call") as mock_call:
            mock_call.return_value = MagicMock(exit_code=0, content="HIGH")
            result = classify_risk("rec-002", "Risky refactor", "Critical system")
            assert result == "high"

    def test_classify_risk_call_failure(self, tmp_path, monkeypatch):
        """Test classification when copilot call fails."""
        monkeypatch.chdir(tmp_path)

        with patch("scripts.classify_risk.llm_call") as mock_call:
            mock_call.return_value = MagicMock(exit_code=1, content="")
            result = classify_risk("rec-003", "Any change", "")
            assert result == "unclassified"

    def test_classify_all_unclassified(self, tmp_path, monkeypatch):
        """Test batch classification of all unclassified recommendations."""
        monkeypatch.chdir(tmp_path)

        recs_file = tmp_path / "logs" / ".recommendations-log.jsonl"
        recs_file.parent.mkdir(parents=True)

        schema = '# Schema: {"id": "rec-NNN", "risk": "unclassified|low|medium|high"}'
        entry1 = json.dumps({"id": "rec-100", "title": "Test 1", "risk": "unclassified", "status": "open"})
        entry2 = json.dumps({"id": "rec-101", "title": "Test 2", "risk": "low", "status": "open"})
        entry3 = json.dumps({"id": "rec-102", "title": "Test 3", "risk": "unclassified", "status": "open"})

        recs_file.write_text(f"{schema}\n{entry1}\n{entry2}\n{entry3}\n")

        with (
            patch("scripts.classify_risk.get_backend", return_value="local"),
            patch("scripts.classify_risk.llm_call") as mock_call,
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            mock_call.return_value = MagicMock(exit_code=0, content="LOW")
            count = classify_all_unclassified()
            assert count == 2
            assert mock_update.call_count == 2
