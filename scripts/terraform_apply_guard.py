#!/usr/bin/env python3
"""Deterministic guard for the sandbox auto-apply pipeline (Decision 77).

Parses `terraform show -json <planfile>` output and decides whether the plan is safe to
auto-apply in the sandbox environment without a human in the loop. The guard is the fail-closed
plan-CONTENT control (Decision 77 / CD.35): it, together with a subagent plan review, IS the
apply gate. Branch protection is now active (main-protection ruleset, Decision 83 / CD.20) but
deliberately non-wedging -- the guard + review remain the content gate. It MUST fail closed.

Exit codes (consumed by .github/workflows/terraform-apply-sandbox.yml):
  0  plan is safe: only create / update / no-op / read on non-IAM resources, no trust diffs, and
     any neon_* change is a pure create / no-op / read; OR an in-budget IAM inline-policy /
     attachment UPDATE on a managed boundary-carrying role (T2.25 / Decision 92 point 5).
  2  plan is BLOCKED: contains a destroy, a replacement, a trust-policy (assume_role_policy) diff,
     an out-of-budget IAM-sensitive change, or a non-create neon_* change. Requires a manual
     admin apply or a gated-apply Environment approval.
  1  internal / parse error (also blocks apply at the workflow level).

--digest mode (T2.39 / rec-2658 forward-fix): `terraform_apply_guard.py --digest <plan.json>`
  prints a bounded, decision-relevant plan summary to stdout and exits 0 (parse errors still
  exit 1). Reuses this module's own resource_changes traversal (build_digest -> _digest_entries)
  so the digest can never drift from the verdict evaluate_plan() computes. Consumed by the
  sandbox subagent plan-review step, which pipes the digest on stdin instead of handing the
  reviewer a bare plan.json filename to read itself (rec-2658 root cause: reading the full
  terraform show -json dump burned the entire turn budget before a verdict was reached). Bounded
  to _DIGEST_SIZE_CAP bytes with an explicit truncation marker on overflow, and redacts AWS ARNs /
  12-digit account ids (Decision 101 public-content boundary) before it ever reaches stdout.

Detection contract (against `terraform show -json`, iterating .resource_changes[]):
  - BLOCK if .change.actions contains "delete" (covers ["delete"] destroys and the replacement
    pairs ["delete","create"] / ["create","delete"]).
  - BLOCK if .type is a neon_* resource AND .change.actions is not a pure ["create"]/["no-op"]/
    ["read"] (T2.16b / CD.34). The DuckLake catalog is the lakehouse's single point of total
    failure, so its third-party Neon resources auto-apply only as pure creates. An update is where
    an IP allow-list widening / role-credential rotation / project-setting change would land;
    delete + replace are already blocked by the rule above. A create is allowed on the strength of
    compensating controls (enforced TLS sslmode=require + a scoped neon_role + the DSN in Secrets
    Manager), NOT an IP allow-list -- Neon IP-Allow is Scale-plan-only and unavailable on the free
    tier, and egress here is dynamic (REPORT R3 / CD.34). The compensating controls are enforced in
    neon_ducklake_catalog.tf, not introspected here, so the guard stays robust against the
    sensitive/unknown attribute values a Neon create reports at plan time.
  - BLOCK if a trust attribute (assume_role_policy) differs between .change.before and
    .change.after on ANY resource. assume_role_policy is serialised as a JSON-encoded string, so
    it is normalised via json.loads before comparison (key-order/whitespace differences do not
    cause nuisance trips). Trust check runs BEFORE IAM classification (T2.25) so a trust diff on
    a managed role is always gated, never slips through as an in-budget update.
  - PASS (in-budget) if .type is in in_budget_resource_types, .change.actions == in_budget_actions
    (["update"]), AND the target role name (.change.after.role or .change.before.role) is in
    in_budget_managed_roles (T2.25 / Decision 92 point 5). Budget table loaded from
    terraform/bootstrap/authority_budget.json (override via TF_AUTHORITY_BUDGET env var). Missing
    or unparseable table = fail closed (all IAM treated as out-of-budget, Decision 77).
  - BLOCK if .type is IAM-sensitive AND .change.actions is not ["no-op"]/["read"] AND not in-budget.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
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

# Third-party Neon provider resources (T2.16b / CD.34). Type prefix kislerdm/neon exposes.
NEON_PROVIDER_PREFIX = "neon_"

# Action sets a neon_* resource may auto-apply with: a pure create (the only provisioning path) or an
# inert no-op/read. Anything else (notably ["update"]) is blocked; delete/replace are caught earlier
# by the "delete" rule. A bare create is allowed because compensating controls -- not an IP allow-list
# -- carry the posture (see the module docstring's Neon detection-contract bullet).
_NEON_SAFE_ACTIONS = (["create"], ["no-op"], ["read"])

# Default path for the authority budget table (T2.25 / Decision 92 point 5). Override via TF_AUTHORITY_BUDGET.
_BUDGET_DEFAULT_PATH = Path(__file__).parent.parent / "terraform" / "bootstrap" / "authority_budget.json"


def _load_budget() -> Optional[dict]:
    """Load the authority budget table from TF_AUTHORITY_BUDGET or the default path.

    Returns None on any failure (missing file, parse error). A None budget is fail-closed:
    _classify_iam_change treats every IAM change as out-of-budget.
    """
    path_env = os.environ.get("TF_AUTHORITY_BUDGET")
    path = Path(path_env) if path_env else _BUDGET_DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _classify_iam_change(change_entry: dict, budget: Optional[dict]) -> bool:
    """Return True if this IAM change is in-budget (safe to auto-apply without gated-apply).

    In-budget = resource type in in_budget_resource_types, action set equals in_budget_actions
    (["update"]), and the target role name is in in_budget_managed_roles. Missing budget or
    missing role attribute returns False (fail-closed).
    """
    if budget is None:
        return False
    rtype = change_entry.get("type", "")
    if rtype not in budget.get("in_budget_resource_types", []):
        return False
    change = change_entry.get("change") or {}
    if change.get("actions") != budget.get("in_budget_actions", []):
        return False
    after = change.get("after") or {}
    before = change.get("before") or {}
    role = after.get("role") or before.get("role")
    if not role:
        return False
    return role in budget.get("in_budget_managed_roles", [])


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


def evaluate_plan(plan: dict, budget: Optional[dict] = None) -> list[dict]:
    """Return a list of blocking findings. An empty list means the plan is safe to auto-apply.

    Each finding is a dict with keys: address, type, actions, reason.

    Pass the loaded authority budget (from _load_budget()) to enable in-budget IAM classification.
    A None budget is fail-closed: all IAM changes are treated as out-of-budget and blocked.

    Evaluation order (T2.25): delete -> neon -> trust-diff -> IAM (in-budget pass / out-of-budget block).
    Trust check runs before IAM so a trust diff on a managed role is always gated.
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

        if rtype.startswith(NEON_PROVIDER_PREFIX) and actions not in _NEON_SAFE_ACTIONS:
            findings.append(
                {
                    "address": address,
                    "type": rtype,
                    "actions": actions,
                    "reason": "non-create neon_* change (allow-list / credential / project-setting mutation)",
                }
            )
            continue

        if _trust_changed(change.get("before"), change.get("after")):
            findings.append(
                {"address": address, "type": rtype, "actions": actions, "reason": "trust-policy (assume_role_policy) diff"}
            )
            continue

        if rtype in IAM_SENSITIVE_TYPES and actions not in _INERT_ACTIONS:
            if _classify_iam_change(change_entry, budget):
                continue  # in-budget inline-policy / attachment update on managed boundary-carrying role
            findings.append(
                {"address": address, "type": rtype, "actions": actions, "reason": "IAM-sensitive change (out-of-budget)"}
            )
            continue

    return findings


# ---------------------------------------------------------------------------
# --digest mode (T2.39 / rec-2658 forward-fix): bounded, redacted plan summary for the
# subagent reviewer's stdin. See the module docstring's "--digest mode" section.
# ---------------------------------------------------------------------------

# Bounded so the reviewer's turn budget is spent judging, not reading (rec-2658 root cause).
_DIGEST_SIZE_CAP = 8000  # bytes

_TRUNCATION_MARKER = "\n... [DIGEST TRUNCATED: size cap reached -- see plan.json for full detail] ...\n"

# ARN token: "arn:aws:<service>:<region>:<account-or-empty>:<resource>". Matches up to the first
# whitespace/quote/backslash so a redacted ARN never bleeds into adjacent digest text.
_ARN_PATTERN = re.compile(r"arn:aws:[a-zA-Z0-9_\-]*:[a-zA-Z0-9_\-]*:[0-9]*:[^\s\"'\\]*")
# Bare 12-digit AWS account id, not part of a longer digit run (word-boundary via negative lookaround).
_ACCOUNT_ID_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _redact(text: str) -> str:
    """Redact AWS ARNs and bare 12-digit account ids (Decision 101 public-content boundary).

    Order matters: ARN redaction runs first so an account id embedded inside an ARN is consumed
    as part of the ARN token (one [ARN] marker) rather than leaving a dangling [ACCOUNT_ID] inside
    already-redacted text.
    """
    text = _ARN_PATTERN.sub("[ARN]", text)
    text = _ACCOUNT_ID_PATTERN.sub("[ACCOUNT_ID]", text)
    return text


def _summarise_value(value: Any, max_len: int = 80) -> str:
    """Return a bounded, single-line string representation of a changed attribute's new value.

    Dicts/lists are compacted via json.dumps (default=str so a non-JSON-native value, e.g. a
    terraform "(known after apply)" sentinel object, never raises); scalars use repr(). Newlines
    are flattened so a value can never break the digest's one-line-per-resource shape, and the
    result is truncated to max_len so one large attribute cannot dominate the size budget.
    """
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str)
    else:
        text = repr(value)
    text = text.replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def _changed_top_level_attrs(before: Any, after: Any) -> list[tuple[str, Any]]:
    """Return sorted (name, new_value) pairs for top-level attributes that differ.

    Top-level only (not a deep diff) -- sufficient for a decision-relevant summary without
    ballooning digest size on large nested attributes (e.g. a full IAM policy document body); the
    reviewer sees WHICH attributes changed and a bounded snippet of the resulting (after) value.
    """
    before_d = before if isinstance(before, dict) else {}
    after_d = after if isinstance(after, dict) else {}
    keys = set(before_d.keys()) | set(after_d.keys())
    changed = sorted(k for k in keys if before_d.get(k) != after_d.get(k))
    return [(k, after_d.get(k)) for k in changed]


def _digest_entries(plan: dict) -> list[dict]:
    """One summary row per resource_changes entry, via the SAME traversal evaluate_plan() uses.

    Sharing the traversal (plan.get("resource_changes") or []) means the digest can never list a
    different resource set than the one the guard verdict was computed over.
    """
    entries: list[dict] = []
    for change_entry in plan.get("resource_changes") or []:
        change = change_entry.get("change") or {}
        entries.append(
            {
                "address": change_entry.get("address", "<unknown>"),
                "type": change_entry.get("type", "<unknown>"),
                "actions": change.get("actions") or [],
                "changed_attrs": _changed_top_level_attrs(change.get("before"), change.get("after")),
            }
        )
    return entries


def build_digest(plan: dict, size_cap: int = _DIGEST_SIZE_CAP) -> str:
    """Build a bounded, redacted, decision-relevant plan summary for inline reviewer stdin.

    One line per resource_changes entry (address / type / actions / changed top-level attributes,
    each with a bounded snippet of its new value). ARNs and 12-digit account ids are redacted
    before the digest is ever returned. If the redacted digest would exceed size_cap bytes, it is
    truncated at a line boundary (never mid-entry) and an explicit truncation marker is appended --
    a silent truncation would let a reviewer PROCEED on a partial view of the plan, which is the
    failure this cap exists to avoid.
    """
    entries = _digest_entries(plan)
    lines = [f"Plan summary: {len(entries)} resource change(s)."]
    for entry in entries:
        if entry["changed_attrs"]:
            attrs = ", ".join(f"{name}={_summarise_value(value)}" for name, value in entry["changed_attrs"])
        else:
            attrs = "(none)"
        lines.append(_redact(f"- {entry['address']} ({entry['type']}) actions={entry['actions']} changed_attrs=[{attrs}]"))

    full = "\n".join(lines)
    if len(full.encode("utf-8")) <= size_cap:
        return full

    marker_bytes = len(_TRUNCATION_MARKER.encode("utf-8"))
    budget = max(0, size_cap - marker_bytes)
    kept: list[str] = []
    used = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for the joining newline
        if used + line_bytes > budget:
            break
        kept.append(line)
        used += line_bytes
    return "\n".join(kept) + _TRUNCATION_MARKER


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Returns the process exit code (0 safe/digest-printed, 2 blocked, 1 error)."""
    args = list(sys.argv[1:] if argv is None else argv)

    digest_mode = "--digest" in args
    if digest_mode:
        args = [a for a in args if a != "--digest"]

    if len(args) != 1:
        print("usage: terraform_apply_guard.py [--digest] <plan.json>", file=sys.stderr)
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

    if digest_mode:
        print(build_digest(plan))
        return 0

    budget = _load_budget()
    findings = evaluate_plan(plan, budget)
    if findings:
        print("terraform_apply_guard: BLOCKED -- this plan requires a manual admin apply or gated-apply approval:")
        for finding in findings:
            print(f"  - {finding['address']} ({finding['type']}) actions={finding['actions']}: {finding['reason']}")
        return 2

    print("terraform_apply_guard: OK -- safe to auto-apply (non-IAM or in-budget IAM, no trust diffs).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
