from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_invariants", owner="platform")
def validate_invariants(failed: list[str]) -> None:
    """Check codebase-level invariants that guard known failure modes.

    Check 1 (@file gotcha): Scan scripts/ for direct copilot subprocess
    invocations that use '-p @file' without an inline instruction string --
    this causes agentic models to implement specs rather than plan against
    them (see 'Copilot CLI @file vs user message' gotcha).

    Check 2 (mock count): Verify that the subprocess.run calls added to
    cleanup_after_merge() in scripts/executor/postflight.py are covered by the
    mock side_effect lists in TestCleanupAfterMerge. A mismatch causes silent
    StopIteration failures in CI (see 'cleanup_after_merge mock exhaustion' gotcha).
    """
    print("\n=== Invariant checks ===")
    errors: list[str] = []
    scripts_dir = _common.ROOT / "scripts"

    # -----------------------------------------------------------------------
    # Check 1: @file without instruction in copilot subprocess calls
    # If any script constructs a copilot command with '-p @file' (without a
    # preceding instruction string), flag it.
    # -----------------------------------------------------------------------
    at_file_pattern = re.compile(r'"-p"\s*,\s*f?"@')
    for py_file in sorted(scripts_dir.glob("**/*.py")):
        content = py_file.read_text(encoding="utf-8")
        for m in at_file_pattern.finditer(content):
            line_num = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(_common.ROOT)
            errors.append(
                f"{rel}:{line_num}: Copilot CLI @file used without instruction string -- "
                "see 'Copilot CLI @file vs user message' gotcha and docs/contracts/copilot-cli.md"
            )

    # -----------------------------------------------------------------------
    # Check 2: cleanup_after_merge mock side_effect count
    # Count subprocess.run calls in cleanup_after_merge() and compare against
    # the maximum side_effect list length in TestCleanupAfterMerge tests.
    # Formula: subprocess_count > max_side_effect * 2 + 2 -> mismatch
    # (The factor of 2+2 accounts for conditional branches that not all tests
    # exercise; adding a new subprocess.run call shifts the balance.)
    # -----------------------------------------------------------------------
    postflight_path = _common.ROOT / "scripts" / "executor" / "postflight.py"
    test_path = _common.ROOT / "tests" / "test_execute_recommendation.py"
    if postflight_path.exists() and test_path.exists():
        postflight_src = postflight_path.read_text(encoding="utf-8")
        # Extract cleanup_after_merge function body
        fn_match = re.search(
            r"def cleanup_after_merge\(.*?\).*?(?=\ndef |\Z)",
            postflight_src,
            re.DOTALL,
        )
        if fn_match:
            fn_body = fn_match.group()
            subprocess_count = len(re.findall(r"\bsubprocess\.run\(", fn_body))

            test_src = test_path.read_text(encoding="utf-8")
            # Find TestCleanupAfterMerge class body
            class_match = re.search(
                r"class TestCleanupAfterMerge\b.*?(?=\nclass |\Z)",
                test_src,
                re.DOTALL,
            )
            if class_match:
                class_body = class_match.group()
                # Find all list literals containing MagicMock items (covers both
                # inline side_effect=[...] and pre-assigned variables like responses=[...])
                list_items_pattern = re.compile(
                    r"\[([^\[\]]*(?:MagicMock|CalledProcessError)[^\[\]]*)\]",
                    re.DOTALL,
                )
                max_side_effect = 0
                for match in list_items_pattern.finditer(class_body):
                    item_count = len(re.findall(r"MagicMock\(", match.group(1)))
                    max_side_effect = max(max_side_effect, item_count)

                threshold = max_side_effect * 2 + 2
                if subprocess_count > threshold:
                    errors.append(
                        f"cleanup_after_merge mock side_effect count mismatch: "
                        f"function has {subprocess_count} subprocess.run calls but "
                        f"max side_effect list has {max_side_effect} entries "
                        f"(threshold: {threshold}). Update TestCleanupAfterMerge side_effect lists."
                    )

    if errors:
        print("Invariant check errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Invariant checks")
    else:
        print("All invariant checks passed.")
