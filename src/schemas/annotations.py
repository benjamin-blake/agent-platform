"""DQ-as-Annotated-Pydantic marker vocabulary (T0.12, CD.12).

Field-level DQ markers (closed at 7, CD.12 ceiling):
  DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted.
Adding an 8th non-DqDeleted marker requires a new candidate decision.
The test suite enforces the count via introspection.

Marker design: frozen dataclasses (hashable, comparable, repr-informative).
Use inside typing.Annotated to attach DQ intent to field types:

    field: Annotated[str, DqNotNull(write_time=True), DqAcceptedValues(values=("a", "b"))]

Out-of-vocabulary YAML checks (expression, path_syntax, acceptance_lint) have no
Annotated equivalents by design -- they live in handler code (ops_data_portal.py).

Class-level schema decorators (separate namespace, not counted as DQ markers):
  migrating(target)  -- coexistence migration window
  partition_by(spec) -- Iceberg PARTITIONED BY spec (T0.13, CD.9)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Literal


@dataclass(frozen=True)
class DqNotNull:
    write_time: bool = False
    enforced: bool = True
    exclude_before: str | None = None


@dataclass(frozen=True)
class DqUnique:
    enforced: bool = True


@dataclass(frozen=True)
class DqAcceptedValues:
    values: tuple[str, ...]
    enforced: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            raise TypeError(f"DqAcceptedValues.values must be a tuple, not {type(self.values).__name__}")


@dataclass(frozen=True)
class DqRelationship:
    to_table: str
    to_column: str
    severity: Literal["error", "warn"] = "error"


@dataclass(frozen=True)
class DqRecency:
    warn_after_hours: int
    error_after_hours: int


@dataclass(frozen=True)
class DqRowCount:
    min: int
    severity: Literal["error", "warn"] = "error"


@dataclass(frozen=True)
class DqDeleted:
    since: str


class MigratingMarker:
    """Metadata marker for fields undergoing a DQ coexistence migration window.

    Dual-mode usage:
    - As a class decorator: @migrating(target='YYYY-MM-DD') sets __migrating_target__ on cls.
    - As Annotated metadata: Annotated[str, DqNotNull(), migrating(target='YYYY-MM-DD')]
      embeds the marker so the drift detector can locate it via get_type_hints.
    """

    def __init__(self, target: str) -> None:
        self.target = target
        self._parsed: date = datetime.strptime(target, "%Y-%m-%d").date()

    def __call__(self, cls: type) -> type:
        cls.__migrating_target__ = self.target
        return cls

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).date() > self._parsed


def migrating(target: str) -> MigratingMarker:
    """Return a MigratingMarker for the given ISO target date.

    Use as a class decorator or as Annotated metadata. When target date is in the
    past, the drift detector treats the field/model as non-migrating and fails on
    divergence.
    """
    return MigratingMarker(target)


def partition_by(spec: str) -> Callable[[type], type]:
    """Return a class decorator that sets cls.__partition_by__ = spec.

    Use as a class decorator on Pydantic models to declare the Iceberg PARTITIONED BY
    transform spec (e.g. 'day(last_updated_timestamp)'). Required on every Iceberg model
    per CD.9. This is a class-level schema decorator, not a DQ marker -- the closed 7-marker
    DQ vocabulary (CD.12) is unaffected.
    """

    def _decorator(cls: type) -> type:
        cls.__partition_by__ = spec  # type: ignore[attr-defined]
        return cls

    return _decorator
