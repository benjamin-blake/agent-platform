"""Tests for scripts/lambda_manifest.py -- schema + load + staging concern (VERBATIM split from
tests/test_lambda_manifest.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.lambda_manifest import (
    LambdaManifest,
    _copytree_ignore,
    _is_excluded,
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
# excludes[] field (T2.17) -- schema, staging, affected-artifacts, patterns
# ---------------------------------------------------------------------------


class TestExcludesField:
    def test_schema_accepts_excludes(self):
        m = LambdaManifest(artifact="a.zip", includes=["src/"], excludes=["src/common/ducklake_runtime.py"])
        assert m.excludes == ["src/common/ducklake_runtime.py"]

    def test_excludes_defaults_empty(self):
        assert LambdaManifest(artifact="a.zip").excludes == []

    def test_is_excluded_exact_and_nested(self):
        ex = ["src/common/ducklake_runtime.py", "src/lambdas/ducklake_writer"]
        assert _is_excluded("src/common/ducklake_runtime.py", ex) is True
        assert _is_excluded("src/lambdas/ducklake_writer", ex) is True
        assert _is_excluded("src/lambdas/ducklake_writer/handler.py", ex) is True
        assert _is_excluded("src/lambdas/ducklake_writer\\handler.py", ex) is True
        assert _is_excluded("src/common/other.py", ex) is False

    def test_stage_bundle_skips_excluded_file_under_include_dir(self, tmp_path):
        # src/ contains both keep.py and an excluded ducklake_runtime.py
        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        (src / "keep.py").write_text("x=1", encoding="utf-8")
        (src / "ducklake_runtime.py").write_text("x=2", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", includes=["src/"], excludes=["src/common/ducklake_runtime.py"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)
        assert (stage_dir / "src" / "common" / "keep.py").exists()
        assert not (stage_dir / "src" / "common" / "ducklake_runtime.py").exists()

    def test_stage_bundle_skips_excluded_subdir(self, tmp_path):
        writer = tmp_path / "src" / "lambdas" / "ducklake_writer"
        writer.mkdir(parents=True)
        (writer / "handler.py").write_text("x=1", encoding="utf-8")
        keep = tmp_path / "src" / "lambdas" / "other"
        keep.mkdir(parents=True)
        (keep / "h.py").write_text("x=1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(artifact="a.zip", includes=["src/"], excludes=["src/lambdas/ducklake_writer"])
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)
        assert (stage_dir / "src" / "lambdas" / "other" / "h.py").exists()
        assert not (stage_dir / "src" / "lambdas" / "ducklake_writer").exists()

    def test_stage_bundle_skips_directly_excluded_include(self, tmp_path):
        # An include path that is itself excluded is skipped entirely.
        f = tmp_path / "src" / "common" / "ducklake_runtime.py"
        f.parent.mkdir(parents=True)
        f.write_text("x=1", encoding="utf-8")
        stage_dir = tmp_path / "stage"
        stage_dir.mkdir()
        m = LambdaManifest(
            artifact="a.zip",
            includes=["src/common/ducklake_runtime.py"],
            excludes=["src/common/ducklake_runtime.py"],
        )
        with patch("scripts.lambda_manifest.ROOT", tmp_path):
            stage_bundle(m, stage_dir)
        assert not (stage_dir / "src" / "common" / "ducklake_runtime.py").exists()

    def test_copytree_ignore_handles_out_of_root_path(self, tmp_path):
        # A directory outside ROOT yields no ignores (ValueError branch).
        with patch("scripts.lambda_manifest.ROOT", tmp_path / "root"):
            (tmp_path / "root").mkdir()
            ignore = _copytree_ignore(["src/x"])
            result = ignore("/some/other/place", ["a.py", "b.py"])
        assert result == set()

    def test_compute_affected_excludes_filtered(self, tmp_path):
        func_dir = tmp_path / "data-pipeline"
        func_dir.mkdir()
        content = {
            "artifact": "data-pipeline.zip",
            "includes": ["src/"],
            "excludes": ["src/common/ducklake_runtime.py"],
            "status": "active",
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        (tmp_path / "src").mkdir()
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            # Excluded file does NOT mark the artifact affected; a normal src file does.
            assert compute_affected_artifacts(["src/common/ducklake_runtime.py"]) == {}
            assert "data-pipeline" in compute_affected_artifacts(["src/data/handlers/h.py"])

    def test_derive_patterns_skips_excluded(self, tmp_path):
        func_dir = tmp_path / "myfunc"
        func_dir.mkdir()
        (tmp_path / "src").mkdir()
        content = {
            "artifact": "myfunc.zip",
            "includes": ["src/", "src/common/ducklake_runtime.py"],
            "excludes": ["src/common/ducklake_runtime.py"],
            "status": "active",
        }
        (func_dir / "manifest.yaml").write_text(yaml.dump(content), encoding="utf-8")
        with (
            patch("scripts.lambda_manifest._LAMBDAS_DIR", tmp_path),
            patch("scripts.lambda_manifest.ROOT", tmp_path),
        ):
            patterns = derive_lambda_file_patterns()
        assert "src/common/ducklake_runtime.py" not in patterns
