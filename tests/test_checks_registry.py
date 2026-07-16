"""Tests for the check registry (Decision 104): scripts/checks/registry.py + _common.py.

Covers: growth-safe sequence invariants (membership floor + scaffold-anchor order --
see the PLAN-checks-registry-growth-safe-baseline supersession note below), facade
completeness (every check/helper reachable via validate.<name> AND `from scripts.validate
import <name>`), mock-interception preservation through moved bodies, owner-metadata
correctness, the no-local-ROOT invariant, and rec-2420's lowering-test gap.

SUPERSESSION NOTE (PLAN-checks-registry-growth-safe-baseline, closes rec-2673/rec-2674):
Decision 104 introduced this module with byte-for-byte frozen ordered-tuple baselines
(a pair of frozen per-tier sequence constants) as a one-time equivalence oracle proving the
validate.py decomposition preserved the check sequence. That oracle's job is done and its
byte-for-byte permanence is superseded here: every registry.py addition required a
synchronous, coupled edit to this file, and the diff-aware --pre tier has no rule binding
registry.py changes to this test file's selection, so the coupling silently escaped to the
post-merge full tier twice (rec-2673, rec-2674). The invariants below replace exact
ordered-tuple equality with (a) a per-tier required-check membership floor (a subset check,
so new checks pass unchanged) and (b) a scaffold-anchor order invariant over the fixed,
non-growing scaffold skeleton. The decomposition mechanism (registry.py, _common.py, the
dispatch loop) is untouched; only this file's oracle shape changes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# Growth-safe invariants (supersedes the Decision 104 frozen ordered-tuple baseline --
# see the module docstring supersession note).
#
# REQUIRED_*_CHECKS are membership floors: every "check"-kind name known to be required
# in that tier today. Asserted as a SUBSET of the actual sequence's check-name set, so a
# new check added to the registry passes unchanged (Decision 55: no rescue loop needed),
# while a required check's removal trips the subset assertion (see the growth-safety proof
# tests below).
#
# FROZEN_*_SCAFFOLDS are exact ordered tuples over the "scaffold"-kind steps only -- a
# fixed, non-growing structural skeleton (lint/precommit/mypy/pytest-diff/coverage/budget
# for pre; lint/unit_tests/mypy_full/terraform/dependency_health/ensure_fresh_dq/precommit
# for full). Exact order here is meaningful and does not grow as checks are added, so it is
# not the test-count-coupling anti-pattern the membership floor replaces.
# ---------------------------------------------------------------------------

REQUIRED_PRE_CHECKS: frozenset[str] = frozenset(
    {
        "validate_iam_runner_policy",
        "validate_prompt_files",
        "validate_cli_tools_in_prompts",
        "validate_workflow_agent_safety",
        "validate_product_roadmap",
        "validate_plan_documents",
        "validate_tier_floor",
        "validate_candidate_decision_ratification",
        "validate_decisions_size",
        "validate_cc_limits",
        "validate_sloc_limits",
        "validate_sloc_budget_raises",
        "validate_subprocess_encoding",
        "validate_test_count_coupling",
        "validate_intent_doc_freeze",
        "validate_prose_allowlist",
        "validate_contract_drift",
        "validate_placement",
        "validate_field_semantics_drift",
        "validate_deploy_channel_conformance",
        "validate_ci_rca_taxonomy",
        "validate_ops_portal_patch_targets",
        "validate_claude_p_retry_wrapper",
        "validate_authority_budget",
        "validate_invoke_implies_resolve",
        "validate_ci_workflow_guards",
        "validate_ducklake_version_lockstep",
        "validate_import_contracts",
        "validate_lockfile_sync",
        "validate_verifier_same_pr_guard",
        "validate_verification_registry",
        "validate_vp_replay",
    }
)

FROZEN_PRE_SCAFFOLDS: tuple[str, ...] = (
    "lint",
    "precommit_changed",
    "mypy_diff",
    "pytest_diff",
    "coverage_report",
    "budget_assertion",
)

REQUIRED_FULL_CHECKS: frozenset[str] = frozenset(
    {
        "validate_subprocess_encoding",
        "validate_test_count_coupling",
        "validate_sys_executable",
        "validate_cli_tools_in_prompts",
        "validate_imports",
        "validate_recommendations_schema",
        "validate_outbox_staleness",
        "validate_executor_boundary",
        "validate_rec_write_paths",
        "validate_decisions_local_writes",
        "validate_warehouse_write_sources",
        "validate_broker_env_reads",
        "validate_invariants",
        "validate_ci_rca_trigger",
        "validate_ci_workflow_guards",
        "validate_claude_p_retry_wrapper",
        "validate_sloc_limits",
        "check_source_registry",
        "validate_platform_roadmap",
        "validate_candidate_decision_ratification",
        "validate_decisions_size",
        "validate_decision_entry_conformance",
        "validate_lambda_manifests",
        "validate_lambda_manifest_coverage",
        "validate_lambda_bundle_completeness",
        "validate_lambda_deploy_gating",
        "validate_product_roadmap",
        "validate_plan_documents",
        "validate_tier_floor",
        "validate_pydantic_yaml_drift",
        "_check_graduation_guard",
        "validate_dq_manifest_gate",
        "validate_test_coverage",
        "validate_no_underscore_instructions",
        "validate_claude_md_pointer_invariant",
        "validate_environment_taxonomy",
        "validate_complexity",
        "validate_scheduled_agent_logs",
        "validate_ghas_probe",
        "validate_hermeticity_flags",
        "validate_verifier_hermeticity",
        "validate_verifier_same_pr_guard",
        "validate_verification_registry",
        "validate_differential_gate_baseline",
        "validate_intent_doc_freeze",
        "validate_prose_allowlist",
        "validate_contract_drift",
        "validate_placement",
        "validate_portal_drift",
        "validate_rec_relevance_contract",
        "validate_field_semantics_drift",
        "validate_ci_rca_taxonomy",
        "validate_ops_portal_patch_targets",
        "validate_authority_budget",
        "validate_invoke_implies_resolve",
        "validate_ducklake_version_lockstep",
        "validate_import_contracts",
        "validate_lockfile_sync",
        "validate_dependency_graph_freshness",
        "validate_iam_runner_policy",
        "validate_requirements",
        "validate_prompt_files",
        "validate_workflow_agent_safety",
        "validate_prompt_compliance",
        "validate_instruction_architecture_layers",
        "validate_verification_harness",
    }
)

FROZEN_FULL_SCAFFOLDS: tuple[str, ...] = (
    "lint",
    "unit_tests",
    "mypy_full",
    "terraform_checks",
    "dependency_health",
    "ensure_fresh_dq",
    "precommit_all_files",
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


class TestSequenceInvariants:
    """Growth-safe successor to the Decision 104 frozen-baseline oracle (see module
    docstring supersession note). A per-tier required-check membership floor plus a
    scaffold-anchor order invariant, instead of exact ordered-tuple equality."""

    def test_pre_sequence_meets_required_floor(self) -> None:
        actual = {s.name for s in registry.pre_sequence() if s.kind == "check"}
        assert REQUIRED_PRE_CHECKS <= actual

    def test_full_sequence_meets_required_floor(self) -> None:
        actual = {s.name for s in registry.full_sequence() if s.kind == "check"}
        assert REQUIRED_FULL_CHECKS <= actual

    def test_pre_scaffold_anchor_order(self) -> None:
        actual = tuple(s.name for s in registry.pre_sequence() if s.kind == "scaffold")
        assert actual == FROZEN_PRE_SCAFFOLDS

    def test_full_scaffold_anchor_order(self) -> None:
        actual = tuple(s.name for s in registry.full_sequence() if s.kind == "scaffold")
        assert actual == FROZEN_FULL_SCAFFOLDS

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

    def test_membership_floor_growth_safe_to_additions(self) -> None:
        """A new check added to the registry must not break the required-check floor."""
        actual = {s.name for s in registry.full_sequence() if s.kind == "check"}
        actual.add("validate_synthetic_new")
        assert REQUIRED_FULL_CHECKS <= actual

    def test_membership_floor_detects_removal(self) -> None:
        """Removing a required check from the sequence must trip the floor -- proves the
        floor has teeth and is not a no-op guard."""
        actual = {s.name for s in registry.full_sequence() if s.kind == "check"}
        removed_one = next(iter(REQUIRED_FULL_CHECKS))
        actual.discard(removed_one)
        assert not (REQUIRED_FULL_CHECKS <= actual)


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
        expecting it to intercept a moved check body (Decision 104 namespace migration).

        tests/test_validate.py was fully decomposed into per-check mirrors under
        tests/checks/** plus the orchestrator residue under tests/validate/ (rec-2709
        Wave 1) -- scan both trees for the same residual anti-pattern the monolith-era
        check guarded against.
        """
        import re

        residual: list[str] = []
        for py_file in sorted((ROOT / "tests" / "checks").rglob("*.py")) + sorted((ROOT / "tests" / "validate").rglob("*.py")):
            text = py_file.read_text(encoding="utf-8")
            residual.extend(re.findall(r'patch\("validate\.(run|ROOT|get_changed_files)"', text))
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


class TestCommonPrimitives:
    """Direct coverage of scripts/checks/_common.py's primitives.

    _common.py is _common.py's own mapped coverage-checker home (Decision 104 grandfather
    rule: scripts/checks/_common.py -> tests/test_checks_registry.py, a flat, non-retiring
    mapping outside the 24-item mirror roster) -- its 100% per-file coverage is asserted HERE,
    not in tests/validate/test_changed_files.py (which covers the SAME primitives'
    behavioural contract, but is not the file this module's coverage check runs against).
    """

    def test_run_delegates_to_subprocess_run(self) -> None:
        result = _common.run(["true"])
        assert result.returncode == 0

    def test_invoke_step_appends_on_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=1)):
            _common.invoke_step("dummy-step", ["true"], failed)
        assert failed == ["dummy-step"]
        assert "dummy-step" in capsys.readouterr().out

    def test_invoke_step_no_append_on_zero(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=0)):
            _common.invoke_step("dummy-step", ["true"], failed)
        assert failed == []

    def test_get_changed_files_origin_main_success_branch(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "a.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            files = _common.get_changed_files()
        assert files == ["a.py"]

    def test_get_changed_files_head_fallback_branch(self, tmp_path: Path) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            if "origin/main" in cmd:
                result.returncode = 1
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            files = _common.get_changed_files()
        assert files == []

    def test_get_status_aware_diff_full_pass(self, tmp_path: Path) -> None:
        """Exercises every line of get_status_aware_diff(): a successful merge-base, a mixed
        M/A/D/malformed diff, and untracked existing/nonexistent paths."""
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "new_thing.py").write_text("x = 2\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            if cmd[:2] == ["git", "merge-base"]:
                result.stdout = "deadbeef\n"
            elif cmd[:2] == ["git", "diff"]:
                result.stdout = "M\ta.py\n\nD\tscripts/gone.py\nno-tab-here\nM\tnot_on_disk.py\nM\t   \nR\told_renamed.py\n"
            elif cmd[:2] == ["git", "ls-files"]:
                result.stdout = "new_thing.py\nghost.py\n"
            else:
                result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = _common.get_status_aware_diff()

        assert set(entries) == {("M", "a.py"), ("D", "scripts/gone.py"), ("??", "new_thing.py")}

    def test_get_status_aware_diff_merge_base_failure_fallback(self, tmp_path: Path) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0 if cmd[:2] != ["git", "merge-base"] else 1
            result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run), patch("scripts.checks._common.ROOT", tmp_path):
            entries = _common.get_status_aware_diff()
        assert entries == []
