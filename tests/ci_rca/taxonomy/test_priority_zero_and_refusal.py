"""Tests for the Priority-0 validation-result attribution path and the evidence_insufficient
refusal gate (ci-rca-evidence-fidelity). Split from the former flat
tests/test_ci_rca_taxonomy.py (Decision 128 decompose-by-default).
"""

import json

from scripts.ci_rca.taxonomy import classify_failure, classify_failures
from tests.fixtures.ci_rca.taxonomy_data import (
    FAILED_CHECKS_TAXONOMY,
    MINIMAL_TAXONOMY,
    STEP_NAME_MAP_TAXONOMY,
    write_taxonomy,
    write_validation_result,
)


class TestPriorityZeroAttribution:
    """ci-rca-evidence-fidelity: the validation-result attribution artifact (Priority 0) is the
    CARRIED fact and must outrank every derived signal below it -- including Priority 1's
    step-name match, which is what actually misdiagnosed rec-2957/2958/2973 (the aggregate step
    name 'Validate full tier (...)' IS a step_name_to_category key)."""

    def test_singular_returns_the_attributed_check(self, tmp_path):
        vr = write_validation_result(tmp_path, [{"check": "validate_test_coverage", "label": "Coverage below 100%"}])
        p = write_taxonomy(tmp_path, STEP_NAME_MAP_TAXONOMY)
        cat, check, src = classify_failure("irrelevant log", path=p, validation_result_path=vr)
        assert cat == "code_regression"
        assert check == "validate_test_coverage"
        assert src == "validate_failed_check_attribution"

    def test_plural_enumerates_n_attributions_to_n_failures(self, tmp_path):
        taxonomy_data = dict(MINIMAL_TAXONOMY)
        taxonomy_data["function_to_category"] = {
            "validate_test_coverage": "code_regression",
            "validate_sloc_limits": "sloc_violation",
        }
        vr = write_validation_result(
            tmp_path,
            [
                {"check": "validate_test_coverage", "label": "Coverage below 100%"},
                {"check": "validate_sloc_limits", "label": "SLOC limits (Decision 43)"},
            ],
        )
        p = write_taxonomy(tmp_path, taxonomy_data)
        results = classify_failures("irrelevant log", path=p, validation_result_path=vr)
        assert len(results) == 2
        assert {r[1] for r in results} == {"validate_test_coverage", "validate_sloc_limits"}
        assert {r[2] for r in results} == {"validate_failed_check_attribution"}

    def test_step_name_collision_case(self, tmp_path):
        """THE regression this plan exists to fix: a jobs-JSON failed step named the full-tier
        aggregate step name (a step_name_to_category KEY, Priority 1) must NOT win when an
        attribution artifact is present -- Priority 0 outranks it."""
        vr = write_validation_result(tmp_path, [{"check": "validate_test_coverage", "label": "Coverage below 100%"}])
        p = write_taxonomy(tmp_path, STEP_NAME_MAP_TAXONOMY)
        jobs = [
            {
                "steps": [
                    {
                        "name": "Validate full tier (ruff, mypy, pytest, DQ runner, verifier harness)",
                        "conclusion": "failure",
                    }
                ]
            }
        ]
        cat, check, src = classify_failure("irrelevant log", jobs=jobs, path=p, validation_result_path=vr)
        assert check == "validate_test_coverage"
        assert cat == "code_regression"

        results = classify_failures("irrelevant log", jobs=jobs, path=p, validation_result_path=vr)
        assert [r[1] for r in results] == ["validate_test_coverage"]

    def test_unmapped_attributed_check_does_not_fire_priority_zero(self, tmp_path):
        """An attribution naming a check absent from function_to_category (should never happen
        given the registry-totality guard, but defensively) does not fire Priority 0 -- falls
        through to the rest of the ladder."""
        vr = write_validation_result(tmp_path, [{"check": "validate_unregistered", "label": "some label"}])
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, validation_result_path=vr)
        assert src == "function_to_category"

    def test_absent_artifact_path_does_not_fire_priority_zero(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure(
            "validate_sloc_limits FAILED", path=p, validation_result_path=tmp_path / "nonexistent.json"
        )
        assert src == "function_to_category"

    def test_no_artifact_path_given_falls_through_unaffected(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert src == "function_to_category"

    def test_malformed_artifact_json_degrades_gracefully(self, tmp_path):
        vr = tmp_path / "validation-result.json"
        vr.write_text("not json", encoding="utf-8")
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, validation_result_path=vr)
        assert src == "function_to_category"

    def test_artifact_json_not_a_mapping_degrades_gracefully(self, tmp_path):
        vr = tmp_path / "validation-result.json"
        vr.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, validation_result_path=vr)
        assert src == "function_to_category"

    def test_artifact_missing_attributions_key_degrades_gracefully(self, tmp_path):
        vr = tmp_path / "validation-result.json"
        vr.write_text(json.dumps({"schema_version": 1, "failed_checks": ["x"]}), encoding="utf-8")
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, validation_result_path=vr)
        assert src == "function_to_category"

    def test_artifact_with_malformed_attribution_entries_skips_them(self, tmp_path):
        vr = tmp_path / "validation-result.json"
        vr.write_text(
            json.dumps({"failed_check_attributions": [{"check": "validate_sloc_limits"}, "not a dict", 42]}),
            encoding="utf-8",
        )
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, validation_result_path=vr)
        # malformed entries (missing "label", non-dict) are skipped -- none resolve, Priority 0
        # does not fire, falls through to the substring scan
        assert src == "function_to_category"

    def test_duplicate_check_attributions_deduplicate_in_enumeration(self, tmp_path):
        taxonomy_data = dict(MINIMAL_TAXONOMY)
        taxonomy_data["function_to_category"] = {"validate_test_coverage": "code_regression"}
        vr = write_validation_result(
            tmp_path,
            [
                {"check": "validate_test_coverage", "label": "Coverage below 100%"},
                {"check": "validate_test_coverage", "label": "Coverage below 100% (again)"},
            ],
        )
        p = write_taxonomy(tmp_path, taxonomy_data)
        results = classify_failures("irrelevant log", path=p, validation_result_path=vr)
        assert len(results) == 1
        assert results[0][1] == "validate_test_coverage"


class TestEvidenceInsufficientRefusal:
    """ci-rca-evidence-fidelity: the refusal preempts Priority 4 (substring scan) and Priority 5
    (regex fallback) when evidence is incomplete AND no attribution artifact AND no junit
    cause-group is available -- but stands down (never fires) when a junit cause-group exists
    (Decision 142: never collapse distinct pytest causes onto one chain)."""

    def test_refusal_preempts_priority_4_substring_trigger(self, tmp_path):
        """The exact rec-2958 shape: a PASSING check's name merely appears in a truncated log."""
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("  [PASS] validate_sloc_limits: ok\n", path=p, complete=False)
        assert cat == "evidence_insufficient"
        assert src == "evidence_insufficient_refusal"

    def test_refusal_preempts_priority_5_regex_only_trigger(self, tmp_path):
        """A regex-only trigger (no function_to_category substring present) also refuses rather
        than guessing via the log_pattern_to_category fallback."""
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("Error: ImportError at line 5", path=p, complete=False)
        assert cat == "evidence_insufficient"
        assert src == "evidence_insufficient_refusal"

    def test_refusal_stands_down_when_junit_cause_group_available(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, complete=False, has_junit_cause_group=True)
        assert cat == "sloc_violation"
        assert src == "function_to_category"

    def test_refusal_does_not_fire_when_evidence_is_complete(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p, complete=True)
        assert cat == "sloc_violation"
        assert src == "function_to_category"

    def test_refusal_does_not_fire_when_a_higher_priority_already_matched(self, tmp_path):
        """Incomplete evidence is irrelevant once Priority 0-3 already resolved the failure --
        here Priority 3's "Failed checks:" block match."""
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        log = "Failed checks:\n  - validate_platform_roadmap\n"
        cat, check, src = classify_failure(log, path=p, complete=False)
        assert cat == "schema_drift"
        assert src == "validate_failed_checks_block"

    def test_plural_refusal_via_fallback_path(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("  [PASS] validate_sloc_limits: ok\n", path=p, complete=False)
        assert len(results) == 1
        assert results[0] == ("evidence_insufficient", "evidence_insufficient", "evidence_insufficient_refusal")

    def test_plural_refusal_stands_down_with_junit_cause_group(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("validate_sloc_limits FAILED", path=p, complete=False, has_junit_cause_group=True)
        assert results == [("sloc_violation", "validate_sloc_limits", "function_to_category")]
