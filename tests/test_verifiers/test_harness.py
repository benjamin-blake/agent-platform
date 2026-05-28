"""Tests for the verification harness."""

import pytest

from scripts.verifiers.harness import (
    Verifier,
    VerifierResult,
    VerifierSeverity,
    VerifierStatus,
    VerifierTier,
    scope_intersects_covers,
)


class MockPassVerifier(Verifier):
    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.PASS, "Success")


class MockFailVerifier(Verifier):
    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.FAIL, "Failure")


class MockAdvisoryFailVerifier(Verifier):
    @property
    def severity(self) -> VerifierSeverity:
        return VerifierSeverity.ADVISORY

    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.FAIL, "Advisory Failure")


class MockV2Verifier(Verifier):
    @property
    def tier(self) -> VerifierTier:
        return VerifierTier.V2

    async def verify(self) -> VerifierResult:
        return VerifierResult(self.name, VerifierStatus.PASS, "V2 Success")


class MockExceptionVerifier(Verifier):
    async def verify(self) -> VerifierResult:
        raise ValueError("Boom")


@pytest.mark.asyncio
async def test_verifier_run_pass():
    verifier = MockPassVerifier()
    result = await verifier.run()
    assert result.status == VerifierStatus.PASS
    assert result.name == "MockPassVerifier"
    assert result.duration_ms > 0
    assert result.severity == VerifierSeverity.HARD_GATE


@pytest.mark.asyncio
async def test_verifier_run_fail():
    verifier = MockFailVerifier()
    result = await verifier.run()
    assert result.status == VerifierStatus.FAIL
    assert "Failure" in result.message
    assert result.severity == VerifierSeverity.HARD_GATE


@pytest.mark.asyncio
async def test_verifier_run_advisory_fail():
    verifier = MockAdvisoryFailVerifier()
    result = await verifier.run()
    assert result.status == VerifierStatus.FAIL
    assert result.severity == VerifierSeverity.ADVISORY


@pytest.mark.asyncio
async def test_verifier_run_exception():
    verifier = MockExceptionVerifier()
    result = await verifier.run()
    assert result.status == VerifierStatus.FAIL
    assert "ValueError: Boom" in result.message


def test_verifier_result_helpers():
    result = VerifierResult("Test", VerifierStatus.PASS, "Msg", duration_ms=10.5, severity=VerifierSeverity.ADVISORY)
    assert str(result) == "[PASS] (ADVISORY) Test: Msg (10.5ms)"
    d = result.to_dict()
    assert d["status"] == "PASS"
    assert d["duration_ms"] == 10.5
    assert d["severity"] == "ADVISORY"


@pytest.mark.asyncio
async def test_run_all_verifiers(monkeypatch):
    from scripts.verifiers import REGISTRY, run_all_verifiers

    # Clear registry for clean test
    original_registry = REGISTRY.copy()
    REGISTRY.clear()
    try:
        REGISTRY.append(MockPassVerifier)
        REGISTRY.append(MockFailVerifier)

        results = await run_all_verifiers()
        assert len(results) == 2
        status_map = {r.name: r.status for r in results}
        assert status_map["MockPassVerifier"] == VerifierStatus.PASS
        assert status_map["MockFailVerifier"] == VerifierStatus.FAIL
    finally:
        REGISTRY.clear()
        REGISTRY.extend(original_registry)


@pytest.mark.asyncio
async def test_run_all_verifiers_tier_filter():
    from scripts.verifiers import REGISTRY, run_all_verifiers

    original_registry = REGISTRY.copy()
    REGISTRY.clear()
    try:
        REGISTRY.append(MockPassVerifier)  # V1
        REGISTRY.append(MockV2Verifier)  # V2

        # Run with V2 filter
        results = await run_all_verifiers(tier_filter=VerifierTier.V2)
        assert len(results) == 1
        assert results[0].name == "MockV2Verifier"

        # Run with V1 filter
        results = await run_all_verifiers(tier_filter=VerifierTier.V1)
        assert len(results) == 1
        assert results[0].name == "MockPassVerifier"
    finally:
        REGISTRY.clear()
        REGISTRY.extend(original_registry)


@pytest.mark.asyncio
async def test_run_all_verifiers_severity_filter():
    from scripts.verifiers import REGISTRY, run_all_verifiers

    original_registry = REGISTRY.copy()
    REGISTRY.clear()
    try:
        REGISTRY.append(MockFailVerifier)  # HARD_GATE
        REGISTRY.append(MockAdvisoryFailVerifier)  # ADVISORY

        # Run with HARD_GATE filter (min_severity=HARD_GATE)
        results = await run_all_verifiers(min_severity=VerifierSeverity.HARD_GATE)
        assert len(results) == 1
        assert results[0].name == "MockFailVerifier"

        # Run without filter (default ADVISORY or None)
        results = await run_all_verifiers()
        assert len(results) == 2
    finally:
        REGISTRY.clear()
        REGISTRY.extend(original_registry)


def test_verifier_covers_default():
    """Verifier base class must expose covers with default ['**']."""
    assert Verifier.covers == ["**"]


@pytest.mark.asyncio
async def test_verifier_run_propagates_covers():
    """run() must copy the verifier's covers list onto the VerifierResult."""

    class MockCoveredVerifier(Verifier):
        covers: list[str] = ["scripts/foo.py", "config/**"]

        async def verify(self) -> VerifierResult:
            return VerifierResult(self.name, VerifierStatus.PASS, "ok")

    result = await MockCoveredVerifier().run()
    assert result.covers == ["scripts/foo.py", "config/**"]


def test_scope_intersects_covers_match():
    """Intersection returns True when a glob matches a scope path."""
    assert scope_intersects_covers(["scripts/ops_data_portal.py"], ["scripts/ops_data_portal.py"])
    assert scope_intersects_covers(["config/agent/data_quality/ops.yaml"], ["config/agent/data_quality/**"])


def test_scope_intersects_covers_no_match():
    """Intersection returns False when no glob matches any scope path."""
    assert not scope_intersects_covers(["docs/foo.md"], ["scripts/**", "config/**"])


def test_scope_intersects_covers_wildcard_all():
    """Default covers=['**'] matches any path."""
    assert scope_intersects_covers(["docs/foo.md"], ["**"])
    assert scope_intersects_covers(["scripts/some_file.py"], ["**"])
