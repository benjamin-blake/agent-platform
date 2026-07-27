from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import scripts.ci_rca.fetch_logs as fetch_module
from scripts.ci_rca.fetch_logs import FetchOutcome, fetch_run_log
from scripts.ci_rca.log_admission import canonical_admission


class _Stream(io.BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.closed_by_consumer = False

    def close(self) -> None:
        self.closed_by_consumer = True
        super().close()


class _Factory:
    def __init__(self, *streams: _Stream) -> None:
        self.streams = list(streams)
        self.calls: list[tuple[str, int]] = []

    def __call__(self, repo: str, job_id: int) -> _Stream:
        self.calls.append((repo, job_id))
        return self.streams.pop(0)


class _InterruptedStream(_Stream):
    def __init__(self) -> None:
        super().__init__(b"partial\n")
        self._reads = 0

    def readline(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise fetch_module.LogTransportError("CI_RCA_LOG_STREAM_INTERRUPTED")
        return super().readline(size)


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
    process = _Stream(b"job\tstep\tfailure\n")
    factory = _Factory(process)
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log("42", "o/r", out, admission_path=_admission(tmp_path), stream_opener=factory)

    assert outcome == FetchOutcome(True, 1, False)
    assert out.read_bytes().endswith(b"job\tstep\tfailure\n")
    metadata = json.loads((tmp_path / "evidence.log.metadata.json").read_text())
    assert metadata["recovery_url"] == "https://github.com/o/r/actions/runs/42"
    assert metadata["omitted_counts_known"] is True
    assert factory.calls[0] == ("o/r", 9)


def test_byte_bound_terminates_producer_and_retains_whole_lines(tmp_path: Path) -> None:
    process = _Stream(b"first\nsecond\nthird\n")
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_admission(tmp_path), max_bytes=62, stream_opener=_Factory(process)
    )

    assert outcome == FetchOutcome(True, 1, True)
    assert out.read_bytes().endswith(b"first\nsecond\n")
    assert process.closed_by_consumer is True
    metadata = json.loads((tmp_path / "evidence.log.metadata.json").read_text())
    assert metadata["segments"][0]["job_id"] == 9


def test_oversized_first_line_fails_closed(tmp_path: Path) -> None:
    process = _Stream(b"0123456789\n")
    out = tmp_path / "evidence.log"

    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_admission(tmp_path), attempts=1, max_bytes=5, stream_opener=_Factory(process)
    )

    assert outcome.fetched is False
    assert not out.exists()


def test_header_fit_with_oversized_first_raw_line_fails_closed(tmp_path: Path) -> None:
    process = _Stream(b"oversized-first-line\n")
    out = tmp_path / "evidence.log"
    header = b'{"job_name":"job","segment_job_id":9,"steps":[]}\n'
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_admission(tmp_path),
        attempts=1,
        max_bytes=len(header) + 5,
        stream_opener=_Factory(process),
    )
    assert outcome.fetched is False
    assert process.closed_by_consumer is True
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_empty_fetch_retries_without_whole_run_fallback(tmp_path: Path) -> None:
    factory = _Factory(_Stream(b""), _Stream(b""), _Stream(b""))
    sleeps: list[int] = []

    outcome = fetch_run_log(
        "42",
        "o/r",
        tmp_path / "evidence.log",
        admission_path=_admission(tmp_path),
        stream_opener=factory,
        sleep_fn=sleeps.append,
    )

    assert outcome == FetchOutcome(False, 3, diagnostic="log empty, unavailable, or gh reported a non-transient error")
    assert sleeps == [10, 20]
    assert factory.calls == [("o/r", 9)] * 3


def test_successful_empty_job_body_cannot_succeed_from_segment_header(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_admission(tmp_path), attempts=1, stream_opener=_Factory(_Stream(b""))
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
        stream_opener=_Factory(_Stream(b"first\n"), _Stream(b"")),
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
        stream_opener=_Factory(_Stream(b"first\n"), _Stream(b"oversized\n")),
    )
    assert outcome.fetched is False
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_transient_classification_reads_stderr_only(tmp_path: Path) -> None:
    def unavailable(repo: str, job_id: int) -> _Stream:
        raise fetch_module.LogTransportError("HTTP 503")

    outcome = fetch_run_log(
        "42", "o/r", tmp_path / "evidence.log", admission_path=_admission(tmp_path), attempts=1, stream_opener=unavailable
    )
    assert outcome.diagnostic == "gh reported a transient error: HTTP 503"


def test_midstream_failure_retries_without_publishing_partial_body(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    sleeps: list[int] = []
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_admission(tmp_path),
        attempts=2,
        stream_opener=_Factory(_InterruptedStream(), _Stream(b"complete\n")),
        sleep_fn=sleeps.append,
    )
    assert outcome == FetchOutcome(True, 2, False)
    assert out.read_bytes().endswith(b"complete\n")
    assert b"partial" not in out.read_bytes()
    assert sleeps == [10]


def test_repeated_midstream_failure_leaves_no_evidence_pair(tmp_path: Path) -> None:
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log(
        "42",
        "o/r",
        out,
        admission_path=_admission(tmp_path),
        attempts=2,
        stream_opener=_Factory(_InterruptedStream(), _InterruptedStream()),
        sleep_fn=lambda _: None,
    )
    assert outcome == FetchOutcome(False, 2, diagnostic="log empty, unavailable, or gh reported a non-transient error")
    assert not out.exists()
    assert not (tmp_path / "evidence.log.metadata.json").exists()


def test_truncation_records_only_acquired_segment_and_selection_omission(tmp_path: Path) -> None:
    first = _Stream(b"first\nsecond\n")
    out = tmp_path / "evidence.log"
    outcome = fetch_run_log(
        "42", "o/r", out, admission_path=_two_job_admission(tmp_path), max_bytes=80, stream_opener=_Factory(first)
    )
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
