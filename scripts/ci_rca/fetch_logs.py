"""Fetch a failed Actions run into a bounded, typed CI-RCA evidence envelope."""

from __future__ import annotations

import argparse
import json
import re
import selectors
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional, cast

from scripts.ci_rca.log_evidence import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    SCHEMA,
    bound_text,
    publish_envelope,
    recovery_url,
)

_TRANSIENT_ERROR_RE = re.compile(r"^(?:failed to get (?:jobs|run)\b|HTTP 5\d\d\b|Service Unavailable)", re.I | re.M)
_Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class FetchOutcome:
    fetched: bool
    attempts_used: int
    diagnostic: Optional[str] = None


@dataclass
class LogResult:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool
    truncation_reason: str | None


def _run(runner: _Runner, command: list[str]) -> subprocess.CompletedProcess:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _run_log(command: list[str], max_bytes: int, max_lines: int) -> LogResult:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    stderr = bytearray()
    lines = 0
    truncated = False
    reason = None
    while selector.get_map() and not truncated:
        for key, _ in selector.select():
            stream = cast(BinaryIO, key.fileobj)
            chunk = stream.read(1 if key.data == "stdout" else 8192)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            if key.data == "stderr":
                if len(stderr) < 8192:
                    stderr.extend(chunk[: 8192 - len(stderr)])
                continue
            if len(stdout) == max_bytes:
                truncated, reason = True, "byte_limit"
                break
            if lines == max_lines:
                truncated, reason = True, "line_limit"
                break
            stdout.extend(chunk)
            if chunk == b"\n":
                lines += 1
    try:
        if truncated:
            process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    finally:
        selector.close()
    return LogResult(
        returncode=0 if truncated else process.returncode,
        stdout=bytes(stdout).decode("utf-8", errors="ignore"),
        stderr=bytes(stderr).decode("utf-8", errors="replace"),
        truncated=truncated,
        truncation_reason=reason,
    )


def _failed_jobs(payload: str) -> list[dict[str, Any]]:
    decoded = json.loads(payload)
    jobs = decoded.get("jobs") if isinstance(decoded, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("GitHub response has no jobs array")
    selected: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("conclusion") not in {"failure", "timed_out", "cancelled"}:
            continue
        job_id = job.get("databaseId")
        if not isinstance(job_id, int) or job_id < 1:
            raise ValueError("failed job has no numeric database id")
        steps = job.get("steps", [])
        failed_steps = [
            {"step_index": index, "conclusion": step["conclusion"]}
            for index, step in enumerate(steps, 1)
            if isinstance(step, dict) and step.get("conclusion") in {"failure", "timed_out", "cancelled"}
        ]
        selected.append({"job_id": job_id, "conclusion": job["conclusion"], "failed_steps": failed_steps})
    selected.sort(key=lambda item: item["job_id"])
    if not selected:
        raise ValueError("run metadata contains no failed jobs")
    return selected


def _diagnose(*stderrs: str) -> str:
    for stderr in stderrs:
        match = _TRANSIENT_ERROR_RE.search(stderr or "")
        if match:
            return f"gh reported a transient error: {match.group(0)!r}"
    return "log empty, unavailable, or gh reported a non-transient error"


def _fallback_logs(
    run_id: str,
    repo: str,
    jobs: list[dict[str, Any]],
    injected_runner: Optional[_Runner],
    max_bytes: int,
    max_lines: int,
) -> tuple[str, list[int], list[str], bool, str | None]:
    fragments: list[str] = []
    queried: list[int] = []
    errors: list[str] = []
    truncated = False
    reason = None
    for job in jobs:
        command = ["gh", "run", "view", run_id, "--repo", repo, "--job", str(job["job_id"]), "--log"]
        remaining = max_bytes - len("".join(fragments).encode("utf-8"))
        remaining_lines = max_lines - len("".join(fragments).splitlines(keepends=True))
        if remaining < 1 or remaining_lines < 1:
            return "".join(fragments), queried, errors, True, "byte_limit" if remaining < 1 else "line_limit"
        result = (
            _run(injected_runner, command) if injected_runner is not None else _run_log(command, remaining, remaining_lines)
        )
        queried.append(job["job_id"])
        if result.returncode != 0 or not result.stdout:
            errors.append(result.stderr)
            continue
        fragments.append(result.stdout)
        truncated = truncated or bool(getattr(result, "truncated", False))
        reason = getattr(result, "truncation_reason", None) or reason
    return "".join(fragments), queried, errors, truncated, reason


def fetch_run_log(
    run_id: str,
    repo: str,
    out_path: Path,
    attempts: int = 3,
    sleep_fn: Optional[Callable[[int], None]] = None,
    runner: Optional[_Runner] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
) -> FetchOutcome:
    if max_bytes < 1 or max_lines < 1:
        raise ValueError("evidence limits must be positive")
    sleep_fn = sleep_fn or time.sleep
    injected_runner = runner
    runner = runner or subprocess.run
    out_path.unlink(missing_ok=True)
    diagnostic = None
    for attempt in range(1, attempts + 1):
        metadata = _run(runner, ["gh", "run", "view", run_id, "--repo", repo, "--json", "jobs"])
        if metadata.returncode != 0:
            diagnostic = _diagnose(metadata.stderr)
        else:
            try:
                jobs = _failed_jobs(metadata.stdout)
            except (ValueError, json.JSONDecodeError) as exc:
                diagnostic = f"invalid failed-job metadata: {exc}"
            else:
                primary_command = ["gh", "run", "view", run_id, "--repo", repo, "--log-failed"]
                primary = (
                    _run(injected_runner, primary_command)
                    if injected_runner is not None
                    else _run_log(primary_command, max_bytes, max_lines)
                )
                log = primary.stdout if primary.returncode == 0 else ""
                transport_truncated = bool(getattr(primary, "truncated", False))
                transport_reason = getattr(primary, "truncation_reason", None)
                retrieval_path = "primary"
                fallback_errors: list[str] = []
                queried_job_ids: list[int] = []
                if not log:
                    retrieval_path = "fallback"
                    log, queried_job_ids, fallback_errors, transport_truncated, transport_reason = _fallback_logs(
                        run_id, repo, jobs, injected_runner, max_bytes, max_lines
                    )
                    if fallback_errors:
                        log = ""
                else:
                    queried_job_ids = [job["job_id"] for job in jobs]
                if log:
                    body, limits = bound_text(log, max_bytes, max_lines)
                    if transport_truncated:
                        limits.update(
                            complete=False,
                            truncation_reason=transport_reason or "source_unavailable",
                            observed_bytes=None,
                            observed_lines=None,
                            omitted_bytes=None,
                            omitted_lines=None,
                        )
                    if body:
                        envelope = {
                            "schema": SCHEMA,
                            "identity": {"repository": repo, "run_id": int(run_id)},
                            "failed_jobs": jobs,
                            "retrieval_path": retrieval_path,
                            "fallback_selection": {
                                "queried_job_ids": queried_job_ids,
                                "unqueried_job_ids": [job["job_id"] for job in jobs if job["job_id"] not in queried_job_ids],
                                "unqueried_reason": (
                                    "aggregate_limit"
                                    if retrieval_path == "fallback" and len(queried_job_ids) < len(jobs)
                                    else None
                                ),
                            },
                            "body": body,
                            "limits": limits,
                            "recovery": {"url": recovery_url(repo, run_id), "state": "available"},
                        }
                        publish_envelope(out_path, envelope)
                        return FetchOutcome(True, attempt)
                diagnostic = _diagnose(primary.stderr, *fallback_errors)
        if attempt < attempts:
            sleep_fn(attempt * 10)
    return FetchOutcome(False, attempts, diagnostic)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch bounded failed-run evidence for CI-RCA.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    args = parser.parse_args(argv)
    try:
        outcome = fetch_run_log(
            args.run_id, args.repo, args.out, args.attempts, max_bytes=args.max_bytes, max_lines=args.max_lines
        )
    except (OSError, ValueError) as exc:
        outcome = FetchOutcome(False, 0, str(exc))
    if outcome.fetched:
        return 0
    print(
        "::error::ci-rca: bounded log evidence unavailable; refusing agent invocation "
        f"after {outcome.attempts_used} attempts (rec-2117 / rec-2118 / rec-2718). {outcome.diagnostic or ''}".rstrip()
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
