"""Shared Entry dataclass for the per-domain check manifests (scripts/checks/<domain>/_manifest.py).

Field grammar, the bare-string-literal rule, the two-field (module/attr, never a combined
"module:attr" string) rule, and the allowed `full_segment` token set are declared in
docs/contracts/check-manifest.yaml -- this module carries no second copy of that grammar.
scripts/checks/deps/validate_check_manifests.py is the registered evaluator that enforces it.
"""

from __future__ import annotations

import dataclasses

# The full-tier segment tokens a manifest Entry.full_segment may declare (or None if the check is
# not in the full tier). Must equal docs/contracts/check-manifest.yaml's declared segment token
# set -- asserted by scripts/checks/deps/validate_check_manifests.py, never restated by import.
SEGMENT_TOKENS: frozenset[str] = frozenset(
    {
        "full_after_lint",
        "full_after_unit_tests",
        "full_after_terraform_checks",
        "full_after_dependency_health",
        "full_after_ensure_fresh_dq",
    }
)


@dataclasses.dataclass(frozen=True)
class Entry:
    """One registered check's manifest entry.

    `module`/`attr` are TWO SEPARATE fields, never a combined "module:attr" string -- see
    docs/contracts/check-manifest.yaml. `pre`/`pre_globs` declare --pre tier membership;
    `full_segment` declares full-tier membership as one of SEGMENT_TOKENS (or None if the check
    does not run in the full tier). A check absent from both tiers is a declared unsequenced entry
    (today's sole instance: validate_terraform_try).
    """

    name: str
    module: str
    attr: str
    owner: str = "platform"
    product_coupled: bool = False
    pre: bool = False
    pre_globs: tuple[str, ...] | None = None
    full_segment: str | None = None
