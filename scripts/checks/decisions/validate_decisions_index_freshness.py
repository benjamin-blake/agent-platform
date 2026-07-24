"""Decisions index freshness validation (DCG-08, PLAN-dcg-decisions-index)."""

from __future__ import annotations

from scripts.checks import registry
from scripts.decisions_index import check_index_freshness


@registry.register("validate_decisions_index_freshness", owner="platform")
def validate_decisions_index_freshness(failed: list[str]) -> None:
    """Fail if docs/decisions-index.json is missing or has drifted from the live corpus.

    Unlike validate_dependency_graph_freshness (no-op when the export is absent, Decision 80
    lean posture), this index is a REQUIRED committed artifact -- absence is itself a failure
    with a regenerate hint. Pure file derivation, credential-free -- runs in BOTH the --pre
    and full presubmit tiers (placed beside validate_decisions_size, which already gates
    DECISIONS.md in both tiers). Delegates to
    scripts.decisions_index.check_index_freshness (DCG-08 / PLAN-dcg-decisions-index).
    """
    print("\n=== Decisions index freshness ===")
    before = len(failed)
    check_index_freshness(failed)
    if len(failed) == before:
        print("  PASS: decisions index is current.")
