"""Tests for scripts/lambda_manifest.py (100% coverage, CD.24)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.lambda_manifest import (
    LambdaManifest,
    check_assets_present,
    check_handler_imports,
    compute_affected_artifacts,
    derive_lambda_file_patterns,
    load,
    load_all,
    stage_bundle,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestLambdaManifestSchema:
    def test_valid_minimal(self):
        m = LambdaManifest(artifact="foo.zip")
        assert m.artifact == "foo.zip"
        assert m.status == "active"
        assert m.handlers == []

    def test_valid_full(self):
        m = LambdaManifest(
            artifact="a.zip",
            functions=["fn1"],
            handlers=["src/h.py"],
            includes=["src/"],
            assets=[".github/agents/schedule.yaml"],
            config=["config/lambda/a/"],
            pip_packages=["pkg==1.0"],
            runtime_config=["ssm/path"],
            status="stub",
            notes="n",
        )
        assert m.status == "stub"
        assert m.pip_packages == ["pkg==1.0"]

    def test_artifact_must_end_with_zip(self):
        with pytest.raises(Exception):
            LambdaManifest(artifact="foo")

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            LambdaManifest(artifact="a.zip", unknown_field="x")

    def test_status_literal(self):
        with pytest.raises(Exception):
            LambdaManifest(artifact="a.zip", status="retired")


class TestLoadManifest:
    def test_load_valid(self, tmp_path):
        mp = tmp_path / "manifest.yaml"
        mp.write_text("artifact: test.zip\n", encoding="utf-8")
        m = load(mp)
        assert m.artifact == "test.zip"

    def test_load_non_dict_raises(self, tmp_path):
        mp = tmp_path / "manifest.yaml"
        mp.write_text("- item\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected a YAML mapping"):
            load(mp)

    def test_load_invalid_schema_raises(self, tmp_path):
        mp = tmp_path / "manifest.yaml"
        mp.write_text("artifact: no-zip-extension\n", encoding="utf-8")
        with pytest.raises(Exception):
            load(mp)

    def test_load_all_skips_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "myfunc").mkdir()
        (tmp_path / "myfunc" / "manifest.yaml").write_text("artifact: m.zip\n", encoding="utf-8")
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            result = load_all()
        assert "myfunc" in result
        assert "__pycache__" not in result

    def test_load_all_skips_no_manifest(self, tmp_path):
        (tmp_path / "nofile").mkdir()
        with patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path):
            result = load_all()
        assert "nofile" not in result


# ---------------------------------------------------------------------------
# Stage bundle
# ---------------------------------------------------------------------------


class TestStageBundle:
    def test_stages_file_include(self, tmp_path):
        src_file = tmp_path / "scripts" / "foo.py"
        src_file.parent.mkdir()
        src_file.write_text("x=1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()

        m = LambdaManifest(artifact="a.zip", includes=["scripts/foo.py"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)

        assert (stage_dir / "scripts" / "foo.py").exists()

    def test_stages_directory_include(self, tmp_path):
        src_dir = tmp_path / "src" / "common"
        src_dir.mkdir(parents=True)
        (src_dir / "mod.py").write_text("x=1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()

        m = LambdaManifest(artifact="a.zip", includes=["src/"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)

        assert (stage_dir / "src" / "common" / "mod.py").exists()

    def test_stages_assets(self, tmp_path):
        asset = tmp_path / ".github" / "agents" / "schedule.yaml"
        asset.parent.mkdir(parents=True)
        asset.write_text("agents: []", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()

        m = LambdaManifest(artifact="a.zip", assets=[".github/agents/schedule.yaml"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)

        assert (stage_dir / ".github" / "agents" / "schedule.yaml").exists()

    def test_stages_config(self, tmp_path):
        config_dir = tmp_path / "config" / "lambda" / "myapp"
        config_dir.mkdir(parents=True)
        (config_dir / "env.yaml").write_text("key: val", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()

        m = LambdaManifest(artifact="a.zip", config=["config/lambda/myapp/"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)

        assert (stage_dir / "config" / "lambda" / "myapp" / "env.yaml").exists()

    def test_skip_missing_src(self, tmp_path):
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", includes=["nonexistent/path.py"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)  # should not raise
        assert list(stage_dir.iterdir()) == []

    def test_skip_pip_false_runs_subprocess(self, tmp_path):
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", pip_packages=["mypkg==1.0"])
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            with patch("scripts.lambda_manifest.subprocess.run", return_value=mock_result) as mock_run:
                stage_bundle(m, stage_dir, skip_pip=False)
        calls = [c for c in mock_run.call_args_list if "mypkg" in str(c)]
        assert len(calls) == 1

    def test_skip_pip_true_no_subprocess(self, tmp_path):
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", pip_packages=["mypkg==1.0"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            with patch("scripts.lambda_manifest.subprocess.run") as mock_run:
                stage_bundle(m, stage_dir, skip_pip=True)
        assert mock_run.call_count == 0

    def test_pip_failure_exits(self, tmp_path):
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", pip_packages=["badpkg==0.0.0"])
        fail_mock = MagicMock()
        fail_mock.returncode = 1
        fail_mock.stderr = "not found"
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            with patch("scripts.lambda_manifest.subprocess.run", return_value=fail_mock):
                with pytest.raises(SystemExit):
                    stage_bundle(m, stage_dir, skip_pip=False)

    def test_handler_staged_from_includes(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        h = src_dir / "handler.py"
        h.write_text("def handler(event, context): pass", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", handlers=["src/handler.py"], includes=["src/"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)
        assert (stage_dir / "src" / "handler.py").exists()


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
