"""Lambda deploy gating advisory check (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_lambda_deploy_gating", owner="platform")
def validate_lambda_deploy_gating(failed: list[str]) -> None:
    """Advisory per-Lambda deploy-scope check (CD.16 + Decision 79).

    Calls compute_affected_artifacts() with the current branch's changed files
    and reports which active Lambda artifacts need per-Lambda deploy/verify
    attention in the plan. Advisory only -- never fails the build; only appends
    to failed on import or setup errors.
    """
    print("\n=== Lambda deploy gating (advisory) ===")

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import compute_affected_artifacts  # noqa: PLC0415

        changed = list(_common.get_changed_files())
        if not changed:
            print("  No changed files detected; skipping deploy-gating scope check.")
            return

        affected = compute_affected_artifacts(changed)
        if not affected:
            print("  No active Lambda artifacts affected by current branch changes.")
            return

        print("  Active Lambda artifacts affected by branch changes (plan must include deploy steps):")
        for slug, files in sorted(affected.items()):
            print(f"    {slug}: {len(files)} file(s) changed")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda deploy gating")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda deploy gating")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
