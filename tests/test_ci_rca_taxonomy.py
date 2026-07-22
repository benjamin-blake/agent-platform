"""Tests for scripts/ci_rca/taxonomy.py (100% coverage)."""

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import scripts.ci_rca.taxonomy as taxonomy_mod  # noqa: E402
from scripts.ci_rca.evidence import _compute_fingerprint, _slugify_workflow  # noqa: E402
from scripts.ci_rca.fingerprint import compute_fingerprint_v2, error_signature_from_log_tail  # noqa: E402
from scripts.ci_rca.taxonomy import (  # noqa: E402
    classify_failure,
    classify_failures,
    enumerate_workflow_names,
    load_taxonomy,
    resolve_workflow_tier,
)

MINIMAL_TAXONOMY = {
    "schema_version": 1,
    "taxonomy_version": 1,
    "function_to_category": {"validate_sloc_limits": "sloc_violation"},
    "log_pattern_to_category": [{"pattern": "ImportError", "category": "dependency_gap", "check_name": "import_error"}],
    "workflow_to_tier": {"CI": "CI", "Deploy": "not_a_gate"},
}


@pytest.fixture(autouse=True)
def reset_cache():
    taxonomy_mod._TAXONOMY_CACHE = None
    yield
    taxonomy_mod._TAXONOMY_CACHE = None


def _write_taxonomy(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "taxonomy.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


_TOP_LEVEL_NAME_RE = re.compile(r"^name:\s*(.+?)\s*$")


def _oracle_workflow_names(workflows_dir: Path) -> set[str]:
    """Independent expected-name oracle: line-scans for the top-level 'name:' key.

    Deliberately avoids yaml.safe_load (the SUT's parse mechanism) so the
    differential retains bug-catching power instead of being circular.
    """
    expected = set()
    for wf_path in Path(workflows_dir).glob("*.yml"):
        for line in wf_path.read_text(encoding="utf-8").splitlines():
            match = _TOP_LEVEL_NAME_RE.match(line)
            if match:
                expected.add(match.group(1).strip("\"'"))
                break
    return expected


class TestLoadTaxonomy:
    def test_happy_path(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        result = load_taxonomy(p)
        assert result["taxonomy_version"] == 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_taxonomy(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [unclosed", encoding="utf-8")
        with pytest.raises(ValueError, match="Malformed taxonomy YAML"):
            load_taxonomy(p)

    def test_non_mapping_raises(self, tmp_path):
        p = tmp_path / "list.yaml"
        p.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_taxonomy(p)

    def test_missing_required_keys_raises(self, tmp_path):
        p = tmp_path / "partial.yaml"
        p.write_text(yaml.dump({"function_to_category": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required keys"):
            load_taxonomy(p)


class TestClassifyFailure:
    def test_function_to_category_primary_match(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_log_pattern_fallback(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("Error: ImportError at line 5", path=p)
        assert cat == "dependency_gap"
        assert check == "import_error"
        assert src == "log_pattern_to_category"

    def test_taxonomy_fallback_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        cat, check, src = classify_failure("something unrecognized", path=p)
        assert cat == "unknown"
        assert check == "unknown"
        assert src == "taxonomy_fallback"

    def test_invalid_regex_skipped(self, tmp_path):
        data = dict(MINIMAL_TAXONOMY)
        data["log_pattern_to_category"] = [
            {"pattern": "[invalid(", "category": "x", "check_name": "y"},
            {"pattern": "ImportError", "category": "dependency_gap", "check_name": "import_error"},
        ]
        p = _write_taxonomy(tmp_path, data)
        cat, check, src = classify_failure("ImportError", path=p)
        assert cat == "dependency_gap"


class TestResolveWorkflowTier:
    def test_ci_maps_to_CI(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("CI", p) == "CI"

    def test_not_a_gate_returns_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("Deploy", p) == "unknown"

    def test_miss_returns_unknown(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        assert resolve_workflow_tier("NotInMap", p) == "unknown"


class TestEnumerateWorkflowNames:
    def test_extracts_names(self, tmp_path):
        wf = tmp_path / "test.yml"
        wf.write_text("name: My Workflow\non:\n  push:\n", encoding="utf-8")
        result = enumerate_workflow_names(tmp_path)
        assert "My Workflow" in result

    def test_skips_unreadable(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        result = enumerate_workflow_names(tmp_path)
        assert isinstance(result, list)

    def test_real_workflows_dir(self):
        names = enumerate_workflow_names()
        assert "CI" in names
        assert set(names) == _oracle_workflow_names(ROOT / ".github" / "workflows")

    def test_drift_immunity_tracks_added_and_removed_workflow(self, tmp_path):
        (tmp_path / "a.yml").write_text("name: Alpha\non:\n  push:\n", encoding="utf-8")
        (tmp_path / "b.yml").write_text("name: Bravo\non:\n  push:\n", encoding="utf-8")
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Bravo"}

        (tmp_path / "c.yml").write_text("name: Charlie\non:\n  push:\n", encoding="utf-8")
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Bravo", "Charlie"}

        (tmp_path / "b.yml").unlink()
        assert set(enumerate_workflow_names(tmp_path)) == {"Alpha", "Charlie"}


MULTI_TAXONOMY = dict(MINIMAL_TAXONOMY)
MULTI_TAXONOMY["function_to_category"] = {
    "validate_sloc_limits": "sloc_violation",
    "validate_iam_runner_policy": "iam_policy_gap",
}

FAILED_CHECKS_TAXONOMY = dict(MINIMAL_TAXONOMY)
FAILED_CHECKS_TAXONOMY["function_to_category"] = {
    "validate_sloc_limits": "sloc_violation",
    "validate_platform_roadmap": "schema_drift",
}


class TestClassifyFailureFailedChecksBlock:
    """rec-2762 / Decision 142 fingerprint-v2 classifier hardening: the authoritative "Failed
    checks:" summary block (validate.py's own list of checks that actually FAILED) must win
    over an arbitrary first-substring-hit against a validate_* name merely mentioned by a
    PASSING check earlier in the same log."""

    _LOG = (
        "=== SLOC ===\n"
        "  PASS: validate_sloc_limits ok\n"
        "=== roadmap ===\n"
        "  FAIL: PLAN-x.yaml: closes_criteria bad\n"
        "\n"
        "=== Validation Summary (scope: all) ===\n"
        "Failed checks:\n"
        "  - validate_platform_roadmap\n"
    )

    def test_failed_checks_block_wins_over_passing_mention(self, tmp_path):
        """Fragmentation regression: a PASSING validate_sloc_limits mention earlier in the log
        must not win over the authoritative block naming validate_platform_roadmap as the
        check that actually failed (pre-fix behaviour returned sloc_violation here)."""
        p = _write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        cat, check, src = classify_failure(self._LOG, path=p)
        assert cat == "schema_drift"
        assert check == "validate_platform_roadmap"
        assert src == "validate_failed_checks_block"

    def test_failed_checks_block_classification_is_stable_across_calls(self, tmp_path):
        """The same failure classified twice must yield an identical category -- the
        fragmentation bug (rec-2749 vs rec-2762) came from the SAME underlying failure landing
        on different categories across runs because the substring scan's winner depends on
        func_map iteration order and which validate_* names happen to appear that run."""
        p = _write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        first = classify_failure(self._LOG, path=p)
        second = classify_failure(self._LOG, path=p)
        assert first == second == ("schema_drift", "validate_platform_roadmap", "validate_failed_checks_block")

    def test_no_failed_checks_block_falls_back_to_substring_scan(self, tmp_path):
        """No "Failed checks:" header present -- the prior substring-scan behaviour for
        non-validate-summary logs is unchanged."""
        p = _write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_failed_checks_block_with_unmapped_check_falls_through(self, tmp_path):
        """A "Failed checks:" block naming a check absent from function_to_category falls
        through to the lower-priority substring scan rather than erroring or dropping the
        classification entirely."""
        p = _write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        log = "validate_sloc_limits ok\nFailed checks:\n  - validate_unmapped_check\n"
        cat, check, src = classify_failure(log, path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"


class TestClassifyFailures:
    def test_single_match_returns_list_of_one(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
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
        p = _write_taxonomy(tmp_path, MULTI_TAXONOMY)
        log = "validate_sloc_limits FAILED\nvalidate_iam_runner_policy FAILED\n"
        results = classify_failures(log, path=p)
        assert len(results) == 1

    def test_genuine_multi_category_failure_via_jobs_json_retained(self, tmp_path):
        """A REAL multi-category failure -- two distinct GitHub Actions steps both reporting
        conclusion=failure -- still emits its distinct bundles (Decision 55: never drop a real
        multi-category failure)."""
        p = _write_taxonomy(tmp_path, MULTI_TAXONOMY)
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
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
        results = classify_failures("nothing matched here", path=p)
        assert isinstance(results, list)
        assert len(results) == 1
        cat, check, src = results[0]
        assert src == "taxonomy_fallback"

    def test_deduplicates_same_function_name(self, tmp_path):
        p = _write_taxonomy(tmp_path, MINIMAL_TAXONOMY)
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
        p = _write_taxonomy(tmp_path, MULTI_TAXONOMY)
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

    def test_failed_checks_block_absent_preserves_prior_fallback_singular(self, tmp_path):
        """No "Failed checks:" block: classify_failures preserves the pre-fix single-call
        fallback exactly -- distinguishes the new bounded-block enumeration from the old,
        deliberately-banned whole-log substring fan-out (test_multiple_log_text_mentions_no_
        longer_fan_out above stays green, covering the same invariant from the fan-out angle)."""
        p = _write_taxonomy(tmp_path, MULTI_TAXONOMY)
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
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
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
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
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
            "workflow_to_tier": {"CI": "CI"},
        }
        p = _write_taxonomy(tmp_path, taxonomy_data)
        jobs = [{"name": "j", "steps": [{"name": "pytest --collect-only", "conclusion": "failure", "number": 1}]}]
        cat, check, src = classify_failure("collected 0 items", jobs=jobs, path=p)
        assert cat == "test_collection_empty"
        assert src == "step_name_to_category"


class TestConvergenceMarkerClassification:
    """Real-runtime-path classification for the terraform-apply-sandbox CONVERGENCE_* /
    STARVED markers (PLAN-ci-rca-convergence-dedup). Uses the REAL config/ci_rca_taxonomy.yaml
    (path=None), not a synthetic minimal taxonomy -- grounded against the actual registered
    rules, not a circular fixture."""

    _PRECONDITION_STEP = "Convergence precondition (refuse on red record -- sole hard block)"
    _REVIEW_STEP = "Subagent plan review (digest-fed, JSON-classified)"

    def _jobs(self, step_name: str) -> list[dict]:
        # Unmapped step name (no step_name_to_category / function_to_category entry for the
        # precondition/review steps -- Risk 1/3 shadowing avoidance) so classify_failures falls
        # through to the single-log-text classify_failure() call: exercises the real
        # jobs-present-but-step-unmapped shape, not a circular test.
        return [{"name": "apply", "steps": [{"name": step_name, "conclusion": "failure"}]}]

    def test_convergence_red_classifies_to_convergence_refused(self):
        log = "::error::CONVERGENCE_RED main is non-converged at commit ed22aa46; apply REFUSED"
        results = classify_failures(log, jobs=self._jobs(self._PRECONDITION_STEP), path=None)
        assert len(results) == 1
        cat, check, src = results[0]
        assert cat == "convergence_refused"
        assert src == "log_pattern_to_category"

    def test_convergence_read_error_classifies_to_convergence_read_error(self):
        log = "::error::CONVERGENCE_READ_ERROR could not read the convergence record; failing CLOSED"
        cat, check, src = classify_failure(log, jobs=self._jobs(self._PRECONDITION_STEP), path=None)
        assert cat == "convergence_read_error"
        assert src == "log_pattern_to_category"

    def test_convergence_parse_error_also_classifies_to_convergence_read_error(self):
        log = "::error::CONVERGENCE_PARSE_ERROR convergence record exists but could not be parsed as JSON"
        cat, check, src = classify_failure(log, jobs=self._jobs(self._PRECONDITION_STEP), path=None)
        assert cat == "convergence_read_error"

    def test_subagent_starved_classifies_to_subagent_starved(self):
        log = "Subagent STARVED (max-turns/no-verdict/API-exhausted) after the same-budget retry"
        cat, check, src = classify_failure(log, jobs=self._jobs(self._REVIEW_STEP), path=None)
        assert cat == "subagent_starved"
        assert src == "log_pattern_to_category"

    def test_review_succeeded_starved_marker_does_not_alias(self):
        """REVIEW_STARVED lives in a SUCCEEDED step (:495), excluded from `gh run view
        --log-failed`; its literal ('Subagent reviewer STARVED') does not contain the
        FAILED-step marker substring 'Subagent STARVED' and must not classify as such."""
        log = (
            "Subagent reviewer STARVED (max-turns/no-verdict/API-exhausted after the "
            "same-budget retry): NOT overwriting the convergence record"
        )
        cat, check, src = classify_failure(log, jobs=None, path=None)
        assert cat != "subagent_starved"

    def test_revise_does_not_alias_starved(self):
        log = "Subagent returned REVISE; failing closed."
        cat, check, src = classify_failure(log, jobs=self._jobs(self._REVIEW_STEP), path=None)
        assert cat != "subagent_starved"

    def test_no_longer_degenerate_unknown_unknown(self):
        """Prior bug: an unclassified sandbox failure collapsed to unknown/unknown (833c78f8...).
        The taxonomy fix means the real CONVERGENCE_RED marker never resolves to 'unknown'."""
        log = "::error::CONVERGENCE_RED main is non-converged at commit x; apply REFUSED"
        cat, check, src = classify_failure(log, jobs=None, path=None)
        assert cat != "unknown"


class TestConvergenceFingerprintDistinctness:
    def test_distinct_fingerprints_across_convergence_starved_environment(self):
        slug = _slugify_workflow("terraform-apply-sandbox")
        fp_refused = _compute_fingerprint(slug, "convergence_refused", "convergence_refused")
        fp_starved = _compute_fingerprint(slug, "subagent_starved", "subagent_starved")
        fp_env = _compute_fingerprint(slug, "terraform_error", "environment")
        assert len({fp_refused, fp_starved, fp_env}) == 3

    def test_rec_2743_rec_2762_collision_pair_now_distinct_at_fingerprint_v2_level(self):
        """Historical false-merge (rec-2762 plan investigation, Decision 142): rec-2743 (a DQ
        'automatable' hard-gate failure, from the "Validate full tier (ruff, mypy, pytest, DQ
        runner, verifier harness)" job's separate Verification Harness step) and rec-2762 (a
        validate_platform_roadmap closes_criteria failure) both classified to
        sloc_violation/validate_sloc_limits under the pre-fix whole-log substring scan -- both
        logs mention validate_sloc_limits from an earlier PASSING validate.py step -- and
        collided on the exact same fingerprint (446f8fe1...). Log text reconstructed from each
        rec's context_v2_json proximate_cause (no raw CI log retained). Proves the hardened
        classifier, run against the REAL config/ci_rca_taxonomy.yaml, now resolves the pair to
        DISTINCT compute_fingerprint_v2 hashes."""
        rec_2762_log = (
            "=== SLOC ===\n"
            "  PASS: validate_sloc_limits ok\n"
            "=== roadmap ===\n"
            "  FAIL: PLAN-ducklake-maintenance-smoke-split.yaml: closes_criteria entry has no "
            "':' or resolves to an unknown tier_item id (5 FAIL rows)\n"
            "\n"
            "=== Validation Summary (scope: all) ===\n"
            "Failed checks:\n"
            "  - validate_platform_roadmap\n"
        )
        # rec-2743's failure is the DQ/Verification-Harness step, a distinct CI step from the
        # validate.py invocation (which PASSED in that same job) -- so its log has no "Failed
        # checks:" header, and the fix leaves this classification exactly as before.
        rec_2743_log = (
            "=== SLOC ===\n"
            "  PASS: validate_sloc_limits ok\n"
            "=== Verification Harness ===\n"
            "[FAIL] (HARD_GATE) DataQualityVerifier: Data quality FAIL: 0 hard-gated, 1 failed, "
            "0 errored, 1 warned.\n"
            "ops_recommendations.automatable [not_null] FAIL (2 violation(s))\n"
        )
        slug = _slugify_workflow("Validate full tier (ruff, mypy, pytest, DQ runner, verifier harness)")

        cat_2762, check_2762, _ = classify_failure(rec_2762_log, path=None)
        cat_2743, check_2743, _ = classify_failure(rec_2743_log, path=None)
        assert cat_2762 == "schema_drift"
        assert cat_2743 == "sloc_violation"

        sig_2762 = error_signature_from_log_tail(rec_2762_log, check_2762)
        sig_2743 = error_signature_from_log_tail(rec_2743_log, check_2743)
        fp_2762 = compute_fingerprint_v2(slug, cat_2762, sig_2762)
        fp_2743 = compute_fingerprint_v2(slug, cat_2743, sig_2743)
        assert fp_2762 != fp_2743
