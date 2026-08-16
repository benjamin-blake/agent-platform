"""Class D population ratchet: the two `contract-population.yaml` `ratchet:` pins
(grandfathered_max, status_active_max), their direction checks, and the pin-vs-census equality
binding (migration-step-3-grandfathering).

Split out of scripts/checks/contracts/_population.py (Decision 128 decompose-by-default): that
module was at 402/500 SLOC before this plan's ratchet additions, so the split is the default
response to the budget pressure, not a contingency.

Equality, not `>=`: acceptance criterion 4 requires `validate_contract_drift` to fail when any pin
does NOT EQUAL its live census bucket. A ceiling (`>=`) would let a landing enforcer leave stale
slack behind after lowering the debt count; equality forces every enforcer landing under rec-3059
to lower the matching debt pin in the same PR.

No import of scripts.checks.contracts._population here (that module re-imports THIS one) -- the
pin-vs-census binding below takes plain {pin_key: live_value} dicts, never the Census dataclass,
to keep this a one-directional dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml

from scripts.checks import _marker_guard

_RATCHET_REL_PATH = "docs/contracts/contract-population.yaml"
_RATCHET_TOKEN = "raise-approved"

GRANDFATHERED_MAX_KEY = "grandfathered_max"
STATUS_ACTIVE_MAX_KEY = "status_active_max"

PIN_KEYS: tuple[str, ...] = (GRANDFATHERED_MAX_KEY, STATUS_ACTIVE_MAX_KEY)


def _make_pin_spec(label: str) -> _marker_guard.RegistrySpec:
    return _marker_guard.RegistrySpec(
        rel_path=_RATCHET_REL_PATH,
        token=_RATCHET_TOKEN,
        gated_direction="up",
        extractor=_marker_guard.make_flat_extractor(_RATCHET_TOKEN, value_type=int),
        gates_new_entry=lambda _value: True,
        label=label,
    )


def ratchet_spec() -> _marker_guard.RegistrySpec:
    """The grandfathered_max pin's RegistrySpec -- name retained from the pre-split module for the
    single, most-established pin (T2.56)."""
    return _make_pin_spec("Contract-population ratchet guardrail (T2.56)")


def status_active_max_spec() -> _marker_guard.RegistrySpec:
    return _make_pin_spec("Contract-population status:active debt-pin guardrail (migration-step-3-grandfathering)")


_SPEC_BY_KEY: dict[str, Callable[[], _marker_guard.RegistrySpec]] = {
    GRANDFATHERED_MAX_KEY: ratchet_spec,
    STATUS_ACTIVE_MAX_KEY: status_active_max_spec,
}


def validate_ratchet_pins(contracts_dir: Path) -> tuple[dict[str, int], list[str]]:
    """Strict type/shape check of both ratchet pins from the PARSED (not regex) YAML, read
    from the injected `contracts_dir` -- never _common.ROOT. Each pin: int, not bool,
    non-negative. Returns (pins, errors): `pins` carries only the pins that parsed cleanly (never
    a sentinel 0 for a missing/malformed one); a missing file or non-mapping document returns
    ({}, []) or ({}, [error]) respectively -- mirrors the pre-split single-pin function's
    (None, []) "nothing to check" contract, but empty-dict-shaped since callers now iterate.
    """
    path = contracts_dir / "contract-population.yaml"
    if not path.exists():
        return {}, []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {}, [f"contract-population.yaml: could not parse for ratchet check: {exc}"]
    if not isinstance(data, dict):
        return {}, ["contract-population.yaml: not a YAML mapping"]
    ratchet = data.get("ratchet")
    if not isinstance(ratchet, dict):
        return {}, ["contract-population.yaml: ratchet block is missing"]

    pins: dict[str, int] = {}
    errors: list[str] = []
    for key in PIN_KEYS:
        if key not in ratchet:
            errors.append(f"contract-population.yaml: ratchet.{key} is missing")
            continue
        value = ratchet[key]
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"contract-population.yaml: ratchet.{key} must be a non-bool int, got {value!r}")
            continue
        if value < 0:
            errors.append(f"contract-population.yaml: ratchet.{key} must be non-negative, got {value!r}")
            continue
        pins[key] = value
    return pins, errors


def check_pin_direction(
    entry_key: str,
    contracts_dir: Path,
    current_value: int,
    *,
    base_reader: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Diff-guard over one pin's value (mirrors the pre-split single-pin
    `check_ratchet_direction`, generalized to either of the two PIN_KEYS), reusing
    scripts.checks._marker_guard's shared extractor/authorization primitives -- but reading
    CURRENT text from the injected `contracts_dir` (never _common.ROOT), which is what lets this
    obey a tmp_path fixture. A base file that does not exist (this plan's own landing PR) or that
    carries no entry for `entry_key` (a brand-new pin -- both new pins added by this plan) skips
    the direction comparison entirely -- a brand-new pin key is never gated on its own addition."""
    spec = _SPEC_BY_KEY[entry_key]()
    reader = base_reader or _marker_guard.default_base_reader
    base_text = reader(spec.rel_path)
    if base_text is None:
        return []

    base_entries = spec.extractor(base_text)
    base_entry = base_entries.get(entry_key)
    if base_entry is None:
        return []
    if current_value <= base_entry.value:
        return []

    current_path = contracts_dir / "contract-population.yaml"
    current_text = current_path.read_text(encoding="utf-8")
    current_entries = spec.extractor(current_text)
    entry = current_entries.get(entry_key)
    marker = entry.marker if entry is not None else None
    if marker is None:
        return [
            f"{entry_key}: unauthorized increase {base_entry.value} -> {current_value} "
            "with no `# raise-approved: dec-NNN` marker."
        ]

    bodies = _marker_guard.load_decision_bodies()
    if _marker_guard.authorization_failure(marker, entry_key, bodies):
        return [f"{entry_key}: {spec.token} marker cites {marker}, but its body does not authorize this entry."]
    return []


def check_ratchet_direction(
    contracts_dir: Path,
    current_value: int,
    *,
    base_reader: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Back-compat single-pin (grandfathered_max) wrapper around check_pin_direction."""
    return check_pin_direction(GRANDFATHERED_MAX_KEY, contracts_dir, current_value, base_reader=base_reader)


def validate_ratchet_pin(contracts_dir: Path) -> tuple[int | None, list[str]]:
    """Back-compat single-pin (grandfathered_max) wrapper around validate_ratchet_pins."""
    pins, errors = validate_ratchet_pins(contracts_dir)
    if errors:
        return None, errors
    if GRANDFATHERED_MAX_KEY not in pins:
        return None, []
    return pins[GRANDFATHERED_MAX_KEY], []


def check_pins_bound_to_census(pins: dict[str, int], census_values: dict[str, int]) -> list[str]:
    """FAILS on ANY inequality between a pin and its live census bucket -- equality, never `>=`
    (acceptance criterion 4): a ceiling lets a landing enforcer leave stale slack behind, whereas
    equality forces every enforcer landing under rec-3059 to lower the debt pin in the same PR.

    `pins`: {pin_key: declared value} (from validate_ratchet_pins -- only pins that parsed
    cleanly). `census_values`: {pin_key: live census count} for the SAME two keys, supplied by
    the caller (never imported here, to keep this module's dependency on _population
    one-directional). A pin key absent from `pins` (already reported by validate_ratchet_pins) or
    from `census_values` contributes no additional error here.
    """
    errors: list[str] = []
    for key, pin_value in pins.items():
        if key not in census_values:
            continue
        live_value = census_values[key]
        if pin_value != live_value:
            errors.append(
                f"ratchet.{key}={pin_value} does not equal the live census bucket ({live_value}) -- "
                "pins must equal the census exactly (equality, not a ceiling)."
            )
    return errors
