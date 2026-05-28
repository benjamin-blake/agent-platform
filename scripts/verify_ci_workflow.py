"""VP helper: structural assertions for ci-workflow-restructure verification plan."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


def _load(path: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text())
    # PyYAML 1.1 quirk: the bare key `on:` may parse as Python True.
    # Normalise the key so callers can always use data["on"].
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


def _get_steps_text(job: dict[str, Any]) -> str:
    """Flatten all 'run' values in a job's steps into a single string for substring search."""
    parts = []
    for step in job.get("steps", []):
        if run := step.get("run"):
            parts.append(run)
        if uses := step.get("uses"):
            parts.append(uses)
    return "\n".join(parts)


def _check_jobs_and_flags() -> None:
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    assert "validate-python" not in jobs, "Old validate-python job still present in ci.yml"
    assert "pr-validate" in jobs, "pr-validate job missing from ci.yml"
    assert "main-validate" in jobs, "main-validate job missing from ci.yml"

    pr_job = jobs["pr-validate"]
    main_job = jobs["main-validate"]

    assert pr_job.get("if") == "github.event_name == 'pull_request'", f"pr-validate.if is wrong: {pr_job.get('if')!r}"
    assert main_job.get("if") == "github.event_name == 'push'", f"main-validate.if is wrong: {main_job.get('if')!r}"

    pr_steps = _get_steps_text(pr_job)
    main_steps = _get_steps_text(main_job)

    assert "--pre" in pr_steps, "pr-validate steps do not contain --pre"
    assert "--pre" not in main_steps, "main-validate steps contain --pre (should not)"


def _check_concurrency() -> None:
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    # terraform-validate intentionally has no ci-runner concurrency group:
    # within a single workflow run, two jobs sharing a concurrency group
    # cancel each other instead of queuing. The runner serialises at host
    # level, so the cross-workflow group is only needed on pr/main jobs.
    for job_name in ("pr-validate", "main-validate"):
        job = jobs.get(job_name)
        assert job is not None, f"Job {job_name!r} not found in ci.yml"
        concurrency = job.get("concurrency")
        assert concurrency is not None, f"{job_name} has no concurrency block"
        assert concurrency.get("group") == "ci-runner", (
            f"{job_name} concurrency.group is {concurrency.get('group')!r}, expected 'ci-runner'"
        )
        assert concurrency.get("cancel-in-progress") is False, f"{job_name} concurrency.cancel-in-progress is not False"


def _check_fetch_depth() -> None:
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    pr_job = jobs.get("pr-validate", {})
    main_job = jobs.get("main-validate", {})

    pr_checkout = None
    main_checkout = None

    for step in pr_job.get("steps", []):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            pr_checkout = step
            break

    for step in main_job.get("steps", []):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            main_checkout = step
            break

    assert pr_checkout is not None, "pr-validate has no checkout step"
    assert main_checkout is not None, "main-validate has no checkout step"

    pr_with = pr_checkout.get("with", {}) or {}
    assert pr_with.get("fetch-depth") == 0, f"pr-validate checkout fetch-depth is {pr_with.get('fetch-depth')!r}, expected 0"

    main_with = main_checkout.get("with", {}) or {}
    assert "fetch-depth" not in main_with, (
        f"main-validate checkout has unexpected fetch-depth: {main_with.get('fetch-depth')!r}"
    )


def _check_canary() -> None:
    data = _load(".github/workflows/main-canary.yml")

    assert data.get("name") == "Main Canary", f"main-canary.yml name is {data.get('name')!r}, expected 'Main Canary'"

    on = data.get("on", {})
    schedule = on.get("schedule", [])
    assert len(schedule) >= 1, "main-canary.yml has no schedule entries"
    assert schedule[0].get("cron") == "0 */3 * * *", f"canary cron is {schedule[0].get('cron')!r}, expected '0 */3 * * *'"
    assert "workflow_dispatch" in on, "main-canary.yml missing workflow_dispatch trigger"

    jobs = data.get("jobs", {})
    assert len(jobs) >= 1, "main-canary.yml has no jobs"
    canary_job = next(iter(jobs.values()))

    runs_on = canary_job.get("runs-on")
    assert isinstance(runs_on, list), f"canary runs-on must be a list, got {type(runs_on).__name__}: {runs_on!r}"
    assert runs_on == ["self-hosted", "linux"], f"canary runs-on is {runs_on!r}, expected ['self-hosted', 'linux']"

    concurrency = canary_job.get("concurrency")
    assert concurrency is not None, "canary job has no concurrency block"
    assert concurrency.get("group") == "ci-runner", (
        f"canary concurrency.group is {concurrency.get('group')!r}, expected 'ci-runner'"
    )
    assert concurrency.get("cancel-in-progress") is False, "canary concurrency.cancel-in-progress is not False"

    steps_text = _get_steps_text(canary_job)
    assert "scripts.validate" in steps_text, "canary steps do not reference scripts.validate"
    assert "--pre" not in steps_text, "canary steps contain --pre (should not)"


def _check_ci_rca_filter() -> None:
    canary_data = _load(".github/workflows/main-canary.yml")
    canary_name = canary_data.get("name")
    assert canary_name, "main-canary.yml has no name field"

    rca_data = _load(".github/workflows/ci-rca.yml")
    on = rca_data.get("on", {})
    workflow_run = on.get("workflow_run", {})
    workflows = workflow_run.get("workflows", [])

    assert "CI" in workflows, f"ci-rca.yml workflows list missing 'CI': {workflows}"
    assert canary_name in workflows, f"ci-rca.yml workflows list missing {canary_name!r}: {workflows}"


_COMMANDS = {
    "jobs-and-flags": _check_jobs_and_flags,
    "concurrency": _check_concurrency,
    "fetch-depth": _check_fetch_depth,
    "canary": _check_canary,
    "ci-rca-filter": _check_ci_rca_filter,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in _COMMANDS:
        print(f"Usage: verify_ci_workflow.py <{'|'.join(_COMMANDS)}>", file=sys.stderr)
        sys.exit(1)

    fn = _COMMANDS[sys.argv[1]]
    try:
        fn()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
