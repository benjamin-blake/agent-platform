"""Tests for check_source_registry()."""

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks.ops_governance.check_source_registry import check_source_registry


class TestCheckSourceRegistry:
    """Tests for check_source_registry()."""

    def test_source_registry_ci_guard_accepts_registered(self, tmp_path: Path) -> None:
        """check_source_registry() passes when all schedule.yaml agent names are registered."""

        (tmp_path / "config" / "agent" / "data_quality").mkdir(parents=True)

        def _mk_entry(cid: str) -> dict:
            return {"canonical_id": cid, "description": "d", "signal_interpretation": "s", "added_date": "2026-01-01"}

        (tmp_path / "config" / "agent" / "data_quality" / "source_registry.yaml").write_text(
            yaml.dump({"entries": [_mk_entry("doc-freshness"), _mk_entry("orphan-code")]}),
            encoding="utf-8",
        )
        (tmp_path / ".github" / "agents").mkdir(parents=True)
        (tmp_path / ".github" / "agents" / "schedule.yaml").write_text(
            yaml.dump({"agents": [{"name": "doc-freshness"}, {"name": "orphan-code"}]}),
            encoding="utf-8",
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "ops_data_portal.py").write_text("", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            check_source_registry(failed)
        assert failed == [], f"Expected no failures but got: {failed}"

    def test_source_registry_ci_guard_rejects_unregistered(self, tmp_path: Path) -> None:
        """check_source_registry() fails when a schedule.yaml agent name is not registered."""

        (tmp_path / "config" / "agent" / "data_quality").mkdir(parents=True)

        def _mk_entry(cid: str) -> dict:
            return {"canonical_id": cid, "description": "d", "signal_interpretation": "s", "added_date": "2026-01-01"}

        (tmp_path / "config" / "agent" / "data_quality" / "source_registry.yaml").write_text(
            yaml.dump({"entries": [_mk_entry("doc-freshness")]}),
            encoding="utf-8",
        )
        (tmp_path / ".github" / "agents").mkdir(parents=True)
        (tmp_path / ".github" / "agents" / "schedule.yaml").write_text(
            yaml.dump({"agents": [{"name": "doc-freshness"}, {"name": "unregistered-agent-xyz"}]}),
            encoding="utf-8",
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "ops_data_portal.py").write_text("", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            check_source_registry(failed)
        assert "Source registry CI guard" in failed
