from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_authority_budget", owner="platform")
def validate_authority_budget(failed: list[str]) -> None:
    """Drift-assertion gate: budget table agrees with the HCL boundary name + IAMRoleWriteBounded managed-role set.

    Checks:
    (a) boundary_policy_name in the budget appears in terraform/bootstrap/github_ci_apply.tf.
    (b) Every in_budget_managed_role appears in the HCL (present in IAMRoleWriteBounded resource targets).
    (c) Self-grant guard: the apply role (contains 'github-ci-apply') is not in in_budget_managed_roles.

    Eligible for both --pre and full tiers (pure Python, sub-second file reads). Override budget path
    via TF_AUTHORITY_BUDGET env var (test isolation; default: terraform/bootstrap/authority_budget.json).
    """
    print("\n=== Authority-budget drift gate (T2.25 / Decision 92 point 5) ===")
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

    # Use bounded matching: names must appear as ARN path components or quoted strings in HCL.
    # Bare substring matching is too broad -- a short name or prefix would match spuriously
    # across comment lines or other strings (H1, code-review 2026-06-29).
    boundary_name = budget.get("boundary_policy_name", "")
    # Boundary policy names appear as ":policy/<name>" in ARN strings in the HCL.
    if f":policy/{boundary_name}" not in hcl_text and f'"{boundary_name}"' not in hcl_text:
        failed.append(
            f"authority-budget: boundary_policy_name {boundary_name!r} not found in {hcl_path.name} -- "
            "budget and HCL are out of sync"
        )
        print(f"  FAIL: boundary_policy_name {boundary_name!r} missing from HCL.")
    else:
        print(f"  PASS: boundary_policy_name {boundary_name!r} found in HCL.")

    for role in budget.get("in_budget_managed_roles", []):
        # Role names appear as ":role/<name>" ARN path components in IAMRoleWriteBounded Resource lists.
        if f":role/{role}" not in hcl_text and f'"{role}"' not in hcl_text:
            failed.append(
                f"authority-budget: in_budget_managed_role {role!r} not found in {hcl_path.name} -- "
                "role is not a target in IAMRoleWriteBounded; remove from budget or update HCL"
            )
            print(f"  FAIL: managed role {role!r} missing from HCL.")
        else:
            print(f"  PASS: managed role {role!r} found in HCL.")
        if "github-ci-apply" in role:
            failed.append(f"authority-budget: self-grant guard -- apply role {role!r} must not be in in_budget_managed_roles")
            print(f"  FAIL: self-grant -- apply role {role!r} listed as managed.")

    budget_key = "authority-budget:"
    if not any(f.startswith(budget_key) for f in failed):
        print("  PASS: budget table is consistent with HCL.")
