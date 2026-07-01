"""Lambda bundle completeness validation (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_lambda_bundle_completeness", owner="platform")
def validate_lambda_bundle_completeness(failed: list[str]) -> None:
    """Stage each active Lambda artifact and verify handler imports + declared assets.

    Delegates to scripts.lambda_manifest.cmd_check_bundles, which stages each
    active manifest into a temp dir, checks that every handler module can be
    imported from the staged tree, and checks that every declared assets[]/config[]
    path is physically present in the staged bundle.

    Full presubmit tier ONLY -- NOT --pre (Decision 73: the import-resolution check
    catches missing includes that py_compile cannot see; the asset-presence check
    catches undeclared runtime filesystem reads).
    """
    print("\n=== Lambda bundle completeness ===")

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import cmd_check_bundles  # noqa: PLC0415

        rc = cmd_check_bundles(None)
        if rc != 0:
            failed.append("Lambda bundle completeness")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda bundle completeness")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda bundle completeness")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
