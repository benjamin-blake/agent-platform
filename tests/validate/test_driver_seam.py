"""Guards for the derived pre_sequence_stub selector and the injection seam it relies on
(Decision 131 clause 3 / PR1 of the _neutralized_pre_registry retirement).

TestSelectorFidelity: select_steps() raises on an absent check/scaffold name, returns TIER
order rather than requested order, and patching scripts.checks.registry.pre_sequence
intercepts dispatch bidirectionally (a selected check dispatches; an unselected real-tier
check does not).

TestFixtureHoming: the tests/validate/ factory fixture is package-scoped and non-autouse.

TestRegistryRows: no in-scope graduated row still references the retired fixture, the retired
row itself is gone (not rewritten), and every in-scope node_id still collects under pytest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks import registry
from tests.fixtures.pre_sequence_stub import UnknownStepError, select_steps
from tests.fixtures.validate_module import _validate

_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _ROOT / "config" / "agent" / "verification_registry" / "registry.yaml"

IN_SCOPE_PATHS = frozenset(
    {
        "tests/fixtures/pre_sequence_stub.py",
        "tests/validate/conftest.py",
        "tests/conftest.py",
        "tests/validate/test_driver_seam.py",
        "tests/validate/test_tiers.py",
        "tests/validate/test_budget.py",
        "tests/validate/test_manifest_isolation.py",
        "tests/checks/roadmap/test_check_graduation_guard.py",
        "tests/test_plan_document.py",
        "tests/test_ci_claude_p_retry.py",
        "config/agent/verification_registry/registry.yaml",
        # Decision 169 (PLAN-validate-facade-manifest-dispatch): this plan's own scope, PLUS
        # scripts/checks/_common.py -- a guard_target of graduated rows this PR touches but not
        # itself a scope row -- PLUS tests/validate/test_scaffold_gates.py, which PR1 omitted.
        # NOTE: config/ci_rca_taxonomy.yaml is deliberately excluded -- this plan's edit there is
        # purely additive (one new function_to_category entry) and cannot orphan any existing
        # graduated row; including it would only surface an unrelated, pre-existing stale node_id
        # (tests/test_ci_rca_taxonomy.py, renamed to tests/checks/ci_guards/
        # test_validate_ci_rca_taxonomy.py before this plan) that already exists on origin/main.
        "config/coverage_baseline.yaml",
        "config/sloc_budgets.yaml",
        "docs/DECISIONS.md",
        "docs/contracts/check-manifest.yaml",
        "docs/contracts/file-router.yaml",
        "docs/decisions-index.json",
        "scripts/CLAUDE.md",
        "scripts/checks/_common.py",
        "scripts/checks/_schema.py",
        "scripts/checks/ci_guards/_manifest.py",
        "scripts/checks/contracts/_manifest.py",
        "scripts/checks/decisions/_manifest.py",
        "scripts/checks/deps/_manifest.py",
        "scripts/checks/deps/validate_check_manifests.py",
        "scripts/checks/executor/_manifest.py",
        "scripts/checks/hygiene/_manifest.py",
        "scripts/checks/iam_tf/_manifest.py",
        "scripts/checks/lambda_pkg/_manifest.py",
        "scripts/checks/misc/_manifest.py",
        "scripts/checks/ops_governance/_manifest.py",
        "scripts/checks/product/_manifest.py",
        "scripts/checks/prompts/_manifest.py",
        "scripts/checks/prose/_manifest.py",
        "scripts/checks/registry.py",
        "scripts/checks/roadmap/_manifest.py",
        "scripts/checks/sloc/_manifest.py",
        "scripts/checks/structural/_manifest.py",
        "scripts/checks/typing/_manifest.py",
        "scripts/checks/validation_result.py",
        "scripts/checks/verification/_manifest.py",
        "scripts/test_coverage_checker.py",
        "scripts/validate.py",
        "tests/checks/_common/__init__.py",
        "tests/checks/_common/test_primitives.py",
        "tests/checks/_common/test_push_context_base.py",
        "tests/checks/ci_guards/test__manifest.py",
        "tests/checks/contracts/test__manifest.py",
        "tests/checks/contracts/test_validate_data_model_standard.py",
        "tests/checks/contracts/validate_contract_drift/conftest.py",
        "tests/checks/decisions/test__manifest.py",
        "tests/checks/decisions/test_conformance_registration.py",
        "tests/checks/deps/test__manifest.py",
        "tests/checks/deps/test_validate_check_manifests.py",
        "tests/checks/executor/test__manifest.py",
        "tests/checks/hygiene/test__manifest.py",
        "tests/checks/iam_tf/test__manifest.py",
        "tests/checks/lambda_pkg/test__manifest.py",
        "tests/checks/misc/test__manifest.py",
        "tests/checks/misc/test_coverage_baseline.py",
        "tests/checks/ops_governance/test__manifest.py",
        "tests/checks/ops_governance/test_validate_pydantic_yaml_drift.py",
        "tests/checks/product/test__manifest.py",
        "tests/checks/prompts/test__manifest.py",
        "tests/checks/prose/test__manifest.py",
        "tests/checks/registry/__init__.py",
        "tests/checks/registry/test_check_metadata.py",
        "tests/checks/registry/test_manifest_contracts.py",
        "tests/checks/registry/test_resolution.py",
        "tests/checks/registry/test_sequences.py",
        "tests/checks/roadmap/test__manifest.py",
        "tests/checks/roadmap/test_validate_tier_floor.py",
        "tests/checks/sloc/test__manifest.py",
        "tests/checks/sloc/test_sloc_limits.py",
        "tests/checks/structural/test__manifest.py",
        "tests/checks/test__schema.py",
        "tests/checks/test_validation_result.py",
        "tests/checks/typing/test__manifest.py",
        "tests/checks/verification/test__manifest.py",
        "tests/checks/verification/test_validate_handoff_full_tier.py",
        "tests/test_checks_registry.py",
        "tests/test_checks_registry_test_obligations.py",
        "tests/test_coverage_checker/test_coverage_checker_map.py",
        "tests/validate/test_failed_check_attribution.py",
        "tests/validate/test_scaffold_gates.py",
    }
)


class TestSelectorFidelity:
    """select_steps() derives from the live registry -- it never hand-authors a Step."""

    def test_raises_on_absent_check_name(self) -> None:
        with pytest.raises(UnknownStepError):
            select_steps(checks=("this_check_does_not_exist",))

    def test_raises_on_unknown_scaffold(self) -> None:
        with pytest.raises(UnknownStepError):
            select_steps(scaffolds=("this_scaffold_does_not_exist",))

    def test_returns_tier_order_not_requested_order(self) -> None:
        """validate_cc_limits precedes validate_sloc_limits in the live pre_sequence; requesting
        them in the opposite order must not reorder the returned Steps."""
        live_names = [s.name for s in registry.pre_sequence() if s.kind == "check"]
        assert live_names.index("validate_cc_limits") < live_names.index("validate_sloc_limits")

        steps = select_steps(checks=("validate_sloc_limits", "validate_cc_limits"), scaffolds=())
        assert [s.name for s in steps] == ["validate_cc_limits", "validate_sloc_limits"]

    def test_selected_steps_are_real_step_objects_with_real_pre_globs(self) -> None:
        (step,) = select_steps(checks=("validate_cc_limits",), scaffolds=())
        live = {s.name: s for s in registry.pre_sequence() if s.kind == "check"}
        assert step == live["validate_cc_limits"]
        assert step.pre_globs == ("**/*.py",)

    def test_dispatch_is_bidirectional(self) -> None:
        """Patching registry.pre_sequence to the derived subset means a selected check
        dispatches and a real-tier check absent from the selection does not."""
        steps = select_steps(checks=("validate_sloc_limits",), scaffolds=())
        called: list[str] = []

        with (
            patch.object(registry, "pre_sequence", return_value=steps),
            patch(
                "scripts.checks.sloc.sloc_limits.validate_sloc_limits",
                side_effect=lambda failed: called.append("validate_sloc_limits"),
            ),
            patch(
                "scripts.checks.sloc.cc_limits.validate_cc_limits",
                side_effect=lambda failed: called.append("validate_cc_limits"),
            ),
        ):
            failed: list[str] = []
            for step in registry.pre_sequence():
                if step.kind == "check":
                    _validate._dispatch_check(step.name, failed)

        assert called == ["validate_sloc_limits"], (
            "a check absent from the derived selection must never dispatch, and a selected check must dispatch exactly once"
        )


class TestFixtureHoming:
    """Decision 131 clause 3: the factory lives package-scoped and non-autouse."""

    def test_factory_is_package_scoped_and_not_autouse(self) -> None:
        from tests.validate.conftest import pre_sequence_stub

        marker = pre_sequence_stub._fixture_function_marker
        assert marker.scope == "package"
        assert marker.autouse is False


class TestRegistryRows:
    """No graduated row survives in name while guarding a retired premise."""

    @staticmethod
    def _rows() -> list[dict]:
        data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data["entries"]

    @staticmethod
    def _in_scope_rows(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r.get("guard_target") in IN_SCOPE_PATHS]

    @staticmethod
    def _collectible_node_ids(rows: list[dict]) -> list[str]:
        node_ids: list[str] = []
        for row in rows:
            spec = row.get("check_spec") or {}
            node_id = spec.get("node_id")
            if node_id:
                node_ids.append(node_id)
                continue
            command = spec.get("command") or []
            for i, token in enumerate(command):
                if isinstance(token, str) and token.endswith("pytest"):
                    for arg in command[i + 1 :]:
                        if isinstance(arg, str) and not arg.startswith("-"):
                            node_ids.append(arg)
                            break
                    break
        return node_ids

    def test_retired_fixture_row_is_gone_not_rewritten(self) -> None:
        check_ids = {r["check_id"] for r in self._rows()}
        assert "graduation-guard-pre-registry-neutralized" not in check_ids

    def test_no_in_scope_row_references_the_retired_fixture(self) -> None:
        in_scope = self._in_scope_rows(self._rows())
        assert in_scope, "expected at least one graduated row targeting an in-scope path"
        for row in in_scope:
            assert "_neutralized_pre_registry" not in json.dumps(row), row["check_id"]

    def test_in_scope_node_ids_still_collect_under_pytest(self) -> None:
        in_scope = self._in_scope_rows(self._rows())
        node_ids = self._collectible_node_ids(in_scope)
        assert node_ids, "expected at least one collectible node_id among in-scope rows"

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *node_ids],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
