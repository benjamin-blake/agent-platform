#!/usr/bin/env python3
# complexity-waiver: decision-43 -- build orchestrator: prod (data-pipeline/ops-compaction) + the T2.17
# DuckLake build path (2 function zips + deps + extensions layer builders) legitimately exceed 500 SLOC.
"""Build Lambda deployment packages for the data pipeline (no Docker required).

Creates these zip artifacts:
  1. data-pipeline.zip                      -- application code (manifest-driven)
  2. ops-compaction.zip                     -- minimal ops compaction handler
  3. data-pipeline-deps-layer.zip           -- dependencies layer (yfinance, pyyaml, etc.)
  4. ducklake-{writer,reader,maintenance,catalog-dr}.zip -- T2.17/T2.18 DuckLake runtime functions (--ducklake-only)
  5. ducklake-{deps,extensions}-layer.zip   -- duckdb (pinned via config/lambda/ducklake/version.yaml)
                                               + baked extensions (--ducklake-only)
  6. ducklake-pgclient-layer.zip            -- pg_dump + pg_restore 16 + libpq.so (--ducklake-only, T2.18 FP-B)

Both app zips are built from src/lambdas/<name>/manifest.yaml rather than
whole-src/whole-config copytrees (Decision 79 / CD.24).
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "lambda-packages"

# AWS Lambda hard ceiling on a function zip / layer (terraform CLAUDE.md). Exceeding it must FAIL
# the build, not warn -- an oversize artifact is rejected at deploy time anyway.
LAMBDA_SIZE_LIMIT_BYTES = 262144000  # 262 MB
LAMBDA_SIZE_WARN_BYTES = 250 * 1024 * 1024  # early warning before the hard ceiling

# DuckLake lockstep pin (OQ.12): derived from the SSOT (config/lambda/ducklake/version.yaml).
from src.common.ducklake_version import (  # noqa: E402, I001
    extension_platform as _extension_platform,
    pinned_duckdb_version as _pinned_duckdb_version,
)

PINNED_DUCKDB_VERSION = _pinned_duckdb_version()

PROD_DEPS = [
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "pyyaml>=6.0",
    "boto3>=1.28.0",
    "pyarrow>=12.0.0",
    "psycopg2-binary>=2.9.0",
    "yfinance>=0.2.30",
    "requests>=2.31.0",
    "sympy>=1.12",
    "scikit-learn>=1.3.0",
    "aiohttp>=3.8.0",
]

# DuckLake deps layer (ducklake-deps): duckdb pinned exactly, plus the runtime's import-time deps.
# pyyaml is required by ducklake_runtime.load_field_semantics; boto3 is provided by the Lambda base.
DUCKLAKE_DEPS = [
    f"duckdb=={PINNED_DUCKDB_VERSION}",
    "psycopg2-binary>=2.9.0",
    "python-ulid>=2.2.0",
    # python-ulid imports `from typing_extensions import Self` unconditionally, but its dependency
    # marker only requires typing_extensions on python<3.11. Building for 3.12 therefore skips it,
    # so the write path ImportErrors at runtime (ModuleNotFoundError: typing_extensions). Pin it.
    "typing_extensions>=4.0",
    # duckdb lazily imports pytz when it converts tz-aware Python datetimes to/from its TIMESTAMP
    # types (the SCD2 path binds UTC-aware ULID timestamps). duckdb declares no hard pytz dep, so it
    # must be bundled explicitly or the write/read paths raise InvalidInputException at runtime.
    "pytz>=2024.1",
    "pyyaml>=6.0",
]

# DuckLake extensions baked into the ducklake-extensions layer: (LOAD name, published file stem).
# DuckDB publishes the Postgres extension binary as postgres_scanner.duckdb_extension even though it
# LOADs as `postgres` (verified against the pinned duckdb / config/lambda/ducklake/version.yaml).
DUCKLAKE_EXTENSIONS = (("ducklake", "ducklake"), ("httpfs", "httpfs"), ("postgres", "postgres_scanner"))
DUCKLAKE_EXT_PLATFORM = _extension_platform()  # derived from config/lambda/ducklake/version.yaml
DUCKLAKE_EXT_URL_BASE = f"https://extensions.duckdb.org/v{PINNED_DUCKDB_VERSION}/{DUCKLAKE_EXT_PLATFORM}"
# Vendored fallback prefix (raw .duckdb_extension files), seeded when egress to the CDN is blocked.
DUCKLAKE_EXT_S3_PREFIX = f"ducklake-extensions/v{PINNED_DUCKDB_VERSION}"
# The DuckDB CDN 403s the default urllib User-Agent; a browser UA returns 200.
_EXT_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0"}

_DUCKLAKE_WRITER_FUNCTION = "agent-platform-ducklake-writer"
_DUCKLAKE_READER_FUNCTION = "agent-platform-ducklake-reader"
_DUCKLAKE_MAINTENANCE_FUNCTION = "agent-platform-ducklake-maintenance"
_DUCKLAKE_CATALOG_DR_FUNCTION = "agent-platform-ducklake-catalog-dr"
_DUCKLAKE_FUNCTION_ZIP_KEYS = {
    _DUCKLAKE_WRITER_FUNCTION: "lambda-packages/ducklake-writer.zip",
    _DUCKLAKE_READER_FUNCTION: "lambda-packages/ducklake-reader.zip",
    _DUCKLAKE_MAINTENANCE_FUNCTION: "lambda-packages/ducklake-maintenance.zip",
    _DUCKLAKE_CATALOG_DR_FUNCTION: "lambda-packages/ducklake-catalog-dr.zip",
}

# S3 key prefix for vendored AL2023/x86_64 pg_dump 16 binary + libpq.so.
# The binary is fetched at layer-build time from this S3 prefix (no pip wheel for pg_dump).
# Seeded by the operator via: aws s3 cp pg_dump s3://<bucket>/ducklake-pgclient/pg_dump16 --profile agent_platform
DUCKLAKE_PGCLIENT_S3_PREFIX = "ducklake-pgclient"
PINNED_PG_MAJOR = "16"

# The three DuckLake Lambda layers (deps + extensions + pgclient). Used by publish_canary_layers.
DUCKLAKE_LAYER_NAMES = (
    "ducklake-deps-layer",
    "ducklake-extensions-layer",
    "ducklake-pgclient-layer",
)

# Retained for backward compatibility with external callers and tests.
_LAMBDA_SCRIPTS = [
    "__init__.py",
    "aws_profile.py",
    "github_models_client.py",
    "llm_client.py",
    "llm_utils.py",
    "ops_writer.py",
    "run_scheduled_agent.py",
    "s3_log_store.py",
    "telemetry_schemas.py",
    "tool_runtime.py",
]

_LAMBDA_FUNCTION_NAMES = [
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
]

_OPS_COMPACTION_FUNCTION_NAME = "agent-platform-ops-compaction"
_OPS_COMPACTION_ZIP_KEY = "lambda-packages/ops-compaction.zip"


# ---------------------------------------------------------------------------
# Build contract loader (T-1.16): lazy, cached, import-safe.
# Falls through to in-code FALLBACK_* constants on ANY read/parse failure.
# ---------------------------------------------------------------------------

_BUILD_CONTRACT_PATH = ROOT / "docs" / "contracts" / "build-lambda.yaml"
_BUILD_CONTRACT_REGISTRY: dict | None = None  # None until first accessor call


def _fallback_build_registry() -> dict:
    return {
        "size_limit_bytes": LAMBDA_SIZE_LIMIT_BYTES,
        "deploy_targets": {
            "prod_functions": list(_LAMBDA_FUNCTION_NAMES),
            "ops_compaction": {
                "function": _OPS_COMPACTION_FUNCTION_NAME,
                "zip_key": _OPS_COMPACTION_ZIP_KEY,
            },
            "ducklake_function_zip_keys": dict(_DUCKLAKE_FUNCTION_ZIP_KEYS),
            "ducklake_layer_names": list(DUCKLAKE_LAYER_NAMES),
        },
    }


def _load_build_contract() -> dict:
    global _BUILD_CONTRACT_REGISTRY
    if _BUILD_CONTRACT_REGISTRY is not None:
        return _BUILD_CONTRACT_REGISTRY
    try:
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load(_BUILD_CONTRACT_PATH.read_text(encoding="utf-8"))
        registry = {
            "size_limit_bytes": raw["size_limit_bytes"],
            "deploy_targets": {
                "prod_functions": list(raw["deploy_targets"]["prod_functions"]),
                "ops_compaction": dict(raw["deploy_targets"]["ops_compaction"]),
                "ducklake_function_zip_keys": dict(raw["deploy_targets"]["ducklake_function_zip_keys"]),
                "ducklake_layer_names": list(raw["deploy_targets"]["ducklake_layer_names"]),
            },
        }
        _BUILD_CONTRACT_REGISTRY = registry
    except Exception:
        _BUILD_CONTRACT_REGISTRY = _fallback_build_registry()
    return _BUILD_CONTRACT_REGISTRY


def _build_size_limit_bytes() -> int:
    return _load_build_contract()["size_limit_bytes"]


def _build_prod_function_names() -> list[str]:
    return list(_load_build_contract()["deploy_targets"]["prod_functions"])


def _build_ops_compaction() -> dict:
    return dict(_load_build_contract()["deploy_targets"]["ops_compaction"])


def _build_ducklake_function_zip_keys() -> dict[str, str]:
    return dict(_load_build_contract()["deploy_targets"]["ducklake_function_zip_keys"])


def _build_ducklake_layer_names() -> list[str]:
    return list(_load_build_contract()["deploy_targets"]["ducklake_layer_names"])


def _get_lambda_file_patterns() -> list[str]:
    """Derive LAMBDA_FILE_PATTERNS from the union of all active manifests (CD.24)."""
    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import derive_lambda_file_patterns  # noqa: PLC0415

        return derive_lambda_file_patterns()
    except Exception:
        return []
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


# Derived at import time from the union of active manifests.
LAMBDA_FILE_PATTERNS: list[str] = _get_lambda_file_patterns()


# Fixed ZipInfo timestamp (DOS epoch floor) so byte-reproducible zips don't leak build-time
# wall-clock mtimes into the archive (Decision 77 no-TOCTOU: the applied zip must be byte-identical
# to the reviewed PR-job artifact).
_FIXED_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)


def _deterministic_zipinfo(arcname: str, *, executable: bool = False) -> zipfile.ZipInfo:
    """Build a ZipInfo with a pinned timestamp + explicit permission bits (no filesystem mtime leak)."""
    info = zipfile.ZipInfo(arcname, date_time=_FIXED_ZIP_DATETIME)
    info.external_attr = (0o755 if executable else 0o644) << 16
    return info


def _zip_staged_dir(stage_dir: Path, zip_path: Path) -> Path:
    """Write all files in stage_dir into zip_path (ZIP_DEFLATED), byte-reproducibly.

    Sorted iteration + pinned ZipInfo timestamp/permissions make the output byte-identical across
    builds of the same input tree (Decision 77). Shared by the four DuckLake function zips and the
    two DuckLake layer builders that don't need pgclient's per-entry executable-bit logic.
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(stage_dir.rglob("*")):
            if f.is_file():
                zf.writestr(_deterministic_zipinfo(str(f.relative_to(stage_dir))), f.read_bytes())
    return zip_path


_zip_layer_dir_deterministic = _zip_staged_dir


def build_app_package(temp_dir: Path) -> Path:
    """Create data-pipeline.zip from the data-pipeline manifest (manifest-driven, CD.24).

    Retired whole-src and whole-config tree bundling in favour of explicit manifest declarations.
    All bundled files are explicitly declared in src/lambdas/data-pipeline/manifest.yaml.
    """
    from scripts.lambda_manifest import load, stage_bundle  # noqa: PLC0415

    manifest = load(ROOT / "src" / "lambdas" / "data-pipeline" / "manifest.yaml")
    app_dir = temp_dir / "app"
    app_dir.mkdir(parents=True)

    print("  Installing pip dependencies into app package...")
    stage_bundle(manifest, app_dir, skip_pip=False)

    zip_path = OUTPUT_DIR / "data-pipeline.zip"
    return _zip_staged_dir(app_dir, zip_path)


def build_ops_compaction_package(temp_dir: Path) -> Path:
    """Create ops-compaction.zip from the ops-compaction manifest (manifest-driven, CD.24).

    Minimal zip -- no pip dependencies to stay under the 262 MB Lambda+AWSSDKPandas limit.
    All bundled files are explicitly declared in src/lambdas/ops-compaction/manifest.yaml.
    """
    from scripts.lambda_manifest import load, stage_bundle  # noqa: PLC0415

    manifest = load(ROOT / "src" / "lambdas" / "ops-compaction" / "manifest.yaml")
    app_dir = temp_dir / "ops-app"
    app_dir.mkdir(parents=True)

    stage_bundle(manifest, app_dir, skip_pip=True)

    zip_path = OUTPUT_DIR / "ops-compaction.zip"
    return _zip_staged_dir(app_dir, zip_path)


def list_bundle(artifact_slug: str) -> None:
    """Stage a manifest-driven bundle and emit the static file list to stdout.

    Excludes __pycache__ entries and pip-installed packages (those are determined
    by pip install and not manifest-declared paths).  Used for file-list equivalence
    diffing against pre-change copytree baselines (VP Step 7 of CD.24 plans).
    """
    from scripts.lambda_manifest import load, stage_bundle  # noqa: PLC0415

    manifest_path = ROOT / "src" / "lambdas" / artifact_slug / "manifest.yaml"
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path.relative_to(ROOT)}", file=sys.stderr)
        sys.exit(1)

    manifest = load(manifest_path)
    with tempfile.TemporaryDirectory(prefix=f"list-bundle-{artifact_slug}-") as tmp:
        stage_dir = Path(tmp)
        stage_bundle(manifest, stage_dir, skip_pip=True)
        for f in sorted(stage_dir.rglob("*")):
            if f.is_file() and "__pycache__" not in str(f):
                print(str(f.relative_to(stage_dir)))


def build_deps_layer(temp_dir: Path) -> Path:
    """Create data-pipeline-deps-layer.zip with Lambda layer structure."""
    site_packages = temp_dir / "layer" / "python" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    req_file = temp_dir / "requirements-lambda.txt"
    req_file.write_text("\n".join(PROD_DEPS), encoding="utf-8")

    print("  Installing to Lambda layer structure...")
    pip_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(req_file),
            "--target",
            str(site_packages),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--quiet",
        ],
        check=False,
    )
    if pip_result.returncode != 0:
        print(f"ERROR: Dependency installation failed (exit {pip_result.returncode})")
        sys.exit(1)

    for pattern in ("*.dist-info", "__pycache__", "*.pyc", "tests", "test"):
        for path in site_packages.rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    zip_path = OUTPUT_DIR / "data-pipeline-deps-layer.zip"
    layer_dir = temp_dir / "layer"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in layer_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(layer_dir))
    return zip_path


def assert_within_size_limit(zip_path: Path) -> None:
    """Hard-fail the build if *zip_path* exceeds the 262 MB Lambda ceiling (terraform CLAUDE.md).

    Replaces the prior non-fatal WARN: an oversize artifact is rejected at deploy time, so the build
    must stop here rather than ship a zip that cannot be deployed.
    """
    size = zip_path.stat().st_size
    limit = _build_size_limit_bytes()
    if size > limit:
        mb = round(size / 1024 / 1024, 2)
        print(
            f"ERROR: {zip_path.name} is {mb} MB ({size} bytes), over the "
            f"{limit} byte (262 MB) Lambda zip/layer limit. Build failed.",
            file=sys.stderr,
        )
        sys.exit(1)


def build_ducklake_function_package(temp_dir: Path, slug: str, zip_name: str) -> Path:
    """Build a DuckLake function zip from its manifest (deps live in the layer, not the zip)."""
    from scripts.lambda_manifest import load, stage_bundle  # noqa: PLC0415

    manifest = load(ROOT / "src" / "lambdas" / slug / "manifest.yaml")
    app_dir = temp_dir / slug
    app_dir.mkdir(parents=True)
    stage_bundle(manifest, app_dir, skip_pip=True)  # pip_packages empty; duckdb/ulid come from the layer
    return _zip_staged_dir(app_dir, OUTPUT_DIR / zip_name)


def build_ducklake_deps_layer(temp_dir: Path) -> Path:
    """Create ducklake-deps-layer.zip (duckdb pinned via config/lambda/ducklake/version.yaml
    + psycopg2-binary + python-ulid + pyyaml)."""
    site_packages = temp_dir / "ducklake-deps" / "python" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    req_file = temp_dir / "requirements-ducklake.txt"
    req_file.write_text("\n".join(DUCKLAKE_DEPS), encoding="utf-8")

    print("  Installing DuckLake deps to Lambda layer structure...")
    # duckdb publishes a manylinux_2_28 wheel (no manylinux2014/2_17 wheel above 1.2.2);
    # Lambda python3.12 runs on Amazon Linux 2023 (glibc 2.34), compatible with 2_28. Offer both
    # tags newest-first so each dep resolves to its best available wheel.
    pip_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(req_file),
            "--target",
            str(site_packages),
            "--platform",
            "manylinux_2_28_x86_64",
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--quiet",
        ],
        check=False,
    )
    if pip_result.returncode != 0:
        print(f"ERROR: DuckLake deps installation failed (exit {pip_result.returncode})")
        sys.exit(1)

    # Do NOT strip *.dist-info: duckdb>=1.3 reads its own version via importlib.metadata at import
    # time (duckdb/_version.py -> importlib.metadata.version("duckdb")), which needs the dist-info
    # METADATA present. Removing it raises PackageNotFoundError on a clean Lambda runtime (no other
    # duckdb metadata on the path), surfacing as an ImportError. The size saved is trivial.
    for pattern in ("__pycache__", "*.pyc", "tests", "test"):
        for path in site_packages.rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    zip_path = OUTPUT_DIR / "ducklake-deps-layer.zip"
    layer_dir = temp_dir / "ducklake-deps"
    return _zip_layer_dir_deterministic(layer_dir, zip_path)


def _fetch_extension_bytes(stem: str, *, bucket: str | None, profile: str, region: str) -> bytes:
    """Return the raw .duckdb_extension bytes for *stem*.

    Prefers the vendored S3 fallback (raw, pre-gunzipped) when present; otherwise fetches the .gz
    from the DuckDB CDN with a browser User-Agent (the CDN 403s the default urllib UA) and gunzips.
    """
    if bucket is not None:
        raw = _try_s3_extension(bucket, stem, profile, region)
        if raw is not None:
            print(f"    {stem}: from S3 fallback s3://{bucket}/{DUCKLAKE_EXT_S3_PREFIX}/")
            return raw
    url = f"{DUCKLAKE_EXT_URL_BASE}/{stem}.duckdb_extension.gz"
    print(f"    {stem}: fetching {url}")
    req = urllib.request.Request(url, headers=_EXT_FETCH_HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 -- pinned https host
        return gzip.decompress(resp.read())


def _try_s3_extension(bucket: str, stem: str, profile: str, region: str) -> bytes | None:
    """Try to read the vendored raw extension from S3; return None if absent/unreadable."""
    import tempfile as _tf  # noqa: PLC0415

    key = f"{DUCKLAKE_EXT_S3_PREFIX}/{stem}.duckdb_extension"
    with _tf.TemporaryDirectory() as td:
        dest = Path(td) / f"{stem}.duckdb_extension"
        result = subprocess.run(
            ["aws", "s3", "cp", f"s3://{bucket}/{key}", str(dest), "--region", region, *_aws_profile_args(profile)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and dest.exists():
            return dest.read_bytes()
    return None


def build_ducklake_extensions_layer(
    temp_dir: Path, *, bucket: str | None = None, profile: str = "agent_platform", region: str = "eu-west-2"
) -> Path:
    """Create ducklake-extensions-layer.zip staging the 3 pinned extensions under /opt.

    Layout: duckdb_extensions/v{ver}/linux_amd64/{ducklake,httpfs,postgres_scanner}.duckdb_extension
    so the runtime sets extension_directory=/opt/duckdb_extensions and LOADs them with no network.
    """
    ext_root = temp_dir / "ducklake-ext" / "duckdb_extensions" / f"v{PINNED_DUCKDB_VERSION}" / DUCKLAKE_EXT_PLATFORM
    ext_root.mkdir(parents=True)

    print("  Staging DuckLake extensions (prefer S3 fallback, else CDN)...")
    for _load_name, stem in DUCKLAKE_EXTENSIONS:
        raw = _fetch_extension_bytes(stem, bucket=bucket, profile=profile, region=region)
        (ext_root / f"{stem}.duckdb_extension").write_bytes(raw)

    zip_path = OUTPUT_DIR / "ducklake-extensions-layer.zip"
    layer_dir = temp_dir / "ducklake-ext"
    return _zip_layer_dir_deterministic(layer_dir, zip_path)


def _try_s3_pgclient(bucket: str, filename: str, profile: str, region: str) -> bytes | None:
    """Try to fetch a vendored pgclient binary from S3; return None if absent/unreadable."""
    import tempfile as _tf  # noqa: PLC0415

    key = f"{DUCKLAKE_PGCLIENT_S3_PREFIX}/{filename}"
    with _tf.TemporaryDirectory() as td:
        dest = Path(td) / filename
        result = subprocess.run(
            ["aws", "s3", "cp", f"s3://{bucket}/{key}", str(dest), "--region", region, *_aws_profile_args(profile)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0 and dest.exists():
            return dest.read_bytes()
    return None


def build_pgclient_layer(
    temp_dir: Path, *, bucket: str | None = None, profile: str = "agent_platform", region: str = "eu-west-2"
) -> Path:
    """Create ducklake-pgclient-layer.zip staging pg_dump + pg_restore 16 + libpq.so under /opt/bin + /opt/lib.

    The Lambda runtime expects the binaries at /opt/bin/{pg_dump,pg_restore} with
    LD_LIBRARY_PATH=/opt/lib so libpq.so resolves at invocation.

    Binary source: AL2023/x86_64 pg_dump + pg_restore 16 + libpq.so vendored to S3
    (s3://<data-lake-bucket>/ducklake-pgclient/{pg_dump16,pg_restore16,libpq.so.5}) by the operator.
    Fetched here at build time; fails closed if the S3 objects are absent (a version mismatch
    at deploy time is better than one at runtime).

    After staging, asserts `./opt/bin/pg_dump --version` and `./opt/bin/pg_restore --version`
    output contains PG major version 16 to catch version drift before the layer is uploaded
    (fail-closed guard). pg_restore is re-added solely for the Decision 88/107 DR
    restore-drill path (action_restore_drill); the Decision 100 clone-rehearsal
    (action_clone_catalog) stays on Neon native branching and does not use it.
    """
    opt_bin = temp_dir / "pgclient" / "bin"
    opt_lib = temp_dir / "pgclient" / "lib"
    opt_bin.mkdir(parents=True)
    opt_lib.mkdir(parents=True)

    if bucket is None:
        print("  pgclient layer: no bucket specified -- skipping S3 fetch (local dev mode)")
    else:
        # Single vendored bundle: bin/pg_dump + lib/<libpq + full transitive .so closure>
        # (ldap/lber/sasl/krb5 family/com_err/keyutils/libevent/libselinux/pcre2). The common
        # libs (libcrypto/libssl/libz/libzstd/liblz4) are provided by the AL2023 Lambda base and
        # deliberately NOT bundled, to avoid overriding the runtime's crypto on the global lib path.
        bundle_name = "pgclient-bundle.tar.gz"
        print(f"  pgclient: fetching {bundle_name} from s3://{bucket}/{DUCKLAKE_PGCLIENT_S3_PREFIX}/...")
        raw = _try_s3_pgclient(bucket, bundle_name, profile, region)
        if raw is None:
            print(
                f"  ERROR: {bundle_name} not found in s3://{bucket}/{DUCKLAKE_PGCLIENT_S3_PREFIX}/. "
                "Seed it first: a gzip tarball with bin/{pg_dump,pg_restore} + lib/<libpq.so.5 + its "
                "transitive shared-library closure>, built from RHEL9/AL2023-ABI (glibc 2.34) RPMs. "
                "See the catalog-DR runbook (Section 4) for the closure-build procedure.",
                file=sys.stderr,
            )
            sys.exit(1)

        import io as _io  # noqa: PLC0415
        import tarfile as _tarfile  # noqa: PLC0415

        n_files = 0
        with _tarfile.open(fileobj=_io.BytesIO(raw), mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not (member.name.startswith("bin/") or member.name.startswith("lib/")):
                    continue
                target = temp_dir / "pgclient" / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                target.write_bytes(extracted.read())
                target.chmod(0o755)
                n_files += 1

        pg_dump_bin = opt_bin / "pg_dump"
        if not pg_dump_bin.exists():
            print(f"  ERROR: {bundle_name} did not contain bin/pg_dump", file=sys.stderr)
            sys.exit(1)

        # Fail-closed version assert: pg_dump --version must report PG major 16, with the bundled
        # libs on the loader path (proves the closure links before the layer ships).
        version_env = {**os.environ, "LD_LIBRARY_PATH": str(opt_lib)}
        version_result = subprocess.run(
            [str(pg_dump_bin), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=version_env,
        )
        if version_result.returncode != 0 or f"pg_dump (PostgreSQL) {PINNED_PG_MAJOR}" not in version_result.stdout:
            actual = version_result.stdout.strip() or version_result.stderr.strip()
            print(
                f"ERROR: pg_dump version assertion failed. Expected PG{PINNED_PG_MAJOR}, got: {actual!r}. "
                "Re-seed the S3 bundle with a PG16 build + complete lib closure.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  OK pg_dump --version reports PG{PINNED_PG_MAJOR} ({n_files} bundled files)")

        # Fail-closed pg_restore existence + version assert, symmetric to the pg_dump guard above.
        # Re-added solely for the Decision 88/107 DR restore-drill path (action_restore_drill);
        # the Decision 100 clone-rehearsal (action_clone_catalog) stays on Neon native branching.
        pg_restore_bin = opt_bin / "pg_restore"
        if not pg_restore_bin.exists():
            print(f"  ERROR: {bundle_name} did not contain bin/pg_restore", file=sys.stderr)
            sys.exit(1)

        restore_version_result = subprocess.run(
            [str(pg_restore_bin), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=version_env,
        )
        if (
            restore_version_result.returncode != 0
            or f"pg_restore (PostgreSQL) {PINNED_PG_MAJOR}" not in restore_version_result.stdout
        ):
            actual = restore_version_result.stdout.strip() or restore_version_result.stderr.strip()
            print(
                f"ERROR: pg_restore version assertion failed. Expected PG{PINNED_PG_MAJOR}, got: {actual!r}. "
                "Re-seed the S3 bundle with a PG16 build + complete lib closure.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  OK pg_restore --version reports PG{PINNED_PG_MAJOR}")

    layer_root = temp_dir / "pgclient"
    zip_path = OUTPUT_DIR / "ducklake-pgclient-layer.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(layer_root.rglob("*")):
            if f.is_file() or f.is_symlink():
                arcname = str(f.relative_to(layer_root))
                if f.is_symlink():
                    info = zipfile.ZipInfo(arcname, date_time=_FIXED_ZIP_DATETIME)
                    info.create_system = 3  # Unix
                    info.external_attr = 0o120755 << 16  # symlink type
                    zf.writestr(info, str(f.resolve().name))
                else:
                    zf.writestr(_deterministic_zipinfo(arcname, executable="bin/" in arcname), f.read_bytes())
    return zip_path


def publish_canary_layers(*, bucket: str, profile: str = "agent_platform", region: str = "eu-west-2") -> dict[str, str]:
    """Publish the three DuckLake layer zips (already in S3) as new aws_lambda layer versions.

    Calls ``aws lambda publish-layer-version`` for each of the three DuckLake layers (deps, extensions,
    pgclient) using the S3 zips that ``--ducklake-only`` already uploaded. Prints JSON mapping layer
    name -> version ARN for the canary orchestrator to consume.

    Layer zips must already be in S3 (run ``--ducklake-only`` first). Fails closed if any publish
    fails. Returns the same ARN dict.
    """
    import json as _json  # noqa: PLC0415

    arns: dict[str, str] = {}
    for layer_name in _build_ducklake_layer_names():
        s3_key = f"lambda-packages/{layer_name}.zip"
        result = subprocess.run(
            [
                "aws",
                "lambda",
                "publish-layer-version",
                "--layer-name",
                layer_name,
                "--content",
                f"S3Bucket={bucket},S3Key={s3_key}",
                "--region",
                region,
                "--profile",
                profile,
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            print(
                f"ERROR: failed to publish layer {layer_name}: {result.stderr.strip()[:500]}",
                file=sys.stderr,
            )
            sys.exit(1)
        data = _json.loads(result.stdout)
        arn = data["LayerVersionArn"]
        arns[layer_name] = arn
        print(f"  OK {layer_name}: {arn}")
    print(_json.dumps(arns))
    return arns


def upload_to_s3(zip_path: Path, bucket: str, profile: str, region: str) -> None:
    """Upload package to S3."""
    s3_key = f"lambda-packages/{zip_path.name}"
    subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            str(zip_path),
            f"s3://{bucket}/{s3_key}",
            "--region",
            region,
            *_aws_profile_args(profile),
        ],
        check=True,
    )


def update_lambda_functions(bucket: str, profile: str, region: str, *, only_ducklake: bool = False) -> None:
    """Update Lambda function code to point at the latest S3 ZIPs.

    Uses ``aws lambda update-function-code`` with --s3-bucket and
    --s3-key.  Dispatcher and findings-processor use the full
    ``data-pipeline.zip``.  The ops_compaction Lambda uses the minimal
    ``ops-compaction.zip`` (no pip dependencies) to stay under the 262 MB
    combined-with-layers size limit imposed by the attached AWSSDKPandas layer.

    ``only_ducklake`` scopes the deploy to the two DuckLake functions (T2.17), leaving the prod
    functions untouched (Decision 79 affected-artifact hygiene).

    Ref: AWS CLI ``lambda update-function-code`` requires
    --function-name, --s3-bucket, --s3-key; optional --region and
    --profile.  Ref: ``docs/contracts/inference-provider.md`` for
    the inference-client packaging requirements.
    """
    if only_ducklake:
        # Scope the deploy to the two DuckLake functions ONLY: data-pipeline + ops-compaction are
        # NOT redeployed by a T2.17 deploy (Decision 79 affected-artifact hygiene).
        function_zip_map = dict(_build_ducklake_function_zip_keys())
    else:
        function_zip_map = {fn: "lambda-packages/data-pipeline.zip" for fn in _build_prod_function_names()}
        ops = _build_ops_compaction()
        function_zip_map[ops["function"]] = ops["zip_key"]

    for fn_name, s3_key in function_zip_map.items():
        print(f"  Updating {fn_name}...")
        result = subprocess.run(
            [
                "aws",
                "lambda",
                "update-function-code",
                "--function-name",
                fn_name,
                "--s3-bucket",
                bucket,
                "--s3-key",
                s3_key,
                "--region",
                region,
                *_aws_profile_args(profile),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"  ERROR: Failed to update {fn_name} (exit {result.returncode})")
            if result.stderr:
                print(f"  {result.stderr.strip()}")
            sys.exit(1)
        print(f"  OK {fn_name} updated")


def resolve_bucket(profile: str) -> str:
    """Resolve S3 bucket from Terraform output, falling back to default.

    Falls back to the well-known data-lake bucket when terraform is unavailable (e.g. a CC-web
    container without the terraform binary) or the output is empty.
    """
    try:
        result = subprocess.run(
            ["terraform", "-chdir=terraform", "output", "-raw", "s3_formulas_discovery_bucket"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        )
    except FileNotFoundError:
        return "agent-platform-data-lake"
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "agent-platform-data-lake"


def validate_bucket_exists(bucket: str, profile: str, region: str) -> bool:
    """Validate that S3 bucket exists.

    Args:
        bucket: S3 bucket name
        profile: AWS CLI profile
        region: AWS region

    Returns:
        True if bucket exists, False otherwise
    """
    result = subprocess.run(
        [
            "aws",
            "s3api",
            "head-bucket",
            "--bucket",
            bucket,
            "--region",
            region,
            *_aws_profile_args(profile),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode == 0


def _run_prod_build(args: argparse.Namespace) -> None:
    """Build (+optionally upload/deploy) the data-pipeline + ops-compaction prod artifacts."""
    with tempfile.TemporaryDirectory(prefix="lambda-build-") as tmp:
        temp_dir = Path(tmp)

        print("[1/4] Building application code package (data-pipeline, manifest-driven)...")
        app_zip = build_app_package(temp_dir)
        print(f"  OK data-pipeline.zip ({round(app_zip.stat().st_size / 1024 / 1024, 2)} MB)")

        print("[1b/4] Building ops-compaction package (no pip dependencies, manifest-driven)...")
        ops_zip = build_ops_compaction_package(temp_dir)
        print(f"  OK ops-compaction.zip ({round(ops_zip.stat().st_size / 1024 / 1024, 2)} MB)")

        print("[2/4] Installing dependencies for Lambda layer...")
        layer_zip = build_deps_layer(temp_dir)
        layer_size = round(layer_zip.stat().st_size / 1024 / 1024, 2)
        print(f"  OK data-pipeline-deps-layer.zip ({layer_size} MB)")
        if layer_zip.stat().st_size > LAMBDA_SIZE_WARN_BYTES:
            print(f"  WARN Layer size {layer_size} MB exceeds 250 MB. Approaching the 262 MB hard limit.")

        for artifact in (app_zip, ops_zip, layer_zip):
            assert_within_size_limit(artifact)

        if not args.skip_upload:
            bucket = args.bucket or resolve_bucket(args.profile)
            if not validate_bucket_exists(bucket, args.profile, args.region):
                print(f"ERROR: S3 bucket does not exist: s3://{bucket}")
                sys.exit(1)
            print(f"[3/4] Uploading to s3://{bucket}/lambda-packages/...")
            for artifact in (app_zip, ops_zip, layer_zip):
                upload_to_s3(artifact, bucket, args.profile, args.region)
            print("  OK Uploaded to S3")
            if args.deploy:
                print("[3b/4] Updating Lambda function code...")
                update_lambda_functions(bucket, args.profile, args.region)
                print("  OK Lambda functions updated")
        else:
            print("[3/4] Skipping S3 upload (--skip-upload)")
        print("[4/4] Build complete.")


def _aws_profile_args(profile: str) -> list[str]:
    """Return the `--profile <name>` argv tokens, or [] when profile is empty.

    GitHub-hosted OIDC runners resolve AWS credentials from the environment (no named profile);
    passing `--profile ""` to the aws CLI is an error, so an empty profile must omit the flag
    entirely rather than pass it empty.
    """
    return ["--profile", profile] if profile else []


def _resolve_ducklake_profile(profile: str) -> str:
    """Map the generic default profile to the personal-account profile for DuckLake.

    The ducklake_writer/reader functions, layers, and S3 bucket all live in the PERSONAL account
    (agent_platform). The generic `company-aws-profile` default cannot reach them (and a same-named
    function elsewhere would be a deploy hazard), so the ducklake path resolves it to agent_platform.
    An explicitly-passed non-default profile is honoured unchanged.
    """
    return "agent_platform" if profile == "company-aws-profile" else profile


def _run_ducklake_build(args: argparse.Namespace) -> None:
    """Build (+optionally upload/deploy) ONLY the T2.17/T2.18 DuckLake artifacts (Decision 79 hygiene)."""
    args.profile = _resolve_ducklake_profile(args.profile)
    bucket = args.bucket or resolve_bucket(args.profile)
    with tempfile.TemporaryDirectory(prefix="ducklake-build-") as tmp:
        temp_dir = Path(tmp)

        print("[1/4] Building ducklake function zips (writer + reader + maintenance + catalog-dr, manifest-driven)...")
        writer_zip = build_ducklake_function_package(temp_dir, "ducklake_writer", "ducklake-writer.zip")
        reader_zip = build_ducklake_function_package(temp_dir, "ducklake_reader", "ducklake-reader.zip")
        maintenance_zip = build_ducklake_function_package(temp_dir, "ducklake_maintenance", "ducklake-maintenance.zip")
        catalog_dr_zip = build_ducklake_function_package(temp_dir, "ducklake_catalog_dr", "ducklake-catalog-dr.zip")
        print(f"  OK ducklake-writer.zip ({round(writer_zip.stat().st_size / 1024 / 1024, 2)} MB)")
        print(f"  OK ducklake-reader.zip ({round(reader_zip.stat().st_size / 1024 / 1024, 2)} MB)")
        print(f"  OK ducklake-maintenance.zip ({round(maintenance_zip.stat().st_size / 1024 / 1024, 2)} MB)")
        print(f"  OK ducklake-catalog-dr.zip ({round(catalog_dr_zip.stat().st_size / 1024 / 1024, 2)} MB)")

        print("[2/4] Building ducklake-deps + ducklake-extensions + ducklake-pgclient layers...")
        deps_layer = build_ducklake_deps_layer(temp_dir)
        ext_layer = build_ducklake_extensions_layer(temp_dir, bucket=bucket, profile=args.profile, region=args.region)
        pgclient_layer = build_pgclient_layer(temp_dir, bucket=bucket, profile=args.profile, region=args.region)
        print(f"  OK ducklake-deps-layer.zip ({round(deps_layer.stat().st_size / 1024 / 1024, 2)} MB)")
        print(f"  OK ducklake-extensions-layer.zip ({round(ext_layer.stat().st_size / 1024 / 1024, 2)} MB)")
        print(f"  OK ducklake-pgclient-layer.zip ({round(pgclient_layer.stat().st_size / 1024 / 1024, 2)} MB)")

        artifacts = (writer_zip, reader_zip, maintenance_zip, catalog_dr_zip, deps_layer, ext_layer, pgclient_layer)
        for artifact in artifacts:
            assert_within_size_limit(artifact)

        if not args.skip_upload:
            if not validate_bucket_exists(bucket, args.profile, args.region):
                print(f"ERROR: S3 bucket does not exist: s3://{bucket}")
                sys.exit(1)
            print(f"[3/4] Uploading to s3://{bucket}/lambda-packages/...")
            for artifact in artifacts:
                upload_to_s3(artifact, bucket, args.profile, args.region)
            print("  OK Uploaded to S3")
            if args.deploy:
                print("[3b/4] Updating DuckLake Lambda function code (writer + reader + maintenance + catalog-dr)...")
                update_lambda_functions(bucket, args.profile, args.region, only_ducklake=True)
                print("  OK DuckLake Lambda functions updated")
        else:
            print("[3/4] Skipping S3 upload (--skip-upload)")
        print("[4/4] DuckLake build complete.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Lambda deployment packages")
    parser.add_argument("--skip-upload", action="store_true", help="Build zips only, skip S3 upload")
    parser.add_argument("--bucket", default="", help="S3 bucket name (default: from terraform output)")
    parser.add_argument("--profile", default="company-aws-profile", help="AWS CLI profile")
    parser.add_argument("--region", default="eu-west-2", help="AWS region")
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="After S3 upload, update Lambda function code",
    )
    parser.add_argument(
        "--ducklake-only",
        action="store_true",
        help="Build/upload/deploy ONLY the DuckLake artifacts (4 zips + 3 layers + 4 "
        "functions: writer, reader, maintenance, catalog-dr); leave data-pipeline/ops-compaction untouched (Decision 79).",
    )
    parser.add_argument(
        "--list-bundle",
        metavar="ARTIFACT_SLUG",
        default=None,
        help="Stage a manifest-driven bundle and emit its static file list (skip_pip=True). "
        "ARTIFACT_SLUG is the src/lambdas/<name>/ directory name (e.g. data-pipeline).",
    )
    parser.add_argument(
        "--ducklake-publish-canary-layers",
        action="store_true",
        dest="ducklake_publish_canary_layers",
        help="Publish the three DuckLake layer zips (already uploaded to S3 by --ducklake-only) as new "
        "aws_lambda layer versions. Prints JSON mapping layer name -> version ARN for the canary "
        "orchestrator (OQ.12 clone-rehearsal). Run after --ducklake-only to get candidate layer ARNs.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.list_bundle:
        list_bundle(args.list_bundle)
        return

    if args.ducklake_publish_canary_layers:
        args.profile = _resolve_ducklake_profile(args.profile)
        bucket = args.bucket or resolve_bucket(args.profile)
        publish_canary_layers(bucket=bucket, profile=args.profile, region=args.region)
        return

    print("Lambda Package Builder (Manifest-Driven, CD.24)")
    print()
    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.ducklake_only:
        _run_ducklake_build(args)
    else:
        _run_prod_build(args)

    print()
    print("Build Complete")
    print("  Artifacts in: lambda-packages/")
    print("  Next: terraform apply")


if __name__ == "__main__":
    main()
