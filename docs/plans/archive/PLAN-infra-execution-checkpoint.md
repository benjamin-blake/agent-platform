# Plan

## Intent
Improve workflow resilience and friction visibility by adding execution state persistence (enabling session resumption after interruption) and enforcing accurate friction reporting in per-step retro-lite captures. This directly supports the North Star's "continuously improves based on captured lessons and friction points" principle.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-execution-checkpoint

## Phase
Infrastructure (workflow improvements)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.vscode/settings.json` | Modify | Add terminal auto-approval setting |
| `scripts/execution_state.py` | Create | Checkpoint save/load/clear functions |
| `tests/test_execution_state.py` | Create | Unit tests for execution state |
| `.github/prompts/implement.prompt.md` | Modify | Add checkpoint save/load integration |
| `.github/agents/retro-lite.agent.md` | Modify | Add friction verification gate |
| `.github/copilot_instructions.md` | Modify | Add File Router entry for execution state |
| `docs/GETTING_STARTED.md` | Modify | Document terminal auto-approval setting |

## Acceptance Criteria
- [ ] VS Code auto-approves terminal commands without prompting (setting present in settings.json)
- [ ] `execution_state.py` can save, load, and clear checkpoint state
- [ ] `implement.prompt.md` checks for existing checkpoint at Step 1 and offers to resume
- [ ] `implement.prompt.md` saves checkpoint after each Ordered Execution Step completes
- [ ] `retro-lite.agent.md` rejects "clean session" claims when tool failures are documented in context
- [ ] All tests pass (`pytest tests/test_execution_state.py`)
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Python 3.12+ with type hints
- Use `encoding='utf-8'` on all file operations
- No external dependencies beyond stdlib
- Instructions must be explicit enough for Haiku (0.33x cost model) to execute

## Context
- Decision 21: Per-step retro-lite captures friction at narrow scope
- Known friction: Previous session reported "clean" despite tool failures (heredoc escapes, retries)
- Known friction: Overnight code review wait caused 10+ hour session duration
- Checkpoint file location: `logs/.execution-state.json` (consistent with other JSONL logs)

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add terminal auto-approval to VS Code settings

**File:** `.vscode/settings.json`

**Current content (full file):**
```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.terminal.activateEnvironment": true,
    "terminal.integrated.defaultProfile.windows": "Git Bash",
    "terminal.integrated.profiles.windows": {
        "Git Bash": {
            "path": "C:\\Program Files\\Git\\bin\\bash.exe",
            "args": ["--login", "-i"],
            "icon": "terminal-bash"
        },
        "PowerShell": {
            "source": "PowerShell",
            "icon": "terminal-powershell"
        }
    },
    "python-envs.defaultEnvManager": "ms-python.python:pyenv"
}
```

**Replace with:**
```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.terminal.activateEnvironment": true,
    "terminal.integrated.defaultProfile.windows": "Git Bash",
    "terminal.integrated.profiles.windows": {
        "Git Bash": {
            "path": "C:\\Program Files\\Git\\bin\\bash.exe",
            "args": ["--login", "-i"],
            "icon": "terminal-bash"
        },
        "PowerShell": {
            "source": "PowerShell",
            "icon": "terminal-powershell"
        }
    },
    "python-envs.defaultEnvManager": "ms-python.python:pyenv",
    "github.copilot.chat.runCommand.enabled": true
}
```

**Verification:** File contains `"github.copilot.chat.runCommand.enabled": true`

---

### Step 2: Create execution_state.py

**File:** `scripts/execution_state.py`

**Create with this exact content:**
```python
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
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "logs" / ".execution-state.json"


class ExecutionState(TypedDict):
    """Schema for execution checkpoint state."""

    branch: str
    plan_file: str
    current_step: int
    total_steps: int
    status: str  # "IN_PROGRESS" or "COMPLETED"
    last_updated: str  # ISO-8601 timestamp


def save_checkpoint(
    branch: str,
    plan_file: str,
    current_step: int,
    total_steps: int,
    status: str = "IN_PROGRESS",
) -> None:
    """Save execution checkpoint to disk.

    Args:
        branch: Current git branch name (e.g., "agent/infra-feature")
        plan_file: Plan file name (e.g., "PLAN-infra-feature.md")
        current_step: The step number just completed (1-indexed)
        total_steps: Total number of Ordered Execution Steps in the plan
        status: "IN_PROGRESS" or "COMPLETED"
    """
    state: ExecutionState = {
        "branch": branch,
        "plan_file": plan_file,
        "current_step": current_step,
        "total_steps": total_steps,
        "status": status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
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
        STATE_FILE.unlink()
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
```

**Verification:** Run `python scripts/execution_state.py load` — should output "No checkpoint found"

---

### Step 3: Create test_execution_state.py

**File:** `tests/test_execution_state.py`

**Create with this exact content:**
```python
#!/usr/bin/env python3
"""Unit tests for execution_state.py checkpoint management."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "execution_state.py"
_spec = importlib.util.spec_from_file_location("execution_state", _MODULE_PATH)
assert _spec and _spec.loader
_execution_state = importlib.util.module_from_spec(_spec)
sys.modules["execution_state"] = _execution_state
_spec.loader.exec_module(_execution_state)  # type: ignore[union-attr]


class TestSaveCheckpoint:
    """Tests for save_checkpoint function."""

    def test_creates_checkpoint_file(self, tmp_path: Path) -> None:
        """Verify checkpoint file is created with correct content."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test-feature",
                plan_file="PLAN-test-feature.md",
                current_step=3,
                total_steps=10,
            )

        assert state_file.exists()
        content = json.loads(state_file.read_text(encoding="utf-8"))
        assert content["branch"] == "agent/test-feature"
        assert content["plan_file"] == "PLAN-test-feature.md"
        assert content["current_step"] == 3
        assert content["total_steps"] == 10
        assert content["status"] == "IN_PROGRESS"
        assert "last_updated" in content

    def test_overwrites_existing_checkpoint(self, tmp_path: Path) -> None:
        """Verify save overwrites previous checkpoint."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"old": "data"}', encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/new",
                plan_file="PLAN-new.md",
                current_step=1,
                total_steps=5,
            )

        content = json.loads(state_file.read_text(encoding="utf-8"))
        assert content["branch"] == "agent/new"
        assert "old" not in content


class TestLoadCheckpoint:
    """Tests for load_checkpoint function."""

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        """Verify None returned when checkpoint doesn't exist."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None

    def test_loads_valid_checkpoint(self, tmp_path: Path) -> None:
        """Verify valid checkpoint is loaded correctly."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps({
                "branch": "agent/test",
                "plan_file": "PLAN-test.md",
                "current_step": 5,
                "total_steps": 10,
                "status": "IN_PROGRESS",
                "last_updated": "2026-03-29T10:00:00+00:00",
            }),
            encoding="utf-8",
        )

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["branch"] == "agent/test"
        assert result["current_step"] == 5

    def test_returns_none_for_malformed_json(self, tmp_path: Path) -> None:
        """Verify None returned for invalid JSON."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("not valid json", encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None

    def test_returns_none_for_missing_fields(self, tmp_path: Path) -> None:
        """Verify None returned when required fields are missing."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"branch": "test"}', encoding="utf-8")  # Missing other fields

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None


class TestClearCheckpoint:
    """Tests for clear_checkpoint function."""

    def test_deletes_existing_checkpoint(self, tmp_path: Path) -> None:
        """Verify checkpoint file is deleted."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{}", encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.clear_checkpoint()

        assert result is True
        assert not state_file.exists()

    def test_returns_false_when_no_checkpoint(self, tmp_path: Path) -> None:
        """Verify False returned when no checkpoint exists."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.clear_checkpoint()

        assert result is False


class TestGetCheckpointAgeMinutes:
    """Tests for get_checkpoint_age_minutes function."""

    def test_returns_none_when_no_checkpoint(self, tmp_path: Path) -> None:
        """Verify None returned when checkpoint doesn't exist."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.get_checkpoint_age_minutes()

        assert result is None

    def test_returns_age_for_valid_checkpoint(self, tmp_path: Path) -> None:
        """Verify age is calculated correctly."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)

        # Create checkpoint with known timestamp
        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="PLAN-test.md",
                current_step=1,
                total_steps=5,
            )
            age = _execution_state.get_checkpoint_age_minutes()

        assert age is not None
        assert age >= 0  # Should be very small (just created)
        assert age < 1  # Less than 1 minute old
```

**Verification:** Run `python -m pytest tests/test_execution_state.py -v` — all tests should pass

---

### Step 4: Add checkpoint loading to implement.prompt.md Step 1

**File:** `.github/prompts/implement.prompt.md`

**Find this text (around line 13-30):**
```markdown
## Step 1: Read Plan File

Find the plan file for the current branch:

```bash
BRANCH=$(git branch --show-current)
SLUG=${BRANCH#agent/}
```

Look for `docs/plans/PLAN-${SLUG}.md`. If it exists, read it completely.

**Fallback:** If no branch-specific plan exists, check for legacy `docs/plans/PLAN.md` (for backwards compatibility with in-flight work predating the repo restructure). If it exists, read it completely. **Note:** All new work uses `docs/plans/PLAN-{slug}.md`. The legacy fallback exists only to avoid breaking in-progress sessions from before the migration.

If neither exists, stop:

> "No plan file found for branch `${BRANCH}`. Expected `docs/plans/PLAN-${SLUG}.md`. Run `/plan` first to create a plan."
```

**Replace with:**
```markdown
## Step 1: Read Plan File and Check for Checkpoint

**Step 1a: Check for existing checkpoint**

```bash
python scripts/execution_state.py load
```

If the output shows `"status": "IN_PROGRESS"`, present the checkpoint to the human:

> "Found checkpoint from a previous session:
> - Branch: `{branch}`
> - Plan: `{plan_file}`
> - Progress: Step {current_step}/{total_steps}
> - Last updated: {last_updated}
>
> **Resume from step {current_step + 1}?** Say 'resume' to continue, or 'restart' to begin from step 1."

- If "resume": Proceed to the Ordered Execution Steps loop (Step 6) and begin execution at step number `current_step + 1`, skipping earlier steps
- If "restart": Run `python scripts/execution_state.py clear` and continue to Step 1b

If no checkpoint exists (output is "No checkpoint found"), continue to Step 1b.

**Step 1b: Find the plan file**

```bash
BRANCH=$(git branch --show-current)
SLUG=${BRANCH#agent/}
```

Look for `docs/plans/PLAN-${SLUG}.md`. If it exists, read it completely.

**Fallback:** If no branch-specific plan exists, check for legacy `docs/plans/PLAN.md` (for backwards compatibility with in-flight work predating the repo restructure). If it exists, read it completely. **Note:** All new work uses `docs/plans/PLAN-{slug}.md`. The legacy fallback exists only to avoid breaking in-progress sessions from before the migration.

If neither exists, stop:

> "No plan file found for branch `${BRANCH}`. Expected `docs/plans/PLAN-${SLUG}.md`. Run `/plan` first to create a plan."
```

---

### Step 5: Add checkpoint saving to implement.prompt.md Step 6

**File:** `.github/prompts/implement.prompt.md`

**Find this text (around line 95-100):**
```markdown
For each step in `## Ordered Execution Steps`:

1. Mark the step in-progress in the todo list.
2. Execute the step according to its specification in the plan file.
3. Mark the step completed in the todo list.
```

**Replace with:**
```markdown
For each step in `## Ordered Execution Steps`:

1. Mark the step in-progress in the todo list.
2. Execute the step according to its specification in the plan file.
3. Mark the step completed in the todo list.
4. **Save checkpoint** (single atomic call):
   ```bash
   python -c "from scripts.execution_state import save_checkpoint; save_checkpoint(branch='BRANCH', plan_file='PLAN-SLUG.md', current_step=N, total_steps=TOTAL)"
   ```
   (Replace BRANCH, SLUG, N, and TOTAL with actual values from the current session.)
```

---

### Step 6: Add friction verification to retro-lite.agent.md

**File:** `.github/agents/retro-lite.agent.md`

**Find this text (around line 60-75):**
```markdown
**Step B — Route.**

- **If Step A found 0 friction items AND the context contains no descriptions of issues, bugs, fixes, workarounds, or surprises:**

  Output exactly:
  ```
  ## Retro-Lite: Clean session
  ```
  Then stop.
```

**Replace with:**
```markdown
**Step B — Route.**

- **If Step A found 0 friction items AND the context contains no descriptions of issues, bugs, fixes, workarounds, or surprises:**

  **VERIFICATION GATE:** Before outputting "Clean session", confirm ALL of the following:
  - The invoking agent explicitly stated "No tool failures, no mismatches, no unexpected states"
  - The context does NOT mention: retries, second attempts, "fix", "corrective", "failed", "error", "unexpected"
  - No file creation commands had to be retried (e.g., heredoc failures requiring `create_file` tool instead)

  If ANY of these checks fail, you MUST record friction. Claiming "clean" when friction occurred breaks the self-improvement feedback loop.

  Only if all checks pass, output exactly:
  ```
  ## Retro-Lite: Clean session
  ```
  Then stop.
```

---

### Step 7: Add File Router entry for execution state

**File:** `.github/copilot_instructions.md`

**Find this text (should be near line 85):**
```markdown
| Decision index | [logs/.decisions-index.jsonl](../logs/.decisions-index.jsonl) |
```

**Replace with:**
```markdown
| Decision index | [logs/.decisions-index.jsonl](../logs/.decisions-index.jsonl) |
| Execution checkpoint state | [logs/.execution-state.json](../logs/.execution-state.json) |
| Execution state management | [scripts/execution_state.py](../scripts/execution_state.py) |
```

---

### Step 8: Add checkpoint clearing to implement.prompt.md session close

**File:** `.github/prompts/implement.prompt.md`

**Find this text (around line 290, in the Session Close Phase section — look for "Step 23: Return to Main"):**
```markdown
## Step 23: Return to Main

```bash
git checkout main && git pull origin main && git branch -d [branch]
```

Report: "Session complete. Ready for next task."
```

**Replace with:**
```markdown
## Step 23: Return to Main

```bash
python scripts/execution_state.py clear
git checkout main && git pull origin main && git branch -d [branch]
```

Report: "Session complete. Ready for next task."
```

---

### Step 9: Document the terminal auto-approval setting in GETTING_STARTED.md

**File:** `docs/GETTING_STARTED.md`

**Find the "Development Environment" or similar section and add:**

```markdown
### VS Code Workspace Settings

The `.vscode/settings.json` file includes workspace-specific settings:

- **`github.copilot.chat.runCommand.enabled`**: Allows Copilot to execute terminal commands without manual approval. This is safe for this workflow because:
  - Commands are constrained to the repo directory
  - Pre-commit hooks validate all changes before commit
  - All automation uses deterministic Python scripts
```

**Verification:** The setting is documented in GETTING_STARTED.md.

---

### Step 10: Run pytest to verify tests pass

```bash
python -m pytest tests/test_execution_state.py -v
```

All tests must pass before proceeding.

---

### Step 11: Run full test suite

```bash
python -m pytest tests/ -q
```

All tests must pass before proceeding.

---

### Step 12: Run validate.py

```bash
python scripts/validate.py
```

Must exit 0. Fix any issues before proceeding.

---

### Step 13: Report implementation summary

Report:
- Files created: `scripts/execution_state.py`, `tests/test_execution_state.py`
- Files modified: `.vscode/settings.json`, `.github/prompts/implement.prompt.md`, `.github/agents/retro-lite.agent.md`, `.github/copilot_instructions.md`
- All acceptance criteria verified
- Any design decisions made during implementation
