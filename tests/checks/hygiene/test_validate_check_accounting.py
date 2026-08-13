"""Tests for validate_check_accounting() -- the declaration ratchet (Decision 170;
docs/contracts/check-accounting.yaml). Exercises the guard in all five directions: undeclared +
unbaselined fails, config-edit-alone admission fails (frozen-constant cross-check), a declaring
check passes, net baseline growth fails, an edited-but-unadopted baselined check fails
(touch-it-fix-it), and an absent base SKIPs loudly rather than passing silently.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.hygiene.validate_check_accounting import (
    _check_module_rel_path,
    _module_declares,
    validate_check_accounting,
)

_UNDECLARED_SOURCE = """
def fake_check(failed):
    pass
"""

_DECLARING_SOURCE = """
from scripts.checks import registry


def fake_check(failed):
    registry.examined(1)
"""

_VALID_CONTRACT = """
contract:
  id: check-accounting
  class: D
  contract_version: 1
  status: ratified
  ratified_via: "Decision 170 / PLAN-validate-vacuous-pass-accounting"
  description: test fixture
  subject: check-accounting
  evaluator:
    check: validate_check_accounting
amendment_log: []
status_vocabulary:
  - failed
  - skipped
  - vacuous
  - enforced
  - undeclared
"""


def _write_module(tmp_path: Path, rel_path: str, source: str, module_name: str):
    full_path = tmp_path / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_contract(tmp_path: Path, text: str = _VALID_CONTRACT) -> None:
    contract_path = tmp_path / "docs" / "contracts" / "check-accounting.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(text, encoding="utf-8")


class TestUndeclaredUnbaselinedCheckFails:
    def test_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        module = _write_module(tmp_path, "scripts/checks/fake/fake_undeclared.py", _UNDECLARED_SOURCE, "fake_undeclared_mod")
        checks = {"fake_check": registry.Check(name="fake_check")}

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.fake_check),
            patch("scripts.checks._marker_guard.default_base_reader", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "Check-accounting declaration ratchet" in failed


class TestDeclaringCheckPasses:
    def test_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        module = _write_module(tmp_path, "scripts/checks/fake/fake_declaring.py", _DECLARING_SOURCE, "fake_declaring_mod")
        checks = {"fake_check": registry.Check(name="fake_check")}

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.fake_check),
            patch("scripts.checks._marker_guard.default_base_reader", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert failed == []


class TestConfigEditAloneAdmissionFails:
    """A synthetic check declaring nothing, added to the baseline directly, still FAILS: the
    frozen _BASELINE_SEED constant does not list it, so a config-file edit alone cannot admit it."""

    def test_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        module = _write_module(tmp_path, "scripts/checks/fake/fake_undeclared.py", _UNDECLARED_SOURCE, "fake_undeclared_mod2")
        checks = {"fake_check": registry.Check(name="fake_check")}
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries:\n  - fake_check\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.fake_check),
            patch("scripts.checks._marker_guard.default_base_reader", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "Check-accounting declaration ratchet" in failed


class TestBaselineGrowthFails:
    """Any net growth of the baseline relative to the committed base FAILS -- even for a name
    that IS in the frozen seed (isolates the shrink-only diff check from the frozen-constant one)."""

    def test_growth_relative_to_base_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries:\n  - validate_placement\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value={}),
            patch("scripts.checks._marker_guard.default_base_reader", return_value="entries: []\n"),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "Check-accounting declaration ratchet" in failed

    def test_shrink_is_allowed(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries: []\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value={}),
            patch("scripts.checks._marker_guard.default_base_reader", return_value="entries:\n  - validate_placement\n"),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert failed == []


class TestTouchItFixIt:
    def test_edited_baselined_check_without_declaration_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        rel_path = "scripts/checks/fake/validate_placement.py"
        module = _write_module(tmp_path, rel_path, _UNDECLARED_SOURCE, "fake_validate_placement_mod")
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries:\n  - validate_placement\n", encoding="utf-8")
        checks = {"validate_placement": registry.Check(name="validate_placement")}

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.fake_check),
            patch("scripts.checks._marker_guard.default_base_reader", return_value="entries:\n  - validate_placement\n"),
            patch("scripts.checks._common.get_changed_files", return_value=[rel_path]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "Check-accounting declaration ratchet" in failed

    def test_unedited_baselined_check_without_declaration_passes(self, tmp_path: Path) -> None:
        """The same undeclared, baselined check does NOT fail when its module is untouched on
        this branch -- grandfathered stock is exempt until it is actively edited."""
        _write_contract(tmp_path)
        rel_path = "scripts/checks/fake/validate_placement.py"
        module = _write_module(tmp_path, rel_path, _UNDECLARED_SOURCE, "fake_validate_placement_mod2")
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries:\n  - validate_placement\n", encoding="utf-8")
        checks = {"validate_placement": registry.Check(name="validate_placement")}

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.fake_check),
            patch("scripts.checks._marker_guard.default_base_reader", return_value="entries:\n  - validate_placement\n"),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert failed == []


class TestAbsentBaseSkipsLoudly:
    def test_prints_skip_and_does_not_fail_on_that_account(self, tmp_path: Path, capsys) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text("entries: []\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value={}),
            patch("scripts.checks._marker_guard.default_base_reader", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "SKIP" in capsys.readouterr().out
        assert failed == []


class TestContractDeriveAndAssert:
    def test_vocabulary_mismatch_fails(self, tmp_path: Path) -> None:
        _write_contract(
            tmp_path,
            _VALID_CONTRACT.replace("  - undeclared\n", "  - undeclared\n  - some_extra_status_not_in_registry\n"),
        )
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value={}),
            patch("scripts.checks._marker_guard.default_base_reader", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert "Check-accounting declaration ratchet" in failed

    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value={}),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        assert len(failed) == 1
        assert "check-accounting.yaml" in failed[0]


class TestModuleDeclaresDirect:
    """Direct unit coverage of _module_declares()'s two branches beyond the attribute-call shape
    already exercised end-to-end above."""

    def test_syntax_error_returns_false(self) -> None:
        assert _module_declares("def broken(:\n") is False

    def test_bare_name_call_shape_is_detected(self) -> None:
        """A `from scripts.checks.registry import examined` -> bare `examined(...)` call shape,
        distinct from the `registry.examined(...)` attribute-call shape."""
        assert _module_declares("from scripts.checks.registry import examined\n\ndef f(failed):\n    examined(1)\n") is True

    def test_no_call_at_all_returns_false(self) -> None:
        assert _module_declares("def f(failed):\n    pass\n") is False


class TestCheckModuleRelPathDirect:
    def test_unknown_check_returns_none(self) -> None:
        with patch.object(registry, "resolve", side_effect=registry.UnknownCheckError("nope")):
            assert _check_module_rel_path("not_a_real_check") is None

    def test_none_source_file_returns_none(self) -> None:
        def _fn(failed):
            pass

        with (
            patch.object(registry, "resolve", return_value=_fn),
            patch("scripts.checks.hygiene.validate_check_accounting.inspect.getsourcefile", return_value=None),
        ):
            assert _check_module_rel_path("some_check") is None

    def test_source_outside_root_returns_none(self, tmp_path: Path) -> None:
        def _fn(failed):
            pass

        with (
            patch.object(registry, "resolve", return_value=_fn),
            patch(
                "scripts.checks.hygiene.validate_check_accounting.inspect.getsourcefile",
                return_value="/completely/unrelated/path.py",
            ),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            assert _check_module_rel_path("some_check") is None
