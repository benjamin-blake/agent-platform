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

from scripts.checks._scaffolding import _TRANSIENT_INIT_SIGNATURES
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


def test_drift_workflow_has_pending_gated_branch() -> None:
    """DEP-11 (T2.47): terraform-drift.yml must recognise a pending_gated marker on the current
    convergence record and label the delta as pending-gated (PENDING_GATED_DRIFT), not merely
    out-of-band drift."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "pending_gated" in content, "terraform-drift.yml is missing the pending_gated recognition branch"
    assert "PENDING_GATED_DRIFT" in content, "terraform-drift.yml is missing the PENDING_GATED_DRIFT marker"


def test_drift_workflow_names_the_pending_pr_via_authenticated_lookup() -> None:
    """The pending_gated branch must resolve the pending PR via an authenticated gh api
    commits/.../pulls lookup (CARRY-3: GH_TOKEN wired for the read-only lookup)."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "GH_TOKEN" in content, "terraform-drift.yml is missing GH_TOKEN for the pending PR gh api lookup"
    assert re.search(r"commits/\$\{[^}]*\}/pulls", content), (
        "terraform-drift.yml is missing the commits/.../pulls PR-resolution lookup"
    )


def test_drift_workflow_permissions_include_pull_requests_read() -> None:
    """CARRY-3: the drift-detect job's permissions must be widened to allow the read-only PR
    lookup -- contents: read alone does not cover commits/.../pulls."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(content)
    job = doc["jobs"]["drift-detect"]
    assert job["permissions"].get("pull-requests") == "read", (
        "drift-detect job permissions must declare pull-requests: read (CARRY-3)"
    )


def test_drift_workflow_pending_gated_checked_before_out_of_band_flip() -> None:
    """The pending_gated branch must be evaluated BEFORE the out-of-band red-flip narrative, so an
    explained (routed-pending) delta never falls through to the out-of-band path."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    pending_gated_check_idx = content.index("PENDING_GATED_PRESENT=$(")
    out_of_band_narrative_idx = content.index("out-of-band infra drift detected by scheduled terraform plan")
    assert pending_gated_check_idx < out_of_band_narrative_idx, (
        "pending_gated detection must run before the out-of-band red-flip narrative"
    )


def test_drift_workflow_pending_gated_branch_never_red_flips() -> None:
    """CARRY-2: the pending_gated branch must never set status to red -- it stays green with only
    the marker/rec-filing side effects; only the (separate, marker-absent) out-of-band branch
    below it is allowed to flip status red."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    start = content.index("PENDING_GATED_PRESENT=$(")
    end = content.index("PENDING_GATED_DRIFT tf_drift rec filed via ops portal.")
    branch_src = content[start:end]
    assert "= 'red'" not in branch_src, "pending_gated branch must not assign a red-status literal"
    assert "existing['status']" not in branch_src, "pending_gated branch must not touch the status field at all"


def test_drift_workflow_stamps_drift_flagged_at_for_idempotency() -> None:
    """The pending_gated branch must stamp drift_flagged_at, and check it, so a later tick with
    the same still-pending marker skips re-filing (one signal per episode, mirroring the existing
    red/unknown dedup invariant)."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "drift_flagged_at" in content, "terraform-drift.yml is missing the drift_flagged_at idempotency stamp"
    assert "ALREADY_FLAGGED" in content, "terraform-drift.yml is missing the already-flagged idempotency check"


def test_drift_workflow_out_of_band_branch_still_gated_behind_marker_absence() -> None:
    """The pre-existing out-of-band red-flip must remain reachable only when no pending_gated
    marker is present -- the pending_gated branch's `if` must close (via `exit 0` + `fi`) strictly
    before the absent-marker fallthrough comment that precedes the out-of-band red-flip."""
    content = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    start = content.index('if [ "$PENDING_GATED_PRESENT" = "true" ]; then')
    end = content.index("# Absent marker: existing out-of-band red-flip, unchanged.")
    assert start < end, "the pending_gated branch must appear before the absent-marker fallthrough"
    branch_and_gap = content[start:end]
    assert "exit 0" in branch_and_gap, "the pending_gated branch must exit 0 (never fall through) once handled"
    assert branch_and_gap.rstrip().endswith("fi"), (
        "the absent-marker fallthrough comment must appear only after the pending_gated branch's `fi` closes"
    )


def test_drift_workflow_init_retry_signature_parity() -> None:
    """The init-retry grep -qE line in terraform-drift.yml must carry every signature in
    _TRANSIENT_INIT_SIGNATURES, not merely the parity comment above it.

    Anchoring on "grep -qE" alone (rather than on a signature substring like "could not
    query provider registry") is required: the rewritten parity comment also enumerates all
    eight signatures, so a substring anchor would let the comment satisfy this guard even if
    the executable grep regressed.
    """
    lines = DRIFT_WORKFLOW.read_text(encoding="utf-8").splitlines()
    grep_lines = [ln for ln in lines if not ln.lstrip().startswith("#") and "grep -qE" in ln]
    assert len(grep_lines) == 1, f"expected exactly one non-comment grep -qE line, found {len(grep_lines)}"
    retry_line = grep_lines[0]
    missing = [sig for sig in _TRANSIENT_INIT_SIGNATURES if sig not in retry_line]
    assert not missing, f"terraform-drift.yml init-retry grep -qE line is missing signatures: {missing}"
