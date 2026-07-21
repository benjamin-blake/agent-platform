"""Pydantic schema for docs/plans/PLAN-*.yaml planning artefacts, loader, and CLI (T1.11 / CD.22)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SUPPORTED_VERSIONS: frozenset[int] = frozenset({1, 2})
_V2_PHASE_ENUM: frozenset[str] = frozenset({"pre-deploy", "post-deploy"})

PlanType = Literal["IMPLEMENTATION", "STRATEGIC", "REPORT-ONLY"]
VerificationTier = Literal["V1", "V2", "V3"]
ScopeAction = Literal["Create", "Modify", "Delete"]
Complexity = Literal["XS", "S", "M", "L", "XL"]
GraduationDisposition = Literal["graduate", "waive", "not-applicable"]


class ScopeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = Field(min_length=1)
    action: ScopeAction
    purpose: str = Field(min_length=1)


class VerificationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    phase: str = Field(min_length=1)
    action: str = Field(min_length=1)
    command: str
    expected: str = Field(min_length=1)
    fix_if: str = Field(min_length=1)
    hermetic: bool = False
    graduation: GraduationDisposition | None = None
    graduation_check_id: str | None = None
    graduation_waiver_reason: str | None = None

    @field_validator("command")
    @classmethod
    def _command_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("verification step requires a non-empty executable command")
        return v

    @model_validator(mode="after")
    def _validate_graduation_disposition(self) -> VerificationStep:
        has_check_id = bool(self.graduation_check_id and self.graduation_check_id.strip())
        has_reason = bool(self.graduation_waiver_reason and self.graduation_waiver_reason.strip())
        if self.graduation == "graduate":
            if not has_check_id:
                raise ValueError(
                    f"verification step {self.step}: graduation='graduate' requires a non-empty graduation_check_id"
                )
            if self.graduation_waiver_reason:
                raise ValueError(f"verification step {self.step}: graduation_waiver_reason requires graduation='waive'")
        elif self.graduation == "waive":
            if not has_reason:
                raise ValueError(
                    f"verification step {self.step}: graduation='waive' requires a non-empty graduation_waiver_reason"
                )
            if self.graduation_check_id:
                raise ValueError(f"verification step {self.step}: graduation_check_id requires graduation='graduate'")
        else:
            if self.graduation_check_id:
                raise ValueError(f"verification step {self.step}: graduation_check_id requires graduation='graduate'")
            if self.graduation_waiver_reason:
                raise ValueError(f"verification step {self.step}: graduation_waiver_reason requires graduation='waive'")
        return self


class WorkArea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    complexity: Complexity


class PlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    slug: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    plan_type: PlanType
    verification_tier: VerificationTier
    plan_path: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    scope: list[ScopeEntry] = Field(min_length=1)
    bundled_recommendations: list[str] = Field(default_factory=list)
    closes_criteria: list[str] = Field(default_factory=list)
    infrastructure_dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    verification_plan: list[VerificationStep] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    pre_implementation_checklist: list[str] = Field(default_factory=list)
    execution_steps: list[str] = Field(default_factory=list)
    work_areas: list[WorkArea] = Field(default_factory=list)
    rollback: str | None = None
    tier_waiver: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, v: int) -> int:
        if v not in _SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported schema_version {v}. Supported: {sorted(_SUPPORTED_VERSIONS)}")
        return v

    @field_validator("closes_criteria")
    @classmethod
    def _closes_criteria_tokens(cls, v: list[str]) -> list[str]:
        # Loose shape check only -- reject prose, accept every real <item-id>:<crit-id> token
        # (lettered criteria, hyphenated/triple-dotted/lettered-suffix item ids). Membership
        # (does the ref actually exist) stays owned by validate_platform_roadmap.
        for entry in v:
            if any(ch.isspace() for ch in entry):
                raise ValueError(
                    f"closes_criteria entry {entry!r} is not a valid '<item-id>:<crit-id>' token "
                    "(contains whitespace -- narrative/prose text belongs in context:, not closes_criteria)"
                )
            if entry.count(":") != 1:
                raise ValueError(
                    f"closes_criteria entry {entry!r} is not a valid '<item-id>:<crit-id>' token "
                    "(must contain exactly one ':' separating item-id and crit-id)"
                )
            item_id, crit_id = entry.split(":", 1)
            if not item_id or not crit_id:
                raise ValueError(
                    f"closes_criteria entry {entry!r} is not a valid '<item-id>:<crit-id>' token "
                    "(item-id and crit-id must both be non-empty)"
                )
        return v

    @model_validator(mode="after")
    def _validate_document(self) -> PlanDocument:
        expected_path = f"docs/plans/PLAN-{self.slug}.yaml"
        if self.plan_path != expected_path:
            raise ValueError(f"plan_path '{self.plan_path}' must equal '{expected_path}' (slug consistency)")

        step_ids = [vp.step for vp in self.verification_plan]
        dupes = sorted({s for s in step_ids if step_ids.count(s) > 1})
        if dupes:
            raise ValueError(f"verification_plan step ids must be unique; duplicates: {dupes}")

        if self.plan_type == "STRATEGIC" and not self.work_areas:
            raise ValueError("STRATEGIC plans require a non-empty work_areas list")
        if self.plan_type != "STRATEGIC" and self.work_areas:
            raise ValueError(f"work_areas are only valid on STRATEGIC plans (plan_type is {self.plan_type})")

        if self.plan_type == "IMPLEMENTATION" and not self.execution_steps:
            raise ValueError("IMPLEMENTATION plans require non-empty execution_steps")

        if self.schema_version == 2:
            bad_phases = sorted({vp.phase for vp in self.verification_plan if vp.phase not in _V2_PHASE_ENUM})
            if bad_phases:
                raise ValueError(
                    f"schema_version 2 verification_plan[].phase must be one of {sorted(_V2_PHASE_ENUM)}, got: {bad_phases}"
                )
        return self


def load(path: str | Path) -> PlanDocument:
    """Parse the YAML plan at path and return a validated PlanDocument.

    Also enforces the filename/slug dangling-reference guard: the file on disk
    must be named PLAN-{slug}.yaml.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    doc = PlanDocument.model_validate(data)
    expected_name = f"PLAN-{doc.slug}.yaml"
    if path.name != expected_name:
        raise ValueError(f"Filename '{path.name}' does not match slug '{doc.slug}' (expected {expected_name})")
    return doc


def validate_paths(paths: list[Path]) -> list[tuple[Path, str]]:
    """Validate each path; return (path, error) tuples for failures."""
    failures: list[tuple[Path, str]] = []
    for path in paths:
        try:
            load(path)
        except Exception as exc:  # noqa: BLE001 -- any parse/validation error is a failure verdict
            failures.append((path, str(exc)))
    return failures


def main(argv: list[str] | None = None, plans_root: Path | None = None) -> int:
    root = plans_root if plans_root is not None else Path(__file__).resolve().parent.parent.parent / "docs" / "plans"
    parser = argparse.ArgumentParser(description="Plan document validator (PLAN-*.yaml)")
    parser.add_argument(
        "paths",
        nargs="*",
        help="PLAN-*.yaml paths to validate (default: all docs/plans/PLAN-*.yaml)",
    )
    args = parser.parse_args(argv)
    paths = [Path(p) for p in args.paths] if args.paths else sorted(root.glob("PLAN-*.yaml"))
    if not paths:
        print("PASS: no PLAN-*.yaml files found.")
        return 0
    failures = validate_paths(paths)
    failed_paths = {p for p, _ in failures}
    for path in paths:
        if path in failed_paths:
            error = next(err for p, err in failures if p == path)
            print(f"FAIL: {path}: {error}")
        else:
            print(f"PASS: {path} validates against PlanDocument schema.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
