from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_environment_taxonomy", owner="platform", product_coupled=True)
def validate_environment_taxonomy(failed: list[str]) -> None:
    """Enforce the two-axis vocabulary reservation (docs/contracts/environment-taxonomy.md).

    On changed docs, flag conflation of the PLATFORM environment axis (sandbox/SIT/PROD) with the
    PRODUCT phase axis (research..live_full): a product-phase token used as an "environment", or a
    platform-tier token used as a "phase". Compound tokens (research_sandbox, production_ensemble)
    are safe via word boundaries. The canonical contract, decisions and roadmaps are allowlisted --
    they define the vocabulary and legitimately span both axes; workflow and test files are skipped.
    """
    print("\n=== Environment/phase taxonomy lint ===")
    allowlist_files = {
        "docs/contracts/environment-taxonomy.md",
        "docs/DECISIONS.md",
        "docs/ROADMAP-PRODUCT.yaml",
        "docs/ROADMAP-PLATFORM.yaml",
        "docs/INTENT-ci-cd-architecture.md",
    }
    product_phases = ("research", "backtest_canonical", "paper", "live_small", "live_full")
    platform_tiers = ("sandbox", "sit", "prod", "production", "staging")
    phase_as_env = re.compile(r"\b(" + "|".join(product_phases) + r")[ \t]+environment\b", re.IGNORECASE)
    tier_as_phase = re.compile(r"\b(" + "|".join(platform_tiers) + r")[ \t]+phase\b", re.IGNORECASE)
    errors: list[str] = []
    for rel in _common.get_changed_files():
        if not rel.endswith((".md", ".yaml", ".yml")):
            continue
        if rel in allowlist_files or rel.startswith(".github/") or rel.startswith("tests/"):
            continue
        try:
            text = (_common.ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if phase_as_env.search(line):
                errors.append(f"{rel}:{lineno}: product phase used as an 'environment' (product states are phases)")
            if tier_as_phase.search(line):
                errors.append(f"{rel}:{lineno}: platform tier used as a 'phase' (platform tiers are environments)")
    if errors:
        print("Environment/phase taxonomy violations (see docs/contracts/environment-taxonomy.md):")
        for e in errors:
            print(f"  - {e}")
        failed.append("Environment/phase taxonomy")
    else:
        print("No environment/phase taxonomy violations in changed docs.")
