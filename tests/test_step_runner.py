"""Unit tests for scripts/executor/step_runner.py."""

from __future__ import annotations

from pathlib import Path

from scripts.executor.step_runner import gather_step_context


class TestGatherStepContext:
    """Tests for gather_step_context()."""

    def test_gather_step_context_with_fallback(self, tmp_path: Path) -> None:
        """Test fallback works when step has no file but
        recommendation_target_file is provided.
        """
        target_file = tmp_path / "test_target.py"
        target_file.write_text("def example(): pass", encoding="utf-8")

        step = {"action": "modify"}
        result = gather_step_context(step, recommendation_target_file=str(target_file))

        assert result["file_content"] != ""
        assert "def example()" in result["file_content"]

    def test_gather_step_context_returns_empty_when_no_file(self) -> None:
        """Test returns empty dict when both step file and
        recommendation_target_file are missing.
        """
        step = {"action": "modify"}
        result = gather_step_context(step, recommendation_target_file="")

        assert result["file_content"] == ""
        assert result["test_content"] == ""
        assert result["pattern_content"] == ""

    def test_gather_step_context_explicit_file_takes_precedence(self, tmp_path: Path) -> None:
        """Test step's explicit file field takes precedence over
        recommendation_target_file.
        """
        explicit_file = tmp_path / "explicit.py"
        explicit_file.write_text("# explicit content", encoding="utf-8")

        fallback_file = tmp_path / "fallback.py"
        fallback_file.write_text("# fallback content", encoding="utf-8")

        step = {"action": "modify", "file": str(explicit_file)}
        result = gather_step_context(step, recommendation_target_file=str(fallback_file))

        assert "# explicit content" in result["file_content"]
        assert "# fallback content" not in result["file_content"]
