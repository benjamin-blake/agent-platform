"""Tests for scripts/plan_document.py covering the T1.11 exit criteria."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scripts.plan_document import PlanDocument, load, main, validate_paths
from scripts.validate import validate_plan_documents

FIXTURES = Path(__file__).parent / "fixtures" / "plan_documents"


def _base() -> dict:
    with (FIXTURES / "valid.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _mutate(**overrides) -> dict:
    d = copy.deepcopy(_base())
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
