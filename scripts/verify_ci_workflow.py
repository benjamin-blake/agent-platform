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


def _get_step_run_text(job: dict[str, Any], step_name: str) -> str:
    """Return the `run:` block text of one specific named step within a job."""
    for step in job.get("steps", []):
        if step.get("name") == step_name:
            return step.get("run") or ""
    raise AssertionError(f"step {step_name!r} not found in job")


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
    _assert_runtime_lock(main_job, "main-validate")


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
    assert main_with.get("fetch-depth") == 2, (
        f"main-validate checkout fetch-depth is {main_with.get('fetch-depth')!r}, expected 2 "
        "(Decision 159: HEAD~1 must resolve for the push-context diff base, squash-merge convention)"
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
    _assert_runtime_lock(canary_job, "main-canary")


def _assert_runtime_lock(job: dict[str, Any], job_name: str) -> None:
    steps_text = _get_steps_text(job)
    for requirements_file in ("requirements.txt", "requirements-dev.txt"):
        expected = f"pip install -c requirements.lock -r {requirements_file}"
        assert expected in steps_text, f"{job_name} does not constrain {requirements_file} with requirements.lock"

    cache_steps = [step for step in job.get("steps", []) if str(step.get("uses", "")).startswith("actions/cache")]
    cache_keys = "\n".join(str(step.get("with", {}).get("key", "")) for step in cache_steps)
    assert "requirements.lock" in cache_keys, f"{job_name} dependency cache key does not include requirements.lock"


def _check_full_tier_runtime_lock() -> None:
    ci_jobs = _load(".github/workflows/ci.yml").get("jobs", {})
    main_job = ci_jobs.get("main-validate")
    assert main_job is not None, "main-validate job missing from ci.yml"
    _assert_runtime_lock(main_job, "main-validate")

    canary_jobs = _load(".github/workflows/main-canary.yml").get("jobs", {})
    assert len(canary_jobs) == 1, "main-canary.yml must contain exactly one full-tier job"
    _assert_runtime_lock(next(iter(canary_jobs.values())), "main-canary")


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


_PATTERN_MATCHING_CONSTRUCT_RE = re.compile(
    r"\bgrep\b|\begrep\b|\brg\b|\bawk\b|\bsed\b|\bcase\b|=~|\bpython[0-9.]*\s+-c\b",
    re.IGNORECASE,
)

_CI_RCA_FETCH_STEP = "      - name: Fetch failed run logs"


def _read_ci_rca_authority_sources() -> tuple[str, str]:
    return tuple(Path(path).read_text(encoding="utf-8") for path in (".github/workflows/ci-rca.yml", "docs/DECISIONS.md"))  # type: ignore[return-value]


def _ci_rca_fetch_source_comment(workflow_source: str) -> str:
    matches = re.findall(rf"((?:^      #.*\n)+)(?=^{re.escape(_CI_RCA_FETCH_STEP)}$)", workflow_source, re.MULTILINE)
    assert workflow_source.count(_CI_RCA_FETCH_STEP) == 1, "GAL-03: Fetch source anchor is missing or duplicated"
    assert len(matches) == 1, "GAL-03: Fetch anchor is missing, duplicated, or lacks immediately adjacent provenance"
    return matches[0]


def _decision_72_entry(decisions_source: str) -> str:
    headers = list(re.finditer(r"^## Decision (\d+):", decisions_source, re.MULTILINE))
    decision_72 = [match for match in headers if match.group(1) == "72"]
    assert len(decision_72) == 1, "GAL-03: docs/DECISIONS.md must contain exactly one well-formed Decision 72 H2 header"
    start = decision_72[0]
    end = next((match.start() for match in headers if match.start() > start.start()), None)
    assert end is not None, "GAL-03: Decision 72 entry has no following Decision H2 boundary"
    return decisions_source[start.start() : end]


def _check_ci_rca_authority_anchor() -> None:
    workflow_source, decisions_source = _read_ci_rca_authority_sources()
    comment = _ci_rca_fetch_source_comment(workflow_source)
    provenance = ("Decision 72 is provenance", "workflow_run-triggered CI-RCA failed-run log retrieval")
    assert all(fragment in comment for fragment in provenance), (
        "GAL-03: adjacent comment must identify Decision 72 only as CI-RCA failed-run log retrieval provenance"
    )
    assert all(fragment in comment for fragment in ("local", "YAML-side fail-closed guard")), (
        "GAL-03: adjacent comment must identify test -s as a local YAML-side fail-closed guard"
    )
    assert "Decision 143" not in comment, "GAL-03: adjacent comment retains the stale Decision 143 mitigation claim"
    assert "Decision 72 mitigation" not in comment and "Decision 72 guard" not in comment, (
        "GAL-03: adjacent comment must not claim Decision 72 owns the local guard"
    )

    authority = ("On CI failure", "`workflow_run`-triggered", ".github/workflows/ci-rca.yml", "failed run logs", "gh run view")
    missing = [fragment for fragment in authority if fragment not in _decision_72_entry(decisions_source)]
    assert not missing, f"GAL-03: bounded Decision 72 entry does not establish CI-RCA failed-run log retrieval: {missing}"


def _check_ci_rca_fetch_classification() -> None:
    """Reject pattern matching in the bounded failed-log retrieval step (rec-2857)."""
    _check_ci_rca_authority_anchor()
    data = _load(".github/workflows/ci-rca.yml")
    job = data.get("jobs", {}).get("rca", {})
    run_text = _get_step_run_text(job, "Fetch failed run logs")
    evidence_run_text = _get_step_run_text(job, "Generate evidence bundle")

    assert "scripts.ci_rca.fetch_logs" in run_text, "'Fetch failed run logs' step no longer invokes scripts.ci_rca.fetch_logs"
    assert "--out /tmp/ci-rca-log-evidence.json" in run_text, "GAL-01: fetch output is not the typed retrieval envelope"
    assert "scripts.ci_rca.log_evidence --validate" in run_text, "GAL-01: bounded retrieval envelope is not validated"
    assert "--extract-body /tmp/ci-rca-failed.log" in run_text, "GAL-01: agent log is not extracted from validated evidence"
    assert "test -s /tmp/ci-rca-log-evidence.json" in run_text, "GAL-01: retrieval envelope false-green guard is missing"
    assert "test -s /tmp/ci-rca-failed.log" in run_text, "GAL-01: extracted body false-green guard is missing"
    assert "--retrieval-envelope /tmp/ci-rca-log-evidence.json" in evidence_run_text, (
        "GAL-01: durable evidence generation does not consume the validated retrieval envelope"
    )
    assert "gh run view" not in run_text or "--log" not in run_text, (
        "GAL-01: workflow contains an uncapped direct log retrieval"
    )
    fetch_source = Path("scripts/ci_rca/fetch_logs.py").read_text(encoding="utf-8")
    for required in (
        "_run_log(primary_command, max_bytes, max_lines)",
        'remaining = max_bytes - len("".join(fragments).encode("utf-8"))',
        "remaining_lines = max_lines -",
        "_run_log(command, remaining, remaining_lines)",
        'selected.sort(key=lambda item: item["job_id"])',
    ):
        assert required in fetch_source, f"GAL-01: bounded retrieval invariant missing: {required}"

    match = _PATTERN_MATCHING_CONSTRUCT_RE.search(run_text)
    assert match is None, (
        f"'Fetch failed run logs' step run: body contains a pattern-matching construct "
        f"({match.group(0)!r}) -- the log-body content check must never be reintroduced (rec-2857)"
    )


# rec-2847 part (c), narrowed to reconcile.yml's red-recovery topology. The six DEP-10
# fresh-replan fallthrough steps; the seventh (the upload-artifact step) carries no `id` and is
# located by its `uses:` below.
_RECOVERY_FALLTHROUGH_STEP_IDS = (
    "replan",
    "guard_fresh",
    "review_fresh",
    "apply_fresh",
    "upload_fresh_plan_sha256",
)
_RECOVERY_FRESH_PLAN_SIGNAL = "steps.route.outputs.needs_fresh_plan == 'true'"
# The pre-fix, single-cause signal. A saved-plan guard-BLOCK SKIPS the `apply` step, so this
# output is never set on exactly the episodes that most need the fallthrough -- gating any
# fallthrough step on it makes that step structurally unreachable on the BLOCK route.
_RECOVERY_LEGACY_STALE_SIGNAL = "steps.apply.outputs.stale"
_RECOVERY_STALE_DETECTION_MARKERS = (
    "saved plan is stale|plan file can no longer be applied|state was changed",
    "stale=true",
    "STALE_PLAN_FRESH_REPLAN",
)
_RECOVERY_FRESH_PLAN_PENDING = "needs.apply-reconcile.outputs.fresh_plan_pending == 'true'"
_RECOVERY_FRESH_PLAN_NOT_PENDING = "needs.apply-reconcile.outputs.fresh_plan_pending != 'true'"


def _recovery_step_body(step: dict[str, Any]) -> str:
    """Flatten one step's `run:` body and `env:` block into a single searchable string."""
    env = step.get("env") or {}
    env_text = "\n".join(f"{key}: {value}" for key, value in env.items())
    return f"{step.get('run') or ''}\n{env_text}"


def _check_recovery_workflow_topology() -> None:
    """rec-2847: reconcile.yml's red-recovery flow must stay reachable on BOTH fresh-plan causes.

    Four invariants, asserted over the PARSED workflow (never a whole-file grep):
      (i)   the `route` aggregator exists and reads BOTH cause signals;
      (ii)  no fresh-replan fallthrough step is gated on the pre-fix stale-only signal, and every
            one of them is gated on the aggregate `needs_fresh_plan` signal;
      (iii) the saved-plan apply step still carries its stale-signature detection -- the union
            ADDS to the DEP-10 stale route, it must never replace it;
      (iv)  the cross-job hand-off is intact: the `fresh_plan_pending` / `fresh_plan_sha256` job
            outputs are declared, gated-apply-reconcile's download + sha256 VERIFY steps are gated
            on pending, and fetch-saved-plan is gated on its negation (mutually exclusive sources).
    """
    data = _load(".github/workflows/reconcile.yml")
    jobs = data.get("jobs", {})

    apply_job = jobs.get("apply-reconcile")
    assert apply_job is not None, "reconcile.yml has no apply-reconcile job"
    gated_job = jobs.get("gated-apply-reconcile")
    assert gated_job is not None, "reconcile.yml has no gated-apply-reconcile job"

    steps = apply_job.get("steps", []) or []
    by_id = {step.get("id"): step for step in steps if step.get("id")}

    # (i) the route aggregator exists and unions BOTH causes.
    route = by_id.get("route")
    assert route is not None, (
        "reconcile.yml apply-reconcile has no `route` step -- without it the fresh-replan "
        "fallthrough is gated on a single cause and is structurally unreachable on a saved-plan "
        "guard-BLOCK (rec-2847)"
    )
    route_body = _recovery_step_body(route)
    for cause in (_RECOVERY_LEGACY_STALE_SIGNAL, "steps.guard.outputs.routed"):
        assert cause in route_body, (
            f"`route` step does not read cause signal {cause!r} -- needs_fresh_plan must be the "
            "UNION of the stale-saved-plan and saved-plan-guard-routed causes, or the defect is "
            "merely relocated"
        )
    assert "needs_fresh_plan" in route_body, "`route` step does not emit a needs_fresh_plan output"

    # (ii) every fallthrough step rides the aggregate signal, none the pre-fix stale-only one.
    upload_artifact = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact")),
        None,
    )
    assert upload_artifact is not None, "reconcile.yml apply-reconcile has no upload-artifact fallthrough step"

    gated_steps: list[tuple[str, dict[str, Any]]] = [
        (step_id, by_id[step_id]) for step_id in _RECOVERY_FALLTHROUGH_STEP_IDS if step_id in by_id
    ]
    missing = [step_id for step_id in _RECOVERY_FALLTHROUGH_STEP_IDS if step_id not in by_id]
    assert not missing, f"reconcile.yml apply-reconcile is missing fresh-replan fallthrough step(s): {missing}"
    gated_steps.append(("upload-artifact", upload_artifact))

    for label, step in gated_steps:
        condition = str(step.get("if", ""))
        assert _RECOVERY_LEGACY_STALE_SIGNAL not in condition, (
            f"fallthrough step {label!r} is still gated on {_RECOVERY_LEGACY_STALE_SIGNAL!r} -- "
            "a saved-plan guard-BLOCK skips the apply step, so that output is never set and this "
            "step can never run on the BLOCK route (rec-2847)"
        )
        assert _RECOVERY_FRESH_PLAN_SIGNAL in condition, (
            f"fallthrough step {label!r} is not gated on {_RECOVERY_FRESH_PLAN_SIGNAL!r}: {condition!r}"
        )

    # (iii) the DEP-10 stale route survived -- the union ADDS to it, never replaces it.
    apply_step = by_id.get("apply")
    assert apply_step is not None, "reconcile.yml apply-reconcile has no saved-plan `apply` step"
    apply_body = apply_step.get("run") or ""
    for marker in _RECOVERY_STALE_DETECTION_MARKERS:
        assert marker in apply_body, (
            f"saved-plan `apply` step lost its stale-signature detection ({marker!r}) -- the "
            "guard-BLOCK cause must be UNIONED with the stale cause, not substituted for it"
        )

    # (iv) the cross-job hand-off is intact.
    outputs = apply_job.get("outputs", {}) or {}
    assert "steps.upload_fresh_plan_sha256.outcome" in str(outputs.get("fresh_plan_pending", "")), (
        "apply-reconcile does not declare a fresh_plan_pending job output derived from steps.upload_fresh_plan_sha256.outcome"
    )
    assert "steps.upload_fresh_plan_sha256.outputs.sha256" in str(outputs.get("fresh_plan_sha256", "")), (
        "apply-reconcile does not declare a fresh_plan_sha256 job output"
    )

    gated_job_steps = gated_job.get("steps", []) or []
    download = next(
        (step for step in gated_job_steps if str(step.get("uses", "")).startswith("actions/download-artifact")),
        None,
    )
    assert download is not None, "gated-apply-reconcile has no download-artifact step"
    assert _RECOVERY_FRESH_PLAN_PENDING in str(download.get("if", "")), (
        f"gated-apply-reconcile's download step is not gated on {_RECOVERY_FRESH_PLAN_PENDING!r}: {download.get('if')!r}"
    )

    verify = next((step for step in gated_job_steps if "FRESH_PLAN_SHA256" in _recovery_step_body(step)), None)
    assert verify is not None, "gated-apply-reconcile has no fresh plan.bin sha256 VERIFY step"
    assert _RECOVERY_FRESH_PLAN_PENDING in str(verify.get("if", "")), (
        f"gated-apply-reconcile's sha256 VERIFY step is not gated on {_RECOVERY_FRESH_PLAN_PENDING!r}: {verify.get('if')!r}"
    )

    fetch_plan = next((step for step in gated_job_steps if step.get("id") == "fetch_plan"), None)
    assert fetch_plan is not None, "gated-apply-reconcile has no fetch_plan step"
    assert _RECOVERY_FRESH_PLAN_NOT_PENDING in str(fetch_plan.get("if", "")), (
        "gated-apply-reconcile's fetch-saved-plan step is not gated on "
        f"{_RECOVERY_FRESH_PLAN_NOT_PENDING!r} -- the fresh and saved plan sources must stay "
        f"mutually exclusive: {fetch_plan.get('if')!r}"
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
    "ci-rca-fetch-classification": _check_ci_rca_fetch_classification,
    "full-tier-runtime-lock": _check_full_tier_runtime_lock,
    "recovery-workflow-topology": _check_recovery_workflow_topology,
}


def main() -> None:
    if len(sys.argv) == 1:
        for fn in _COMMANDS.values():
            fn()
        print("OK")
        return
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
