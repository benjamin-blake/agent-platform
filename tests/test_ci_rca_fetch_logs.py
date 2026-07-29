from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_rca.fetch_logs import _run_log, fetch_run_log, main
from scripts.ci_rca.log_evidence import read_envelope


def _cp(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class Runner:
    def __init__(self, results: list[subprocess.CompletedProcess]) -> None:
        self.results = results
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs) -> subprocess.CompletedProcess:
        self.calls.append(command)
        return self.results.pop(0)


JOBS = json.dumps(
    {
        "jobs": [
            {
                "databaseId": 22,
                "conclusion": "failure",
                "name": "untrusted token=secret",
                "steps": [{"name": "setup", "conclusion": "success"}, {"name": "test", "conclusion": "failure"}],
            }
        ]
    }
)


def test_primary_creates_typed_envelope_and_preserves_http_body(tmp_path: Path) -> None:
    out = tmp_path / "evidence.json"
    runner = Runner([_cp(stdout=JOBS), _cp(stdout="HTTP 502 in genuine log body\n")])
    result = fetch_run_log("123", "owner/repo", out, runner=runner)
    envelope = read_envelope(out)
    assert result.fetched
    assert envelope["retrieval_path"] == "primary"
    assert envelope["failed_jobs"] == [
        {"job_id": 22, "conclusion": "failure", "failed_steps": [{"step_index": 2, "conclusion": "failure"}]}
    ]
    assert envelope["body"] == "HTTP 502 in genuine log body\n"
    assert "untrusted" not in out.read_text(encoding="utf-8")


def test_fallback_is_per_failed_job_and_uses_shared_cap(tmp_path: Path) -> None:
    jobs = json.dumps(
        {
            "jobs": [
                {"databaseId": 9, "conclusion": "failure", "steps": []},
                {"databaseId": 2, "conclusion": "failure", "steps": []},
            ]
        }
    )
    runner = Runner([_cp(stdout=jobs), _cp(code=1, stderr="failed to get jobs"), _cp(stdout="abc\n"), _cp(stdout="def\n")])
    out = tmp_path / "evidence.json"
    result = fetch_run_log("123", "owner/repo", out, runner=runner, max_bytes=5, max_lines=10)
    envelope = read_envelope(out)
    assert result.fetched
    assert envelope["body"] == "abc\n"
    assert envelope["limits"]["complete"] is False
    assert [call[-2] for call in runner.calls[2:]] == ["2", "9"]
    assert all("--job" in call and "--log" in call for call in runner.calls[2:])
    assert not any(call[-1] == "--log" and "--job" not in call for call in runner.calls)


def test_failed_metadata_retries_and_leaves_no_output(tmp_path: Path) -> None:
    runner = Runner([_cp(code=1, stderr="HTTP 503") for _ in range(3)])
    out = tmp_path / "evidence.json"
    sleeps: list[int] = []
    result = fetch_run_log("123", "owner/repo", out, runner=runner, sleep_fn=sleeps.append)
    assert not result.fetched
    assert sleeps == [10, 20]
    assert not out.exists()


def test_main_fails_closed_with_annotation(tmp_path: Path, monkeypatch, capsys) -> None:
    runner = Runner([_cp(code=1) for _ in range(3)])
    monkeypatch.setattr("scripts.ci_rca.fetch_logs.subprocess.run", runner)
    monkeypatch.setattr("scripts.ci_rca.fetch_logs.time.sleep", lambda _value: None)
    assert main(["--run-id", "1", "--repo", "owner/repo", "--out", str(tmp_path / "out")]) == 1
    assert "::error::" in capsys.readouterr().out


@pytest.mark.parametrize("max_bytes,max_lines", [(0, 1), (1, 0), (-1, 1)])
def test_invalid_limits_fail_before_any_subprocess(tmp_path: Path, max_bytes: int, max_lines: int) -> None:
    runner = Runner([])
    with pytest.raises(ValueError, match="positive"):
        fetch_run_log("1", "owner/repo", tmp_path / "out", runner=runner, max_bytes=max_bytes, max_lines=max_lines)
    assert runner.calls == []


def test_partial_fallback_failure_fails_whole_attempt(tmp_path: Path) -> None:
    jobs = json.dumps(
        {
            "jobs": [
                {"databaseId": 2, "conclusion": "failure", "steps": []},
                {"databaseId": 9, "conclusion": "failure", "steps": []},
            ]
        }
    )
    runner = Runner([_cp(stdout=jobs), _cp(code=1), _cp(stdout="partial\n"), _cp(code=1, stderr="unavailable")])
    result = fetch_run_log("1", "owner/repo", tmp_path / "out", attempts=1, runner=runner)
    assert not result.fetched
    assert not (tmp_path / "out").exists()


class TestClassification:
    def test_successful_fetch_with_5xx_in_log_body_is_accepted(self, tmp_path: Path) -> None:
        test_primary_creates_typed_envelope_and_preserves_http_body(tmp_path)

    def test_successful_fetch_with_transient_signature_on_stderr_is_accepted(self, tmp_path: Path) -> None:
        out = tmp_path / "evidence.json"
        runner = Runner([_cp(stdout=JOBS), _cp(stdout="body\n", stderr="failed to get jobs: HTTP 503")])
        assert fetch_run_log("123", "owner/repo", out, runner=runner).fetched


class TestTransientRetry:
    def test_transient_stderr_failure_retries_then_fails_loud(self, tmp_path: Path) -> None:
        test_failed_metadata_retries_and_leaves_no_output(tmp_path)


class TestStreamingTransport:
    def test_exact_byte_cap_is_complete_but_cap_plus_one_is_truncated(self) -> None:
        exact = _run_log([sys.executable, "-c", "import sys;sys.stdout.write('abcd')"], 4, 10)
        over = _run_log([sys.executable, "-c", "import sys;sys.stdout.write('abcde')"], 4, 10)
        assert exact.stdout == over.stdout == "abcd"
        assert exact.truncated is False
        assert over.truncated is True and over.truncation_reason == "byte_limit"

    def test_line_cap_terminates_on_first_byte_of_next_line(self) -> None:
        result = _run_log([sys.executable, "-c", "import sys;sys.stdout.write('one\\ntwo\\nthree')"], 100, 2)
        assert result.stdout == "one\ntwo\n"
        assert result.truncated is True and result.truncation_reason == "line_limit"

    def test_large_stderr_is_drained_concurrently(self) -> None:
        program = "import sys;sys.stderr.write('x'*200000);sys.stderr.flush();sys.stdout.write('ok')"
        result = _run_log([sys.executable, "-c", program], 100, 10)
        assert result.returncode == 0
        assert result.stdout == "ok"
        assert len(result.stderr) == 8192

    def test_sigterm_ignoring_child_is_killed_after_truncation(self) -> None:
        program = (
            "import signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "sys.stdout.write('xx');sys.stdout.flush();time.sleep(10)"
        )
        result = _run_log([sys.executable, "-c", program], 1, 10)
        assert result.stdout == "x"
        assert result.truncated is True
