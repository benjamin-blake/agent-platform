"""Tests for validate_reversal_stanzas() -- the SEQ-02 stanza well-formedness gate.

Self-contained (Decision 131 no-cross-test-import): patches
scripts.checks.ops_governance.validate_reversal_stanzas.evaluate directly with canned
DecisionConditionState results rather than importing another test module's fixtures.
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.checks.ops_governance.validate_reversal_stanzas import validate_reversal_stanzas
from scripts.preflight.decision_conditions import DecisionConditionState


class TestValidateReversalStanzasWellFormed:
    def test_well_formed_tree_appends_no_failure(self) -> None:
        canned = [
            DecisionConditionState(decision_id=133, state="not-due", review_by="2026-09-30"),
            DecisionConditionState(decision_id=901, state="manual-review-due", review_by="2020-01-01"),
        ]
        with patch(
            "scripts.checks.ops_governance.validate_reversal_stanzas.evaluate",
            return_value=canned,
        ):
            failed: list[str] = []
            validate_reversal_stanzas(failed)
        assert failed == [], f"Expected no failure on a well-formed tree, got: {failed}"

    def test_manual_condition_without_predicate_params_is_not_flagged(self) -> None:
        """A kind: manual state (no predicate/params, mirroring Decision 133's
        platform-mvp-closes condition) must never itself be treated as malformed by this gate --
        the manual/repo_state optionality is validated inside evaluate(), and a non-MALFORMED
        state from evaluate() must pass through untouched here."""
        canned = [DecisionConditionState(decision_id=133, state="not-due", review_by="2026-09-30")]
        with patch(
            "scripts.checks.ops_governance.validate_reversal_stanzas.evaluate",
            return_value=canned,
        ):
            failed: list[str] = []
            validate_reversal_stanzas(failed)
        assert failed == []


class TestValidateReversalStanzasMalformed:
    def test_single_malformed_entry_appends_one_failure_naming_the_decision(self) -> None:
        canned = [
            DecisionConditionState(decision_id=133, state="not-due", review_by="2026-09-30"),
            DecisionConditionState(decision_id=905, state="MALFORMED", error="stanza 'decision: 999' mismatch"),
        ]
        with patch(
            "scripts.checks.ops_governance.validate_reversal_stanzas.evaluate",
            return_value=canned,
        ):
            failed: list[str] = []
            validate_reversal_stanzas(failed)
        assert len(failed) == 1
        assert "905" in failed[0]
        assert "MALFORMED" in failed[0]

    def test_one_failure_per_malformed_variant(self) -> None:
        canned = [
            DecisionConditionState(decision_id=906, state="MALFORMED", error="unclosed fence"),
            DecisionConditionState(decision_id=907, state="MALFORMED", error="unregistered predicate"),
            DecisionConditionState(decision_id=908, state="MALFORMED", error="unknown kind"),
        ]
        with patch(
            "scripts.checks.ops_governance.validate_reversal_stanzas.evaluate",
            return_value=canned,
        ):
            failed: list[str] = []
            validate_reversal_stanzas(failed)
        assert len(failed) == 3
        assert "906" in failed[0]
        assert "907" in failed[1]
        assert "908" in failed[2]

    def test_evaluate_raising_fails_loud_not_silently(self) -> None:
        """evaluate() raising must append a failure -- never silently pass a broken tree
        (Decision 55: fail loud at the call site)."""
        with patch(
            "scripts.checks.ops_governance.validate_reversal_stanzas.evaluate",
            side_effect=RuntimeError("boom"),
        ):
            failed: list[str] = []
            validate_reversal_stanzas(failed)
        assert len(failed) == 1
        assert "boom" in failed[0]


class TestValidateReversalStanzasRealTree:
    def test_real_decisions_md_is_well_formed(self) -> None:
        """No mocking -- runs the real evaluate() over the real DECISIONS.md/DECISIONS_ARCHIVE.md.
        Confirms the current committed tree (including Decision 133 and Decision 134) is clean."""
        failed: list[str] = []
        validate_reversal_stanzas(failed)
        assert failed == [], f"Real DECISIONS.md tree has malformed reversal-conditions stanza(s): {failed}"
