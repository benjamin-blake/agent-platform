"""Tests for validate_intent_doc_freeze() -- Decision 86 enforcement."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks.contracts.validate_intent_doc_freeze import validate_intent_doc_freeze


class TestIntentDocFreeze:
    """Tests for validate_intent_doc_freeze() -- Decision 86 enforcement."""

    _MANIFEST_PENDING = {
        "documents": [
            {"id": "bazel-feasibility", "disposition_state": "pending"},
            {"id": "ducklake-consolidation", "disposition_state": "pending"},
        ]
    }

    def _write_manifest(self, docs_dir: Path, data: dict) -> None:

        migration_dir = docs_dir / "intent-migration"
        migration_dir.mkdir(parents=True, exist_ok=True)
        (migration_dir / "MANIFEST.yaml").write_text(yaml.dump(data), encoding="utf-8")

    def test_grandfathered_intent_doc_passes(self, tmp_path: Path) -> None:
        """A docs/INTENT-*.md with a non-done manifest entry is allowed."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "INTENT-bazel-feasibility.md").write_text("# content\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert failed == []

    def test_new_intent_doc_not_in_manifest_is_rejected(self, tmp_path: Path) -> None:
        """A docs/INTENT-*.md with no manifest entry is rejected."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "INTENT-zzz-new.md").write_text("# rogue\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert any("INTENT-zzz-new.md" in f for f in failed)

    def test_done_manifest_entry_is_rejected(self, tmp_path: Path) -> None:
        """A doc whose manifest entry has disposition_state: done is rejected (it should have been deleted)."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        manifest = {
            "documents": [
                {"id": "bazel-feasibility", "disposition_state": "done"},
            ]
        }
        self._write_manifest(docs_dir, manifest)
        (docs_dir / "INTENT-bazel-feasibility.md").write_text("# content\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert any("bazel-feasibility" in f for f in failed)

    def test_contracts_dir_excluded(self, tmp_path: Path) -> None:
        """A docs/contracts/INTENT-*.md is NOT flagged (contracts dir is excluded)."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        contracts_dir = docs_dir / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "INTENT-zzz.md").write_text("# contract\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert not any("zzz" in f for f in failed)

    def test_intent_migration_dir_excluded(self, tmp_path: Path) -> None:
        """Files under docs/intent-migration/ are NOT flagged."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "intent-migration" / "INTENT-internal.md").write_text("# internal\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert not any("INTENT-internal" in f for f in failed)

    def test_manifest_absent_fails_open(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When the manifest is absent the check emits a warning and does NOT append to failed."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "INTENT-zzz.md").write_text("# rogue\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert failed == []
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "WARNING" in captured.err
