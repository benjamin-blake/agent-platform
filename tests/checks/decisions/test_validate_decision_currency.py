"""Tests for scripts/checks/decisions/validate_decision_currency.py (PLAN-decision-corpus-currency,
rec-3055/rec-3056).

Builds a synthetic root tree under tmp_path per fixture and passes it via the check's root=
injection seam -- no tracked file (docs/DECISIONS.md included) is ever mutated (round-2 finding,
actioned: an earlier draft's mutation test could not restore on the raise path and is gone).

VP steps 2 and 4 grep for the two class names below (TestInvariantsFailWhenViolated,
TestContractVocabularyIsCausal) and run them as pytest node ids -- an existence guard, since
`pytest -k` matching nothing exits 0. Keep both names exact.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.checks.decisions.validate_decision_currency import validate_decision_currency

_DECISION_ENTRY_YAML = "currency:\n  values: [current, amended, superseded_pointer, superseded_compacted]\n"

_SKILL_HEALTHY = (
    "7. **Currency filter.** `superseded_compacted` is the ONLY value that demotes to RELATED. "
    "`superseded_pointer` is NEVER filtered and NEVER severity-reduced.\n"
)

_DEFAULT_DECISIONS_MD = (
    "## Decision 1: Alpha (Decided)\n\n**Status:** Decided\n\n**Date:** 2026-01-01\n\n**Decision:** X.\n\n---\n"
)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_tree(
    tmp_path: Path,
    *,
    decisions_md: str = _DEFAULT_DECISIONS_MD,
    archive_md: str = "",
    index_decisions: list | None = None,
    contract_yaml: str = _DECISION_ENTRY_YAML,
    skill_text: str = _SKILL_HEALTHY,
) -> Path:
    root = tmp_path
    _write(root, "docs/DECISIONS.md", decisions_md)
    _write(root, "docs/DECISIONS_ARCHIVE.md", archive_md)
    if index_decisions is None:
        index_decisions = [{"number": 1, "live": True, "currency": "current"}]
    _write(root, "docs/decisions-index.json", json.dumps({"decisions": index_decisions}))
    _write(root, "docs/contracts/decision-entry.yaml", contract_yaml)
    _write(root, ".claude/skills/decision-scout/SKILL.md", skill_text)
    return root


class TestValidateDecisionCurrencyHealthyTree:
    """The passing counterpart to TestInvariantsFailWhenViolated below: a synthetic tree where
    every invariant genuinely holds produces zero failures."""

    def test_passes_when_every_invariant_holds(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert failed == []


class TestLoaderEdgeCases:
    """Coverage for the defensive load/validate branches in _load_index_decisions,
    _load_currency_vocabulary, and _check_i5 -- exercised through the public entry point, so
    both the loader's own FAIL and validate_decision_currency's early return fire together."""

    def test_missing_index_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        (root / "docs" / "decisions-index.json").unlink()
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("not found" in f for f in failed), failed

    def test_unreadable_index_json_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        _write(root, "docs/decisions-index.json", "not valid json {{{")
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("could not parse" in f for f in failed), failed

    def test_index_without_decisions_list_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        _write(root, "docs/decisions-index.json", json.dumps({"metadata": {}}))
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("no 'decisions' list" in f for f in failed), failed

    def test_missing_contract_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        (root / "docs" / "contracts" / "decision-entry.yaml").unlink()
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("not found" in f for f in failed), failed

    def test_unparseable_contract_yaml_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path, contract_yaml="currency: [unterminated")
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("could not parse" in f for f in failed), failed

    def test_contract_without_currency_values_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path, contract_yaml="currency: {}\n")
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("no currency.values list" in f for f in failed), failed

    def test_missing_skill_file_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path)
        (root / ".claude" / "skills" / "decision-scout" / "SKILL.md").unlink()
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I5" in f and "not found" in f for f in failed), failed


class TestInvariantsFailWhenViolated:
    """One deliberately-FAILING fixture per invariant (I1-I5)."""

    def test_i1_status_superseded_without_pointer_fails(self, tmp_path: Path) -> None:
        # Load-bearing fixture: a live entry carries '**Status:** Superseded' with NO resolvable
        # pointer (a malformed compaction) -- is_compacted_stub is False, so the index deriving
        # anything other than 'superseded_compacted' must fail I1.
        decisions_md = (
            "## Decision 1: Alpha (Superseded)\n\n**Status:** Superseded\n\n**Date:** 2026-01-01\n\n"
            "**Decision:** No pointer here.\n\n---\n"
        )
        root = _build_tree(
            tmp_path,
            decisions_md=decisions_md,
            index_decisions=[{"number": 1, "live": True, "currency": "current"}],
        )
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I1" in f for f in failed), failed

    def test_i2_currency_present_on_archive_row_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path, index_decisions=[{"number": 1, "live": False, "currency": "current"}])
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I2" in f for f in failed), failed

    def test_i2_missing_currency_on_live_row_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path, index_decisions=[{"number": 1, "live": True}])
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I2" in f for f in failed), failed

    def test_i3_currency_outside_vocabulary_fails(self, tmp_path: Path) -> None:
        root = _build_tree(
            tmp_path,
            index_decisions=[{"number": 1, "live": True, "currency": "not_a_real_token"}],
        )
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I3" in f for f in failed), failed

    def test_i4_reversed_status_outside_grandfather_fails(self, tmp_path: Path) -> None:
        decisions_md = (
            "## Decision 1: Alpha (Reversed)\n\n**Status:** Reversed -- 2026-01-01\n\n**Date:** 2026-01-01\n\n"
            "**Decision:** X.\n\n---\n"
        )
        root = _build_tree(
            tmp_path,
            decisions_md=decisions_md,
            index_decisions=[{"number": 1, "live": True, "currency": "current"}],
        )
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I4" in f for f in failed), failed

    def test_i5_missing_consumer_contract_clause_fails(self, tmp_path: Path) -> None:
        root = _build_tree(tmp_path, skill_text="No currency clauses here at all.\n")
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I5" in f for f in failed), failed

    def test_i5_retired_status_prose_fallback_present_fails(self, tmp_path: Path) -> None:
        skill_text = _SKILL_HEALTHY + "Only flag decisions whose status is active.\n"
        root = _build_tree(tmp_path, skill_text=skill_text)
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I5" in f for f in failed), failed


class TestContractVocabularyIsCausal:
    """Proves the check reads its vocabulary from docs/contracts/decision-entry.yaml at check
    time, never a hardcoded or generator-sourced copy: a contract whose currency.values omits a
    token the corpus/index actually emits must fail."""

    def test_check_fails_when_contract_vocabulary_omits_emitted_token(self, tmp_path: Path) -> None:
        truncated_contract = "currency:\n  values: [current, amended, superseded_compacted]\n"  # omits superseded_pointer
        decisions_md = (
            "## Decision 1: Alpha (Decided)\n\n**Status:** Decided\n\n**Date:** 2026-01-01\n\n"
            "**Decision:** X.\n\n**Superseded by: Decision 2**\n\n---\n"
            "## Decision 2: Beta (Decided)\n\n**Status:** Decided\n\n**Date:** 2026-01-01\n\n**Decision:** Y.\n\n---\n"
        )
        root = _build_tree(
            tmp_path,
            decisions_md=decisions_md,
            contract_yaml=truncated_contract,
            index_decisions=[
                {"number": 1, "live": True, "currency": "superseded_pointer"},
                {"number": 2, "live": True, "currency": "current"},
            ],
        )
        failed: list[str] = []
        validate_decision_currency(failed, root=root)
        assert any("I3" in f for f in failed), failed
