"""Standing guard pinning IAMRoleReconcile's Resource set (Decision 172 contraction closure).

iam:UpdateAssumeRolePolicy is a trust verb and stays fleet-narrow under Decision 143 clause 1
(worst-verb scoping), a standing rule that needs no DEP-05 contingency. The rec-3132 rename-window
widening (planner + deploy ARNs) was a TEMPORARY exception whose only end condition was an HCL
comment -- exactly why it outlived the event it was scoped to. This test is the machine-checkable
expiry that comment lacked: a future re-widening must be a reviewed edit to this assertion, never a
quiet comment nobody enforces.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_policy.tf"

_EXPECTED_RESOURCES = frozenset(
    {
        "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-branch",
        "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-pr",
    }
)


def _iam_role_reconcile_block() -> str:
    """Return the IAMRoleReconcile statement's text, bounded to its own Sid."""
    text = _POLICY_FILE.read_text(encoding="utf-8")
    start = text.index('Sid    = "IAMRoleReconcile"')
    end = text.index('Sid    = "IAMRoleMetadataWrite"', start)
    return text[start:end]


class TestIAMRoleReconcileScope:
    def test_resource_set_is_exactly_branch_and_pr(self) -> None:
        block = _iam_role_reconcile_block()
        resource_match = re.search(r"Resource\s*=\s*\[(?P<body>[^\]]*)\]", block, re.S)
        assert resource_match is not None, "IAMRoleReconcile Sid declares no Resource list"
        got = frozenset(re.findall(r'"([^"]+)"', resource_match.group("body")))
        assert got == _EXPECTED_RESOURCES, (
            f"IAMRoleReconcile Resource set is {sorted(got)}, expected exactly "
            f"{sorted(_EXPECTED_RESOURCES)} -- iam:UpdateAssumeRolePolicy is a trust verb and "
            "stays fleet-narrow (Decision 143 clause 1); a re-widening must be a reviewed edit "
            "to this assertion, never a quiet HCL comment."
        )
