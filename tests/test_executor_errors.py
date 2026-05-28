"""Unit tests for scripts/executor/errors.py."""

from __future__ import annotations

import pytest

from scripts.executor.errors import (
    AcceptanceCommandError,
    CheckpointError,
    CIFailureCategory,
    ExecutorError,
    MergeFailureReason,
    PlanParseError,
)


class TestCIFailureCategory:
    """Tests for the CIFailureCategory enum."""

    def test_enum_members_exist(self) -> None:
        assert CIFailureCategory.LINT
        assert CIFailureCategory.IMPORT
        assert CIFailureCategory.TYPE
        assert CIFailureCategory.TEST
        assert CIFailureCategory.UNKNOWN

    def test_enum_values_are_strings(self) -> None:
        assert CIFailureCategory.LINT == "lint"
        assert CIFailureCategory.IMPORT == "import"
        assert CIFailureCategory.TYPE == "type"
        assert CIFailureCategory.TEST == "test"
        assert CIFailureCategory.UNKNOWN == "unknown"

    def test_is_str_subclass(self) -> None:
        assert isinstance(CIFailureCategory.LINT, str)
        assert CIFailureCategory.LINT.upper() == "LINT"

    def test_all_five_members(self) -> None:
        assert len(CIFailureCategory) == 5

    def test_str_comparison(self) -> None:
        assert CIFailureCategory.LINT == "lint"
        assert CIFailureCategory.IMPORT != "lint"


class TestMergeFailureReason:
    """Tests for the MergeFailureReason enum."""

    def test_enum_values(self) -> None:
        assert MergeFailureReason.CONFLICT == "conflict"
        assert MergeFailureReason.DIRTY_TREE == "dirty_tree"
        assert MergeFailureReason.DRAFT_PR == "draft_pr"
        assert MergeFailureReason.UNKNOWN == "unknown"

    def test_is_str_subclass(self) -> None:
        assert isinstance(MergeFailureReason.CONFLICT, str)

    def test_all_four_members(self) -> None:
        assert len(MergeFailureReason) == 4


class TestExecutorError:
    """Tests for ExecutorError base exception."""

    def test_basic_message(self) -> None:
        err = ExecutorError("something went wrong")
        assert str(err) == "something went wrong"

    def test_context_appears_in_str(self) -> None:
        err = ExecutorError("bad thing", context={"rec_id": "rec-001"})
        result = str(err)
        assert "bad thing" in result
        assert "rec_id" in result
        assert "rec-001" in result

    def test_empty_context_not_shown(self) -> None:
        err = ExecutorError("plain message")
        assert str(err) == "plain message"
        assert "context" not in str(err)

    def test_none_context_defaults_to_empty_dict(self) -> None:
        err = ExecutorError("message", context=None)
        assert err.context == {}

    def test_is_exception(self) -> None:
        with pytest.raises(ExecutorError):
            raise ExecutorError("boom")

    def test_context_stored(self) -> None:
        ctx = {"step": 3, "file": "foo.py"}
        err = ExecutorError("oops", context=ctx)
        assert err.context == ctx


class TestPlanParseError:
    """Tests for PlanParseError subclass."""

    def test_inherits_from_executor_error(self) -> None:
        err = PlanParseError("could not parse")
        assert isinstance(err, ExecutorError)
        assert isinstance(err, Exception)

    def test_message_preserved(self) -> None:
        err = PlanParseError("parse failed at step 3")
        assert "parse failed" in str(err)

    def test_context_works(self) -> None:
        err = PlanParseError("parse error", context={"raw": "garbled output"})
        assert "garbled output" in str(err)

    def test_raises_as_executor_error(self) -> None:
        with pytest.raises(ExecutorError):
            raise PlanParseError("plan parse failure")


class TestAcceptanceCommandError:
    """Tests for AcceptanceCommandError subclass."""

    def test_inherits_from_executor_error(self) -> None:
        err = AcceptanceCommandError("no cmd found")
        assert isinstance(err, ExecutorError)

    def test_message(self) -> None:
        err = AcceptanceCommandError("command exited 1")
        assert "command exited 1" in str(err)

    def test_raises(self) -> None:
        with pytest.raises(AcceptanceCommandError):
            raise AcceptanceCommandError("acceptance failed")


class TestCheckpointError:
    """Tests for CheckpointError subclass."""

    def test_inherits_from_executor_error(self) -> None:
        err = CheckpointError("checkpoint I/O error")
        assert isinstance(err, ExecutorError)

    def test_message(self) -> None:
        err = CheckpointError("disk full")
        assert "disk full" in str(err)

    def test_raises(self) -> None:
        with pytest.raises(CheckpointError):
            raise CheckpointError("checkpoint save failed")
