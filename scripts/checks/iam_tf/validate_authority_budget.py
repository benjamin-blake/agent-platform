from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_authority_budget", owner="platform")
def validate_authority_budget(failed: list[str]) -> None:
    """Drift-assertion gate: the authority budget agrees with the github_ci_apply.tf HCL.

    v2 (Decision 144 / T2.48, boundary-carrying agent-platform-* prefix):
    (a) boundary_policy_name appears in terraform/bootstrap/github_ci_apply.tf.
    (b) in_budget_managed_role_prefix maps to the IAMRoleWriteBounded Resource role/<prefix>* in the HCL.
    (c) Apply-role self-exclusion: the explicit DenySelfInlinePolicyWrite carve-out of the apply role's
        own ARN exists in the HCL (the widened prefix necessarily matches agent-platform-github-ci-apply,
        so the self-grant break must be an explicit Deny -- upgrades the v1 substring self-grant guard).
    (d) in_budget_actions == ["create", "update"] (create newly in-budget; was update-only).

    v1 (legacy enumerated in_budget_managed_roles) is still accepted as a fail-safe fallback:
    every listed role must appear in the HCL, and the apply role must not be listed.

    Eligible for both --pre and full tiers (pure Python, sub-second file reads). Override budget path
    via TF_AUTHORITY_BUDGET env var (test isolation; default: terraform/bootstrap/authority_budget.json).
    """
    print("\n=== Authority-budget drift gate (T2.25 / T2.48 / Decision 92 point 5 / Decision 144) ===")
    budget_path_env = os.environ.get("TF_AUTHORITY_BUDGET")
    budget_path = (
        Path(budget_path_env) if budget_path_env else _common.ROOT / "terraform" / "bootstrap" / "authority_budget.json"
    )
    try:
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failed.append(f"authority-budget: cannot read or parse {budget_path}: {exc}")
        print(f"  FAIL: cannot load budget table: {exc}")
        return

    hcl_path = _common.ROOT / "terraform" / "bootstrap" / "github_ci_apply.tf"
    try:
        hcl_text = hcl_path.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"authority-budget: cannot read {hcl_path.name}: {exc}")
        print(f"  FAIL: cannot read HCL: {exc}")
        return

    # (a) boundary name must appear as ":policy/<name>" or a quoted literal in the HCL. Bounded matching
    # (H1, code-review 2026-06-29): bare substring matching is too broad across comments/other strings.
    boundary_name = budget.get("boundary_policy_name", "")
    if f":policy/{boundary_name}" not in hcl_text and f'"{boundary_name}"' not in hcl_text:
        failed.append(
            f"authority-budget: boundary_policy_name {boundary_name!r} not found in {hcl_path.name} -- "
            "budget and HCL are out of sync"
        )
        print(f"  FAIL: boundary_policy_name {boundary_name!r} missing from HCL.")
    else:
        print(f"  PASS: boundary_policy_name {boundary_name!r} found in HCL.")

    prefix = budget.get("in_budget_managed_role_prefix")
    if prefix:
        _check_v2_prefix(budget, hcl_text, hcl_path.name, prefix, failed)
    else:
        _check_v1_enumerated(budget, hcl_text, hcl_path.name, failed)

    _check_in_budget_actions(budget, bool(prefix), failed)

    if not any(f.startswith("authority-budget:") for f in failed):
        print("  PASS: budget table is consistent with HCL.")


def _check_v2_prefix(budget: dict, hcl_text: str, hcl_name: str, prefix: str, failed: list[str]) -> None:
    """v2: the managed-role prefix maps to role/<prefix>* in the HCL and the apply role is self-excluded."""
    marker = f"role/{prefix}*"  # e.g. role/agent-platform-*
    if marker not in hcl_text:
        failed.append(
            f"authority-budget: in_budget_managed_role_prefix {prefix!r} does not map to a {marker!r} Resource "
            f"in the IAMRoleWriteBounded SCP in {hcl_name} -- budget and HCL are out of sync"
        )
        print(f"  FAIL: managed-role prefix {prefix!r} not mapped to {marker!r} in HCL.")
    else:
        print(f"  PASS: managed-role prefix {prefix!r} maps to {marker!r} in HCL.")

    # (c) The widened prefix matches the apply role's own ARN, so an explicit self-exclusion Deny is
    # MANDATORY (retains the T2.23 self-grant break). Assert the DenySelfInlinePolicyWrite carve-out.
    self_excl = budget.get("apply_role_self_exclusion", "agent-platform-github-ci-apply")
    if "DenySelfInlinePolicyWrite" not in hcl_text or f"role/{self_excl}" not in hcl_text:
        failed.append(
            f"authority-budget: v2 prefix budget requires an explicit DenySelfInlinePolicyWrite carve-out of "
            f"role/{self_excl} in {hcl_name} (the widened prefix matches the apply role's own ARN) -- "
            "the T2.23 self-grant break is missing"
        )
        print(f"  FAIL: DenySelfInlinePolicyWrite self-exclusion of {self_excl!r} missing from HCL.")
    else:
        print(f"  PASS: DenySelfInlinePolicyWrite self-exclusion of {self_excl!r} present in HCL.")


def _check_v1_enumerated(budget: dict, hcl_text: str, hcl_name: str, failed: list[str]) -> None:
    """v1 fallback: every enumerated managed role appears in the HCL and the apply role is not listed."""
    for role in budget.get("in_budget_managed_roles", []):
        if f":role/{role}" not in hcl_text and f'"{role}"' not in hcl_text:
            failed.append(
                f"authority-budget: in_budget_managed_role {role!r} not found in {hcl_name} -- "
                "role is not a target in IAMRoleWriteBounded; remove from budget or update HCL"
            )
            print(f"  FAIL: managed role {role!r} missing from HCL.")
        else:
            print(f"  PASS: managed role {role!r} found in HCL.")
        if "github-ci-apply" in role:
            failed.append(f"authority-budget: self-grant guard -- apply role {role!r} must not be in in_budget_managed_roles")
            print(f"  FAIL: self-grant -- apply role {role!r} listed as managed.")


def _check_in_budget_actions(budget: dict, is_v2: bool, failed: list[str]) -> None:
    """v2 requires in_budget_actions == [create, update]; v1 requires [update]."""
    actions = budget.get("in_budget_actions", [])
    expected = ["create", "update"] if is_v2 else ["update"]
    if sorted(actions) != sorted(expected):
        failed.append(
            f"authority-budget: in_budget_actions must be {expected} for a "
            f"{'v2 prefix' if is_v2 else 'v1 enumerated'} budget, got {actions}"
        )
        print(f"  FAIL: in_budget_actions {actions} != {expected}.")
    else:
        print(f"  PASS: in_budget_actions == {expected}.")


if __name__ == "__main__":  # pragma: no cover
    _failed: list[str] = []
    validate_authority_budget(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
