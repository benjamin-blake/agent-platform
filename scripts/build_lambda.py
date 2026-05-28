#!/usr/bin/env python3
"""Build Lambda deployment packages for the data pipeline (no Docker required).

Creates two zip artifacts:
  1. data-pipeline.zip             -- application code (src/ + config/)
  2. data-pipeline-deps-layer.zip  -- dependencies layer (yfinance, pyyaml, etc.)

Both zips are placed in ./lambda-packages/ and then uploaded to S3.
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


_LAMBDA_SCRIPTS = [
    "__init__.py",
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

# Functions that use the full data-pipeline.zip
_LAMBDA_FUNCTION_NAMES = [
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
]

# ops_compaction uses a separate minimal zip (no Copilot SDK) to stay
# under the 262 MB Lambda limit when combined with the AWSSDKPandas layer.
_OPS_COMPACTION_FUNCTION_NAME = "agent-platform-ops-compaction"
_OPS_COMPACTION_ZIP_KEY = "lambda-packages/ops-compaction.zip"


def build_app_package(temp_dir: Path) -> Path:
    """Create data-pipeline.zip with src/, config/, scheduled-agent scripts, and .github assets."""
    app_dir = temp_dir / "app"
    app_dir.mkdir(parents=True)
    shutil.copytree(ROOT / "src", app_dir / "src")
    config_dest = app_dir / "config"
    config_dest.mkdir(parents=True)
    if (ROOT / "config" / "config.yaml").exists():
        shutil.copy2(ROOT / "config" / "config.yaml", config_dest / "config.yaml")
    if (ROOT / "config" / "config.yaml.example").exists():
        shutil.copy2(ROOT / "config" / "config.yaml.example", config_dest / "config.yaml.example")
    lambda_subtree_src = ROOT / "config" / "lambda" / "data-pipeline"
    if lambda_subtree_src.exists():
        shutil.copytree(lambda_subtree_src, config_dest / "lambda" / "data-pipeline")

    # Include scripts required by scheduled-agent Lambda handlers.
    scripts_dest = app_dir / "scripts"
    scripts_dest.mkdir(parents=True)
    for name in _LAMBDA_SCRIPTS:
        src_file = ROOT / "scripts" / name
        if src_file.exists():
            shutil.copy2(src_file, scripts_dest / name)

    # Include schedule.yaml manifest and scheduled prompts used by Lambda handlers.
    schedule_dest = app_dir / ".github" / "agents"
    schedule_dest.mkdir(parents=True)
    schedule_src = ROOT / ".github" / "agents" / "schedule.yaml"
    if schedule_src.exists():
        shutil.copy2(schedule_src, schedule_dest / "schedule.yaml")

    prompts_src = ROOT / ".github" / "prompts" / "scheduled"
    prompts_dest = app_dir / ".github" / "prompts" / "scheduled"
    if prompts_src.exists():
        shutil.copytree(prompts_src, prompts_dest)

    # Include both roadmap files so scheduled agents can read them from /var/task.
    docs_dest = app_dir / "docs"
    docs_dest.mkdir(parents=True)
    for roadmap_name in ("ROADMAP-PRODUCT.md", "ROADMAP-PLATFORM.yaml"):
        roadmap_src = ROOT / "docs" / roadmap_name
        if roadmap_src.exists():
            shutil.copy2(roadmap_src, docs_dest / roadmap_name)

    # Install Copilot SDK into the app package (includes bundled CLI binary).
    print("  Installing Copilot SDK into app package...")
    sdk_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            _COPILOT_SDK_PACKAGE,
            "--target",
            str(app_dir),
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
    if sdk_result.returncode != 0:
        print(f"ERROR: Copilot SDK installation failed (exit {sdk_result.returncode})")
        sys.exit(1)

    zip_path = OUTPUT_DIR / "data-pipeline.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in app_dir.rglob("*"):
            if f.is_file():
                arcname = str(f.relative_to(app_dir))
                info = zipfile.ZipInfo(arcname)
                if "copilot/bin/" in arcname.replace("\\", "/") and not arcname.endswith(".py"):
                    info.external_attr = 0o755 << 16  # Unix executable
                else:
                    info.external_attr = 0o644 << 16
                zf.writestr(info, f.read_bytes())
    return zip_path


def build_ops_compaction_package(temp_dir: Path) -> Path:
    """Create ops-compaction.zip with src/ + scripts/ only (no Copilot SDK).

    The ops_compaction Lambda has the AWSSDKPandas layer attached which is
    ~128 MB unzipped. Including the full data-pipeline.zip (which embeds the
    Copilot SDK binary at ~120 MB) would push the combined unzipped size past
    the 262 MB Lambda limit. This minimal zip contains only the application
    source and the ops-related scripts needed by ops_compaction_handler.py.
    """
    app_dir = temp_dir / "ops-app"
    app_dir.mkdir(parents=True)
    shutil.copytree(ROOT / "src", app_dir / "src")
    config_dest = app_dir / "config"
    config_dest.mkdir(parents=True)
    if (ROOT / "config" / "config.yaml").exists():
        shutil.copy2(ROOT / "config" / "config.yaml", config_dest / "config.yaml")
    if (ROOT / "config" / "config.yaml.example").exists():
        shutil.copy2(ROOT / "config" / "config.yaml.example", config_dest / "config.yaml.example")
    lambda_subtree_src = ROOT / "config" / "lambda" / "ops-compaction"
    if lambda_subtree_src.exists():
        shutil.copytree(lambda_subtree_src, config_dest / "lambda" / "ops-compaction")

    scripts_dest = app_dir / "scripts"
    scripts_dest.mkdir(parents=True)
    for name in _LAMBDA_SCRIPTS:
        src_file = ROOT / "scripts" / name
        if src_file.exists():
            shutil.copy2(src_file, scripts_dest / name)

    zip_path = OUTPUT_DIR / "ops-compaction.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in app_dir.rglob("*"):
            if f.is_file():
                arcname = str(f.relative_to(app_dir))
                info = zipfile.ZipInfo(arcname)
                info.external_attr = 0o644 << 16
                zf.writestr(info, f.read_bytes())
    return zip_path


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

    # Clean up unnecessary files to reduce layer size
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
    # Map each function to its deployment zip key.
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
    return "bblake-platform-data-lake"


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
    args = parser.parse_args()

    print("Lambda Package Builder (No Docker Required)")
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lambda-build-") as tmp:
        temp_dir = Path(tmp)

        print("[1/4] Building application code package...")
        app_zip = build_app_package(temp_dir)
        app_size = round(app_zip.stat().st_size / 1024 / 1024, 2)
        print(f"  OK data-pipeline.zip ({app_size} MB)")

        print("[1b/4] Building ops-compaction package (no Copilot SDK)...")
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

            # Validate bucket exists before attempting upload
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
