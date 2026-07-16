"""Tests for validate_hermeticity_flags() and _build_unit_test_cmd()."""

from scripts.checks._scaffolding import _build_unit_test_cmd
from scripts.checks.verification.validate_hermeticity_flags import _UNIT_TEST_HERMETICITY_FLAGS, validate_hermeticity_flags


class TestValidateHermeticityFlags:
    """Tests for validate_hermeticity_flags() and _build_unit_test_cmd()."""

    def test_build_unit_test_cmd_contains_disable_socket(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--disable-socket" in cmd

    def test_build_unit_test_cmd_contains_randomly_seed(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--randomly-seed=last" in cmd

    def test_build_unit_test_cmd_contains_all_hermeticity_flags(self) -> None:
        cmd = _build_unit_test_cmd()
        for flag in _UNIT_TEST_HERMETICITY_FLAGS:
            assert flag in cmd, f"flag {flag!r} missing from _build_unit_test_cmd()"

    def test_validate_hermeticity_flags_passes_when_all_present(self) -> None:
        full_cmd = list(_build_unit_test_cmd())
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=full_cmd)
        assert failed == []

    def test_validate_hermeticity_flags_fails_when_disable_socket_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != "--disable-socket"]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 1
        assert "--disable-socket" in failed[0]

    def test_validate_hermeticity_flags_fails_when_randomly_seed_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != "--randomly-seed=last"]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 1
        assert "--randomly-seed=last" in failed[0]

    def test_validate_hermeticity_flags_fails_when_both_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c not in _UNIT_TEST_HERMETICITY_FLAGS]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 2

    def test_validate_hermeticity_flags_uses_build_cmd_by_default(self) -> None:
        failed: list[str] = []
        validate_hermeticity_flags(failed)
        assert failed == [], "default command must contain all hermeticity flags"
