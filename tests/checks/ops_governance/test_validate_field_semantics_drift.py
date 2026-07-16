"""Tests for validate_field_semantics_drift() -- the T2.33 fail-closed drift gate."""

from pathlib import Path

from scripts.checks._common import ROOT
from scripts.checks.ops_governance.validate_field_semantics_drift import validate_field_semantics_drift


class TestFieldSemanticsDriftGate:
    """Tests for validate_field_semantics_drift() -- the T2.33 fail-closed drift gate."""

    def test_passes_when_committed_matches_generator(self, tmp_path: Path) -> None:
        """If the committed file matches what the generator would produce: no failure."""
        import importlib.util as _ilu

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        # Write the exact generator output to tmp_path
        output = tmp_path / "field_semantics.yaml"
        output.write_text(gen._emit_yaml(gen.generate(include_prose=False)), encoding="utf-8")

        import unittest.mock as _m

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)
        assert failed == [], f"Expected no failure but got: {failed}"

    def test_fails_when_committed_has_drift(self, tmp_path: Path) -> None:
        """If the committed file has extra content vs the generator output: failure appended."""
        import importlib.util as _ilu
        import unittest.mock as _m

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen2", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        output = tmp_path / "field_semantics.yaml"
        output.write_text(
            gen._emit_yaml(gen.generate(include_prose=False)) + "\n# injected drift\n",
            encoding="utf-8",
        )

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)
        assert len(failed) == 1, f"Expected exactly one failure but got: {failed}"
        assert "drift" in failed[0].lower() or "Field semantics" in failed[0]

    def test_does_not_auto_write_on_drift(self, tmp_path: Path) -> None:
        """The drift gate MUST NOT auto-write (Decision 55)."""
        import importlib.util as _ilu
        import unittest.mock as _m

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen3", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        injected = gen._emit_yaml(gen.generate(include_prose=False)) + "\n# injected drift\n"
        output = tmp_path / "field_semantics.yaml"
        output.write_text(injected, encoding="utf-8")

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)

        assert output.read_text(encoding="utf-8") == injected, (
            "validate_field_semantics_drift must NOT auto-write the file (Decision 55 fail-closed)"
        )
