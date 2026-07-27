"""Tests for scripts/ops_portal/reader_transient.py -- the DCG-03 transient reader classifier
(Decision 155).

Covers the classifier's full truth table (each member of the reader's transient set classifies
transient; a transient-status message that ALSO carries an error_type marker does NOT; a 4xx does
NOT; a non-RuntimeError does NOT; requests.ConnectionError/Timeout DO) and the derive-the-set
parity test that keeps the classifier's accepted set locked to
src.common.iceberg_reader._READER_TRANSIENT_STATUS rather than an independently restated literal.

GUARD SHAPE IS PINNED (plan-critique round 4, B2): the `requests` dependency is guarded
FUNCTION-SCOPED, inside the two ConnectionError/Timeout test bodies only -- NEVER a module-scope
`pytest.importorskip("requests")`. requests is absent from requirements-fast.txt and is a member
of `scripts.checks._scaffolding._excluded_heavy_import_names()`, so a module-scope skip would skip
the WHOLE file under the pr-validate fast tier, silently defeating this file's own coverage and
degrading its two registry rows to non-fatal `skipped`. TestTransientSetParity needs no `requests`
at all and must always collect and run.
"""

from __future__ import annotations

import pytest


class TestIsReaderUnavailableTruthTable:
    """RuntimeError-message branch of the classifier -- no requests dependency needed."""

    def test_502_classifies_transient(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("ducklake reader failed (HTTP 502)")) is True

    def test_503_classifies_transient(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 503)")) is True

    def test_504_classifies_transient(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 504)")) is True

    def test_transient_status_with_error_type_marker_does_not_classify(self) -> None:
        """A structured handler error (error_type marker present) is not transient -- it gates."""
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 502) error_type=runtime")) is False

    def test_structured_500_with_error_type_does_not_classify(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 500) error_type=version_mismatch")) is False

    def test_bare_500_does_not_classify(self) -> None:
        """500 is not in the reader's transient set -- it gates."""
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 500)")) is False

    def test_4xx_does_not_classify(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(RuntimeError("failed (HTTP 403)")) is False

    def test_non_runtime_error_does_not_classify(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(Exception("some error")) is False

    def test_value_error_does_not_classify(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(ValueError("bad value")) is False

    def test_connection_error_classifies_transient(self) -> None:
        requests = pytest.importorskip("requests")
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(requests.ConnectionError("connection refused")) is True

    def test_timeout_classifies_transient(self) -> None:
        requests = pytest.importorskip("requests")
        from scripts.ops_portal.reader_transient import is_reader_unavailable

        assert is_reader_unavailable(requests.Timeout("timed out")) is True


class TestTransientSetParity:
    """Derive-the-set equality (Decision 154's DUCKLAKE_ARTIFACT_NAMES shape): the classifier's
    accepted status set must equal the reader's own authoritative transient set, never an
    independently restated literal that can silently drift from it. Needs no `requests` at all
    and must always collect and run -- it is the anti-drift mechanism for the classifier."""

    def test_classifier_set_equals_reader_authority(self) -> None:
        from scripts.ops_portal.reader_transient import is_reader_unavailable
        from src.common.iceberg_reader import _READER_TRANSIENT_STATUS

        accepted = {status for status in range(400, 600) if is_reader_unavailable(RuntimeError(f"failed (HTTP {status})"))}
        assert accepted == set(_READER_TRANSIENT_STATUS)

        rejected = set(range(400, 600)) - set(_READER_TRANSIENT_STATUS)
        for status in rejected:
            assert is_reader_unavailable(RuntimeError(f"failed (HTTP {status})")) is False
