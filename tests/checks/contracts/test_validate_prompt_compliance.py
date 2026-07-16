"""Tests for validate_prompt_compliance()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.contracts.validate_prompt_compliance import validate_prompt_compliance


class TestValidatePromptCompliance:
    """Tests for validate_prompt_compliance()."""

    def test_passes_when_no_violations(self, tmp_path: Path) -> None:
        """No failures when compliance checker reports no violations (YAML-sourced discovery)."""
        skill_dir = tmp_path / ".claude" / "skills" / "implement"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "## Behavioural Invariants\n```yaml\nretro_lite_per_step: true\n```\n",
            encoding="utf-8",
        )

        mock_compliance = MagicMock()
        mock_compliance.get_behavioural_invariant_sources.return_value = [".claude/skills/*/SKILL.md"]
        mock_compliance.parse_invariants.return_value = {"retro_lite_per_step": True}
        mock_compliance.parse_retro_lite_log.return_value = []
        mock_compliance.parse_execution_state.return_value = None
        mock_compliance.check_retro_lite_compliance.return_value = []

        with (
            patch("scripts.checks.contracts.validate_prompt_compliance._load_prompt_compliance", return_value=mock_compliance),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_prompt_compliance(failed)

        assert failed == []

    def test_fails_when_violations_found(self, tmp_path: Path) -> None:
        """Appends to failed list when compliance violations are found (YAML-sourced discovery)."""
        skill_dir = tmp_path / ".claude" / "skills" / "implement"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "## Behavioural Invariants\n```yaml\nretro_lite_per_step: true\n```\n",
            encoding="utf-8",
        )

        mock_compliance = MagicMock()
        mock_compliance.get_behavioural_invariant_sources.return_value = [".claude/skills/*/SKILL.md"]
        mock_compliance.parse_invariants.return_value = {"retro_lite_per_step": True}
        mock_compliance.parse_retro_lite_log.return_value = []
        mock_compliance.parse_execution_state.return_value = {"total_steps": 5, "current_step": 1}
        mock_compliance.check_retro_lite_compliance.return_value = ["retro_lite_per_step: expected 5 entries, found 0"]

        with (
            patch("scripts.checks.contracts.validate_prompt_compliance._load_prompt_compliance", return_value=mock_compliance),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_prompt_compliance(failed)

        assert len(failed) == 1
        assert "Prompt compliance check" in failed[0]

    def test_skips_when_compliance_not_found(self) -> None:
        """No failures when prompt_compliance.py is absent."""
        with patch("scripts.checks.contracts.validate_prompt_compliance._load_prompt_compliance", return_value=None):
            failed: list[str] = []
            validate_prompt_compliance(failed)

        assert failed == []
