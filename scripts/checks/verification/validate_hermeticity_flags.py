"""Unit-test hermeticity-flag enforcement (Decision 104)."""

from __future__ import annotations

from scripts.checks import _common, registry
from scripts.checks._scaffolding import _PYTEST_FLAGS, _PYTEST_RANDOMLY_SEED

_UNIT_TEST_HERMETICITY_FLAGS: tuple[str, ...] = ("--disable-socket", f"--randomly-seed={_PYTEST_RANDOMLY_SEED}")


def _read_pyproject_addopts() -> list[str]:
    """Read [tool.pytest.ini_options].addopts from pyproject.toml (read-only parse; pyproject.toml
    itself is never modified by this check -- rec-2052)."""
    import tomllib  # noqa: PLC0415

    pyproject_path = _common.ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    addopts = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts", [])
    return list(addopts) if addopts else []


@registry.register("validate_hermeticity_flags", owner="platform")
def validate_hermeticity_flags(failed: list[str], _cmd: list[str] | None = None) -> None:
    """Fail CI if mandatory hermeticity flags are absent from the unit-test pytest command.

    Guards against accidental removal of --disable-socket or the fixed --randomly-seed from the
    full-tier test invocation. VTS-10/13 (audit validate-test-suite-4df4d48): the guarded seed is
    now the SAME fixed rec-2653 seed the fast tier already carries (--randomly-seed=last is no
    longer accepted here -- a fixed integer seed is what makes -n auto xdist collection stable
    across workers). Accepts an optional _cmd override for unit-testing this function itself.

    rec-2052 widened-guard additions (each a distinct failed[] entry):
    - the fast-tier _PYTEST_FLAGS list must ALSO carry the same fixed seed, so the two tiers can
      never drift apart on this flag again;
    - pyproject.toml's addopts (read-only parse; addopts itself is never modified here) must still
      carry --disable-socket and an --allow-hosts entry -- the local-dev/implicit-pytest-invocation
      hermeticity floor that the explicit command builders don't restate, but that a stray
      pyproject.toml edit could otherwise silently drop unnoticed.
    """
    if _cmd is not None:
        cmd = _cmd
    else:
        from scripts.checks._scaffolding import _build_unit_test_cmd  # noqa: PLC0415

        cmd = _build_unit_test_cmd()
    for flag in _UNIT_TEST_HERMETICITY_FLAGS:
        if flag not in cmd:
            failed.append(f"hermeticity-flags: {flag!r} missing from pytest invocation")

    fixed_seed = f"--randomly-seed={_PYTEST_RANDOMLY_SEED}"
    if fixed_seed not in _PYTEST_FLAGS:
        failed.append(f"hermeticity-flags: {fixed_seed!r} missing from the fast-tier _PYTEST_FLAGS")

    try:
        addopts = _read_pyproject_addopts()
    except Exception as exc:  # noqa: BLE001
        failed.append(f"hermeticity-flags: could not parse pyproject.toml addopts: {exc}")
        return

    if "--disable-socket" not in addopts:
        failed.append("hermeticity-flags: '--disable-socket' missing from pyproject.toml addopts")
    if not any(opt.startswith("--allow-hosts") for opt in addopts):
        failed.append("hermeticity-flags: '--allow-hosts' missing from pyproject.toml addopts")
