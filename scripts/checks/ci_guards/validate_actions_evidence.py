"""Risk-based GitHub Actions diagnostics and retention contract validation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from scripts.checks import _common, registry

CONTRACT_PATH = Path("docs/contracts/github-actions-evidence.yaml")
_REQUIRED_CLASSES = {"ephemeral_handoff", "ordinary_ci", "governed_deployment", "security_evidence"}
_SAFE_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]{5,80}$")
_SECRET_SHAPES = re.compile(r"(?i)(?:aws|secret|token|password|credential)[_-]?[a-z0-9]{8,}|\d{12}|https?://[^/\s]+@")


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a mapping")
    return value


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ValueError("selected job steps must be a list of mappings")
    return steps


def _matching_steps(steps: list[dict[str, Any]], selector: Any) -> list[dict[str, Any]]:
    if not isinstance(selector, dict) or set(selector) not in ({"id"}, {"name"}):
        raise ValueError("critical step selector must contain exactly one of id or name")
    key, value = next(iter(selector.items()))
    if not isinstance(value, str) or not value:
        raise ValueError("critical step selector must be a nonempty string")
    return [step for step in steps if step.get(key) == value]


def _validate_classes(contract: dict[str, Any]) -> None:
    required = set(contract.get("required_retention_classes", []))
    classes = contract.get("retention_classes")
    if required != _REQUIRED_CLASSES or not isinstance(classes, dict) or set(classes) != _REQUIRED_CLASSES:
        raise ValueError("retention contract must define exactly the four required purpose classes")
    for class_id, policy in classes.items():
        if not isinstance(policy, dict):
            raise ValueError(f"retention class {class_id}: expected a mapping")
        values = tuple(policy.get(key) for key in ("minimum_days", "maximum_days", "delayed_rca_days"))
        if any(type(value) is not int for value in values):
            raise ValueError(f"retention class {class_id}: invalid day bounds")
        minimum, maximum, delayed = cast(tuple[int, int, int], values)
        if not (1 <= minimum <= delayed <= maximum):
            raise ValueError(f"retention class {class_id}: invalid day bounds")
        if policy.get("expiry_state") != "unavailable_expired" or not policy.get("recovery"):
            raise ValueError(f"retention class {class_id}: missing fail-closed expiry or recovery semantics")


def evidence_availability(class_policy: dict[str, Any], created_at: datetime, observed_at: datetime) -> dict[str, str]:
    """Return the contract state for delayed RCA without implying post-expiry availability."""
    if created_at.tzinfo is None or observed_at.tzinfo is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    age_days = (observed_at.astimezone(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds() / 86400
    if age_days <= class_policy["delayed_rca_days"]:
        return {"state": "available", "recovery": "not_required"}
    return {"state": class_policy["expiry_state"], "recovery": class_policy["recovery"]}


def _validate_s1(root: Path, contract: dict[str, Any]) -> None:
    linkage = contract.get("s1_linkage", {})
    if linkage.get("schema") != "ci-rca-log-evidence/v2":
        raise ValueError("S1 linkage schema must be ci-rca-log-evidence/v2")
    expected = {"producer": "publish_envelope", "extractor": "extract_body", "consumer": "load_retrieval_input"}
    for role, symbol in expected.items():
        relative = linkage.get(role)
        if not isinstance(relative, str) or not (root / relative).is_file():
            raise ValueError(f"S1 {role} target is missing")
        if symbol not in (root / relative).read_text(encoding="utf-8"):
            raise ValueError(f"S1 {role} target does not expose {symbol}")


def _validate_jobs(root: Path, contract: dict[str, Any]) -> None:
    entries = contract.get("governed_jobs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("governed_jobs must be a nonempty list")
    seen: set[tuple[str, str]] = set()
    workflow_names: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("governed job entry must be a mapping")
        workflow, job_key = entry.get("workflow"), entry.get("job")
        if not isinstance(workflow, str) or not isinstance(job_key, str):
            raise ValueError("governed job requires workflow and job")
        identity = (workflow, job_key)
        if identity in seen:
            raise ValueError(f"duplicate governed selector: {workflow}:{job_key}")
        seen.add(identity)
        document = _load_yaml(root / workflow)
        display_name = document.get("name")
        if not isinstance(display_name, str) or display_name != entry.get("workflow_name"):
            raise ValueError(f"stale workflow display-name selector: {workflow}:{job_key}")
        if display_name in workflow_names and workflow_names[display_name] != workflow:
            raise ValueError(f"workflow display name is ambiguous: {display_name}")
        workflow_names[display_name] = workflow
        if not isinstance(job_key, str):
            raise ValueError("governed job requires workflow and job")
        jobs = document.get("jobs", {})
        if job_key not in jobs:
            raise ValueError(f"selected job is missing: {workflow}:{job_key}")
        steps = _steps(jobs[job_key])
        critical = entry.get("critical_step")
        if len(_matching_steps(steps, critical)) != 1:
            raise ValueError(f"critical step selector is missing or ambiguous: {workflow}:{job_key}")
        diagnostic_id = entry.get("diagnostic_id")
        if (
            not isinstance(diagnostic_id, str)
            or not _SAFE_IDENTIFIER.fullmatch(diagnostic_id)
            or _SECRET_SHAPES.search(diagnostic_id)
        ):
            raise ValueError(f"unsafe or unstable diagnostic identifier: {workflow}:{job_key}")
        surface = entry.get("surface")
        if not isinstance(surface, dict) or surface.get("class") not in contract.get("diagnostic_classes", {}):
            raise ValueError(f"unknown diagnostic surface class: {workflow}:{job_key}")
        if surface.get("class") != "native_step_failure" or surface.get("step") != critical:
            raise ValueError(f"decisive surface is not tied to the selected critical step: {workflow}:{job_key}")


def _actual_uploads(root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        document = _load_yaml(path)
        for job_key, job in document.get("jobs", {}).items():
            for step in _steps(job):
                if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                    settings = step.get("with", {})
                    found.append(
                        {
                            "workflow": str(path.relative_to(root)),
                            "job": job_key,
                            "step": step.get("name"),
                            "artifact": settings.get("name"),
                            "retention_days": settings.get("retention-days"),
                        }
                    )
    return found


def _validate_uploads(root: Path, contract: dict[str, Any]) -> None:
    declared = contract.get("artifact_uploads")
    if not isinstance(declared, list):
        raise ValueError("artifact_uploads must be a list")
    classes = contract["retention_classes"]
    keys: set[tuple[Any, ...]] = set()
    for item in declared:
        if not isinstance(item, dict) or item.get("retention_class") not in classes:
            raise ValueError("artifact upload has an unknown retention class")
        key = tuple(item.get(field) for field in ("workflow", "job", "step", "artifact"))
        if key in keys:
            raise ValueError(f"duplicate artifact classification: {key}")
        keys.add(key)
    actual = _actual_uploads(root)
    actual_keys = {tuple(item[field] for field in ("workflow", "job", "step", "artifact")) for item in actual}
    if keys != actual_keys:
        raise ValueError(
            f"artifact classification inventory differs: missing={actual_keys - keys}, stale={keys - actual_keys}"
        )
    by_key = {tuple(item.get(field) for field in ("workflow", "job", "step", "artifact")): item for item in declared}
    for upload in actual:
        if type(upload["retention_days"]) is not int:
            raise ValueError(f"artifact upload requires integer retention-days: {upload['workflow']}:{upload['step']}")
        classification = by_key[tuple(upload[field] for field in ("workflow", "job", "step", "artifact"))]
        policy = classes[classification["retention_class"]]
        if not policy["minimum_days"] <= upload["retention_days"] <= policy["maximum_days"]:
            raise ValueError(f"artifact retention is outside class bounds: {upload['workflow']}:{upload['step']}")


def validate_contract(root: Path) -> None:
    contract = _load_yaml(root / CONTRACT_PATH)
    _validate_classes(contract)
    _validate_s1(root, contract)
    _validate_jobs(root, contract)
    _validate_uploads(root, contract)


@registry.register("validate_actions_evidence", owner="platform")
def validate_actions_evidence(failed: list[str]) -> None:
    print("\n=== GitHub Actions evidence governance ===")
    try:
        validate_contract(_common.ROOT)
        print("  PASS: governed diagnostics and artifact retention match the contract")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        failed.append("GitHub Actions evidence governance")
