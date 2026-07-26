"""Unit tests for scripts.ci_rca.fetch_logs (rec-2857 regression proof + full behavioural coverage).

Fakes subprocess.run via dependency injection (the module's `runner` parameter) rather than
patching the `subprocess` module globally -- each test controls exactly what gh "returns" per
call and asserts on the exact commands issued. Sleep is injected too, so the retry tests never
wall-clock.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_rca.fetch_logs import FetchOutcome, fetch_run_log, main


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _ScriptedRunner:
    """A fake `subprocess.run` returning one scripted CompletedProcess per call, in order."""

    def __init__(self, results: list[subprocess.CompletedProcess]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        assert self._results, f"ScriptedRunner exhausted: unexpected extra subprocess call {cmd!r}"
        return self._results.pop(0)


class _RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, seconds: int) -> None:
        self.calls.append(seconds)


class TestClassification:
    def test_successful_fetch_with_5xx_in_log_body_is_accepted(self, tmp_path: Path) -> None:
        """rec-2857 REGRESSION PROOF: a successful fetch whose log BODY contains 'HTTP 502' must
        be accepted on attempt 1 -- the content grep that used to reject this is gone."""
        out = tmp_path / "ci-rca-failed.log"
        log_body = "Step failed: ducklake_writer returned HTTP 502: Bad Gateway\nsee traceback above\n"
        runner = _ScriptedRunner([_cp(returncode=0, stdout=log_body, stderr="")])
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome == FetchOutcome(fetched=True, attempts_used=1)
        assert out.read_text(encoding="utf-8") == log_body
        assert len(runner.calls) == 1
        assert sleep_fn.calls == []

    def test_successful_fetch_with_transient_signature_on_stderr_is_accepted(self, tmp_path: Path) -> None:
        """DUAL OF rec-2857: a fetch that SUCCEEDS while gh writes a transient signature to its
        OWN stderr must still be accepted on attempt 1 -- the stderr signature must never override
        a successful exit status."""
        out = tmp_path / "ci-rca-failed.log"
        log_body = "ordinary failure log content\n"
        runner = _ScriptedRunner(
            [_cp(returncode=0, stdout=log_body, stderr="failed to get jobs: HTTP 503: Service Unavailable")]
        )
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome == FetchOutcome(fetched=True, attempts_used=1)
        assert out.read_text(encoding="utf-8") == log_body
        assert len(runner.calls) == 1
        assert sleep_fn.calls == []


class TestTransientRetry:
    def test_transient_stderr_failure_retries_then_fails_loud(self, tmp_path: Path) -> None:
        """rec-2718 contract: a genuine transient gh fetch failure (non-zero exit, transient
        signature on stderr, empty stdout) is retried up to 3 attempts and, if never satisfied,
        fails loudly (fetched=False) rather than being silently accepted."""
        out = tmp_path / "ci-rca-failed.log"
        transient_cp = _cp(returncode=1, stdout="", stderr="failed to get jobs: HTTP 503: Service Unavailable")
        # 3 attempts * (primary + fallback) = 6 calls, all transient failures.
        runner = _ScriptedRunner([transient_cp] * 6)
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome.fetched is False
        assert outcome.attempts_used == 3
        assert "transient" in outcome.diagnostic
        assert len(runner.calls) == 6
        assert not out.exists()
        # Sleeps between attempts 1->2 and 2->3 only (never after the final attempt).
        assert sleep_fn.calls == [10, 20]

    def test_succeeds_on_second_attempt_after_transient_failure(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        transient_cp = _cp(returncode=1, stdout="", stderr="failed to get run: HTTP 502")
        success_cp = _cp(returncode=0, stdout="fetched at last\n", stderr="")
        runner = _ScriptedRunner([transient_cp, transient_cp, success_cp])
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome == FetchOutcome(fetched=True, attempts_used=2)
        assert out.read_text(encoding="utf-8") == "fetched at last\n"
        assert sleep_fn.calls == [10]

    def test_non_transient_failure_also_retries_and_fails_loud(self, tmp_path: Path) -> None:
        """A failure whose stderr matches no transient signature still exhausts all attempts
        (the module does not special-case "non-transient" into an early exit) and the diagnostic
        falls through to the generic message."""
        out = tmp_path / "ci-rca-failed.log"
        opaque_cp = _cp(returncode=1, stdout="", stderr="permission denied")
        runner = _ScriptedRunner([opaque_cp] * 6)
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome.fetched is False
        assert outcome.attempts_used == 3
        assert outcome.diagnostic == "log empty, unavailable, or gh reported a non-transient error"
        assert len(runner.calls) == 6


class TestFallbackChain:
    def test_fallback_fires_on_empty_rc0_log_failed(self, tmp_path: Path) -> None:
        """Widened fallback (disclosed behaviour change): --log-failed exiting 0 with EMPTY
        stdout (a run with no failed-step logs) falls through to --log, not just a non-zero exit."""
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner([_cp(returncode=0, stdout=""), _cp(returncode=0, stdout="full run log\n")])
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome == FetchOutcome(fetched=True, attempts_used=1)
        assert out.read_text(encoding="utf-8") == "full run log\n"
        assert len(runner.calls) == 2
        assert runner.calls[0][-1] == "--log-failed"
        assert runner.calls[1][-1] == "--log"

    def test_fallback_fires_on_nonzero_exit(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner(
            [_cp(returncode=1, stdout="", stderr="some error"), _cp(returncode=0, stdout="full run log\n")]
        )
        sleep_fn = _RecordingSleep()

        outcome = fetch_run_log("123", "o/r", out, sleep_fn=sleep_fn, runner=runner)

        assert outcome == FetchOutcome(fetched=True, attempts_used=1)
        assert out.read_text(encoding="utf-8") == "full run log\n"

    def test_commands_target_run_id_and_repo(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner([_cp(returncode=0, stdout="ok\n")])
        fetch_run_log("999", "benjamin-blake/agent-platform", out, sleep_fn=_RecordingSleep(), runner=runner)

        assert runner.calls[0] == [
            "gh",
            "run",
            "view",
            "999",
            "--repo",
            "benjamin-blake/agent-platform",
            "--log-failed",
        ]


class TestOutputContract:
    def test_writes_stdout_only_not_stderr(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner([_cp(returncode=0, stdout="stdout content\n", stderr="a warning on stderr")])

        fetch_run_log("123", "o/r", out, sleep_fn=_RecordingSleep(), runner=runner)

        written = out.read_text(encoding="utf-8")
        assert written == "stdout content\n"
        assert "warning" not in written

    def test_byte_for_byte_passthrough(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        body = "line one\nline two\ttabbed\nHTTP 502 appears mid-body but is irrelevant\n"
        runner = _ScriptedRunner([_cp(returncode=0, stdout=body, stderr="")])

        fetch_run_log("123", "o/r", out, sleep_fn=_RecordingSleep(), runner=runner)

        assert out.read_text(encoding="utf-8") == body

    def test_nothing_written_on_exhaustion(self, tmp_path: Path) -> None:
        out = tmp_path / "ci-rca-failed.log"
        failing = _cp(returncode=1, stdout="", stderr="")
        runner = _ScriptedRunner([failing] * 6)

        fetch_run_log("123", "o/r", out, sleep_fn=_RecordingSleep(), runner=runner)

        assert not out.exists()


class TestMain:
    def test_exits_zero_and_writes_log_on_success(self, tmp_path: Path, monkeypatch, capsys) -> None:
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner([_cp(returncode=0, stdout="ok\n")])
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.subprocess.run", runner)

        rc = main(["--run-id", "1", "--repo", "o/r", "--out", str(out)])

        assert rc == 0
        assert out.read_text(encoding="utf-8") == "ok\n"

    def test_exits_nonzero_and_prints_error_annotation_on_exhaustion(self, tmp_path: Path, monkeypatch, capsys) -> None:
        out = tmp_path / "ci-rca-failed.log"
        failing = _cp(returncode=1, stdout="", stderr="failed to get jobs: HTTP 503")
        runner = _ScriptedRunner([failing] * 6)
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.subprocess.run", runner)
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.time.sleep", lambda _seconds: None)

        rc = main(["--run-id", "1", "--repo", "o/r", "--out", str(out)])

        assert rc == 1
        assert not out.exists()
        captured = capsys.readouterr().out
        assert "::error::" in captured
        assert "rec-2117" in captured and "rec-2118" in captured and "rec-2718" in captured

    def test_respects_attempts_override(self, tmp_path: Path, monkeypatch) -> None:
        out = tmp_path / "ci-rca-failed.log"
        failing = _cp(returncode=1, stdout="", stderr="")
        runner = _ScriptedRunner([failing] * 2)
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.subprocess.run", runner)
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.time.sleep", lambda _seconds: None)

        rc = main(["--run-id", "1", "--repo", "o/r", "--out", str(out), "--attempts", "1"])

        assert rc == 1
        assert len(runner.calls) == 2


class TestCliMain:
    # This module is already imported at collection time (for the direct-call tests above), so
    # it is already in sys.modules by the time runpy re-executes it below -- the standard, benign
    # runpy caveat for this pattern (docs.python.org/3/library/runpy.html).
    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_runpy_main_entrypoint_writes_log_and_exits_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        out = tmp_path / "ci-rca-failed.log"
        runner = _ScriptedRunner([_cp(returncode=0, stdout="ok\n")])
        monkeypatch.setattr("scripts.ci_rca.fetch_logs.subprocess.run", runner)
        monkeypatch.setattr(sys, "argv", ["fetch_logs", "--run-id", "1", "--repo", "o/r", "--out", str(out)])

        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("scripts.ci_rca.fetch_logs", run_name="__main__")

        assert exc_info.value.code == 0
        assert out.read_text(encoding="utf-8") == "ok\n"
