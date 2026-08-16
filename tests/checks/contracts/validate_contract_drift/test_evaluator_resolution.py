"""VP step 2: evaluator resolution by evidence of READING, not mention -- both verified poles,
plus sequencing and indirection cases.

Exercises scripts.checks.contracts._population.resolve_evaluator directly (the unit under test),
against REAL registered checks for the two verified poles named in the plan's acceptance
criteria: validate_placement/file-router.yaml (executable literal at validate_placement.py:19)
and validate_sloc_budget_raises/marker-grammar.yaml (only a docstring + `#` comment mention, via
its one-hop `scripts.checks._marker_guard` import).
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks.contracts import _population
from scripts.contracts_schema import EvaluatorSpec

_ROOT = Path(__file__).resolve().parents[4]


class TestEvaluatorResolution:
    def test_validate_placement_file_router_resolves(self) -> None:
        resolves, detail = _population.resolve_evaluator(
            "file-router.yaml", EvaluatorSpec(check="validate_placement"), root=_ROOT
        )
        assert resolves, detail

    def test_marker_guard_marker_grammar_does_not_resolve(self) -> None:
        # A docstring mention and a `#` comment mention are the ONLY occurrences of
        # "marker-grammar.yaml" in scripts/checks/_marker_guard.py -- neither is executable
        # context, so a check whose one-hop import is _marker_guard must NOT resolve against it.
        resolves, detail = _population.resolve_evaluator(
            "marker-grammar.yaml", EvaluatorSpec(check="validate_sloc_budget_raises"), root=_ROOT
        )
        assert not resolves, detail

    def test_registered_but_unsequenced_check_fails(self) -> None:
        resolves, detail = _population.resolve_evaluator(
            "file-router.yaml",
            EvaluatorSpec(check="fake_registered_check"),
            root=_ROOT,
            registered_checks={"fake_registered_check": object()},
            sequenced_names=set(),
        )
        assert not resolves
        assert "not sequenced" in detail

    def test_unknown_check_name_fails(self) -> None:
        resolves, detail = _population.resolve_evaluator(
            "file-router.yaml",
            EvaluatorSpec(check="totally_unknown_check"),
            root=_ROOT,
            registered_checks={},
            sequenced_names=set(),
        )
        assert not resolves
        assert "not a registered check" in detail

    def test_one_hop_imported_module_carrying_the_literal_passes(self, tmp_path) -> None:
        # one_hop_scripts_imports only follows absolute `scripts.*` imports (the real convention
        # every check module uses), so the synthetic fixture mirrors that shape under a fake root.
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.py").write_text('_TARGET = "some-contract.yaml"\n', encoding="utf-8")
        (scripts_dir / "primary.py").write_text(
            '"""A module whose own body never mentions the contract."""\nfrom scripts import helper  # noqa: F401\n',
            encoding="utf-8",
        )
        resolves, detail = _population.resolve_evaluator(
            "some-contract.yaml",
            EvaluatorSpec(check="synthetic_check"),
            root=tmp_path,
            registered_checks={"synthetic_check": object()},
            sequenced_names={"synthetic_check"},
            check_module_resolver=lambda _name: scripts_dir / "primary.py",
        )
        assert resolves, detail
        assert "one-hop import" in detail

    def test_own_module_docstring_mention_does_not_resolve(self, tmp_path) -> None:
        (tmp_path / "primary.py").write_text(
            '"""Reads docs/contracts/some-contract.yaml for configuration."""\n'
            "# also mentioned here: some-contract.yaml\n"
            "VALUE = 1\n",
            encoding="utf-8",
        )
        resolves, detail = _population.resolve_evaluator(
            "some-contract.yaml",
            EvaluatorSpec(check="synthetic_check"),
            root=tmp_path,
            registered_checks={"synthetic_check": object()},
            sequenced_names={"synthetic_check"},
            check_module_resolver=lambda _name: tmp_path / "primary.py",
        )
        assert not resolves, detail

    def test_agent_surface_evaluator_resolves_when_target_mentions_basename(self, tmp_path) -> None:
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text("This skill reads some-contract.yaml directly.\n", encoding="utf-8")
        resolves, detail = _population.resolve_evaluator(
            "some-contract.yaml", EvaluatorSpec(agent_surface="SKILL.md"), root=tmp_path
        )
        assert resolves, detail

    def test_agent_surface_evaluator_fails_when_target_missing_or_silent(self, tmp_path) -> None:
        resolves, _detail = _population.resolve_evaluator(
            "some-contract.yaml", EvaluatorSpec(agent_surface="MISSING.md"), root=tmp_path
        )
        assert not resolves

        present = tmp_path / "SILENT.md"
        present.write_text("No mention of the target here.\n", encoding="utf-8")
        resolves2, _detail2 = _population.resolve_evaluator(
            "some-contract.yaml", EvaluatorSpec(agent_surface="SILENT.md"), root=tmp_path
        )
        assert not resolves2

    def test_exact_equality_not_substring(self, tmp_path) -> None:
        (tmp_path / "primary.py").write_text('_TARGET = "my-file-router.yaml"\n', encoding="utf-8")
        resolves, _detail = _population.resolve_evaluator(
            "file-router.yaml",
            EvaluatorSpec(check="synthetic_check"),
            root=tmp_path,
            registered_checks={"synthetic_check": object()},
            sequenced_names={"synthetic_check"},
            check_module_resolver=lambda _name: tmp_path / "primary.py",
        )
        assert not resolves
