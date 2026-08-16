"""Direct module-boundary coverage for scripts/checks/contracts/_ratchet.py: the two ratchet
pins (grandfathered_max, status_active_max), their direction checks, and the pin-vs-census
equality binding.

Migrated from tests/checks/contracts/test__population.py's TestRatchetSpecAndCensus alongside the
_ratchet.py source move (Decision 128 decompose-by-default / Decision 131 mirror convention,
migration-step-3-grandfathering)."""

from __future__ import annotations

from scripts.checks.contracts import _ratchet


class TestRatchetSpecShapes:
    def test_grandfathered_max_spec_shape(self) -> None:
        spec = _ratchet.ratchet_spec()
        assert spec.rel_path == "docs/contracts/contract-population.yaml"
        assert spec.token == "raise-approved"
        assert spec.gated_direction == "up"
        assert spec.gates_new_entry(0) is True

    def test_status_active_max_spec_shape(self) -> None:
        spec = _ratchet.status_active_max_spec()
        assert spec.rel_path == "docs/contracts/contract-population.yaml"
        assert spec.token == "raise-approved"
        assert spec.gated_direction == "up"


class TestValidateRatchetPins:
    def test_missing_file(self, tmp_path) -> None:
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {} and errors == []

    def test_unparseable(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("{bad: [unclosed", encoding="utf-8")
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {} and errors

    def test_non_mapping(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("- a\n- b\n", encoding="utf-8")
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {} and errors

    def test_missing_ratchet_block(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("other_key: 1\n", encoding="utf-8")
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {} and "ratchet block is missing" in errors[0]

    def test_missing_individual_pin_reports_error_but_others_parse(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: 19\n", encoding="utf-8")
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {"grandfathered_max": 19}
        assert any("status_active_max" in e and "missing" in e for e in errors)

    def test_string_value_reported_and_omitted(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: 'x'\n  status_active_max: 16\n",
            encoding="utf-8",
        )
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert "grandfathered_max" not in pins
        assert pins == {"status_active_max": 16}
        assert any("non-bool int" in e for e in errors)

    def test_bool_value_reported_and_omitted(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: false\n  status_active_max: 16\n",
            encoding="utf-8",
        )
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert "grandfathered_max" not in pins
        assert any("non-bool int" in e for e in errors)

    def test_negative_value_reported_and_omitted(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: -5\n  status_active_max: 16\n",
            encoding="utf-8",
        )
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert "grandfathered_max" not in pins
        assert any("non-negative" in e for e in errors)

    def test_both_pins_valid(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: 19\n  status_active_max: 16\n",
            encoding="utf-8",
        )
        pins, errors = _ratchet.validate_ratchet_pins(tmp_path)
        assert pins == {"grandfathered_max": 19, "status_active_max": 16}
        assert errors == []


class TestValidateRatchetPinBackCompat:
    """The single-pin (grandfathered_max) back-compat wrapper."""

    def test_missing_file(self, tmp_path) -> None:
        value, errors = _ratchet.validate_ratchet_pin(tmp_path)
        assert value is None and errors == []

    def test_valid(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: 19\n  status_active_max: 16\n",
            encoding="utf-8",
        )
        value, errors = _ratchet.validate_ratchet_pin(tmp_path)
        assert value == 19 and errors == []

    def test_missing_key_only(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  other: 1\n", encoding="utf-8")
        value, errors = _ratchet.validate_ratchet_pin(tmp_path)
        assert value is None and errors


class TestCheckPinDirection:
    def test_base_present_but_no_entry_for_key_skips(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: 25\n", encoding="utf-8")
        violations = _ratchet.check_pin_direction(
            "grandfathered_max", tmp_path, 25, base_reader=lambda rel: "ratchet:\n  some_other_key: 1\n"
        )
        assert violations == []

    def test_base_absent_skips(self, tmp_path) -> None:
        assert _ratchet.check_pin_direction("grandfathered_max", tmp_path, 999, base_reader=lambda rel: None) == []

    def test_decrease_and_equal_pass(self, tmp_path) -> None:
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        assert _ratchet.check_pin_direction("grandfathered_max", tmp_path, 10, base_reader=lambda rel: base_text) == []
        assert _ratchet.check_pin_direction("grandfathered_max", tmp_path, 21, base_reader=lambda rel: base_text) == []

    def test_unmarked_increase_fails(self, tmp_path) -> None:
        (tmp_path / "contract-population.yaml").write_text("ratchet:\n  grandfathered_max: 25\n", encoding="utf-8")
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        violations = _ratchet.check_pin_direction("grandfathered_max", tmp_path, 25, base_reader=lambda rel: base_text)
        assert violations and "unauthorized" in violations[0]

    def test_marked_increase_authorized_passes(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: 25  # raise-approved: dec-500 grew\n", encoding="utf-8"
        )
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        monkeypatch.setattr(
            _ratchet._marker_guard,
            "load_decision_bodies",
            lambda: {500: "authorizes grandfathered_max"},
        )
        violations = _ratchet.check_pin_direction("grandfathered_max", tmp_path, 25, base_reader=lambda rel: base_text)
        assert violations == []

    def test_marked_increase_unauthorized_fails(self, tmp_path, monkeypatch) -> None:
        (tmp_path / "contract-population.yaml").write_text(
            "ratchet:\n  grandfathered_max: 25  # raise-approved: dec-999 unrelated\n", encoding="utf-8"
        )
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        monkeypatch.setattr(_ratchet._marker_guard, "load_decision_bodies", lambda: {999: "unrelated text"})
        violations = _ratchet.check_pin_direction("grandfathered_max", tmp_path, 25, base_reader=lambda rel: base_text)
        assert violations and "does not authorize" in violations[0]

    def test_new_pin_key_with_no_base_entry_skips_even_though_base_file_exists(self, tmp_path) -> None:
        """A brand-new pin (status_active_max, on migration-step-3-grandfathering's own landing)
        is never gated on its own addition -- the base file exists but carries no entry for the
        new key, so the direction comparison skips entirely (no marker required)."""
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        violations = _ratchet.check_pin_direction("status_active_max", tmp_path, 16, base_reader=lambda rel: base_text)
        assert violations == []

    def test_check_ratchet_direction_back_compat_wrapper(self, tmp_path) -> None:
        base_text = "ratchet:\n  grandfathered_max: 21\n"
        assert _ratchet.check_ratchet_direction(tmp_path, 19, base_reader=lambda rel: base_text) == []


class TestPinBinding:
    """The pin-vs-census equality binding (acceptance criterion 4): FAILS on ANY inequality
    between a pin and its live census bucket, in EITHER direction."""

    def test_all_pins_equal_census_pass(self) -> None:
        pins = {"grandfathered_max": 19, "status_active_max": 16}
        census_values = {"grandfathered_max": 19, "status_active_max": 16}
        assert _ratchet.check_pins_bound_to_census(pins, census_values) == []

    def test_census_over_pin_fails(self) -> None:
        # Pin sits BELOW its census bucket (an under-census pin) -- FAILS, not just an over-pin.
        pins = {"grandfathered_max": 19}
        census_values = {"grandfathered_max": 20}
        errors = _ratchet.check_pins_bound_to_census(pins, census_values)
        assert len(errors) == 1
        assert "grandfathered_max=19" in errors[0]
        assert "does not equal" in errors[0]

    def test_pin_over_census_fails(self) -> None:
        # Pin sits ABOVE its census bucket -- stale slack left behind by a landed enforcer --
        # FAILS too (equality, not a `>=` ceiling).
        pins = {"status_active_max": 16}
        census_values = {"status_active_max": 15}
        errors = _ratchet.check_pins_bound_to_census(pins, census_values)
        assert len(errors) == 1
        assert "status_active_max=16" in errors[0]

    def test_pin_absent_from_census_values_is_silently_skipped(self) -> None:
        pins = {"unrecognized_key": 5}
        assert _ratchet.check_pins_bound_to_census(pins, {}) == []

    def test_multiple_mismatches_all_reported(self) -> None:
        pins = {"grandfathered_max": 19, "status_active_max": 16}
        census_values = {"grandfathered_max": 18, "status_active_max": 15}
        errors = _ratchet.check_pins_bound_to_census(pins, census_values)
        assert len(errors) == 2
