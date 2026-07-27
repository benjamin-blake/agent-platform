"""Validate and publish the final agent-visible CI-RCA evidence envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.ci_rca.bounded_evidence import SCHEMA_VERSION, EvidenceMetadata
from scripts.ci_rca.log_admission import load_admission

AGENT_VISIBLE_MAX_BYTES = 300_000


def _integer(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"invalid {name}")
    return value


def _validate_metadata(metadata: Any, admission: dict[str, Any], body: bytes) -> None:
    if not isinstance(metadata, dict) or set(metadata) != {field.name for field in fields(EvidenceMetadata)}:
        raise ValueError("invalid evidence metadata schema")
    if metadata["schema_version"] != SCHEMA_VERSION or metadata["run_id"] != admission["run_id"]:
        raise ValueError("evidence run or schema differs from admission")
    for name in ("max_bytes", "max_lines"):
        _integer(metadata[name], name, positive=True)
    for name in ("retained_bytes", "retained_lines"):
        _integer(metadata[name], name)
    if metadata["retained_bytes"] > metadata["max_bytes"] or metadata["retained_lines"] > metadata["max_lines"]:
        raise ValueError("retained evidence exceeds declared ceiling")
    for name in ("truncated", "omitted_counts_known"):
        if type(metadata[name]) is not bool:
            raise ValueError(f"invalid {name}")
    if metadata["truncated"] == metadata["omitted_counts_known"]:
        raise ValueError("invalid truncation accounting state")
    expected_omitted = 0 if metadata["omitted_counts_known"] else None
    if metadata["omitted_bytes"] != expected_omitted or metadata["omitted_lines"] != expected_omitted:
        raise ValueError("invalid omitted counts")
    parsed = urlparse(metadata["recovery_url"] if isinstance(metadata["recovery_url"], str) else "")
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.query or parsed.fragment:
        raise ValueError("invalid recovery URL")
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) != 5 or path_parts[2:] != ["actions", "runs", metadata["run_id"]]:
        raise ValueError("invalid recovery URL path")
    if not isinstance(metadata["recovery_caveat"], str) or not metadata["recovery_caveat"].strip():
        raise ValueError("invalid recovery caveat")
    if not isinstance(metadata["recovery_instructions"], str) or not metadata["recovery_instructions"].strip():
        raise ValueError("invalid recovery instructions")
    expected_argv = ["gh", "run", "view", metadata["run_id"], "--repo", "/".join(path_parts[:2]), "--web"]
    if metadata["recovery_argv"] != expected_argv:
        raise ValueError("invalid recovery command")
    if hashlib.sha256(body).hexdigest() != metadata["body_sha256"]:
        raise ValueError("evidence body digest mismatch")
    if len(body) != metadata["retained_bytes"] or body.count(b"\n") != metadata["retained_lines"]:
        raise ValueError("evidence body accounting mismatch")
    _validate_segments(metadata, admission, body)


def _validate_segments(metadata: dict[str, Any], admission: dict[str, Any], body: bytes) -> None:
    failed = [job for job in admission["jobs"] if job["conclusion"] == "failure"]
    segments = metadata["segments"]
    omitted = metadata["selection_omitted_job_ids"]
    if not isinstance(segments, list) or not isinstance(omitted, list) or any(type(item) is not int for item in omitted):
        raise ValueError("invalid segment selection")
    acquired_ids = [item.get("job_id") for item in segments if isinstance(item, dict)]
    failed_ids = [job["id"] for job in failed]
    if acquired_ids + omitted != failed_ids or (omitted and not metadata["truncated"]):
        raise ValueError("evidence selection differs from admitted failures")
    cursor = 0
    expected_keys = {"job_id", "job_name", "steps", "header_bytes", "retained_bytes", "retained_lines", "truncated"}
    for segment, job in zip(segments, failed, strict=False):
        if not isinstance(segment, dict) or set(segment) != expected_keys:
            raise ValueError("invalid segment schema")
        if segment["job_id"] != job["id"] or segment["job_name"] != job["name"] or segment["steps"] != job["steps"]:
            raise ValueError("segment identity differs from admission")
        header_bytes = _integer(segment["header_bytes"], "segment header bytes", positive=True)
        retained_bytes = _integer(segment["retained_bytes"], "segment retained bytes")
        retained_lines = _integer(segment["retained_lines"], "segment retained lines")
        if type(segment["truncated"]) is not bool:
            raise ValueError("invalid segment truncation")
        expected_header = (
            json.dumps(
                {"segment_job_id": job["id"], "job_name": job["name"], "steps": job["steps"]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        if header_bytes != len(expected_header) or body[cursor : cursor + header_bytes] != expected_header:
            raise ValueError("segment body header differs from admission")
        cursor += header_bytes
        payload = body[cursor : cursor + retained_bytes]
        if payload.count(b"\n") != retained_lines:
            raise ValueError("segment body accounting mismatch")
        cursor += retained_bytes
    truncated_segments = [index for index, item in enumerate(segments) if item["truncated"]]
    if truncated_segments and (truncated_segments != [len(segments) - 1] or not metadata["truncated"]):
        raise ValueError("invalid segment truncation position")
    if metadata["truncated"] and not truncated_segments and not omitted:
        raise ValueError("truncation has no segment or selection omission")
    if cursor != len(body) or len(truncated_segments) > 1:
        raise ValueError("segment framing does not cover evidence body")


def publish(admission_path: Path, metadata_path: Path, body_path: Path, output_path: Path) -> None:
    output_path.unlink(missing_ok=True)
    admission = load_admission(admission_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    body = body_path.read_bytes()
    _validate_metadata(metadata, admission, body)
    header = (
        json.dumps(
            {"evidence_metadata": metadata, "admission": admission, "raw_evidence_follows": True},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    if len(header) + len(body) > AGENT_VISIBLE_MAX_BYTES:
        raise ValueError("agent-visible evidence exceeds its independent ceiling")
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        temporary.write_bytes(header + body)
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        publish(args.admission, args.metadata, args.body, args.out)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CI_RCA_ENVELOPE_INVALID: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
