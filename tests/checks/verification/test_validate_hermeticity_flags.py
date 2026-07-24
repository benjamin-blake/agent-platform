"""Tests for validate_hermeticity_flags() and _build_unit_test_cmd() (VTS-10/13/rec-2052,
audit validate-test-suite-4df4d48)."""

from unittest.mock import patch

from scripts.checks._scaffolding import _PYTEST_FLAGS, _PYTEST_RANDOMLY_SEED, _build_unit_test_cmd
from scripts.checks.verification.validate_hermeticity_flags import (
    _UNIT_TEST_HERMETICITY_FLAGS,
    _read_pyproject_addopts,
    validate_hermeticity_flags,
)

_FIXED_SEED_FLAG = f"--randomly-seed={_PYTEST_RANDOMLY_SEED}"


class TestBuildUnitTestCmd:
    """VTS-10/13: the full-tier command gains the fast tier's xdist/timeout/fixed-seed flags
    (parity, not a double-add) while keeping --cov/--disable-socket/--junitxml."""

    def test_contains_disable_socket(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--disable-socket" in cmd

    def test_contains_fixed_randomly_seed(self) -> None:
        cmd = _build_unit_test_cmd()
        assert _FIXED_SEED_FLAG in cmd

    def test_does_not_contain_randomly_seed_last(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--randomly-seed=last" not in cmd

    def test_contains_xdist_auto(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "-n" in cmd
        assert "auto" in cmd

    def test_contains_timeout_120(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--timeout" in cmd
        assert "120" in cmd

    def test_contains_timeout_method_thread(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--timeout-method=thread" in cmd

    def test_retains_cov_and_junitxml(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--cov=src" in cmd
        assert "--cov-report=term-missing" in cmd
        assert "--junitxml=logs/debug/pytest-junit.xml" in cmd

    def test_contains_all_hermeticity_flags(self) -> None:
        cmd = _build_unit_test_cmd()
        for flag in _UNIT_TEST_HERMETICITY_FLAGS:
            assert flag in cmd, f"flag {flag!r} missing from _build_unit_test_cmd()"


class TestValidateHermeticityFlags:
    """Tests for validate_hermeticity_flags() against an explicit _cmd override."""

    def test_passes_when_all_present(self) -> None:
        full_cmd = list(_build_unit_test_cmd())
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=full_cmd)
        assert failed == []

    def test_fails_when_disable_socket_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != "--disable-socket"]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert any("--disable-socket" in f for f in failed)

    def test_fails_when_fixed_seed_absent_from_full_cmd(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != _FIXED_SEED_FLAG]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert any(_FIXED_SEED_FLAG in f for f in failed)

    def test_fails_when_both_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c not in _UNIT_TEST_HERMETICITY_FLAGS]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert sum(1 for f in failed if "--disable-socket" in f or _FIXED_SEED_FLAG in f) == 2

    def test_uses_build_cmd_by_default(self) -> None:
        failed: list[str] = []
        validate_hermeticity_flags(failed)
        assert failed == [], "default command + real repo config must satisfy every guarded flag"


class TestWidenedGuardFastTierAndAddopts:
    """rec-2052: the guard also asserts the fast-tier _PYTEST_FLAGS carries the fixed seed and
    that pyproject.toml addopts still carries --disable-socket and --allow-hosts."""

    def test_passes_on_real_config(self) -> None:
        """Anti-vacuous: exercised against the REAL _PYTEST_FLAGS and the REAL pyproject.toml,
        not a mock, at least once."""
        failed: list[str] = []
        validate_hermeticity_flags(failed)
        assert failed == []

    def test_fails_when_fast_tier_flags_drop_the_fixed_seed(self) -> None:
        stripped = [f for f in _PYTEST_FLAGS if f != _FIXED_SEED_FLAG]
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_hermeticity_flags._PYTEST_FLAGS", stripped):
            validate_hermeticity_flags(failed)
        assert any("_PYTEST_FLAGS" in f for f in failed)

    def test_fails_when_addopts_missing_allow_hosts(self) -> None:
        stripped_addopts = ["-v", "--strict-markers", "--disable-socket", _FIXED_SEED_FLAG]
        failed: list[str] = []
        with patch(
            "scripts.checks.verification.validate_hermeticity_flags._read_pyproject_addopts",
            return_value=stripped_addopts,
        ):
            validate_hermeticity_flags(failed)
        assert any("allow-hosts" in f for f in failed)

    def test_fails_when_addopts_missing_disable_socket(self) -> None:
        stripped_addopts = ["-v", "--strict-markers", "--allow-hosts=127.0.0.1,::1"]
        failed: list[str] = []
        with patch(
            "scripts.checks.verification.validate_hermeticity_flags._read_pyproject_addopts",
            return_value=stripped_addopts,
        ):
            validate_hermeticity_flags(failed)
        assert any("disable-socket" in f for f in failed)

    def test_addopts_parse_failure_appends_distinct_entry(self) -> None:
        failed: list[str] = []
        with patch(
            "scripts.checks.verification.validate_hermeticity_flags._read_pyproject_addopts",
            side_effect=OSError("pyproject.toml unreadable"),
        ):
            validate_hermeticity_flags(failed)
        assert any("pyproject.toml" in f for f in failed)

    def test_real_pyproject_addopts_contains_allow_hosts_and_disable_socket(self) -> None:
        """Anti-vacuous: read the REAL pyproject.toml, not a mock, at least once."""
        addopts = _read_pyproject_addopts()
        assert "--disable-socket" in addopts
        assert any(a.startswith("--allow-hosts") for a in addopts)
