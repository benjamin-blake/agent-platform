"""Fetch + classify a failed CI run's log for ci-rca.yml (rec-2857 forward fix).

ci-rca.yml's "Fetch failed run logs" step used to merge gh's stdout and stderr into one file
(`2>&1`) and grep that combined stream for transient-error signatures (rec-2117 / rec-2118 /
rec-2718's retry contract). With stdout and stderr indistinguishable, a genuine failure log whose
BODY happens to contain an HTTP 5xx string (e.g. a ducklake_writer error trace) was rejected as a
failed FETCH and retried against identical content until exhaustion -- the run never reached the
ci-rca agent (rec-2857).

This module restores the distinction: fetched-ness is decided purely from the gh subprocess
returncode plus non-empty stdout. The anchored transient-error patterns are matched against gh's
own STDERR only, and only to compose the diagnostic message on the failure path -- they never
override a successful exit status, and are never evaluated against the log body. Mirrors
scripts/ci_rca/designed_refusal.py's shape: a thin argparse CLI, no shared state, no raise at
import.

CLI usage (invoked by ci-rca.yml's "Fetch failed run logs" step):
    bin/venv-python -m scripts.ci_rca.fetch_logs \\
        --run-id "$RUN_ID" --repo "${{ github.repository }}" --out /tmp/ci-rca-failed.log
Exits 0 with the log written to --out on a successful fetch; exits 1 (nothing written) after
exhausting --attempts, printing a `::error::` annotation with the rec-2117 / rec-2118 / rec-2718
provenance.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Anchored restoration of PLAN-resolve-ci-rca-canary-red.yaml:179's original intent
# ("^failed to get (jobs|run)" | "HTTP 5xx:" | "Service Unavailable"), which the shipped
# unanchored regex dropped. Matched per-line against gh's stderr only -- never the log body.
_TRANSIENT_ERROR_RE = re.compile(
    r"^(?:failed to get (?:jobs|run)\b|HTTP 5\d\d\b|Service Unavailable)",
    re.IGNORECASE | re.MULTILINE,
)

_Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class FetchOutcome:
    fetched: bool
    attempts_used: int
    diagnostic: Optional[str] = None


def _gh_view_cmd(run_id: str, repo: str, *, log_failed: bool) -> list[str]:
    cmd = ["gh", "run", "view", run_id, "--repo", repo]
    cmd.append("--log-failed" if log_failed else "--log")
    return cmd


def _run_gh(runner: _Runner, cmd: list[str]) -> subprocess.CompletedProcess:
    return runner(cmd, capture_output=True, text=True, encoding="utf-8")


def _transient_signature(stderr: str) -> Optional[str]:
    match = _TRANSIENT_ERROR_RE.search(stderr or "")
    return match.group(0) if match else None


def _diagnose(*stderrs: str) -> str:
    for stderr in stderrs:
        signature = _transient_signature(stderr)
        if signature:
            return f"gh reported a transient error: {signature!r}"
    return "log empty, unavailable, or gh reported a non-transient error"


def fetch_run_log(
    run_id: str,
    repo: str,
    out_path: Path,
    attempts: int = 3,
    sleep_fn: Optional[Callable[[int], None]] = None,
    runner: Optional[_Runner] = None,
) -> FetchOutcome:
    """Fetch the failed-run log, retrying up to `attempts` times.

    Per attempt: run `gh run view --log-failed`; treat it as fetched when returncode == 0 AND
    stdout is non-empty. Otherwise fall back to the same call without --log-failed (this widens
    the original fallback, which fired on non-zero exit only, to also fire on an empty-but-rc-0
    --log-failed result -- a run with no failed-step logs). Only stdout is ever written to
    out_path; the transient-pattern match against stderr affects only the diagnostic message on
    the failure path, never the fetched/not-fetched decision.

    `sleep_fn` / `runner` default to `time.sleep` / `subprocess.run` resolved at CALL time (not
    bound as parameter defaults) so a test can monkeypatch `subprocess.run` and have `main()`'s
    unparameterized call pick it up.
    """
    sleep_fn = sleep_fn or time.sleep
    runner = runner or subprocess.run
    diagnostic = None
    for attempt in range(1, attempts + 1):
        primary = _run_gh(runner, _gh_view_cmd(run_id, repo, log_failed=True))
        if primary.returncode == 0 and primary.stdout:
            out_path.write_text(primary.stdout, encoding="utf-8")
            return FetchOutcome(fetched=True, attempts_used=attempt)

        fallback = _run_gh(runner, _gh_view_cmd(run_id, repo, log_failed=False))
        if fallback.returncode == 0 and fallback.stdout:
            out_path.write_text(fallback.stdout, encoding="utf-8")
            return FetchOutcome(fetched=True, attempts_used=attempt)

        diagnostic = _diagnose(primary.stderr, fallback.stderr)
        if attempt < attempts:
            sleep_fn(attempt * 10)

    return FetchOutcome(fetched=False, attempts_used=attempts, diagnostic=diagnostic)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch + classify a failed CI run's log for ci-rca.yml.")
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID of the failed run.")
    parser.add_argument("--repo", required=True, help="owner/repo, e.g. github.repository.")
    parser.add_argument("--out", type=Path, required=True, help="Output path for the fetched log.")
    parser.add_argument("--attempts", type=int, default=3, help="Maximum fetch attempts (default 3).")
    args = parser.parse_args(argv)

    outcome = fetch_run_log(args.run_id, args.repo, args.out, attempts=args.attempts)
    if not outcome.fetched:
        print(
            f"::error::ci-rca: log file is empty or only contains a transient gh API error after "
            f"{outcome.attempts_used} attempts for run {args.run_id}. The log may not be available yet or "
            f"the run produced no output. Failing loudly so the agent is not invoked on a 0-byte log "
            f"(rec-2117 / rec-2118 / rec-2718). {outcome.diagnostic or ''}".rstrip()
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
