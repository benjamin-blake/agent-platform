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

    def test_closes_criteria_rejects_prose_with_whitespace(self) -> None:
        """T-1.23 field_validator: narrative/prose entries belong in context:, not closes_criteria."""
        d = _mutate(closes_criteria=["APPLY-PATH SPLIT (critical -- some narrative caveat)."])
        with pytest.raises(ValidationError, match="contains whitespace"):
            PlanDocument.model_validate(d)

    def test_closes_criteria_rejects_missing_colon(self) -> None:
        d = _mutate(closes_criteria=["T2.18c1"])
        with pytest.raises(ValidationError, match="exactly one ':'"):
            PlanDocument.model_validate(d)

    def test_closes_criteria_rejects_multiple_colons(self) -> None:
        d = _mutate(closes_criteria=["T2.18:c1:extra"])
        with pytest.raises(ValidationError, match="exactly one ':'"):
            PlanDocument.model_validate(d)

    def test_closes_criteria_rejects_empty_item_id(self) -> None:
        d = _mutate(closes_criteria=[":c1"])
        with pytest.raises(ValidationError, match="must both be non-empty"):
            PlanDocument.model_validate(d)

    def test_closes_criteria_rejects_empty_crit_id(self) -> None:
        d = _mutate(closes_criteria=["T2.18:"])
        with pytest.raises(ValidationError, match="must both be non-empty"):
            PlanDocument.model_validate(d)

    def test_closes_criteria_accepts_real_world_token_shapes(self) -> None:
        """Loose grammar: lettered criteria and hyphenated/triple-dotted/lettered-suffix item ids."""
        tokens = ["T2.18:c1", "T4.12:cA", "T-1.20:c3", "T3.15.1:c4", "T2.25a:c2"]
        d = _mutate(closes_criteria=tokens)
        doc = PlanDocument.model_validate(d)
        assert doc.closes_criteria == tokens


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
        with pytest.raises(ValidationError, match="require handoff_policy"):
            PlanDocument.model_validate(_mutate_v2(schema_version=3))


class TestSchemaVersion3:
    def test_historical_version_forbids_handoff_policy(self) -> None:
        data = _mutate_v2(handoff_policy={"full_validation_required_before_commit": True, "timeout_disposition": "blocked"})
        with pytest.raises(ValidationError, match="only valid with schema_version 3"):
            PlanDocument.model_validate(data)

    def test_implementation_requires_blocking_handoff_policy(self) -> None:
        data = _mutate_v2(
            schema_version=3,
            handoff_policy={"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
        )
        assert PlanDocument.model_validate(data).schema_version == 3

    @pytest.mark.parametrize(
        "policy",
        [
            None,
            {"full_validation_required_before_commit": False, "timeout_disposition": "blocked"},
            {"full_validation_required_before_commit": True, "timeout_disposition": "warning"},
        ],
    )
    def test_invalid_implementation_policy_fails_closed(self, policy: object) -> None:
        data = _mutate_v2(schema_version=3)
        if policy is not None:
            data["handoff_policy"] = policy
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(data)

    @pytest.mark.parametrize("plan_type", ["STRATEGIC", "REPORT-ONLY"])
    def test_non_implementation_forbids_policy(self, plan_type: str) -> None:
        data = _mutate_v2(
            schema_version=3,
            plan_type=plan_type,
            execution_steps=[],
            handoff_policy={"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
        )
        if plan_type == "STRATEGIC":
            data["work_areas"] = [{"area": "A", "scope": "files", "rationale": "why", "complexity": "S"}]
        with pytest.raises(ValidationError, match="only valid"):
            PlanDocument.model_validate(data)


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


class TestFallbackReevaluation:
    """ESB-02 remediation (PLAN-esb-fallback-spec-carrier): the optional fallback_reevaluation
    block a plan carries when it names a CD.27-gated tier item (scripts/checks/roadmap/
    validate_fallback_reevaluation.py). The obligation to attach it lives in that check, not in
    this schema -- so absence must stay valid on every historical plan."""

    def _block(self, **overrides) -> dict:
        base = {
            "reevaluated_on": "2026-08-02",
            "substrate_status": "no API-semantics regression observed at filing",
            "verdict": "continue_on_current_substrate",
            "basis": "reviewed against the CD.27 fallback_spec trigger; substrate semantics unchanged",
        }
        base.update(overrides)
        return base

    def test_well_formed_block_validates(self) -> None:
        d = _mutate(fallback_reevaluation=self._block())
        doc = PlanDocument.model_validate(d)
        assert doc.fallback_reevaluation is not None
        assert doc.fallback_reevaluation.verdict == "continue_on_current_substrate"

    def test_field_absent_is_valid_backward_compatible(self) -> None:
        doc = PlanDocument.model_validate(_base())
        assert doc.fallback_reevaluation is None

    def test_unknown_verdict_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(verdict="looks_fine"))
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)

    def test_empty_basis_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(basis="   "))
        with pytest.raises(ValidationError, match="basis must be non-blank"):
            PlanDocument.model_validate(d)

    def test_whitespace_only_reevaluated_on_rejected(self) -> None:
        """Symmetry with basis (code review round 1): all three free-text fields reject blank."""
        d = _mutate(fallback_reevaluation=self._block(reevaluated_on="   "))
        with pytest.raises(ValidationError, match="reevaluated_on must be non-blank"):
            PlanDocument.model_validate(d)

    def test_whitespace_only_substrate_status_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(substrate_status="   "))
        with pytest.raises(ValidationError, match="substrate_status must be non-blank"):
            PlanDocument.model_validate(d)

    def test_non_iso_reevaluated_on_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(reevaluated_on="August 2, 2026"))
        with pytest.raises(ValidationError, match="must be an ISO date"):
            PlanDocument.model_validate(d)

    def test_iso_reevaluated_on_accepted(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(reevaluated_on="2026-01-05"))
        doc = PlanDocument.model_validate(d)
        assert doc.fallback_reevaluation.reevaluated_on == "2026-01-05"

    def test_basic_format_reevaluated_on_rejected(self) -> None:
        """Code review round 2 (Low): date.fromisoformat() alone accepts the dash-free basic
        ISO format on Python 3.11+ ('20260802'); the validator must reject it -- this is a date
        stamp in a governance document, and the error message promises YYYY-MM-DD specifically."""
        d = _mutate(fallback_reevaluation=self._block(reevaluated_on="20260802"))
        with pytest.raises(ValidationError, match="must be an ISO date"):
            PlanDocument.model_validate(d)

    def test_datetime_with_time_component_reevaluated_on_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(reevaluated_on="2026-08-02T00:00:00"))
        with pytest.raises(ValidationError, match="must be an ISO date"):
            PlanDocument.model_validate(d)

    def test_missing_basis_rejected(self) -> None:
        block = self._block()
        block.pop("basis")
        d = _mutate(fallback_reevaluation=block)
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)

    def test_extra_key_rejected(self) -> None:
        d = _mutate(fallback_reevaluation=self._block(note="x"))
        with pytest.raises(ValidationError):
            PlanDocument.model_validate(d)

    def test_all_historical_plans_still_valid_with_field_absent(self) -> None:
        """Decision 85: validate_plan_documents re-validates the whole plans directory against
        an extra='forbid' model, so an added optional field is a repo-wide event."""
        paths = sorted((Path(__file__).parent.parent / "docs" / "plans").glob("PLAN-*.yaml"))
        failures = validate_paths(paths)
        assert not failures, f"historical plan(s) invalidated by the new field: {[(p.name, e[:80]) for p, e in failures[:3]]}"
