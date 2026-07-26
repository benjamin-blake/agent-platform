#!/usr/bin/env python3
"""T2.42 c4 (rec-2659) + DEP-08: tested DuckLake build byte-identity-assert + dual-write upload.

Extracted from the "Build DuckLake lambda packages" step duplicated 5x across
terraform-apply-sandbox.yml (apply-sandbox, speculative-plan, gated-apply) and reconcile.yml
(apply-reconcile, gated-apply-reconcile). The .github/actions/build-ducklake-artifacts composite
action is the caller for its 'assert' and 'skip-assert' modes: it runs `python -m
scripts.build_lambda --ducklake-only --skip-upload` to produce the seven zips under
lambda-packages/, then calls assert_and_upload() below to byte-check (push path only) and
dual-write them to S3. The action's third mode, 'upload-only' (the PR speculative-plan job's
first-upload path, which also builds an eighth artifact -- ducklake-maintenance-smoke.zip -- not
in DUCKLAKE_ARTIFACT_NAMES below), does not call this module at all: it runs `build_lambda
--ducklake-only` WITHOUT --skip-upload and lets build_lambda's own internal upload_to_s3 (already
a fixed+per-sha dual-write, scripts/build_lambda_deploy.py) handle the upload directly.

event_name convention (matches the original inline bash's `if [ "${{ github.event_name }}" =
"push" ]` gate): pass the literal string "push" to run the byte-identity assert before uploading
-- the apply-time path re-verifying the freshly rebuilt zips are byte-identical to what the
originating PR's speculative-plan job uploaded (Decision 77 no-TOCTOU: the applied layer content
must not skew from the reviewed plan). Pass any other value (e.g. "workflow_dispatch",
"pull_request") to skip the assert and upload directly -- the PR speculative-plan job populating
S3 for the first time, or a fresh workflow_dispatch plan with no prior PR artifact to compare
against. The calling composite action's own `mode: assert|skip-assert` input decides which string
to pass here -- independent of the workflow's REAL triggering github.event_name (Reconcile is
workflow_dispatch-triggered but always wants assert semantics, matching the push-path parity its
rebuild-from-the-red-commit intentionally mirrors).

Decision 154 / rec-2862: the composite action's fourth mode, 'fetch', calls fetch_reviewed()
below instead of rebuilding at all. Every human-gated apply path (gated-apply, apply-reconcile,
gated-apply-reconcile) sits behind an unbounded approval wait; rebuilding after that wait can
resolve a dependency to a version published during the wait, producing bytes that were never
reviewed (the exact rec-2862 TOCTOU). fetch_reviewed() instead downloads the already-reviewed
per-sha artifacts and server-side copies them onto the fixed key -- the push-path apply-sandbox
job keeps mode='assert' as the reproducibility canary, since it runs immediately after the
rebuild with no approval-wait exposure window.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

DUCKLAKE_ARTIFACT_NAMES: tuple[str, ...] = (
    "ducklake-writer.zip",
    "ducklake-reader.zip",
    "ducklake-maintenance.zip",
    "ducklake-catalog-dr.zip",
    "ducklake-deps-layer.zip",
    "ducklake-extensions-layer.zip",
    "ducklake-pgclient-layer.zip",
)


class DucklakeArtifactError(RuntimeError):
    """Fail-closed error: byte-mismatch or a missing per-sha reference object (Decision 77 no-TOCTOU)."""


def _md5_hex(data: bytes) -> str:
    """Content-identity digest (parity check, not a security digest) -- matches the original md5sum."""
    return hashlib.md5(data).hexdigest()


def build_ducklake_only(*, cwd: str | None = None) -> None:
    """Thin wrapper: `python -m scripts.build_lambda --ducklake-only --skip-upload ...`.

    The caller (the build-ducklake-artifacts composite action) is responsible for installing
    build_lambda's import-time deps first (this runner has no .venv -- CC-web-only convention).
    """
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.build_lambda",
            "--ducklake-only",
            "--skip-upload",
            "--profile",
            "",
            "--bucket",
            "agent-platform-data-lake",
        ],
        cwd=cwd,
        check=True,
    )


def assert_and_upload(
    names: list[str],
    artifact_sha: str,
    event_name: str,
    bucket: str,
    region: str = "eu-west-2",
    *,
    packages_dir: str | Path = "lambda-packages",
    s3_client: Any = None,
) -> None:
    """Byte-assert (push path only) then dual-write upload the built DuckLake zips.

    Raises DucklakeArtifactError (fail-closed) on a byte-mismatch or a missing per-sha reference
    object when event_name == "push" (see module docstring for the event_name convention).
    Upload always dual-writes BOTH the fixed key (lambda-packages/<name>, keeps terraform's
    static s3_key genuine-republish read fed) AND the per-sha key
    (lambda-packages/<artifact_sha>/<name>, overwrite-immune per PR-head-sha -- D1/rec-2755
    content-addressing, T2.42 c3 / DEP-03).

    s3_client is injected for testability (boto3.client("s3", region_name=region) when None) --
    mirrors the injection pattern in scripts/ci/reconcile_target.py.
    """
    if s3_client is None:
        import boto3  # noqa: PLC0415

        s3_client = boto3.client("s3", region_name=region)

    packages_root = Path(packages_dir)

    if event_name == "push":
        for name in names:
            local_path = packages_root / name
            local_md5 = _md5_hex(local_path.read_bytes())
            key = f"lambda-packages/{artifact_sha}/{name}"
            try:
                response = s3_client.get_object(Bucket=bucket, Key=key)
                remote_bytes = response["Body"].read()
            except Exception as exc:  # noqa: BLE001 -- any fetch failure fails closed (mirrors `! aws s3 cp`)
                raise DucklakeArtifactError(
                    f"DUCKLAKE_ZIP_MISMATCH {name}: no existing per-sha S3 object found at {key} "
                    f"(PR job did not upload it); failing closed (Decision 77 no-TOCTOU). Underlying: {exc}"
                ) from exc
            remote_md5 = _md5_hex(remote_bytes)
            if local_md5 != remote_md5:
                raise DucklakeArtifactError(
                    f"DUCKLAKE_ZIP_MISMATCH {name}: local={local_md5} remote={remote_md5}; applied layer "
                    "content would skew from the reviewed plan.bin. Failing closed (Decision 77 no-TOCTOU)."
                )
        print("DUCKLAKE_ZIP_IDEMPOTENT_OK: all seven rebuilt zips are byte-identical to the PR-uploaded per-sha artifacts.")

    for name in names:
        local_path = packages_root / name
        s3_client.upload_file(str(local_path), bucket, f"lambda-packages/{name}")
        s3_client.upload_file(str(local_path), bucket, f"lambda-packages/{artifact_sha}/{name}")
    print(f"Uploaded {len(names)} DuckLake artifact(s) to s3://{bucket}/lambda-packages/ (fixed + per-sha dual-write).")


def fetch_reviewed(
    names: list[str],
    artifact_sha: str,
    bucket: str,
    region: str = "eu-west-2",
    *,
    packages_dir: str | Path = "lambda-packages",
    s3_client: Any = None,
) -> None:
    """Download the reviewed per-sha artifacts and server-side copy each onto its fixed key.

    For a human-gated apply consuming an already-reviewed plan (gated-apply, apply-reconcile,
    gated-apply-reconcile), the artifact that must land is the one a reviewer looked at, not a
    fresh rebuild -- rebuilding invites the exact TOCTOU rec-2862 hit (a dependency resolving to a
    newer version between review and approval). This downloads
    lambda-packages/<artifact_sha>/<name> for every name into packages_dir, raising
    DucklakeArtifactError (fail-closed, Decision 77 no-TOCTOU) on any missing per-sha object
    BEFORE any copy is attempted -- mirrors assert_and_upload's all-or-nothing batch semantics
    (rec-2755 parity). Once every object is confirmed present, each per-sha object is
    server-side copy_object'd onto its fixed key (lambda-packages/<name>) -- the key terraform's
    static s3_key reads. Deliberately does NOT re-upload to the per-sha key: that key IS the
    immutable reviewed reference, and rewriting it would be a self-copy moving ~183 MB for no
    gain. Prints DUCKLAKE_FETCH_OK on success so a green convergence record can be attributed to
    this route (see the caller's write-convergence-record step).

    s3_client is injected for testability (boto3.client("s3", region_name=region) when None).
    """
    if s3_client is None:
        import boto3  # noqa: PLC0415

        s3_client = boto3.client("s3", region_name=region)

    packages_root = Path(packages_dir)
    packages_root.mkdir(parents=True, exist_ok=True)

    for name in names:
        key = f"lambda-packages/{artifact_sha}/{name}"
        local_path = packages_root / name
        try:
            s3_client.download_file(bucket, key, str(local_path))
        except Exception as exc:  # noqa: BLE001 -- any fetch failure fails closed (Decision 77 no-TOCTOU)
            raise DucklakeArtifactError(
                f"DUCKLAKE_FETCH_MISSING {name}: no reviewed per-sha S3 object found at {key}; "
                f"failing closed (Decision 77 no-TOCTOU). Underlying: {exc}"
            ) from exc

    for name in names:
        key = f"lambda-packages/{artifact_sha}/{name}"
        s3_client.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key}, Key=f"lambda-packages/{name}")

    print(
        f"DUCKLAKE_FETCH_OK: fetched {len(names)} reviewed DuckLake artifact(s) from "
        f"lambda-packages/{artifact_sha}/ and server-side-copied each onto its fixed key."
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the build-ducklake-artifacts composite action.

    --mode build (default): build (unless --skip-build) then assert_and_upload() -- the existing
    rebuild path (assert / skip-assert / upload-only composite modes).
    --mode fetch: fetch_reviewed() -- downloads the reviewed per-sha artifacts and server-side
    copies them onto the fixed key, with no rebuild.

    Usage: ducklake_artifacts.py <event_name> <artifact_sha> <bucket> [--region REGION] [--skip-build] [--mode {build,fetch}]
    """
    parser = argparse.ArgumentParser(prog="ducklake_artifacts.py")
    parser.add_argument(
        "event_name", help="'push' runs the byte-identity assert; anything else skips it. Unused in --mode fetch."
    )
    parser.add_argument("artifact_sha", help="Content-addressing sha for the per-sha S3 key.")
    parser.add_argument("bucket", help="S3 bucket for the DuckLake artifacts.")
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument(
        "--skip-build", action="store_true", help="Skip the build step (artifacts already built). Ignored in --mode fetch."
    )
    parser.add_argument(
        "--mode",
        choices=("build", "fetch"),
        default="build",
        help="'build' rebuilds and asserts/uploads (default); 'fetch' downloads the reviewed per-sha artifacts instead.",
    )
    args = parser.parse_args(argv)

    if args.mode == "fetch":
        try:
            fetch_reviewed(list(DUCKLAKE_ARTIFACT_NAMES), args.artifact_sha, args.bucket, args.region)
        except DucklakeArtifactError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        return 0

    if not args.skip_build:
        build_ducklake_only()

    try:
        assert_and_upload(list(DUCKLAKE_ARTIFACT_NAMES), args.artifact_sha, args.event_name, args.bucket, args.region)
    except DucklakeArtifactError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
