"""plan prompt-load / step-parse tests: load_prompt, parse_steps_from_plan (rec-2709 Wave 5)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.executor.plan as plan_mod
from scripts.executor.plan import load_prompt, parse_steps_from_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAN_TEXT = """\
### Step 1: Create the module
**File**: scripts/executor/errors.py
**Action**: create
**Description**: Add error types for the executor package.
**Acceptance**: `python -c "from scripts.executor.errors import ExecutorError"`

### Step 2: Update init
**File**: scripts/executor/__init__.py
**Action**: modify
**Description**: Re-export all public symbols.
**Acceptance**: `python -c "import scripts.executor"`
"""


class TestLoadPrompt:
    """Tests for load_prompt()."""

    def test_loads_template_and_returns_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "planning.prompt.md"
        prompt_file.write_text("Hello {rec_id}", encoding="utf-8")

        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            template, prompt_hash = load_prompt("planning")

        assert template == "Hello {rec_id}"
        expected_hash = hashlib.sha256(b"Hello {rec_id}").hexdigest()[:12]
        assert prompt_hash == expected_hash

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        with patch.object(plan_mod, "PROMPTS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                load_prompt("nonexistent")

    def test_hash_is_12_hex_chars(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "p.prompt.md").write_text("content", encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h = load_prompt("p")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        content = "deterministic content"
        (prompts_dir / "q.prompt.md").write_text(content, encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h1 = load_prompt("q")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h2 = load_prompt("q")
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "a.prompt.md").write_text("content A", encoding="utf-8")
        (prompts_dir / "b.prompt.md").write_text("content B", encoding="utf-8")
        with patch.object(plan_mod, "PROMPTS_DIR", prompts_dir):
            _, h_a = load_prompt("a")
            _, h_b = load_prompt("b")
        assert h_a != h_b


class TestParseStepsFromPlan:
    """Tests for parse_steps_from_plan()."""

    def test_parses_two_steps(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert len(steps) == 2

    def test_step_numbers_correct(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["n"] == 1
        assert steps[1]["n"] == 2

    def test_step_titles_correct(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert "Create the module" in steps[0]["title"]
        assert "Update init" in steps[1]["title"]

    def test_step_files_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["file"] == "scripts/executor/errors.py"
        assert steps[1]["file"] == "scripts/executor/__init__.py"

    def test_step_actions_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert steps[0]["action"] == "create"
        assert steps[1]["action"] == "modify"

    def test_acceptance_parsed(self) -> None:
        steps = parse_steps_from_plan(_PLAN_TEXT)
        assert "ExecutorError" in steps[0]["acceptance"]

    def test_empty_plan_returns_empty_list(self) -> None:
        assert parse_steps_from_plan("") == []

    def test_fallback_numbered_list(self) -> None:
        numbered = "1. First task\n2. Second task\n3. Third task\n"
        steps = parse_steps_from_plan(numbered)
        assert len(steps) == 3
        assert steps[0]["title"] == "First task"
        assert steps[0]["action"] == "modify"

    def test_steps_sorted_by_n(self) -> None:
        inverted = """\
### Step 3: Third
**File**: c.py
**Action**: modify
**Description**: desc c
**Acceptance**: ``

### Step 1: First
**File**: a.py
**Action**: create
**Description**: desc a
**Acceptance**: ``
"""
        steps = parse_steps_from_plan(inverted)
        assert steps[0]["n"] == 1
        assert steps[1]["n"] == 3

    def test_file_backticks_stripped(self) -> None:
        text = (
            "### Step 1: Setup\n"
            "**File**: `scripts/foo.py`\n"
            "**Action**: create\n"
            "**Description**: make\n"
            "**Acceptance**: `echo ok`\n"
        )
        steps = parse_steps_from_plan(text)
        assert steps[0]["file"] == "scripts/foo.py"

    def test_dedup_prefers_complete_over_empty(self) -> None:
        """When step N appears twice, prefer the one with file+acceptance populated."""
        text = """\
### Step 1: First attempt (incomplete)
**File**:
**Action**: create
**Description**: desc
**Acceptance**:

### Step 1: Second attempt (complete)
**File**: scripts/foo.py
**Action**: create
**Description**: desc
**Acceptance**: `echo ok`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        assert steps[0]["file"] == "scripts/foo.py"
        assert steps[0]["acceptance"] == "`echo ok`"

    def test_dedup_prefers_first_complete_over_later_complete(self) -> None:
        """When both duplicates are complete, keep the first one."""
        text = """\
### Step 1: First
**File**: scripts/first.py
**Action**: create
**Description**: first desc
**Acceptance**: `python first.py`

### Step 1: Second
**File**: scripts/second.py
**Action**: modify
**Description**: second desc
**Acceptance**: `python second.py`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        assert steps[0]["file"] == "scripts/first.py"
        assert steps[0]["acceptance"] == "`python first.py`"

    def test_dedup_empty_stays_empty_when_all_empty(self) -> None:
        """When all duplicates are empty, keep the first one."""
        text = """\
### Step 1: First
**File**:
**Action**: create
**Description**: desc
**Acceptance**:

### Step 1: Second
**File**:
**Action**: modify
**Description**: desc
**Acceptance**:
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 1
        # When file is empty (just ": " with nothing), the regex captures nothing useful
        # and stripping returns empty string
        assert steps[0]["action"] == "create"  # Verify first one is kept

    def test_dedup_multiple_step_numbers(self) -> None:
        """Deduplication works independently for each step number."""
        text = """\
### Step 1: First attempt
**File**:
**Action**: create
**Description**: desc1
**Acceptance**:

### Step 1: Complete
**File**: foo.py
**Action**: create
**Description**: desc1
**Acceptance**: `python foo.py`

### Step 2: First attempt
**File**:
**Action**: modify
**Description**: desc2
**Acceptance**:

### Step 2: Complete
**File**: bar.py
**Action**: modify
**Description**: desc2
**Acceptance**: `python bar.py`
"""
        steps = parse_steps_from_plan(text)
        assert len(steps) == 2
        assert steps[0]["n"] == 1
        assert steps[0]["file"] == "foo.py"
        assert steps[1]["n"] == 2
        assert steps[1]["file"] == "bar.py"

    def test_rejects_malformed_file_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """File values with markdown bold markers are rejected and set to empty."""
        text = """\
### Step 1: Test malformed file detection
**File**: **Action**: create
**Action**: create
**Description**: This should be rejected due to malformed file value
**Acceptance**: `python test.py`

### Step 2: Test partial markdown artifact
**File**: path/to/**file**.py
**Action**: modify
**Description**: This should also be rejected due to bold markers in path
**Acceptance**: `python test2.py`

### Step 3: Valid file path
**File**: valid/path.py
**Action**: modify
**Description**: This should be accepted
**Acceptance**: `python valid.py`
"""
        with caplog.at_level("WARNING"):
            steps = parse_steps_from_plan(text)

        assert len(steps) == 3

        # Step 1: File value starting with ** should be rejected
        assert steps[0]["n"] == 1
        assert steps[0]["file"] == ""  # Should be empty due to malformed value

        # Step 2: File value containing ** should be rejected
        assert steps[1]["n"] == 2
        assert steps[1]["file"] == ""  # Should be empty due to bold markers

        # Step 3: Valid file path should be accepted
        assert steps[2]["n"] == 3
        assert steps[2]["file"] == "valid/path.py"

        # Check warning logs were generated
        assert len(caplog.records) == 2
        assert "malformed file value" in caplog.records[0].message.lower()
        assert "**Action**: create" in caplog.records[0].message
        assert "malformed file value" in caplog.records[1].message.lower()
        assert "**file**" in caplog.records[1].message
