"""Tests for scripts/lambda_manifest.py -- CLI command-entrypoint concern (VERBATIM split from
tests/test_lambda_manifest.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Coverage check
# ---------------------------------------------------------------------------


class TestCoverageCheck:
    def test_dir_without_manifest_fails(self, tmp_path):
        (tmp_path / "myfunc").mkdir()
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            from scripts.lambda_manifest import cmd_check_coverage

            rc = cmd_check_coverage(None)
        assert rc == 1

    def test_all_covered_passes(self, tmp_path):
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text("artifact: myfunc.zip\n", encoding="utf-8")
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            from scripts.lambda_manifest import cmd_check_coverage

            rc = cmd_check_coverage(None)
        assert rc == 0

    def test_missing_lambdas_dir_fails(self, tmp_path):
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path / "nonexistent"):
            from scripts.lambda_manifest import cmd_check_coverage

            rc = cmd_check_coverage(None)
        assert rc == 1


# ---------------------------------------------------------------------------
# CLI validation command
# ---------------------------------------------------------------------------


class TestCmdValidate:
    def test_validates_all_manifests(self, tmp_path):
        func_dir = tmp_path / "f1"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text("artifact: f1.zip\n", encoding="utf-8")
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            from scripts.lambda_manifest import cmd_validate

            rc = cmd_validate(None)
        assert rc == 0

    def test_fails_on_invalid_manifest(self, tmp_path):
        func_dir = tmp_path / "bad"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text("artifact: no-zip\n", encoding="utf-8")
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            from scripts.lambda_manifest import cmd_validate

            rc = cmd_validate(None)
        assert rc == 1

    def test_missing_dir_fails(self, tmp_path):
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path / "nonexistent"):
            from scripts.lambda_manifest import cmd_validate

            rc = cmd_validate(None)
        assert rc == 1

    def test_skips_dirs_without_manifest(self, tmp_path, capsys):
        no_manifest_dir = tmp_path / "no_manifest"
        no_manifest_dir.mkdir()
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            from scripts.lambda_manifest import cmd_validate

            rc = cmd_validate(None)
        assert rc == 0
        captured = capsys.readouterr()
        assert "SKIP" in captured.out


# ---------------------------------------------------------------------------
# CLI check-bundles command
# ---------------------------------------------------------------------------


class TestCmdCheckBundles:
    def test_passes_for_valid_bundle(self, tmp_path):
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        handler.write_text("x = 1\n", encoding="utf-8")
        asset = tmp_path / "data" / "f.yaml"
        asset.parent.mkdir()
        asset.write_text("", encoding="utf-8")
        content = {
            "artifact": "myfunc.zip",
            "handlers": ["src/h.py"],
            "includes": ["src/"],
            "assets": ["data/f.yaml"],
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            from scripts.lambda_manifest import cmd_check_bundles

            rc = cmd_check_bundles(None)
        assert rc == 0

    def test_fails_on_missing_import(self, tmp_path):
        """cmd_check_bundles fails when a handler module has a missing import."""
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        handler.write_text("import nonexistent_module_xyz_abc\n", encoding="utf-8")
        content = {
            "artifact": "myfunc.zip",
            "handlers": ["src/h.py"],
            "includes": ["src/"],
            "assets": [],
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            from scripts.lambda_manifest import cmd_check_bundles

            rc = cmd_check_bundles(None)
        assert rc == 1

    def test_skips_stubs(self, tmp_path):
        func_dir = tmp_path / "stub_fn"
        func_dir.mkdir()
        (func_dir / "manifest.yaml").write_text("artifact: stub.zip\nstatus: stub\n", encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            from scripts.lambda_manifest import cmd_check_bundles

            rc = cmd_check_bundles(None)
        assert rc == 0

    def test_fails_on_missing_declared_asset(self, tmp_path, capsys):
        """cmd_check_bundles fails when a declared asset exists in the repo but is not staged.

        Plan acceptance criterion (line 91): 'removing a declared asset from the stage fails the
        check'. stage_bundle normally always stages declared assets, so we patch it with a fake
        that stages handlers/includes (so the import check passes) but deliberately drops assets[].
        check_assets_present then sees the repo-present asset missing from the staged tree and
        cmd_check_bundles returns 1 -- and we assert the failure is the ASSET, not the handler.
        """
        import shutil as _sh

        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        handler = tmp_path / "src" / "h.py"
        handler.parent.mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        handler.write_text("x = 1\n", encoding="utf-8")
        # Asset exists in the repo root (so check_assets_present does NOT skip it as optional)
        asset = tmp_path / "data" / "runtime.yaml"
        asset.parent.mkdir()
        asset.write_text("k: v", encoding="utf-8")
        content = {
            "artifact": "myfunc.zip",
            "handlers": ["src/h.py"],
            "includes": ["src/"],
            "assets": ["data/runtime.yaml"],
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")

        def _stage_without_assets(manifest, stage_dir, *, skip_pip=True):
            # Stage handlers + includes so the import check resolves; drop assets[] on purpose.
            for rel in manifest.handlers + manifest.includes:
                src = tmp_path / rel.rstrip("/")
                dst = stage_dir / rel.rstrip("/")
                if src.is_dir():
                    _sh.copytree(src, dst, dirs_exist_ok=True)
                elif src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    _sh.copy2(src, dst)

        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
            patch("scripts.lambda_manifest.stage_bundle", side_effect=_stage_without_assets),
        ):
            from scripts.lambda_manifest import cmd_check_bundles

            rc = cmd_check_bundles(None)
        out = capsys.readouterr().out
        assert rc == 1
        assert "data/runtime.yaml" in out  # failure is the dropped asset
        assert "FAIL (asset)" in out


# ---------------------------------------------------------------------------
# CLI list-patterns command
# ---------------------------------------------------------------------------


class TestCmdListPatterns:
    def test_emits_patterns(self, tmp_path, capsys):
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        (tmp_path / "src").mkdir()
        content = {"artifact": "myfunc.zip", "handlers": ["src/h.py"], "includes": ["src/"]}
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            from scripts.lambda_manifest import cmd_list_patterns

            rc = cmd_list_patterns(None)
        assert rc == 0
        out = capsys.readouterr().out
        assert "src/" in out


# ---------------------------------------------------------------------------
# _minimal_env helper
# ---------------------------------------------------------------------------


class TestMinimalEnv:
    def test_keeps_path(self):
        from scripts.lambda_manifest import _minimal_env

        env = _minimal_env()
        assert "PATH" in env

    def test_strips_aws_creds(self):
        import os

        from scripts.lambda_manifest import _minimal_env

        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "secret", "AWS_SECRET_ACCESS_KEY": "secret"}):
            env = _minimal_env()
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
