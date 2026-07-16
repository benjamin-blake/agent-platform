"""Tests for validate_recommendations_schema() -- specifically the python -c ban."""

import json
from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_recommendations_schema import validate_recommendations_schema


class TestValidateRecommendationsSchema:
    """Tests for validate_recommendations_schema() — specifically the python -c ban."""

    _VALID_REC = {
        "id": "rec-001",
        "date": "2026-01-01",
        "title": "Test recommendation",
        "source": "executor-supervision",
        "effort": "XS",
        "priority": "Low",
        "status": "open",
        "automatable": True,
        "risk": "low",
        "file": "scripts/foo.py",
        "context": "Some context.",
        "acceptance": "`grep -q 'pattern' scripts/foo.py`",
    }

    def _write_jsonl(self, tmp_path: Path, entries: list[dict]) -> Path:

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        recs_path = log_dir / ".recommendations-log.jsonl"
        recs_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return recs_path

    def test_passes_on_valid_rec(self, tmp_path: Path) -> None:
        """A well-formed rec with a safe acceptance command passes."""
        self._write_jsonl(tmp_path, [self._VALID_REC])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert failed == []

    def test_fails_when_acceptance_contains_python_c(self, tmp_path: Path) -> None:
        """An acceptance field containing 'python -c' triggers a schema error."""
        import copy

        bad_rec = copy.deepcopy(self._VALID_REC)
        bad_rec["acceptance"] = '`python -c "import foo; assert foo.bar"`'
        self._write_jsonl(tmp_path, [bad_rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert "Recommendations schema validation" in failed

    def test_skips_when_file_missing(self, tmp_path: Path) -> None:
        """No error when the JSONL file does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert failed == []
