"""Tests for scripts/executor/rec_write_guidance.py."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


class TestLoadSourceRegistry:
    """Tests for load_source_registry()."""

    def test_entry_count_matches_independent_raw_text_scan(self) -> None:
        """load_source_registry()'s entry count matches an independent raw-text scan of
        source_registry.yaml (regex, not yaml.safe_load -- catches a loader bug that a
        second yaml.safe_load() cross-check could not), and canonical_ids have no dupes."""
        from scripts.executor.rec_write_guidance import _DEFAULT_REGISTRY, load_source_registry

        entries = load_source_registry()
        raw_text = _DEFAULT_REGISTRY.read_text(encoding="utf-8")
        raw_count = len(re.findall(r"^\s*-\s*canonical_id:\s*\S+", raw_text, re.MULTILINE))
        assert len(entries) == raw_count

        canonical_ids = [e["canonical_id"] for e in entries]
        assert len(canonical_ids) == len(set(canonical_ids))

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
            assert len(entries) == 1  # count-coupling-ok: controlled 1-entry tmp-path fixture, not a growing collection
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

    def test_registered_values_matches_source_registry_canonical_ids(self) -> None:
        """'registered_values' is exactly the canonical_ids from load_source_registry() --
        a wiring-contract cross-check, not a hardcoded count, so it tracks registry growth."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance, load_source_registry

        guidance = get_rec_write_guidance()
        assert guidance["source"]["registered_values"] == [e["canonical_id"] for e in load_source_registry()]

    def test_other_columns_have_description_and_semantics(self) -> None:
        """Non-source columns also carry description and semantics."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        for col_name, col_data in guidance.items():
            if col_name == "source":
                continue
            assert "description" in col_data, f"{col_name} missing description"
            assert "semantics" in col_data, f"{col_name} missing semantics"


class TestCiRcaGuidanceSchemaLockstep:
    """CIRCA-04/08/09: get_rec_write_guidance(source='ci_rca') text stays in lockstep with the
    CiRcaContext schema amendments (version-gated why_chain ceiling, typed terminus override,
    'unknown' actual_gate_that_caught_it)."""

    def test_why_chain_documents_version_gated_ceiling(self) -> None:
        """CIRCA-04 ceiling: guidance states 40-250 at schema_version 1 and 40-400 at version 2."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca")
        why_chain_doc = guidance["context_v2_json"]["schema_fields"]["why_chain"]
        assert "40-250" in why_chain_doc
        assert "40-400" in why_chain_doc
        assert "schema_version 1" in why_chain_doc
        assert "schema_version 2" in why_chain_doc

    def test_terminus_override_documents_required_typed_reason(self) -> None:
        """CIRCA-08: guidance states the reason field is required and bounded 80-400 chars."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca")
        terminus_doc = guidance["context_v2_json"]["schema_fields"]["why_chain_terminus_override"]
        assert "80-400" in terminus_doc
        assert "reason" in terminus_doc

    def test_detection_gap_documents_unknown_and_mirror_null_instruction(self) -> None:
        """CIRCA-09: guidance lists 'unknown' in actual_gate_that_caught_it and instructs the
        agent to mirror a bundle-null value as 'unknown' rather than fabricating a real gate."""
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance(source="ci_rca")
        detection_gap_doc = guidance["context_v2_json"]["schema_fields"]["detection_gap"]
        assert "actual_gate_that_caught_it: pre|presubmit|CI|unknown" in detection_gap_doc
        assert "unknown" in detection_gap_doc
        assert "mirror" in detection_gap_doc.lower()
        assert "null" in detection_gap_doc.lower()
