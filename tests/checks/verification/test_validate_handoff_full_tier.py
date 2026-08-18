"""Tests for validate_handoff_full_tier() (rec-2965 remediation, Decision 163).

TestHandoffFullTier exercises the check's diff-scoping and handoff_policy semantics via the
changed_files/root/load_plan injection seams -- load_plan is stubbed with a plain fake object
(no real plan-schema fixture needed, since this check only reads .handoff_policy and
.verification_plan[].command). TestFullTierMatcher pins the matcher against the four
discrimination cases named in the plan's verification_plan step 5, including the two real
committed plans that motivate this check (PLAN-esb-fallback-spec-carrier.yaml, PR #836) and
this plan itself (PLAN-coverage-gate-handoff-integrity.yaml).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.checks import _common, registry
from scripts.checks.verification.validate_handoff_full_tier import (
    _SHELL_SEPARATOR_RE,
    _has_full_tier_step,
    _is_full_tier_segment,
    validate_handoff_full_tier,
)
from scripts.roadmap.plan_document import load as load_plan_doc


def _fake_doc(handoff: bool, commands: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        handoff_policy=SimpleNamespace() if handoff else None,
        verification_plan=[SimpleNamespace(command=c) for c in commands],
    )


def _touch_plan(root: Path, slug: str) -> str:
    rel = f"docs/plans/PLAN-{slug}.yaml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder: true\n", encoding="utf-8")
    return rel


class TestHandoffFullTier:
    def test_plan_without_full_tier_step_fails(self, tmp_path: Path) -> None:
        rel = _touch_plan(tmp_path, "hft-noncompliant")
        doc = _fake_doc(handoff=True, commands=["bin/venv-python -m scripts.validate --pre"])
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[rel], root=tmp_path, load_plan=lambda r, root: doc)
        assert any("hft-noncompliant" in f and "no verification_plan step invokes the full tier" in f for f in failed)

    def test_plan_with_full_tier_step_passes(self, tmp_path: Path) -> None:
        rel = _touch_plan(tmp_path, "hft-compliant")
        doc = _fake_doc(handoff=True, commands=["bin/venv-python -m scripts.validate"])
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[rel], root=tmp_path, load_plan=lambda r, root: doc)
        assert failed == []

    def test_plan_outside_diff_is_untouched(self, tmp_path: Path) -> None:
        """A plan present on disk but not named in changed_files is never loaded or evaluated,
        even though it would fail if it were."""
        _touch_plan(tmp_path, "hft-historical")

        def _must_not_load(_rel: str, _root: Path) -> None:
            raise AssertionError("load_plan must not be called for a plan outside the diff")

        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=["scripts/unrelated.py"], root=tmp_path, load_plan=_must_not_load)
        assert failed == []

    def test_empty_plan_diff_is_noop(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[], root=tmp_path)
        assert failed == []

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=["docs/plans/PLAN-hft-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_plan_without_handoff_policy_is_skipped(self, tmp_path: Path) -> None:
        rel = _touch_plan(tmp_path, "hft-no-handoff")
        doc = _fake_doc(handoff=False, commands=[])
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[rel], root=tmp_path, load_plan=lambda r, root: doc)
        assert failed == []

    def test_import_error_on_load_fails(self, tmp_path: Path) -> None:
        rel = _touch_plan(tmp_path, "hft-importerror")

        def _raise_import_error(_rel: str, _root: Path) -> None:
            raise ImportError("boom")

        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[rel], root=tmp_path, load_plan=_raise_import_error)
        assert any("could not import" in f for f in failed)

    def test_generic_load_error_is_skipped(self, tmp_path: Path) -> None:
        rel = _touch_plan(tmp_path, "hft-loaderror")

        def _raise_value_error(_rel: str, _root: Path) -> None:
            raise ValueError("malformed plan")

        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[rel], root=tmp_path, load_plan=_raise_value_error)
        assert failed == []

    def test_default_seams_use_common(self, tmp_path: Path) -> None:
        """No injected seams -- exercises the _common.ROOT / get_changed_files / load_plan defaults."""
        failed: list[str] = []
        validate_handoff_full_tier(failed, changed_files=[], root=tmp_path, load_plan=lambda r, root: None)
        assert failed == []

    def test_tier_membership(self) -> None:
        """The registry-wiring assertion that fails without the registry.py change."""
        name = "validate_handoff_full_tier"
        pre = {s.name for s in registry.pre_sequence() if s.kind == "check"}
        full = {s.name for s in registry.full_sequence() if s.kind == "check"}
        assert name in pre
        assert name in full


class TestDeclarationAdoption:
    """Decision 170 touch-it-fix-it: this check was baselined (no declaration) before this
    plan; editing it now obligates a registry.examined() declaration on BOTH of its reachable
    exit paths -- the empty diff-present-plan-set early return, and the loop fall-through."""

    def test_declaration_examined_zero_when_no_plan_in_diff(self, tmp_path: Path) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_handoff_full_tier(failed, changed_files=["scripts/unrelated.py"], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "declared_plans"

    def test_declaration_examined_counts_fallthrough_plans(self, tmp_path: Path) -> None:
        rel_a = _touch_plan(tmp_path, "hft-decl-a")
        rel_b = _touch_plan(tmp_path, "hft-decl-b")
        doc = _fake_doc(handoff=True, commands=["bin/venv-python -m scripts.validate"])
        failed: list[str] = []
        registry.pop_declaration()
        validate_handoff_full_tier(failed, changed_files=[rel_a, rel_b], root=tmp_path, load_plan=lambda r, root: doc)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 2
        assert declaration.unit == "declared_plans"
        assert failed == []


class TestFullTierMatcher:
    def test_plan_esb_fallback_spec_carrier_is_non_compliant(self) -> None:
        doc = load_plan_doc(_common.ROOT / "docs" / "plans" / "PLAN-esb-fallback-spec-carrier.yaml")
        assert not _has_full_tier_step(doc)

    def test_this_plan_is_compliant(self) -> None:
        doc = load_plan_doc(_common.ROOT / "docs" / "plans" / "PLAN-coverage-gate-handoff-integrity.yaml")
        assert _has_full_tier_step(doc)

    def test_chained_pre_and_full_is_accepted(self) -> None:
        command = "bin/venv-python -m scripts.validate --pre && bin/venv-python -m scripts.validate"
        assert any(_is_full_tier_segment(seg) for seg in _SHELL_SEPARATOR_RE.split(command))

    def test_bare_python_import_does_not_match(self) -> None:
        command = 'bin/venv-python -c "import scripts.validate as v"'
        assert not any(_is_full_tier_segment(seg) for seg in _SHELL_SEPARATOR_RE.split(command))
