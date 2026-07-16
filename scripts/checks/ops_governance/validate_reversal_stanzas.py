"""Reversal-conditions stanza well-formedness gate (audit SEQ-02 follow-on to Decision 133)."""

from __future__ import annotations

from scripts.checks import registry
from scripts.preflight.decision_conditions import evaluate


@registry.register("validate_reversal_stanzas", owner="platform")
def validate_reversal_stanzas(failed: list[str]) -> None:
    """Gate stanza WELL-FORMEDNESS only.

    Never gates on review date or fired conditions -- that stays surfacing-only, owned by
    scripts.preflight.decision_conditions.preflight_bucket() (session preflight + the orient
    skill's Status Digest). A kind: manual condition with no predicate/params is well-formed
    (Decision 133's platform-mvp-closes condition ships id/kind/description only) -- the shared
    evaluate() well-formedness rules never require predicate/params on a manual condition.
    """
    print("\n=== Reversal-conditions stanza well-formedness gate (SEQ-02) ===")
    try:
        results = evaluate()
    except Exception as exc:  # noqa: BLE001 -- fail loud at the call site, never silently pass
        msg = f"validate_reversal_stanzas: evaluate() raised: {exc}"
        failed.append(msg)
        print(f"  FAIL: {msg}")
        return

    malformed = [r for r in results if r.state == "MALFORMED"]
    if not malformed:
        print(f"  PASS: {len(results)} monitored reversal-conditions stanza(s), all well-formed.")
        return

    for r in malformed:
        msg = f"Decision {r.decision_id}: MALFORMED reversal-conditions stanza -- {r.error}"
        failed.append(msg)
        print(f"  FAIL: {msg}")
