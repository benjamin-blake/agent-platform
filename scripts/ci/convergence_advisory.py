#!/usr/bin/env python3
"""Testable classifier for the advisory terraform-converged status (Decision 172 PR-2).

Extracted from terraform-apply-sandbox.yml's advisory-status inline `run:` body (Decision 162 R3
thin-adapter obligation): the pre-extraction body read the convergence record with
`aws s3 cp ... 2>/dev/null || echo ""` and treated ANY read failure -- a genuinely absent record
(NoSuchKey) OR a credential/authorization failure -- identically as "pass-on-absent" GREEN. That
conflation is exactly what published a green `terraform-converged` status throughout the
2026-08-15 OIDC outage this plan recovers from, even though main was in fact unverifiable, not
converged.

classify() discriminates SIX mutually-exclusive outcomes:
  1. NoSuchKey / genuinely absent record -> success, pass-on-absent (first-apply-allowed).
  2. Any OTHER read failure (credential/authorization) -> error, UNVERIFIED -- never a green.
  3. Empty response body -> error, UNVERIFIED (today folds into pass-on-absent green; must not).
  4. Unparseable / non-object JSON -> error, UNVERIFIED (today aborts under inherited errexit,
     reding a job that must never red; here it degrades to a printed state instead).
  5. status == "red" -> failure (advisory only; never a required check, Decision 83).
  6. status != "red" -> success, distinguishing a pending_gated marker (DEP-11) from plain green.

classify() is a pure function of (return code, stderr text, response body) -- no I/O, no AWS
call -- so all six outcomes are unit-provable (tests/test_convergence_advisory.py). The S3 read
itself stays in the workflow's `run:` body, reusing the NoSuchKey-vs-other-error pattern already
at terraform-drift.yml:198-225 rather than inventing a second one.

main() never raises (Decision 55/83: the advisory-status job must never red a PR) -- any
unexpected exception classifies as `error`/UNVERIFIED rather than propagating, per this plan's
constraint that the job stays green by the classifier never raising, not by adding
continue-on-error to the adapter step.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

SUCCESS = "success"
FAILURE = "failure"
ERROR = "error"

_NOT_FOUND_RE = re.compile(r"NoSuchKey|Not Found|404", re.IGNORECASE)


def classify(rc: int, stderr: str, body: str) -> tuple[str, str]:
    """Classify a convergence-record read into (state, description) for the
    `terraform-converged` commit status. See module docstring for the six outcomes."""
    if rc != 0:
        if _NOT_FOUND_RE.search(stderr or ""):
            return (
                SUCCESS,
                "No convergence record yet (pass-on-absent); main treated as converged. Advisory only.",
            )
        return (
            ERROR,
            "UNVERIFIED -- could not read the convergence record (credential/authorization "
            "failure), not evidence of convergence. Advisory only.",
        )

    text = (body or "").strip()
    if not text:
        return (
            ERROR,
            "UNVERIFIED -- convergence record body is empty, not evidence of pass-on-absent green. Advisory only.",
        )

    try:
        record = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return (
            ERROR,
            "UNVERIFIED -- convergence record could not be parsed as JSON, not evidence of convergence. Advisory only.",
        )
    if not isinstance(record, dict):
        return (
            ERROR,
            "UNVERIFIED -- convergence record JSON is not an object, not evidence of convergence. Advisory only.",
        )

    status = record.get("status", "")
    if status == "red":
        commit = record.get("commit_sha", "")
        return (
            FAILURE,
            f"main is non-converged (last sandbox apply RED at {commit}). Advisory only -- not a required check.",
        )

    pending_gated = record.get("pending_gated")
    pending_sha = pending_gated.get("commit_sha") if isinstance(pending_gated, dict) else None
    if pending_sha:
        return (
            SUCCESS,
            f"main is pending-gated (a routed change at {pending_sha} awaits gated-apply "
            "reviewer approval; not a failure). Advisory only.",
        )

    return SUCCESS, "main is converged (last sandbox apply GREEN). Advisory only."


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint: read RC / S3_STDERR / REC_JSON from the environment, print
    "<state>\\n<description>" for the calling `run:` body to parse.

    Always exits 0 and never raises -- classification itself must never fail the advisory-status
    job (Decision 83: it must never red a PR).
    """
    del argv  # no positional args; env-var contract only (mirrors the calling run: body's shape)
    try:
        rc_raw = os.environ.get("RC", "0")
        try:
            rc = int(rc_raw)
        except ValueError:
            rc = 1
        stderr = os.environ.get("S3_STDERR", "")
        body = os.environ.get("REC_JSON", "")
        state, description = classify(rc, stderr, body)
    except Exception as exc:  # noqa: BLE001 -- never raise; the advisory job must stay green (Decision 83)
        state, description = (
            ERROR,
            f"UNVERIFIED -- convergence_advisory classifier raised {type(exc).__name__}; "
            "treating as unverified rather than crashing the advisory-status job.",
        )
    print(state)
    print(description)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
