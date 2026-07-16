"""Tests for scripts/lambda_manifest.py -- bundle-integrity checks + pattern derivation concern
(VERBATIM split from tests/test_lambda_manifest.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.lambda_manifest import (
    LambdaManifest,
    check_assets_present,
    check_handler_imports,
    compute_affected_artifacts,
    derive_lambda_file_patterns,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# check_handler_imports
# ---------------------------------------------------------------------------


class TestCheckHandlerImports:
    def test_missing_handler_file(self, tmp_path):
        m = LambdaManifest(artifact="a.zip", handlers=["src/missing.py"])
        errors = check_handler_imports(m, tmp_path)
        assert any("not found" in e for e in errors)

    def test_successful_import(self, tmp_path):
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        handler.write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        m = LambdaManifest(artifact="a.zip", handlers=["src/h.py"])
        errors = check_handler_imports(m, tmp_path)
        assert errors == []

    def test_missing_module_reported(self, tmp_path):
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        handler.write_text("import nonexistent_module_xyz\n", encoding="utf-8")
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        m = LambdaManifest(artifact="a.zip", handlers=["src/h.py"])
        errors = check_handler_imports(m, tmp_path)
        assert len(errors) == 1
        assert "nonexistent_module_xyz" in errors[0]

    def test_import_failure_non_module_error(self, tmp_path):
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        handler.write_text("raise RuntimeError('bad import')\n", encoding="utf-8")
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        m = LambdaManifest(artifact="a.zip", handlers=["src/h.py"])
        errors = check_handler_imports(m, tmp_path)
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# check_assets_present
# ---------------------------------------------------------------------------


class TestCheckAssetsPresent:
    def test_passes_when_all_present(self, tmp_path):
        asset = tmp_path / "data" / "file.yaml"
        asset.parent.mkdir()
        asset.write_text("x: 1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        (stage_dir / "data").mkdir()
        (stage_dir / "data" / "file.yaml").write_text("x: 1", encoding="utf-8")
        m = LambdaManifest(artifact="a.zip", assets=["data/file.yaml"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            errors = check_assets_present(m, stage_dir)
        assert errors == []

    def test_fails_when_staged_missing(self, tmp_path):
        asset = tmp_path / "data" / "file.yaml"
        asset.parent.mkdir()
        asset.write_text("x: 1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", assets=["data/file.yaml"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            errors = check_assets_present(m, stage_dir)
        assert len(errors) == 1
        assert "data/file.yaml" in errors[0]

    def test_skips_optional_files(self, tmp_path):
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", assets=["config/config.yaml"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            errors = check_assets_present(m, stage_dir)
        assert errors == []  # file doesn't exist in repo root -> skip

    def test_checks_config_paths(self, tmp_path):
        config_dir = tmp_path / "config" / "lambda" / "app"
        config_dir.mkdir(parents=True)
        (config_dir / "env.yaml").write_text("", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", config=["config/lambda/app/"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            errors = check_assets_present(m, stage_dir)
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# LAMBDA_FILE_PATTERNS derivation
# ---------------------------------------------------------------------------


class TestLambdaFilePatterns:
    def test_derives_patterns_from_active_manifest(self, tmp_path):
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text(
            "artifact: myfunc.zip\nhandlers: [src/data/handlers/h.py]\n"
            "includes: [src/]\nassets: [.github/agents/schedule.yaml]\n"
            "config: [config/lambda/myfunc/]\n",
            encoding="utf-8",
        )
        (tmp_path / "src").mkdir()
        (tmp_path / ".github" / "agents").mkdir(parents=True)
        (tmp_path / ".github" / "agents" / "schedule.yaml").write_text("", encoding="utf-8")
        (tmp_path / "config" / "lambda" / "myfunc").mkdir(parents=True)
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            with patch("scripts.lambda_manifest.ROOT", tmp_path):
                patterns = derive_lambda_file_patterns()
        assert any("src/" in p for p in patterns)
        assert any("schedule.yaml" in p for p in patterns)

    def test_stub_manifests_excluded(self, tmp_path):
        func_dir = tmp_path / "stubfunc"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text(
            "artifact: stubfunc.zip\nstatus: stub\nhandlers: [src/h.py]\n",
            encoding="utf-8",
        )
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            with patch("scripts.lambda_manifest.ROOT", tmp_path):
                patterns = derive_lambda_file_patterns()
        assert patterns == []

    def test_returns_empty_on_load_failure(self, tmp_path):
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path / "nonexistent"):
            patterns = derive_lambda_file_patterns()
        assert patterns == []


# ---------------------------------------------------------------------------
# compute_affected_artifacts (deploy gating)
# ---------------------------------------------------------------------------


class TestComputeAffectedArtifacts:
    def _make_manifest(self, tmp_path: Path, slug: str, handlers: list[str]) -> None:
        func_dir = tmp_path / slug
        func_dir.mkdir(exist_ok=True)
        content = {
            "artifact": f"{slug}.zip",
            "handlers": handlers,
            "includes": ["src/"],
            "status": "active",
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        (tmp_path / "src").mkdir(exist_ok=True)

    def test_returns_matching_artifact(self, tmp_path):
        self._make_manifest(tmp_path, "myfunc", ["src/data/handlers/h.py"])
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            result = compute_affected_artifacts(["src/data/handlers/h.py"])
        assert "myfunc" in result
        assert "src/data/handlers/h.py" in result["myfunc"]

    def test_returns_empty_for_unrelated_changes(self, tmp_path):
        self._make_manifest(tmp_path, "myfunc", ["src/data/handlers/h.py"])
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            result = compute_affected_artifacts(["docs/README.md"])
        assert result == {}

    def test_stub_manifest_excluded(self, tmp_path):
        func_dir = tmp_path / "stubfunc"
        func_dir.mkdir()
        content = {"artifact": "stubfunc.zip", "handlers": ["src/h.py"], "status": "stub"}
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            result = compute_affected_artifacts(["src/h.py"])
        assert result == {}

    def test_manifest_yaml_change_matches(self, tmp_path):
        self._make_manifest(tmp_path, "myfunc", [])
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            result = compute_affected_artifacts(["src/lambdas/myfunc/manifest.yaml"])
        assert "myfunc" in result

    def test_returns_empty_on_load_failure(self, tmp_path):
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path / "nonexistent"):
            result = compute_affected_artifacts(["any/file.py"])
        assert result == {}
