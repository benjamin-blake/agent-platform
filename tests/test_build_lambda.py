"""Tests for build_lambda module."""

import gzip
import types
from unittest.mock import MagicMock, patch

import pytest

import scripts.build_lambda as bl
from scripts.build_lambda import (
    _DUCKLAKE_CATALOG_DR_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_WRITER_FUNCTION,
    _LAMBDA_FUNCTION_NAMES,
    _LAMBDA_SCRIPTS,
    _OPS_COMPACTION_FUNCTION_NAME,
    _OPS_COMPACTION_ZIP_KEY,
    PINNED_DUCKDB_VERSION,
    assert_within_size_limit,
    update_lambda_functions,
    validate_bucket_exists,
)
from src.common.ducklake_version import pinned_duckdb_version


class _FakePath:
    """Minimal Path double exposing .name + .stat().st_size for size-assert tests."""

    def __init__(self, size=100, name="x.zip"):
        self._size = size
        self.name = name

    def stat(self):
        return types.SimpleNamespace(st_size=self._size)


def _args(**kw):
    import argparse

    ns = argparse.Namespace(
        skip_upload=True,
        bucket="",
        profile="agent_platform",
        region="eu-west-2",
        deploy=False,
        ducklake_only=False,
        list_bundle=None,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


pytestmark = pytest.mark.unit


def test_validate_bucket_exists_success():
    """Test that validate_bucket_exists returns True when bucket exists."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        result = validate_bucket_exists("test-bucket", "company-aws-profile", "eu-west-2")

        assert result is True
        mock_run.assert_called_once()


def test_validate_bucket_exists_failure():
    """Test that validate_bucket_exists returns False when bucket doesn't exist."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 254

        result = validate_bucket_exists("nonexistent-bucket", "company-aws-profile", "eu-west-2")

        assert result is False
        mock_run.assert_called_once()


def test_validate_bucket_exists_call_args():
    """Test that validate_bucket_exists calls aws s3api head-bucket with correct arguments."""
    with patch("scripts.build_lambda.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        validate_bucket_exists("my-bucket", "my-profile", "us-west-2")

        call_args = mock_run.call_args[0][0]
        assert "aws" in call_args
        assert "s3api" in call_args
        assert "head-bucket" in call_args
        assert "--bucket" in call_args
        assert "my-bucket" in call_args
        assert "--profile" in call_args
        assert "my-profile" in call_args
        assert "--region" in call_args
        assert "us-west-2" in call_args


class TestUpdateLambdaFunctions:
    """Tests for the update_lambda_functions deploy path."""

    # depth-first subprocess call tree for update_lambda_functions():
    #   1. aws lambda update-function-code (dispatcher)      (subprocess.run)
    #   2. aws lambda update-function-code (findings)        (subprocess.run)
    #   3. aws lambda update-function-code (ops_compaction)  (subprocess.run)
    # Total subprocess.run count: 3 -- side_effect list must have 3 entries

    def _make_success(self) -> MagicMock:
        mock = MagicMock()
        mock.returncode = 0
        return mock

    def test_update_calls_all_functions(self):
        """All three Lambda functions receive an update-function-code call."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

            assert mock_run.call_count == 3

    def test_update_function_names(self):
        """Each call targets the correct Lambda function name."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("my-bucket", "my-profile", "eu-west-2")

            all_functions = list(_LAMBDA_FUNCTION_NAMES) + [_OPS_COMPACTION_FUNCTION_NAME]
            for idx, fn_name in enumerate(all_functions):
                cmd = mock_run.call_args_list[idx][0][0]
                fn_idx = cmd.index("--function-name")
                assert cmd[fn_idx + 1] == fn_name

    def test_update_pipeline_functions_use_pipeline_zip(self):
        """Dispatcher and findings-processor use data-pipeline.zip."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

            for idx in range(len(_LAMBDA_FUNCTION_NAMES)):
                cmd = mock_run.call_args_list[idx][0][0]
                bucket_idx = cmd.index("--s3-bucket")
                assert cmd[bucket_idx + 1] == "deploy-bucket"
                key_idx = cmd.index("--s3-key")
                assert cmd[key_idx + 1] == "lambda-packages/data-pipeline.zip"

    def test_update_ops_compaction_uses_minimal_zip(self):
        """ops_compaction Lambda uses the minimal ops-compaction.zip."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("deploy-bucket", "prof", "eu-west-2")

            # ops_compaction is the last call (index = len(_LAMBDA_FUNCTION_NAMES))
            ops_idx = len(_LAMBDA_FUNCTION_NAMES)
            cmd = mock_run.call_args_list[ops_idx][0][0]
            fn_idx = cmd.index("--function-name")
            assert cmd[fn_idx + 1] == _OPS_COMPACTION_FUNCTION_NAME
            key_idx = cmd.index("--s3-key")
            assert cmd[key_idx + 1] == _OPS_COMPACTION_ZIP_KEY

    def test_update_region_and_profile(self):
        """Region and profile are forwarded to the AWS CLI."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("b", "company-aws-profile", "eu-west-2")

            for c in mock_run.call_args_list:
                cmd = c[0][0]
                region_idx = cmd.index("--region")
                assert cmd[region_idx + 1] == "eu-west-2"
                profile_idx = cmd.index("--profile")
                assert cmd[profile_idx + 1] == "company-aws-profile"

    def test_update_subprocess_kwargs(self):
        """Windows-safe subprocess kwargs are set."""
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                self._make_success(),
                self._make_success(),
                self._make_success(),
            ]

            update_lambda_functions("b", "p", "eu-west-2")

            for c in mock_run.call_args_list:
                kwargs = c[1]
                assert kwargs["text"] is True
                assert kwargs["encoding"] == "utf-8"
                assert kwargs["errors"] == "replace"
                assert kwargs["capture_output"] is True

    def test_update_exits_on_failure(self):
        """sys.exit is called when a Lambda update fails."""
        fail_mock = MagicMock()
        fail_mock.returncode = 1
        fail_mock.stderr = "AccessDenied"

        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [fail_mock]

            with pytest.raises(SystemExit) as exc_info:
                update_lambda_functions("b", "p", "eu-west-2")

            assert exc_info.value.code == 1

    def test_lambda_function_names_constant(self):
        """All expected Lambda function names are present."""
        assert "agent-platform-scheduled-agent-dispatcher" in _LAMBDA_FUNCTION_NAMES
        assert "agent-platform-findings-processor" in _LAMBDA_FUNCTION_NAMES
        assert _OPS_COMPACTION_FUNCTION_NAME == "agent-platform-ops-compaction"
        assert _OPS_COMPACTION_ZIP_KEY == "lambda-packages/ops-compaction.zip"


class TestLambdaScriptsAndSdkConfig:
    """Tests for _LAMBDA_SCRIPTS constants."""

    def test_llm_client_in_lambda_scripts(self):
        """llm_client.py is listed in _LAMBDA_SCRIPTS."""
        assert "llm_client.py" in _LAMBDA_SCRIPTS

    def test_llm_utils_in_lambda_scripts(self):
        """llm_utils.py is listed in _LAMBDA_SCRIPTS."""
        assert "llm_utils.py" in _LAMBDA_SCRIPTS

    def test_tool_runtime_in_lambda_scripts(self):
        """tool_runtime.py is listed in _LAMBDA_SCRIPTS."""
        assert "tool_runtime.py" in _LAMBDA_SCRIPTS

    def test_bedrock_client_absent_from_lambda_scripts(self):
        """bedrock_client.py left the bundle with the CD.28 retirement."""
        assert "bedrock_client.py" not in _LAMBDA_SCRIPTS


class TestBuildAppPackageSdkInstall:
    """Verify Copilot SDK install step is present."""

    def test_build_app_package_installs_copilot_sdk(self, tmp_path):
        """build_app_package calls pip to install github-copilot-sdk."""

        from scripts.build_lambda import build_app_package

        (tmp_path / "app").mkdir()

        sdk_calls: list[list] = []

        def mock_run(cmd, *args, **kwargs):
            sdk_calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch("shutil.copytree"),
            patch("shutil.copy2"),
            patch("scripts.build_lambda.subprocess.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("scripts.build_lambda.OUTPUT_DIR", tmp_path),
            patch(
                "zipfile.ZipFile.__enter__",
                return_value=MagicMock(writestr=MagicMock()),
            ),
            patch("zipfile.ZipFile.__exit__", return_value=False),
            patch("pathlib.Path.rglob", return_value=[]),
            patch("pathlib.Path.mkdir"),
        ):
            with patch("scripts.build_lambda.OUTPUT_DIR", tmp_path):
                build_app_package(tmp_path)

        sdk_install_calls = [c for c in sdk_calls if any("github-copilot-sdk" in str(a) for a in c)]
        assert sdk_install_calls, "Copilot SDK install should be present (reverted from Bedrock migration)"


class TestBuildLambdaConfigScope:
    """Verify Lambda zips contain only config.yaml + lambda/<name>/ (T-1.7)."""

    def _run_build(self, builder_fn_name: str, tmp_path):
        """Run a build function with all IO patched, capturing copy2 and copytree calls."""
        import scripts.build_lambda as bm

        builder = getattr(bm, builder_fn_name)
        copy2_calls: list[tuple] = []
        copytree_calls: list[tuple] = []

        def fake_copy2(src, dst):
            copy2_calls.append((str(src), str(dst)))

        def fake_copytree(src, dst, **kw):
            copytree_calls.append((str(src), str(dst)))

        sdk_mock = MagicMock()
        sdk_mock.returncode = 0

        with (
            patch("shutil.copy2", side_effect=fake_copy2),
            patch("shutil.copytree", side_effect=fake_copytree),
            patch("scripts.build_lambda.subprocess.run", return_value=sdk_mock),
            patch("pathlib.Path.exists", return_value=True),
            patch("scripts.build_lambda.OUTPUT_DIR", tmp_path),
            patch("zipfile.ZipFile.__enter__", return_value=MagicMock(writestr=MagicMock())),
            patch("zipfile.ZipFile.__exit__", return_value=False),
            patch("pathlib.Path.rglob", return_value=[]),
            patch("pathlib.Path.mkdir"),
        ):
            builder(tmp_path)

        return copy2_calls, copytree_calls

    def test_data_pipeline_copies_config_yaml(self, tmp_path):
        """build_app_package copies config.yaml (not blanket config/ tree)."""
        copy2_calls, _ = self._run_build("build_app_package", tmp_path)
        copied_sources = [src for src, _ in copy2_calls]
        assert any("config.yaml" in s and "config.yaml.example" not in s for s in copied_sources)

    def test_data_pipeline_no_blanket_config_copytree(self, tmp_path):
        """build_app_package does NOT call shutil.copytree(ROOT/"config", ...) (T-1.7)."""
        _, copytree_calls = self._run_build("build_app_package", tmp_path)
        for src, _ in copytree_calls:
            assert not src.endswith("/config"), f"Blanket config copytree detected: {src}"
            assert "config/agent" not in src, f"Agent config must not be in Lambda zip: {src}"
            assert "config/data_quality" not in src, f"DQ config must not be in Lambda zip: {src}"

    def test_ops_compaction_copies_config_yaml(self, tmp_path):
        """build_ops_compaction_package copies config.yaml (not blanket config/ tree)."""
        copy2_calls, _ = self._run_build("build_ops_compaction_package", tmp_path)
        copied_sources = [src for src, _ in copy2_calls]
        assert any("config.yaml" in s and "config.yaml.example" not in s for s in copied_sources)

    def test_ops_compaction_no_blanket_config_copytree(self, tmp_path):
        """build_ops_compaction_package does NOT call shutil.copytree(ROOT/"config", ...)."""
        _, copytree_calls = self._run_build("build_ops_compaction_package", tmp_path)
        for src, _ in copytree_calls:
            assert not src.endswith("/config"), f"Blanket config copytree detected: {src}"
            assert "config/agent" not in src, f"Agent config must not be in Lambda zip: {src}"

    def test_build_lambda_source_has_no_hardcoded_src_or_config_copytree(self):
        """build_lambda.py source must not hardcode shutil.copytree(ROOT/"src") or ROOT/"config".

        CD.24 retired the blanket whole-src and whole-config copytrees from build_lambda.py.
        The src/ tree is still bundled, but ONLY because the data-pipeline manifest declares
        includes: [src/] and stage_bundle (in lambda_manifest.py) walks it -- the copytree must
        be manifest-driven, never hardcoded here. This source-level guard mirrors VP Step 4 and
        prevents a regression that re-adds the hardcoded blanket copytree. (Asserting absence of
        a runtime /src copytree would be wrong: stage_bundle legitimately copytrees src/ per the
        manifest, as the binding file-list-equivalence check confirms.)
        """
        import re
        from pathlib import Path

        from scripts.build_lambda import __file__ as build_lambda_path

        source = Path(build_lambda_path).read_text(encoding="utf-8")
        # Strip comments and docstrings is overkill; match only actual copytree CALLS on ROOT/src|config.
        src_copytree = re.compile(r"copytree\(\s*ROOT\s*/\s*[\"']src[\"']")
        config_copytree = re.compile(r"copytree\(\s*ROOT\s*/\s*[\"']config[\"']")
        assert not src_copytree.search(source), "Hardcoded shutil.copytree(ROOT/'src') must be retired (CD.24)"
        assert not config_copytree.search(source), "Hardcoded shutil.copytree(ROOT/'config') must be retired (CD.24)"


# ---------------------------------------------------------------------------
# T2.17 DuckLake build additions: size assert, layer builders, ducklake deploy
# ---------------------------------------------------------------------------


class TestSizeAssert:
    def test_under_limit_ok(self):
        assert_within_size_limit(_FakePath(size=100))  # no raise

    def test_at_limit_ok(self):
        assert_within_size_limit(_FakePath(size=bl.LAMBDA_SIZE_LIMIT_BYTES))

    def test_over_limit_exits(self):
        with pytest.raises(SystemExit) as exc:
            assert_within_size_limit(_FakePath(size=bl.LAMBDA_SIZE_LIMIT_BYTES + 1, name="big.zip"))
        assert exc.value.code == 1


class TestPinnedConstants:
    def test_pinned_duckdb_version(self):
        assert PINNED_DUCKDB_VERSION == pinned_duckdb_version()

    def test_ducklake_deps_pin_exact(self):
        assert f"duckdb=={PINNED_DUCKDB_VERSION}" in bl.DUCKLAKE_DEPS

    def test_postgres_published_as_scanner(self):
        stems = dict(bl.DUCKLAKE_EXTENSIONS)
        assert stems["postgres"] == "postgres_scanner"

    def test_ducklake_function_zip_keys(self):
        assert bl._DUCKLAKE_FUNCTION_ZIP_KEYS[_DUCKLAKE_WRITER_FUNCTION] == "lambda-packages/ducklake-writer.zip"
        assert bl._DUCKLAKE_FUNCTION_ZIP_KEYS[_DUCKLAKE_READER_FUNCTION] == "lambda-packages/ducklake-reader.zip"
        assert bl._DUCKLAKE_FUNCTION_ZIP_KEYS[_DUCKLAKE_MAINTENANCE_FUNCTION] == "lambda-packages/ducklake-maintenance.zip"
        assert bl._DUCKLAKE_FUNCTION_ZIP_KEYS[_DUCKLAKE_CATALOG_DR_FUNCTION] == "lambda-packages/ducklake-catalog-dr.zip"


class TestBuildDucklakeFunctionPackage:
    def test_builds_from_manifest(self, tmp_path):
        with (
            patch("scripts.lambda_manifest.load", return_value=MagicMock()) as mock_load,
            patch("scripts.lambda_manifest.stage_bundle") as mock_stage,
            patch("scripts.build_lambda._zip_staged_dir", return_value=tmp_path / "ducklake-writer.zip") as mock_zip,
        ):
            out = bl.build_ducklake_function_package(tmp_path, "ducklake_writer", "ducklake-writer.zip")
        assert out == tmp_path / "ducklake-writer.zip"
        mock_load.assert_called_once()
        mock_stage.assert_called_once()
        mock_zip.assert_called_once()


class TestBuildDucklakeDepsLayer:
    def test_pip_args_pin_duckdb_and_stages(self, tmp_path):
        from pathlib import Path

        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            # Emulate pip --target: stage a package file + a dist-info dir to exercise cleanup + zip.
            target = Path(cmd[cmd.index("--target") + 1])
            (target / "foo.py").write_text("x=1", encoding="utf-8")
            (target / "foo.dist-info").mkdir()
            (target / "foo.dist-info" / "METADATA").write_text("m", encoding="utf-8")
            return types.SimpleNamespace(returncode=0)

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            with patch("scripts.build_lambda.OUTPUT_DIR", tmp_path):
                out = bl.build_ducklake_deps_layer(tmp_path)
        assert out == tmp_path / "ducklake-deps-layer.zip"
        cmd = captured["cmd"]
        reqs = (tmp_path / "requirements-ducklake.txt").read_text()
        assert f"duckdb=={PINNED_DUCKDB_VERSION}" in reqs
        # Transitive deps that duckdb/python-ulid import but do not auto-install for py3.12 must be
        # pinned explicitly, or the write/read paths ModuleNotFoundError at runtime.
        assert "typing_extensions" in reqs  # python-ulid imports `from typing_extensions import Self`
        assert "pytz" in reqs  # duckdb lazily imports pytz for tz-aware TIMESTAMP conversion
        assert "manylinux_2_28_x86_64" in cmd
        # dist-info is PRESERVED (not stripped): duckdb>=1.3 reads its version via importlib.metadata.
        import zipfile

        names = zipfile.ZipFile(out).namelist()
        assert any(n.endswith("foo.py") for n in names)
        assert any("dist-info" in n for n in names)

    def test_pip_failure_exits(self, tmp_path):
        with patch("scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=1)):
            with patch("scripts.build_lambda.OUTPUT_DIR", tmp_path):
                with pytest.raises(SystemExit):
                    bl.build_ducklake_deps_layer(tmp_path)


class TestBuildDucklakeExtensionsLayer:
    def test_stages_three_extensions(self, tmp_path):
        with patch("scripts.build_lambda._fetch_extension_bytes", return_value=b"EXTDATA"):
            with patch("scripts.build_lambda.OUTPUT_DIR", tmp_path):
                out = bl.build_ducklake_extensions_layer(tmp_path, bucket="b", profile="p", region="r")
        import zipfile

        names = zipfile.ZipFile(out).namelist()
        for stem in ("ducklake", "httpfs", "postgres_scanner"):
            assert any(f"duckdb_extensions/v{pinned_duckdb_version()}/linux_amd64/{stem}.duckdb_extension" == n for n in names)


class TestFetchExtensionBytes:
    def test_prefers_s3_fallback(self):
        with patch("scripts.build_lambda._try_s3_extension", return_value=b"S3RAW"):
            out = bl._fetch_extension_bytes("ducklake", bucket="b", profile="p", region="r")
        assert out == b"S3RAW"

    def test_falls_back_to_url_with_ua(self):
        payload = gzip.compress(b"RAWEXT")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["headers"] = req.headers
            return _Resp()

        with patch("scripts.build_lambda._try_s3_extension", return_value=None):
            with patch("scripts.build_lambda.urllib.request.urlopen", side_effect=fake_urlopen):
                out = bl._fetch_extension_bytes("ducklake", bucket="b", profile="p", region="r")
        assert out == b"RAWEXT"
        # browser UA present (the CDN 403s the default urllib UA)
        assert any("mozilla" in str(v).lower() for v in captured["headers"].values())

    def test_no_bucket_goes_straight_to_url(self):
        payload = gzip.compress(b"X")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with patch("scripts.build_lambda.urllib.request.urlopen", return_value=_Resp()):
            out = bl._fetch_extension_bytes("httpfs", bucket=None, profile="p", region="r")
        assert out == b"X"


class TestTryS3Extension:
    def test_success_reads_bytes(self, tmp_path):
        def fake_run(cmd, **kw):
            # Emulate `aws s3 cp <s3uri> <dest> ...` writing the dest file (cmd[4] is the local dest).
            dest = cmd[4]
            from pathlib import Path

            Path(dest).write_bytes(b"DATA")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            out = bl._try_s3_extension("bucket", "ducklake", "profile", "region")
        assert out == b"DATA"

    def test_failure_returns_none(self):
        with patch(
            "scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="x")
        ):
            assert bl._try_s3_extension("bucket", "ducklake", "profile", "region") is None


class TestUpdateLambdaFunctionsDucklakeOnly:
    def test_only_ducklake_updates_four_functions(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.side_effect = [
                types.SimpleNamespace(returncode=0),
                types.SimpleNamespace(returncode=0),
                types.SimpleNamespace(returncode=0),
                types.SimpleNamespace(returncode=0),
            ]
            update_lambda_functions("b", "p", "eu-west-2", only_ducklake=True)
        assert mock_run.call_count == 4
        targeted = []
        for c in mock_run.call_args_list:
            cmd = c[0][0]
            targeted.append(cmd[cmd.index("--function-name") + 1])
        assert set(targeted) == {
            _DUCKLAKE_WRITER_FUNCTION,
            _DUCKLAKE_READER_FUNCTION,
            _DUCKLAKE_MAINTENANCE_FUNCTION,
            _DUCKLAKE_CATALOG_DR_FUNCTION,
        }


class TestResolveDucklakeProfile:
    def test_generic_default_maps_to_personal(self):
        assert bl._resolve_ducklake_profile("company-aws-profile") == "agent_platform"

    def test_explicit_profile_unchanged(self):
        assert bl._resolve_ducklake_profile("agent_platform") == "agent_platform"
        assert bl._resolve_ducklake_profile("agent_platform_admin") == "agent_platform_admin"

    def test_ducklake_build_resolves_profile(self):
        captured = {}
        with (
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch(
                "scripts.build_lambda.build_ducklake_function_package",
                side_effect=[
                    _FakePath(name="w.zip"),
                    _FakePath(name="r.zip"),
                    _FakePath(name="m.zip"),
                    _FakePath(name="dr.zip"),
                ],
            ),
            patch("scripts.build_lambda.build_ducklake_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch(
                "scripts.build_lambda.build_ducklake_extensions_layer",
                side_effect=lambda td, **kw: captured.update(kw) or _FakePath(name="ext.zip"),
            ),
            patch("scripts.build_lambda.build_pgclient_layer", return_value=_FakePath(name="pgclient.zip")),
            patch("scripts.build_lambda.assert_within_size_limit"),
        ):
            bl._run_ducklake_build(_args(skip_upload=True, profile="company-aws-profile"))
        assert captured["profile"] == "agent_platform"  # generic default resolved to personal


class TestRunBuilds:
    def test_run_ducklake_build_skip_upload(self):
        with (
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch(
                "scripts.build_lambda.build_ducklake_function_package",
                side_effect=[
                    _FakePath(name="w.zip"),
                    _FakePath(name="r.zip"),
                    _FakePath(name="m.zip"),
                    _FakePath(name="dr.zip"),
                ],
            ),
            patch("scripts.build_lambda.build_ducklake_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch("scripts.build_lambda.build_ducklake_extensions_layer", return_value=_FakePath(name="ext.zip")),
            patch("scripts.build_lambda.build_pgclient_layer", return_value=_FakePath(name="pgclient.zip")),
            patch("scripts.build_lambda.assert_within_size_limit") as mock_assert,
            patch("scripts.build_lambda.upload_to_s3") as mock_upload,
        ):
            bl._run_ducklake_build(_args(skip_upload=True))
        assert mock_assert.call_count == 7  # 4 function zips + 3 layers
        assert mock_upload.call_count == 0

    def test_run_ducklake_build_upload_and_deploy(self):
        with (
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch(
                "scripts.build_lambda.build_ducklake_function_package",
                side_effect=[
                    _FakePath(name="w.zip"),
                    _FakePath(name="r.zip"),
                    _FakePath(name="m.zip"),
                    _FakePath(name="dr.zip"),
                ],
            ),
            patch("scripts.build_lambda.build_ducklake_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch("scripts.build_lambda.build_ducklake_extensions_layer", return_value=_FakePath(name="ext.zip")),
            patch("scripts.build_lambda.build_pgclient_layer", return_value=_FakePath(name="pgclient.zip")),
            patch("scripts.build_lambda.assert_within_size_limit"),
            patch("scripts.build_lambda.validate_bucket_exists", return_value=True),
            patch("scripts.build_lambda.upload_to_s3") as mock_upload,
            patch("scripts.build_lambda.update_lambda_functions") as mock_update,
        ):
            bl._run_ducklake_build(_args(skip_upload=False, deploy=True))
        assert mock_upload.call_count == 7  # 4 function zips + 3 layers
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs.get("only_ducklake") is True

    def test_run_ducklake_build_bucket_missing_exits(self):
        with (
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch(
                "scripts.build_lambda.build_ducklake_function_package",
                side_effect=[_FakePath(), _FakePath(), _FakePath(), _FakePath()],
            ),
            patch("scripts.build_lambda.build_ducklake_deps_layer", return_value=_FakePath()),
            patch("scripts.build_lambda.build_ducklake_extensions_layer", return_value=_FakePath()),
            patch("scripts.build_lambda.build_pgclient_layer", return_value=_FakePath()),
            patch("scripts.build_lambda.assert_within_size_limit"),
            patch("scripts.build_lambda.validate_bucket_exists", return_value=False),
        ):
            with pytest.raises(SystemExit):
                bl._run_ducklake_build(_args(skip_upload=False))

    def test_run_prod_build_skip_upload_warns_on_large_layer(self):
        big = _FakePath(size=260 * 1024 * 1024, name="deps.zip")  # > 250 MB WARN, < 262 MB hard
        with (
            patch("scripts.build_lambda.build_app_package", return_value=_FakePath(name="dp.zip")),
            patch("scripts.build_lambda.build_ops_compaction_package", return_value=_FakePath(name="ops.zip")),
            patch("scripts.build_lambda.build_deps_layer", return_value=big),
            patch("scripts.build_lambda.assert_within_size_limit") as mock_assert,
            patch("scripts.build_lambda.upload_to_s3") as mock_upload,
        ):
            bl._run_prod_build(_args(skip_upload=True))
        assert mock_assert.call_count == 3
        assert mock_upload.call_count == 0

    def test_run_prod_build_bucket_missing_exits(self):
        with (
            patch("scripts.build_lambda.build_app_package", return_value=_FakePath(name="dp.zip")),
            patch("scripts.build_lambda.build_ops_compaction_package", return_value=_FakePath(name="ops.zip")),
            patch("scripts.build_lambda.build_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch("scripts.build_lambda.assert_within_size_limit"),
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch("scripts.build_lambda.validate_bucket_exists", return_value=False),
        ):
            with pytest.raises(SystemExit):
                bl._run_prod_build(_args(skip_upload=False))

    def test_run_prod_build_upload_and_deploy(self):
        with (
            patch("scripts.build_lambda.build_app_package", return_value=_FakePath(name="dp.zip")),
            patch("scripts.build_lambda.build_ops_compaction_package", return_value=_FakePath(name="ops.zip")),
            patch("scripts.build_lambda.build_deps_layer", return_value=_FakePath(name="deps.zip")),
            patch("scripts.build_lambda.assert_within_size_limit"),
            patch("scripts.build_lambda.resolve_bucket", return_value="bk"),
            patch("scripts.build_lambda.validate_bucket_exists", return_value=True),
            patch("scripts.build_lambda.upload_to_s3") as mock_upload,
            patch("scripts.build_lambda.update_lambda_functions") as mock_update,
        ):
            bl._run_prod_build(_args(skip_upload=False, deploy=True))
        assert mock_upload.call_count == 3
        mock_update.assert_called_once()


class TestResolveBucket:
    def test_terraform_output_used(self):
        with patch(
            "scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=0, stdout="tf-bucket\n")
        ):
            assert bl.resolve_bucket("p") == "tf-bucket"

    def test_empty_output_falls_back(self):
        with patch("scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=0, stdout="")):
            assert bl.resolve_bucket("p") == "agent-platform-data-lake"

    def test_terraform_missing_falls_back(self):
        with patch("scripts.build_lambda.subprocess.run", side_effect=FileNotFoundError):
            assert bl.resolve_bucket("p") == "agent-platform-data-lake"


class TestMainDispatch:
    def test_main_ducklake_only_routes(self):
        with (
            patch("scripts.build_lambda._run_ducklake_build") as mock_dl,
            patch("scripts.build_lambda._run_prod_build") as mock_prod,
            patch("sys.argv", ["build_lambda", "--ducklake-only", "--skip-upload"]),
        ):
            bl.main()
        mock_dl.assert_called_once()
        mock_prod.assert_not_called()

    def test_main_default_routes_prod(self):
        with (
            patch("scripts.build_lambda._run_ducklake_build") as mock_dl,
            patch("scripts.build_lambda._run_prod_build") as mock_prod,
            patch("sys.argv", ["build_lambda", "--skip-upload"]),
        ):
            bl.main()
        mock_prod.assert_called_once()
        mock_dl.assert_not_called()

    def test_main_list_bundle_short_circuits(self):
        with (
            patch("scripts.build_lambda.list_bundle") as mock_lb,
            patch("scripts.build_lambda._run_prod_build") as mock_prod,
            patch("sys.argv", ["build_lambda", "--list-bundle", "data-pipeline"]),
        ):
            bl.main()
        mock_lb.assert_called_once_with("data-pipeline")
        mock_prod.assert_not_called()

    def test_main_ducklake_publish_canary_layers_routes(self):
        """--ducklake-publish-canary-layers short-circuits to publish_canary_layers() then returns."""
        with (
            patch("scripts.build_lambda.publish_canary_layers") as mock_pub,
            patch("scripts.build_lambda.resolve_bucket", return_value="test-bucket"),
            patch("scripts.build_lambda._run_ducklake_build") as mock_dl,
            patch(
                "sys.argv",
                ["build_lambda", "--ducklake-publish-canary-layers", "--profile", "agent_platform"],
            ),
        ):
            bl.main()
        mock_pub.assert_called_once()
        mock_dl.assert_not_called()


class TestPublishCanaryLayers:
    """Unit tests for publish_canary_layers() -- mocked aws lambda publish-layer-version."""

    def _arn_response(self, layer_name: str) -> str:
        import json

        return json.dumps(
            {
                "LayerVersionArn": f"arn:aws:lambda:eu-west-2:ACCOUNT_ID_PLACEHOLDER:layer:{layer_name}:99",
                "Version": 99,
            }
        )

    def test_publishes_all_three_layers_returns_arns(self):
        call_args_list = []

        def fake_run(cmd, **kw):
            layer_name = cmd[cmd.index("--layer-name") + 1]
            call_args_list.append(layer_name)
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            arns = bl.publish_canary_layers(bucket="my-bucket", profile="agent_platform", region="eu-west-2")

        assert set(arns.keys()) == {"ducklake-deps-layer", "ducklake-extensions-layer", "ducklake-pgclient-layer"}
        for name, arn in arns.items():
            assert arn == f"arn:aws:lambda:eu-west-2:ACCOUNT_ID_PLACEHOLDER:layer:{name}:99"
        assert set(call_args_list) == {"ducklake-deps-layer", "ducklake-extensions-layer", "ducklake-pgclient-layer"}

    def test_prints_json_arns_to_stdout(self, capsys):
        def fake_run(cmd, **kw):
            layer_name = cmd[cmd.index("--layer-name") + 1]
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bl.publish_canary_layers(bucket="b", profile="p", region="r")

        captured = capsys.readouterr().out
        import json

        json_line = [ln for ln in captured.splitlines() if ln.startswith("{")]
        assert json_line, "Expected a JSON line in stdout"
        data = json.loads(json_line[-1])
        assert "ducklake-deps-layer" in data

    def test_exits_on_publish_failure(self):
        def fake_run(cmd, **kw):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="AccessDenied")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            with pytest.raises(SystemExit):
                bl.publish_canary_layers(bucket="b", profile="p", region="r")

    def test_uses_correct_s3_key_per_layer(self):
        seen_keys = []

        def fake_run(cmd, **kw):
            content_arg = cmd[cmd.index("--content") + 1]
            seen_keys.append(content_arg)
            layer_name = cmd[cmd.index("--layer-name") + 1]
            return types.SimpleNamespace(returncode=0, stdout=self._arn_response(layer_name), stderr="")

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            bl.publish_canary_layers(bucket="my-bucket", profile="p", region="r")

        for key in seen_keys:
            assert "my-bucket" in key
            assert key.startswith("S3Bucket=my-bucket,S3Key=lambda-packages/")


class TestBuildPgclientLayerPgDumpOnlyBundle:
    """build_pgclient_layer succeeds with a pg_dump-only bundle (no pg_restore required, Decision 100)."""

    def test_passes_with_pg_dump_only_bundle(self, tmp_path):
        """pg_dump-only bundle (no bin/pg_restore) must not cause build_pgclient_layer to exit."""
        import io
        import tarfile

        raw_tar = io.BytesIO()
        with tarfile.open(fileobj=raw_tar, mode="w:gz") as tar:
            content = b"#!/bin/sh\necho 'fake-binary'"
            info = tarfile.TarInfo(name="bin/pg_dump")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        bundle_bytes = raw_tar.getvalue()

        def fake_run(cmd, **kw):
            return types.SimpleNamespace(returncode=0, stdout=f"pg_dump (PostgreSQL) {bl.PINNED_PG_MAJOR}.0\n", stderr="")

        with (
            patch("scripts.build_lambda._try_s3_pgclient", return_value=bundle_bytes),
            patch("scripts.build_lambda.subprocess.run", side_effect=fake_run),
            patch("scripts.build_lambda.OUTPUT_DIR", tmp_path),
        ):
            result = bl.build_pgclient_layer(tmp_path, bucket="my-bucket", profile="p", region="r")
        assert result.name == "ducklake-pgclient-layer.zip"
