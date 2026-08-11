"""Ordered per-tier check registry (Decision 104, dispatch rewired to per-domain manifests by
Decision 169, amending Decision 104's facade re-export mechanism).

``register()`` tags a validate_*/check_* function with its owner metadata -- UNCHANGED, and still
the sole identity/ownership oracle (97 sites, orphan-detection AST walk target). Dispatch and
tier-sequence derivation now come from the 18 per-domain scripts/checks/<domain>/_manifest.py
``Entry`` manifests (grammar: docs/contracts/check-manifest.yaml), never from a facade re-export
block in scripts/validate.py.

Adding a check touches ONLY this package: create scripts/checks/<domain>/<module>.py, decorate it
with ``@register(...)``, and add its ``Entry`` (bare string-literal module=/attr=) to that
domain's ``_manifest.py`` -- scripts/validate.py is never touched.

``resolve(name)`` imports the Entry's defining module and returns ``getattr(module, entry.attr)``
at CALL TIME. The module import may be cached (importlib's own sys.modules cache); the RESOLVED
CALLABLE is NEVER cached, so a test's ``patch("<defining module>.<attr>", ...)`` still intercepts
through a real dispatch pass. ``all_checks()`` imports every manifest-declared module (populating
``_REGISTRY`` via each module's own ``@register`` decorator) before returning the registry -- the
ONLY place this package imports check modules; doing so at THIS module's own import time would be
a genuine circular import, since every check module does ``from scripts.checks import registry``.

Tier dispatch (scripts/validate.py) iterates ``pre_sequence()``/``full_sequence()``; each "check"
step is resolved via ``resolve(name)(failed)`` and each "scaffold" step is resolved against a dict
of closures built locally in main() (they close over per-run locals a generic registry cannot own).
"""

from __future__ import annotations

import dataclasses
import importlib
from typing import Callable

from scripts.checks._schema import Entry
from scripts.checks.ci_guards._manifest import ENTRIES as _CI_GUARDS_ENTRIES
from scripts.checks.contracts._manifest import ENTRIES as _CONTRACTS_ENTRIES
from scripts.checks.decisions._manifest import ENTRIES as _DECISIONS_ENTRIES
from scripts.checks.deps._manifest import ENTRIES as _DEPS_ENTRIES
from scripts.checks.executor._manifest import ENTRIES as _EXECUTOR_ENTRIES
from scripts.checks.hygiene._manifest import ENTRIES as _HYGIENE_ENTRIES
from scripts.checks.iam_tf._manifest import ENTRIES as _IAM_TF_ENTRIES
from scripts.checks.lambda_pkg._manifest import ENTRIES as _LAMBDA_PKG_ENTRIES
from scripts.checks.misc._manifest import ENTRIES as _MISC_ENTRIES
from scripts.checks.ops_governance._manifest import ENTRIES as _OPS_GOVERNANCE_ENTRIES
from scripts.checks.product._manifest import ENTRIES as _PRODUCT_ENTRIES
from scripts.checks.prompts._manifest import ENTRIES as _PROMPTS_ENTRIES
from scripts.checks.prose._manifest import ENTRIES as _PROSE_ENTRIES
from scripts.checks.roadmap._manifest import ENTRIES as _ROADMAP_ENTRIES
from scripts.checks.sloc._manifest import ENTRIES as _SLOC_ENTRIES
from scripts.checks.structural._manifest import ENTRIES as _STRUCTURAL_ENTRIES
from scripts.checks.typing._manifest import ENTRIES as _TYPING_ENTRIES
from scripts.checks.verification._manifest import ENTRIES as _VERIFICATION_ENTRIES

_VALID_OWNERS = ("platform", "trading")


@dataclasses.dataclass(frozen=True)
class Check:
    """A registered check's ownership metadata (separate from Step's per-tier sequence entry).

    `owner` and `product_coupled` are consumer-facing metadata, not dispatch inputs --
    pre_sequence()/full_sequence() dispatch purely by Step.name, so neither field affects
    whether or when a check runs. Today's sole reader is
    tests/checks/registry/test_check_metadata.py::TestOwnerMetadata (the OWNER_EXPECTATIONS
    pinned-owner spot checks plus the platform/product_coupled=False default-floor assertion over
    every other registered check); both fields are set once at each check's `@register(...)` call
    site and are otherwise free for a future owner-scoped reporting/routing consumer.
    """

    name: str
    owner: str = "platform"
    product_coupled: bool = False

    def __post_init__(self) -> None:
        if self.owner not in _VALID_OWNERS:
            raise ValueError(f"Check {self.name!r}: owner must be one of {_VALID_OWNERS}, got {self.owner!r}")


_REGISTRY: dict[str, Check] = {}


def register(name: str, owner: str = "platform", product_coupled: bool = False):
    """Decorator registering a validate_*/check_* function under `name`.

    `name` is the manifest Entry.name / Entry.attr key and the AST-orphan-detection identity --
    normally identical to the decorated function's own __name__.
    """

    def _decorate(fn):
        _REGISTRY[name] = Check(name=name, owner=owner, product_coupled=product_coupled)
        return fn

    return _decorate


def get_check(name: str) -> Check:
    return _REGISTRY[name]


_ALL_ENTRIES: dict[str, Entry] = {
    entry.name: entry
    for entry in (
        *_CI_GUARDS_ENTRIES,
        *_CONTRACTS_ENTRIES,
        *_DECISIONS_ENTRIES,
        *_DEPS_ENTRIES,
        *_EXECUTOR_ENTRIES,
        *_HYGIENE_ENTRIES,
        *_IAM_TF_ENTRIES,
        *_LAMBDA_PKG_ENTRIES,
        *_MISC_ENTRIES,
        *_OPS_GOVERNANCE_ENTRIES,
        *_PRODUCT_ENTRIES,
        *_PROMPTS_ENTRIES,
        *_PROSE_ENTRIES,
        *_ROADMAP_ENTRIES,
        *_SLOC_ENTRIES,
        *_STRUCTURAL_ENTRIES,
        *_TYPING_ENTRIES,
        *_VERIFICATION_ENTRIES,
    )
}


class UnknownCheckError(KeyError):
    """Raised by resolve() when `name` has no manifest Entry in any of the 18 domains."""


def resolve(name: str) -> Callable[..., None]:
    """Import the Entry's defining module and return getattr(module, entry.attr) -- late-bound,
    never caching the resolved callable. See module docstring for the interception contract this
    preserves. Callable[..., None] (not [[list[str]], None]) because a handful of checks accept
    additional keyword-only params beyond `failed` (e.g. validate_plan_documents' plans_dir/
    added_plan_names, used by non-dispatch-path test callers)."""
    entry = _ALL_ENTRIES.get(name)
    if entry is None:
        raise UnknownCheckError(f"no manifest Entry for check {name!r}")
    module = importlib.import_module(entry.module)
    return getattr(module, entry.attr)


def all_checks() -> dict[str, Check]:
    """Import every manifest-declared module (populating _REGISTRY via each module's own
    @register call) and return the complete roster as a MUTABLE dict[str, Check] (never a set --
    see AGENTS.md constraint on ci-rca-taxonomy-covers-registry). The only place this package
    imports check modules -- see module docstring for why registry.py's own import time must not."""
    for entry in _ALL_ENTRIES.values():
        importlib.import_module(entry.module)
    return dict(_REGISTRY)


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str  # "check" | "scaffold"
    name: str
    pre_globs: tuple[str, ...] | None = None  # --pre only; None = ungated, always runs


def _c(name: str, pre_globs: tuple[str, ...] | None = None) -> Step:
    return Step(kind="check", name=name, pre_globs=pre_globs)


def _s(name: str) -> Step:
    return Step(kind="scaffold", name=name)


# --- Derived-sequence skeleton (Decision 169) -----------------------------------------------
#
# Cross-domain order is DERIVED, not hand-listed per check: each segment's domain-block order is
# pinned ONCE below as the domain's FIRST-APPEARANCE order in the pre-Decision-169 sequence
# (OD-0) -- a compact ordering key (one short tuple per segment), not a generated per-check
# roster. Within-domain order is whatever each domain's own scripts/checks/<domain>/_manifest.py
# ENTRIES tuple declares (OD-1/OD-2's cc_limits/sloc_limits/sloc_budget_raises ordering lives
# there). BYTE-PARITY of overall check order is NOT claimed or asserted -- only membership
# (Set identity) and the OD-0..OD-6 invariants (tests/checks/registry/test_sequences.py).

_PRE_DOMAIN_ORDER: tuple[str, ...] = (
    "iam_tf",
    "prompts",
    "hygiene",
    "ci_guards",
    "roadmap",
    "verification",
    "decisions",
    "sloc",
    "structural",
    "prose",
    "misc",
    "typing",
    "contracts",
    "ops_governance",
    "deps",
)

_FULL_SEGMENT_DOMAIN_ORDER: dict[str, tuple[str, ...]] = {
    "full_after_lint": (
        "hygiene",
        "ops_governance",
        "executor",
        "product",
        "misc",
        "ci_guards",
        "sloc",
        "structural",
        "prose",
        "roadmap",
        "decisions",
        "lambda_pkg",
        "verification",
        "typing",
        "contracts",
        "iam_tf",
        "deps",
    ),
    "full_after_unit_tests": ("typing",),
    "full_after_terraform_checks": ("iam_tf",),
    "full_after_dependency_health": ("deps", "prompts", "ci_guards", "contracts"),
    "full_after_ensure_fresh_dq": ("verification",),
}

# The six scaffold anchors (OD-3), in their frozen order, each paired with the full_segment token
# (docs/contracts/check-manifest.yaml) of the check block immediately following it -- None for the
# final anchor, which precedes no further checks.
_FULL_TIER_SKELETON: tuple[tuple[str, str | None], ...] = (
    ("lint", "full_after_lint"),
    ("unit_tests", "full_after_unit_tests"),
    ("terraform_checks", "full_after_terraform_checks"),
    ("dependency_health", "full_after_dependency_health"),
    ("ensure_fresh_dq", "full_after_ensure_fresh_dq"),
    ("precommit_all_files", None),
)

_PRE_TIER_LEADING_SCAFFOLDS: tuple[str, ...] = ("lint", "precommit_changed", "mypy_diff", "pytest_diff")
_PRE_TIER_TRAILING_SCAFFOLDS: tuple[str, ...] = ("verifier_coverage_report", "budget_assertion")


def _entries_by_domain() -> dict[str, list[Entry]]:
    by_domain: dict[str, list[Entry]] = {}
    for entry in _ALL_ENTRIES.values():
        domain = entry.module.split(".")[2]
        by_domain.setdefault(domain, []).append(entry)
    return by_domain


def pre_sequence() -> list[Step]:
    """The --pre (fast) tier, in the exact order main() runs them."""
    by_domain = _entries_by_domain()
    steps = [_s(name) for name in _PRE_TIER_LEADING_SCAFFOLDS]
    for domain in _PRE_DOMAIN_ORDER:
        for entry in by_domain.get(domain, []):
            if entry.pre:
                steps.append(_c(entry.name, pre_globs=entry.pre_globs))
    steps.extend(_s(name) for name in _PRE_TIER_TRAILING_SCAFFOLDS)
    return steps


def full_sequence() -> list[Step]:
    """The full (default, no-flag) tier, in the exact order main() runs them.

    Spans the whole main() default-scope body: run_python_checks, the terraform block,
    validate_iam_runner_policy, run_dependency_checks + validate_requirements, the prompts block,
    ensure_fresh_dq_results, validate_verification_harness, and the all-files precommit run.
    """
    by_domain = _entries_by_domain()
    steps: list[Step] = []
    for scaffold_name, segment in _FULL_TIER_SKELETON:
        steps.append(_s(scaffold_name))
        if segment is None:
            continue
        for domain in _FULL_SEGMENT_DOMAIN_ORDER[segment]:
            for entry in by_domain.get(domain, []):
                if entry.full_segment == segment:
                    steps.append(_c(entry.name))
    return steps
