"""Recommendation-relevance contract drift gate (T3.8) (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_rec_relevance_contract", owner="platform")
def validate_rec_relevance_contract(failed: list[str]) -> None:
    """Guard: recommendation-relevance.yaml verdict enum matches rec_relevance.RELEVANCE_VERDICTS (T3.8).

    Checks:
    (a) docs/contracts/recommendation-relevance.yaml parses and has a 'verdicts' list.
    (b) The contract verdicts == rec_relevance.RELEVANCE_VERDICTS (no drift).
    (c) The contract declares no 'columns' or 'fields' (Decision 84: no new Class A columns).
    """
    print("\n=== Recommendation-relevance contract drift gate (T3.8) ===")
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        import yaml as _yaml

        contract_path = _common.ROOT / "docs" / "contracts" / "recommendation-relevance.yaml"
        if not contract_path.exists():
            failed.append("rec-relevance contract: docs/contracts/recommendation-relevance.yaml not found")
            return

        try:
            contract = _yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        except _yaml.YAMLError as exc:
            failed.append(f"rec-relevance contract: parse error: {exc}")
            return

        if not isinstance(contract, dict):
            failed.append("rec-relevance contract: not a YAML mapping")
            return

        if "columns" in contract or "fields" in contract:
            failed.append(
                "rec-relevance contract: declares 'columns' or 'fields' --"
                " Decision 84 violation; relevance is a read-time projection,"
                " not a Class A column set"
            )
            return

        contract_verdicts = set(contract.get("verdicts") or [])
        if not contract_verdicts:
            failed.append("rec-relevance contract: missing or empty 'verdicts' list")
            return

        try:
            import scripts.rec_relevance as _rr

            evaluator_verdicts = set(_rr.RELEVANCE_VERDICTS)
        except Exception as exc:
            failed.append(f"rec-relevance contract: cannot import scripts.rec_relevance: {exc}")
            return

        diff = contract_verdicts ^ evaluator_verdicts
        if diff:
            failed.append(
                f"rec-relevance contract: verdict enum drift -- symmetric diff: {sorted(diff)}. "
                "Reconcile docs/contracts/recommendation-relevance.yaml with scripts/rec_relevance.RELEVANCE_VERDICTS."
            )
        else:
            print("  PASS: recommendation-relevance.yaml verdict enum matches rec_relevance.RELEVANCE_VERDICTS.")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
