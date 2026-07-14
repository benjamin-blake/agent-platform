#!/usr/bin/env python3
"""AWS deploy/publish + bucket resolution for the Lambda build/deploy tool (Decision 104 pattern).

Holds upload_to_s3, update_lambda_functions, resolve_bucket, validate_bucket_exists,
publish_canary_layers, and _resolve_ducklake_profile. Imports only the accessors and constants it
needs from scripts.build_lambda_config (no import of build_lambda_packaging -- no cycle). See
scripts/build_lambda.py for the CLI facade that re-exports this module's public and
test-patched symbols.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.build_lambda_config import (
    ROOT,
    _aws_profile_args,
    _build_ducklake_function_zip_keys,
    _build_ducklake_layer_names,
    _build_ops_compaction,
    _build_prod_function_names,
)

_DEPLOY_RECORD_BUCKET = "agent-platform-data-lake"


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

    ``only_ducklake`` scopes the deploy to the four DuckLake functions (T2.17/T2.18), leaving the
    prod functions untouched (Decision 79 affected-artifact hygiene). Both paths capture
    CodeSha256 from each successful update and write a per-function deployment record (see
    ``_write_ducklake_deploy_record`` / ``read_deploy_record``): ``deploy-records/ducklake/*``
    for the DuckLake path, ``deploy-records/prod/*`` for the prod path (T2.43).

    Ref: AWS CLI ``lambda update-function-code`` requires
    --function-name, --s3-bucket, --s3-key; optional --region and
    --profile.  Ref: ``docs/contracts/inference-provider.yaml`` for
    the inference-client packaging requirements.
    """
    if only_ducklake:
        # Scope the deploy to the four DuckLake functions ONLY: data-pipeline + ops-compaction are
        # NOT redeployed by a T2.17/T2.18 deploy (Decision 79 affected-artifact hygiene).
        function_zip_map = dict(_build_ducklake_function_zip_keys())
        channel = "ducklake"
    else:
        function_zip_map = {fn: "lambda-packages/data-pipeline.zip" for fn in _build_prod_function_names()}
        ops = _build_ops_compaction()
        function_zip_map[ops["function"]] = ops["zip_key"]
        channel = "prod"

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
                "--output",
                "json",
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

        _write_ducklake_deploy_record(fn_name, result.stdout, bucket, profile, region, channel=channel)


def _write_ducklake_deploy_record(
    function: str,
    update_function_code_stdout: str,
    bucket: str,
    profile: str,
    region: str,
    channel: str = "ducklake",
) -> None:
    """Capture CodeSha256 from the update-function-code JSON response and write a deploy record.

    Writes ``deploy-records/<channel>/<function>.json``: ``{function, code_sha256,
    source_git_sha, deployed_at}``. ``channel`` defaults to ``"ducklake"`` (the T2.38 original
    caller); the prod class (T2.43) passes ``channel="prod"`` -- same schema, different S3
    prefix, generalising this function rather than duplicating it. ``source_git_sha`` reads
    ``os.environ.get("GITHUB_SHA")`` -- None-safe: a local break-glass path (``bin/venv-python -m
    scripts.build_lambda [--ducklake-only] --deploy``) has no ``GITHUB_SHA``, so the record
    carries ``source_git_sha: null`` rather than raising. Read back via ``read_deploy_record``
    (consumed by ``scripts.convergence_health.detect_ducklake_code_drift`` /
    ``detect_prod_code_drift``).
    """
    try:
        code_sha256 = json.loads(update_function_code_stdout)["CodeSha256"]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"  ERROR: could not parse CodeSha256 from update-function-code response for {function}: {exc}")
        sys.exit(1)

    record = {
        "function": function,
        "code_sha256": code_sha256,
        "source_git_sha": os.environ.get("GITHUB_SHA"),
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"deploy-records/{channel}/{function}.json"
    result = subprocess.run(
        [
            "aws",
            "s3",
            "cp",
            "-",
            f"s3://{bucket}/{key}",
            "--region",
            region,
            "--content-type",
            "application/json",
            *_aws_profile_args(profile),
        ],
        input=json.dumps(record),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(f"  ERROR: Failed to write deploy record for {function} (exit {result.returncode})")
        if result.stderr:
            print(f"  {result.stderr.strip()}")
        sys.exit(1)
    print(f"  OK deploy record written: {key}")


def read_deploy_record(
    function: str,
    s3_client: Any = None,
    bucket: str = _DEPLOY_RECORD_BUCKET,
    channel: str = "ducklake",
) -> Optional[dict[str, Any]]:
    """Read ``deploy-records/<channel>/<function>.json``. Returns None if the record is absent.

    ``channel`` defaults to ``"ducklake"`` (the T2.38 original caller); the prod class (T2.43)
    passes ``channel="prod"`` so ``scripts.convergence_health.detect_prod_code_drift`` can read
    its deploy records through the same generalised accessor. ``s3_client`` is injected for
    testability (a boto3-like client exposing ``get_object(Bucket, Key) -> {"Body": <stream>}``),
    mirroring ``scripts.convergence_health.read_convergence_record``. When None, a boto3 client is
    created lazily (never at import time, per the repo's import-safety rule).
    """
    if s3_client is None:
        import boto3  # noqa: PLC0415

        s3_client = boto3.client("s3")

    key = f"deploy-records/{channel}/{function}.json"
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc) + type(exc).__name__
        if any(marker in exc_str for marker in ("NoSuchKey", "404", "NoSuchBucket")):
            return None
        raise


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


def _resolve_ducklake_profile(profile: str) -> str:
    """Map the generic default profile to the personal-account profile for DuckLake.

    The ducklake_writer/reader functions, layers, and S3 bucket all live in the PERSONAL account
    (agent_platform). The generic `company-aws-profile` default cannot reach them (and a same-named
    function elsewhere would be a deploy hazard), so the ducklake path resolves it to agent_platform.
    An explicitly-passed non-default profile is honoured unchanged.
    """
    return "agent_platform" if profile == "company-aws-profile" else profile
