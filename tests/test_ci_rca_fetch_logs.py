from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest

import scripts.ci_rca.fetch_logs as fetch_module
from scripts.ci_rca.fetch_logs import FetchOutcome, fetch_run_log
from scripts.ci_rca.log_admission import canonical_admission


class _Process:
    def __init__(self, body: bytes, returncode: int = 0, stderr: bytes = b"") -> None:
        self.stdout: BinaryIO | None = io.BytesIO(body)
        self.returncode = returncode
        self.stderr_body = stderr
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return -15 if self.terminated else self.returncode

    def kill(self) -> None:
        self.terminated = True


class _Factory:
    def __init__(self, *processes: _Process) -> None:
        self.processes = list(processes)
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], *args: Any, **kwargs: Any) -> fetch_module._Process:
        self.calls.append(command)
        process = self.processes.pop(0)
        stderr = kwargs.get("stderr")
        if process.stderr_body and hasattr(stderr, "write"):
            stream = cast(BinaryIO, stderr)
            stream.write(process.stderr_body)
            stream.flush()
        return process


def _admission(tmp_path: Path) -> Path:
    path = tmp_path / "admission.json"
    path.write_bytes(
        canonical_admission(
            [{"jobs": [{"id": 9, "name": "job", "conclusion": "failure", "steps": []}]}],
            run_id="42",
            head_sha="a" * 40,
        )
    )
    return path


def _two_job_admission(tmp_path: Path) -> Path:
    path = tmp_path / "admission.json"
    path.write_bytes(
        canonical_admission(
            [
                {
                    "jobs": [
                        {"id": 9, "name": "first", "conclusion": "failure", "steps": []},
                        {"id": 10, "name": "second", "conclusion": "failure", "steps": []},
                    ]
                }
            ],
            run_id="42",
            head_sha="a" * 40,
        )
    )
    return path


def test_complete_failed_log_is_written_with_recovery_metadata(tmp_path: Path) -> None:
    process = _Process(b"job\tstep\tfailure\n")
    factory = _Factory(process)
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log("42", "o/r", out, admission_path=_admission(tmp_path), popen=factory)

    assert outcome == FetchOutcome(True, 1, False)
    assert out.read_bytes().endswith(b"job\tstep\tfailure\n")
    metadata = json.loads((tmp_path / "evidence.log.metadata.json").read_text())
    assert metadata["recovery_url"] == "https://github.com/o/r/actions/runs/42"
    assert metadata["omitted_counts_known"] is True
    assert factory.calls[0][-1] == "repos/o/r/actions/jobs/9/logs"


def test_byte_bound_terminates_producer_and_retains_whole_lines(tmp_path: Path) -> None:
    process = _Process(b"first\nsecond\nthird\n")
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log("42", "o/r", out, admission_path=_admission(tmp_path), max_bytes=62, popen=_Factory(process))

    assert outcome == FetchOutcome(True, 1, True)
    assert out.read_bytes().endswith(b"first\nsecond\n")
    assert process.terminated is True
    metadata = json.loads((tmp_path / "evidence.log.metadata.json").read_text())
    assert metadata["segments"][0]["job_id"] == 9


def test_oversized_first_line_fails_closed(tmp_path: Path) -> None:
    process = _Process(b"0123456789\n")
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_admission(tmp_path), attempts=1, max_bytes=5, popen=_Factory(process)
    )

    assert outcome.fetched is False
    assert not out.exists()


def test_header_fit_with_oversized_first_raw_line_fails_closed(tmp_path: Path) -> None:
    process = _Process(b"oversized-first-line\n")
    out = tmp_path / "evidence.log"
    header = b'{"job_name":"job","segment_job_id":9,"steps":[]}\n'
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_admission(tmp_path),
        attempts=1,
        max_bytes=len(header) + 5,
        popen=_Factory(process),
    )
    assert outcome.fetched is False
    assert process.terminated is True
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_empty_fetch_retries_without_whole_run_fallback(tmp_path: Path) -> None:
    factory = _Factory(_Process(b"", 1), _Process(b"", 1), _Process(b"", 1))
    sleeps: list[int] = []

    outcome = fetch_run_log(
        "42",
        "o/r",
        tmp_path / "evidence.log",
        admission_path=_admission(tmp_path),
        popen=factory,
        sleep_fn=sleeps.append,
    )

    assert outcome == FetchOutcome(False, 3, diagnostic="log empty, unavailable, or gh reported a non-transient error")
    assert sleeps == [10, 20]
    assert all(command[-1] == "repos/o/r/actions/jobs/9/logs" for command in factory.calls)


def test_successful_empty_job_body_cannot_succeed_from_segment_header(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_admission(tmp_path), attempts=1, popen=_Factory(_Process(b"", 0))
    )
    assert outcome.fetched is False
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_empty_later_job_fails_closed_instead_of_attesting_header_only_segment(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_two_job_admission(tmp_path),
        attempts=1,
        popen=_Factory(_Process(b"first\n", 0), _Process(b"", 0)),
    )
    assert outcome.fetched is False
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_oversized_first_line_in_later_job_fails_entire_multi_job_fetch(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    first_header = b'{"job_name":"first","segment_job_id":9,"steps":[]}\n'
    second_header = b'{"job_name":"second","segment_job_id":10,"steps":[]}\n'
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_two_job_admission(tmp_path),
        attempts=1,
        max_bytes=len(first_header) + len(b"first\n") + len(second_header) + 5,
        popen=_Factory(_Process(b"first\n", 0), _Process(b"oversized\n", 0)),
    )
    assert outcome.fetched is False
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_transient_classification_reads_stderr_only(tmp_path: Path) -> None:
    process = _Process(b"", 1, b"failed to get jobs: HTTP 503\n")
    outcome = fetch_run_log(
        "42",
        "o/r",
        tmp_path / "evidence.log",
        admission_path=_admission(tmp_path),
        attempts=1,
        popen=_Factory(process),
    )
    assert outcome.diagnostic == "gh reported a transient error: failed to get jobs"


def test_truncation_records_only_acquired_segment_and_selection_omission(tmp_path: Path) -> None:
    first = _Process(b"first\nsecond\n")
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log("42", "o/r", out, admission_path=_two_job_admission(tmp_path), max_bytes=80, popen=_Factory(first))
    assert outcome.truncated
    metadata = json.loads((tmp_path / "evidence.log.metadata.json").read_text())
    assert [item["job_id"] for item in metadata["segments"]] == [9]
    assert metadata["selection_omitted_job_ids"] == [10]
    assert metadata["segments"][0]["retained_bytes"] > 0


def test_pair_publication_restores_previous_pair_on_second_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = tmp_path / "body"
    metadata = tmp_path / "metadata"
    body.write_bytes(b"old-body")
    metadata.write_bytes(b"old-metadata")
    body_tmp = tmp_path / "body.tmp"
    metadata_tmp = tmp_path / "metadata.tmp"
    body_tmp.write_bytes(b"new-body")
    metadata_tmp.write_bytes(b"new-metadata")
    real_replace = fetch_module.os.replace

    def failing_replace(source: Path, destination: Path) -> None:
        if source == metadata_tmp and destination == metadata:
            raise OSError("simulated")
        real_replace(source, destination)

    monkeypatch.setattr(fetch_module.os, "replace", failing_replace)
    with pytest.raises(OSError):
        fetch_module._publish_pair(body_tmp, metadata_tmp, body, metadata)
    assert body.read_bytes() == b"old-body"
    assert metadata.read_bytes() == b"old-metadata"
