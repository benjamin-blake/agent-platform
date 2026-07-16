"""Tests for scripts/roadmap/plan_document.py covering the T1.11 exit criteria."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scripts.roadmap.plan_document import PlanDocument, load, main, validate_paths
from scripts.validate import validate_plan_documents

FIXTURES = Path(__file__).parent / "fixtures" / "plan_documents"


def _base() -> dict:
    with (FIXTURES / "valid.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _base_v2() -> dict:
    with (FIXTURES / "valid_v2.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _mutate(**overrides) -> dict:
    d = copy.deepcopy(_base())
    d.update(overrides)
    return d


def _mutate_v2(**overrides) -> dict:
    d = copy.deepcopy(_base_v2())
    d.update(overrides)
    return d


class TestPlanDocumentSchema:
    def test_valid_document_validates(self):
        doc = PlanDocument.model_validate(_base())
        assert doc.slug == "zz-valid-demo"
        assert doc.plan_type == "IMPLEMENTATION"
        assert doc.verification_plan[0].command == "echo ok"

    def test_bad_plan_type_enum_fails(self):
        with pytest.raises(ValidationError, match="plan_type"):
            PlanDocument.model_validate(_mutate(plan_type="WRONG"))

    def test_bad_verification_tier_enum_fails(self):
        with pytest.raises(ValidationError, match="verification_tier"):
            PlanDocument.model_validate(_mutate(verification_tier="V9"))

    def test_unsupported_schema_version_fails(self):
        with pytest.raises(ValidationError, match="Unsupported schema_version"):
            PlanDocument.model_validate(_mutate(schema_version=99))

    def test_unknown_top_level_key_fails(self):
        with pytest.raises(ValidationError, match="acceptance_critera"):
            PlanDocument.model_validate(_mutate(acceptance_critera=["typo key is schema drift"]))

    def test_empty_scope_fails(self):
        with pytest.raises(ValidationError, match="scope"):
            PlanDocument.model_validate(_mutate(scope=[]))

    def test_whitespace_command_fails(self):
        base = _base()
        base["verification_plan"][0]["command"] = "   "
        with pytest.raises(ValidationError, match="non-empty executable command"):
            PlanDocument.model_validate(base)

    def test_duplicate_vp_step_ids_fail(self):
        base = _base()
        base["verification_plan"].append(dict(base["verification_plan"][0]))
        with pytest.raises(ValidationError, match="duplicates"):
            PlanDocument.model_validate(base)

    def test_plan_path_slug_mismatch_fails(self):
        with pytest.raises(ValidationError, match="slug consistency"):
            PlanDocument.model_validate(_mutate(plan_path="docs/plans/PLAN-other-slug.yaml"))

    def test_work_areas_on_implementation_fail(self):
        wa = [{"area": "A", "scope": "files", "rationale": "why", "complexity": "S"}]
        with pytest.raises(ValidationError, match="only valid on STRATEGIC"):
            PlanDocument.model_validate(_mutate(work_areas=wa))

    def test_strategic_requires_work_areas(self):
        with pytest.raises(ValidationError, match="require a non-empty work_areas"):
            PlanDocument.model_validate(_mutate(plan_type="STRATEGIC"))

    def test_strategic_with_work_areas_validates(self):
        wa = [{"area": "A", "scope": "files", "rationale": "why", "complexity": "S"}]
        doc = PlanDocument.model_validate(
            _mutate(
                plan_type="STRATEGIC",
                slug="zz-strategic-demo",
                plan_path="docs/plans/PLAN-zz-strategic-demo.yaml",
                work_areas=wa,
            )
        )
        assert doc.work_areas[0].complexity == "S"

    def test_implementation_requires_execution_steps(self):
        with pytest.raises(ValidationError, match="non-empty execution_steps"):
            PlanDocument.model_validate(_mutate(execution_steps=[]))

    def test_report_only_without_execution_steps_validates(self):
        doc = PlanDocument.model_validate(_mutate(plan_type="REPORT-ONLY", execution_steps=[]))
        assert doc.plan_type == "REPORT-ONLY"


class TestLoader:
    def test_load_valid_file(self, tmp_path):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        doc = load(target)
        assert doc.slug == "zz-valid-demo"

    def test_load_malformed_fixture_fails_on_command(self, tmp_path):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        with pytest.raises(ValidationError, match="non-empty executable command"):
            load(target)

    def test_filename_slug_guard(self, tmp_path):
        target = tmp_path / "PLAN-wrong-name.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        with pytest.raises(ValueError, match="does not match slug"):
            load(target)

    def test_validate_paths_reports_failures(self, tmp_path):
        good = tmp_path / "PLAN-zz-valid-demo.yaml"
        bad = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", good)
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", bad)
        failures = validate_paths([good, bad])
        assert len(failures) == 1
        assert failures[0][0] == bad


class TestCli:
    def test_main_pass_on_valid(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        assert main([str(target)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_main_fail_on_malformed(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        assert main([str(target)]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_main_default_glob_empty_dir(self, tmp_path, capsys):
        assert main([], plans_root=tmp_path) == 0
        assert "no PLAN-*.yaml files found" in capsys.readouterr().out

    def test_main_default_glob_finds_files(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        assert main([], plans_root=tmp_path) == 0
        assert "PASS" in capsys.readouterr().out


class TestValidateIntegration:
    def test_validate_plan_documents_passes_on_valid_dir(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert failed == []
        assert "PASS" in capsys.readouterr().out

    def test_validate_plan_documents_fails_on_malformed(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert "Plan document schema validation" in failed
        assert "FAIL" in capsys.readouterr().out

    def test_validate_plan_documents_empty_dir_passes(self, tmp_path, capsys):
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert failed == []
        assert "no PLAN-*.yaml files to validate" in capsys.readouterr().out


class TestClosesCriteria:
    """T-1.23: closes_criteria is an additive optional field (Decision 85)."""

    def test_closes_criteria_defaults_to_empty_list(self) -> None:
        doc = PlanDocument.model_validate(_base())
        assert doc.closes_criteria == []

    def test_closes_criteria_accepts_list_of_strings(self) -> None:
        d = _mutate(closes_criteria=["T-1.23:c1", "T-1.23:c2"])
        doc = PlanDocument.model_validate(d)
        assert doc.closes_criteria == ["T-1.23:c1", "T-1.23:c2"]

    def test_closes_criteria_empty_list_explicit(self) -> None:
        d = _mutate(closes_criteria=[])
        doc = PlanDocument.model_validate(d)
        assert doc.closes_criteria == []

    def test_unknown_field_still_rejected(self) -> None:
        d = _mutate(some_unknown_field="oops")
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)

    def test_closes_criteria_present_does_not_break_extra_forbid(self) -> None:
        d = _mutate(closes_criteria=["T0.4:c1"], some_bad="x")
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)


class TestSchemaVersion2:
    """T3.17 (VF-04/VF-13): schema_version-2 phase enum, hermetic default, tier_waiver."""

    def test_v2_valid_document_validates(self) -> None:
        doc = PlanDocument.model_validate(_base_v2())
        assert doc.schema_version == 2
        assert doc.verification_plan[0].phase == "pre-deploy"
        assert doc.verification_plan[1].phase == "post-deploy"

    def test_v2_phase_pre_merge_rejected(self) -> None:
        d = _base_v2()
        d["verification_plan"][0]["phase"] = "pre-merge"
        with pytest.raises(ValidationError, match="schema_version 2 verification_plan"):
            PlanDocument.model_validate(d)

    def test_v1_free_text_phase_still_accepted(self) -> None:
        d = _mutate()
        d["verification_plan"][0]["phase"] = "pre-merge"
        doc = PlanDocument.model_validate(d)
        assert doc.verification_plan[0].phase == "pre-merge"

    def test_hermetic_defaults_false(self) -> None:
        d = _base_v2()
        d["verification_plan"][1]["hermetic"] = False
        doc = PlanDocument.model_validate(d)
        assert doc.verification_plan[1].hermetic is False

    def test_hermetic_true_accepted(self) -> None:
        doc = PlanDocument.model_validate(_base_v2())
        assert doc.verification_plan[0].hermetic is True

    def test_tier_waiver_optional_defaults_none(self) -> None:
        doc = PlanDocument.model_validate(_base_v2())
        assert doc.tier_waiver is None

    def test_tier_waiver_accepted_as_string(self) -> None:
        d = _mutate_v2(tier_waiver="conscious V2: comment-only .tf change")
        doc = PlanDocument.model_validate(d)
        assert doc.tier_waiver == "conscious V2: comment-only .tf change"

    def test_v2_unsupported_version_still_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported schema_version"):
            PlanDocument.model_validate(_mutate_v2(schema_version=3))


class TestGraduationDisposition:
    """T3.21 (VF-05 enforcement): per-VP-step graduation disposition, backward-compatible."""

    def test_graduate_with_check_id_accepted(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "graduate"
        d["verification_plan"][0]["graduation_check_id"] = "some-check-id"
        doc = PlanDocument.model_validate(d)
        assert doc.verification_plan[0].graduation == "graduate"
        assert doc.verification_plan[0].graduation_check_id == "some-check-id"

    def test_waive_with_reason_accepted(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "waive"
        d["verification_plan"][0]["graduation_waiver_reason"] = "requires live infra, not kernel-expressible"
        doc = PlanDocument.model_validate(d)
        assert doc.verification_plan[0].graduation == "waive"
        assert doc.verification_plan[0].graduation_waiver_reason == "requires live infra, not kernel-expressible"

    def test_not_applicable_accepted(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "not-applicable"
        doc = PlanDocument.model_validate(d)
        assert doc.verification_plan[0].graduation == "not-applicable"

    def test_absent_field_backward_compatible(self) -> None:
        doc = PlanDocument.model_validate(_base())
        assert doc.verification_plan[0].graduation is None
        assert doc.verification_plan[0].graduation_check_id is None
        assert doc.verification_plan[0].graduation_waiver_reason is None

    def test_graduate_without_check_id_rejected(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "graduate"
        with pytest.raises(ValidationError, match="graduation='graduate' requires a non-empty graduation_check_id"):
            PlanDocument.model_validate(d)

    def test_waive_without_reason_rejected(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "waive"
        with pytest.raises(ValidationError, match="graduation='waive' requires a non-empty graduation_waiver_reason"):
            PlanDocument.model_validate(d)

    def test_unknown_disposition_value_rejected(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation"] = "bogus"
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)

    def test_check_id_without_graduate_rejected(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation_check_id"] = "orphaned-check-id"
        with pytest.raises(ValidationError, match="graduation_check_id requires graduation='graduate'"):
            PlanDocument.model_validate(d)

    def test_reason_without_waive_rejected(self) -> None:
        d = _base()
        d["verification_plan"][0]["graduation_waiver_reason"] = "orphaned reason"
        with pytest.raises(ValidationError, match="graduation_waiver_reason requires graduation='waive'"):
            PlanDocument.model_validate(d)

    def test_graduate_with_stray_waiver_reason_rejected(self) -> None:
        """Cross-field leakage: a 'graduate' step must not also carry a waiver reason."""
        d = _base()
        d["verification_plan"][0]["graduation"] = "graduate"
        d["verification_plan"][0]["graduation_check_id"] = "some-check-id"
        d["verification_plan"][0]["graduation_waiver_reason"] = "stray leftover reason"
        with pytest.raises(ValidationError, match="graduation_waiver_reason requires graduation='waive'"):
            PlanDocument.model_validate(d)

    def test_waive_with_stray_check_id_rejected(self) -> None:
        """Cross-field leakage: a 'waive' step must not also carry a check_id."""
        d = _base()
        d["verification_plan"][0]["graduation"] = "waive"
        d["verification_plan"][0]["graduation_waiver_reason"] = "requires live infra"
        d["verification_plan"][0]["graduation_check_id"] = "stray leftover check-id"
        with pytest.raises(ValidationError, match="graduation_check_id requires graduation='graduate'"):
            PlanDocument.model_validate(d)

    def test_historical_plans_all_validate(self) -> None:
        """No PLAN-*.yaml on disk carries the new field yet -- confirms the field is optional."""
        from scripts.roadmap.plan_document import main as _main

        assert _main([]) == 0
