"""Bound CI-RCA text evidence before it reaches disk or an agent."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

SCHEMA_VERSION = "ci-rca-bounded-evidence/v1"
DEFAULT_MAX_BYTES = 256_000
DEFAULT_MAX_LINES = 4_000


@dataclass(frozen=True)
class EvidenceMetadata:
    schema_version: str
    run_id: str
    recovery_url: str
    max_bytes: int
    max_lines: int
    retained_bytes: int
    retained_lines: int
    truncated: bool
    omitted_counts_known: bool
    omitted_bytes: int | None
    omitted_lines: int | None
    recovery_caveat: str
    recovery_instructions: str
    recovery_argv: list[str]
    body_sha256: str
    segments: list[dict[str, object]]
    selection_omitted_job_ids: list[int]


def copy_bounded_lines(source: BinaryIO, destination: BinaryIO, *, max_bytes: int, max_lines: int) -> tuple[int, int, bool]:
    """Copy complete lines within both limits and stop reading as soon as either is reached."""
    retained_bytes = 0
    retained_lines = 0
    while retained_lines < max_lines:
        remaining = max_bytes - retained_bytes
        if remaining <= 0:
            return retained_bytes, retained_lines, bool(source.read(1))
        line = source.readline(remaining + 1)
        if not line:
            return retained_bytes, retained_lines, False
        if len(line) > remaining or not line.endswith(b"\n"):
            return retained_bytes, retained_lines, True
        destination.write(line)
        retained_bytes += len(line)
        retained_lines += 1
    return retained_bytes, retained_lines, bool(source.read(1))


def write_metadata(path: Path, metadata: EvidenceMetadata) -> None:
    path.write_text(json.dumps(asdict(metadata), sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
