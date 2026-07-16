"""Tests for validate_pydantic_yaml_drift / _check_drift_for_table (T0.12)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Annotated, Optional

from pydantic import BaseModel

from src.schemas.annotations import DqAcceptedValues, DqDeleted, DqNotNull, migrating

_SCRIPT_PATH = Path(__file__).parent.parent.parent.parent / "scripts" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate_drift", _SCRIPT_PATH)
_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_validate)  # type: ignore[union-attr]
sys.modules["validate_drift"] = _validate

_check_drift_for_table = _validate._check_drift_for_table


def _table(columns: dict) -> dict:
    return {"columns": columns}


def _col(*test_dicts) -> dict:
    return {"tests": list(test_dicts)}


class TestDriftDetectorAligned:
    def test_drift_detector_passes_when_aligned(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        table = _table({"field_a": _col({"not_null": {"enforced": True}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_aligned_with_accepted_values(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), DqAcceptedValues(values=("x", "y"))]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x", "y"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_unannotated_field_skipped(self) -> None:
        class SyntheticModel(BaseModel):
            plain_field: str

        table = _table({"plain_field": _col({"not_null": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_field_absent_from_yaml_skipped(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        table = _table({})  # field_a not in YAML columns
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_out_of_vocabulary_yaml_checks_ignored(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        # path_syntax and expression are out-of-vocabulary; only not_null should match
        table = _table({"field_a": _col({"not_null": {}}, {"path_syntax": {}}, {"expression": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []


class TestDriftDetectorUnmarkedDivergence:
    def test_drift_detector_fails_on_unmarked_divergence(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        # YAML has accepted_values but Pydantic does not
        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x", "y"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)

    def test_pydantic_extra_marker_fails(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), DqAcceptedValues(values=("x",))]

        # YAML only has not_null, Pydantic has also DqAcceptedValues
        table = _table({"field_a": _col({"not_null": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)


class TestMigratingMarker:
    def test_migrating_marker_tolerates_divergence(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), migrating(target="9999-12-31")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_expired_migrating_marker_fails(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), migrating(target="1900-01-01")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)


class TestDqDeleted:
    def test_dqdeleted_field_allowed_when_absent_from_yaml(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqDeleted(since="2026-01-01")]

        table = _table({})  # field_a absent from YAML
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_dqdeleted_field_skips_even_when_present_in_yaml(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqDeleted(since="2026-01-01")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_optional_annotated_field_is_processed(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[Optional[int], DqNotNull(enforced=False)] = None

        table = _table({"field_a": _col({"not_null": {"enforced": False}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []
