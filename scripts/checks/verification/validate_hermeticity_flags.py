"""Unit-test hermeticity-flag enforcement (Decision 104)."""

from __future__ import annotations

from scripts.checks import registry

_UNIT_TEST_HERMETICITY_FLAGS: tuple[str, ...] = ("--disable-socket", "--randomly-seed=last")


@registry.register("validate_hermeticity_flags", owner="platform")
def validate_hermeticity_flags(failed: list[str], _cmd: list[str] | None = None) -> None:
    """Fail CI if mandatory hermeticity flags are absent from the unit-test pytest command.

    Guards against accidental removal of --disable-socket or --randomly-seed=last from the
    test invocation. Accepts an optional _cmd override for unit-testing this function itself.
    """
    if _cmd is not None:
        cmd = _cmd
    else:
        from scripts.validate import _build_unit_test_cmd  # noqa: PLC0415

        cmd = _build_unit_test_cmd()
    for flag in _UNIT_TEST_HERMETICITY_FLAGS:
        if flag not in cmd:
            failed.append(f"hermeticity-flags: {flag!r} missing from pytest invocation")
