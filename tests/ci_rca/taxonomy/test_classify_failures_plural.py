"""Tests for classify_failures (the enumeration/plural entry point) and jobs-JSON preference.
Split from the former flat tests/test_ci_rca_taxonomy.py (ci-rca-evidence-fidelity, Decision 128
decompose-by-default).
"""

from scripts.ci_rca.taxonomy import classify_failure, classify_failures
from tests.fixtures.ci_rca.taxonomy_data import MINIMAL_TAXONOMY, MULTI_TAXONOMY, write_taxonomy


class TestClassifyFailures:
    def test_single_match_returns_list_of_one(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("validate_sloc_limits FAILED", path=p)
        assert isinstance(results, list)
        assert len(results) == 1
        cat, check, src = results[0]
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_multiple_log_text_mentions_no_longer_fan_out(self, tmp_path):
        """Regression test (2026-07 incident): a single failing check's FULL job log routinely
        mentions other, unrelated validate_* function names (checks that ran and passed earlier
        in the same job). Without jobs-JSON failed-step data, multiple log-text substring hits
        must NOT be treated as multiple distinct failures -- exactly one bundle is emitted via
        the single priority-ordered classify_failure() fallback."""
        p = write_taxonomy(tmp_path, MULTI_TAXONOMY)
        log = "validate_sloc_limits FAILED\nvalidate_iam_runner_policy FAILED\n"
        results = classify_failures(log, path=p)
        assert len(results) == 1

    def test_genuine_multi_category_failure_via_jobs_json_retained(self, tmp_path):
        """A REAL multi-category failure -- two distinct GitHub Actions steps both reporting
        conclusion=failure -- still emits its distinct bundles (Decision 55: never drop a real
        multi-category failure)."""
        p = write_taxonomy(tmp_path, MULTI_TAXONOMY)
        jobs = [
            {
                "name": "validate",
                "steps": [
                    {"name": "validate_sloc_limits", "conclusion": "failure"},
                    {"name": "validate_iam_runner_policy", "conclusion": "failure"},
                ],
            }
        ]
        results = classify_failures("irrelevant log text", jobs=jobs, path=p)
        assert len(results) == 2
        checks = {r[1] for r in results}
        assert checks == {"validate_sloc_limits", "validate_iam_runner_policy"}
        cats = {r[0] for r in results}
        assert cats == {"sloc_violation", "iam_policy_gap"}

    def test_no_match_returns_taxonomy_fallback(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("nothing matched here", path=p)
        assert isinstance(results, list)
        assert len(results) == 1
        cat, check, src = results[0]
        assert src == "taxonomy_fallback"

    def test_deduplicates_same_function_name(self, tmp_path):
        p = write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        # function name appears twice in log -- should produce exactly one result
        log = "validate_sloc_limits FAILED\nvalidate_sloc_limits also here\n"
        results = classify_failures(log, path=p)
        assert len(results) == 1

    def test_failed_checks_block_enumerates_distinct_categories(self, tmp_path):
        """Collision regression: two distinct failed checks named in the authoritative "Failed
        checks:" block yield two distinct categories. This enumeration is bounded to the
        authoritative block (each entry a genuine, independently-reported failure), so it does
        not reintroduce the banned whole-log substring fan-out this module's docstring warns
        against."""
        p = write_taxonomy(tmp_path, MULTI_TAXONOMY)
        log = (
            "validate_sloc_limits ok (passing mention earlier in the log)\n"
            "Failed checks:\n"
            "  - validate_sloc_limits\n"
            "  - validate_iam_runner_policy\n"
        )
        results = classify_failures(log, path=p)
        assert len(results) == 2
        assert {r[0] for r in results} == {"sloc_violation", "iam_policy_gap"}
        assert {r[1] for r in results} == {"validate_sloc_limits", "validate_iam_runner_policy"}
        assert {r[2] for r in results} == {"validate_failed_checks_block"}

    def test_plural_priority_1_step_name_to_category_match(self, tmp_path):
        """classify_failures' own Priority 1 branch (step_name_to_category), independent of the
        classify_failure() singular fallback -- a failed step whose name IS a
        step_name_to_category key."""
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "function_to_category": {},
            "step_name_to_category": {"Run pytest": "code_regression"},
            "log_pattern_to_category": [],
            "workflows": {"CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"}},
        }
        p = write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"steps": [{"name": "Run pytest", "conclusion": "failure"}]}]
        results = classify_failures("irrelevant log", jobs=jobs, path=p)
        assert results == [("code_regression", "Run pytest", "step_name_to_category")]

    def test_failed_checks_block_absent_preserves_prior_fallback_singular(self, tmp_path):
        """No "Failed checks:" block: classify_failures preserves the pre-fix single-call
        fallback exactly -- distinguishes the new bounded-block enumeration from the old,
        deliberately-banned whole-log substring fan-out (test_multiple_log_text_mentions_no_
        longer_fan_out above stays green, covering the same invariant from the fan-out angle)."""
        p = write_taxonomy(tmp_path, MULTI_TAXONOMY)
        log = "validate_sloc_limits FAILED\nvalidate_iam_runner_policy FAILED\n"
        results = classify_failures(log, path=p)
        assert len(results) == 1
        cat, check, src = results[0]
        assert src == "function_to_category"


class TestJobsJsonPreference:
    """c9b: jobs-JSON step names take priority over log text substring scan."""

    def test_jobs_step_name_wins_over_log_text(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "code_regression", "unknown"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {"Run pytest": "code_regression"},
            "log_pattern_to_category": [],
            "workflows": {"CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"}},
        }
        p = write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"name": "test", "steps": [{"name": "Run pytest", "conclusion": "failure", "number": 1}]}]
        cat, check, src = classify_failure("validate_sloc_limits FAILED in output", jobs=jobs, path=p)
        assert cat == "code_regression"
        assert check == "Run pytest"
        assert src == "step_name_to_category"

    def test_jobs_json_none_falls_back_to_log_text(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["sloc_violation", "unknown"],
            "function_to_category": {"validate_sloc_limits": "sloc_violation"},
            "step_name_to_category": {},
            "log_pattern_to_category": [],
            "workflows": {"CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"}},
        }
        p = write_taxonomy(tmp_path, taxonomy_data)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", jobs=None, path=p)
        assert cat == "sloc_violation"
        assert src == "function_to_category"

    def test_new_categories_in_taxonomy(self, tmp_path):
        taxonomy_data = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "failure_categories": ["test_collection_empty", "gate_escape", "unknown"],
            "function_to_category": {},
            "step_name_to_category": {"pytest --collect-only": "test_collection_empty"},
            "log_pattern_to_category": [],
            "workflows": {"CI": {"tier": "CI", "ci_rca": "watched", "owner": "platform", "rationale": "test fixture"}},
        }
        p = write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"name": "j", "steps": [{"name": "pytest --collect-only", "conclusion": "failure", "number": 1}]}]
        cat, check, src = classify_failure("collected 0 items", jobs=jobs, path=p)
        assert cat == "test_collection_empty"
        assert src == "step_name_to_category"
