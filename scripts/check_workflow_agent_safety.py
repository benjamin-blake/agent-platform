"""Static check: headless `claude -p` workflow steps must not silently swallow failures.

A workflow step that runs the Claude CLI headlessly (`claude -p` / `claude --print`)
and masks the exit code (`|| true` on the invocation, or a step-level
`continue-on-error: true`) MUST also assert on the agent's output, so an empty or
error response fails the step loudly instead of passing as a no-op.

Without that assertion, a broken invocation (for example a prompt misparsed because it
trails a variadic flag, leaving claude with no input) exits non-zero, the mask turns it
into exit 0, and downstream logic acts on nothing -- the silent-failure class that
produced the ci-rca "Input must be provided ... when using --print" regression.

Detection is intentionally conservative to keep false positives near zero: a masked
`claude -p` step passes only if its run block also contains an output guard -- a
`grep`/`test`/`[ ... ]` condition together with an `exit 1` or `::error::` annotation
that can red the step.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Raw CLI invocation only. `uses: anthropics/claude-code-action` has no `run:` block and
# is handled by the Action, so it never reaches this check.
_CLAUDE_INVOCATION = re.compile(r"\bclaude\s+(?:-p|--print)\b")
_MASK = re.compile(r"\|\|\s*true\b")
# An output guard: a grep/test/[ condition AND a failing branch (exit 1 or ::error::).
_GUARD_CONDITION = re.compile(r"\b(?:grep|test)\b|\[\s")
_GUARD_FAILURE = re.compile(r"\bexit\s+1\b|::error")


def _iter_run_steps(workflow: dict) -> list[dict]:
    """Yield every step dict that has a string `run:` block, across all jobs."""
    steps: list[dict] = []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return steps
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                steps.append(step)
    return steps


def _is_masked(step: dict, run: str) -> bool:
    if _MASK.search(run):
        return True
    coe = step.get("continue-on-error")
    return coe is True or (isinstance(coe, str) and coe.strip().lower() == "true")


def _has_output_guard(run: str) -> bool:
    return bool(_GUARD_CONDITION.search(run)) and bool(_GUARD_FAILURE.search(run))


def check_workflow_agent_safety() -> list[str]:
    """Return a list of human-readable violation strings (empty == pass)."""
    violations: list[str] = []
    if not WORKFLOWS_DIR.is_dir():
        return violations

    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            workflow = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            violations.append(f"{wf_path.name}: YAML parse error: {exc}")
            continue
        if not isinstance(workflow, dict):
            continue

        for step in _iter_run_steps(workflow):
            run = step["run"]
            if not _CLAUDE_INVOCATION.search(run):
                continue
            if not _is_masked(step, run):
                # Unmasked: a broken claude exits non-zero and reds the step already.
                continue
            if _has_output_guard(run):
                continue
            name = step.get("name", "<unnamed step>")
            violations.append(
                f"{wf_path.name}: step '{name}' runs headless `claude -p` with masked failure "
                "(|| true / continue-on-error) but no output assertion (expected a grep/test guard "
                "with `exit 1` or `::error::`). A misparsed prompt or empty response would pass silently."
            )

    return violations


if __name__ == "__main__":
    import sys

    found = check_workflow_agent_safety()
    if found:
        print("Workflow agent-safety violations:")
        for v in found:
            print(f"  - {v}")
        sys.exit(1)
    print("Workflow agent-safety: all headless claude -p steps assert their output.")
