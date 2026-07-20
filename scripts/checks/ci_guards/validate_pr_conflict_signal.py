"""pr-conflict-signal.yml structural invariants gate (PLAN-pr-conflict-wake-signal)."""

from __future__ import annotations

from scripts.checks import registry
from scripts.verify_ci_workflow import _get_steps_text, _load

_WORKFLOW_PATH = ".github/workflows/pr-conflict-signal.yml"


@registry.register("validate_pr_conflict_signal", owner="platform")
def validate_pr_conflict_signal(failed: list[str]) -> None:
    """Assert pr-conflict-signal.yml's load-bearing shape (PLAN-pr-conflict-wake-signal).

    This is the push:[main] counterpart to signal-green: it delivers the
    merge-conflict-transition wake that the pull_request-only signal-green job structurally
    cannot (a push to main fires no pull_request event on open PRs). Each guard failure appends
    a distinct label to `failed` rather than raising, matching the ci_guards module pattern.
    """
    print("\n=== pr-conflict-signal guard gate ===")
    try:
        data = _load(_WORKFLOW_PATH)
    except Exception as exc:
        print(f"  FAIL: could not load {_WORKFLOW_PATH}: {exc}")
        failed.append("pr-conflict-signal: workflow file unreadable")
        return

    on = data.get("on", {})
    push = on.get("push") or {}
    if push.get("branches") != ["main"]:
        print(f"  FAIL: on.push.branches is not [main]: {push.get('branches')!r}")
        failed.append("pr-conflict-signal: push trigger not scoped to [main]")
    else:
        print("  PASS: on.push.branches == [main]")

    if "workflow_dispatch" not in on:
        print("  FAIL: workflow_dispatch trigger missing")
        failed.append("pr-conflict-signal: missing workflow_dispatch trigger")
    else:
        print("  PASS: workflow_dispatch trigger present")

    jobs = data.get("jobs", {})
    if not jobs:
        print("  FAIL: no jobs defined")
        failed.append("pr-conflict-signal: no jobs defined")
        return

    steps_text = ""
    permissions_ok = False
    for job in jobs.values():
        perms = job.get("permissions") or {}
        if perms.get("pull-requests") == "write":
            permissions_ok = True
        steps_text += "\n" + _get_steps_text(job)

    if permissions_ok:
        print("  PASS: a job declares permissions.pull-requests: write")
    else:
        print("  FAIL: no job declares permissions.pull-requests: write")
        failed.append("pr-conflict-signal: missing pull-requests: write permission")

    checks = [
        ("claude/* head filter", "claude/" in steps_text),
        ("mergeable poll", "mergeable" in steps_text),
        ("UNKNOWN-skip handling", "UNKNOWN" in steps_text),
        ("CONFLICTING-only comment gate", "CONFLICTING" in steps_text),
        ("head-SHA dedup marker", "conflict-wake:" in steps_text),
    ]
    for label, present in checks:
        if present:
            print(f"  PASS: {label}")
        else:
            print(f"  FAIL: {label} not found in steps")
            failed.append(f"pr-conflict-signal: missing {label}")

    coe_ok = any(step.get("continue-on-error") is True for job in jobs.values() for step in job.get("steps", []))
    if coe_ok:
        print("  PASS: a step declares continue-on-error: true")
    else:
        print("  FAIL: no step declares continue-on-error: true")
        failed.append("pr-conflict-signal: missing continue-on-error: true")
