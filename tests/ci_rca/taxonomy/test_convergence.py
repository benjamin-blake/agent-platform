"""Tests for terraform-apply-sandbox CONVERGENCE_*/STARVED marker classification and the legacy
v1 fingerprint's distinctness across those categories. Split from the former flat
tests/test_ci_rca_taxonomy.py (ci-rca-evidence-fidelity, Decision 128 decompose-by-default).
"""

from scripts.ci_rca.evidence import _compute_fingerprint, _slugify_workflow
from scripts.ci_rca.fingerprint import compute_fingerprint_v2, error_signature_from_log_tail
from scripts.ci_rca.taxonomy import classify_failure, classify_failures


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
