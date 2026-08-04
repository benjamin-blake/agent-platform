"""Tests for Priority 3 (_classify_via_failed_checks_block): the authoritative "Failed checks:"
summary block. Split from the former flat tests/test_ci_rca_taxonomy.py (ci-rca-evidence-fidelity,
Decision 128 decompose-by-default).
"""

import scripts.ci_rca.taxonomy as taxonomy_mod
from scripts.ci_rca.taxonomy import classify_failure
from tests.fixtures.ci_rca.taxonomy_data import FAILED_CHECKS_TAXONOMY, write_taxonomy


class TestClassifyFailureFailedChecksBlockRealLabels:
    """ci-rca-evidence-fidelity: Priority 3 (_classify_via_failed_checks_block) keys on
    validate_* FUNCTION names, but validate.py's real failed.append() calls emit human-readable
    LABELS (e.g. "Coverage below 100%" -- scripts/checks/misc/validate_test_coverage.py:81;
    "Platform roadmap schema validation" -- scripts/checks/roadmap/validate_platform_roadmap.py:46),
    never the function name. This class's fixtures use REAL labels and prove Priority 3
    correctly finds NO match against them (falls through the ladder) -- Priority 0 (the
    validation-result attribution artifact, tests/ci_rca/taxonomy/test_priority_zero_and_refusal.py)
    is the mechanism that actually resolves this correctly in production. Supersedes the pre-fix
    fixtures here, which fed synthetic function-name block entries validate.py never emits -- a
    vacuous test of a branch that has never fired against real output."""

    _REAL_LABEL_LOG = (
        "=== SLOC ===\n"
        "  PASS: validate_sloc_limits ok\n"
        "=== roadmap ===\n"
        "  FAIL: PLAN-x.yaml: closes_criteria bad\n"
        "\n"
        "=== Validation Summary (scope: all) ===\n"
        "Failed checks:\n"
        "  - Platform roadmap schema validation\n"
    )

    def test_real_label_never_matches_priority_3_function_name_keying(self):
        result = taxonomy_mod._classify_via_failed_checks_block(
            self._REAL_LABEL_LOG, {"validate_platform_roadmap": "schema_drift"}
        )
        assert result is None

    def test_real_label_log_falls_through_to_substring_scan(self, tmp_path):
        """Priority 3 contributes nothing for a real label; the passing SLOC mention wins via
        the substring scan instead -- exactly the rec-2958 false-positive shape this plan exists
        to remove for the REAL production path (Priority 0, see below)."""
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        cat, check, src = classify_failure(self._REAL_LABEL_LOG, path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_no_failed_checks_block_falls_back_to_substring_scan(self, tmp_path):
        """No "Failed checks:" header present -- the prior substring-scan behaviour for
        non-validate-summary logs is unchanged."""
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        cat, check, src = classify_failure("validate_sloc_limits FAILED", path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"

    def test_failed_checks_block_with_unmapped_real_label_falls_through(self, tmp_path):
        """A "Failed checks:" block naming a real label absent from function_to_category falls
        through to the lower-priority substring scan rather than erroring or dropping the
        classification entirely."""
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        log = "validate_sloc_limits ok\nFailed checks:\n  - Some unmapped human label\n"
        cat, check, src = classify_failure(log, path=p)
        assert cat == "sloc_violation"
        assert check == "validate_sloc_limits"
        assert src == "function_to_category"


class TestClassifyFailureFailedChecksBlockFunctionNameMatchCoverageOnly:
    """Coverage-only: Priority 3's "match" branch is unreachable with real validate.py output
    (see the real-label class above), but the code path itself still exists (a future check
    could legitimately append its own function name as a label) -- exercised directly against
    the helper rather than via the priority ladder, so it is never mistaken for a
    production-fidelity assertion."""

    def test_function_name_shaped_entry_matches_directly(self):
        result = taxonomy_mod._classify_via_failed_checks_block(
            "Failed checks:\n  - validate_platform_roadmap\n", {"validate_platform_roadmap": "schema_drift"}
        )
        assert result == ("schema_drift", "validate_platform_roadmap", "validate_failed_checks_block")

    def test_unmapped_function_name_returns_none(self):
        result = taxonomy_mod._classify_via_failed_checks_block(
            "Failed checks:\n  - validate_unmapped\n", {"validate_platform_roadmap": "schema_drift"}
        )
        assert result is None

    def test_classification_is_stable_across_calls(self, tmp_path):
        """The same failure classified twice must yield an identical category -- the
        fragmentation bug (rec-2749 vs rec-2762) came from the SAME underlying failure landing
        on different categories across runs because the substring scan's winner depends on
        func_map iteration order and which validate_* names happen to appear that run."""
        log = (
            "=== SLOC ===\n"
            "  PASS: validate_sloc_limits ok\n"
            "\n"
            "=== Validation Summary (scope: all) ===\n"
            "Failed checks:\n"
            "  - validate_platform_roadmap\n"
        )
        p = write_taxonomy(tmp_path, FAILED_CHECKS_TAXONOMY)
        first = classify_failure(log, path=p)
        second = classify_failure(log, path=p)
        assert first == second == ("schema_drift", "validate_platform_roadmap", "validate_failed_checks_block")
