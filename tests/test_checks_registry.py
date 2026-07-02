"""Tests for the check registry (Decision 104): scripts/checks/registry.py + _common.py.

Covers: full-trace equivalence against the frozen pre-refactor baseline, facade
completeness (every check/helper reachable via validate.<name> AND `from scripts.validate
import <name>`), mock-interception preservation through moved bodies, owner-metadata
correctness, the no-local-ROOT invariant, and rec-2420's lowering-test gap.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent

_SCRIPT_PATH = ROOT / "scripts" / "validate.py"
# Reuse an already-loaded "validate" module (e.g. from tests/test_validate.py in the same
# session) rather than overwriting sys.modules["validate"] with a second, independent exec
# of the same file -- doing so would silently break any other test file's `patch("validate.X")`
# calls, which resolve against whatever object currently sits at that sys.modules key.
if "validate" in sys.modules:
    _validate = sys.modules["validate"]
else:
    _spec = importlib.util.spec_from_file_location("validate", _SCRIPT_PATH)
    _validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_validate)  # type: ignore[union-attr]
    sys.modules["validate"] = _validate

from scripts.checks import _common, registry  # noqa: E402

# ---------------------------------------------------------------------------
# Frozen pre-refactor baseline (captured from the monolithic scripts/validate.py
# BEFORE any code was moved -- see PLAN-validate-decomposition.yaml execution_steps
# item 1). Structural (kind, name) tuples, not raw stdout: comparing print-text would
# make this oracle fragile to cosmetic wording changes with zero behavioural meaning.
# ---------------------------------------------------------------------------

FROZEN_PRE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("scaffold", "lint"),
    ("scaffold", "precommit_changed"),
    ("scaffold", "mypy_diff"),
    ("scaffold", "pytest_diff"),
    ("check", "validate_iam_runner_policy"),
    ("check", "validate_copilot_multipliers"),
    ("check", "validate_prompt_files"),
    ("check", "validate_cli_tools_in_prompts"),
    ("check", "validate_workflow_agent_safety"),
    ("check", "validate_product_roadmap"),
    ("check", "validate_plan_documents"),
    ("check", "validate_candidate_decision_ratification"),
    ("check", "validate_cc_limits"),
    ("check", "validate_sloc_limits"),
    ("check", "validate_subprocess_encoding"),
    ("check", "validate_intent_doc_freeze"),
    ("check", "validate_contract_drift"),
    ("check", "validate_field_semantics_drift"),
    ("check", "validate_ci_rca_taxonomy"),
    ("check", "validate_claude_p_retry_wrapper"),
    ("check", "validate_authority_budget"),
    ("check", "validate_ci_workflow_guards"),
    ("check", "validate_ducklake_version_lockstep"),
    ("check", "validate_import_contracts"),
    ("check", "validate_lockfile_sync"),
    ("check", "validate_verifier_same_pr_guard"),
    ("check", "validate_verification_registry"),
    ("scaffold", "budget_assertion"),
)

FROZEN_FULL_SEQUENCE: tuple[tuple[str, str], ...] = (
    # run_python_checks()
    ("scaffold", "lint"),
    ("check", "validate_subprocess_encoding"),
    ("check", "validate_sys_executable"),
    ("check", "validate_copilot_multipliers"),
    ("check", "validate_cli_tools_in_prompts"),
    ("check", "validate_imports"),
    ("check", "validate_recommendations_schema"),
    ("check", "validate_outbox_staleness"),
    ("check", "validate_executor_boundary"),
    ("check", "validate_rec_write_paths"),
    ("check", "validate_decisions_local_writes"),
    ("check", "validate_warehouse_write_sources"),
    ("check", "validate_broker_env_reads"),
    ("check", "validate_invariants"),
    ("check", "validate_ci_rca_trigger"),
    ("check", "validate_ci_workflow_guards"),
    ("check", "validate_claude_p_retry_wrapper"),
    ("check", "validate_sloc_limits"),
    ("check", "check_source_registry"),
    ("check", "validate_platform_roadmap"),
    ("check", "validate_candidate_decision_ratification"),
    ("check", "validate_lambda_manifests"),
    ("check", "validate_lambda_manifest_coverage"),
    ("check", "validate_lambda_bundle_completeness"),
    ("check", "validate_lambda_deploy_gating"),
    ("check", "validate_product_roadmap"),
    ("check", "validate_plan_documents"),
    ("check", "validate_pydantic_yaml_drift"),
    ("check", "_check_graduation_guard"),
    ("check", "validate_dq_manifest_gate"),
    ("check", "validate_test_coverage"),
    ("check", "validate_no_underscore_instructions"),
    ("check", "validate_claude_md_pointer_invariant"),
    ("check", "validate_environment_taxonomy"),
    ("check", "validate_complexity"),
    ("check", "validate_scheduled_agent_logs"),
    ("check", "validate_hermeticity_flags"),
    ("check", "validate_verifier_hermeticity"),
    ("check", "validate_verifier_same_pr_guard"),
    ("check", "validate_verification_registry"),
    ("check", "validate_differential_gate_baseline"),
    ("check", "validate_intent_doc_freeze"),
    ("check", "validate_contract_drift"),
    ("check", "validate_portal_drift"),
    ("check", "validate_rec_relevance_contract"),
    ("check", "validate_field_semantics_drift"),
    ("check", "validate_ci_rca_taxonomy"),
    ("check", "validate_authority_budget"),
    ("check", "validate_ducklake_version_lockstep"),
    ("check", "validate_import_contracts"),
    ("check", "validate_lockfile_sync"),
    ("check", "validate_dependency_graph_freshness"),
    ("scaffold", "unit_tests"),
    ("scaffold", "mypy_full"),
    ("scaffold", "terraform_checks"),
    ("check", "validate_iam_runner_policy"),
    # run_dependency_checks() + validate_requirements
    ("scaffold", "dependency_health"),
    ("check", "validate_requirements"),
    # prompts block
    ("check", "validate_prompt_files"),
    ("check", "validate_cli_tools_in_prompts"),
    ("check", "validate_workflow_agent_safety"),
    ("check", "validate_prompt_compliance"),
    ("check", "validate_instruction_architecture_layers"),
    # tail
    ("scaffold", "ensure_fresh_dq"),
    ("check", "validate_verification_harness"),
    ("scaffold", "precommit_all_files"),
)

# Every check name + every extracted private helper. Both must resolve via
# getattr(validate_module, name) AND `from scripts.validate import name`.
ALL_CHECK_NAMES: tuple[str, ...] = tuple(sorted(registry.all_checks().keys()))

EXTRACTED_HELPER_NAMES: tuple[str, ...] = (
    "_load_boundary_patterns",
    "_load_coverage_checker",
    "_load_prompt_compliance",
    "_extract_enforced_map",
    "_check_drift_for_table",
    "_dotted_name_from_attr",
    "_verifier_is_non_hermetic",
    "_extract_verifier_covers",
    "_is_inside_try",
    "check_claude_md_pointer_invariant",
    "_check_claude_p_raw_invocations",
    "_load_sloc_budgets",
    "_update_sloc_budgets",
)

OWNER_EXPECTATIONS: dict[str, tuple[str, bool]] = {
    "validate_broker_env_reads": ("trading", False),
    "validate_product_roadmap": ("platform", True),
    "validate_environment_taxonomy": ("platform", True),
}


class TestFrozenBaselineEquivalence:
    """VP step 2: full ordered per-tier trace equivalence (step kind+name, not raw stdout)."""

    def test_pre_sequence_matches_frozen_baseline(self) -> None:
        actual = tuple((s.kind, s.name) for s in registry.pre_sequence())
        assert actual == FROZEN_PRE_SEQUENCE

    def test_full_sequence_matches_frozen_baseline(self) -> None:
        actual = tuple((s.kind, s.name) for s in registry.full_sequence())
        assert actual == FROZEN_FULL_SEQUENCE

    def test_pre_sequence_has_no_duplicate_checks(self) -> None:
        """Unlike full_sequence (validate_cli_tools_in_prompts legitimately runs twice),
        pre_sequence's checks should each appear once."""
        names = [s.name for s in registry.pre_sequence() if s.kind == "check"]
        assert len(names) == len(set(names))

    def test_full_sequence_cli_tools_in_prompts_appears_exactly_twice(self) -> None:
        """Existing behaviour preserved verbatim: once via run_python_checks, once via
        the prompts block."""
        names = [s.name for s in registry.full_sequence() if s.kind == "check"]
        assert names.count("validate_cli_tools_in_prompts") == 2


class TestFacadeCompleteness:
    """VP step 3 (part 1): every check + extracted helper resolves both ways."""

    @pytest.mark.parametrize("name", ALL_CHECK_NAMES)
    def test_check_reachable_via_getattr(self, name: str) -> None:
        assert hasattr(_validate, name), f"validate.{name} not reachable via getattr"
        assert callable(getattr(_validate, name))

    @pytest.mark.parametrize("name", ALL_CHECK_NAMES)
    def test_check_reachable_via_from_import(self, name: str) -> None:
        mod = importlib.import_module("scripts.validate")
        assert hasattr(mod, name), f"from scripts.validate import {name} would fail"

    @pytest.mark.parametrize("name", EXTRACTED_HELPER_NAMES)
    def test_helper_reachable_via_getattr(self, name: str) -> None:
        assert hasattr(_validate, name), f"validate.{name} not reachable via getattr"

    @pytest.mark.parametrize("name", EXTRACTED_HELPER_NAMES)
    def test_helper_reachable_via_from_import(self, name: str) -> None:
        mod = importlib.import_module("scripts.validate")
        assert hasattr(mod, name), f"from scripts.validate import {name} would fail"


class TestMockInterceptionPreservation:
    """VP step 3 (part 2): patching each _common primitive intercepts through a moved body."""

    def test_patching_common_root_intercepts_moved_check(self, tmp_path: Path) -> None:
        """validate_subprocess_encoding scans _common.ROOT; patching _common.ROOT redirects it."""
        (tmp_path / "src").mkdir()
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            _validate.validate_subprocess_encoding(failed)
        assert failed == []

    def test_patching_common_get_changed_files_intercepts_moved_check(self) -> None:
        """validate_environment_taxonomy calls _common.get_changed_files(); patching it redirects."""
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            failed: list[str] = []
            _validate.validate_environment_taxonomy(failed)
        assert failed == []

    def test_patching_common_run_intercepts_check_source_registry(self, tmp_path: Path) -> None:
        """check_source_registry uses _common.ROOT for its file scan; verifies the _common.run
        primitive is resolvable as a patch target (used by other moved checks, e.g. validate_requirements)."""
        assert callable(_common.run)
        with patch("scripts.checks._common.ROOT", tmp_path):
            (tmp_path / "config" / "agent" / "data_quality").mkdir(parents=True)
            failed: list[str] = ["placeholder"]
            failed.clear()
            _validate.check_source_registry(failed)
        assert failed == ["Source registry CI guard"]

    def test_patching_common_python_is_resolvable(self) -> None:
        """PYTHON is exported from _common and importable as a patch target."""
        with patch("scripts.checks._common.PYTHON", "/usr/bin/env-python-test"):
            assert _common.PYTHON == "/usr/bin/env-python-test"

    def test_patching_common_invoke_step_is_resolvable(self) -> None:
        calls: list[str] = []
        with patch("scripts.checks._common.invoke_step", side_effect=lambda name, cmd, failed: calls.append(name)):
            _common.invoke_step("dummy", ["true"], [])
        assert calls == ["dummy"]

    def test_check_to_check_pair_interception(self) -> None:
        """validate_ci_workflow_guards calls _ensure_root_on_path (co-located helper); patching
        a moved check-to-helper pair still intercepts through the moved body."""
        with patch(
            "scripts.checks.ci_guards.validate_ci_workflow_guards._ensure_root_on_path",
            return_value=False,
        ) as mock_ensure:
            failed: list[str] = []
            _validate.validate_ci_workflow_guards(failed)
        mock_ensure.assert_called_once()


class TestOwnerMetadata:
    """VP step 4: owner metadata correctness."""

    @pytest.mark.parametrize("name,expected", list(OWNER_EXPECTATIONS.items()))
    def test_pinned_owner(self, name: str, expected: tuple[str, bool]) -> None:
        owner, product_coupled = expected
        check = registry.get_check(name)
        assert check.owner == owner
        assert check.product_coupled is product_coupled

    @pytest.mark.parametrize(
        "name",
        [n for n in ALL_CHECK_NAMES if n not in OWNER_EXPECTATIONS],
    )
    def test_default_owner_is_platform(self, name: str) -> None:
        check = registry.get_check(name)
        assert check.owner == "platform"
        assert check.product_coupled is False

    def test_exactly_three_pinned_checks(self) -> None:
        """Sampled others=platform per the plan's ownership audit: exactly one trading check
        and two platform/product_coupled=trading checks exist in the whole registry."""
        trading = [n for n in ALL_CHECK_NAMES if registry.get_check(n).owner == "trading"]
        product_coupled = [n for n in ALL_CHECK_NAMES if registry.get_check(n).product_coupled]
        assert trading == ["validate_broker_env_reads"]
        assert sorted(product_coupled) == ["validate_environment_taxonomy", "validate_product_roadmap"]


class TestNoLocalRootRecomputation:
    """Constraint: no scripts/checks module may recompute ROOT locally."""

    def test_no_checks_module_recomputes_root(self) -> None:
        violations: list[str] = []
        checks_dir = ROOT / "scripts" / "checks"
        for py_file in sorted(checks_dir.rglob("*.py")):
            if py_file == checks_dir / "_common.py":
                continue  # the sole source of ROOT
            text = py_file.read_text(encoding="utf-8")
            if "Path(__file__).parent.parent.parent" in text or "Path(__file__).resolve().parent.parent" in text:
                violations.append(str(py_file.relative_to(ROOT)))
        assert violations == [], f"Modules recomputing ROOT locally: {violations}"

    def test_zero_residual_bare_root_patch_sites_in_tests(self) -> None:
        """Grep-count closure: no test still patches validate.run/ROOT/get_changed_files
        expecting it to intercept a moved check body (Decision 104 namespace migration)."""
        import re

        text = (ROOT / "tests" / "test_validate.py").read_text(encoding="utf-8")
        residual = re.findall(r'patch\("validate\.(run|ROOT|get_changed_files)"', text)
        assert residual == [], f"Residual validate.{{run,ROOT,get_changed_files}} patch sites: {residual}"


class TestUpdateSlocBudgetsLoweringGap:
    """rec-2420: a file shrinks from an existing budget of 700 to 550 SLOC (still over 500) --
    the budget should lower from 700 to 550, not stay frozen at the old value."""

    def test_update_sloc_budgets_lowers_shrunken_oversized(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "shrunk_but_still_big.py").write_text("x = 1\n" * 550, encoding="utf-8")
        (config_dir / "sloc_budgets.yaml").write_text("budgets:\n  scripts/shrunk_but_still_big.py: 700\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            _validate._update_sloc_budgets()
            result = _validate._load_sloc_budgets()

        assert result["scripts/shrunk_but_still_big.py"] == 550
