"""Tests for validate_instruction_architecture_layers()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.contracts.validate_instruction_architecture_layers import validate_instruction_architecture_layers


class TestValidateInstructionArchitectureLayers:
    """Tests for validate_instruction_architecture_layers()."""

    def test_passes_when_all_layers_resolve(self, tmp_path: Path) -> None:
        """No failures when every layer's content_locations resolves."""
        mock_compliance = MagicMock()
        mock_compliance._load_instruction_architecture.return_value = {
            "layers": [{"layer": 1, "name": "Universal rules", "content_locations": []}]
        }
        mock_compliance.check_layer_compliance.return_value = []

        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=mock_compliance,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert failed == []

    def test_fails_when_layer_glob_unresolved(self, tmp_path: Path) -> None:
        """Appends to failed list when a layer glob resolves to nothing."""
        mock_compliance = MagicMock()
        mock_compliance._load_instruction_architecture.return_value = {"layers": []}
        mock_compliance.check_layer_compliance.return_value = ["layer 99 (Ghost): no files match 'ghost/*.md'"]

        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=mock_compliance,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert len(failed) == 1
        assert "Instruction architecture layer claims" in failed[0]

    def test_skips_when_compliance_not_found(self) -> None:
        """No failures when prompt_compliance.py is absent."""
        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=None,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert failed == []
