"""Write-coverage submodule (Decision 128 decomposition + Decision 144 / T2.48 c5, DEP-01).

The enumerated-model recurrence (rec-2703 / rec-2757) was a resource whose refresh-READ was covered
but whose WRITE verb was missing from github_ci_apply's inline policy, so a real apply AccessDenied.
The read-coverage gate (_read_coverage) closes the read half; this submodule closes the write half:
for every resource TYPE the github_ci_apply pipeline is expected to WRITE (create / modify / destroy
at apply time), assert the apply role's inline policy grants the required write verbs on a matching
resource prefix. An apply-role-written type with no covering write grant FAILS LOUD, mirroring the
read-coverage loud-fail (Decision 55: fail loud, never silently pass).

Credential-free (pure text parsing) -- eligible for --pre and full tiers. Stays < 500 SLOC.
"""

from __future__ import annotations

from scripts.checks.iam_tf._read_coverage import _action_matches

# ---------------------------------------------------------------------------
# WRITE-coverage map: managed resource type -> the write actions github_ci_apply's inline policy MUST
# grant + a marker substring the granting statement's Resource list must contain (the broadened
# agent-platform-* / ducklake-* prefix from the DEP-01 write-surface inversion). A required action is
# covered when SOME apply statement grants it on a Resource containing the marker.
# ---------------------------------------------------------------------------

WRITE_COVERAGE: dict[str, dict] = {
    "aws_lambda_function": {
        "write_actions": ("lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"),
        "resource_marker": "function:agent-platform-*",
    },
    "aws_cloudwatch_log_group": {
        "write_actions": ("logs:CreateLogGroup", "logs:PutRetentionPolicy"),
        "resource_marker": "log-group:/aws/lambda/agent-platform-*",
    },
    "aws_cloudwatch_metric_alarm": {
        "write_actions": ("cloudwatch:PutMetricAlarm",),
        "resource_marker": "alarm:",
    },
    "aws_cloudwatch_event_rule": {
        "write_actions": ("events:PutRule",),
        "resource_marker": "rule/agent-platform-*",
    },
    "aws_iam_role": {
        # Role CREATE routes to gated-apply (guard), but the apply role still needs the VERB to execute
        # the approved create; IAMRoleCreateBounded grants iam:CreateRole on role/agent-platform-* under
        # the boundary-propagation condition (DEP-02 / Decision 144).
        "write_actions": ("iam:CreateRole",),
        "resource_marker": "role/agent-platform-*",
    },
}

# The resource TYPES the github_ci_apply pipeline writes at apply time. Every entry MUST have a
# WRITE_COVERAGE mapping (asserted below) -- an apply-role-written type present in terraform/personal
# with no write-coverage entry AccessDenies at a real apply (rec-2703/rec-2757 recurrence).
APPLY_WRITTEN_TYPES: frozenset[str] = frozenset(WRITE_COVERAGE)


def _write_grant_present(apply_statements: list[dict], spec: dict) -> bool:
    """True if each required write action is granted by some apply statement on a matching Resource."""
    marker = spec["resource_marker"]
    for action in spec["write_actions"]:
        covered = False
        for stmt in apply_statements:
            if _action_matches((action,), stmt["actions"]) and marker in stmt["resources_raw"]:
                covered = True
                break
        if not covered:
            return False
    return True


def check_write_coverage(
    apply_statements: list[dict], resources: list[tuple[str, str, str]], failed: list[str], key: str
) -> int:
    """Assert github_ci_apply's inline policy write-covers every apply-role-written managed type (c5).

    Two loud-fail directions (mirroring read-coverage):
      1. Every WRITE_COVERAGE type's required write verbs are present in the apply policy on the
         broadened prefix. A removed / narrowed write grant fails the PR (DEP-01 write-surface gap).
      2. A terraform/personal resource of an apply-role-written type with NO WRITE_COVERAGE entry
         fails loud -- a new write-managed resource class must declare its write grant.

    Returns the count of write-managed types asserted (for the PASS summary). Appends to `failed`.
    """
    for rtype, spec in WRITE_COVERAGE.items():
        if not _write_grant_present(apply_statements, spec):
            failed.append(
                f"{key} apply-role write-managed type {rtype!r} has no covering write grant in "
                f"github_ci_apply.tf (expected {spec['write_actions']} on a Resource matching "
                f"{spec['resource_marker']!r}) -- DEP-01 write-surface gap (rec-2703/rec-2757)"
            )

    for rtype, rname, fname in resources:
        if rtype in APPLY_WRITTEN_TYPES and rtype not in WRITE_COVERAGE:
            failed.append(
                f"{key} apply-role-written type {rtype!r} (resource {rname} in {fname}) has no "
                "WRITE_COVERAGE entry -- add one to scripts/checks/iam_tf/_write_coverage.py"
            )

    return len(WRITE_COVERAGE)
