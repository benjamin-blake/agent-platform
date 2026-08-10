"""pr-conflict-signal.yml structural invariants gate (PLAN-pr-conflict-wake-signal; extraction
per Decision 162 / rec-2735)."""

from __future__ import annotations

import re

from scripts.checks import _common, registry
from scripts.verify_ci_workflow import _load

_WORKFLOW_PATH = ".github/workflows/pr-conflict-signal.yml"

# The delegation line is fully anchored: `run: bash <repo-root-relative-path>.sh`, nothing else --
# mirrors the composite-action guard's _DELEGATE_LINE_RE anchoring discipline (Decision 162 R1),
# adapted for a workflow step (repo-root-relative cwd via actions/checkout, not
# github.action_path-relative).
_DELEGATE_RUN_RE = re.compile(r"^bash\s+([\w./-]+\.sh)\s*$")

# A literal "gh <subcommand>" call site, anchored to an actual command POSITION (line start, or
# immediately after a command-substitution "$(") -- never a bare `\bgh\b` scan, which would also
# match "gh" inside a comment or inside a quoted prose string (e.g. a _signal_failure message
# describing "gh pr view ... failed"). This guard is filesystem-only (Decision 153 fast-tier
# budget) -- no subprocess, no network, no real shell parsing beyond regex/line-scanning.
_GH_CALL_RE = re.compile(r"(?:^|\$\()\s*gh\s")
# A gh call passed as an ARGUMENT to the shared retry helper (e.g.
# "mergeable=$(_gh_bounded_retry 5 5 \"UNKNOWN\" gh pr view ...)") never matches _GH_CALL_RE --
# "gh" sits after the helper's own leading arguments, not at line-start or immediately after
# "$(" -- so it needs its own, looser word-boundary detector to be recognised as a call site at
# all before the retry-helper exemption below can apply to it.
_GH_WORD_RE = re.compile(r"\bgh\s")
_RETRY_HELPER_TOKEN = "_gh_bounded_retry"
_EXIT_STATUS_CAPTURE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\$\?$")


def _join_continuations(text: str) -> list[str]:
    """Backslash-continued physical lines joined into one stripped logical line each."""
    logical: list[str] = []
    buffer = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        buffer = f"{buffer} {stripped}".strip() if buffer else stripped
        if buffer.endswith("\\"):
            buffer = buffer[:-1].rstrip()
            continue
        logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def _unguarded_gh_call_sites(script_text: str) -> list[str]:
    """gh call sites that are neither routed through the shared retry helper nor immediately
    followed by an explicit `$?` capture -- the rec-2735 shape this guard exists to reject."""
    logical_lines = _join_continuations(script_text)
    unguarded: list[str] = []
    for index, line in enumerate(logical_lines):
        if not line or line.startswith("#"):
            continue
        routed_through_helper = _RETRY_HELPER_TOKEN in line and bool(_GH_WORD_RE.search(line))
        if routed_through_helper:
            continue
        if not _GH_CALL_RE.search(line):
            continue
        following = logical_lines[index + 1] if index + 1 < len(logical_lines) else ""
        if _EXIT_STATUS_CAPTURE_RE.match(following):
            continue
        unguarded.append(line)
    return unguarded


def _resolve_delegate(jobs: dict) -> tuple[str | None, str | None, int | None]:
    """First (job_name, script_rel_path, step_index) whose `run:` is a bare delegation line."""
    for job_name, job in jobs.items():
        steps = job.get("steps") or []
        for index, step in enumerate(steps):
            run_body = step.get("run")
            if not isinstance(run_body, str):
                continue
            match = _DELEGATE_RUN_RE.match(run_body.strip())
            if match:
                return job_name, match.group(1), index
    return None, None, None


@registry.register("validate_pr_conflict_signal", owner="platform")
def validate_pr_conflict_signal(failed: list[str]) -> None:
    """Assert pr-conflict-signal.yml's load-bearing shape (PLAN-pr-conflict-wake-signal).

    This is the push:[main] counterpart to signal-green: it delivers the merge-conflict-transition
    wake that the pull_request-only signal-green job structurally cannot (a push to main fires no
    pull_request event on open PRs). The poll step is a thin delegation to
    scripts/ci/pr_conflict_signal.sh (Decision 162 R1/R3); this guard follows that delegation and
    asserts its five semantic invariants against the SCRIPT's own contents, plus delegate
    existence, checkout-precedes-delegation, errexit clearing, and per-call-site exit-status
    handling. Each guard failure appends a distinct label to `failed` rather than raising, matching
    the ci_guards module pattern.
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

    permissions_ok = any((job.get("permissions") or {}).get("pull-requests") == "write" for job in jobs.values())
    if permissions_ok:
        print("  PASS: a job declares permissions.pull-requests: write")
    else:
        print("  FAIL: no job declares permissions.pull-requests: write")
        failed.append("pr-conflict-signal: missing pull-requests: write permission")

    coe_ok = any(step.get("continue-on-error") is True for job in jobs.values() for step in job.get("steps", []))
    if coe_ok:
        print("  PASS: a step declares continue-on-error: true")
    else:
        print("  FAIL: no step declares continue-on-error: true")
        failed.append("pr-conflict-signal: missing continue-on-error: true")

    job_name, script_rel_path, step_index = _resolve_delegate(jobs)
    if script_rel_path is None or job_name is None or step_index is None:
        print("  FAIL: could not resolve a delegate script from any step's run: body")
        failed.append("pr-conflict-signal: could not resolve delegate script")
        return

    script_path = _common.ROOT / script_rel_path
    if not script_path.is_file():
        print(f"  FAIL: delegate script {script_rel_path} does not exist on disk")
        failed.append("pr-conflict-signal: delegate script missing on disk")
        return
    print(f"  PASS: delegate script {script_rel_path} exists")

    steps = jobs[job_name].get("steps") or []
    checkout_before = any(str(step.get("uses", "")).startswith("actions/checkout") for step in steps[:step_index])
    if checkout_before:
        print("  PASS: actions/checkout precedes the delegation step")
    else:
        print("  FAIL: no actions/checkout step precedes the delegation step")
        failed.append("pr-conflict-signal: checkout does not precede delegation")

    script_text = script_path.read_text(encoding="utf-8")

    if "\nset +e\n" in f"\n{script_text}\n":
        print("  PASS: delegate script clears inherited errexit (set +e)")
    else:
        print("  FAIL: delegate script does not clear errexit (no `set +e` line)")
        failed.append("pr-conflict-signal: delegate script does not clear errexit")

    checks = [
        ("claude/* head filter", "claude/" in script_text),
        ("mergeable poll", "mergeable" in script_text),
        ("UNKNOWN-skip handling", "UNKNOWN" in script_text),
        ("CONFLICTING-only comment gate", "CONFLICTING" in script_text),
        ("head-SHA dedup marker", "conflict-wake:" in script_text),
    ]
    for label, present in checks:
        if present:
            print(f"  PASS: {label}")
        else:
            print(f"  FAIL: {label} not found in delegate script")
            failed.append(f"pr-conflict-signal: missing {label}")

    unguarded = _unguarded_gh_call_sites(script_text)
    if unguarded:
        print(f"  FAIL: gh call site(s) without explicit exit-status handling: {unguarded}")
        failed.append("pr-conflict-signal: gh call site(s) missing explicit exit-status handling")
    else:
        print("  PASS: every gh call site handles its exit status")
