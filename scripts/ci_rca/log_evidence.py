"""Typed, bounded retrieval evidence for CI-RCA."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "ci-rca-log-evidence/v2"

# AC2: the legal conclusion domain for a `scope` step entry is strictly wider than
# failed_steps' closed {failure, timed_out, cancelled} -- it admits success and skipped
# (routine outcomes for a step that ran) and a null conclusion for a not-started step,
# which is routine in a cancelled job. Copying _validate_jobs' narrower enum here would
# reject every real envelope.
_SCOPE_CONCLUSIONS = {"failure", "timed_out", "cancelled", "success", "skipped", None}
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_LINES = 4000
_IDENTIFIER = re.compile(r"^[1-9][0-9]*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def recovery_url(repo: str, run_id: str) -> str:
    if not _REPOSITORY.fullmatch(repo) or not _IDENTIFIER.fullmatch(run_id):
        raise ValueError("invalid GitHub repository or run identity")
    url = f"https://github.com/{repo}/actions/runs/{run_id}"
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.query or parsed.username:
        raise ValueError("unsafe recovery URL")
    return url


def bound_text(text: str, max_bytes: int, max_lines: int) -> tuple[str, dict[str, Any]]:
    if max_bytes < 1 or max_lines < 1:
        raise ValueError("evidence limits must be positive")
    encoded = text.encode("utf-8")
    lines = text.splitlines(keepends=True)
    included: list[str] = []
    used_bytes = 0
    for line in lines:
        raw = line.encode("utf-8")
        if len(included) == max_lines or used_bytes + len(raw) > max_bytes:
            break
        included.append(line)
        used_bytes += len(raw)
    body = "".join(included)
    complete = body == text
    reason = None
    if not complete:
        reason = "line_limit" if len(included) == max_lines else "byte_limit"
    return body, {
        "max_bytes": max_bytes,
        "max_lines": max_lines,
        "observed_bytes": len(encoded),
        "observed_lines": len(lines),
        "included_bytes": used_bytes,
        "included_lines": len(included),
        "omitted_bytes": len(encoded) - used_bytes,
        "omitted_lines": len(lines) - len(included),
        "complete": complete,
        "truncation_reason": reason,
    }


_WINDOW_MARKER = "\n... [elided] ...\n"


def bound_text_windowed(text: str, max_bytes: int, max_lines: int) -> tuple[str, dict[str, Any]]:
    """Head + elision marker + tail within the SAME max_bytes/max_lines budget bound_text uses.

    Unlike bound_text (head-only truncation), this retains a TAIL sample too -- ci-rca-evidence-
    fidelity: an oversized `validate.py` log's authoritative "Failed checks:" summary is always
    the last few lines, and a head-only truncation always drops it. When `text` already fits,
    behaves identically to bound_text (complete=True, truncation_reason=None). Otherwise the
    reported observed/included/omitted counts are internally consistent (observed ==
    included + omitted, forced) but omitted_bytes/omitted_lines under-report the true elision by
    the marker's own size -- the marker itself is neither included content nor omitted content.
    """
    if max_bytes < 1 or max_lines < 1:
        raise ValueError("evidence limits must be positive")
    encoded = text.encode("utf-8")
    lines = text.splitlines(keepends=True)
    if len(encoded) <= max_bytes and len(lines) <= max_lines:
        return text, {
            "max_bytes": max_bytes,
            "max_lines": max_lines,
            "observed_bytes": len(encoded),
            "observed_lines": len(lines),
            "included_bytes": len(encoded),
            "included_lines": len(lines),
            "omitted_bytes": 0,
            "omitted_lines": 0,
            "complete": True,
            "truncation_reason": None,
        }

    marker_bytes = len(_WINDOW_MARKER.encode("utf-8"))
    marker_lines = len(_WINDOW_MARKER.splitlines(keepends=True))
    if max_bytes <= marker_bytes or max_lines <= marker_lines:
        # Budget too small to fit the elision marker itself (only reachable at test-scale
        # budgets, never at DEFAULT_MAX_BYTES/DEFAULT_MAX_LINES) -- degrade to plain head
        # truncation rather than emit a marker-only body that overflows the declared budget.
        body, limits = bound_text(text, max_bytes, max_lines)
        if not limits["complete"]:
            limits["truncation_reason"] = "head_tail_window"
        return body, limits
    budget_bytes = max(max_bytes - marker_bytes, 0)
    budget_lines = max(max_lines - marker_lines, 0)
    head_budget_bytes = budget_bytes // 2
    tail_budget_bytes = budget_bytes - head_budget_bytes
    head_budget_lines = budget_lines // 2
    tail_budget_lines = budget_lines - head_budget_lines

    head: list[str] = []
    head_used_bytes = 0
    for line in lines:
        raw = line.encode("utf-8")
        if len(head) == head_budget_lines or head_used_bytes + len(raw) > head_budget_bytes:
            break
        head.append(line)
        head_used_bytes += len(raw)

    tail_rev: list[str] = []
    tail_used_bytes = 0
    for line in reversed(lines[len(head) :]):
        raw = line.encode("utf-8")
        if len(tail_rev) == tail_budget_lines or tail_used_bytes + len(raw) > tail_budget_bytes:
            break
        tail_rev.append(line)
        tail_used_bytes += len(raw)
    tail_rev.reverse()

    body = "".join(head) + _WINDOW_MARKER + "".join(tail_rev)
    included_bytes = len(body.encode("utf-8"))
    included_lines = len(body.splitlines(keepends=True))
    observed_bytes = len(encoded)
    observed_lines = len(lines)
    return body, {
        "max_bytes": max_bytes,
        "max_lines": max_lines,
        "observed_bytes": observed_bytes,
        "observed_lines": observed_lines,
        "included_bytes": included_bytes,
        "included_lines": included_lines,
        "omitted_bytes": observed_bytes - included_bytes,
        "omitted_lines": observed_lines - included_lines,
        "complete": False,
        "truncation_reason": "head_tail_window",
    }


def _validate_limits(body: str, limits: Any) -> None:
    if not isinstance(limits, dict):
        raise ValueError("missing limit metadata")
    body_bytes = len(body.encode("utf-8"))
    body_lines = len(body.splitlines(keepends=True))
    if limits.get("included_bytes") != body_bytes or limits.get("included_lines") != body_lines:
        raise ValueError("retrieval body does not match limit metadata")
    if body_bytes > limits.get("max_bytes", 0) or body_lines > limits.get("max_lines", 0):
        raise ValueError("retrieval evidence exceeds its declared limits")
    required_counts = ("max_bytes", "max_lines", "included_bytes", "included_lines")
    if any(type(limits.get(field)) is not int or limits[field] < 0 for field in required_counts):
        raise ValueError("invalid retrieval limit count")
    complete = limits.get("complete")
    reason = limits.get("truncation_reason")
    if (
        type(complete) is not bool
        or (complete and reason is not None)
        or (
            not complete
            and reason not in {"byte_limit", "line_limit", "source_unavailable", "head_tail_window", "drain_ceiling"}
        )
    ):
        raise ValueError("inconsistent retrieval completeness metadata")
    for observed, included, omitted in (
        ("observed_bytes", "included_bytes", "omitted_bytes"),
        ("observed_lines", "included_lines", "omitted_lines"),
    ):
        observed_value, omitted_value = limits.get(observed), limits.get(omitted)
        if observed_value is None or omitted_value is None:
            if observed_value is not None or omitted_value is not None or complete:
                raise ValueError("inconsistent unknown omitted counts")
        elif type(observed_value) is not int or type(omitted_value) is not int or omitted_value < 0:
            raise ValueError("invalid observed or omitted count")
        elif observed_value != limits[included] + omitted_value:
            raise ValueError("observed and omitted counts do not balance")


def _validate_jobs(jobs: Any) -> list[int]:
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("missing failed job identity")
    job_ids: list[int] = []
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("job_id"), int) or job["job_id"] < 1:
            raise ValueError("invalid failed job identity")
        if job.get("conclusion") not in {"failure", "timed_out", "cancelled"}:
            raise ValueError("invalid failed job conclusion")
        job_ids.append(job["job_id"])
        steps = job.get("failed_steps")
        if not isinstance(steps, list):
            raise ValueError("invalid failed step identity")
        indexes: list[int] = []
        for step in steps:
            if (
                not isinstance(step, dict)
                or type(step.get("step_index")) is not int
                or step["step_index"] < 1
                or step.get("conclusion") not in {"failure", "timed_out", "cancelled"}
            ):
                raise ValueError("invalid failed step identity")
            indexes.append(step["step_index"])
        if indexes != sorted(set(indexes)):
            raise ValueError("failed steps are not sorted and unique")
    if job_ids != sorted(set(job_ids)):
        raise ValueError("failed jobs are not sorted and unique")
    return job_ids


def _validate_selection(selection: Any, job_ids: list[int], limits: dict[str, Any]) -> None:
    if not isinstance(selection, dict):
        raise ValueError("missing fallback selection metadata")
    queried = selection.get("queried_job_ids")
    unqueried = selection.get("unqueried_job_ids")
    if (
        not isinstance(queried, list)
        or not isinstance(unqueried, list)
        or any(type(item) is not int for item in queried + unqueried)
        or sorted(queried + unqueried) != job_ids
        or set(queried) & set(unqueried)
    ):
        raise ValueError("invalid fallback job coverage")
    expected_reason = "aggregate_limit" if unqueried else None
    if selection.get("unqueried_reason") != expected_reason:
        raise ValueError("invalid unqueried job reason")
    if unqueried and (
        limits["complete"]
        or limits["truncation_reason"]
        not in {"byte_limit", "line_limit", "source_unavailable", "head_tail_window", "drain_ceiling"}
        or any(limits[field] is not None for field in ("observed_bytes", "observed_lines", "omitted_bytes", "omitted_lines"))
    ):
        raise ValueError("unqueried fallback jobs require unknown incomplete evidence metadata")


def _validate_scope(
    scope: Any,
    failed_jobs: list[dict[str, Any]],
    retrieval_path: Any,
    fallback_selection: dict[str, Any],
) -> None:
    """AC1/AC6: `scope` declares, per failed job, EVERY executed step as
    {step_index, conclusion, log_retrieved} -- a second per-job structure parallel to
    failed_jobs[].failed_steps. Rejects an absent scope, a per-job step set that is not a
    superset of that job's failed_steps, unsorted/duplicate indexes, conclusions disagreeing
    with failed_steps, or log_retrieved flags contradicting retrieval_path/fallback_selection.
    """
    if not isinstance(scope, list):
        raise ValueError("missing evidence scope")
    by_job: dict[int, list[dict[str, Any]]] = {}
    for entry in scope:
        if not isinstance(entry, dict) or type(entry.get("job_id")) is not int:
            raise ValueError("invalid evidence scope job entry")
        job_id = entry["job_id"]
        if job_id in by_job:
            raise ValueError("duplicate evidence scope job entry")
        steps = entry.get("steps")
        if not isinstance(steps, list):
            raise ValueError("invalid evidence scope step table")
        indexes: list[int] = []
        parsed: list[dict[str, Any]] = []
        for step in steps:
            if (
                not isinstance(step, dict)
                or type(step.get("step_index")) is not int
                or step["step_index"] < 1
                or step.get("conclusion") not in _SCOPE_CONCLUSIONS
                or type(step.get("log_retrieved")) is not bool
            ):
                raise ValueError("invalid evidence scope step entry")
            indexes.append(step["step_index"])
            parsed.append(step)
        if indexes != sorted(set(indexes)):
            raise ValueError("evidence scope steps are not sorted and unique")
        by_job[job_id] = parsed

    expected_job_ids = sorted(job["job_id"] for job in failed_jobs)
    if sorted(by_job) != expected_job_ids:
        raise ValueError("evidence scope job set does not match failed jobs")

    queried = set(fallback_selection.get("queried_job_ids", []))
    for job in failed_jobs:
        job_id = job["job_id"]
        by_index = {step["step_index"]: step for step in by_job[job_id]}
        for failed_step in job.get("failed_steps", []):
            scope_step = by_index.get(failed_step["step_index"])
            if scope_step is None or scope_step["conclusion"] != failed_step["conclusion"]:
                raise ValueError("evidence scope is not a superset of failed steps")
        job_retrieved = job_id in queried
        for step in by_job[job_id]:
            if retrieval_path == "primary":
                expected = step["conclusion"] in {"failure", "timed_out", "cancelled"}
            else:
                expected = job_retrieved
            if step["log_retrieved"] != expected:
                raise ValueError("log_retrieved contradicts retrieval_path and fallback_selection")


def validate_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("invalid retrieval evidence schema")
    body = value.get("body")
    if not isinstance(body, str) or not body:
        raise ValueError("retrieval evidence body is empty")
    identity = value.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("missing retrieval identity")
    expected = recovery_url(identity.get("repository", ""), str(identity.get("run_id", "")))
    recovery = value.get("recovery")
    if not isinstance(recovery, dict) or recovery.get("url") != expected:
        raise ValueError("invalid recovery reference")
    if recovery.get("state") not in {"available", "expired"}:
        raise ValueError("invalid recovery reference")
    if value.get("retrieval_path") not in {"primary", "fallback"}:
        raise ValueError("invalid retrieval path")
    limits = value.get("limits")
    _validate_limits(body, limits)
    job_ids = _validate_jobs(value.get("failed_jobs"))
    _validate_selection(value.get("fallback_selection"), job_ids, limits)
    _validate_scope(value.get("scope"), value.get("failed_jobs"), value.get("retrieval_path"), value.get("fallback_selection"))
    return value


def read_envelope(path: Path) -> dict[str, Any]:
    return validate_envelope(json.loads(path.read_text(encoding="utf-8")))


def publish_envelope(path: Path, envelope: dict[str, Any]) -> None:
    validate_envelope(envelope)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def extract_body(envelope_path: Path, body_path: Path) -> None:
    envelope = read_envelope(envelope_path)
    if envelope["recovery"]["state"] != "available":
        raise ValueError("raw recovery evidence has expired")
    body_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{body_path.name}.", dir=body_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(envelope["body"])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, body_path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path, required=True)
    parser.add_argument("--extract-body", type=Path)
    args = parser.parse_args(argv)
    try:
        read_envelope(args.validate)
        if args.extract_body:
            extract_body(args.validate, args.extract_body)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"::error::ci-rca: invalid bounded retrieval evidence: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
