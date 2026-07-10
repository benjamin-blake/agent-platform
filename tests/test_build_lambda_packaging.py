"""Tests for scripts/build_lambda_packaging.py (Decision 104 split of tests/test_build_lambda.py)."""

import gzip
import hashlib
import types
from unittest.mock import MagicMock, patch

import pytest

import scripts.build_lambda_packaging as bm
from scripts.build_lambda_config import LAMBDA_SIZE_LIMIT_BYTES, PINNED_DUCKDB_VERSION, PINNED_PG_MAJOR
from src.common.ducklake_version import pinned_duckdb_version

pytestmark = pytest.mark.unit


class _FakePath:
    """Minimal Path double exposing .name + .stat().st_size for size-assert tests."""

    def __init__(self, size=100, name="x.zip"):
        self._size = size
        self.name = name

    def stat(self):
        return types.SimpleNamespace(st_size=self._size)


def _make_pgclient_bundle(*, include_pg_restore: bool) -> bytes:
    import io
    import tarfile

    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w:gz") as tar:
        content = b"#!/bin/sh\necho 'fake-binary'"
        names = ["bin/pg_dump"] + (["bin/pg_restore"] if include_pg_restore else [])
        for name in names:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return raw_tar.getvalue()


def _fake_version_run(*, pg_restore_version: str = PINNED_PG_MAJOR):
    def fake_run(cmd, **kw):
        binary = cmd[0]
        if binary.endswith("pg_restore"):
            return types.SimpleNamespace(returncode=0, stdout=f"pg_restore (PostgreSQL) {pg_restore_version}.0\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout=f"pg_dump (PostgreSQL) {PINNED_PG_MAJOR}.0\n", stderr="")

    return fake_run


class TestSizeAssert:
    def test_under_limit_ok(self):
        bm.assert_within_size_limit(_FakePath(size=100))  # no raise

    def test_at_limit_ok(self):
        bm.assert_within_size_limit(_FakePath(size=LAMBDA_SIZE_LIMIT_BYTES))

    def test_over_limit_exits(self):
        with pytest.raises(SystemExit) as exc:
            bm.assert_within_size_limit(_FakePath(size=LAMBDA_SIZE_LIMIT_BYTES + 1, name="big.zip"))
        assert exc.value.code == 1


class TestBuildLambdaConfigScope:
    """Verify Lambda zips contain only config.yaml + lambda/<name>/ (T-1.7)."""

    def _run_build(self, builder_fn_name: str, tmp_path):
        """Run a build function with all IO patched, capturing copy2 and copytree calls."""
        import scripts.build_lambda_packaging as bm

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
            patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path),
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
        """build_lambda_packaging.py source must not hardcode shutil.copytree(ROOT/"src") or ROOT/"config".

        CD.24 retired the blanket whole-src and whole-config copytrees from the Lambda build tool.
        The src/ tree is still bundled, but ONLY because the data-pipeline manifest declares
        includes: [src/] and stage_bundle (in lambda_manifest.py) walks it -- the copytree must
        be manifest-driven, never hardcoded here. This source-level guard mirrors VP Step 4 and
        prevents a regression that re-adds the hardcoded blanket copytree. (Asserting absence of
        a runtime /src copytree would be wrong: stage_bundle legitimately copytrees src/ per the
        manifest, as the binding file-list-equivalence check confirms.)
        """
        import re
        from pathlib import Path

        from scripts.build_lambda_packaging import __file__ as build_lambda_packaging_path

        source = Path(build_lambda_packaging_path).read_text(encoding="utf-8")
        # Strip comments and docstrings is overkill; match only actual copytree CALLS on ROOT/src|config.
        src_copytree = re.compile(r"copytree\(\s*ROOT\s*/\s*[\"']src[\"']")
        config_copytree = re.compile(r"copytree\(\s*ROOT\s*/\s*[\"']config[\"']")
        assert not src_copytree.search(source), "Hardcoded shutil.copytree(ROOT/'src') must be retired (CD.24)"
        assert not config_copytree.search(source), "Hardcoded shutil.copytree(ROOT/'config') must be retired (CD.24)"


class TestBuildDucklakeFunctionPackage:
    def test_builds_from_manifest(self, tmp_path):
        with (
            patch("scripts.lambda_manifest.load", return_value=MagicMock()) as mock_load,
            patch("scripts.lambda_manifest.stage_bundle") as mock_stage,
            patch("scripts.build_lambda_packaging._zip_staged_dir", return_value=tmp_path / "ducklake-writer.zip") as mock_zip,
        ):
            out = bm.build_ducklake_function_package(tmp_path, "ducklake_writer", "ducklake-writer.zip")
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
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path):
                out = bm.build_ducklake_deps_layer(tmp_path)
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
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path):
                with pytest.raises(SystemExit):
                    bm.build_ducklake_deps_layer(tmp_path)


class TestBuildDucklakeExtensionsLayer:
    def test_stages_three_extensions(self, tmp_path):
        with patch("scripts.build_lambda_packaging._fetch_extension_bytes", return_value=b"EXTDATA"):
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path):
                out = bm.build_ducklake_extensions_layer(tmp_path, bucket="b", profile="p", region="r")
        import zipfile

        names = zipfile.ZipFile(out).namelist()
        for stem in ("ducklake", "httpfs", "postgres_scanner"):
            assert any(f"duckdb_extensions/v{pinned_duckdb_version()}/linux_amd64/{stem}.duckdb_extension" == n for n in names)


class TestFetchExtensionBytes:
    def test_prefers_s3_fallback(self):
        with patch("scripts.build_lambda_packaging._try_s3_extension", return_value=b"S3RAW"):
            out = bm._fetch_extension_bytes("ducklake", bucket="b", profile="p", region="r")
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

        with patch("scripts.build_lambda_packaging._try_s3_extension", return_value=None):
            with patch("scripts.build_lambda.urllib.request.urlopen", side_effect=fake_urlopen):
                out = bm._fetch_extension_bytes("ducklake", bucket="b", profile="p", region="r")
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
            out = bm._fetch_extension_bytes("httpfs", bucket=None, profile="p", region="r")
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
            out = bm._try_s3_extension("bucket", "ducklake", "profile", "region")
        assert out == b"DATA"

    def test_failure_returns_none(self):
        with patch(
            "scripts.build_lambda.subprocess.run", return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="x")
        ):
            assert bm._try_s3_extension("bucket", "ducklake", "profile", "region") is None


class TestBuildPgclientLayerPgRestoreGuard:
    """build_pgclient_layer fails closed without a valid PG16 pg_restore (Decision 88/107 c1 gate)."""

    def test_missing_pg_restore_exits(self, tmp_path):
        """A bundle with pg_dump but no bin/pg_restore must exit before the layer ships."""
        bundle_bytes = _make_pgclient_bundle(include_pg_restore=False)

        with (
            patch("scripts.build_lambda_packaging._try_s3_pgclient", return_value=bundle_bytes),
            patch("scripts.build_lambda.subprocess.run", side_effect=_fake_version_run()),
            patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path),
            pytest.raises(SystemExit),
        ):
            bm.build_pgclient_layer(tmp_path, bucket="my-bucket", profile="p", region="r")

    def test_non_pg16_pg_restore_exits(self, tmp_path):
        """A bundled pg_restore that reports a non-PG16 version must exit before the layer ships."""
        bundle_bytes = _make_pgclient_bundle(include_pg_restore=True)

        with (
            patch("scripts.build_lambda_packaging._try_s3_pgclient", return_value=bundle_bytes),
            patch("scripts.build_lambda.subprocess.run", side_effect=_fake_version_run(pg_restore_version="15")),
            patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path),
            pytest.raises(SystemExit),
        ):
            bm.build_pgclient_layer(tmp_path, bucket="my-bucket", profile="p", region="r")

    def test_valid_pg16_bundle_succeeds(self, tmp_path):
        """A bundle with a valid PG16 pg_dump + pg_restore builds the layer without exiting."""
        bundle_bytes = _make_pgclient_bundle(include_pg_restore=True)

        with (
            patch("scripts.build_lambda_packaging._try_s3_pgclient", return_value=bundle_bytes),
            patch("scripts.build_lambda.subprocess.run", side_effect=_fake_version_run()),
            patch("scripts.build_lambda_packaging.OUTPUT_DIR", tmp_path),
        ):
            result = bm.build_pgclient_layer(tmp_path, bucket="my-bucket", profile="p", region="r")
        assert result.name == "ducklake-pgclient-layer.zip"


class TestDucklakeZipDeterminism:
    """The seven DuckLake zip builders produce byte-identical output across two builds of the
    same input tree (Decision 77 no-TOCTOU mitigation: the push apply-path re-upload must be
    idempotent vs. the reviewed PR-job artifact's filemd5)."""

    def test_staged_dir_byte_identical_across_two_builds(self, tmp_path):
        """_zip_staged_dir backs the four DuckLake function zips (writer/reader/maintenance/catalog-dr)."""
        stage1 = tmp_path / "stage1"
        stage2 = tmp_path / "stage2"
        for stage in (stage1, stage2):
            (stage / "sub").mkdir(parents=True)
            (stage / "a.py").write_text("a=1", encoding="utf-8")
            (stage / "sub" / "b.py").write_text("b=2", encoding="utf-8")

        zip1 = bm._zip_staged_dir(stage1, tmp_path / "one.zip")
        zip2 = bm._zip_staged_dir(stage2, tmp_path / "two.zip")

        assert hashlib.md5(zip1.read_bytes()).hexdigest() == hashlib.md5(zip2.read_bytes()).hexdigest()

    def test_deps_layer_byte_identical_across_two_builds(self, tmp_path):
        from pathlib import Path

        def fake_run(cmd, **kw):
            target = Path(cmd[cmd.index("--target") + 1])
            (target / "foo.py").write_text("x=1", encoding="utf-8")
            (target / "bar").mkdir()
            (target / "bar" / "baz.py").write_text("y=2", encoding="utf-8")
            return types.SimpleNamespace(returncode=0)

        out_dir_1 = tmp_path / "out1"
        out_dir_1.mkdir()
        out_dir_2 = tmp_path / "out2"
        out_dir_2.mkdir()

        with patch("scripts.build_lambda.subprocess.run", side_effect=fake_run):
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_1):
                zip1 = bm.build_ducklake_deps_layer(tmp_path / "build1")
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_2):
                zip2 = bm.build_ducklake_deps_layer(tmp_path / "build2")

        assert hashlib.md5(zip1.read_bytes()).hexdigest() == hashlib.md5(zip2.read_bytes()).hexdigest()

    def test_extensions_layer_byte_identical_across_two_builds(self, tmp_path):
        out_dir_1 = tmp_path / "out1"
        out_dir_1.mkdir()
        out_dir_2 = tmp_path / "out2"
        out_dir_2.mkdir()
        with patch("scripts.build_lambda_packaging._fetch_extension_bytes", return_value=b"EXTDATA"):
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_1):
                zip1 = bm.build_ducklake_extensions_layer(tmp_path / "build1", bucket="b", profile="p", region="r")
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_2):
                zip2 = bm.build_ducklake_extensions_layer(tmp_path / "build2", bucket="b", profile="p", region="r")
        assert hashlib.md5(zip1.read_bytes()).hexdigest() == hashlib.md5(zip2.read_bytes()).hexdigest()

    def test_pgclient_layer_byte_identical_across_two_builds(self, tmp_path):
        bundle_bytes = _make_pgclient_bundle(include_pg_restore=True)
        out_dir_1 = tmp_path / "out1"
        out_dir_1.mkdir()
        out_dir_2 = tmp_path / "out2"
        out_dir_2.mkdir()
        with (
            patch("scripts.build_lambda_packaging._try_s3_pgclient", return_value=bundle_bytes),
            patch("scripts.build_lambda.subprocess.run", side_effect=_fake_version_run()),
        ):
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_1):
                zip1 = bm.build_pgclient_layer(tmp_path / "build1", bucket="my-bucket", profile="p", region="r")
            with patch("scripts.build_lambda_packaging.OUTPUT_DIR", out_dir_2):
                zip2 = bm.build_pgclient_layer(tmp_path / "build2", bucket="my-bucket", profile="p", region="r")
        assert hashlib.md5(zip1.read_bytes()).hexdigest() == hashlib.md5(zip2.read_bytes()).hexdigest()


class TestProfilelessArgv:
    """aws CLI argv omits `--profile` when the resolved profile is empty (GitHub-hosted OIDC
    runners resolve creds from the environment and have no named profile) and includes it when
    non-empty (local/agent_platform dev). Unblocks `--ducklake-only` under CI (rec-2512).

    Only the packaging-owned functions' profileless tests live here; see the config/deploy test
    files for the rest of the original TestProfilelessArgv split.
    """

    def test_try_s3_pgclient_omits_profile_when_empty(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.return_value = types.SimpleNamespace(returncode=1, stdout="", stderr="")
            bm._try_s3_pgclient("bucket", "pgclient-bundle.tar.gz", "", "eu-west-2")
        argv = mock_run.call_args[0][0]
        assert "--profile" not in argv

    def test_try_s3_extension_omits_profile_when_empty(self):
        with patch("scripts.build_lambda.subprocess.run") as mock_run:
            mock_run.return_value = types.SimpleNamespace(returncode=1, stdout="", stderr="")
            bm._try_s3_extension("bucket", "ducklake", "", "eu-west-2")
        argv = mock_run.call_args[0][0]
        assert "--profile" not in argv


class TestListBundle:
    """rec-2077: list_bundle stages a manifest-driven bundle and prints its static file list
    (intent, NOT bundled -- see plan context)."""

    def test_missing_manifest_exits(self):
        with pytest.raises(SystemExit) as exc:
            bm.list_bundle("definitely-not-a-real-lambda-slug")
        assert exc.value.code == 1

    def test_prints_sorted_files_excludes_pycache(self, capsys):
        def fake_stage(manifest, stage_dir, skip_pip=True):
            (stage_dir / "b.py").write_text("b", encoding="utf-8")
            (stage_dir / "a.py").write_text("a", encoding="utf-8")
            pycache = stage_dir / "__pycache__"
            pycache.mkdir()
            (pycache / "a.cpython-312.pyc").write_bytes(b"x")

        with (
            patch("scripts.lambda_manifest.load", return_value=MagicMock()),
            patch("scripts.lambda_manifest.stage_bundle", side_effect=fake_stage),
        ):
            bm.list_bundle("data-pipeline")

        out = capsys.readouterr().out.splitlines()
        assert out == ["a.py", "b.py"]
