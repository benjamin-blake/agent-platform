"""Structural-size classification + measurement engine (SGE-01/SGE-02/SGE-04, Decision 166).

Shared by validate_structural_size_limits and validate_structural_size_budget_raises so
their scan roots can never drift apart (the scripts/checks/sloc/_shared.py::
iter_gated_py_files precedent). Layered first-match-wins classification: exclusions, then
the provenance override (generated_pinned membership or a narrow do-not-edit banner in the
first 10 lines), then the ordered classes:[] directory+extension globs, then the mandatory
residual default. Field semantics for the class table, the counting rule, the glob grammar
and the long-line threshold live in config/structural_size_budgets.yaml (Decision 86/127
routing), not here.

Imports ROOT from scripts.checks._common and never recomputes it
(tests/test_checks_registry.py::TestNoLocalRootRecomputation enforces this repo-wide).
"""

from __future__ import annotations

import fnmatch
import re
from typing import Iterator

import yaml

from scripts.checks import _common

_REGISTRY_REL_PATH = "config/structural_size_budgets.yaml"

# Narrow provenance banner: a self-description of authorship ("generated") is not a
# machine-ownership claim (audit Q8 seed 1) -- a loose regex matched
# audits/size-governance-expansion-3dee4a5.yaml and docs/plans/PLAN-dcg-decisions-index.yaml
# on the bare word "generated" in prose. This pattern requires the exact
# "GENERATED -- DO NOT EDIT" phrase and is scanned only over the file's first 10 lines.
_BANNER_RE = re.compile(r"GENERATED\s*--\s*DO NOT EDIT")
_BANNER_SCAN_LINES = 10

_registry_cache: dict[str, dict] = {}


def load_registry() -> dict:
    """Cached yaml.safe_load of config/structural_size_budgets.yaml, memoized per
    _common.ROOT value (mirrors scripts.checks._marker_guard.load_decision_bodies's
    per-ROOT cache -- a patched ROOT in a test gets its own fresh parse)."""
    root_key = str(_common.ROOT)
    cached = _registry_cache.get(root_key)
    if cached is not None:
        return cached

    path = _common.ROOT / _REGISTRY_REL_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _registry_cache[root_key] = data
    return data


def effective_lines(text: str) -> int:
    """PINNED counting rule: non-blank lines whose first non-whitespace character is not
    '#'. Applied verbatim to every class, no per-language comment handling."""
    return len([ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")])


def longest_line(text: str) -> int:
    """Character count of the longest raw line (the long-line companion's own unit)."""
    lines = text.splitlines()
    return max((len(ln) for ln in lines), default=0)


def _is_excluded(rel: str, exclusions: dict) -> bool:
    suffixes = tuple(exclusions.get("suffixes") or ())
    if rel.endswith(suffixes):
        return True
    dirs = set(exclusions.get("dirs") or ())
    parts = rel.split("/")
    return any(part in dirs for part in parts[:-1])


def _has_banner(text: str) -> bool:
    head = "\n".join(text.splitlines()[:_BANNER_SCAN_LINES])
    return bool(_BANNER_RE.search(head))


def _read_text(rel: str) -> str:
    full_path = _common.ROOT / rel
    if not full_path.exists():
        return ""
    return full_path.read_text(encoding="utf-8", errors="replace")


def classify_path(rel: str, text: str | None = None) -> str:
    """Layered first-match-wins classification of one repo-relative path.

    `text` is read from disk when omitted (needed only for the provenance banner test --
    generated_pinned membership and every glob-based class need no file read at all, so a
    hypothetical, not-yet-existing path classifies correctly too). Returns "excluded" for
    a suffix/vendored-dir exclusion, "generated" for the provenance override, one of the
    ten remaining named class slugs on a glob match, or "residual" as the mandatory
    terminal default.
    """
    reg = load_registry()
    exclusions = reg.get("exclusions") or {}
    if _is_excluded(rel, exclusions):
        return "excluded"

    generated_pinned = reg.get("generated_pinned") or []
    if rel in generated_pinned:
        return "generated"

    probe_text = text if text is not None else _read_text(rel)
    if _has_banner(probe_text):
        return "generated"

    for row in reg.get("classes") or []:
        slug = row["slug"]
        if slug in ("generated", "residual"):
            continue
        for pattern in row.get("include") or []:
            if fnmatch.fnmatch(rel, pattern):
                return slug

    return "residual"


def iter_measured_files() -> Iterator[tuple[str, str]]:
    """Yield (rel, slug) for every tracked, non-excluded, GOVERNED file over `git
    ls-files` -- excluding exempt classes (generated, workflow_outputs, test_fixtures) and
    every path in the roadmaps row's defer_to_incumbent list (docs/ROADMAP-PLATFORM.yaml,
    deferred to its incumbent validate_platform_roadmap gate per Decisions 114/147).
    """
    reg = load_registry()
    classes_by_slug = {row["slug"]: row for row in reg.get("classes") or []}
    roadmaps_row = classes_by_slug.get("roadmaps") or {}
    defer_to_incumbent = set(roadmaps_row.get("defer_to_incumbent") or [])

    result = _common.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
    tracked = result.stdout.splitlines() if result.returncode == 0 else []

    for rel in sorted(tracked):
        if rel in defer_to_incumbent:
            continue
        text = _read_text(rel)
        if not text and not (_common.ROOT / rel).exists():
            continue
        slug = classify_path(rel, text=text)
        if slug == "excluded":
            continue
        class_row = classes_by_slug.get(slug)
        if class_row is None or not class_row.get("governed", False):
            continue
        yield rel, slug
