"""Read-only plan scope registration-closure engine plus its advisory CLI (plan-obligation-closure).

Derives which of docs/contracts/plan-obligations.yaml's `registration_surfaces` obligations a
plan's `scope` rows have or have not satisfied. Holds no second copy of the obligation map --
every rule (trigger pattern, required companion paths) is read from the contract at check time,
never hardcoded here.

Reads plans as PLAIN YAML (schema_version/plan_type/scope only), not through the strict
scripts.roadmap.plan_document.PlanDocument loader: registration closure is structurally derivable
from those three fields alone, and validate_plan_documents already separately owns full-schema
validity. This also lets the engine evaluate a minimal in-memory fixture dict (the graduated VP
steps in this plan build fixtures from inline dicts, not full PlanDocument-valid ones) without
tripping on unrelated required fields.

Exception-contained throughout: scripts/checks/validation_result.py calls a check's function with
no try/except, so an unhandled raise here would abort the whole --pre/full tier and skip
write_completed_visible, destroying CI-RCA's attribution substrate. A missing/malformed contract
or an unreadable/malformed plan yields a reported finding string, never an exception.

The sole registered check (scripts/checks/roadmap/validate_plan_scope_closure.py) is a thin
delegate over this module's `evaluate_plan`/`net_new_v4_implementation_plan_paths`. This module
also exposes an advisory CLI: `bin/venv-python -m scripts.roadmap.plan_obligations --plan <path>`
always exits 0, including when the plan has unmet obligations -- the registered check is the
gate, this CLI is a report.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common

ROOT = _common.ROOT
_CONTRACT_PATH = ROOT / "docs" / "contracts" / "plan-obligations.yaml"

# The schema_version floor a plan must meet before this check evaluates it at all -- mirrors
# validate_plan_documents' own _MIN_NEW_PLAN_SCHEMA_VERSION grandfathering precedent. 65 of 329
# existing plans create a check while omitting an obligated row (7 of them at v4); without this
# floor plus the net-new-in-diff gate below, every one of them would red on first touch.
MIN_SCHEMA_VERSION = 4
_IMPLEMENTATION = "IMPLEMENTATION"


def load_obligation_map(contract_path: Path | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Read the contract's `registration_surfaces` mapping. Returns (rules, error) -- never
    raises; a missing file, unparseable YAML, or malformed shape yields ([], "<reason>")."""
    path = contract_path if contract_path is not None else _CONTRACT_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"could not read {path}: {exc}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [], f"could not parse {path}: {exc}"
    if not isinstance(data, dict):
        return [], f"{path} is not a YAML mapping"
    surfaces = data.get("registration_surfaces")
    if not isinstance(surfaces, dict) or not surfaces:
        return [], f"{path} is missing a non-empty 'registration_surfaces' mapping"
    return [rule for rule in surfaces.values() if isinstance(rule, dict)], None


def _read_plan_dict(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Plain YAML read of a plan file -- never raises. Returns (data, error)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not read {path}: {exc}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"could not parse {path}: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} is not a YAML mapping"
    return data, None


def _scope_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    scope = data.get("scope")
    if not isinstance(scope, list):
        return []
    rows: list[dict[str, str]] = []
    for row in scope:
        if isinstance(row, dict) and isinstance(row.get("file"), str) and isinstance(row.get("action"), str):
            rows.append(row)
    return rows


def _is_grandfathered(data: dict[str, Any]) -> bool:
    schema_version = data.get("schema_version")
    meets_floor = isinstance(schema_version, int) and schema_version >= MIN_SCHEMA_VERSION
    return not (meets_floor and data.get("plan_type") == _IMPLEMENTATION)


def _derive_findings(scope: list[dict[str, str]], rules: list[dict[str, Any]]) -> list[str]:
    """Pure derivation: which rule-declared companion paths are absent from `scope`.

    Each rule names a `trigger.file_pattern` (matched against a scope row's `file`, optionally
    gated by `trigger.action`) and a `requires` list of `path_template` strings formatted with
    the trigger's regex capture groups. A required path missing from the scope's file set is one
    finding, naming the missing path and the triggering row.
    """
    scope_files = {row["file"] for row in scope}
    findings: list[str] = []
    for rule in rules:
        trigger = rule.get("trigger")
        if not isinstance(trigger, dict):
            continue
        pattern = trigger.get("file_pattern")
        required_action = trigger.get("action")
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            compiled = re.compile(pattern)
        except re.error:
            continue
        requirements = rule.get("requires")
        if not isinstance(requirements, list):
            continue
        for row in scope:
            if required_action and row.get("action") != required_action:
                continue
            match = compiled.match(row["file"])
            if not match:
                continue
            groups = match.groupdict()
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                template = requirement.get("path_template")
                if not isinstance(template, str) or not template:
                    continue
                try:
                    required_path = template.format(**groups)
                except (KeyError, IndexError):
                    continue
                if required_path not in scope_files:
                    label = requirement.get("label", required_path)
                    findings.append(
                        f"missing {label} ({required_path}) -- required because {row['file']} is a new check module"
                    )
    return findings


def evaluate_plan(path: Path, rules: list[dict[str, Any]] | None = None) -> list[str]:
    """Evaluate one plan file's scope against the obligation map. Never raises.

    Grandfathers (returns []) any plan below MIN_SCHEMA_VERSION or not plan_type IMPLEMENTATION.
    An unreadable/unparseable plan becomes a single finding string rather than propagating.
    """
    data, error = _read_plan_dict(path)
    if error or data is None:
        return [f"{path.name}: {error}"]
    if _is_grandfathered(data):
        return []
    if rules is None:
        rules, rule_error = load_obligation_map()
        if rule_error:
            return [f"{path.name}: {rule_error}"]
    return [f"{path.name}: {finding}" for finding in _derive_findings(_scope_rows(data), rules)]


def net_new_v4_implementation_plan_paths() -> list[Path]:
    """Net-new (git status A) docs/plans/PLAN-*.yaml paths, schema_version >= MIN_SCHEMA_VERSION
    and plan_type IMPLEMENTATION -- derived from the status-aware git diff, NEVER a docs/plans/
    glob (validate_plan_documents globs the whole 329-plan corpus at ~6.24s per call; this
    function must stay one hop, not a directory walk).
    """
    paths: list[Path] = []
    for status, rel_path in _common.get_status_aware_diff():
        if status != "A" or not _common.PLAN_PATH_RE.match(rel_path):
            continue
        candidate = ROOT / rel_path
        data, error = _read_plan_dict(candidate)
        if error or data is None or _is_grandfathered(data):
            continue
        paths.append(candidate)
    return paths


def build_report(path: Path) -> str:
    """Advisory, human-readable report for one plan path. Never raises."""
    findings = evaluate_plan(path)
    if not findings:
        return (
            f"{path}: no unmet registration obligations "
            f"(or plan is grandfathered / below schema_version {MIN_SCHEMA_VERSION})."
        )
    lines = [f"{path}: {len(findings)} unmet registration obligation(s):"]
    lines.extend(f"  - {finding}" for finding in findings)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Advisory CLI. ALWAYS exits 0, including on unmet obligations -- the registered check
    (validate_plan_scope_closure) is the gate this report only informs."""
    parser = argparse.ArgumentParser(description="Plan registration-obligation report (advisory; always exits 0)")
    parser.add_argument("--plan", required=True, help="Path to a docs/plans/PLAN-{slug}.yaml file")
    args = parser.parse_args(argv)
    print(build_report(Path(args.plan)))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
