"""Composite-action-shape roster parity check (rec-3059 second-wave enforcer build).

Asserts docs/contracts/composite-action-shape.yaml's declared registries genuinely equal the live
guard/config surfaces they claim to describe -- promoting the contract from a routed
evaluator.none_grandfathered debt record to a machine-enforced check:

  1. known_r1_violators (keys AND pinned_lines) equals BOTH
     scripts/checks/ci_guards/validate_composite_action_shell_bodies.py's frozen
     _R1_KNOWN_VIOLATORS constant (keys) and config/composite_action_body_baseline.yaml's `r1:`
     section (keys + pinned-line ceilings).
  2. baseline_file.path equals the guard's own _BASELINE_REL_PATH constant.
  3. baseline_file.section_allowlist.sections equals
     scripts/checks/ci_guards/_workflow_shell_bodies.py's frozen _KNOWN_BASELINE_SECTIONS
     constant.
  4. known_r1_conformant[].delegate and closing_instance.script resolve to real files on disk.

DELIBERATE DEVIATION from the contract's own recorded (now-retired) enforcement route, which
proposed having the guard read known_r1_violators FROM the contract instead of its hardcoded
_R1_KNOWN_VIOLATORS copy. Decision 162's R1 MEMBERSHIP clause makes that deviation mandatory: "a
config-file edit alone can never admit a third violator; growing the set requires editing the
guard's own source in a reviewed change." This check instead builds a three-way parity assertion
over the pre-existing unverified copy -- see composite-action-shape.yaml's amendment_log for the
recorded deviation and its accepted cost.

Decomposed into one helper per assertion group (Decision 43 cyclomatic-complexity limit) -- each
helper returns (failures, examined_count) for its own block, and the registered check aggregates.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_NAME = "composite-action-shape.yaml"
_BASELINE_CONFIG_REL_PATH = "config/composite_action_body_baseline.yaml"


def _dig(data: object, *keys: str) -> object:
    """Walk nested mappings by `keys`; returns None the moment any level is not a mapping."""
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _check_known_r1_violators(
    data: dict, baseline_config_path: Path | None, r1_known_violators: frozenset[str]
) -> tuple[list[str], int]:
    """known_r1_violators (keys + pinned_lines) vs _R1_KNOWN_VIOLATORS + baseline r1: section."""
    failed: list[str] = []
    violators = data.get("known_r1_violators")
    if not isinstance(violators, list) or not violators:
        failed.append(f"Composite-action-shape roster parity: {_CONTRACT_NAME} missing or empty 'known_r1_violators'")
        return failed, 0

    declared_pinned: dict[str, int] = {}
    for entry in violators:
        if not isinstance(entry, dict) or "key" not in entry or "pinned_lines" not in entry:
            failed.append(
                f"Composite-action-shape roster parity: {_CONTRACT_NAME} known_r1_violators entry "
                f"malformed (missing key/pinned_lines): {entry!r}"
            )
            continue
        declared_pinned[str(entry["key"])] = entry["pinned_lines"]
    if len(declared_pinned) != len(violators):
        return failed, 0  # a malformed entry already reported above; skip the parity legs

    declared_keys = set(declared_pinned)
    if declared_keys != set(r1_known_violators):
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} known_r1_violators keys "
            f"{sorted(declared_keys)} do not equal validate_composite_action_shell_bodies."
            f"_R1_KNOWN_VIOLATORS {sorted(r1_known_violators)}"
        )
    baseline_r1 = _read_baseline_section(baseline_config_path, "r1")
    if baseline_r1 is None:
        failed.append(f"Composite-action-shape roster parity: {_BASELINE_CONFIG_REL_PATH} missing or empty 'r1' section")
    elif declared_pinned != baseline_r1:
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} known_r1_violators "
            f"{declared_pinned} does not equal {_BASELINE_CONFIG_REL_PATH}'s r1 section {baseline_r1}"
        )
    return failed, len(declared_pinned)


def _check_baseline_file(data: dict, baseline_rel_path: str, known_baseline_sections: frozenset[str]) -> tuple[list[str], int]:
    """baseline_file.path + baseline_file.section_allowlist.sections."""
    failed: list[str] = []
    baseline_file = data.get("baseline_file")
    if not isinstance(baseline_file, dict) or not baseline_file:
        failed.append(f"Composite-action-shape roster parity: {_CONTRACT_NAME} missing or empty 'baseline_file'")
        return failed, 0

    declared_path = baseline_file.get("path")
    if declared_path != baseline_rel_path:
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} baseline_file.path {declared_path!r} "
            f"does not equal the guard's _BASELINE_REL_PATH {baseline_rel_path!r}"
        )
    sections = _dig(baseline_file, "section_allowlist", "sections")
    if not isinstance(sections, list) or not sections:
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} missing or empty "
            "'baseline_file.section_allowlist.sections'"
        )
    elif set(sections) != set(known_baseline_sections):
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} "
            f"baseline_file.section_allowlist.sections {sorted(sections)} does not equal "
            f"_workflow_shell_bodies._KNOWN_BASELINE_SECTIONS {sorted(known_baseline_sections)}"
        )
    return failed, 1


def _check_known_r1_conformant(data: dict) -> tuple[list[str], int]:
    """known_r1_conformant[].delegate resolves on disk (relative to its action directory)."""
    failed: list[str] = []
    conformant = data.get("known_r1_conformant")
    if not isinstance(conformant, list) or not conformant:
        failed.append(f"Composite-action-shape roster parity: {_CONTRACT_NAME} missing or empty 'known_r1_conformant'")
        return failed, 0

    for entry in conformant:
        if not isinstance(entry, dict) or "key" not in entry or "delegate" not in entry:
            failed.append(
                f"Composite-action-shape roster parity: {_CONTRACT_NAME} known_r1_conformant entry "
                f"malformed (missing key/delegate): {entry!r}"
            )
            continue
        action_rel_dir = str(entry["key"]).split("::", 1)[0]
        delegate_path = _common.ROOT / action_rel_dir / str(entry["delegate"])
        if not delegate_path.is_file():
            failed.append(
                f"Composite-action-shape roster parity: {_CONTRACT_NAME} known_r1_conformant "
                f"{entry['key']!r} delegate {entry['delegate']!r} does not resolve at {delegate_path}"
            )
    return failed, len(conformant)


def _check_closing_instance(data: dict) -> tuple[list[str], int]:
    """closing_instance.script resolves on disk."""
    failed: list[str] = []
    closing_instance = data.get("closing_instance")
    if not isinstance(closing_instance, dict) or not closing_instance.get("script"):
        failed.append(f"Composite-action-shape roster parity: {_CONTRACT_NAME} missing or empty 'closing_instance.script'")
        return failed, 0

    script_path = _common.ROOT / str(closing_instance["script"])
    if not script_path.is_file():
        failed.append(
            f"Composite-action-shape roster parity: {_CONTRACT_NAME} closing_instance.script "
            f"{closing_instance['script']!r} does not resolve at {script_path}"
        )
    return failed, 1


@registry.register("validate_composite_action_shape_rosters", owner="platform")
def validate_composite_action_shape_rosters(
    failed: list[str],
    *,
    contracts_dir: Path | None = None,
    baseline_config_path: Path | None = None,
) -> None:
    """Fail if composite-action-shape.yaml's declared rosters diverge from the live guard/config
    surfaces, or if a declared delegate/script does not resolve on disk.

    `baseline_config_path` overrides config/composite_action_body_baseline.yaml's location for
    test isolation -- it is a SEPARATE file from `contracts_dir`, injected independently so a
    red-path test can perturb either surface without touching the real repo tree.
    """
    # Lazy in-function import so registry.all_checks() stays cheap (module import graph stays
    # small) -- these two modules are only needed when this check actually runs.
    from scripts.checks.ci_guards._workflow_shell_bodies import _KNOWN_BASELINE_SECTIONS  # noqa: PLC0415
    from scripts.checks.ci_guards.validate_composite_action_shell_bodies import (  # noqa: PLC0415
        _BASELINE_REL_PATH,
        _R1_KNOWN_VIOLATORS,
    )

    print("\n=== Composite-action-shape roster parity ===")
    target_dir = contracts_dir if contracts_dir is not None else _common.ROOT / "docs" / "contracts"
    path = target_dir / _CONTRACT_NAME

    if not path.is_file():
        failed.append(f"Composite-action-shape roster parity: {path} not found")
        registry.skipped(f"{_CONTRACT_NAME} not found")
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Composite-action-shape roster parity: could not read/parse {path}: {exc}")
        registry.skipped(f"{_CONTRACT_NAME} not parseable")
        return
    if not isinstance(data, dict):
        failed.append(f"Composite-action-shape roster parity: {path} is not a YAML mapping")
        registry.skipped(f"{_CONTRACT_NAME} not a mapping")
        return

    error_count_before = len(failed)
    examined_count = 0

    violators_failed, violators_examined = _check_known_r1_violators(data, baseline_config_path, _R1_KNOWN_VIOLATORS)
    baseline_failed, baseline_examined = _check_baseline_file(data, _BASELINE_REL_PATH, _KNOWN_BASELINE_SECTIONS)
    conformant_failed, conformant_examined = _check_known_r1_conformant(data)
    closing_failed, closing_examined = _check_closing_instance(data)

    failed.extend(violators_failed)
    failed.extend(baseline_failed)
    failed.extend(conformant_failed)
    failed.extend(closing_failed)
    examined_count = violators_examined + baseline_examined + conformant_examined + closing_examined

    registry.examined(examined_count, unit="roster_entries")

    if len(failed) == error_count_before:
        print(f"  PASS: {_CONTRACT_NAME} rosters match the live guard/config surfaces ({examined_count} entries).")


def _read_baseline_section(baseline_config_path: Path | None, section: str) -> dict[str, int] | None:
    """Read `section` from config/composite_action_body_baseline.yaml (or the injected override).
    Returns None if the file, the section, or the section's shape is missing/malformed."""
    baseline_path = baseline_config_path if baseline_config_path is not None else _common.ROOT / _BASELINE_CONFIG_REL_PATH
    try:
        data = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    section_data = data.get(section)
    if not isinstance(section_data, dict) or not section_data:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in section_data.values()):
        return None
    return {str(k): v for k, v in section_data.items()}
