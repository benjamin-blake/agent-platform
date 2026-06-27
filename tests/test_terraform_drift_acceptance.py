"""Regression guard: every workflow-embedded ops portal --acceptance value must pass
lint_acceptance_command, and terraform-drift.yml must preserve alarm-only structural invariants.

Prevents recurrence of the prose-acceptance defect (T2.24 root cause) for any workflow that
files a rec via scripts.ops_data_portal --file-rec --acceptance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts.executor.acceptance_lint import lint_acceptance_command

WORKFLOWS_DIR = Path(".github/workflows")
DRIFT_WORKFLOW = WORKFLOWS_DIR / "terraform-drift.yml"

_PORTAL_PATTERN = re.compile(r"scripts\.ops_data_portal|\.venv/bin/python\s+-m\s+scripts\.ops_data_portal")
_ACCEPTANCE_DOUBLE = re.compile(r'--acceptance\s+"([^"]+)"')
_ACCEPTANCE_SINGLE = re.compile(r"--acceptance\s+'([^']+)'")


def _extract_acceptance_values(run_block: str) -> list[str]:
    """Return all --acceptance values from a run block that also invokes ops_data_portal."""
    if not _PORTAL_PATTERN.search(run_block):
        return []
    values = _ACCEPTANCE_DOUBLE.findall(run_block) + _ACCEPTANCE_SINGLE.findall(run_block)
    return values


def _collect_acceptance_values() -> list[tuple[str, str]]:
    """Collect (workflow_filename, acceptance_value) pairs from all workflow files."""
    results: list[tuple[str, str]] = []
    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        content = wf_path.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        jobs = doc.get("jobs") or {}
        for _job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                run = step.get("run", "")
                if not isinstance(run, str):
                    continue
                for val in _extract_acceptance_values(run):
                    results.append((wf_path.name, val))
    return results


_ACCEPTANCE_CASES = _collect_acceptance_values()


@pytest.mark.parametrize("workflow_name,acceptance_value", _ACCEPTANCE_CASES)
def test_portal_acceptance_passes_lint(workflow_name: str, acceptance_value: str) -> None:
    """Every ops portal --acceptance argument embedded in a workflow must pass lint_acceptance_command."""
    ok, msg = lint_acceptance_command(acceptance_value)
    assert ok, f"{workflow_name}: --acceptance value fails lint_acceptance_command: {acceptance_value!r} -> {msg}"


def test_drift_workflow_has_no_terraform_apply() -> None:
    """terraform-drift.yml must not contain a terraform apply invocation (alarm-only invariant).

    Comments (lines starting with #) are excluded so documentation mentions of the invariant
    do not trip this guard.
    """
    lines = DRIFT_WORKFLOW.read_text(encoding="utf-8").splitlines()
    non_comment_lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    non_comment_content = "\n".join(non_comment_lines)
    assert not re.search(r"terraform\s+apply\b", non_comment_content), (
        "ALARM-ONLY violated: terraform apply found in non-comment lines of terraform-drift.yml"
    )


def test_drift_workflow_has_detailed_exitcode() -> None:
    """terraform-drift.yml must use -detailed-exitcode to distinguish drift from no-change."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "-detailed-exitcode" in content, "terraform-drift.yml is missing -detailed-exitcode; drift detection would break"


def test_drift_workflow_has_lock_skip_branch() -> None:
    """terraform-drift.yml must have the lock-acquisition-failure skip branch."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "Error acquiring the state lock" in content, (
        "terraform-drift.yml is missing the lock-acquisition-failure skip branch"
    )
