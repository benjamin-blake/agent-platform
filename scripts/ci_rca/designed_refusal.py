"""Designed-refusal fail-closed skip predicate for ci-rca.yml (PLAN-ci-rca-ops-plane-coverage).

Some watched workflows can fail via a DESIGNED refusal -- a gate that deliberately blocks a step
under a known, self-documenting condition (e.g. deploy-ducklake-lambdas' reconcile-gate job, the
Decision 88 reconcile-pending predicate) rather than a genuine defect. Filing a fresh
priority=critical ci_rca rec for every such refusal would mint a rec storm and a planning-queue
wedge (Decision 73 L5/L6) for a condition that already self-documents and already blocks the
deploy -- see PLAN-ci-rca-ops-plane-coverage's WATCHED-SET ADJUDICATION context, and rec-2854 for
the alarm-not-gate monitor lane that covers the STANDING refusal instead.

Fail-closed is the point (Decision 55): this predicate returns skip=true ONLY when the resolved
failing-job set for the run is non-empty AND every member is a DECLARED designed-refusal job for
that workflow slug. Any uncertainty -- an empty failing-job set, an unparseable/`{}` jobs file, or
any undeclared failing job (even alongside a declared one) -- returns skip=false, so the ci-rca
agent still runs and files.

Mirrors scripts/ci_rca/convergence_dedup.py exactly: a thin invocation-only shell, no network call
of its own -- it consumes the /tmp/ci-rca-jobs.json the existing "Fetch jobs JSON" step already
writes (continue-on-error, `{}` on failure -- a concrete producer for the fail-closed input).

CLI usage (invoked by ci-rca.yml's designed-refusal skip step):
    bin/venv-python -m scripts.ci_rca.designed_refusal \\
        --jobs-json /tmp/ci-rca-jobs.json --workflow-slug deploy-ducklake-lambdas
Prints skip=true|false.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Declared workflow slug -> designed-refusal job NAME set. The job NAME is checked (not a step
# name) because the failing-job granularity is what the jobs JSON exposes; none of
# deploy-ducklake-lambdas.yml's jobs set a `name:` key, so the API display name equals the job id.
DESIGNED_REFUSAL_JOBS: dict[str, frozenset[str]] = {
    "deploy-ducklake-lambdas": frozenset({"reconcile-gate"}),
}


def resolve_failing_jobs(jobs_payload: dict) -> set[str]:
    """Extract the set of job NAMES whose conclusion is 'failure' from a parsed jobs JSON.

    `jobs_payload` is the parsed `gh run view --json jobs` response shape: {"jobs": [{"name":
    ..., "conclusion": ...}, ...]}. Any other shape (empty dict, missing/non-list "jobs" key)
    resolves to an empty set -- the fail-closed default, never an exception.
    """
    if not isinstance(jobs_payload, dict):
        return set()
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        return set()
    return {
        job.get("name") for job in jobs if isinstance(job, dict) and job.get("conclusion") == "failure" and job.get("name")
    }


def is_designed_refusal(workflow_slug: str, jobs_payload: dict) -> bool:
    """True iff every failing job in this run is a DECLARED designed-refusal job for the slug.

    Fail-closed: an empty failing-job set (nothing resolved -- uncertain, never treated as "no
    genuine failure") and any undeclared failing job co-occurring with a declared one both return
    False.
    """
    failing = resolve_failing_jobs(jobs_payload)
    if not failing:
        return False
    declared = DESIGNED_REFUSAL_JOBS.get(workflow_slug, frozenset())
    return failing.issubset(declared)


def _load_jobs_payload(jobs_json: Path) -> dict:
    """Read + parse the jobs JSON file. Any read/parse failure resolves to {} (fail-closed)."""
    try:
        text = jobs_json.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Designed-refusal fail-closed skip predicate for ci-rca.yml.")
    parser.add_argument(
        "--jobs-json",
        type=Path,
        default=Path("/tmp/ci-rca-jobs.json"),
        help="Path to the jobs JSON written by ci-rca.yml's Fetch jobs JSON step.",
    )
    parser.add_argument(
        "--workflow-slug",
        required=True,
        help="The slugified workflow name (ci-rca.yml's Resolve run metadata workflow_slug output).",
    )
    args = parser.parse_args(argv)

    jobs_payload = _load_jobs_payload(args.jobs_json)
    skip = is_designed_refusal(args.workflow_slug, jobs_payload)
    print(f"skip={'true' if skip else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
