"""VP helper: structural assertions for ci-workflow-restructure verification plan."""

from __future__ import annotations

import re
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


def _is_truthy_concurrency_flag(value: Any) -> bool:
    """Accept a YAML bool True or a templated/string truthy value ("true", "${{ true }}").

    GitHub Actions `cancel-in-progress` is normally a bare YAML boolean (PyYAML loads it as
    Python True), but may also appear quoted or as a `${{ ... }}` expression -- both of which
    PyYAML loads as plain strings.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    return bool(re.fullmatch(r"\$\{\{\s*true\s*\}\}", normalized))


def _check_concurrency() -> None:
    """VTS-11: pr-validate must cancel superseded runs on a per-PR key (so a force-pushed PR
    doesn't leave a stale run occupying a required check); main-validate -- the merge-to-main
    gate -- must NOT cancel in-flight runs (drift-canary + per-commit RCA role, dec-73 L8). Also
    retains the CD.21 ci-runner-serialisation-group-absence anti-regression guard for both jobs.
    """
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    # CD.21: the self-hosted runner is retired; each job runs on its own
    # isolated GitHub-hosted runner, so the ci-runner serialisation group
    # is obsolete. Assert it is absent as an anti-regression guard.
    for job_name in ("pr-validate", "main-validate"):
        job = jobs.get(job_name)
        assert job is not None, f"Job {job_name!r} not found in ci.yml"
        concurrency = job.get("concurrency") or {}
        assert concurrency.get("group") != "ci-runner", (
            f"{job_name} still declares obsolete concurrency.group 'ci-runner' (retired by CD.21)"
        )

    # pr-validate: a superseded run (e.g. after a force-push) must be cancelled, keyed
    # per-PR so distinct PRs never cross-cancel each other.
    pr_job = jobs.get("pr-validate") or {}
    pr_concurrency = pr_job.get("concurrency") or {}
    pr_group = str(pr_concurrency.get("group", ""))
    assert any(key in pr_group for key in ("github.ref", "head_ref", "pull_request")), (
        f"pr-validate concurrency.group is not per-PR keyed (expected github.ref / head_ref / "
        f"pull_request in the group): {pr_group!r}"
    )
    assert _is_truthy_concurrency_flag(pr_concurrency.get("cancel-in-progress")), (
        f"pr-validate concurrency.cancel-in-progress is not truthy: {pr_concurrency.get('cancel-in-progress')!r}"
    )

    # main-validate: the merge-to-main gate must run to completion even if superseded --
    # cancel-in-progress must stay absent/false.
    main_job = jobs.get("main-validate") or {}
    main_concurrency = main_job.get("concurrency") or {}
    assert not _is_truthy_concurrency_flag(main_concurrency.get("cancel-in-progress")), (
        f"main-validate concurrency.cancel-in-progress is truthy (must not cancel in-flight main "
        f"runs): {main_concurrency.get('cancel-in-progress')!r}"
    )


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
    assert runs_on == "ubuntu-latest", f"canary runs-on is {runs_on!r}, expected 'ubuntu-latest' (CD.21)"

    steps_text = _get_steps_text(canary_job)
    assert "scripts.validate" in steps_text, "canary steps do not reference scripts.validate"
    assert "--pre" not in steps_text, "canary steps contain --pre (should not)"


# PLAN-ci-rca-ops-plane-coverage: the required-membership floor for ci-rca.yml's
# workflow_run.workflows filter. "Main Canary" is resolved dynamically from main-canary.yml's own
# name field below rather than hardcoded here, so a canary rename does not desync the two checks.
# This is a FLOOR, not an exact-set assertion (growth beyond these entries is governed by the
# per-entry adjudication requirement in docs/contracts/ci-rca-lifecycle.yaml, not by this guard) --
# its job is only to prevent silent REMOVAL, per rec-2849 (terraform-apply-sandbox was in the
# filter but unguarded here, so the CD.35 wiring could have been deleted silently).
_REQUIRED_CI_RCA_WORKFLOWS = ("CI", "terraform-apply-sandbox", "rec-autoclose", "deploy-ducklake-lambdas")


def _check_ci_rca_filter() -> None:
    canary_data = _load(".github/workflows/main-canary.yml")
    canary_name = canary_data.get("name")
    assert canary_name, "main-canary.yml has no name field"

    rca_data = _load(".github/workflows/ci-rca.yml")
    on = rca_data.get("on", {})
    workflow_run = on.get("workflow_run", {})
    workflows = workflow_run.get("workflows", [])

    required = (*_REQUIRED_CI_RCA_WORKFLOWS, canary_name)
    missing = [w for w in required if w not in workflows]
    assert not missing, f"ci-rca.yml workflows list missing required entries {missing}: {workflows}"

    assert len(workflows) == len(set(workflows)), f"ci-rca.yml workflows list has duplicate entries: {workflows}"

    rca_job_if = rca_data.get("jobs", {}).get("rca", {}).get("if", "")
    assert "head_branch" in rca_job_if, (
        f"ci-rca.yml rca job if: missing main-branch gate (head_branch not found): {rca_job_if!r}"
    )
    assert "default_branch" in rca_job_if, (
        f"ci-rca.yml rca job if: missing main-branch gate (default_branch not found): {rca_job_if!r}"
    )

    agent_doc = Path(".claude/agents/scheduled/ci-rca.md").read_text(encoding="utf-8")
    assert "FILED:" in agent_doc, (
        ".claude/agents/scheduled/ci-rca.md missing FILED: marker contract -- "
        "the prompt rewrite plan must preserve this signal for the workflow parser"
    )


def _check_apply_rca_fallback() -> None:
    """Assert both sandbox-apply jobs self-dispatch ci-rca on a re-run failure.

    PLAN-gated-apply-rca-trigger: ci-rca.yml's workflow_run trigger is not reliably
    re-dispatched on a manual re-run's completion (confirmed gap: run 28379330706,
    gated-apply, run_attempt=2, zero RCA signal). Each of apply-sandbox and gated-apply
    must carry actions: write and a failure-path step that dispatches ci-rca.yml, gated
    on run_attempt so the workflow_run-covered attempt-1 path does not double-fire.
    """
    data = _load(".github/workflows/terraform-apply-sandbox.yml")
    jobs = data.get("jobs", {})

    for job_name in ("apply-sandbox", "gated-apply"):
        job = jobs.get(job_name)
        assert job is not None, f"Job {job_name!r} not found in terraform-apply-sandbox.yml"

        permissions = job.get("permissions", {}) or {}
        assert permissions.get("actions") == "write", (
            f"{job_name} is missing 'actions: write' permission required for the ci-rca self-dispatch step"
        )

        dispatch_step = None
        for step in job.get("steps", []):
            step_if = str(step.get("if", ""))
            step_run = str(step.get("run", ""))
            if "failure()" in step_if and "run_attempt" in step_if and "gh workflow run ci-rca.yml" in step_run:
                dispatch_step = step
                break

        assert dispatch_step is not None, (
            f"{job_name} is missing a failure()-gated, run_attempt-gated step that dispatches ci-rca.yml "
            "via 'gh workflow run ci-rca.yml'"
        )


_MODULE_INVOCATION_RE = re.compile(
    r"(?:python[0-9.]*\s+-m\s+scripts\.([A-Za-z_][A-Za-z0-9_]*)|scripts/([A-Za-z_][A-Za-z0-9_]*)\.py)"
)
_CHECK_LIKE_RE = re.compile(r"^(validate|verify|check)")


def _check_validate_single_source() -> None:
    """Decision 80: ci.yml's only validation entrypoint is `scripts.validate`.

    Every check-like `python -m scripts.<mod>` / `scripts/<mod>.py` invocation in
    ci.yml (module name matching ^(validate|verify|check)) must resolve to the
    scripts.validate registry runner -- not a bespoke module bypassing it.
    """
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    violations = []
    for job_name, job in jobs.items():
        steps_text = _get_steps_text(job)
        for match in _MODULE_INVOCATION_RE.finditer(steps_text):
            module = match.group(1) or match.group(2)
            if _CHECK_LIKE_RE.match(module) and module != "validate":
                violations.append(f"{job_name}: scripts.{module}")

    assert not violations, f"ci.yml invokes check-like module(s) other than scripts.validate: {violations}"


def _admits_pull_request(if_expr: Any) -> bool:
    """A job is PR-gating unless its `if` is a push-only guard.

    A job with NO `if` key runs on every triggering event, including pull_request --
    that makes it PR-gating too (e.g. terraform-validate). A job whose `if` mentions
    `push` but not `pull_request` is treated as a push-only guard and excluded. An
    `if` mentioning neither (e.g. a schedule/workflow_dispatch-only guard) defaults
    to PR-gating -- the conservative direction, since excluding a job that actually
    can run on pull_request would silently create an ungated merge path.
    """
    if if_expr is None:
        return True
    if_str = str(if_expr)
    if "pull_request" in if_str:
        return True
    if "push" in if_str:
        return False
    return True


def _check_signal_green_needs() -> None:
    """Every PR-gating job in ci.yml must be listed in signal-green.needs."""
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    signal_green = jobs.get("signal-green")
    assert signal_green is not None, "signal-green job missing from ci.yml"

    needs = signal_green.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]

    missing = [
        job_name
        for job_name, job in jobs.items()
        if job_name != "signal-green" and _admits_pull_request(job.get("if")) and job_name not in needs
    ]

    assert not missing, f"PR-gating job(s) missing from signal-green.needs: {missing}"


def _check_terraform_apply_concurrency() -> None:
    """T2.35 hardening: apply-sandbox's concurrency group must be event-keyed, and
    reconcile.yml must keep sharing the push/dispatch key.

    Regression this guards against: a config that would permit concurrent applies against
    shared tfstate -- either within terraform-apply-sandbox.yml (a bare non-conditional group,
    a missing per-PR key, or cancel-in-progress not gated on pull_request) or across it and
    reconcile.yml (reconcile.yml drifting to a different push/dispatch group, silently
    decoupling the two workflows' serialization).
    """
    apply_data = _load(".github/workflows/terraform-apply-sandbox.yml")
    reconcile_data = _load(".github/workflows/reconcile.yml")

    concurrency = apply_data.get("concurrency") or {}
    group = str(concurrency.get("group", ""))
    cancel_in_progress = str(concurrency.get("cancel-in-progress", ""))

    assert "pull_request" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is not event-keyed on pull_request: {group!r}"
    )
    assert "format(" in group and "pull_request.number" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is missing a per-PR format key: {group!r}"
    )
    assert "terraform-apply-sandbox" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is missing the shared push/dispatch "
        f"key 'terraform-apply-sandbox': {group!r}"
    )

    assert "pull_request" in cancel_in_progress, (
        f"terraform-apply-sandbox.yml concurrency.cancel-in-progress is not gated on pull_request "
        f"(a push/dispatch apply run could be cancelled): {cancel_in_progress!r}"
    )
    assert cancel_in_progress.strip() not in ("true", "${{ true }}"), (
        f"terraform-apply-sandbox.yml concurrency.cancel-in-progress is unconditionally true: {cancel_in_progress!r}"
    )

    reconcile_concurrency = reconcile_data.get("concurrency") or {}
    reconcile_group = str(reconcile_concurrency.get("group", ""))
    assert reconcile_group == "terraform-apply-sandbox", (
        f"reconcile.yml concurrency.group no longer shares the terraform-apply-sandbox push/dispatch "
        f"key (cross-workflow apply serialization broken): {reconcile_group!r}"
    )


_COMMANDS = {
    "jobs-and-flags": _check_jobs_and_flags,
    "concurrency": _check_concurrency,
    "fetch-depth": _check_fetch_depth,
    "canary": _check_canary,
    "ci-rca-filter": _check_ci_rca_filter,
    "apply-rca-fallback": _check_apply_rca_fallback,
    "validate-single-source": _check_validate_single_source,
    "signal-green-needs": _check_signal_green_needs,
    "terraform-apply-concurrency": _check_terraform_apply_concurrency,
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
