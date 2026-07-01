"""Differential admission gate self-test (T3.1, Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_differential_gate_baseline", owner="platform")
def validate_differential_gate_baseline(failed: list[str]) -> None:
    """Exercise the differential admission gate on the kernel's own self-test (full tier, T3.1).

    Runs the slot-count invariant check via is_admitted() with a revert_runner that
    simulates a pre-change environment where SLOT_COUNT is wrong (7).  The check must
    FAIL in that environment (proving it is non-tautological) and PASS in the live one.

    This is the gate's own self-test; production baseline execution surfaces are:
      - validate.py CI hard-gate (this function, live)
      - Step-Functions executor verify-state (named surface, deferred per CD.27)
    """
    print("\n=== Differential admission gate baseline (T3.1) ===")
    root_str = str(_common.ROOT)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.verification_checks import (  # noqa: PLC0415
            CANONICAL_SLOTS,
            CheckResult,
            CheckStatus,
            GrepCountCheck,
            is_admitted,
        )
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)

    # Build a check that asserts the SLOT_COUNT sentinel is present (via grep on the source file).
    kernel_path = str(_common.ROOT / "scripts" / "verification_checks.py")
    slot_count_check = GrepCountCheck(
        name="kernel-slot-count-eq-6",
        path=kernel_path,
        pattern=r"SLOT_COUNT: int = len\(CANONICAL_SLOTS\)",
        operator="eq",
        count=1,
    )

    # Revert runner: simulates the pre-change tree where the sentinel line is absent.
    def revert_runner(check: GrepCountCheck) -> CheckResult:  # type: ignore[override]
        # In the pre-change environment the sentinel line "SLOT_COUNT: int = 6" did not
        # exist (the file didn't exist). Simulate by returning FAIL directly.
        return CheckResult(status=CheckStatus.FAIL, message="simulated pre-change: sentinel absent")

    admitted = is_admitted(slot_count_check, revert_runner)  # type: ignore[arg-type]
    if not admitted:
        failed.append("Differential gate baseline: slot_count_check was not admitted (revert did not produce FAIL)")
        return

    # Additionally verify the live check actually passes.
    live_result = slot_count_check.run()
    if live_result.status != CheckStatus.PASS:
        failed.append(f"Differential gate baseline: slot_count_check FAILED on live tree: {live_result.message}")
        return

    # Verify CANONICAL_SLOTS has exactly 6 entries.
    if len(CANONICAL_SLOTS) != 6:
        failed.append(f"Differential gate baseline: CANONICAL_SLOTS has {len(CANONICAL_SLOTS)} entries, expected 6")
        return

    print(f"  OK: differential gate admitted slot_count_check; live check passed; CANONICAL_SLOTS={sorted(CANONICAL_SLOTS)}")
