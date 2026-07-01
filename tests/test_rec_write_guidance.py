"""Tests for scripts/executor/rec_write_guidance.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


class TestLoadSourceRegistry:
    """Tests for load_source_registry()."""

    def test_returns_34_entries(self) -> None:
        """load_source_registry() returns 34 canonical entries (includes ci_rca_probe_health)."""
        from scripts.executor.rec_write_guidance import load_source_registry

        entries = load_source_registry()
        assert len(entries) == 34

    def test_entries_have_required_keys(self) -> None:
        """Every entry has canonical_id, description, signal_interpretation, added_date."""
        from scripts.executor.rec_write_guidance import load_source_registry

        required_keys = {"canonical_id", "description", "signal_interpretation", "added_date"}
        for entry in load_source_registry():
            missing = required_keys - entry.keys()
            assert not missing, f"Entry {entry.get('canonical_id')} missing keys: {missing}"

    def test_custom_registry_path(self, tmp_path: Path) -> None:
        """load_source_registry() accepts an override path and reads from it."""
        from scripts.executor import rec_write_guidance

        registry = tmp_path / "registry.yaml"
        entry = {"canonical_id": "test-agent", "description": "d", "signal_interpretation": "s", "added_date": "2026-01-01"}
        registry.write_text(
            yaml.dump({"entries": [entry]}),
            encoding="utf-8",
        )
        rec_write_guidance._load_registry_cached.cache_clear()
        try:
            entries = rec_write_guidance.load_source_registry(registry)
            assert len(entries) == 1
            assert entries[0]["canonical_id"] == "test-agent"
        finally:
            rec_write_guidance._load_registry_cached.cache_clear()


class TestValidateSource:
    """Tests for validate_source()."""

    def test_registered_value_raises_no_exception(self) -> None:
        """validate_source() accepts a known canonical_id without raising."""
        from scripts.executor.rec_write_guidance import validate_source

        validate_source("planning")
        validate_source("manual")
        validate_source("code-review")

    def test_unregistered_value_raises_value_error(self) -> None:
        """validate_source() raises ValueError for unknown source values."""
        from scripts.executor.rec_write_guidance import validate_source

        with pytest.raises(ValueError, match="Unknown source 'ghost-agent'"):
            validate_source("ghost-agent")

    def test_empty_string_raises_value_error(self) -> None:
        """validate_source() rejects empty string."""
        from scripts.executor.rec_write_guidance import validate_source

        with pytest.raises(ValueError):
            validate_source("")

    def test_case_sensitive_match(self) -> None:
        """validate_source() is case-sensitive -- 'Planning' != 'planning'."""
        from scripts.executor.rec_write_guidance import validate_source

        with pytest.raises(ValueError):
            validate_source("Planning")


class TestGetRecWriteGuidance:
    """Tests for get_rec_write_guidance()."""

    def test_returns_dict_with_source_key(self) -> None:
        """get_rec_write_guidance() returns a dict containing a 'source' key."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        assert isinstance(guidance, dict)
        assert "source" in guidance

    def test_source_entry_has_semantics(self) -> None:
        """The 'source' entry has a non-empty 'semantics' string."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        source = guidance["source"]
        assert isinstance(source.get("semantics"), str)
        assert len(source["semantics"]) > 0

    def test_source_entry_has_registered_values_list(self) -> None:
        """The 'source' entry carries a 'registered_values' list containing 'planning'."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        registered = guidance["source"].get("registered_values")
        assert isinstance(registered, list)
        assert "planning" in registered

    def test_registered_values_has_34_entries(self) -> None:
        """'registered_values' list has 34 registry entries (includes ci_rca_probe_health)."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        assert len(guidance["source"]["registered_values"]) == 34

    def test_other_columns_have_description_and_semantics(self) -> None:
        """Non-source columns also carry description and semantics."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        for col_name, col_data in guidance.items():
            if col_name == "source":
                continue
            assert "description" in col_data, f"{col_name} missing description"
            assert "semantics" in col_data, f"{col_name} missing semantics"
