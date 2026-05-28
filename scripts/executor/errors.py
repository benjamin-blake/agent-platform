"""Structured error types for the recommendation executor."""

from enum import Enum


class CIFailureCategory(str, Enum):
    """Categories of CI failure for deterministic triage."""

    LINT = "lint"
    IMPORT = "import"
    TYPE = "type"
    TEST = "test"
    UNKNOWN = "unknown"


class MergeFailureReason(str, Enum):
    """Reasons a PR merge can fail."""

    CONFLICT = "conflict"
    DIRTY_TREE = "dirty_tree"
    DRAFT_PR = "draft_pr"
    UNKNOWN = "unknown"


class ExecutorError(Exception):
    """Base exception for all executor errors."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.context = context or {}

    def __str__(self) -> str:
        base = super().__str__()
        if self.context:
            return f"{base} | context={self.context}"
        return base


class PlanParseError(ExecutorError):
    """Raised when a plan cannot be parsed from LLM output."""


class AcceptanceCommandError(ExecutorError):
    """Raised when an acceptance command cannot be parsed or fails."""


class CheckpointError(ExecutorError):
    """Raised when checkpoint save/load fails."""
