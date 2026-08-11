"""Tests for validate_plan_scope_closure() -- plan-obligation-closure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks import registry
from scripts.checks.roadmap.validate_plan_scope_closure import validate_plan_scope_closure
from scripts.roadmap import plan_obligations


def _base_scope() -> dict:
    return {
        "schema_version": 4,
        "plan_type": "IMPLEMENTATION",
        "slug": "fixture-probe",
        "plan_path": "docs/plans/PLAN-fixture-probe.yaml",
        "scope": [
            {"file": "scripts/checks/roadmap/validate_x.py", "action": "Create", "purpose": "p"},
            {"file": "scripts/checks/roadmap/_manifest.py", "action": "Modify", "purpose": "p"},
            {"file": "config/ci_rca_taxonomy.yaml", "action": "Modify", "purpose": "p"},
            {"file": "tests/checks/roadmap/test_validate_x.py", "action": "Create", "purpose": "p"},
        ],
    }


def _write(tmp_path: Path, data: dict, name: str = "PLAN-fixture-probe.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestClosure:
    def test_registered_and_sequenced_in_both_tiers(self) -> None:
        registry.resolve("validate_plan_scope_closure")
        pre = {step.name for step in registry.pre_sequence()}
        full = {step.name for step in registry.full_sequence()}
        assert "validate_plan_scope_closure" in pre
        assert "validate_plan_scope_closure" in full

    def test_complete_plan_passes(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _base_scope())
        failed: list[str] = []
        validate_plan_scope_closure(failed, plan_paths=[path])
        assert failed == []

    def test_names_each_omission_by_path_in_failed(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "scripts/checks/roadmap/_manifest.py"]
        path = _write(tmp_path, data)
        failed: list[str] = []
        validate_plan_scope_closure(failed, plan_paths=[path])
        assert failed and any("scripts/checks/roadmap/_manifest.py" in entry for entry in failed)

    def test_grandfathers_sub_v4_plan(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["schema_version"] = 3
        data["scope"] = [{"file": "scripts/checks/roadmap/validate_y.py", "action": "Create", "purpose": "p"}]
        path = _write(tmp_path, data)
        failed: list[str] = []
        validate_plan_scope_closure(failed, plan_paths=[path])
        assert failed == []

    def test_explicit_empty_plan_paths_never_derives_from_diff(self) -> None:
        with patch.object(plan_obligations, "net_new_v4_implementation_plan_paths") as mock_derive:
            failed: list[str] = []
            validate_plan_scope_closure(failed, plan_paths=[])
            assert failed == []
            mock_derive.assert_not_called()

    def test_none_plan_paths_derives_from_diff(self) -> None:
        with patch.object(plan_obligations, "net_new_v4_implementation_plan_paths", return_value=[]) as mock_derive:
            failed: list[str] = []
            validate_plan_scope_closure(failed, plan_paths=None)
            assert failed == []
            mock_derive.assert_called_once()

    def test_absent_file_reported_never_raises(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_plan_scope_closure(failed, plan_paths=[tmp_path / "PLAN-absent.yaml"])
        assert failed and "could not read" in failed[0]

    def test_dispatch_recording_attributes_each_finding_to_this_check(self, tmp_path: Path) -> None:
        """scripts.checks.validation_result.dispatch_recording attributes every label a check
        appends to `failed` back to the check's registered name -- exercised directly here since
        this check appends one label per omission, not a single summary string."""
        from scripts.checks import validation_result

        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "config/ci_rca_taxonomy.yaml"]
        path = _write(tmp_path, data)
        failed: list[str] = []
        validation_result._ATTRIBUTIONS.clear()
        validation_result.dispatch_recording(
            "validate_plan_scope_closure", failed, lambda f: validate_plan_scope_closure(f, plan_paths=[path])
        )
        assert failed
        assert all(a["check"] == "validate_plan_scope_closure" for a in validation_result._ATTRIBUTIONS)
        validation_result._ATTRIBUTIONS.clear()
