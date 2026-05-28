#!/usr/bin/env python3
"""Execution state checkpoint management for session resumption.

Saves and loads checkpoint state to allow implementation sessions to resume
after interruption (overnight wait, context overflow, timeout).

Usage:
    from scripts.execution_state import save_checkpoint, load_checkpoint, clear_checkpoint

    # Save after each step
    save_checkpoint(branch="agent/feature", plan_file="PLAN-feature.md", current_step=3, total_steps=10)

    # Load at session start
    state = load_checkpoint()
    if state and state["status"] == "IN_PROGRESS":
        print(f"Resuming from step {state['current_step']}")

    # Clear after successful completion
    clear_checkpoint()
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "logs" / ".execution-state.json"


class ExecutionState(TypedDict, total=False):
    """Schema for execution checkpoint state.

    Required fields: branch, plan_file, current_step, total_steps, status, last_updated.
    Optional fields: todo_state (added in v2; migrated to [] if missing on load).

    Valid status values: IN_PROGRESS, PLAN_COMPLETE, IMPL_COMPLETE, REVIEW_COMPLETE,
    CI_PENDING, COMPLETED.
    """

    branch: str
    plan_file: str
    current_step: int
    total_steps: int
    status: str  # see VALID_STATUSES for valid values
    last_updated: str  # ISO-8601 timestamp
    todo_state: list[dict[str, Any]]  # [{"id": N, "title": "...", "status": "..."}]


VALID_STATUSES: frozenset[str] = frozenset(
    {
        "IN_PROGRESS",
        "PLAN_COMPLETE",
        "IMPL_COMPLETE",
        "REVIEW_COMPLETE",
        "CI_PENDING",
        "COMPLETED",
    }
)


def save_checkpoint(
    branch: str,
    plan_file: str,
    current_step: int,
    total_steps: int,
    status: str = "IN_PROGRESS",
    todo_state: list[dict[str, Any]] | None = None,
) -> None:
    """Save execution checkpoint to disk.

    Args:
        branch: Current git branch name (e.g., "agent/infra-feature")
        plan_file: Plan file name (e.g., "PLAN-infra-feature.md")
        current_step: The step number just completed (1-indexed)
        total_steps: Total number of Ordered Execution Steps in the plan
        status: Checkpoint status -- see VALID_STATUSES for valid values
        todo_state: Optional list of todo items with id, title, status fields.
    """
    if status not in VALID_STATUSES:
        logger.warning("Unknown checkpoint status: %s (valid: %s)", status, ", ".join(sorted(VALID_STATUSES)))
    state: ExecutionState = {
        "branch": branch,
        "plan_file": plan_file,
        "current_step": current_step,
        "total_steps": total_steps,
        "status": status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "todo_state": todo_state if todo_state is not None else [],
    }

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info(
        "Checkpoint saved: step %d/%d on %s (%s)",
        current_step,
        total_steps,
        branch,
        status,
    )


def load_checkpoint() -> ExecutionState | None:
    """Load execution checkpoint from disk.

    Returns:
        ExecutionState dict if checkpoint exists and is valid, None otherwise.
    """
    if not STATE_FILE.exists():
        return None

    try:
        content = STATE_FILE.read_text(encoding="utf-8")
        state = json.loads(content)

        # Validate required fields
        required = {"branch", "plan_file", "current_step", "total_steps", "status", "last_updated"}
        if not required.issubset(state.keys()):
            logger.warning("Checkpoint missing required fields, ignoring")
            return None

        # Migration: initialise todo_state for old checkpoints that predate v2 schema
        if "todo_state" not in state:
            state["todo_state"] = []

        return state
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load checkpoint: %s", exc)
        return None


def clear_checkpoint() -> bool:
    """Clear execution checkpoint after successful completion.

    Returns:
        True if checkpoint was deleted, False if it didn't exist.
    """
    if STATE_FILE.exists():
        STATE_FILE.unlink(missing_ok=True)
        subprocess.run(
            ["git", "rm", "--cached", "logs/.execution-state.json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        logger.info("Checkpoint cleared")
        return True
    return False


def get_checkpoint_age_minutes() -> float | None:
    """Get age of checkpoint in minutes.

    Returns:
        Age in minutes if checkpoint exists, None otherwise.
    """
    state = load_checkpoint()
    if not state:
        return None

    try:
        last_updated = datetime.fromisoformat(state["last_updated"])
        now = datetime.now(timezone.utc)
        return (now - last_updated).total_seconds() / 60
    except (ValueError, KeyError):
        return None


if __name__ == "__main__":
    # CLI for testing
    import sys

    if len(sys.argv) < 2:
        print("Usage: python execution_state.py [save|load|clear|age]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "load":
        state = load_checkpoint()
        print(json.dumps(state, indent=2) if state else "No checkpoint found")
    elif cmd == "clear":
        cleared = clear_checkpoint()
        print("Cleared" if cleared else "No checkpoint to clear")
    elif cmd == "age":
        age = get_checkpoint_age_minutes()
        print(f"{age:.1f} minutes" if age else "No checkpoint found")
    elif cmd == "save":
        # For testing: save a dummy checkpoint
        save_checkpoint(
            branch="test-branch",
            plan_file="PLAN-test.md",
            current_step=1,
            total_steps=5,
        )
        print("Test checkpoint saved")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
