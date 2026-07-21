"""Tests for scripts.agent_development.run_skill.resolve_context_paths.

Context injection is explicit-only: the retired frontmatter auto-loading primitive
is gone (docs/contracts/instruction-architecture.yaml layer-4), so every caller of
run_skill.py supplies its own context files via --context. This test exercises the
resolver plus a regression guard that the retired parser stays removed.
"""

import pytest

from scripts.agent_development import run_skill

pytestmark = pytest.mark.unit


def test_resolve_context_paths_empty_when_none():
    assert run_skill.resolve_context_paths(None) == []


def test_resolve_context_paths_dedupes_preserving_order():
    assert run_skill.resolve_context_paths(["a", "b", "a"]) == ["a", "b"]


def test_resolve_context_paths_single_path():
    assert run_skill.resolve_context_paths(["docs/PROJECT_CONTEXT.md"]) == ["docs/PROJECT_CONTEXT.md"]


def test_parse_required_context_removed():
    """Regression guard: the retired frontmatter parser must not reappear."""
    assert not hasattr(run_skill, "parse_required_context")
