"""Tests for scripts/copilot_multipliers_refresher.py.

Covers HTML parsing, multiplier comparison, metadata updates, YAML writing,
and error handling without making real network calls.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.copilot_multipliers_refresher import (
    compare_multipliers,
    fetch_docs_page,
    load_config,
    parse_multipliers_from_html,
    update_metadata,
    write_config,
)


class TestFetchDocsPage:
    """Tests for fetch_docs_page()."""

    def test_fetch_success(self) -> None:
        """fetch_docs_page returns content on successful HTTP request."""
        mock_response = MagicMock()
        mock_response.text = "<html>test content</html>"
        mock_response.raise_for_status = MagicMock()

        with patch("scripts.copilot_multipliers_refresher.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = fetch_docs_page()

        assert result == "<html>test content</html>"
        mock_get.assert_called_once()

    def test_fetch_failure_raises_exception(self) -> None:
        """fetch_docs_page raises exception on HTTP error."""
        with patch("scripts.copilot_multipliers_refresher.requests.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            with pytest.raises(Exception, match="Network error"):
                fetch_docs_page()


class TestParseMultipliersFromHtml:
    """Tests for parse_multipliers_from_html()."""

    def test_parse_valid_table(self) -> None:
        """Parses multipliers from HTML table with model names and values."""
        html = """
        <table>
            <tr><td>Claude Haiku 4.5</td><td>0.33</td></tr>
            <tr><td>Claude Sonnet 4.6</td><td>1.0</td></tr>
            <tr><td>Claude Opus 4.6</td><td>3.0</td></tr>
        </table>
        """
        result = parse_multipliers_from_html(html)

        assert result["claude-haiku-4.5"] == 0.33
        assert result["claude-sonnet-4.6"] == 1.0
        assert result["claude-opus-4.6"] == 3.0

    def test_parse_skips_header_rows(self) -> None:
        """Skips rows with header names like 'Model', 'Model name', 'Name'."""
        html = """
        <table>
            <tr><th>Model</th><th>Multiplier</th></tr>
            <tr><td>Claude Haiku 4.5</td><td>0.33</td></tr>
        </table>
        """
        result = parse_multipliers_from_html(html)

        assert "model" not in result
        assert result["claude-haiku-4.5"] == 0.33

    def test_parse_normalizes_spaces_and_parentheses(self) -> None:
        """Converts spaces and parentheses to hyphens in model names."""
        html = """
        <table>
            <tr><td>Claude Opus 4.6 (fast mode) (preview)</td><td>30.0</td></tr>
        </table>
        """
        result = parse_multipliers_from_html(html)

        assert "claude-opus-4.6-fast-mode-preview" in result
        assert result["claude-opus-4.6-fast-mode-preview"] == 30.0

    def test_parse_empty_html_returns_empty_dict(self) -> None:
        """Returns empty dict when no tables found."""
        html = "<html><body>No tables here</body></html>"
        result = parse_multipliers_from_html(html)

        assert result == {}

    def test_parse_invalid_multiplier_skipped(self) -> None:
        """Skips rows with non-numeric multiplier values."""
        html = """
        <table>
            <tr><td>Claude Haiku 4.5</td><td>invalid</td></tr>
            <tr><td>Claude Sonnet 4.6</td><td>1.0</td></tr>
        </table>
        """
        result = parse_multipliers_from_html(html)

        assert "claude-haiku-4.5" not in result
        assert result["claude-sonnet-4.6"] == 1.0


class TestCompareMultipliers:
    """Tests for compare_multipliers()."""

    def test_all_match_returns_true(self) -> None:
        """Returns (True, []) when parsed and config multipliers match."""
        parsed = {"claude-haiku-4.5": 0.33, "claude-sonnet-4.6": 1.0}
        config = {"multipliers": {"claude-haiku-4.5": 0.33, "claude-sonnet-4.6": 1.0}}

        all_match, discrepancies = compare_multipliers(parsed, config)

        assert all_match is True
        assert discrepancies == []

    def test_missing_in_config_detected(self) -> None:
        """Detects models in parsed but not in config."""
        parsed = {"new-model": 2.0, "claude-haiku-4.5": 0.33}
        config = {"multipliers": {"claude-haiku-4.5": 0.33}}

        all_match, discrepancies = compare_multipliers(parsed, config)

        assert all_match is False
        assert any("new-model" in d and "not in config" in d for d in discrepancies)

    def test_missing_in_parsed_detected(self) -> None:
        """Detects models in config but not in parsed."""
        parsed = {"claude-haiku-4.5": 0.33}
        config = {"multipliers": {"claude-haiku-4.5": 0.33, "old-model": 1.0}}

        all_match, discrepancies = compare_multipliers(parsed, config)

        assert all_match is False
        assert any("old-model" in d and "not found in docs" in d for d in discrepancies)

    def test_value_mismatch_detected(self) -> None:
        """Detects when a model's multiplier value differs."""
        parsed = {"claude-haiku-4.5": 0.5}
        config = {"multipliers": {"claude-haiku-4.5": 0.33}}

        all_match, discrepancies = compare_multipliers(parsed, config)

        assert all_match is False
        assert any("claude-haiku-4.5" in d and "config=0.33" in d for d in discrepancies)


class TestUpdateMetadata:
    """Tests for update_metadata()."""

    def test_sets_last_verified_to_today(self) -> None:
        """Sets last_verified to today's date."""
        config = {"metadata": {}}
        updated = update_metadata(config)

        today = datetime.now(timezone.utc).date()
        assert updated["metadata"]["last_verified"] == str(today)

    def test_sets_next_review_30_days_ahead(self) -> None:
        """Sets next_review to 30 days from today."""
        config = {"metadata": {}}
        updated = update_metadata(config)

        today = datetime.now(timezone.utc).date()
        expected = today + timedelta(days=30)
        assert updated["metadata"]["next_review"] == str(expected)

    def test_creates_metadata_if_missing(self) -> None:
        """Creates metadata dict if it doesn't exist."""
        config = {}
        updated = update_metadata(config)

        assert "metadata" in updated
        assert "last_verified" in updated["metadata"]
        assert "next_review" in updated["metadata"]


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Loads valid YAML config from file."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            """
metadata:
  source_url: https://example.com
  last_verified: '2026-04-01'
default_multiplier: 1.0
multipliers:
  claude-haiku-4.5: 0.33
""",
            encoding="utf-8",
        )

        with patch(
            "scripts.copilot_multipliers_refresher.CONFIG_PATH",
            config_file,
        ):
            result = load_config()

        assert result["metadata"]["source_url"] == "https://example.com"
        assert result["default_multiplier"] == 1.0
        assert result["multipliers"]["claude-haiku-4.5"] == 0.33

    def test_load_nonexistent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Returns empty dict if config file doesn't exist."""
        with patch(
            "scripts.copilot_multipliers_refresher.CONFIG_PATH",
            tmp_path / "nonexistent.yaml",
        ):
            result = load_config()

        assert result == {}


class TestWriteConfig:
    """Tests for write_config()."""

    def test_writes_yaml_to_file(self, tmp_path: Path) -> None:
        """Writes config dict to YAML file."""
        config_file = tmp_path / "test.yaml"
        config = {
            "metadata": {"last_verified": "2026-04-03"},
            "default_multiplier": 1.0,
            "multipliers": {"claude-haiku-4.5": 0.33},
        }

        with patch(
            "scripts.copilot_multipliers_refresher.CONFIG_PATH",
            config_file,
        ):
            write_config(config)

        assert config_file.exists()
        content = config_file.read_text(encoding="utf-8")
        assert "last_verified: '2026-04-03'" in content
        assert "default_multiplier: 1.0" in content


class TestIntegration:
    """Integration tests for the full refresh workflow."""

    def test_full_refresh_no_changes(self) -> None:
        """Full workflow: fetch, parse, compare (no changes), update metadata."""
        html = """
        <table>
            <tr><td>Claude Haiku 4.5</td><td>0.33</td></tr>
            <tr><td>Claude Sonnet 4.6</td><td>1.0</td></tr>
        </table>
        """
        config = {
            "metadata": {},
            "default_multiplier": 1.0,
            "multipliers": {
                "claude-haiku-4.5": 0.33,
                "claude-sonnet-4.6": 1.0,
            },
        }

        parsed = parse_multipliers_from_html(html)
        all_match, _ = compare_multipliers(parsed, config)
        updated_config = update_metadata(config)

        assert all_match is True
        assert "last_verified" in updated_config["metadata"]

    def test_full_refresh_with_discrepancies(self) -> None:
        """Full workflow: detects and logs discrepancies but still updates metadata."""
        html = """
        <table>
            <tr><td>Claude Haiku 4.5</td><td>0.5</td></tr>
            <tr><td>Claude Sonnet 4.6</td><td>1.0</td></tr>
            <tr><td>New Model</td><td>2.0</td></tr>
        </table>
        """
        config = {
            "metadata": {},
            "default_multiplier": 1.0,
            "multipliers": {
                "claude-haiku-4.5": 0.33,
                "claude-sonnet-4.6": 1.0,
            },
        }

        parsed = parse_multipliers_from_html(html)
        all_match, discrepancies = compare_multipliers(parsed, config)
        updated_config = update_metadata(config)

        assert all_match is False
        assert len(discrepancies) > 0
        assert "last_verified" in updated_config["metadata"]
