"""Tests for validate_rec_relevance_contract() -- T3.8 enum-drift guard."""

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks.ops_governance.validate_rec_relevance_contract import validate_rec_relevance_contract


class TestValidateRecRelevanceContract:
    """Tests for validate_rec_relevance_contract() -- T3.8 enum-drift guard."""

    def test_passes_on_live_contract(self) -> None:
        """The live recommendation-relevance.yaml passes the guard (no drift)."""
        failed: list[str] = []
        validate_rec_relevance_contract(failed)
        assert not failed, f"unexpected failures: {failed}"

    def test_fails_when_contract_missing(self, tmp_path: Path) -> None:
        """Missing contract file -> failure appended."""
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            (tmp_path / "docs" / "contracts").mkdir(parents=True)
            validate_rec_relevance_contract(failed)
        assert any("not found" in f for f in failed)

    def test_fails_when_contract_unparseable(self, tmp_path: Path) -> None:
        """Unparseable YAML -> failure appended."""
        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(": invalid: [yaml", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("parse error" in f for f in failed)

    def test_fails_when_contract_declares_columns(self, tmp_path: Path) -> None:
        """Contract with 'columns' key -> Decision 84 violation."""

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": ["relevant", "unknown"], "columns": {"foo": "bar"}}
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("Decision 84" in f or "columns" in f for f in failed)

    def test_fails_when_verdict_enum_drifts(self, tmp_path: Path) -> None:
        """Contract verdicts != RELEVANCE_VERDICTS -> drift failure."""

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": ["relevant", "satisfied", "unknown"]}  # missing 5 verdicts
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("drift" in f for f in failed)

    def test_fails_when_verdicts_empty(self, tmp_path: Path) -> None:
        """Contract with empty verdicts -> failure."""

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": []}
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert failed
