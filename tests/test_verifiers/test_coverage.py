"""Tests for scripts.verifiers.check_coverage().

Validates that scope files are correctly classified as covered or uncovered
based on each verifier class's `covers` glob list.
"""

from __future__ import annotations

import pytest

from scripts.verifiers import REGISTRY, check_coverage
from scripts.verifiers.harness import Verifier, VerifierResult, VerifierStatus


class _MockOpsVerifier(Verifier):
    covers: list[str] = [
        "scripts/ops_data_portal.py",
        "scripts/ops_writer.py",
    ]

    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.PASS, "ok")


class _MockDqVerifier(Verifier):
    covers: list[str] = [
        "config/agent/data_quality/**",
        "src/data/**",
    ]

    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.PASS, "ok")


@pytest.fixture
def isolated_registry():
    """Replace the REGISTRY for the duration of the test, then restore it."""
    saved = REGISTRY.copy()
    REGISTRY.clear()
    REGISTRY.append(_MockOpsVerifier)
    REGISTRY.append(_MockDqVerifier)
    try:
        yield
    finally:
        REGISTRY.clear()
        REGISTRY.extend(saved)


class TestCheckCoverage:
    """check_coverage(scope_files) -> list[str] uncovered files."""

    def test_check_coverage_exact_match_is_covered(self, isolated_registry):
        """A scope file equal to a verifier's covers entry is covered."""
        uncovered = check_coverage(["scripts/ops_data_portal.py"])
        assert uncovered == []

    def test_check_coverage_glob_expansion_is_covered(self, isolated_registry):
        """A scope file under a `**` glob is matched as covered."""
        uncovered = check_coverage(["config/agent/data_quality/ops.yaml"])
        assert uncovered == []

    def test_check_coverage_nested_glob_is_covered(self, isolated_registry):
        """Deeply nested file under a `**` glob is still covered."""
        uncovered = check_coverage(["src/data/handlers/fetch_handler.py"])
        assert uncovered == []

    def test_check_coverage_unmatched_file_is_uncovered(self, isolated_registry):
        """A scope file matching no glob is returned in the uncovered list."""
        uncovered = check_coverage(["docs/foo.md"])
        assert uncovered == ["docs/foo.md"]

    def test_check_coverage_mixed_returns_only_uncovered(self, isolated_registry):
        """Only scope files lacking coverage are returned; covered ones drop out."""
        scope = [
            "scripts/ops_data_portal.py",
            "docs/foo.md",
            "config/agent/data_quality/telemetry.yaml",
            "scripts/unrelated_script.py",
        ]
        uncovered = check_coverage(scope)
        assert uncovered == ["docs/foo.md", "scripts/unrelated_script.py"]

    def test_check_coverage_normalises_windows_separators(self, isolated_registry):
        """Backslash-separated paths are normalised before glob matching."""
        uncovered = check_coverage(["config\\agent\\data_quality\\ops.yaml"])
        assert uncovered == []

    def test_check_coverage_empty_scope_returns_empty(self, isolated_registry):
        """An empty scope returns an empty uncovered list."""
        assert check_coverage([]) == []

    def test_check_coverage_empty_registry_marks_everything_uncovered(self):
        """When no verifiers are registered, every scope file is uncovered."""
        saved = REGISTRY.copy()
        REGISTRY.clear()
        try:
            uncovered = check_coverage(["scripts/foo.py"])
            assert uncovered == ["scripts/foo.py"]
        finally:
            REGISTRY.clear()
            REGISTRY.extend(saved)

    def test_check_coverage_differential_against_real_registry(self):
        """(T3.16:c1) Against the REAL REGISTRY (no isolated_registry fixture): an absurd path is
        reported uncovered -- this FAILS on the pre-change tree where a "**"/"*" verifier glob
        makes coverage structurally vacuous -- while a genuinely-covered path still returns []."""
        uncovered = check_coverage(["zzz/definitely_not_covered.xyz"])
        assert uncovered == ["zzz/definitely_not_covered.xyz"]
        assert check_coverage(["config/agent/data_quality/ops.yaml"]) == []
