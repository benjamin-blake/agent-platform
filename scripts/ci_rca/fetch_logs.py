"""Fetch CI-RCA logs through a fail-closed streaming bound."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, cast

from scripts.ci_rca.bounded_evidence import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    SCHEMA_VERSION,
    EvidenceMetadata,
    copy_bounded_lines,
    write_metadata,
)
from scripts.ci_rca.log_admission import load_admission
from scripts.ci_rca.log_transport import LogTransportError, StreamOpener, open_job_log

_TRANSIENT_ERROR_RE = re.compile(
    r"^(?:failed to get (?:jobs|run)\b|HTTP 5\d\d\b|Service Unavailable)", re.IGNORECASE | re.MULTILINE
)


@dataclass(frozen=True)
class FetchOutcome:
    fetched: bool
    attempts_used: int
    truncated: bool = False
    diagnostic: Optional[str] = None


@dataclass(frozen=True)
class _Attempt:
    retained_bytes: int
    retained_lines: int
    truncated: bool
    failed: bool
    error: str
    segments: list[dict[str, object]]
    omitted_job_ids: list[int]


def _stream_jobs(
    failed_jobs: list[dict[str, object]], repo: str, body_tmp: Path, open_stream: StreamOpener, max_bytes: int, max_lines: int
) -> _Attempt:
    retained_bytes = retained_lines = 0
    truncated = failed = False
    error = ""
    segments: list[dict[str, object]] = []
    omitted_job_ids: list[int] = []
    with body_tmp.open("wb") as destination:
        for job_index, job in enumerate(failed_jobs):
            segment = (
                json.dumps(
                    {"segment_job_id": job["id"], "job_name": job["name"], "steps": job["steps"]},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            if retained_bytes + len(segment) > max_bytes or retained_lines + 1 > max_lines:
                truncated = True
                omitted_job_ids = [cast(int, item["id"]) for item in failed_jobs[job_index:]]
                break
            destination.write(segment)
            retained_bytes += len(segment)
            retained_lines += 1
            copied_bytes = copied_lines = 0
            job_truncated = False
            try:
                with open_stream(repo, cast(int, job["id"])) as source:
                    copied_bytes, copied_lines, job_truncated = copy_bounded_lines(
                        source, destination, max_bytes=max_bytes - retained_bytes, max_lines=max_lines - retained_lines
                    )
            except LogTransportError as exc:
                error = str(exc)
                failed = True
            retained_bytes += copied_bytes
            retained_lines += copied_lines
            segments.append(
                {
                    "job_id": cast(int, job["id"]),
                    "job_name": str(job["name"]),
                    "steps": cast(list[dict[str, object]], job["steps"]),
                    "header_bytes": len(segment),
                    "retained_bytes": copied_bytes,
                    "retained_lines": copied_lines,
                    "truncated": job_truncated,
                }
            )
            if copied_bytes == 0:
                failed = True
                error = error or "CI_RCA_LOG_EMPTY"
                break
            if job_truncated:
                truncated = True
                omitted_job_ids = [cast(int, item["id"]) for item in failed_jobs[job_index + 1 :]]
                break
    return _Attempt(retained_bytes, retained_lines, truncated, failed, error, segments, omitted_job_ids)


def fetch_run_log(
    run_id: str,
    repo: str,
    out_path: Path,
    *,
    metadata_path: Optional[Path] = None,
    admission_path: Optional[Path] = None,
    attempts: int = 3,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
    sleep_fn: Callable[[int], None] = time.sleep,
    stream_opener: StreamOpener | None = None,
) -> FetchOutcome:
    """Stream individually admitted failed-job logs into identity-keyed segments."""
    if admission_path is None:
        raise ValueError("admission metadata is required")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if stream_opener is None and not token:
        raise ValueError("GitHub token is required")
    open_stream = stream_opener or (lambda selected_repo, job_id: open_job_log(selected_repo, job_id, token=token or ""))
    admission = load_admission(admission_path)
    if admission["run_id"] != run_id:
        raise ValueError("run identity differs from admission")
    failed_jobs = [job for job in admission["jobs"] if job["conclusion"] == "failure"]
    if not failed_jobs:
        raise ValueError("admission contains no failed jobs")
    diagnostic = "log empty or unavailable"
    final_metadata_path = metadata_path or out_path.with_suffix(out_path.suffix + ".metadata.json")
    body_tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    metadata_tmp = final_metadata_path.with_suffix(final_metadata_path.suffix + ".tmp")
    for path in (out_path, final_metadata_path, body_tmp, metadata_tmp):
        path.unlink(missing_ok=True)
    for attempt in range(1, attempts + 1):
        result = _stream_jobs(failed_jobs, repo, body_tmp, open_stream, max_bytes, max_lines)
        if result.retained_bytes and not result.failed:
            metadata = EvidenceMetadata(
                schema_version=SCHEMA_VERSION,
                run_id=run_id,
                recovery_url=f"https://github.com/{repo}/actions/runs/{run_id}",
                max_bytes=max_bytes,
                max_lines=max_lines,
                retained_bytes=result.retained_bytes,
                retained_lines=result.retained_lines,
                truncated=result.truncated,
                omitted_counts_known=not result.truncated,
                omitted_bytes=0 if not result.truncated else None,
                omitted_lines=0 if not result.truncated else None,
                recovery_caveat="GitHub controls raw-log availability and expiry; the URL may cease serving retained logs.",
                recovery_instructions="Open the run URL and use GitHub's failed job and step log controls.",
                recovery_argv=["gh", "run", "view", run_id, "--repo", repo, "--web"],
                body_sha256=hashlib.sha256(body_tmp.read_bytes()).hexdigest(),
                segments=result.segments,
                selection_omitted_job_ids=result.omitted_job_ids,
            )
            try:
                write_metadata(metadata_tmp, metadata)
                _publish_pair(body_tmp, metadata_tmp, out_path, final_metadata_path)
            finally:
                body_tmp.unlink(missing_ok=True)
                metadata_tmp.unlink(missing_ok=True)
            return FetchOutcome(True, attempt, result.truncated)
        transient = _TRANSIENT_ERROR_RE.search(result.error)
        diagnostic = (
            f"gh reported a transient error: {transient.group(0)}"
            if transient
            else "log empty, unavailable, or gh reported a non-transient error"
        )
        body_tmp.unlink(missing_ok=True)
        if attempt < attempts:
            sleep_fn(attempt * 10)
    return FetchOutcome(False, attempts, diagnostic=diagnostic)


def _publish_pair(body_tmp: Path, metadata_tmp: Path, body_path: Path, metadata_path: Path) -> None:
    """Publish both files or restore the prior pair if either replacement fails."""
    body_backup = body_path.with_suffix(body_path.suffix + ".bak")
    metadata_backup = metadata_path.with_suffix(metadata_path.suffix + ".bak")
    for backup in (body_backup, metadata_backup):
        backup.unlink(missing_ok=True)
    try:
        if body_path.exists():
            os.replace(body_path, body_backup)
        if metadata_path.exists():
            os.replace(metadata_path, metadata_backup)
        os.replace(body_tmp, body_path)
        os.replace(metadata_tmp, metadata_path)
    except OSError:
        body_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        if body_backup.exists():
            os.replace(body_backup, body_path)
        if metadata_backup.exists():
            os.replace(metadata_backup, metadata_path)
        raise
    finally:
        for path in (body_tmp, metadata_tmp, body_backup, metadata_backup):
            path.unlink(missing_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--metadata-out", type=Path)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    args = parser.parse_args(argv)
    outcome = fetch_run_log(
        args.run_id,
        args.repo,
        args.out,
        metadata_path=args.metadata_out,
        admission_path=args.admission,
        attempts=args.attempts,
        max_bytes=args.max_bytes,
        max_lines=args.max_lines,
    )
    if outcome.fetched:
        return 0
    print(f"::error::CI_RCA_LOG_UNAVAILABLE: bounded failed-step evidence unavailable for run {args.run_id}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
