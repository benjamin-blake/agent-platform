"""Tests for src/schemas/annotations.py (T0.12 exit criteria)."""

from __future__ import annotations

import pytest

from src.schemas import annotations
from src.schemas.annotations import (
    DqAcceptedValues,
    DqDeleted,
    DqNotNull,
    DqRecency,
    DqRelationship,
    DqRowCount,
    DqUnique,
    migrating,
    partition_by,
)


def test_seven_markers_exposed() -> None:
    markers = [n for n in dir(annotations) if n.startswith("Dq")]
    assert len(markers) == 7, f"Expected exactly 7 Dq markers, got {len(markers)}: {markers}"


def test_markers_are_frozen() -> None:
    nn = DqNotNull(write_time=True)
    with pytest.raises((AttributeError, TypeError)):
        nn.write_time = False  # type: ignore[misc]


def test_marker_equality() -> None:
    assert DqNotNull(write_time=True) == DqNotNull(write_time=True)
    assert DqNotNull(write_time=True) != DqNotNull(write_time=False)
    assert DqAcceptedValues(values=("a", "b")) == DqAcceptedValues(values=("a", "b"))
    assert DqAcceptedValues(values=("a", "b")) != DqAcceptedValues(values=("a", "c"))


def test_marker_repr() -> None:
    r = repr(DqNotNull(write_time=True, enforced=True))
    assert "DqNotNull" in r
    assert "write_time=True" in r


def test_dqaccepted_values_is_tuple() -> None:
    with pytest.raises(TypeError, match="tuple"):
        DqAcceptedValues(values=["a", "b"])  # type: ignore[arg-type]


def test_migrating_decorator_sets_target() -> None:
    @migrating(target="2099-01-01")
    class _Dummy:
        pass

    assert hasattr(_Dummy, "__migrating_target__")
    assert _Dummy.__migrating_target__ == "2099-01-01"


def test_all_marker_classes_importable() -> None:
    for cls in (DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted):
        assert cls.__name__.startswith("Dq")


def test_dqrecency_fields() -> None:
    r = DqRecency(warn_after_hours=24, error_after_hours=168)
    assert r.warn_after_hours == 24
    assert r.error_after_hours == 168


def test_dqdeleted_requires_since() -> None:
    d = DqDeleted(since="2026-01-01")
    assert d.since == "2026-01-01"


def test_migrating_marker_is_expired_past() -> None:
    m = migrating(target="1900-01-01")
    assert m.is_expired() is True


def test_migrating_marker_is_not_expired_future() -> None:
    m = migrating(target="9999-12-31")
    assert m.is_expired() is False


def test_partition_by_decorator_sets_attr() -> None:
    @partition_by("day(last_updated_timestamp)")
    class _Dummy:
        pass

    assert hasattr(_Dummy, "__partition_by__")
    assert _Dummy.__partition_by__ == "day(last_updated_timestamp)"
