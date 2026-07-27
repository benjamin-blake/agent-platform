from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci_rca.agent_envelope import publish
from scripts.ci_rca.bounded_evidence import SCHEMA_VERSION, EvidenceMetadata, write_metadata
from scripts.ci_rca.log_admission import canonical_admission


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    admission = tmp_path / "admission.json"
    admission.write_bytes(
        canonical_admission(
            [{"jobs": [{"id": 9, "name": "job", "conclusion": "failure", "steps": []}]}],
            run_id="42",
            head_sha="a" * 40,
        )
    )
    body = tmp_path / "body.log"
    body.write_bytes(b"line\n")
    metadata = tmp_path / "metadata.json"
    write_metadata(
        metadata,
        EvidenceMetadata(
            schema_version=SCHEMA_VERSION,
            run_id="42",
            recovery_url="https://github.com/o/r/actions/runs/42",
            max_bytes=100,
            max_lines=10,
            retained_bytes=5,
            retained_lines=1,
            truncated=False,
            omitted_counts_known=True,
            omitted_bytes=0,
            omitted_lines=0,
            recovery_caveat="expires",
            recovery_instructions="open run",
            recovery_argv=["gh", "run", "view", "42", "--repo", "o/r", "--web"],
            body_sha256=hashlib.sha256(b"line\n").hexdigest(),
            segments=[
                {
                    "job_id": 9,
                    "job_name": "job",
                    "steps": [],
                    "header_bytes": 65,
                    "retained_bytes": 5,
                    "retained_lines": 1,
                    "truncated": False,
                }
            ],
            selection_omitted_job_ids=[],
        ),
    )
    header = b'{"job_name":"job","segment_job_id":9,"steps":[]}\n'
    body.write_bytes(header + b"line\n")
    document = json.loads(metadata.read_text())
    document["retained_bytes"] = len(header) + 5
    document["retained_lines"] = 2
    document["segments"][0]["header_bytes"] = len(header)
    document["body_sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    return admission, metadata, body


def test_publish_validates_and_frames_agent_evidence(tmp_path: Path) -> None:
    admission, metadata, body = _files(tmp_path)
    output = tmp_path / "agent.log"
    publish(admission, metadata, body, output)
    header, raw = output.read_bytes().split(b"\n", 1)
    assert json.loads(header)["admission"]["run_id"] == "42"
    assert raw.endswith(b"line\n")


def test_digest_mismatch_removes_output(tmp_path: Path) -> None:
    admission, metadata, body = _files(tmp_path)
    body.write_bytes(b"changed\n")
    output = tmp_path / "agent.log"
    output.write_text("stale")
    with pytest.raises(ValueError, match="digest"):
        publish(admission, metadata, body, output)


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_id", "43"), ("max_bytes", 0), ("retained_lines", -1), ("recovery_url", "https://evil.invalid/x")],
)
def test_invalid_typed_metadata_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    admission, metadata, body = _files(tmp_path)
    document = json.loads(metadata.read_text())
    document[field] = value
    metadata.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ValueError):
        publish(admission, metadata, body, tmp_path / "out")


def test_segment_header_must_match_admission(tmp_path: Path) -> None:
    admission, metadata, body = _files(tmp_path)
    body.write_bytes(body.read_bytes().replace(b'"job"', b'"bad"'))
    document = json.loads(metadata.read_text())
    document["body_sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
    document["retained_bytes"] = len(body.read_bytes())
    metadata.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ValueError, match="header"):
        publish(admission, metadata, body, tmp_path / "out")
