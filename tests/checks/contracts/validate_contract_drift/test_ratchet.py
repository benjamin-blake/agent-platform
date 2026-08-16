"""VP step 8: the ratchet -- typing, direction, the ratified marker path, and the base-absent
bootstrap. Fixtures carry both pins (migration-step-3-grandfathering, narrowed to two by rec-3059
wave 2: grandfathered_max, status_active_max) since scripts/checks/contracts/_ratchet.py's
validate_ratchet_pins reports a missing-pin error for any pin absent from the ratchet: block."""

from __future__ import annotations

from scripts.checks.contracts import _population, _ratchet

from .conftest import validate_contract_drift


def _population_yaml(
    pin: int,
    *,
    marker: str = "",
    status_active_max: int = 0,
) -> str:
    return (
        "contract:\n"
        "  id: contract-population\n"
        "  class: D\n"
        "  contract_version: 1\n"
        "  status: ratified\n"
        "  ratified_via: test-decision\n"
        "  subject: contract-population\n"
        "  evaluator:\n"
        "    check: validate_contract_drift\n"
        "amendment_log: []\n"
        "ratchet:\n"
        f"  grandfathered_max: {pin}{marker}\n"
        f"  status_active_max: {status_active_max}\n"
    )


class TestRatchet:
    def test_unmarked_increase_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(25))
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/contract-population.yaml"],
                show_map={"docs/contracts/contract-population.yaml": _population_yaml(21)},
            )
        )
        pin_value, pin_errors = _population.validate_ratchet_pin(tmp_path)
        assert pin_value == 25 and pin_errors == []
        violations = _ratchet.check_pin_direction(
            "grandfathered_max",
            tmp_path,
            pin_value,
            base_reader=lambda rel: _population_yaml(21) if rel.endswith("contract-population.yaml") else None,
        )
        assert violations and "unauthorized" in violations[0]

    def test_marked_increase_with_authorizing_decision_passes(
        self, tmp_path, install_fake_git, write_contract, FakeGit, monkeypatch
    ) -> None:
        write_contract(
            tmp_path, "contract-population.yaml", _population_yaml(25, marker="  # raise-approved: dec-500 population grew")
        )
        bodies = {500: "This entry authorizes docs/contracts/contract-population.yaml's grandfathered_max entry."}
        monkeypatch.setattr(_ratchet._marker_guard, "load_decision_bodies", lambda: bodies)
        violations = _ratchet.check_pin_direction(
            "grandfathered_max", tmp_path, 25, base_reader=lambda rel: _population_yaml(21)
        )
        assert violations == []

    def test_marked_increase_citing_unrelated_decision_fails(self, tmp_path, monkeypatch) -> None:
        write_contract = lambda d, n, t: (d / n).write_text(t, encoding="utf-8")  # noqa: E731
        write_contract(
            tmp_path, "contract-population.yaml", _population_yaml(25, marker="  # raise-approved: dec-999 unrelated")
        )
        bodies = {999: "This decision is about something else entirely."}
        monkeypatch.setattr(_ratchet._marker_guard, "load_decision_bodies", lambda: bodies)
        violations = _ratchet.check_pin_direction(
            "grandfathered_max", tmp_path, 25, base_reader=lambda rel: _population_yaml(21)
        )
        assert violations and "does not authorize" in violations[0]

    def test_decrease_passes(self, tmp_path) -> None:
        violations = _ratchet.check_pin_direction(
            "grandfathered_max", tmp_path, 10, base_reader=lambda rel: _population_yaml(21)
        )
        assert violations == []

    def test_missing_key_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("contract:\n  id: x\n  class: D\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and "missing" in errors[0]

    def test_string_value_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: 'twenty'\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and any("non-bool int" in e for e in errors)

    def test_bool_value_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: true\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and any("non-bool int" in e for e in errors)

    def test_negative_value_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: -1\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and any("non-negative" in e for e in errors)

    def test_base_file_absent_skips_direction_comparison(self, tmp_path) -> None:
        violations = _ratchet.check_pin_direction("grandfathered_max", tmp_path, 999999, base_reader=lambda rel: None)
        assert violations == []

    def test_pin_is_read_from_injected_contracts_dir(self, tmp_path) -> None:
        real_default = tmp_path / "not_the_real_root"
        real_default.mkdir()
        write_contract = lambda d, n, t: (d / n).write_text(t, encoding="utf-8")  # noqa: E731
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(21))
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value == 21 and errors == []
        # A DIFFERENT directory with no such file must not be silently substituted.
        value2, errors2 = _population.validate_ratchet_pin(real_default)
        assert value2 is None and errors2 == []

    def test_full_gate_end_to_end_unauthorized_increase(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(25))
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/contract-population.yaml"],
                show_map={"docs/contracts/contract-population.yaml": _population_yaml(21)},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("ratchet" in f and "unauthorized" in f for f in failed), failed

    def test_pins_must_equal_live_census(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        """Acceptance criterion 4: the pin-vs-census equality binding runs UNCONDITIONALLY (even
        with the baseline unreachable, install_fake_git's default merge_base_rc=1) -- a pin ABOVE
        its census bucket (stale slack) fails, and equal-value pins pass."""
        # contract-population.yaml itself is Class D + status=ratified + a resolving evaluator,
        # so scanning ONLY this one file yields census.grandfathered == 0 -- a pinned
        # grandfathered_max of 5 must therefore FAIL (5 != 0).
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(5))
        install_fake_git(FakeGit())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("ratchet" in f and "grandfathered_max=5" in f and "does not equal" in f for f in failed), failed

    def test_pins_equal_to_live_census_pass(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(0))
        install_fake_git(FakeGit())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert not any("ratchet" in f for f in failed), failed

    def test_pin_vs_census_cascade_suppressed_when_a_contract_is_skipped(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        """rec-3101: a contract that fails schema/evaluator resolution increments census.skipped
        and its own bucket never increments -- the pin-vs-census equality binding must NOT also
        fire a second, misleading "lower the pin" error on top of the skip failure. The surviving
        message says to fix the skipped contract, never to lower the pin."""
        # grandfathered_max=5 deliberately mismatches the live census (0, per
        # test_pins_must_equal_live_census above) -- WITHOUT the rec-3101 suppression this would
        # ALSO fire a ratchet cascade error alongside the skip.
        write_contract(tmp_path, "contract-population.yaml", _population_yaml(5))
        write_contract(tmp_path, "broken.yaml", class_d_yaml(contract_id="broken", subject="broken", evaluator=None))
        install_fake_git(FakeGit())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("broken.yaml" in f and "schema" in f for f in failed), failed
        assert not any("ratchet" in f and "does not equal" in f for f in failed), failed
