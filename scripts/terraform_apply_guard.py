#!/usr/bin/env python3
"""Deterministic guard for the sandbox auto-apply pipeline (Decision 76).

Parses `terraform show -json <planfile>` output and decides whether the plan is safe to
auto-apply in the sandbox environment without a human in the loop. The guard is the compensating
control for the absence of branch protection / required status checks (Decision 72 / CD.20): it,
together with a subagent plan review, IS the apply gate. It MUST fail closed.

Exit codes (consumed by .github/workflows/terraform-apply-sandbox.yml):
  0  plan is safe: only create / update / no-op / read on non-IAM resources, no trust diffs.
  2  plan is BLOCKED: contains a destroy, a replacement, an IAM-sensitive change, or a
     trust-policy (assume_role_policy) diff. Requires a manual admin apply.
  1  internal / parse error (also blocks apply at the workflow level).

Detection contract (against `terraform show -json`, iterating .resource_changes[]):
  - BLOCK if .change.actions contains "delete" (covers ["delete"] destroys and the replacement
    pairs ["delete","create"] / ["create","delete"]).
  - BLOCK if .type is IAM-sensitive AND .change.actions is not ["no-op"]/["read"].
  - BLOCK if a trust attribute (assume_role_policy) differs between .change.before and
    .change.after on ANY resource. assume_role_policy is serialised as a JSON-encoded string, so
    it is normalised via json.loads before comparison (key-order/whitespace differences do not
    cause nuisance trips). Fail-closed makes a false positive safe -- it forces a manual apply.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

IAM_SENSITIVE_TYPES = frozenset(
    {
        "aws_iam_role",
        "aws_iam_role_policy",
        "aws_iam_policy",
        "aws_iam_role_policy_attachment",
        "aws_iam_openid_connect_provider",
        "aws_iam_user",
        "aws_iam_group",
    }
)

# Attributes that carry a resource trust policy. Serialised by terraform as a JSON-encoded string.
TRUST_ATTRIBUTES = ("assume_role_policy",)

# Action sets that are inert for an IAM-sensitive resource (no privilege change).
_INERT_ACTIONS = (["no-op"], ["read"])


def _normalise_policy(value: Any) -> Any:
    """Return a comparable representation of a policy value.

    terraform serialises assume_role_policy as a JSON-encoded string; parse it so two
    structurally-equal policies that differ only in key order / whitespace compare equal. Falls
    back to the raw value when it is not a parseable JSON string.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def _trust_changed(before: Any, after: Any) -> bool:
    """True if any trust attribute differs between the before and after resource states."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    for attr in TRUST_ATTRIBUTES:
        if attr in before or attr in after:
            if _normalise_policy(before.get(attr)) != _normalise_policy(after.get(attr)):
                return True
    return False


def evaluate_plan(plan: dict) -> list[dict]:
    """Return a list of blocking findings. An empty list means the plan is safe to auto-apply.

    Each finding is a dict with keys: address, type, actions, reason.
    """
    findings: list[dict] = []
    for change_entry in plan.get("resource_changes") or []:
        change = change_entry.get("change") or {}
        actions = change.get("actions") or []
        address = change_entry.get("address", "<unknown>")
        rtype = change_entry.get("type", "<unknown>")

        if "delete" in actions:
            findings.append({"address": address, "type": rtype, "actions": actions, "reason": "destroy or replacement"})
            continue

        if rtype in IAM_SENSITIVE_TYPES and actions not in _INERT_ACTIONS:
            findings.append({"address": address, "type": rtype, "actions": actions, "reason": "IAM-sensitive change"})
            continue

        if _trust_changed(change.get("before"), change.get("after")):
            findings.append(
                {"address": address, "type": rtype, "actions": actions, "reason": "trust-policy (assume_role_policy) diff"}
            )

    return findings


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code (0 safe, 2 blocked, 1 error)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: terraform_apply_guard.py <plan.json>", file=sys.stderr)
        return 1

    path = args[0]
    try:
        with open(path, encoding="utf-8") as handle:
            plan = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"terraform_apply_guard: cannot read or parse {path!r}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(plan, dict):
        print(f"terraform_apply_guard: expected a JSON object at the top level, got {type(plan).__name__}", file=sys.stderr)
        return 1

    findings = evaluate_plan(plan)
    if findings:
        print("terraform_apply_guard: BLOCKED -- this plan requires a manual admin apply:")
        for finding in findings:
            print(f"  - {finding['address']} ({finding['type']}) actions={finding['actions']}: {finding['reason']}")
        return 2

    print("terraform_apply_guard: OK -- create/update/no-op/read on non-IAM resources, no trust diffs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
