#!/usr/bin/env python3
"""Build Lambda deployment packages for the data pipeline (no Docker required).

Creates two zip artifacts:
  1. data-pipeline.zip             -- application code (manifest-driven)
  2. ops-compaction.zip            -- minimal ops compaction handler
  3. data-pipeline-deps-layer.zip  -- dependencies layer (yfinance, pyyaml, etc.)

Both app zips are built from src/lambdas/<name>/manifest.yaml rather than
whole-src/whole-config copytrees (Decision 79 / CD.24).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "lambda-packages"

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

# Retained for backward compatibility with external callers and tests.
_LAMBDA_SCRIPTS = [
    "__init__.py",
    "aws_profile.py",
    "bedrock_client.py",
    "copilot_sdk_client.py",
    "copilot_wrapper.py",
    "github_models_client.py",
    "llm_client.py",
    "llm_utils.py",
    "ops_writer.py",
    "run_scheduled_agent.py",
    "s3_log_store.py",
    "telemetry_schemas.py",
    "tool_runtime.py",
]

_COPILOT_SDK_PACKAGE = "github-copilot-sdk==0.2.2"

_LAMBDA_FUNCTION_NAMES = [
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
]

_OPS_COMPACTION_FUNCTION_NAME = "agent-platform-ops-compaction"
_OPS_COMPACTION_ZIP_KEY = "lambda-packages/ops-compaction.zip"


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


def _zip_staged_dir(stage_dir: Path, zip_path: Path) -> Path:
    """Write all files in stage_dir into zip_path (ZIP_DEFLATED)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in stage_dir.rglob("*"):
            if f.is_file():
                arcname = str(f.relative_to(stage_dir))
                info = zipfile.ZipInfo(arcname)
                if "copilot/bin/" in arcname.replace("\\", "/") and not arcname.endswith(".py"):
                    info.external_attr = 0o755 << 16  # Unix executable bit
                else:
                    info.external_attr = 0o644 << 16
                zf.writestr(info, f.read_bytes())
    return zip_path


def build_app_package(temp_dir: Path) -> Path:
    """Create data-pipeline.zip from the data-pipeline manifest (manifest-driven, CD.24).

    Retired whole-src and whole-config tree bundling in favour of explicit manifest declarations.
    All bundled files are explicitly declared in src/lambdas/data-pipeline/manifest.yaml.
    """
    from scripts.lambda_manifest import load, stage_bundle  # noqa: PLC0415

    manifest = load(ROOT / "src" / "lambdas" / "data-pipeline" / "manifest.yaml")
    app_dir = temp_dir / "app"
    app_dir.mkdir(parents=True)

    print("  Installing Copilot SDK into app package...")
    stage_bundle(manifest, app_dir, skip_pip=False)

    zip_path = OUTPUT_DIR / "data-pipeline.zip"
    return _zip_staged_dir(app_dir, zip_path)


def build_ops_compaction_package(temp_dir: Path) -> Path:
    """Create ops-compaction.zip from the ops-compaction manifest (manifest-driven, CD.24).

    Minimal zip -- no Copilot SDK to stay under the 262 MB Lambda+AWSSDKPandas limit.
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
            "--profile",
            profile,
        ],
        check=True,
    )


def update_lambda_functions(bucket: str, profile: str, region: str) -> None:
    """Update Lambda function code to point at the latest S3 ZIPs.

    Uses ``aws lambda update-function-code`` with --s3-bucket and
    --s3-key.  Dispatcher and findings-processor use the full
    ``data-pipeline.zip`` (which includes the Copilot SDK).  The
    ops_compaction Lambda uses the minimal ``ops-compaction.zip``
    (no Copilot SDK) to stay under the 262 MB combined-with-layers
    size limit imposed by the attached AWSSDKPandas layer.

    Ref: AWS CLI ``lambda update-function-code`` requires
    --function-name, --s3-bucket, --s3-key; optional --region and
    --profile.  Ref: ``docs/contracts/inference-provider.md`` for
    the packaging requirement that ``bedrock_client.py`` be bundled.
    """
    function_zip_map = {fn: "lambda-packages/data-pipeline.zip" for fn in _LAMBDA_FUNCTION_NAMES}
    function_zip_map[_OPS_COMPACTION_FUNCTION_NAME] = _OPS_COMPACTION_ZIP_KEY

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
                "--profile",
                profile,
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
    """Resolve S3 bucket from Terraform output, falling back to default."""
    result = subprocess.run(
        ["terraform", "-chdir=terraform", "output", "-raw", "s3_formulas_discovery_bucket"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
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
            "--profile",
            profile,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.returncode == 0


def main() -> None:
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
        "--list-bundle",
        metavar="ARTIFACT_SLUG",
        default=None,
        help="Stage a manifest-driven bundle and emit its static file list (skip_pip=True). "
        "ARTIFACT_SLUG is the src/lambdas/<name>/ directory name (e.g. data-pipeline).",
    )
    args = parser.parse_args()

    if args.list_bundle:
        list_bundle(args.list_bundle)
        return

    print("Lambda Package Builder (Manifest-Driven, CD.24)")
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lambda-build-") as tmp:
        temp_dir = Path(tmp)

        print("[1/4] Building application code package (data-pipeline, manifest-driven)...")
        app_zip = build_app_package(temp_dir)
        app_size = round(app_zip.stat().st_size / 1024 / 1024, 2)
        print(f"  OK data-pipeline.zip ({app_size} MB)")

        print("[1b/4] Building ops-compaction package (no Copilot SDK, manifest-driven)...")
        ops_zip = build_ops_compaction_package(temp_dir)
        ops_size = round(ops_zip.stat().st_size / 1024 / 1024, 2)
        print(f"  OK ops-compaction.zip ({ops_size} MB)")

        print("[2/4] Installing dependencies for Lambda layer...")
        layer_zip = build_deps_layer(temp_dir)
        layer_size = round(layer_zip.stat().st_size / 1024 / 1024, 2)
        print(f"  OK data-pipeline-deps-layer.zip ({layer_size} MB)")

        if layer_size > 250:
            print(f"  WARN Layer size {layer_size} MB exceeds 250 MB limit. Consider splitting.")

        if not args.skip_upload:
            bucket = args.bucket or resolve_bucket(args.profile)

            if not validate_bucket_exists(bucket, args.profile, args.region):
                print(f"ERROR: S3 bucket does not exist: s3://{bucket}")
                sys.exit(1)

            print(f"[3/4] Uploading to s3://{bucket}/lambda-packages/...")
            upload_to_s3(app_zip, bucket, args.profile, args.region)
            upload_to_s3(ops_zip, bucket, args.profile, args.region)
            upload_to_s3(layer_zip, bucket, args.profile, args.region)
            print("  OK Uploaded to S3")

            if args.deploy:
                print("[3b/4] Updating Lambda function code...")
                update_lambda_functions(bucket, args.profile, args.region)
                print("  OK Lambda functions updated")
        else:
            print("[3/4] Skipping S3 upload (--skip-upload)")

        print("[4/4] Build complete.")

    print()
    print("Build Complete")
    print("  Artifacts in: lambda-packages/")
    print(f"    data-pipeline.zip           ({app_size} MB)")
    print(f"    ops-compaction.zip           ({ops_size} MB)")
    print(f"    data-pipeline-deps-layer.zip ({layer_size} MB)")
    print("  Next: terraform apply")


if __name__ == "__main__":
    main()
