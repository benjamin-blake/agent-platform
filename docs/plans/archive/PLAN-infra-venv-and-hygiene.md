# Plan

## Intent
Eliminate the most frequent recurring friction point (venv activation failure on Windows Git Bash) and resolve minor hygiene issues in prompt/script files to improve workflow reliability.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-venv-and-hygiene

## Phase
Infrastructure (parallel to Phase 1.5)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `setup.py` | Modify | Add `fix_venv_activate_for_git_bash()` that patches backslashes to forward slashes |
| `tests/test_setup.py` | Create | Test the venv activate fix function |
| `.github/copilot_instructions.md` | Modify | Add note about `python setup.py` fixing venv activation |
| `.github/prompts/plan.prompt.md` | Modify | Remove duplicate "Platform compatibility check" block |
| `scripts/plan_audit.py` | Modify | Add `logging.basicConfig()` for debug visibility |
| `docs/RECOMMENDATIONS.md` | Modify | Mark 3 items as resolved |

## Acceptance Criteria
- [ ] `python setup.py` patches `.venv/Scripts/activate` to use forward slashes
- [ ] After running `setup.py`, activating venv shows correct Python path (not corrupted)
- [ ] `tests/test_setup.py` passes (tests the fix function with mock files)
- [ ] `pytest tests/` passes (all tests including new ones)
- [ ] `python scripts/validate.py` exits 0

## Constraints
- Python-only automation (no shell wrappers)
- Must be idempotent (running setup.py multiple times is safe)
- Must not break Unix venv activation (forward slashes work on both platforms)

## Context
- Friction log shows 3+ occurrences of "wrong venv at session start"
- Root cause: Python's `venv` module generates activate script with Windows backslashes
- Git Bash interprets `\U`, `\G`, etc. as escape sequences, corrupting PATH
- Existing Known Gotcha in copilot_instructions.md mentions the symptom but not the fix

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add `fix_venv_activate_for_git_bash()` to setup.py

In `setup.py`, add this function after the `create_venv()` function (around line 26):

```python
def fix_venv_activate_for_git_bash() -> None:
    """Patch .venv/Scripts/activate to use forward slashes for Git Bash compatibility.

    Python's venv module generates activate scripts with Windows backslashes, e.g.:
        VIRTUAL_ENV="C:\\Users\\user\\repo\\.venv"

    Git Bash interprets backslash sequences (\\U, \\G, etc.) as escapes, corrupting PATH.
    This function converts to forward slashes which work on both Windows and Unix:
        VIRTUAL_ENV="/c/Users/user/repo/.venv"
    """
    activate_path = ROOT / ".venv" / "Scripts" / "activate"
    if not activate_path.exists():
        return

    content = activate_path.read_text(encoding="utf-8")

    # Check if already fixed (contains forward slashes in VIRTUAL_ENV line)
    if 'VIRTUAL_ENV="/' in content:
        print("Venv activate script already fixed for Git Bash.")
        return

    # Convert Windows paths to Git Bash format: C:\path -> /c/path
    import re
    def convert_path(match: re.Match[str]) -> str:
        path = match.group(1)
        # Convert drive letter: C:\ -> /c/
        if len(path) >= 2 and path[1] == ":":
            drive = path[0].lower()
            path = f"/{drive}{path[2:]}"
        # Convert backslashes to forward slashes
        path = path.replace("\\", "/")
        return f'VIRTUAL_ENV="{path}"'

    fixed = re.sub(r'VIRTUAL_ENV="([^"]+)"', convert_path, content)
    activate_path.write_text(fixed, encoding="utf-8")
    print("Fixed venv activate script for Git Bash compatibility.")
```

Then in the `main()` function, add a call to `fix_venv_activate_for_git_bash()` immediately after `create_venv()`:

```python
def main() -> None:
    print("Setting up Lakehouse Trading System...")
    print()

    check_python_version()
    create_venv()
    fix_venv_activate_for_git_bash()  # <-- Add this line
    install_dependencies()
```

### Step 2: Create tests/test_setup.py

Create a new test file `tests/test_setup.py` with the following content:

```python
#!/usr/bin/env python3
"""Unit tests for setup.py venv activation fix."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "setup.py"
_spec = importlib.util.spec_from_file_location("setup", _MODULE_PATH)
assert _spec and _spec.loader
_setup = importlib.util.module_from_spec(_spec)
sys.modules["setup"] = _setup
_spec.loader.exec_module(_setup)  # type: ignore[union-attr]


class TestFixVenvActivateForGitBash:
    """Tests for the fix_venv_activate_for_git_bash function."""

    def test_converts_windows_backslashes_to_forward_slashes(self, tmp_path: Path) -> None:
        """Verify Windows paths are converted to Git Bash format."""
        # Setup: Create activate script with Windows backslashes
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        activate_file.write_text(
            'VIRTUAL_ENV="C:\\Users\\bblake\\Git Repos\\agent-platform\\.venv"\n'
            'export VIRTUAL_ENV\n'
            'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n',
            encoding="utf-8",
        )

        # Execute
        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        # Verify
        result = activate_file.read_text(encoding="utf-8")
        assert 'VIRTUAL_ENV="/c/Users/bblake/Git Repos/agent-platform/.venv"' in result
        assert "C:\\" not in result
        assert "\\\\" not in result

    def test_idempotent_does_not_double_fix(self, tmp_path: Path) -> None:
        """Verify running twice doesn't corrupt already-fixed paths."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        already_fixed = 'VIRTUAL_ENV="/c/Users/bblake/Git Repos/agent-platform/.venv"\n'
        activate_file.write_text(already_fixed, encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert result == already_fixed  # Unchanged

    def test_skips_if_activate_not_exists(self, tmp_path: Path) -> None:
        """Verify no error if .venv/Scripts/activate doesn't exist."""
        with patch.object(_setup, "ROOT", tmp_path):
            # Should not raise
            _setup.fix_venv_activate_for_git_bash()

    def test_preserves_other_content(self, tmp_path: Path) -> None:
        """Verify only VIRTUAL_ENV line is modified, rest preserved."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        original = (
            '# This is a comment\n'
            'VIRTUAL_ENV="D:\\Projects\\test\\.venv"\n'
            '_OLD_VIRTUAL_PATH="$PATH"\n'
            'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n'
            'export PATH\n'
        )
        activate_file.write_text(original, encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert '# This is a comment\n' in result
        assert 'VIRTUAL_ENV="/d/Projects/test/.venv"' in result
        assert '_OLD_VIRTUAL_PATH="$PATH"\n' in result
        assert 'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n' in result
        assert 'export PATH\n' in result

    def test_handles_different_drive_letters(self, tmp_path: Path) -> None:
        """Verify different drive letters are converted correctly."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        activate_file.write_text('VIRTUAL_ENV="E:\\dev\\project\\.venv"\n', encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert 'VIRTUAL_ENV="/e/dev/project/.venv"' in result
```

### Step 3: Add logging.basicConfig() to plan_audit.py

In `scripts/plan_audit.py`, add a `logging.basicConfig()` call after the logger definition (around line 16-17):

Find:
```python
logger = logging.getLogger(__name__)
```

Replace with:
```python
logger = logging.getLogger(__name__)
logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.WARNING)
```

### Step 4: Remove duplicate "Platform compatibility check" from plan.prompt.md

In `.github/prompts/plan.prompt.md`, remove the duplicate block at lines 234-235.

Find (the second occurrence, after the "git commit" block):
```markdown
This commits the plan to the feature branch, making it tracked, associated with the feature branch, and safe for concurrent planning on other branches.

**Platform compatibility check:** When writing steps that involve shell commands, file operations, or platform-specific tools, verify they are Windows-compatible. Reference the Shell rule in `copilot_instructions.md` ("Python scripts only for automation"). Common gotchas: `stat -c` (Linux), `grep` without fallback, hardcoded forward slashes in scripts.

---

## Step 9: Plan Critique Gate (MANDATORY)
```

Replace with:
```markdown
This commits the plan to the feature branch, making it tracked, associated with the feature branch, and safe for concurrent planning on other branches.

---

## Step 9: Plan Critique Gate (MANDATORY)
```

### Step 5: Update copilot_instructions.md Known Gotcha

In `.github/copilot_instructions.md`, update the venv switching gotcha (line 117) to mention the fix.

Find:
```markdown
- **Virtual environment switching between repos (High Risk):** When switching between Git repos in the same terminal session, the previously activated venv remains active. This causes import errors and cryptic failures. **Always verify the venv matches the current repo** before starting any work: run `python -c "import sys; print(sys.executable)"` and confirm the path contains the current repo folder name. If wrong, run `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (Unix) to activate the correct environment. `plan.prompt.md` Step 1 enforces this check at session start.
```

Replace with:
```markdown
- **Virtual environment switching between repos (High Risk):** When switching between Git repos in the same terminal session, the previously activated venv remains active. This causes import errors and cryptic failures. **Always verify the venv matches the current repo** before starting any work: run `python -c "import sys; print(sys.executable)"` and confirm the path contains the current repo folder name. If wrong, run `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (Unix) to activate the correct environment. `plan.prompt.md` Step 0 enforces this check at session start. **Git Bash PATH corruption fix:** If activating venv produces garbled paths, run `python setup.py` — it patches the activate script to use forward slashes instead of Windows backslashes.
```

### Step 6: Update RECOMMENDATIONS.md

Mark the following items as resolved in `docs/RECOMMENDATIONS.md`:

1. Find the row containing `plan.prompt.md Step 8 has two identical "Platform compatibility check" blocks` and change its Status from `Open` to `Resolved 2026-03-28 — removed duplicate block`

2. Find the row containing `plan_audit.py` calls `logger.debug()` but no logging is configured` and change its Status from `Open` to `Resolved 2026-03-28 — added logging.basicConfig()`

3. Add a new row to the Closed Recommendations section:
```markdown
| 2026-03-28 | Venv activate script Git Bash incompatibility | Fixed in setup.py — `fix_venv_activate_for_git_bash()` converts backslashes to forward slashes |
```

### Step 7: Run tests

Run `pytest tests/` and verify all tests pass, including the new `tests/test_setup.py`.

### Step 8: Run validate.py

Run `python scripts/validate.py` and verify it exits 0.

### Step 9: Apply the fix to current venv

Run `python setup.py` to apply the fix to the current `.venv/Scripts/activate` file.

Verify the fix by checking the activate script:
```bash
grep "VIRTUAL_ENV=" .venv/Scripts/activate
```

Expected output should show forward slashes:
```
VIRTUAL_ENV="/c/Users/bblake/Git Repos/agent-platform/.venv"
```

### Step 10: Test venv activation end-to-end

Deactivate and reactivate the venv to verify the fix works:
```bash
deactivate
source .venv/Scripts/activate
python -c "import sys; print(sys.executable)"
```

The output should show the correct venv Python path without PATH corruption.

### Step 11: Report implementation summary

Report what was implemented and any design decisions made during implementation.
