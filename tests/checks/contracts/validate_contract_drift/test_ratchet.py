"""VP step 8: the ratchet -- typing, direction, the ratified marker path, and the base-absent
bootstrap."""

from __future__ import annotations

from scripts.checks.contracts import _population

from .conftest import validate_contract_drift


def _population_yaml(pin: int, *, marker: str = "") -> str:
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
        violations = _population.check_ratchet_direction(
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
        monkeypatch.setattr(_population._marker_guard, "load_decision_bodies", lambda: bodies)
        violations = _population.check_ratchet_direction(tmp_path, 25, base_reader=lambda rel: _population_yaml(21))
        assert violations == []

    def test_marked_increase_citing_unrelated_decision_fails(self, tmp_path, monkeypatch) -> None:
        write_contract = lambda d, n, t: (d / n).write_text(t, encoding="utf-8")  # noqa: E731
        write_contract(
            tmp_path, "contract-population.yaml", _population_yaml(25, marker="  # raise-approved: dec-999 unrelated")
        )
        bodies = {999: "This decision is about something else entirely."}
        monkeypatch.setattr(_population._marker_guard, "load_decision_bodies", lambda: bodies)
        violations = _population.check_ratchet_direction(tmp_path, 25, base_reader=lambda rel: _population_yaml(21))
        assert violations and "does not authorize" in violations[0]

    def test_decrease_passes(self, tmp_path) -> None:
        violations = _population.check_ratchet_direction(tmp_path, 10, base_reader=lambda rel: _population_yaml(21))
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
        assert errors and "non-bool int" in errors[0]

    def test_bool_value_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: true\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and "non-bool int" in errors[0]

    def test_negative_value_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: -1\n", encoding="utf-8")
        value, errors = _population.validate_ratchet_pin(tmp_path)
        assert value is None
        assert errors and "non-negative" in errors[0]

    def test_base_file_absent_skips_direction_comparison(self, tmp_path) -> None:
        violations = _population.check_ratchet_direction(tmp_path, 999999, base_reader=lambda rel: None)
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
