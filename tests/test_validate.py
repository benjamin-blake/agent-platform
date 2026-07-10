"""Tests for the new functions added to scripts/validate.py in agent/infra-testing-enforcement.

Covers: validate_cli_tools_in_prompts, validate_test_coverage, validate_prompt_compliance,
and the _load_coverage_checker / _load_prompt_compliance helpers.
"""

import importlib.util
import itertools
import json
import sys
import urllib.error
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import verification_graduation
from scripts.checks._scaffolding import (
    _excluded_heavy_import_names,
    _parse_requirement_dist_names,
    partition_changed_tests_by_collectability,
)
from scripts.checks.hygiene.validate_test_count_coupling import _find_violations
from scripts.checks.misc.validate_ghas_probe import _run_cli as _ghas_run_cli

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate", _SCRIPT_PATH)
_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_validate)  # type: ignore[union-attr]
sys.modules["validate"] = _validate

validate_scheduled_agent_logs = _validate.validate_scheduled_agent_logs
validate_ghas_probe = _validate.validate_ghas_probe
validate_cli_tools_in_prompts = _validate.validate_cli_tools_in_prompts
validate_test_coverage = _validate.validate_test_coverage
validate_prompt_compliance = _validate.validate_prompt_compliance
validate_instruction_architecture_layers = _validate.validate_instruction_architecture_layers
validate_invariants = _validate.validate_invariants
validate_no_underscore_instructions = _validate.validate_no_underscore_instructions
validate_recommendations_schema = _validate.validate_recommendations_schema
validate_complexity = _validate.validate_complexity
validate_sloc_limits = _validate.validate_sloc_limits
validate_cc_limits = _validate.validate_cc_limits
validate_ci_rca_trigger = _validate.validate_ci_rca_trigger
validate_ci_workflow_guards = _validate.validate_ci_workflow_guards
ensure_fresh_dq_results = _validate.ensure_fresh_dq_results
run_coverage_check = _validate.run_coverage_check
_load_coverage_checker = _validate._load_coverage_checker
_load_prompt_compliance = _validate._load_prompt_compliance
_check_graduation_guard = _validate._check_graduation_guard
_extract_enforced_map = _validate._extract_enforced_map
check_source_registry = _validate.check_source_registry
validate_iam_runner_policy = _validate.validate_iam_runner_policy
get_changed_files = _validate.get_changed_files
validate_environment_taxonomy = _validate.validate_environment_taxonomy
_file_budget_breach_rec = _validate._file_budget_breach_rec
_file_budget_bypass_rec = _validate._file_budget_bypass_rec
_FAST_TIER_BUDGET_SECONDS = _validate._FAST_TIER_BUDGET_SECONDS
ROOT = _validate.ROOT
check_claude_md_pointer_invariant = _validate.check_claude_md_pointer_invariant
validate_hermeticity_flags = _validate.validate_hermeticity_flags
_build_unit_test_cmd = _validate._build_unit_test_cmd
_UNIT_TEST_HERMETICITY_FLAGS = _validate._UNIT_TEST_HERMETICITY_FLAGS
validate_lambda_manifests = _validate.validate_lambda_manifests
validate_lambda_manifest_coverage = _validate.validate_lambda_manifest_coverage
validate_lambda_bundle_completeness = _validate.validate_lambda_bundle_completeness
validate_lambda_deploy_gating = _validate.validate_lambda_deploy_gating
validate_intent_doc_freeze = _validate.validate_intent_doc_freeze
validate_ci_rca_taxonomy = _validate.validate_ci_rca_taxonomy
validate_verifier_hermeticity = _validate.validate_verifier_hermeticity
validate_field_semantics_drift = _validate.validate_field_semantics_drift
validate_broker_env_reads = _validate.validate_broker_env_reads
validate_platform_roadmap = _validate.validate_platform_roadmap
validate_candidate_decision_ratification = _validate.validate_candidate_decision_ratification
validate_ducklake_version_lockstep = _validate.validate_ducklake_version_lockstep
validate_verifier_same_pr_guard = _validate.validate_verifier_same_pr_guard
validate_verification_registry = _validate.validate_verification_registry
validate_differential_gate_baseline = _validate.validate_differential_gate_baseline
validate_vp_replay = _validate.validate_vp_replay
validate_rec_relevance_contract = _validate.validate_rec_relevance_contract
_extract_verifier_covers = _validate._extract_verifier_covers
_load_sloc_budgets = _validate._load_sloc_budgets
_update_sloc_budgets = _validate._update_sloc_budgets
validate_dependency_graph_freshness = _validate.validate_dependency_graph_freshness
validate_import_contracts = _validate.validate_import_contracts
validate_lockfile_sync = _validate.validate_lockfile_sync
validate_portal_drift = _validate.validate_portal_drift
run_pytest_diff = _validate.run_pytest_diff
validate_tier_floor = _validate.validate_tier_floor
validate_invoke_implies_resolve = _validate.validate_invoke_implies_resolve


class TestDependencyGraphFreshness:
    """Tests for validate_dependency_graph_freshness() -- the Decision 80 freshness gate."""

    def test_no_op_when_export_absent(self, tmp_path: Path) -> None:
        """No failure when docs/dependency-graph.json does not exist."""
        from unittest.mock import patch as _patch

        missing = tmp_path / "nonexistent.json"
        with _patch("scripts.dependency_graph._EXPORT_PATH", missing):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)
        assert not failed

    def test_fails_when_export_is_stale(self, tmp_path: Path) -> None:
        """A failure is appended when the committed export differs from the current graph."""
        import json
        from unittest.mock import patch as _patch

        export_path = tmp_path / "dependency-graph.json"
        stale = {"nodes": ["stale.module"], "edges": [], "roots": [], "metadata": {}, "symbol_nodes": []}
        export_path.write_text(json.dumps(stale), encoding="utf-8")
        with _patch("scripts.dependency_graph._EXPORT_PATH", export_path):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)
        assert len(failed) == 1
        msg = failed[0].lower()
        assert "stale" in msg or "drift" in msg or "dependency graph" in msg


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


class TestClaudeMdPointerInvariant:
    """Tests for check_claude_md_pointer_invariant()."""

    def test_claude_md_pointer_happy_path(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is True

    def test_claude_md_pointer_extra_content(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\nstray content\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_wrong_target(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@OTHER.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False


class TestValidateCliToolsInPrompts:
    """Tests for validate_cli_tools_in_prompts()."""

    def test_passes_when_all_tools_in_path(self, tmp_path: Path) -> None:
        """No failures when all referenced tools are found in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\naws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.shutil.which", return_value="/usr/bin/aws"),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_fails_when_tool_not_in_path(self, tmp_path: Path) -> None:
        """Appends to failed list when a referenced tool is not in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\nterraform validate\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"terraform"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert len(failed) == 1
        assert "CLI tool verification" in failed[0]

    def test_optional_tool_gh_missing_is_skipped(self, tmp_path: Path) -> None:
        """gh is optional (Decision 76); a referenced-but-missing gh does not fail the gate."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "ci.prompt.md"
        md.write_text("```bash\ngh pr view\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"gh"}),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._OPTIONAL_CLI_TOOLS", {"gh"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_skips_comment_lines_in_code_blocks(self, tmp_path: Path) -> None:
        """Lines starting with # inside code blocks are not treated as commands."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\n# aws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        # aws appears only in a comment — not in referenced, so not checked
        assert failed == []

    def test_no_failures_when_no_md_files(self, tmp_path: Path) -> None:
        """No failures when no markdown files exist in the search dirs."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []


class TestValidatePlacement:
    """Tests for validate_placement() (RS-04 link-validity gate, docs/contracts/file-router.yaml)."""

    validate_placement = staticmethod(_validate.validate_placement)

    @staticmethod
    def _router(tmp_path: Path, content: str) -> Path:
        router = tmp_path / "file-router.yaml"
        router.write_text(content, encoding="utf-8")
        return router

    @staticmethod
    def _mock_ls_files(tracked_paths: list[str]):
        def _run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "".join(f"{p}\n" for p in tracked_paths)
            result.stderr = ""
            return result

        return _run

    def test_happy_path_zero_dead_targets(self, tmp_path: Path) -> None:
        """A well-formed router with a file target and a directory target and zero dead
        targets passes with an empty failed list (proves directory-prefix resolution works,
        not just exact-file matches)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "  - topic: dir-target\n"
            "    targets: [src/lambdas/]\n",
        )
        with patch(
            "scripts.checks._common.run",
            side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md", "src/lambdas/handler.py"]),
        ):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_dead_target_reports_failure(self, tmp_path: Path) -> None:
        """A non-runtime target absent from the tracked snapshot fails the gate."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: bogus-topic\n    targets: [scripts/does_not_exist.py]\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "dead target" in failed[0]
        assert "scripts/does_not_exist.py" in failed[0]

    def test_runtime_row_parent_tracked_passes(self, tmp_path: Path) -> None:
        """A runtime:true row whose target is untracked but whose parent dir is tracked passes."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: recommendations-log\n"
            "    targets: [logs/.recommendations-log.jsonl]\n"
            "    runtime: true\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["logs/.friction-analysis-log.jsonl"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_runtime_row_bogus_parent_fails(self, tmp_path: Path) -> None:
        """A runtime:true row whose parent directory is not tracked at all fails the gate."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: orphan-cache\n"
            "    targets: [nonexistent_dir/.cache.json]\n"
            "    runtime: true\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "runtime target" in failed[0]

    def test_duplicate_topic_fails(self, tmp_path: Path) -> None:
        """Two route objects sharing the same topic string fail the gate. Detected by
        iterating the routes LIST, not by mapping-key uniqueness -- yaml.safe_load would
        silently collapse a topic-keyed mapping, making this gate unconstructable."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: dup-topic\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "  - topic: dup-topic\n"
            "    targets: [docs/DECISIONS.md]\n",
        )
        with patch(
            "scripts.checks._common.run",
            side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md", "docs/DECISIONS.md"]),
        ):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "duplicate topic" in failed[0]
        assert "dup-topic" in failed[0]

    def test_missing_router_file_fails(self, tmp_path: Path) -> None:
        """A router_path that does not exist on disk fails the gate (never raises)."""
        failed: list[str] = []
        self.validate_placement(failed, router_path=tmp_path / "does-not-exist.yaml")
        assert len(failed) == 1
        assert "does not exist" in failed[0]

    def test_malformed_yaml_syntax_fails(self, tmp_path: Path) -> None:
        """Unparseable YAML content is a gate failure, never an unhandled exception."""
        router = self._router(tmp_path, "routes: [unclosed\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "could not read/parse" in failed[0]

    def test_router_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """A top-level YAML list (not a mapping) fails the gate."""
        router = self._router(tmp_path, "- one\n- two\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "not a YAML mapping" in failed[0]

    def test_routes_not_a_list_fails(self, tmp_path: Path) -> None:
        """A top-level mapping with 'routes' missing (or not a list) fails the gate."""
        router = self._router(tmp_path, "schema_version: 1\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "'routes' is missing or not a non-empty list" in failed[0]

    def test_route_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """A routes-list entry that is not itself a mapping is a malformed row, not a crash."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - just-a-string\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "not a mapping" in failed[0]

    def test_route_missing_topic_fails(self, tmp_path: Path) -> None:
        """A route missing 'topic' is a malformed row."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - targets: [docs/ARCHITECTURE.md]\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "topic" in failed[0]

    def test_route_missing_targets_fails(self, tmp_path: Path) -> None:
        """A route missing 'targets' is a malformed row."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - topic: no-targets\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "targets" in failed[0]

    def test_git_ls_files_failure_yields_dead_targets(self, tmp_path: Path) -> None:
        """A non-zero git ls-files exit falls back to an empty tracked set -- fails loud on
        every non-runtime target rather than silently passing (Decision 55)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: whatever\n    targets: [docs/ARCHITECTURE.md]\n",
        )

        def _failing_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "fatal: not a git repository"
            return result

        with patch("scripts.checks._common.run", side_effect=_failing_run):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "dead target" in failed[0]


class TestValidateTestCoverage:
    """Tests for validate_test_coverage()."""

    @pytest.fixture(autouse=True)
    def _clear_subprocess_guard(self, monkeypatch):
        """Remove the conftest recursion guard so coverage logic is exercised."""
        monkeypatch.delenv("_COVERAGE_SUBPROCESS", raising=False)

    def test_passes_when_no_changed_files(self) -> None:
        """No failures when get_changed_source_files returns empty list."""
        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = []

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_passes_when_all_test_files_exist(self, tmp_path: Path) -> None:
        """No failures when all changed files have corresponding test files."""
        source = tmp_path / "src" / "config.py"
        source.parent.mkdir(parents=True)
        source.write_text("def foo(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (True, "test file found")
        mock_checker.check_per_file_coverage.return_value = []

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_fails_when_test_file_missing(self, tmp_path: Path) -> None:
        """Appends to failed list when a changed file has no test file."""
        source = tmp_path / "src" / "new_module.py"
        source.parent.mkdir(parents=True)
        source.write_text("def bar(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (False, "missing test file: tests/test_new_module.py")

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert len(failed) == 1
        assert "Test coverage check" in failed[0]

    def test_skips_when_checker_not_found(self) -> None:
        """No failures (and no exception) when test_coverage_checker.py is absent."""
        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=None):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []


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
            _validate.validate_instruction_architecture_layers(failed)

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
            _validate.validate_instruction_architecture_layers(failed)

        assert len(failed) == 1
        assert "Instruction architecture layer claims" in failed[0]

    def test_skips_when_compliance_not_found(self) -> None:
        """No failures when prompt_compliance.py is absent."""
        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=None,
        ):
            failed: list[str] = []
            _validate.validate_instruction_architecture_layers(failed)

        assert failed == []


class TestLoadHelpers:
    """Tests for _load_coverage_checker and _load_prompt_compliance."""

    def test_load_coverage_checker_returns_module_when_exists(self) -> None:
        """Returns a module object when test_coverage_checker.py exists."""
        checker = _load_coverage_checker()
        assert checker is not None
        assert hasattr(checker, "extract_definitions")
        assert hasattr(checker, "get_changed_source_files")

    def test_load_coverage_checker_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_coverage_checker()
        assert result is None

    def test_load_prompt_compliance_returns_module_when_exists(self) -> None:
        """Returns a module object when prompt_compliance.py exists."""
        compliance = _load_prompt_compliance()
        assert compliance is not None
        assert hasattr(compliance, "parse_invariants")
        assert hasattr(compliance, "check_retro_lite_compliance")

    def test_load_prompt_compliance_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_prompt_compliance()
        assert result is None


class TestValidateEnvironmentTaxonomy:
    """Tests for validate_environment_taxonomy (two-axis vocabulary reservation lint)."""

    def _run(self, tmp_path: Path, files: dict[str, str], changed: list[str]) -> list[str]:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        failed: list[str] = []
        with (
            patch("scripts.checks._common.get_changed_files", return_value=changed),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            validate_environment_taxonomy(failed)
        return failed

    def test_flags_phase_used_as_environment(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, {"docs/x.md": "We run the live_full environment nightly.\n"}, ["docs/x.md"])
        assert failed == ["Environment/phase taxonomy"]

    def test_flags_tier_used_as_phase(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, {"docs/x.md": "The sandbox phase mocks externals.\n"}, ["docs/x.md"])
        assert failed == ["Environment/phase taxonomy"]

    def test_clean_doc_passes(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/x.md": "The sandbox environment auto-applies; research is a phase.\n"},
            ["docs/x.md"],
        )
        assert failed == []

    def test_compound_tokens_allowed(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/x.md": "research_sandbox environment and production_ensemble phase are fine.\n"},
            ["docs/x.md"],
        )
        assert failed == []

    def test_allowlisted_file_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"docs/DECISIONS.md": "The live_full environment and sandbox phase appear here.\n"},
            ["docs/DECISIONS.md"],
        )
        assert failed == []

    def test_github_and_tests_paths_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {".github/workflows/w.yml": "name: sandbox phase\n", "tests/fixture.md": "live_full environment\n"},
            [".github/workflows/w.yml", "tests/fixture.md"],
        )
        assert failed == []

    def test_non_doc_suffix_skipped(self, tmp_path: Path) -> None:
        failed = self._run(
            tmp_path,
            {"scripts/foo.py": "# sandbox phase live_full environment\n"},
            ["scripts/foo.py"],
        )
        assert failed == []

    def test_missing_file_ignored(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["docs/gone.md"]),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            validate_environment_taxonomy(failed)
        assert failed == []


class TestRunTerraformChecks:
    """Tests for run_terraform_checks() (full presubmit) and run_terraform_creds_free()."""

    def test_warns_when_personal_plan_exit_code_2(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_checks() warns when the terraform/personal plan returns exit code 2."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 2 if "-detailed-exitcode" in cmd else 0
            return result

        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "WARNING: Terraform changes pending" in captured.out
        assert "terraform/personal" in captured.out
        assert failed == []

    def test_no_warning_when_exit_code_0(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_checks() does not warn when plan returns exit code 0."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
        assert failed == []

    def test_skips_terraform_binary_steps_when_not_found(self, capsys: pytest.CaptureFixture) -> None:
        """No terraform binary -> creds-free helper prints a skip and `run` is never invoked."""
        with (
            patch("scripts.checks._terraform.validate_terraform_try"),
            patch("validate.shutil.which", return_value=None),
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called when terraform is absent")),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "skipped" in captured.out
        assert failed == []

    def test_creds_free_covers_both_roots(self) -> None:
        """run_terraform_creds_free() runs init -backend=false + validate + fmt for ALL roots, no plan."""
        calls: list[list] = []

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)

        chdirs = {arg for cmd in calls for arg in cmd if isinstance(arg, str) and arg.startswith("-chdir=")}
        flat = [tok for cmd in calls for tok in cmd]
        assert "-chdir=terraform" in chdirs
        assert "-chdir=terraform/personal" in chdirs
        assert "-chdir=terraform/bootstrap" in chdirs
        assert any("-backend=false" in cmd for cmd in calls)  # creds-free init
        assert all("plan" not in cmd for cmd in calls)  # no creds-needing plan here
        assert "init" in flat and "validate" in flat and "fmt" in flat
        assert failed == []

    def test_creds_free_skips_when_terraform_absent(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_creds_free() emits a visible skip and calls nothing when terraform is absent."""
        with (
            patch("validate.shutil.which", return_value=None),
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)
        assert "skipped" in capsys.readouterr().out
        assert failed == []

    def test_creds_free_init_retries_on_transient_5xx(self, capsys: pytest.CaptureFixture) -> None:
        """_terraform_init_with_retry retries on transient 5xx and succeeds on the third attempt."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                if init_call_count < 3:
                    result.returncode = 1
                    result.stdout = "Error: could not query provider registry"
                    result.stderr = ""
                else:
                    result.returncode = 0
                    result.stdout = "Terraform has been successfully initialized!"
                    result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3
        assert failed == []

    def test_creds_free_init_fails_fast_on_non_transient(self) -> None:
        """_terraform_init_with_retry does NOT retry on non-transient errors."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = "Error: Required token could not be found"
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 1
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_exhausts_retries_on_persistent_transient(self) -> None:
        """A transient 5xx on all 3 attempts exhausts the retry budget and appends to failed."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Error: 502 Bad Gateway from registry.terraform.io"
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3  # all attempts consumed
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_retries_on_connection_reset(self) -> None:
        """_terraform_init_with_retry retries a provider-download connection reset and succeeds on attempt 3."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                if init_call_count < 3:
                    result.returncode = 1
                    result.stdout = ""
                    result.stderr = "read: connection reset by peer"
                else:
                    result.returncode = 0
                    result.stdout = "Terraform has been successfully initialized!"
                    result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 3
        assert failed == []

    def test_creds_free_init_fails_fast_on_bad_pin(self) -> None:
        """A non-transient bad-pin provider error is not retried, even though it fails init."""
        init_call_count = 0

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            nonlocal init_call_count
            result = MagicMock()
            if "init" in cmd:
                init_call_count += 1
                result.returncode = 1
                result.stdout = (
                    "Error: Failed to install provider\n"
                    "provider registry does not have a provider named registry.terraform.io/hashicorp/aws"
                )
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform",))

        assert init_call_count == 1
        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_creds_free_init_skips_on_proxy_403(self, capsys: pytest.CaptureFixture) -> None:
        """A github.com-403 auth-checksum init failure is a visible skip, not a failure, and fmt still runs."""
        calls: list[list] = []

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            if "init" in cmd:
                result.returncode = 1
                result.stdout = ""
                result.stderr = (
                    "Error: Failed to install provider\n"
                    "Error: retrieving checksums for provider: 403 Forbidden returned from github.com"
                )
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform/personal",))

        captured = capsys.readouterr()
        assert "SKIP" in captured.out
        assert failed == []
        assert not any("validate" in cmd for cmd in calls)
        assert any("fmt" in cmd for cmd in calls)

    def test_creds_free_init_still_fails_on_non_github_403(self) -> None:
        """A 403 lacking the github.com/checksum co-occurrence (e.g. an S3 backend 403) still fails."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            if "init" in cmd:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "Error: error configuring S3 Backend: 403 Forbidden: AccessDenied"
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("validate.time.sleep"),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed, roots=("terraform/personal",))

        assert len(failed) == 1
        assert "Terraform init" in failed[0]

    def test_transient_init_signatures_exact_set(self) -> None:
        """_TRANSIENT_INIT_SIGNATURES contains the expected tokens (parity with workflow retry loop)."""
        expected = frozenset(
            (
                "502",
                "Bad Gateway",
                "could not query provider registry",
                "failed after ",
                "connection reset by peer",
                "i/o timeout",
                "TLS handshake timeout",
                "unexpected EOF",
            )
        )
        assert frozenset(_validate._TRANSIENT_INIT_SIGNATURES) == expected


class TestValidateSubprocessEncoding:
    """Tests for validate_subprocess_encoding()."""

    validate_subprocess_encoding = staticmethod(_validate.validate_subprocess_encoding)

    def test_passes_when_encoding_present(self, tmp_path: Path) -> None:
        """No failure when subprocess.run with text=True also has encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run(["cmd"], text=True, encoding="utf-8")\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_fails_when_encoding_missing(self, tmp_path: Path) -> None:
        """Fails when subprocess.run with text=True has no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text('subprocess.run(["cmd"], capture_output=True, text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed

    def test_passes_when_no_text_true(self, tmp_path: Path) -> None:
        """No failure when subprocess.run does not use text=True."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ok.py").write_text('subprocess.run(["cmd"], capture_output=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_catches_popen_without_encoding(self, tmp_path: Path) -> None:
        """Fails for subprocess.Popen with text=True and no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_popen.py").write_text('subprocess.Popen(["cmd"], text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed


class TestValidateTestCountCoupling:
    """Tests for validate_test_count_coupling() (Decision 104 test-count-coupling guard).

    Exercises the pure _find_violations(paths) core directly on synthetic temp files --
    the incident's three brittle shapes (direct reference, aliased local, string-subscript
    key), both comparison orders, the waiver escape hatch, and both-tiers registration.
    """

    def _write(self, tmp_path: Path, name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_direct_reference_is_flagged(self, tmp_path: Path) -> None:
        """assert len(TABLE_NAMES) == N -- direct reference to a curated collection."""
        path = self._write(tmp_path, "test_a.py", "def test_x():\n    assert len(TABLE_NAMES) == 11\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_aliased_local_is_flagged(self, tmp_path: Path) -> None:
        """entries = load_source_registry(); assert len(entries) == N -- the incident's blind spot."""
        path = self._write(
            tmp_path,
            "test_b.py",
            "def test_x():\n    entries = load_source_registry()\n    assert len(entries) == 35\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_string_subscript_key_is_flagged(self, tmp_path: Path) -> None:
        """assert len(g["source"]["registered_values"]) == N -- string-subscript key shape."""
        path = self._write(
            tmp_path,
            "test_c.py",
            'def test_x():\n    assert len(g["source"]["registered_values"]) == 35\n',
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_derived_assertion_not_flagged(self, tmp_path: Path) -> None:
        """RHS not an int literal -- a genuine derivation, not a hardcoded count."""
        path = self._write(
            tmp_path,
            "test_d.py",
            "def test_x():\n    entries = load_source_registry()\n    assert len(entries) == len(raw_ids)\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_waived_assertion_not_flagged(self, tmp_path: Path) -> None:
        """A `# count-coupling-ok:` comment on the assert's line silences the guard."""
        path = self._write(
            tmp_path,
            "test_e.py",
            "def test_x():\n    assert len(TABLE_NAMES) == 11  # count-coupling-ok: deliberate tripwire\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_non_curated_count_not_flagged(self, tmp_path: Path) -> None:
        """A hardcoded exact-count assertion against a non-curated collection is not the anti-pattern."""
        path = self._write(tmp_path, "test_f.py", "def test_x():\n    assert len(rows) == 3\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_tainted_controlled_fixture_flagged_then_waived(self, tmp_path: Path) -> None:
        """The test_rec_write_guidance.py:43 class: a curated-tainted local with a small,
        deliberately-sized fixture count IS flagged unwaived, but NOT once waived."""
        unwaived = self._write(
            tmp_path,
            "test_g.py",
            "def test_x():\n    e = load_source_registry(p)\n    assert len(e) == 1\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert len(_find_violations([unwaived])) == 1

        waived = self._write(
            tmp_path,
            "test_h.py",
            "def test_x():\n    e = load_source_registry(p)\n    assert len(e) == 1  # count-coupling-ok: fixture\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert _find_violations([waived]) == []

    def test_yoda_order_is_flagged(self, tmp_path: Path) -> None:
        """assert N == len(TABLE_NAMES) -- reversed comparison order, same anti-pattern."""
        path = self._write(tmp_path, "test_i.py", "def test_x():\n    assert 11 == len(TABLE_NAMES)\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_registered_in_both_tiers(self) -> None:
        """validate_test_count_coupling appears in both pre_sequence() and full_sequence()."""
        from scripts.checks import registry

        names = [s.name for s in registry.pre_sequence() + registry.full_sequence()]
        assert names.count("validate_test_count_coupling") >= 2


class TestValidateSysExecutable:
    """Tests for validate_sys_executable()."""

    validate_sys_executable = staticmethod(_validate.validate_sys_executable)

    def test_passes_when_sys_executable_used(self, tmp_path: Path) -> None:
        """No failure when sys.executable is used."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run([sys.executable, "-m", "pytest"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert failed == []

    def test_fails_when_bare_python_used(self, tmp_path: Path) -> None:
        """Fails when bare 'python' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text("subprocess.run(['python', '-m', 'pytest'])\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed

    def test_fails_when_bare_pip_used(self, tmp_path: Path) -> None:
        """Fails when bare 'pip' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_pip.py").write_text('subprocess.run(["pip", "install", "boto3"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed


class TestValidateTerraformTry:
    """Tests for validate_terraform_try()."""

    validate_terraform_try = staticmethod(_validate.validate_terraform_try)

    def test_passes_when_filemd5_inside_try(self, tmp_path: Path) -> None:
        """No failure when filemd5() is wrapped in try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "main.tf").write_text(
            'source_code_hash = try(\n  filemd5("build/lambda.zip"),\n  md5("fallback")\n)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_fails_when_filemd5_not_inside_try(self, tmp_path: Path) -> None:
        """Fails when filemd5() is used without wrapping try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "bad.tf").write_text(
            'source_code_hash = filemd5("build/lambda.zip")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed

    def test_passes_with_no_tf_files(self, tmp_path: Path) -> None:
        """No failure when terraform directory has no .tf files."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_fails_when_bare_file_not_inside_try(self, tmp_path: Path) -> None:
        """Fails when file() is used directly without wrapping try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "bad.tf").write_text(
            'policy = file("policy.json")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed

    def test_passes_when_file_inside_nested_try(self, tmp_path: Path) -> None:
        """No failure when file() is nested inside a try() as a fallback arg."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "ok.tf").write_text(
            'hash = try(\n  filemd5("build/lambda.zip"),\n  md5(file("ok.tf"))\n)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_retry_identifier_not_treated_as_try(self, tmp_path: Path) -> None:
        """Functions named retry() are NOT treated as try() (word boundary check)."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "retry.tf").write_text(
            'hash = retry(filemd5("build/lambda.zip"))\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed


class TestValidateInvariants:
    """Tests for validate_invariants(): @file gotcha and mock count checks."""

    def test_passes_when_no_violations(self, tmp_path: Path) -> None:
        """No failures when codebase has no @file violations and mock counts are OK."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # Other script: no @file pattern
        (tmp_path / "scripts" / "other.py").write_text(
            'subprocess.run(["git", "status"])\n',
            encoding="utf-8",
        )
        # postflight: 2 subprocess.run calls in cleanup_after_merge
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(branch):\n"
            "    subprocess.run(['git', 'checkout', 'main'])\n"
            "    subprocess.run(['git', 'pull'])\n"
            "    return True\n",
            encoding="utf-8",
        )
        # test file: side_effect list with 4 MagicMock entries (2*2+2=6 threshold)
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_example(self):\n"
            "        responses = [\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "            MagicMock(returncode=0),\n"
            "        ]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert failed == []

    def test_fails_on_at_file_without_instruction(self, tmp_path: Path) -> None:
        """Fails when a script uses '-p', '@file' pattern without an instruction string."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # A script that uses the bad pattern
        (tmp_path / "scripts" / "bad_script.py").write_text(
            'cmd.extend(["-p", f"@{some_file}"])\n',
            encoding="utf-8",
        )
        # Minimal postflight + test files so check 2 doesn't interfere
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(b):\n    subprocess.run(['git', 'checkout'])\n    return True\n",
            encoding="utf-8",
        )
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_x(self):\n"
            "        r = [MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert "Invariant checks" in failed
        # Error message must mention the @file gotcha
        # (validated by test passing -- the function adds to failed list)

    def test_passes_on_instruction_before_at_file(self, tmp_path: Path) -> None:
        """Does not flag a '-p' call list that carries an instruction before @file."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # A script that uses -p with an inline instruction preceding @file
        (tmp_path / "scripts" / "good_script.py").write_text(
            'cmd.extend(["-p", "review this", f"@{some_file}"])\n',
            encoding="utf-8",
        )
        (scripts_dir / "postflight.py").write_text(
            "def cleanup_after_merge(b):\n    subprocess.run(['git', 'checkout'])\n    return True\n",
            encoding="utf-8",
        )
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n"
            "    def test_x(self):\n"
            "        r = [MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert failed == []

    def test_fails_on_mock_count_mismatch(self, tmp_path: Path) -> None:
        """Fails when cleanup_after_merge has many subprocess calls but few test mocks."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # postflight: 12 subprocess.run calls (many, simulate a bloated function)
        postflight_src = "def cleanup_after_merge(branch):\n"
        for i in range(12):
            postflight_src += f"    subprocess.run(['cmd{i}'])\n"
        postflight_src += "    return True\n"
        (scripts_dir / "postflight.py").write_text(postflight_src, encoding="utf-8")

        # test file: only 1 MagicMock in side_effect list (12 > 1*2+2=4 -> FAIL)
        (tests_dir / "test_execute_recommendation.py").write_text(
            "class TestCleanupAfterMerge:\n    def test_x(self):\n        r = [MagicMock(returncode=0)]\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert "Invariant checks" in failed


class TestValidateNoUnderscoreInstructions:
    """Tests for validate_no_underscore_instructions()."""

    def test_underscore_check_passes_when_file_absent(self, tmp_path: Path) -> None:
        """Validation passes when the underscore instruction file is not present."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir(parents=True)
        # Only the hyphen variant exists -- underscore must be absent
        (github_dir / "copilot-instructions.md").write_text("# instructions\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_no_underscore_instructions(failed)

        assert failed == []

    def test_underscore_check_fails_when_file_present(self, tmp_path: Path) -> None:
        """Validation fails when .github/copilot_instructions.md exists."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir(parents=True)
        (github_dir / "copilot_instructions.md").write_text("# ghost\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_no_underscore_instructions(failed)

        assert "Underscore instruction file check" in failed


class TestValidateRecommendationsSchema:
    """Tests for validate_recommendations_schema() — specifically the python -c ban."""

    _VALID_REC = {
        "id": "rec-001",
        "date": "2026-01-01",
        "title": "Test recommendation",
        "source": "executor-supervision",
        "effort": "XS",
        "priority": "Low",
        "status": "open",
        "automatable": True,
        "risk": "low",
        "file": "scripts/foo.py",
        "context": "Some context.",
        "acceptance": "`grep -q 'pattern' scripts/foo.py`",
    }

    def _write_jsonl(self, tmp_path: Path, entries: list[dict]) -> Path:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        recs_path = log_dir / ".recommendations-log.jsonl"
        recs_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return recs_path

    def test_passes_on_valid_rec(self, tmp_path: Path) -> None:
        """A well-formed rec with a safe acceptance command passes."""
        self._write_jsonl(tmp_path, [self._VALID_REC])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert failed == []

    def test_fails_when_acceptance_contains_python_c(self, tmp_path: Path) -> None:
        """An acceptance field containing 'python -c' triggers a schema error."""
        import copy

        bad_rec = copy.deepcopy(self._VALID_REC)
        bad_rec["acceptance"] = '`python -c "import foo; assert foo.bar"`'
        self._write_jsonl(tmp_path, [bad_rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert "Recommendations schema validation" in failed

    def test_skips_when_file_missing(self, tmp_path: Path) -> None:
        """No error when the JSONL file does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert failed == []


class TestValidateSlocLimits:
    """Tests for validate_sloc_limits() -- Decision 43 SLOC gate."""

    def test_catches_over_limit_file(self, tmp_path: Path) -> None:
        """Files exceeding 500 SLOC without waiver are flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "big_module.py"
        big_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Bare waiver alone is insufficient for >500 SLOC files; budget registration required (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "waivered.py"
        big_file.write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 501,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_under_limit_file(self, tmp_path: Path) -> None:
        """Files under 500 SLOC pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small_file = scripts_dir / "small.py"
        small_file.write_text("x = 1\n" * 100, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from SLOC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        init_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        """Write a sloc_budgets.yaml into tmp_path/config/."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_registered_file_exceeds_budget_fails(self, tmp_path: Path) -> None:
        """A registered file whose current SLOC exceeds its budget fails the gate."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 601, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A registered file at exactly its budget does not fail."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_registered_file_below_budget_passes_advisory(self, tmp_path: Path) -> None:
        """A registered file below its budget passes (advisory only, no failure)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 550, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_oversized_unregistered_with_waiver_fails(self, tmp_path: Path) -> None:
        """A file >500 SLOC with a waiver but no budget registration fails (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "old_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 510,
            encoding="utf-8",
        )
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_stale_waiver_under_limit_is_advisory_not_failure(self, tmp_path: Path) -> None:
        """A file <=500 SLOC with a waiver is a stale-waiver advisory, not a failure."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "small_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 100,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_update_sloc_budgets_downward_only(self, tmp_path: Path) -> None:
        """_update_sloc_budgets never raises an existing budget below current SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "growing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        # Seed a budget BELOW current SLOC -- regen must not raise it
        self._write_budget(tmp_path, {"scripts/growing.py": 580})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert result["scripts/growing.py"] == 580

    def test_update_sloc_budgets_seeds_new_oversized(self, tmp_path: Path) -> None:
        """_update_sloc_budgets seeds a newly-oversized file at its current SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "new_big.py").write_text("x = 1\n" * 620, encoding="utf-8")
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert "scripts/new_big.py" in result
        assert result["scripts/new_big.py"] == 620

    def test_update_sloc_budgets_drops_shrunken_file(self, tmp_path: Path) -> None:
        """_update_sloc_budgets drops a file that shrank to <=500 SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "shrunken.py").write_text("x = 1\n" * 100, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/shrunken.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert "scripts/shrunken.py" not in result


class TestValidateCcLimits:
    """Tests for validate_cc_limits() -- Decision 43 cyclomatic-complexity gate."""

    def test_catches_over_limit_function(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Functions exceeding 20 branches without waiver are flagged by name."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        over_limit = scripts_dir / "big_func.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        over_limit.write_text(f"def heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert len(failed) == 1
        assert "Cyclomatic complexity" in failed[0]
        captured = capsys.readouterr()
        assert "heavy_dispatch" in captured.out

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Files with waiver annotation in first 10 lines are skipped entirely."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        waivered = scripts_dir / "waivered.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        waivered.write_text(
            f"# complexity-waiver: decision-43\ndef heavy_dispatch(x):\n{branches}\n",
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []

    def test_allows_under_limit_function(self, tmp_path: Path) -> None:
        """Functions with 5 branches pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small = scripts_dir / "small_func.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(5))
        small.write_text(f"def light_func(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from CC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        init_file.write_text(f"def heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert failed == []


class TestValidateComplexity:
    """Tests for validate_complexity()."""

    def test_returns_empty_list_when_no_outliers(self, tmp_path: Path) -> None:
        """Returns empty list and writes empty JSON when no complexity outliers."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create simple Python files with moderate complexity
        for i in range(3):
            py_file = src_dir / f"module{i}.py"
            py_file.write_text(
                "def func1(): pass\ndef func2(): pass\nimport os\nimport sys\n",
                encoding="utf-8",
            )

        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(3):
            md_file = prompts_dir / f"test{i}.md"
            md_file.write_text("Some text here.\nRegular lines only.\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        assert warnings == []
        assert failed == []
        warnings_file = tmp_path / "logs" / ".complexity-warnings.json"
        assert warnings_file.exists()
        import json

        data = json.loads(warnings_file.read_text(encoding="utf-8"))
        assert data == []

    def test_flags_outlier_python_files(self, tmp_path: Path) -> None:
        """Flags Python files with complexity >2 std-devs above package mean."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create 5 simple files with low complexity + 1 extreme outlier
        # This gives us more points for the std-dev calculation
        for i in range(5):
            py_file = src_dir / f"simple{i}.py"
            py_file.write_text(
                "def func1(): pass\nimport os\n",
                encoding="utf-8",
            )

        # Extreme outlier: 100 functions + 100 imports = 200
        complex_file = src_dir / "complex.py"
        complex_lines = []
        for i in range(1, 101):
            complex_lines.append(f"def f{i}(): pass")
        # Add many imports to reach 100+ unique ones
        for i in range(100):
            complex_lines.append(f"import m{i}")
        complex_file.write_text("\n".join(complex_lines) + "\n", encoding="utf-8")

        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(3):
            md_file = prompts_dir / f"test{i}.md"
            md_file.write_text("Regular text here.\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        assert len(warnings) > 0
        assert any(w["file"].endswith("complex.py") for w in warnings)
        assert failed == []

    def test_skips_excluded_files(self, tmp_path: Path) -> None:
        """Skips __init__.py, conftest.py, and files under excluded dirs."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create excluded files
        init_file = src_dir / "__init__.py"
        init_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        conftest_file = src_dir / "conftest.py"
        conftest_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        # Create file in excluded dir
        pip_dir = tmp_path / "pip"
        pip_dir.mkdir()
        pip_file = pip_dir / "module.py"
        pip_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        # Excluded files should not appear in warnings
        file_paths = [w["file"] for w in warnings]
        assert not any("__init__.py" in p for p in file_paths)
        assert not any("conftest.py" in p for p in file_paths)
        assert not any("pip" in p for p in file_paths)
        assert failed == []

    def test_skips_packages_with_fewer_than_3_files(self, tmp_path: Path) -> None:
        """Skips complexity analysis for packages with <3 files."""
        src_dir = tmp_path / "src" / "small_pkg"
        src_dir.mkdir(parents=True)

        # Create only 2 files (below threshold)
        for i in range(2):
            py_file = src_dir / f"module{i}.py"
            py_file.write_text(
                "def func1(): pass\n" * 10 + "import a\n" * 10,
                encoding="utf-8",
            )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        # Should not flag any warnings (package too small)
        assert all("small_pkg" not in w.get("package", "") for w in warnings)
        assert failed == []

    def test_never_appends_to_failed_list(self, tmp_path: Path) -> None:
        """Complexity analysis never appends to the failed list."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        complex_file = src_dir / "complex.py"
        complex_file.write_text(
            "def f1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        for i in range(2):
            py_file = src_dir / f"simple{i}.py"
            py_file.write_text("def func(): pass\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_complexity(failed)

        assert failed == []


validate_executor_boundary = _validate.validate_executor_boundary
validate_outbox_staleness = _validate.validate_outbox_staleness
validate_rec_write_paths = _validate.validate_rec_write_paths
validate_warehouse_write_sources = _validate.validate_warehouse_write_sources


class TestValidateRecWritePaths:
    """Tests for validate_rec_write_paths() -- rec JSONL write-path enforcement."""

    def test_catches_direct_recs_jsonl_open_append(self, tmp_path: Path, capsys) -> None:
        """Detects RECS_JSONL.open('a') in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_script.py"
        bad_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert len(failed) > 0
        assert any("bad_script.py" in e for e in failed)

    def test_allows_whitelist_portal_file(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_allows_whitelist_sync_recommendations(self, tmp_path: Path, capsys) -> None:
        """sync_recommendations.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        sync_file = scripts_dir / "sync_recommendations.py"
        sync_file.write_text(
            'with open(_LOCAL_RECS_FILE, "w", encoding="utf-8") as fh: fh.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_clean_scripts_directory_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts with no direct JSONL writes pass without failures."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []


class TestValidateWarehouseWriteSources:
    """Tests for validate_warehouse_write_sources() -- warehouse-as-source invariant."""

    def test_catches_unwhitelisted_ops_recommendations_write(self, tmp_path: Path, capsys) -> None:
        """Detects OpsWriter().write('ops_*', ...) in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_replay.py"
        bad_file.write_text(
            'OpsWriter().write("ops_recommendations", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_replay.py" in e for e in failed)

    def test_catches_aliased_writer_call(self, tmp_path: Path, capsys) -> None:
        """Detects writer.write('ops_*', ...) where writer is an OpsWriter instance."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_alias.py"
        bad_file.write_text(
            'writer = OpsWriter()\nwriter.write("ops_decisions", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_alias.py" in e for e in failed)

    def test_allows_whitelisted_portal_for_unmigrated_tables(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py stays whitelisted for the NOT-yet-migrated tables (session_log)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'OpsWriter().write("ops_session_log", merged)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []

    def test_migrated_tables_opswriter_blocked_even_for_whitelisted_portal(self, tmp_path: Path, capsys) -> None:
        """Decision 84 I-1: the migrated-tables block applies to ALL files including the whitelist.

        Even whitelisted callers (ops_data_portal.py) must not route ops_recommendations,
        ops_decisions, or ops_priority_queue through OpsWriter -- readers serve DuckLake, so an
        Iceberg write is a silent split-brain. The guard must fire regardless of whitelist status.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        for table in ("ops_recommendations", "ops_decisions", "ops_priority_queue"):
            portal_file.write_text(
                f'OpsWriter().write("{table}", merged)\n',
                encoding="utf-8",
            )
            with patch("scripts.checks._common.ROOT", tmp_path):
                failed: list[str] = []
                validate_warehouse_write_sources(failed)
            assert len(failed) > 0, f"migrated-table block must fire for {table}"
            assert any("DuckLake-migrated table" in e for e in failed)

    def test_s3_log_store_queue_producer_exemption(self, tmp_path: Path, capsys) -> None:
        """The dormant queue producer keeps its tracked exemption until the T2.26 repoint."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        store_file = scripts_dir / "s3_log_store.py"
        store_file.write_text(
            'ops.write("ops_priority_queue", enriched)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert not any("DuckLake-migrated table" in e for e in failed)

    def test_clean_script_with_no_warehouse_writes_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only call portal functions (file_rec) pass cleanly."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []


class TestValidateExecutorBoundary:
    """Tests for validate_executor_boundary() -- Decision 44 enforcement."""

    _VALID_REC = {
        "id": "rec-001",
        "date": "2026-01-01",
        "title": "Test boundary rec",
        "source": "executor-supervision",
        "effort": "XS",
        "priority": "High",
        "status": "open",
        "automatable": True,
        "risk": "low",
        "file": "scripts/executor/plan.py",
        "context": "Some context about the executor plan module.",
        "acceptance": "`python -m pytest tests/test_executor_plan.py -x -q`",
    }

    def _write_jsonl(self, tmp_path: Path, entries: list[dict]) -> Path:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        recs_path = log_dir / ".recommendations-log.jsonl"
        recs_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return recs_path

    def test_boundary_violation_detected(self, tmp_path: Path) -> None:
        """Open rec with boundary file + automatable:true is reported as a violation."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        # file matches "scripts/executor/" pattern, automatable:True, status:open
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert "Executor boundary validation" in failed

    def test_boundary_compliant_passes(self, tmp_path: Path) -> None:
        """Open rec with boundary file but automatable:false passes."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["automatable"] = False
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_non_boundary_file_ignored(self, tmp_path: Path) -> None:
        """Open rec targeting a non-boundary file with automatable:true passes."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["file"] = "scripts/session_postflight.py"
        rec["acceptance"] = "`python -m pytest tests/test_session_postflight.py -x -q`"
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_closed_rec_ignored(self, tmp_path: Path) -> None:
        """Closed rec with boundary file + automatable:true is not flagged."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["status"] = "closed"
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_missing_jsonl_skips_gracefully(self, tmp_path: Path) -> None:
        """Missing JSONL file does not raise and does not append to failed."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_executor_boundary_matches_new_prompt_path(self, tmp_path: Path) -> None:
        """config/agent/executor/prompts/*.prompt.md is recognised as a boundary file.

        Regression guard for T-1.7 config split: the YAML boundary_patterns must list
        the new path so open recs targeting executor prompts are still flagged.
        """
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["file"] = "config/agent/executor/prompts/planning.prompt.md"
        rec["acceptance"] = "`grep -q planning config/agent/executor/prompts/planning.prompt.md`"
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert "Executor boundary validation" in failed

    def test_boundary_pattern_in_acceptance_only_not_flagged(self, tmp_path: Path) -> None:
        """A boundary pattern in the acceptance command but NOT the file is not a violation.

        Regression for the rec-2048 false positive: validate_executor_boundary previously
        substring-matched boundary patterns against the acceptance command text, so a rec
        targeting a benign file (docs/ROADMAP-PLATFORM.yaml) whose acceptance greps for a
        string containing a boundary filename ('DECISIONS.md') was wrongly flagged. The
        check now matches the `file` field only.
        """
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["file"] = "docs/ROADMAP-PLATFORM.yaml"
        rec["acceptance"] = "`grep -c 'does NOT touch DECISIONS.md' docs/ROADMAP-PLATFORM.yaml`"
        self._write_jsonl(tmp_path, [rec])
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []


# ---------------------------------------------------------------------------
# TestValidateOutboxStaleness
# ---------------------------------------------------------------------------


class TestValidateOutboxStaleness:
    """Tests for validate_outbox_staleness()."""

    def test_no_outbox_directory_passes(self, tmp_path: Path, capsys) -> None:
        """No outbox directory: passes with 'No outbox directory' message."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "No outbox directory" in captured.out
        assert failed == []

    def test_recent_files_passes(self, tmp_path: Path, capsys) -> None:
        """Outbox with files modified < 24h ago: passes with count displayed."""
        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations"
        outbox.mkdir(parents=True)
        (outbox / "entry.jsonl").write_text("{}", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "none stale" in captured.out
        assert failed == []

    def test_stale_files_prints_warning(self, tmp_path: Path, capsys) -> None:
        """Outbox with files modified > 24h ago: prints WARNING (not a hard failure)."""
        import os
        import time

        outbox = tmp_path / "logs" / ".ops-outbox" / "ops_recommendations"
        outbox.mkdir(parents=True)
        stale_file = outbox / "stale.jsonl"
        stale_file.write_text("{}", encoding="utf-8")
        # Set mtime to 48h ago
        old_mtime = time.time() - 48 * 3600
        os.utime(str(stale_file), (old_mtime, old_mtime))

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_outbox_staleness(failed)
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        # Stale outbox is a warning only, not a hard failure
        assert failed == []


def _mock_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a MagicMock that quacks like subprocess.CompletedProcess."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class TestEnsureFreshDqResults:
    """Tests for ensure_fresh_dq_results() — the DQ runner auto-invoke."""

    @pytest.fixture(autouse=True)
    def _inject_boto3_stub(self):
        """Ensure boto3 is in sys.modules so patch("boto3.Session") resolves on CI runners where boto3 is not installed."""
        if "boto3" not in sys.modules:
            sys.modules["boto3"] = MagicMock()
            yield
            del sys.modules["boto3"]
        else:
            yield

    def test_ensure_fresh_dq_runs_when_cache_missing(self, tmp_path: Path, capsys) -> None:
        """No dq-latest.json on disk: credential check runs, then data_quality_runner is invoked."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache missing" in captured.out
        assert "data_quality_runner" in captured.out
        # One subprocess call: data_quality_runner only (credential check is boto3).
        assert mock_run.call_count == 1
        runner_cmd = mock_run.call_args_list[0].args[0]
        assert "data_quality_runner" in " ".join(runner_cmd)
        assert failed == []

    def test_ensure_fresh_dq_runs_when_cache_stale(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json older than the freshness window: re-runs the runner."""
        import os
        import time

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Backdate mtime by 2 hours -- well past the 1h freshness window.
        old_mtime = time.time() - 2 * 3600
        os.utime(str(dq_file), (old_mtime, old_mtime))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache stale" in captured.out
        assert "data_quality_runner" in captured.out
        assert mock_run.call_count == 1
        assert failed == []

    def test_ensure_fresh_dq_skips_when_cache_fresh(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json modified within the last hour: skip with a clear message."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Default mtime is 'now', well inside the 1h freshness window.

        with patch("scripts.checks._common.ROOT", tmp_path), patch("scripts.checks._common.run") as mock_run:
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache fresh" in captured.out
        # Fresh cache must short-circuit before invoking subprocess at all.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_sso_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: failed boto3 credential check prints actionable guidance and skips."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("Token has expired")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        # No subprocess calls -- the runner was never invoked after the credential failure.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_credentials_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: any boto3 credential error must skip with guidance, not crash."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.side_effect = Exception("ProfileNotFound")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        assert mock_run.call_count == 0
        assert failed == []


class TestRunCoverageCheck:
    """Tests for run_coverage_check() — the --coverage advisory mode."""

    def test_run_coverage_check_no_changed_files_prints_message(self, capsys) -> None:
        """When there are no changed files, the function reports nothing to check."""
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "coverage" in captured.out.lower()
        assert "No changed files" in captured.out

    def test_run_coverage_check_all_covered(self, capsys) -> None:
        """When every changed file is covered, the report says 'All scope files covered'."""
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/ops_data_portal.py"]),
            patch("scripts.verifiers.check_coverage", return_value=[]),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "All scope files covered" in captured.out

    def test_run_coverage_check_lists_uncovered(self, capsys) -> None:
        """Uncovered files are printed line-by-line under the report header."""
        with (
            patch(
                "scripts.checks._common.get_changed_files",
                return_value=["docs/foo.md", "scripts/ops_data_portal.py"],
            ),
            patch(
                "scripts.verifiers.check_coverage",
                return_value=["docs/foo.md"],
            ),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        assert "- docs/foo.md" in captured.out
        assert "Advisory only" in captured.out

    def test_run_coverage_check_uses_supplied_changed_files(self, capsys) -> None:
        """A supplied changed_files list is used verbatim, skipping the get_changed_files() call
        (VF-02(d): the --pre closure reuses its already-computed diff -- budget-safe)."""
        with (
            patch("scripts.checks._common.get_changed_files") as mock_get_changed,
            patch("scripts.verifiers.check_coverage", return_value=["docs/foo.md"]),
        ):
            run_coverage_check(changed_files=["docs/foo.md", "scripts/ops_data_portal.py"])
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        mock_get_changed.assert_not_called()


class TestExtractEnforcedMap:
    """Unit tests for _extract_enforced_map() YAML parser."""

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_enforced_map("") == {}

    def test_invalid_yaml_returns_empty(self) -> None:
        assert _extract_enforced_map("{invalid: [yaml: content}") == {}

    def test_no_tables_key_returns_empty(self) -> None:
        assert _extract_enforced_map("database: db\n") == {}

    def test_row_count_enforced_false(self) -> None:
        yaml_text = "tables:\n  t:\n    row_count:\n      min: 1\n      enforced: false\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", None, "row_count")] is False

    def test_row_count_default_true(self) -> None:
        yaml_text = "tables:\n  t:\n    row_count:\n      min: 1\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", None, "row_count")] is True

    def test_recency_enforced(self) -> None:
        yaml_text = "tables:\n  t:\n    recency:\n      column: ts\n      enforced: false\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "ts", "recency")] is False

    def test_bare_string_test_defaults_true(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c:\n        tests:\n          - not_null\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "not_null")] is True

    def test_dict_test_with_enforced(self) -> None:
        yaml_text = (
            "tables:\n  t:\n    columns:\n      c:\n        tests:\n"
            "          - accepted_values:\n              values: [a]\n              enforced: false\n"
        )
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "accepted_values")] is False

    def test_dict_test_params_not_dict(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c:\n        tests:\n          - not_null: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "not_null")] is True

    def test_non_dict_table_def_skipped(self) -> None:
        yaml_text = "tables:\n  t: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result == {}

    def test_non_dict_col_def_skipped(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result == {}


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestGraduationGuard:
    """Tests for _check_graduation_guard() -- enforced flip validation."""

    _OLD_YAML_ENFORCED_FALSE = (
        "tables:\n"
        "  tbl:\n"
        "    columns:\n"
        "      col:\n"
        "        tests:\n"
        "          - accepted_values:\n"
        "              values: [a]\n"
        "              enforced: false\n"
    )
    _NEW_YAML_ENFORCED_TRUE = (
        "tables:\n"
        "  tbl:\n"
        "    columns:\n"
        "      col:\n"
        "        tests:\n"
        "          - accepted_values:\n"
        "              values: [a]\n"
        "              enforced: true\n"
    )

    def _write_dq_latest(self, tmp_path: Path, checks: list) -> None:
        import json

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "FAIL", "checks": checks}),
            encoding="utf-8",
        )

    def _write_new_yaml(self, tmp_path: Path, content: str) -> None:
        yaml_file = tmp_path / "config" / "agent" / "data_quality" / "test.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text(content, encoding="utf-8")

    def _make_run(self, old_yaml: str = "", git_show_rc: int = 0, no_changes: bool = False):
        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "" if no_changes else "config/agent/data_quality/test.yaml\n"
            elif "show" in joined and "HEAD:" in joined:
                result.stdout = old_yaml
                result.returncode = git_show_rc
            else:
                result.stdout = ""
            return result

        return _run

    def test_blocks_flip_when_fail(self, tmp_path: Path) -> None:
        """Blocks enforced:false -> enforced:true flip when verdict is FAIL."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.accepted_values" in failed[0]
        assert "enforced:true" in failed[0]

    def test_allows_flip_when_pass(self, tmp_path: Path) -> None:
        """Allows enforced:false -> enforced:true flip when verdict is PASS."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "PASS"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_warns_no_block_missing_dq_file(self, tmp_path: Path, capsys) -> None:
        """Warns but does not block when dq-latest.json is missing."""
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run()),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "missing" in capsys.readouterr().out

    def test_warns_no_block_no_checks_array(self, tmp_path: Path, capsys) -> None:
        """Warns but does not block when dq-latest.json has no 'checks' array."""
        import json

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        (dq_dir / "dq-latest.json").write_text(json.dumps({"verdict": "FAIL"}), encoding="utf-8")
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run()),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "checks" in capsys.readouterr().out

    def test_warns_no_block_on_skip_verdict(self, tmp_path: Path, capsys) -> None:
        """Treats SKIP verdict as inconclusive -- warns but does not block."""
        old_yaml = (
            "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: false\n"
        )
        new_yaml = (
            "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: true\n"
        )
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "SKIP"}],
        )
        self._write_new_yaml(tmp_path, new_yaml)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=old_yaml)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "SKIP" in capsys.readouterr().out

    def test_blocks_new_enforced_true_when_fail(self, tmp_path: Path) -> None:
        """Blocks a new check added directly as enforced:true when verdict is FAIL."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(git_show_rc=1)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.accepted_values" in failed[0]

    def test_no_dq_yaml_changes_returns_early(self, tmp_path: Path) -> None:
        """Returns without loading dq-latest.json when no YAML files changed."""
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(no_changes=True)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_pre_mode_does_not_call_guard(self) -> None:
        """main() --pre does not invoke _check_graduation_guard."""
        with (
            patch("validate._check_graduation_guard") as mock_guard,
            patch("validate.run_lint_checks"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("scripts.checks._common.run", return_value=MagicMock(stdout="agent/test\n", returncode=0)),
            patch.dict("os.environ", {"_VALIDATE_DEPTH": "0"}),
            patch("sys.argv", ["validate.py", "--pre"]),
        ):
            with pytest.raises(SystemExit):
                _validate.main()
        mock_guard.assert_not_called()


class TestGraduationGuardUnavailableCarveout:
    """UNAVAILABLE per-check verdict warns (inconclusive) and does NOT block graduation."""

    _OLD_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: false\n"
    )
    _NEW_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: true\n"
    )

    def _write_dq_latest(self, tmp_path: Path, checks: list) -> None:
        import json

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "DEGRADED", "checks": checks}),
            encoding="utf-8",
        )

    def _write_new_yaml(self, tmp_path: Path, content: str) -> None:
        yaml_file = tmp_path / "config" / "agent" / "data_quality" / "test.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text(content, encoding="utf-8")

    def _make_run(self, old_yaml: str = "", git_show_rc: int = 0):
        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "config/agent/data_quality/test.yaml\n"
            elif "show" in joined and "HEAD:" in joined:
                result.stdout = old_yaml
                result.returncode = git_show_rc
            else:
                result.stdout = ""
            return result

        return _run

    def test_unavailable_verdict_warns_does_not_block(self, tmp_path: Path, capsys) -> None:
        """UNAVAILABLE per-check verdict warns (inconclusive) and does not append a graduation failure."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "UNAVAILABLE"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "UNAVAILABLE" in capsys.readouterr().out

    def test_non_pass_non_skip_non_unavailable_still_blocks(self, tmp_path: Path) -> None:
        """A genuine non-PASS/non-SKIP/non-UNAVAILABLE verdict (FAIL) still blocks graduation."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        import json

        checks_data = [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "FAIL"}]
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "FAIL", "checks": checks_data}),
            encoding="utf-8",
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.not_null" in failed[0]


class TestValidateDqManifestGate:
    """Tests for validate_dq_manifest_gate() -- allowlist enforcement."""

    _OPS_YAML = (
        "tables:\n"
        "  ops_recommendations:\n"
        "    columns:\n"
        "      title:\n"
        "        tests:\n"
        "          - not_null:\n"
        "              enforced: true\n"
    )

    def _write_ops_yaml(self, tmp_path: Path, content: str = "") -> None:
        dq_dir = tmp_path / "config" / "agent" / "data_quality"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "ops.yaml").write_text(content or self._OPS_YAML, encoding="utf-8")

    def _write_manifest(self, tmp_path: Path, state: str) -> None:
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        manifest_yaml = f"table: ops_recommendations\nfields:\n  title:\n    enforcement_ready: {state}\n"
        (dec_dir / "ops_recommendations.yaml").write_text(manifest_yaml, encoding="utf-8")

    def _run(self, tmp_path: Path) -> list[str]:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            _validate.validate_dq_manifest_gate(failed)
        return failed

    def test_allowed_state_ready_now_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "READY_NOW")
        assert self._run(tmp_path) == []

    def test_allowed_state_write_fix_deployed_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "write_fix_deployed")
        assert self._run(tmp_path) == []

    def test_allowed_state_graduated_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "GRADUATED")
        assert self._run(tmp_path) == []

    def test_allowed_state_needs_temporal_gate_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_TEMPORAL_GATE")
        assert self._run(tmp_path) == []

    def test_blocked_state_needs_write_fix_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_WRITE_FIX")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_blocked_state_needs_data_correction_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_DATA_CORRECTION")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_unknown_state_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "SOME_FUTURE_UNKNOWN_STATE")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_missing_manifest_entry_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        (dec_dir / "ops_recommendations.yaml").write_text("table: ops_recommendations\nfields: {}\n", encoding="utf-8")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_non_enforced_column_skipped(self, tmp_path: Path) -> None:
        ops_yaml = (
            "tables:\n"
            "  ops_recommendations:\n"
            "    columns:\n"
            "      title:\n"
            "        tests:\n"
            "          - not_null:\n"
            "              enforced: false\n"
        )
        self._write_ops_yaml(tmp_path, ops_yaml)
        assert self._run(tmp_path) == []

    def test_missing_ops_yaml_skips_gracefully(self, tmp_path: Path) -> None:
        assert self._run(tmp_path) == []


class TestCheckSourceRegistry:
    """Tests for check_source_registry()."""

    def test_source_registry_ci_guard_accepts_registered(self, tmp_path: Path) -> None:
        """check_source_registry() passes when all schedule.yaml agent names are registered."""
        import yaml

        (tmp_path / "config" / "agent" / "data_quality").mkdir(parents=True)

        def _mk_entry(cid: str) -> dict:
            return {"canonical_id": cid, "description": "d", "signal_interpretation": "s", "added_date": "2026-01-01"}

        (tmp_path / "config" / "agent" / "data_quality" / "source_registry.yaml").write_text(
            yaml.dump({"entries": [_mk_entry("doc-freshness"), _mk_entry("orphan-code")]}),
            encoding="utf-8",
        )
        (tmp_path / ".github" / "agents").mkdir(parents=True)
        (tmp_path / ".github" / "agents" / "schedule.yaml").write_text(
            yaml.dump({"agents": [{"name": "doc-freshness"}, {"name": "orphan-code"}]}),
            encoding="utf-8",
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "ops_data_portal.py").write_text("", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            check_source_registry(failed)
        assert failed == [], f"Expected no failures but got: {failed}"

    def test_source_registry_ci_guard_rejects_unregistered(self, tmp_path: Path) -> None:
        """check_source_registry() fails when a schedule.yaml agent name is not registered."""
        import yaml

        (tmp_path / "config" / "agent" / "data_quality").mkdir(parents=True)

        def _mk_entry(cid: str) -> dict:
            return {"canonical_id": cid, "description": "d", "signal_interpretation": "s", "added_date": "2026-01-01"}

        (tmp_path / "config" / "agent" / "data_quality" / "source_registry.yaml").write_text(
            yaml.dump({"entries": [_mk_entry("doc-freshness")]}),
            encoding="utf-8",
        )
        (tmp_path / ".github" / "agents").mkdir(parents=True)
        (tmp_path / ".github" / "agents" / "schedule.yaml").write_text(
            yaml.dump({"agents": [{"name": "doc-freshness"}, {"name": "unregistered-agent-xyz"}]}),
            encoding="utf-8",
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "ops_data_portal.py").write_text("", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            check_source_registry(failed)
        assert "Source registry CI guard" in failed


class TestValidateScheduledAgentLogs:
    """Tests for validate_scheduled_agent_logs()."""

    def _make_run(self, changed_files: list[str]):
        """Return a mock for validate.run that reports the given changed files."""

        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "\n".join(changed_files) + "\n" if changed_files else ""
            return result

        return mock_run

    def test_passes_with_valid_agent_log(self, tmp_path: Path) -> None:
        """Passes when all changed files are valid scheduled-agent JSONL logs."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text(
            '{"type": "priority-queue-entry", "timestamp": "2026-05-09T18:20:00Z", "rank": 1}\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_fails_on_canonical_state_write(self) -> None:
        """Fails when logs/.recommendations-log.jsonl appears in the diff."""
        changed = [
            "logs/agents/rec-curator/20260509T182000Z.jsonl",
            "logs/.recommendations-log.jsonl",
        ]
        with patch("scripts.checks._common.run", side_effect=self._make_run(changed)):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_fails_on_malformed_jsonl(self, tmp_path: Path) -> None:
        """Fails when a JSONL file contains a non-JSON line."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "20260509T182000Z.jsonl"
        log_file.write_text("this is not json\n", encoding="utf-8")
        changed = ["logs/agents/rec-curator/20260509T182000Z.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_fails_on_invalid_filename(self, tmp_path: Path) -> None:
        """Fails when JSONL filename does not match the ISO timestamp pattern."""
        agent_dir = tmp_path / "logs" / "agents" / "rec-curator"
        agent_dir.mkdir(parents=True)
        log_file = agent_dir / "output.jsonl"
        log_file.write_text(
            '{"type": "cluster", "timestamp": "2026-05-09T18:20:00Z"}\n',
            encoding="utf-8",
        )
        changed = ["logs/agents/rec-curator/output.jsonl"]
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(changed)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert "Scheduled agent log validation" in failed

    def test_skips_when_source_files_changed(self) -> None:
        """Skips validation when non-log files appear in the diff (feature branch)."""
        changed = [
            "scripts/validate.py",
            "logs/agents/rec-curator/20260509T182000Z.jsonl",
        ]
        with patch("scripts.checks._common.run", side_effect=self._make_run(changed)):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_skips_when_no_files_changed(self) -> None:
        """Skips validation when there are no changed files relative to main."""
        with patch("scripts.checks._common.run", side_effect=self._make_run([])):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []


class TestValidateIamRunnerPolicy:
    """Tests for validate_iam_runner_policy()."""

    def test_passes_when_all_actions_present(self, tmp_path: Path) -> None:
        """No failures when all manifest actions are in the Terraform file."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:GetObject'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert failed == []

    def test_fails_when_action_missing(self, tmp_path: Path) -> None:
        """Fails when an action in the manifest is not in the Terraform file."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:DeleteObject'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert len(failed) == 1
        assert "Missing actions" in failed[0]
        assert "s3:DeleteObject" in failed[0]

    def test_requires_quoted_match(self, tmp_path: Path) -> None:
        """Actions must appear within quotes to prevent partial matches."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:Get'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        # s3:Get matches part of s3:GetObject, but we want exact quoted match
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert len(failed) == 1
        assert "s3:Get" in failed[0]

    def test_skips_when_manifest_missing(self, tmp_path: Path, capsys) -> None:
        """Gracefully skips if config/agent/validate/iam_runner_manifest.yaml does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        captured = capsys.readouterr()
        assert "SKIPPED: IAM runner manifest missing" in captured.out
        assert failed == []


class TestGetChangedFilesOriginMain:
    """Tests for the get_changed_files() origin/main semantics."""

    def test_uses_origin_main_on_success(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/validate.py\ntests/test_validate.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert "tests/test_validate.py" in files
        assert any("origin/main" in c for c in calls[0])

    def test_falls_back_to_head_on_nonzero(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            if "origin/main" in cmd:
                result.returncode = 1
                result.stdout = ""
            else:
                result.returncode = 0
                result.stdout = "scripts/validate.py\n"
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert "scripts/validate.py" in files
        assert any("origin/main" in c for c in calls[0])
        assert any("HEAD" in c for c in calls[1])

    def test_empty_result_returns_empty_list(self) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            files = get_changed_files()

        assert files == []


def _pre_mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
    """Shared subprocess mock that handles git branch + everything else."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "agent/test-branch\n"
    return result


class TestExcludedHeavyDeps:
    """Excluded-heavy import-name set derivation from the REAL requirements files (rec-2485)."""

    def test_heavy_deps_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("pyarrow", "pandas", "numpy", "duckdb"):
            assert name in excluded, f"{name} should be excluded (heavy, requirements.txt-only)"

    def test_fast_tier_deps_not_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("ruff", "mypy", "pytest", "pyyaml", "pydantic"):
            assert name not in excluded, f"{name} is present in requirements-fast.txt; must not be excluded"

    def test_parse_requirement_dist_names_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        assert _parse_requirement_dist_names(tmp_path / "nonexistent-requirements.txt") == set()


class TestFastTierCollectability:
    """Classifier routing: (returncode, output) -> (runnable | deferred) (rec-2485).

    Every heavy-dep-absence case below monkeypatches importlib.util.find_spec because pyarrow
    (and the other heavy deps) are actually installed in this dev venv -- only requirements-fast.txt
    (the pr-validate CI job) omits them, so genuine absence must be simulated here.
    """

    def test_heavy_dep_collection_error_defers(self) -> None:
        """A collect-only error whose root cause is a genuinely-absent excluded-heavy dep defers."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == []
        assert deferred == [("tests/test_some_heavy_dep_file.py", "pyarrow")]

    def test_runtime_failure_hard_fails(self) -> None:
        """A file that collects fine but fails at runtime (pytest exit 1) still hard-fails the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0 if "--collect-only" in cmd else 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_non_heavy_modulenotfound_routes_to_runnable(self) -> None:
        """A collection error naming a repo-local (non-excluded) module routes to runnable."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'scripts.some_deleted_module'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_something.py"])

        assert runnable == ["tests/test_something.py"]
        assert deferred == []

    def test_syntaxerror_collection_error_hard_fails(self) -> None:
        """A collection error with NO 'No module named' line (SyntaxError) routes to runnable, not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "SyntaxError: invalid syntax"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken.py"])

        assert runnable == ["tests/test_broken.py"]
        assert deferred == []

    def test_cannot_import_name_hard_fails(self) -> None:
        """A collection error carrying 'ImportError: cannot import name' (no 'No module named') hard-fails."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ImportError: cannot import name 'Thing' from 'scripts.foo'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken_import.py"])

        assert runnable == ["tests/test_broken_import.py"]
        assert deferred == []

    def test_present_module_not_deferred(self) -> None:
        """A ModuleNotFoundError naming an excluded-heavy dep that IS importable (find_spec not None) is not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == ["tests/test_some_heavy_dep_file.py"]
        assert deferred == []

    def test_iceberg_reader_defers_when_pyarrow_absent(self) -> None:
        """Real-file proof: the actual PR #405 offending file (tests/test_iceberg_reader.py, which
        imports pyarrow at module scope) lands in `deferred`, not `failed`, when pyarrow is simulated
        absent via find_spec."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_iceberg_reader.py"])

        assert runnable == []
        assert deferred == [("tests/test_iceberg_reader.py", "pyarrow")]


class TestRunPytestDiff:
    """Orchestration behaviours of run_pytest_diff() -- the consumer moved out of validate.py (rec-2485)."""

    def test_no_op_when_no_changed_tests(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")):
            run_pytest_diff([], failed)
        assert failed == []

    def test_prints_loud_warning_and_does_not_redden_when_all_defer(self, capsys: pytest.CaptureFixture) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = ""
            result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py"], failed)

        captured = capsys.readouterr()
        assert "DEFERRED TO FULL TIER" in captured.out
        assert "tests/test_iceberg_reader.py" in captured.out
        assert "pyarrow" in captured.out
        assert failed == []


class TestRunPytestDiffSingleExecution:
    """Common-case single execution (acceptance criterion 1): when every changed test file
    collects and passes, run_pytest_diff issues EXACTLY ONE non-collect-only pytest invocation
    over the runnable set -- no proactive per-file isolated probe."""

    def test_runs_pytest_exactly_once_in_mixed_case(self) -> None:
        """tests/test_iceberg_reader.py defers at --collect-only (never gets a real run at all);
        tests/test_validate.py collects fine and passes, so it gets exactly one real run."""
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                if "tests/test_iceberg_reader.py" in cmd:
                    result.returncode = 2
                    result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
                else:
                    result.returncode = 0
            else:
                result.returncode = 0
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py", "tests/test_validate.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_validate.py" in real_run_cmds[0]
        assert "tests/test_iceberg_reader.py" not in real_run_cmds[0]
        assert failed == []

    def test_runs_pytest_exactly_once_when_all_runnable_pass(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_a.py" in real_run_cmds[0]
        assert "tests/test_b.py" in real_run_cmds[0]
        assert failed == []


class TestRunPytestDiffReactiveDefer:
    """Reactive lazy-import heavy-dep defer (acceptance criterion 2): a genuinely-absent
    excluded heavy dependency imported lazily (function scope, invisible to --collect-only) is
    caught only AFTER the combined run fails, via a per-file isolated re-classification pass
    (rec-2572..2576 test_ops_writer.py shape). Every other failure shape reddens immediately."""

    def test_runtime_lazy_import_of_excluded_dep_defers(self) -> None:
        """A file that collects fine but fails at real-run time with a genuinely-absent excluded
        dep defers, via the reactive per-file probe -- and does not redden the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::TestCompact::test_compact_x - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_failure_with_no_module_error_reddens_immediately(self) -> None:
        """A file that collects fine and fails at runtime with no 'No module named' signature at
        all is a genuine failure -- must redden immediately (fail-closed), with no reactive re-run."""
        real_run_calls = {"n": 0}

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
            else:
                real_run_calls["n"] += 1
                result.returncode = 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]
        assert real_run_calls["n"] == 1, "no reactive re-run should occur when there is no heavy-dep signature"

    def test_runtime_knockon_failures_still_defer_whole_file(self) -> None:
        """When one failing test names the missing excluded dep and OTHER failures in the same
        combined run look unrelated (e.g. state-pollution knock-on effects from the first
        failure), the whole file still defers -- ANY match is sufficient, not ALL, because once
        a required dependency is known absent, the other failures in that same run aren't
        independently meaningful."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::A::test_a - assert 0 == 1\n"
                    "FAILED tests/test_ops_writer.py::B::test_b - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                    "FAILED tests/test_ops_writer.py::C::test_c - TypeError: 'NoneType' object is not subscriptable\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_lazy_import_of_present_dep_not_deferred(self) -> None:
        """A runtime ModuleNotFoundError naming an excluded dep that IS actually importable
        (find_spec not None) is a genuine failure, not a fast-tier absence -- must redden, not defer."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_reactive_rerun_reddens_on_survivor_failure(self) -> None:
        """Two changed files: one's combined-run failure resolves (via the isolated probe) to a
        genuine failure (survivor), the other to a heavy-dep defer. The survivor is re-run alone;
        a real failure there still reddens the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated per-file probe (_runtime_heavy_dep_defer_reason)
                if "tests/test_a.py" in cmd:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                else:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
            elif "tests/test_b.py" in cmd:
                # combined gate run: both files present, mixed failure signature
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                    "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
                )
            else:
                # reactive re-run of the survivor alone: genuine failure persists
                result.returncode = 1
                result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_isolated_probe_passing_makes_file_a_survivor(self) -> None:
        """A file whose combined-run failure carries a heavy-dep signature (triggering the
        reactive fallback) but whose ISOLATED single-file run actually passes (e.g. the failure
        was a cross-file interaction, not a real heavy-dep absence) is treated as a survivor, not
        deferred -- covers _runtime_heavy_dep_defer_reason's rc==0 -> None branch via the reactive
        path specifically (as opposed to the collect-only-only tests in TestFastTierCollectability)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated probe: passes cleanly in isolation
                result.returncode = 0
                result.stdout = ""
            else:
                # combined run and final survivor re-run both fail identically
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]


class TestPytestDiffParallelAndTimeout:
    """run_pytest_diff wires -n (parallel) and --timeout on both pytest invocations
    (pre-validation-performance / rec-2387)."""

    def test_primary_invocation_carries_parallel_and_timeout_flags(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1
        cmd = real_run_cmds[0]
        assert "-n" in cmd
        assert cmd[cmd.index("-n") + 1] == "auto"
        assert "--timeout" in cmd
        assert failed == []

    def test_reactive_rerun_invocation_carries_parallel_and_timeout_flags(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif len([c for c in captured_cmds if "--collect-only" not in c]) == 1:
                # the initial (non--collect-only) combined run: fail with a
                # deliberately-excluded, genuinely-absent heavy-dep signature so the
                # reactive re-run path fires
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) >= 2, f"expected at least primary + reactive rerun, got: {captured_cmds}"
        rerun_cmd = real_run_cmds[-1]
        assert "-n" in rerun_cmd
        assert rerun_cmd[rerun_cmd.index("-n") + 1] == "auto"
        assert "--timeout" in rerun_cmd
        assert failed == []


@pytest.fixture
def _neutralized_pre_registry():
    """Patch every check-kind step of pre_sequence() to a no-op on the `validate` namespace.

    Applied via @pytest.mark.usefixtures to the classes whose tests call _validate.main()
    in --pre mode, so those tests exercise only the scaffold machinery plus whichever
    check(s) they explicitly patch themselves -- not the real check registry.
    _dispatch_check resolves each check via globals()[name] on the `validate` module
    (Decision 104), so patching "validate.<name>" intercepts it. A test's own explicit
    `with patch("validate.<name>")` still wins for the duration of its body: it is
    entered inside this fixture's ExitStack, so it becomes the innermost -- and active --
    patch on that name.
    """
    from scripts.checks import registry as _registry  # noqa: PLC0415

    with ExitStack() as stack:
        for step in _registry.pre_sequence():
            if step.kind == "check":
                stack.enter_context(patch(f"validate.{step.name}"))
        yield


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeDiffAware:
    """Tests that --pre passes changed files to ruff/mypy/pytest."""

    def test_passes_changed_py_files_to_ruff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        changed = ["scripts/validate.py", "tests/test_validate.py"]

        with (
            patch("scripts.checks._common.get_changed_files", return_value=changed),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_check = [c for c in captured_cmds if "ruff" in c and "check" in c and "format" not in c]
        assert ruff_check, "No ruff check command issued"
        assert "scripts/validate.py" in ruff_check[0]

    def test_skips_lint_when_no_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_cmds = [c for c in captured_cmds if "ruff" in c]
        assert not ruff_cmds, f"Unexpected ruff invocation: {ruff_cmds}"

    def test_skips_pytest_when_no_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert not pytest_cmds

    def test_invokes_pytest_with_explicit_files_when_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest not invoked"
        assert "tests/test_validate.py" in pytest_cmds[0], "explicit test file path not in pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear in pytest argv"
        assert "not integration" in pytest_cmds[0]

    def test_treats_pytest_exit_5_as_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = "agent/test-branch\n"
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModePytestSelection:
    """Regression tests locking the explicit-file pytest selection contract.

    Acceptance criteria from PLAN-ci-pre-gate-pytest-picked-noop:
    (a) changed test file -> pytest invoked with that explicit path, no --picked
    (b) exit 5 / 0-collected with changed test files -> failure (gate reddens)
    (c) no test files changed -> pytest not invoked at all
    """

    def test_explicit_path_in_argv_no_picked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest was not invoked despite changed test file"
        assert "tests/test_x.py" in pytest_cmds[0], "explicit file path missing from pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear (explicit-file transport)"

    def test_exit_5_with_changed_tests_reddens_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0, "exit 5 / 0-collected with changed test files must redden the gate"

    def test_no_pytest_when_no_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "scripts/sync_ops.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert not pytest_cmds, f"pytest must not run when no test files changed, got: {pytest_cmds}"


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestBudgetAssertion:
    """Tests for the 5-minute fast-tier wall-clock budget assertion."""

    def test_exits_1_on_budget_breach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 1

    def test_budget_breach_output_contains_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Fast tier exceeded budget" in captured.out

    def test_exits_0_within_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0

    def test_budget_constant_is_300(self) -> None:
        assert _FAST_TIER_BUDGET_SECONDS == 300

    def test_breach_rec_receives_a_real_dominant_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The dominant phase threaded to _file_budget_breach_rec must correctly identify WHICH
        step actually dominated the elapsed wall-clock -- not merely be non-None. Makes
        pytest_diff artificially slow (a real, attributable jump in the mocked clock) relative to
        every other near-zero step, so the assertion is on correctness of attribution, not just
        truthiness."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0  # dwarfs every other (near-zero) step's duration

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        dominant_phase_arg = mock_breach.call_args[0][2]
        assert dominant_phase_arg == "pytest_diff"

    def test_breach_console_error_names_dominant_phase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Same correctness bar as above, applied to the printed console diagnostic."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Dominant phase: pytest_diff" in captured.out


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestIgnoreBudgetFlag:
    """Tests for the --ignore-budget escape hatch."""

    def test_bypass_calls_bypass_rec_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_bypass.assert_called_once()

    def test_bypass_reason_captured_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget", "--ignore-budget-reason", "disk slow"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg == "disk slow"

    def test_bypass_reason_null_when_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg is None

    def test_bypass_skips_budget_assertion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Breach rec is NOT filed when --ignore-budget is set, even if elapsed > 300."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            patch("validate._file_budget_bypass_rec"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestIgnoreBudgetCIGuard:
    """Tests for the CI guard that forbids --ignore-budget in CI environments."""

    def test_refuses_ignore_budget_in_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")

        with pytest.raises(SystemExit) as exc_info:
            _validate.main()

        assert exc_info.value.code == 1

    def test_ci_guard_message_contains_expected_phrase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")

        with pytest.raises(SystemExit):
            _validate.main()

        captured = capsys.readouterr()
        assert "cannot be used in CI" in captured.out

    def test_allows_ignore_budget_when_ci_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0


class TestBudgetBreachRecFiling:
    """Tests for _file_budget_breach_rec and _file_budget_bypass_rec helpers.

    These exercise the LOCAL (non-CI) path -- CI-guard behaviour is covered separately by
    TestBudgetRecFilingCiGuard below. Every test here runs with CI unset regardless of the
    ambient environment (this file itself runs under CI="true" in the pr-validate/main-validate
    CI jobs), so the local-path assertions stay deterministic.
    """

    @pytest.fixture(autouse=True)
    def _no_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)

    def test_breach_rec_calls_file_rec_with_budget_breach_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_breach"

    def test_breach_rec_context_contains_elapsed_and_manifest(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "scripts/validate.py" in fields["context"]
        assert "6.7 min" in fields["context"] or "6." in fields["context"]

    def test_breach_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_breach_rec(400.0, [], None)

    def test_bypass_rec_calls_file_rec_with_budget_bypass_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()
        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["source"] == "budget_bypass"
        assert "disk issue" in fields["context"]

    def test_bypass_rec_reason_null_when_omitted(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, [], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert "none provided" in fields["context"].lower()

    def test_bypass_portal_exception_is_suppressed(self) -> None:
        mock_portal = MagicMock()
        mock_portal.file_rec.side_effect = RuntimeError("DynamoDB unreachable")
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_bypass_rec(60.0, [], None)

    def test_breach_priority_is_accepted_value(self) -> None:
        """_file_budget_breach_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_bypass_priority_is_accepted_value(self) -> None:
        """_file_budget_bypass_rec must pass a title-case priority (rec-2156)."""
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        fields = mock_portal.file_rec.call_args[0][0]
        assert fields["priority"] in {"Critical", "High", "Medium", "Low"}

    def test_breach_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_breach_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], None)

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise

    def test_bypass_priority_survives_real_accepted_values_validator(self) -> None:
        """Anti-vacuous: the priority _file_budget_bypass_rec passes must survive the REAL
        ops.yaml accepted_values validator, not just a hardcoded set in this test."""
        from scripts.ops_data_portal import _load_write_time_validators  # noqa: PLC0415

        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        priority = mock_portal.file_rec.call_args[0][0]["priority"]
        priority_validators = [fn for col, fn in _load_write_time_validators("ops_recommendations") if col == "priority"]
        assert priority_validators, "no priority validators loaded from ops.yaml"
        for validator in priority_validators:
            validator(priority, "priority")  # must not raise


class TestBudgetRecFilingCiGuard:
    """CI-guard on the budget rec-filing helpers (Decision 84 I-4 / ULID anomaly root cause).

    The pr-validate CI job installs requirements-fast.txt (no python-ulid) and configures no AWS
    credentials, so a real portal file_rec() write there raises a swallowed ModuleNotFoundError
    from ducklake_runtime's mint_write_identity. With CI=="true" neither helper may even attempt
    the portal import -- it must print a loud diagnostic instead (never a silent skip, never a
    buffered outbox entry).
    """

    def test_breach_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_breach_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err
        assert "400.0" not in captured.err  # sanity: elapsed is rendered as minutes, not raw seconds
        assert "6.7" in captured.err or "6." in captured.err

    def test_breach_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_portal.file_rec.assert_called_once()

    def test_bypass_rec_skips_file_rec_under_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CI", "true")
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_bypass_rec_prints_diagnostic_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")

        _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        captured = capsys.readouterr()
        assert "disk issue" in captured.err

    def test_bypass_rec_calls_file_rec_when_ci_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CI", raising=False)
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("scripts.checks._common.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_bypass_rec(60.0, ["scripts/validate.py"], "disk issue")

        mock_portal.file_rec.assert_called_once()


class TestBudgetBreachCiTelemetry:
    """CI-native budget-breach telemetry (pre-validation-performance / rec-2387): with
    CI="true" and GITHUB_STEP_SUMMARY set, _file_budget_breach_rec writes dominant_phase +
    the diff manifest to that file, files no rec, and stages no outbox entry."""

    def test_writes_dominant_phase_and_manifest_to_step_summary(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], "pytest_diff")

        content = summary_file.read_text(encoding="utf-8")
        assert "pytest_diff" in content
        assert "scripts/validate.py" in content
        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_no_ops_outbox_staged(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        outbox_dir = tmp_path / "logs" / ".ops-outbox"

        with patch("scripts.checks._common.run") as mock_run:
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_run.assert_not_called()
        assert not outbox_dir.exists()

    def test_falls_back_to_stderr_when_step_summary_unset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err


class TestValidateCiRcaTrigger:
    """Tests for validate_ci_rca_trigger() -- the presubmit wrapper around _check_ci_rca_filter."""

    def test_passes_when_guard_succeeds(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == []
        mock_module._check_ci_rca_filter.assert_called_once()

    def test_appends_to_failed_when_guard_raises(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("main-branch gate missing")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]

    def test_no_error_propagation_on_assertion(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("something wrong")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == ["ci-rca trigger gate"]

    def test_no_error_propagation_on_runtime_error(self) -> None:
        """rec-2027: validate_ci_rca_trigger catches non-AssertionError and records failure."""
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = RuntimeError("unexpected boom")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]


class TestValidateCiWorkflowGuards:
    """Tests for validate_ci_workflow_guards() -- the presubmit wrapper around four ci guards."""

    def test_passes_when_all_guards_succeed(self) -> None:
        mock_module = MagicMock()
        for attr in ("_check_jobs_and_flags", "_check_fetch_depth", "_check_concurrency", "_check_canary"):
            setattr(mock_module, attr, MagicMock())

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert failed == []

    def test_appends_failure_when_guard_raises_assertion(self) -> None:
        mock_module = MagicMock()
        mock_module._check_jobs_and_flags = MagicMock()
        mock_module._check_fetch_depth = MagicMock()
        mock_module._check_concurrency = MagicMock(side_effect=AssertionError("ci-runner still present"))
        mock_module._check_canary = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "concurrency" in failed[0]

    def test_records_failure_on_runtime_error_no_propagation(self) -> None:
        """rec-2027: a non-AssertionError exception records a failure and does not propagate."""
        mock_module = MagicMock()
        mock_module._check_jobs_and_flags = MagicMock(side_effect=RuntimeError("disk full"))
        mock_module._check_fetch_depth = MagicMock()
        mock_module._check_concurrency = MagicMock()
        mock_module._check_canary = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "jobs-and-flags" in failed[0]

    def test_records_failure_on_import_error_no_propagation(self) -> None:
        """rec-2027: an ImportError at guard-import time records a gate failure, no propagation."""
        # Setting the module to None in sys.modules makes `import` raise ImportError.
        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": None}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "ci-workflow guards gate" in failed[0]


class TestValidateHermeticityFlags:
    """Tests for validate_hermeticity_flags() and _build_unit_test_cmd()."""

    def test_build_unit_test_cmd_contains_disable_socket(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--disable-socket" in cmd

    def test_build_unit_test_cmd_contains_randomly_seed(self) -> None:
        cmd = _build_unit_test_cmd()
        assert "--randomly-seed=last" in cmd

    def test_build_unit_test_cmd_contains_all_hermeticity_flags(self) -> None:
        cmd = _build_unit_test_cmd()
        for flag in _UNIT_TEST_HERMETICITY_FLAGS:
            assert flag in cmd, f"flag {flag!r} missing from _build_unit_test_cmd()"

    def test_validate_hermeticity_flags_passes_when_all_present(self) -> None:
        full_cmd = list(_build_unit_test_cmd())
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=full_cmd)
        assert failed == []

    def test_validate_hermeticity_flags_fails_when_disable_socket_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != "--disable-socket"]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 1
        assert "--disable-socket" in failed[0]

    def test_validate_hermeticity_flags_fails_when_randomly_seed_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c != "--randomly-seed=last"]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 1
        assert "--randomly-seed=last" in failed[0]

    def test_validate_hermeticity_flags_fails_when_both_absent(self) -> None:
        cmd = [c for c in _build_unit_test_cmd() if c not in _UNIT_TEST_HERMETICITY_FLAGS]
        failed: list[str] = []
        validate_hermeticity_flags(failed, _cmd=cmd)
        assert len(failed) == 2

    def test_validate_hermeticity_flags_uses_build_cmd_by_default(self) -> None:
        failed: list[str] = []
        validate_hermeticity_flags(failed)
        assert failed == [], "default command must contain all hermeticity flags"


class TestValidateLambdaManifests:
    """Tests for validate_lambda_manifests() -- schema validation wrapper."""

    def test_passes_when_cmd_validate_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert failed == []

    def test_fails_when_cmd_validate_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.side_effect = RuntimeError("unexpected boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed


class TestValidateLambdaManifestCoverage:
    """Tests for validate_lambda_manifest_coverage() -- coverage gate wrapper."""

    def test_passes_when_cmd_check_coverage_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert failed == []

    def test_fails_when_cmd_check_coverage_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed


class TestValidateLambdaBundleCompleteness:
    """Tests for validate_lambda_bundle_completeness() -- bundle check wrapper."""

    def test_passes_when_cmd_check_bundles_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert failed == []

    def test_fails_when_cmd_check_bundles_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.side_effect = RuntimeError("staging failed")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed


class TestValidateLambdaDeployGating:
    """Tests for validate_lambda_deploy_gating() -- advisory deploy scope check."""

    def test_no_changed_files_skips_silently(self) -> None:
        mock_lm = MagicMock()
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []
        mock_lm.compute_affected_artifacts.assert_not_called()

    def test_reports_affected_artifact_without_failing(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {"data-pipeline": ["src/data/handlers/fetch_handler.py"]}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/data/handlers/fetch_handler.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []
        mock_lm.compute_affected_artifacts.assert_called_once_with(["src/data/handlers/fetch_handler.py"])

    def test_no_affected_artifacts_is_advisory_pass(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["docs/README.md"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []

    def test_fails_on_import_error(self) -> None:
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": None}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/some/file.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert "Lambda deploy gating" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.side_effect = RuntimeError("load failed")
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/some/file.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert "Lambda deploy gating" in failed


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestSlocLimitsInPreMode:
    """Assert validate_sloc_limits runs in the --pre tier (rec-2106 RCA fix)."""

    def test_sloc_limits_called_in_pre_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_sloc_limits must be invoked during --pre alongside validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        sloc_called = []

        def capture_sloc(failed: list[str]) -> None:
            sloc_called.append(True)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert sloc_called, "validate_sloc_limits was NOT called in --pre mode"

    def test_sloc_limits_called_after_cc_limits_in_pre(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_sloc_limits is called in the same --pre block as validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        call_order: list[str] = []

        def capture_cc(failed: list[str]) -> None:
            call_order.append("cc")

        def capture_sloc(failed: list[str]) -> None:
            call_order.append("sloc")

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_cc_limits", side_effect=capture_cc),
            patch("validate.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        assert "cc" in call_order, "validate_cc_limits not called in --pre mode"
        assert "sloc" in call_order, "validate_sloc_limits not called in --pre mode"
        cc_idx = call_order.index("cc")
        sloc_idx = call_order.index("sloc")
        assert cc_idx < sloc_idx, "validate_sloc_limits must be called after validate_cc_limits"


class TestGetChangedFilesDeletedPaths:
    """Assert get_changed_files() drops deleted (non-existent) paths before returning."""

    def test_drops_deleted_file(self, tmp_path: Path) -> None:
        """A file listed by git diff but absent on disk is excluded from the result."""
        existing = tmp_path / "scripts" / "exists.py"
        existing.parent.mkdir()
        existing.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/exists.py\nscripts/deleted_gone.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert "scripts/exists.py" in files
        assert "scripts/deleted_gone.py" not in files

    def test_all_deleted_returns_empty(self, tmp_path: Path) -> None:
        """When all listed files are deleted, the result is an empty list."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "scripts/migrate_ops_iceberg_to_ducklake.py\ntests/test_migrate_ops_iceberg_to_ducklake.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert files == []

    def test_existing_files_all_returned(self, tmp_path: Path) -> None:
        """When all listed files exist on disk, none are filtered out."""
        for name in ("a.py", "b.py"):
            f = tmp_path / name
            f.write_text("x = 1\n", encoding="utf-8")

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "a.py\nb.py\n"
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            files = get_changed_files()

        assert sorted(files) == ["a.py", "b.py"]


class TestIntentDocFreeze:
    """Tests for validate_intent_doc_freeze() -- Decision 86 enforcement."""

    _MANIFEST_PENDING = {
        "documents": [
            {"id": "bazel-feasibility", "disposition_state": "pending"},
            {"id": "ducklake-consolidation", "disposition_state": "pending"},
        ]
    }

    def _write_manifest(self, docs_dir: Path, data: dict) -> None:
        import yaml  # noqa: PLC0415

        migration_dir = docs_dir / "intent-migration"
        migration_dir.mkdir(parents=True, exist_ok=True)
        (migration_dir / "MANIFEST.yaml").write_text(yaml.dump(data), encoding="utf-8")

    def test_grandfathered_intent_doc_passes(self, tmp_path: Path) -> None:
        """A docs/INTENT-*.md with a non-done manifest entry is allowed."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "INTENT-bazel-feasibility.md").write_text("# content\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert failed == []

    def test_new_intent_doc_not_in_manifest_is_rejected(self, tmp_path: Path) -> None:
        """A docs/INTENT-*.md with no manifest entry is rejected."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "INTENT-zzz-new.md").write_text("# rogue\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert any("INTENT-zzz-new.md" in f for f in failed)

    def test_done_manifest_entry_is_rejected(self, tmp_path: Path) -> None:
        """A doc whose manifest entry has disposition_state: done is rejected (it should have been deleted)."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        manifest = {
            "documents": [
                {"id": "bazel-feasibility", "disposition_state": "done"},
            ]
        }
        self._write_manifest(docs_dir, manifest)
        (docs_dir / "INTENT-bazel-feasibility.md").write_text("# content\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert any("bazel-feasibility" in f for f in failed)

    def test_contracts_dir_excluded(self, tmp_path: Path) -> None:
        """A docs/contracts/INTENT-*.md is NOT flagged (contracts dir is excluded)."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        contracts_dir = docs_dir / "contracts"
        contracts_dir.mkdir()
        (contracts_dir / "INTENT-zzz.md").write_text("# contract\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert not any("zzz" in f for f in failed)

    def test_intent_migration_dir_excluded(self, tmp_path: Path) -> None:
        """Files under docs/intent-migration/ are NOT flagged."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        self._write_manifest(docs_dir, self._MANIFEST_PENDING)
        (docs_dir / "intent-migration" / "INTENT-internal.md").write_text("# internal\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert not any("INTENT-internal" in f for f in failed)

    def test_manifest_absent_fails_open(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When the manifest is absent the check emits a warning and does NOT append to failed."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "INTENT-zzz.md").write_text("# rogue\n", encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_intent_doc_freeze(failed)

        assert failed == []
        captured = capsys.readouterr()
        assert "WARNING" in captured.out or "WARNING" in captured.err


class TestValidateCiRcaTaxonomy:
    """Tests for validate_ci_rca_taxonomy (wired into both --pre and run_python_checks)."""

    def test_complete_map_passes(self) -> None:
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        assert not failed, f"Expected no failures, got: {failed}"

    def test_missing_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import scripts.ci_rca_taxonomy as taxonomy_mod  # noqa: I001
        import yaml

        incomplete_taxonomy = {
            "schema_version": 1,
            "taxonomy_version": 1,
            "function_to_category": {},
            "log_pattern_to_category": [],
            "workflow_to_tier": {"CI": "CI"},
        }
        tax_path = tmp_path / "taxonomy.yaml"
        tax_path.write_text(yaml.dump(incomplete_taxonomy))

        taxonomy_mod._TAXONOMY_CACHE = None
        original_path = taxonomy_mod._TAXONOMY_PATH
        taxonomy_mod._TAXONOMY_PATH = tax_path
        try:
            from scripts.ci_rca_taxonomy import enumerate_workflow_names

            workflows_dir = ROOT / ".github" / "workflows"
            actual_names = enumerate_workflow_names(workflows_dir)
            missing = [n for n in actual_names if n != "CI"]
            if not missing:
                pytest.skip("All workflows happen to be in the minimal map")

            failed: list[str] = []
            validate_ci_rca_taxonomy(failed)
            assert any("absent from workflow_to_tier" in f for f in failed), (
                f"Expected taxonomy failure for missing workflows, got: {failed}"
            )
        finally:
            taxonomy_mod._TAXONOMY_PATH = original_path
            taxonomy_mod._TAXONOMY_CACHE = None

    def test_taxonomy_file_missing_fails(self, tmp_path: Path) -> None:
        import scripts.ci_rca_taxonomy as taxonomy_mod

        taxonomy_mod._TAXONOMY_CACHE = None
        original_path = taxonomy_mod._TAXONOMY_PATH
        taxonomy_mod._TAXONOMY_PATH = tmp_path / "nonexistent.yaml"
        try:
            failed: list[str] = []
            validate_ci_rca_taxonomy(failed)
            assert any("CI-RCA taxonomy" in f for f in failed), f"Expected taxonomy error, got: {failed}"
        finally:
            taxonomy_mod._TAXONOMY_PATH = original_path
            taxonomy_mod._TAXONOMY_CACHE = None


class TestVerifierHermeticity:
    """Tests for validate_verifier_hermeticity() (T3.6 AST gate)."""

    def test_real_tree_is_clean(self) -> None:
        """The live scripts/verifiers/ tree produces no hermeticity violations."""
        failed: list[str] = []
        validate_verifier_hermeticity(failed)
        assert failed == [], f"Expected no failures against real verifier tree, got: {failed}"

    def test_hermetic_declared_with_time_time_fails(self, tmp_path: Path) -> None:
        """A HERMETIC-defaulting class using time.time() is rejected."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "clock_verifier.py").write_text(
            "import time\n\nclass ClockVerifier:\n    async def verify(self):\n        return time.time()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("time.time" in f for f in failed), f"Expected time.time violation, got: {failed}"

    def test_hermetic_declared_with_boto3_import_fails(self, tmp_path: Path) -> None:
        """A HERMETIC-defaulting file importing boto3 is rejected."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "network_verifier.py").write_text(
            "import boto3\n\nclass NetworkVerifier:\n    async def verify(self):\n        pass\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("boto3" in f for f in failed), f"Expected boto3 violation, got: {failed}"

    def test_non_hermetic_declared_with_time_time_is_exempt(self, tmp_path: Path) -> None:
        """A NON_HERMETIC_BY_CONSTRUCTION verifier using time.time() is exempt."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "exempt_verifier.py").write_text(
            "import time\n\n"
            "class ExemptVerifier:\n"
            "    hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION\n"
            "    async def verify(self):\n"
            "        return time.time()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert failed == [], f"Expected no failures for NON_HERMETIC verifier, got: {failed}"

    def test_three_level_datetime_now_fails(self, tmp_path: Path) -> None:
        """import datetime; datetime.datetime.now() is caught (3-level dotted name)."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "three_level_verifier.py").write_text(
            "import datetime\n\n"
            "class ThreeLevelVerifier:\n"
            "    async def verify(self):\n"
            "        return datetime.datetime.now()\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert any("datetime.datetime.now" in f for f in failed), f"Expected datetime.datetime.now violation, got: {failed}"

    def test_syntax_error_file_is_skipped(self, tmp_path: Path) -> None:
        """A file with a SyntaxError is skipped without crashing the gate."""
        verifiers_dir = tmp_path / "scripts" / "verifiers"
        verifiers_dir.mkdir(parents=True)
        (verifiers_dir / "bad_syntax.py").write_text(
            "def broken(\n    # unclosed paren\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_hermeticity(failed)
        assert failed == [], f"SyntaxError file must be skipped, got: {failed}"


class TestBrokerEnvReadGuard:
    """Tests for validate_broker_env_reads -- RESOLVE-BY-KEY-ONLY invariant (T2.14 exit criterion 3)."""

    def test_clean_tree_passes(self) -> None:
        """The live src/ + scripts/ tree contains no direct broker env reads."""
        failed: list[str] = []
        validate_broker_env_reads(failed)
        assert failed == [], f"Expected no failures against real tree, got: {failed}"

    def test_planted_environ_bracket_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.environ["ALPACA_API_KEY"] in a src file is flagged."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bad_adapter.py").write_text(
            'import os\nkey = os.environ["ALPACA_API_KEY"]\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_planted_getenv_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.getenv("ALPACA_SECRET") in a scripts file is flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'import os\nsecret = os.getenv("ALPACA_SECRET_KEY")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_planted_environ_get_violation_is_flagged(self, tmp_path: Path) -> None:
        """os.environ.get("ALPACA_API_KEY") in a scripts file is flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'import os\nkey = os.environ.get("ALPACA_API_KEY", "")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert any("ALPACA" in f or "broker" in f.lower() for f in failed), (
            f"Expected broker env-read violation, got: {failed}"
        )

    def test_broker_secrets_py_is_self_excluded(self, tmp_path: Path) -> None:
        """scripts/broker_secrets.py is excluded even if it contains the pattern string."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "broker_secrets.py").write_text(
            '# patterns: os.environ["ALPACA_API_KEY"] os.getenv("ALPACA_SECRET")\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"broker_secrets.py must be self-excluded, got: {failed}"

    def test_validate_py_is_self_excluded(self, tmp_path: Path) -> None:
        """scripts/validate.py is excluded even though it contains the pattern strings."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "validate.py").write_text(
            "patterns = [r'os\\.environ\\[\\s*[\"\\']ALPACA_']\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"validate.py must be self-excluded, got: {failed}"

    def test_tests_dir_is_not_scanned(self, tmp_path: Path) -> None:
        """Files under tests/ are not scanned (test fixtures may plant violations intentionally)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_adapter.py").write_text(
            'key = os.environ["ALPACA_API_KEY"]  # planted fixture\n',
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_broker_env_reads(failed)
        assert failed == [], f"tests/ must not be scanned, got: {failed}"


class TestCandidateDecisionRatification:
    """Tests for validate_candidate_decision_ratification() (Decision 105): R1/R2/R3."""

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup(self, tmp_path: Path, cd_yaml: str, decisions_md: str = "", archive_md: str | None = None) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + cd_yaml, encoding="utf-8")
        (docs_dir / "DECISIONS.md").write_text(decisions_md, encoding="utf-8")
        if archive_md is not None:
            (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_md, encoding="utf-8")

    def test_ratified_cd_resolves_via_header_passes(self, tmp_path: Path) -> None:
        """dec-078 resolves via the '## Decision 78:' header (int-derived, not string-padded)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.31\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-078\n    filed_via: ops_decisions:dec-078\n",
            decisions_md="## Decision 78: Adopt DuckLake (Decided)\n\nbody with stale Warehouse ID: dec-1085 text\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_cd_unknown_dec_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.99\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-999\n    filed_via: ops_decisions:dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_ratified_as_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    ratified_as: dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_dec_pointer_filed_via_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    filed_via: ops_decisions:dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_pending_literal_passes(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.6\n    title: t\n    state: pending\n"
            "    filed_via: pending_log_decision_lambda\n    realization_evidence: Realized.\n",
            decisions_md="",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_as_filed_via_mismatch_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.16\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-079\n    filed_via: ops_decisions:dec-080\n",
            decisions_md="## Decision 79: X (Decided)\n## Decision 80: Y (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_superseded_cd_exempt_from_r1(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.14\n    title: t\n    state: superseded\n    ratified_as: dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_dec_resolves_via_archive_only(self, tmp_path: Path) -> None:
        """A dec-NNN whose header lives only in DECISIONS_ARCHIVE.md still resolves (union read)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.50\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-34\n    filed_via: ops_decisions:dec-34\n",
            decisions_md="## Decision 1: Something (Decided)\n",
            archive_md="## Decision 34: Unified Cross-Workflow Session Telemetry\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []


class TestPlatformRoadmapCriteriaIntegrity:
    """Tests for validate_platform_roadmap() criteria-status integrity assertions (T-1.23).

    Check (i)  -- met criterion met_by resolves to a real plan file or 40-hex sha.
    Check (iii) -- every PLAN-*.yaml closes_criteria ref resolves to a real item:criterion.
    """

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup_dirs(self, tmp_path: Path, roadmap_extra: str = "") -> None:
        """Write a minimal ROADMAP-PLATFORM.yaml and create docs/plans/ under tmp_path."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + roadmap_extra, encoding="utf-8")

    @staticmethod
    def _no_diff_ctx():
        """Patch subprocess.run so the git-diff check (ii) sees an empty diff."""
        return patch("validate.subprocess.run", return_value=_mock_completed(returncode=0, stdout=""))

    def test_met_criterion_dangling_met_by_fails(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by names no real plan and is not a 40-hex SHA -> failure."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            "        met_by: nonexistent-plan\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_met_criterion_valid_plan_file_passes(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by points to an existing PLAN-*.yaml -> pass."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            "        met_by: real-plan\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-real-plan.yaml").write_text("slug: real-plan\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed

    def test_met_criterion_valid_sha_passes(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by is a 40-hex commit SHA -> pass."""
        sha = "a" * 40
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            f"        met_by: '{sha}'\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed

    def test_closes_criteria_unknown_item_fails(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria refs a tier_item id absent from the roadmap -> failure."""
        self._setup_dirs(tmp_path)  # roadmap has no tier_items
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T999.1:c1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_closes_criteria_unknown_criterion_fails(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria refs a criterion id absent from a known item -> failure."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: criterion 1\n"
            "        status: open\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T0.1:c999\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_closes_criteria_valid_ref_passes(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria ref resolves to a real item:criterion -> pass."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: criterion 1\n"
            "        status: open\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T0.1:c1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed

    def test_diff_touched_item_with_bare_string_criterion_fails(self, tmp_path: Path) -> None:
        """Check (ii): a tier_item appearing in the git diff that retains a bare-string criterion -> failure.

        The Pydantic normalizer converts bare strings at load time, but check (ii) reads the raw YAML
        to detect whether the on-disk representation still has unstructured criteria on touched items.
        """
        self._setup_dirs(
            tmp_path,
            # Bare-string criterion: Pydantic normalizes it but the raw YAML still has a string.
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - criterion that was never converted to ExitCriterion format\n",
        )
        # Simulate a git diff that names T0.1 as a modified tier_item.
        mock_diff = "+  - id: T0.1\n+    status: in_progress\n"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.subprocess.run", return_value=_mock_completed(returncode=0, stdout=mock_diff)),
        ):
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_diff_touched_item_with_structured_criteria_passes(self, tmp_path: Path) -> None:
        """Check (ii): a tier_item in the diff with fully-structured criteria -> pass (no failure)."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: structured criterion\n"
            "        status: open\n",
        )
        mock_diff = "+  - id: T0.1\n"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("validate.subprocess.run", return_value=_mock_completed(returncode=0, stdout=mock_diff)),
        ):
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed


class TestDucklakeVersionLockstepGate:
    """Tests for validate_ducklake_version_lockstep() -- the OQ.12 SSOT drift gate."""

    def test_passes_on_coherent_tree(self, tmp_path: Path) -> None:
        """Gate passes when requirements.txt is in sync and no literal in derive surfaces."""
        import scripts.sync_ducklake_version as _sdv_inner  # noqa: PLC0415

        # coherent requirements.txt
        req = tmp_path / "requirements.txt"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        runtime = src / "ducklake_runtime.py"
        no_literal = (
            "# no literal\n"
            "from src.common.ducklake_version import pinned_duckdb_version as _p\n"
            "_PINNED_DUCKDB_VERSION = None\n"
        )
        runtime.write_text(no_literal, encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        build = scripts / "build_lambda.py"
        build.write_text(
            "from src.common.ducklake_version import pinned_duckdb_version as _p\nPINNED_DUCKDB_VERSION = _p()\n",
            encoding="utf-8",
        )

        import scripts.sync_ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert failed == [], failed

    def test_fails_when_requirements_drifts(self, tmp_path: Path) -> None:
        """Gate fails when requirements.txt has old floor."""
        req = tmp_path / "requirements.txt"
        req.write_text("duckdb>=1.5.3  # old\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        (src / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync_ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("duckdb floor" in f or "requirements" in f for f in failed), failed

    def test_fails_when_literal_in_derive_surface(self, tmp_path: Path) -> None:
        """Gate fails when a raw PINNED_DUCKDB_VERSION = '...' literal is in a derive surface."""
        import scripts.sync_ducklake_version as _sdv_inner  # noqa: PLC0415

        req = tmp_path / "requirements.txt"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        # reintroduce a hardcoded literal
        (src / "ducklake_runtime.py").write_text('PINNED_DUCKDB_VERSION = "1.5.3"\n', encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync_ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("hardcoded" in f or "literal" in f or "ducklake_runtime" in f for f in failed), failed


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeChecks:
    """Assert validate_subprocess_encoding runs in the --pre tier (rec-2382 RCA fix)."""

    def test_pre_mode_calls_subprocess_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_subprocess_encoding must be invoked during --pre (tier-membership regression guard)."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        encoding_called = []

        def capture_encoding(failed: list[str]) -> None:
            encoding_called.append(True)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.validate_subprocess_encoding", side_effect=capture_encoding),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert encoding_called, "validate_subprocess_encoding was NOT called in --pre mode"


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestPreModeRegistryIsolation:
    """Isolation-guard test (defect 2 lock-in): proves the real check registry is not
    executed inside a neutralized --pre main() call, so a future edit that silently
    reintroduces full-registry execution (and its wall-clock cost) is caught here instead
    of resurfacing as a slow/flaky fast-tier gate."""

    def test_real_registry_check_not_invoked_under_neutralization(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """validate_import_contracts prints a distinctive banner when it actually runs
        (see scripts/checks/deps/validate_import_contracts.py); the neutralization fixture
        replaces it with a plain no-op MagicMock, so that banner must never appear here.
        """
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Import contracts (Decision 80" not in captured.out, (
            "validate_import_contracts printed its real banner -- the real check ran "
            "instead of being neutralized by the _neutralized_pre_registry fixture"
        )


# ---------------------------------------------------------------------------
# same_pr_guard tests (T3.1)
# ---------------------------------------------------------------------------


class TestSamePrGuard:
    """Tests for validate_verifier_same_pr_guard() in validate.py --pre tier."""

    def test_no_violations_when_no_verifier_in_diff(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_no_violation_when_verifier_newly_added(self, tmp_path: Path) -> None:
        """Exception (b): a brand-new verifier file is exempt from the guard.

        Its covers ('**') intersects the diff, so this also exercises the VF-06 c3
        differential dispatch path -- stubbed here to an admitted outcome since the
        differential mechanism itself (real worktree) is covered by
        TestSamePrGuardDifferential below.
        """
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "new_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['**']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/new_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/validate.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=rel + "\n"),
            ),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="stubbed for AST-level guard test"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation for newly-added verifier: {failed}"

    def test_no_violation_exception_c_no_covered_in_diff(self, tmp_path: Path) -> None:
        """Exception (c): verifier modified but no covered file in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/some_module.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/other.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation when no covered file in diff: {failed}"

    def test_violation_detected_when_verifier_and_covered_both_modified(self, tmp_path: Path) -> None:
        """Same-PR guard fires when an existing verifier AND a file it covers are both in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        target = "scripts/target.py"
        (tmp_path / "scripts" / "target.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "scripts" / "target.py").write_text("# target\n", encoding="utf-8")
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, target]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert "Verifier same-PR guard" in failed


class TestSamePrGuardHelpers:
    """Edge-case coverage for _extract_verifier_covers and the guard's structural branches."""

    def test_extract_verifier_covers_annotated_assignment(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    covers: list[str] = ['a.py', 'b.py']\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) == ["a.py", "b.py"]

    def test_extract_verifier_covers_returns_none_when_absent(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    pass\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) is None

    def test_verifiers_dir_missing_returns_early(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_syntax_error_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        rel = "scripts/verifiers/broken.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_no_classes_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "no_classes.py").write_text("x = 1\n", encoding="utf-8")
        rel = "scripts/verifiers/no_classes.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed


# ---------------------------------------------------------------------------
# verification_registry tests (T3.1)
# ---------------------------------------------------------------------------


class TestVerificationRegistry:
    """Tests for validate_verification_registry() in validate.py --pre tier."""

    def test_pass_with_empty_entries(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: []\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert not failed

    def test_fail_missing_entries_key(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("other_key: 1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("missing top-level 'entries' key" in f for f in failed), failed

    def test_fail_entries_not_a_list(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: not-a-list\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("'entries' must be a list" in f for f in failed), failed

    def test_schema_error_non_dict_entry(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries:\n  - just-a-string\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_missing_file(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("not found" in f for f in failed)

    def test_fail_invalid_yaml(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: [\n  - invalid: yaml: :", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("YAML" in f for f in failed)

    def test_fail_missing_required_field(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            "entries:\n  - check_id: x\n    primitive_slot: grep_count\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_unknown_slot(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            (
                "entries:\n"
                "  - check_id: x\n"
                "    primitive_slot: unknown_slot\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-06-29'\n"
            ),
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_duplicate_check_id(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        entry = (
            "  - check_id: dup\n"
            "    primitive_slot: grep_count\n"
            "    guard_target: scripts/foo.py\n"
            "    plan_slug: my-plan\n"
            "    graduated_at: '2026-06-29'\n"
        )
        (reg / "registry.yaml").write_text(f"entries:\n{entry}{entry}", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_pass_valid_entry(self, tmp_path: Path) -> None:
        """Schema-valid entry with no check_spec: treated as pre-existing (not added), so the
        VF-06 c2 differential does not fire (no check_spec means it can't be materialized)."""
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            (
                "entries:\n"
                "  - check_id: my-check\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-06-29'\n"
            ),
            encoding="utf-8",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[],
            ),
        ):
            validate_verification_registry(failed)
        assert not failed


# ---------------------------------------------------------------------------
# VF-06 c2/c3 differential-execution branch tests (T3.18, audit-remediation-wave-4)
# ---------------------------------------------------------------------------


class TestVerificationRegistryDifferential:
    """VP step 6: validate_verification_registry's added-entry differential branch (VF-06 c2).

    The differential mechanism itself (real worktree revert) is covered by
    tests/test_verification_graduation.py; here we drive the validate.py wiring with a stubbed
    scripts.verification_graduation to verify the diff-gating, message shape, and fail-loud
    error surfacing.
    """

    def _write_registry(self, tmp_path: Path, entries_yaml: str) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(entries_yaml, encoding="utf-8")

    def test_added_entry_admitted(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: new-check\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-07-04'\n"
                "    check_spec: {path: scripts/foo.py, pattern: 'x', operator: eq, count: 1}\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "new-check"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=True, reason="admitted -- fails on origin/main, passes on HEAD"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert not failed

    def test_added_entry_not_admitted_tautological(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: taut\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: x\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "taut"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=False, reason="not admitted -- revert did not produce FAIL (tautological)"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_no_added_entry_is_noop(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: x\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: y\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.verification.validate_verification_registry._added_entries", return_value=[]),
            patch("scripts.verification_graduation.run_differential") as mock_diff,
        ):
            validate_verification_registry(failed)
        assert not failed
        mock_diff.assert_not_called()

    def test_graduation_error_surfaces_as_failure(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: bad\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: y\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "bad"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verification_registry(failed)
        assert any("error --" in f for f in failed), failed


class TestEntriesAtRef:
    """Direct unit tests for _entries_at_ref (VF-06 c2 baseline-fetch helper)."""

    def test_returns_empty_on_nonzero_returncode(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=1, stdout="")):
            assert _entries_at_ref("origin/main") == []

    def test_returns_empty_on_yaml_parse_error(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch(
            "scripts.checks._common.run",
            return_value=MagicMock(returncode=0, stdout="entries: [\n  - broken: yaml: :"),
        ):
            assert _entries_at_ref("origin/main") == []

    def test_returns_empty_on_non_dict_content(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="just-a-string\n")):
            assert _entries_at_ref("origin/main") == []

    def test_returns_entries_list_on_valid_content(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        stdout = "entries:\n  - check_id: x\n    primitive_slot: grep_count\n"
        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=stdout)):
            entries = _entries_at_ref("origin/main")
        assert entries == [{"check_id": "x", "primitive_slot": "grep_count"}]


class TestSamePrGuardDifferential:
    """VP step 7: validate_verifier_same_pr_guard's exception-(b) differential branch (VF-06 c3).

    The differential mechanism itself is covered by tests/test_verification_graduation.py; here
    we drive the validate.py wiring with a stubbed scripts.verification_graduation.
    """

    def _setup_new_verifier(self, tmp_path: Path) -> str:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "new_verifier.py").write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n", encoding="utf-8"
        )
        target = tmp_path / "scripts" / "target.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# target\n", encoding="utf-8")
        return "scripts/verifiers/new_verifier.py"

    def test_exception_b_differential_admits(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="admitted"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_tautological_fails(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False,
                    skipped=False,
                    reason="not admitted -- verifier passes even with its covered change reverted",
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_exception_b_non_hermetic_advisory_skip_does_not_block(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False, skipped=True, reason="advisory SKIP -- NON_HERMETIC_BY_CONSTRUCTION new verifier"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_error_surfaces(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("error --" in f for f in failed), failed


# ---------------------------------------------------------------------------
# differential_gate_step tests (T3.1)
# ---------------------------------------------------------------------------


class TestDifferentialGateStep:
    """Tests for validate_differential_gate_baseline() in validate.py full tier."""

    def test_passes_when_kernel_file_contains_sentinel(self) -> None:
        """Gate passes when scripts/verification_checks.py exists and has SLOT_COUNT: int = 6."""
        failed: list[str] = []
        validate_differential_gate_baseline(failed)
        assert not failed, f"Differential gate baseline failed: {failed}"

    def test_fails_when_sentinel_absent(self, tmp_path: Path) -> None:
        """Gate fails if the kernel file lacks the expected sentinel line."""
        kernel_dir = tmp_path / "scripts"
        kernel_dir.mkdir()
        (kernel_dir / "verification_checks.py").write_text("# no sentinel here\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_differential_gate_baseline(failed)
        assert any("Differential gate baseline" in f for f in failed)


# ---------------------------------------------------------------------------
# platform_roadmap ExitCriterion tests (T3.1 structured criteria)
# ---------------------------------------------------------------------------


class TestPlatformRoadmapT31Criteria:
    """Tests that T3.1's exit_criteria are now structured ExitCriterion objects."""

    def test_t31_exit_criteria_are_structured(self) -> None:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
        assert t31 is not None, "T3.1 not found in ROADMAP-PLATFORM.yaml"
        criteria = t31["exit_criteria"]
        assert isinstance(criteria, list)
        assert len(criteria) == 7
        for crit in criteria:
            assert isinstance(crit, dict), f"Criterion is not a dict: {crit!r}"
            assert "id" in crit, f"Criterion missing 'id': {crit}"
            assert "text" in crit, f"Criterion missing 'text': {crit}"
            assert "status" in crit, f"Criterion missing 'status': {crit}"

    def test_t31_criterion_ids_are_c1_through_c7(self) -> None:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
        ids = [c["id"] for c in t31["exit_criteria"]]
        assert ids == ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]


# ---------------------------------------------------------------------------
# VP selector hooks for test_validate.py
# Standalone functions named so that `pytest -k <selector>` collects them.
# ---------------------------------------------------------------------------


def test_verification_registry_accepts_empty_file(tmp_path: Path) -> None:
    """VP step 5: registry guard accepts an empty well-formed entries list."""
    reg = tmp_path / "config" / "agent" / "verification_registry"
    reg.mkdir(parents=True)
    (reg / "registry.yaml").write_text("entries: []\n", encoding="utf-8")
    failed: list = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_verification_registry(failed)
    assert not failed


def test_same_pr_guard_passes_on_no_verifier_in_diff() -> None:
    """VP step 6: same-PR guard passes when no verifier file is in the diff."""
    failed: list = []
    with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
        validate_verifier_same_pr_guard(failed)
    assert not failed


def test_differential_gate_step_passes_on_live_tree() -> None:
    """VP step 9: differential gate baseline step passes on the live code tree."""
    failed: list = []
    validate_differential_gate_baseline(failed)
    assert not failed


def test_platform_roadmap_t31_criteria_are_structured() -> None:
    """VP step 10: T3.1 exit_criteria are structured ExitCriterion objects, not bare strings."""
    import yaml  # noqa: PLC0415

    data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
    t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
    assert t31 is not None
    for crit in t31["exit_criteria"]:
        assert isinstance(crit, dict)
        assert {"id", "text", "status"} <= crit.keys()


class TestValidateRecRelevanceContract:
    """Tests for validate_rec_relevance_contract() -- T3.8 enum-drift guard."""

    def test_passes_on_live_contract(self) -> None:
        """The live recommendation-relevance.yaml passes the guard (no drift)."""
        failed: list[str] = []
        validate_rec_relevance_contract(failed)
        assert not failed, f"unexpected failures: {failed}"

    def test_fails_when_contract_missing(self, tmp_path: Path) -> None:
        """Missing contract file -> failure appended."""
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            (tmp_path / "docs" / "contracts").mkdir(parents=True)
            validate_rec_relevance_contract(failed)
        assert any("not found" in f for f in failed)

    def test_fails_when_contract_unparseable(self, tmp_path: Path) -> None:
        """Unparseable YAML -> failure appended."""
        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(": invalid: [yaml", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("parse error" in f for f in failed)

    def test_fails_when_contract_declares_columns(self, tmp_path: Path) -> None:
        """Contract with 'columns' key -> Decision 84 violation."""
        import yaml  # noqa: PLC0415

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": ["relevant", "unknown"], "columns": {"foo": "bar"}}
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("Decision 84" in f or "columns" in f for f in failed)

    def test_fails_when_verdict_enum_drifts(self, tmp_path: Path) -> None:
        """Contract verdicts != RELEVANCE_VERDICTS -> drift failure."""
        import yaml  # noqa: PLC0415

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": ["relevant", "satisfied", "unknown"]}  # missing 5 verdicts
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert any("drift" in f for f in failed)

    def test_fails_when_verdicts_empty(self, tmp_path: Path) -> None:
        """Contract with empty verdicts -> failure."""
        import yaml  # noqa: PLC0415

        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        contract = {"verdicts": []}
        (tmp_path / "docs" / "contracts" / "recommendation-relevance.yaml").write_text(yaml.dump(contract), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_rec_relevance_contract(failed)
        assert failed


# ---------------------------------------------------------------------------
# validate_import_contracts (Decision 80 / T3.11 wrapper)
# ---------------------------------------------------------------------------


class TestValidateImportContracts:
    """Tests for validate_import_contracts() -- thin wrapper around import_governance.run_import_contracts."""

    def test_passes_on_clean_tree(self) -> None:
        """Contracts pass on the unmodified repository tree (integration smoke)."""
        failed: list[str] = []
        validate_import_contracts(failed)
        assert not failed, f"Unexpected import-contract failures: {failed}"

    def test_appends_to_failed_on_contract_breach(self) -> None:
        """When run_import_contracts returns (False, ...), failure is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "run_import_contracts", return_value=(False, "BROKEN: bad cycle\n")):
            validate_import_contracts(failed)
        assert any("Import contracts" in f for f in failed)

    def test_no_failure_on_pass(self) -> None:
        """When run_import_contracts returns (True, ...), nothing is appended to failed."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "run_import_contracts", return_value=(True, "All contracts kept\n")):
            validate_import_contracts(failed)
        assert not failed

    def test_wired_in_both_tiers(self) -> None:
        """validate_import_contracts is a registered check in both the --pre and full-tier sequences.

        Decision 104: dispatch is registry-driven (scripts/checks/registry.py), not a literal
        `validate_import_contracts(failed)` call site in scripts/validate.py -- so tier membership
        is verified via the registry's declared sequences, not AST call-site counting.
        """
        from scripts.checks import registry  # noqa: PLC0415

        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_import_contracts" in pre_names, "validate_import_contracts missing from pre_sequence()"
        assert "validate_import_contracts" in full_names, "validate_import_contracts missing from full_sequence()"


# ---------------------------------------------------------------------------
# validate_lockfile_sync (Decision 80 / T3.11 wrapper)
# ---------------------------------------------------------------------------


class TestValidateLockfileSync:
    """Tests for validate_lockfile_sync() -- thin wrapper around import_governance.check_lockfile_sync."""

    def test_passes_on_committed_lockfile(self) -> None:
        """Lockfile is in sync on the unmodified repository tree (integration smoke)."""
        failed: list[str] = []
        validate_lockfile_sync(failed)
        assert not failed, f"Unexpected lockfile-sync failures: {failed}"

    def test_appends_to_failed_on_drift(self) -> None:
        """When check_lockfile_sync returns (False, ...), failure is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "check_lockfile_sync", return_value=(False, "mypackage missing from lock")):
            validate_lockfile_sync(failed)
        assert any("Lockfile" in f for f in failed)

    def test_no_failure_on_in_sync(self) -> None:
        """When check_lockfile_sync returns (True, ...), nothing is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "check_lockfile_sync", return_value=(True, "pins all packages")):
            validate_lockfile_sync(failed)
        assert not failed

    def test_wired_in_both_tiers(self) -> None:
        """validate_lockfile_sync is a registered check in both the --pre and full-tier sequences.

        Decision 104: dispatch is registry-driven (scripts/checks/registry.py), not a literal
        `validate_lockfile_sync(failed)` call site in scripts/validate.py -- so tier membership
        is verified via the registry's declared sequences, not AST call-site counting.
        """
        from scripts.checks import registry  # noqa: PLC0415

        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_lockfile_sync" in pre_names, "validate_lockfile_sync missing from pre_sequence()"
        assert "validate_lockfile_sync" in full_names, "validate_lockfile_sync missing from full_sequence()"


class TestValidatePortalDrift:
    """Tests for validate_portal_drift() -- ULF-11 portal-artefact drift gate."""

    _BASELINE_PROMPTS = (
        "projection: >-\n"
        "  Test projection header for the curated evaluator index.\n"
        "questions:\n"
        "  - id: Q1\n"
        "    theme: test\n"
        "    question: test question\n"
        "    answer_loci:\n"
        "      - README.md\n"
    )
    _BASELINE_README = "# agent-platform\n\nThis file is a projection of CLAUDE.md.\n"
    _BASELINE_SECURITY = "# Security Policy\n\nThis file is a projection of the security posture.\n"

    def _write_baseline(self, tmp_path: Path) -> None:
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(self._BASELINE_PROMPTS, encoding="utf-8")
        (tmp_path / "README.md").write_text(self._BASELINE_README, encoding="utf-8")
        (tmp_path / "SECURITY.md").write_text(self._BASELINE_SECURITY, encoding="utf-8")

    def test_live_repo_is_clean(self) -> None:
        """The live repo passes today: no answer-locus, header, or token drift."""
        failed: list[str] = []
        validate_portal_drift(failed)
        assert failed == []

    def test_baseline_fixture_is_clean(self, tmp_path: Path) -> None:
        """Sanity: the synthetic baseline used by the failure-mode tests passes on its own."""
        self._write_baseline(tmp_path)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert failed == []

    def test_fails_when_answer_locus_does_not_resolve(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        prompts_path = tmp_path / "EVALUATION-PROMPTS.yaml"
        prompts_path.write_text(self._BASELINE_PROMPTS.replace("README.md", "docs/does-not-exist.md"), encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("answer-locus does not resolve" in f for f in failed)

    def test_fails_when_portal_file_missing_projection_header(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "README.md").write_text("# agent-platform\n\nNo header claim here.\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("missing a 'projection of' line" in f for f in failed)

    def test_fails_when_evaluation_prompts_missing_top_level_projection_key(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            "questions:\n  - id: Q1\n    answer_loci:\n      - README.md\n", encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("missing its top-level `projection:` header" in f for f in failed)

    def test_fails_when_ops_table_token_leaks_into_evaluation_prompts(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            self._BASELINE_PROMPTS + "    # references ops_recommendations internally\n", encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("ops_recommendations" in f for f in failed)

    def test_fails_when_yaml_import_fails(self, tmp_path: Path) -> None:
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("no yaml")
            return real_import(name, *args, **kwargs)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.__import__", side_effect=_fake_import),
        ):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("yaml import failed" in f for f in failed)

    def test_fails_when_evaluation_prompts_missing(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("EVALUATION-PROMPTS.yaml is missing" in f for f in failed)

    def test_fails_when_evaluation_prompts_is_invalid_yaml(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text("projection: [unterminated\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("failed to parse" in f for f in failed)

    def test_skips_empty_answer_locus_entry(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "EVALUATION-PROMPTS.yaml").write_text(
            self._BASELINE_PROMPTS.replace("- README.md", "- ''\n      - README.md"), encoding="utf-8"
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert failed == []

    def test_fails_when_readme_or_security_file_missing(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path)
        (tmp_path / "README.md").unlink()
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_portal_drift(failed)
        assert any("portal file missing: README.md" in f for f in failed)


class TestRoadmapSizeGuard:
    """Tests for _roadmap_size_issues() / _ROADMAP_MAX_LINES (Decision 114, PLAN-close-audit-ulf-04-ulf-10)."""

    def test_ceiling_constant_is_10000(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _ROADMAP_MAX_LINES

        assert _ROADMAP_MAX_LINES == 10000

    def test_over_ceiling_returns_one_item_fail_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "\n" * 10001
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert len(issues) == 1
        assert "10001" in issues[0]
        assert "10000" in issues[0]
        assert "Decision 114" in issues[0]

    def test_within_ceiling_returns_empty_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "\n" * 9999
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert issues == []

    def test_exactly_at_ceiling_returns_empty_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "line\n" * 10000
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert issues == []


class TestValidateGhasProbe:
    """Tests for validate_ghas_probe() (CHECK, skip-when-unscoped) and _run_cli() (RUNNER, loud-fail)."""

    class _FakeResponse:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> "TestValidateGhasProbe._FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

    @staticmethod
    def _repo_body(secret_scanning: str = "enabled", push_protection: str = "enabled") -> bytes:
        return json.dumps(
            {
                "security_and_analysis": {
                    "secret_scanning": {"status": secret_scanning},
                    "secret_scanning_push_protection": {"status": push_protection},
                }
            }
        ).encode("utf-8")

    @staticmethod
    def _actions_body(enabled: bool = True, allowed_actions: str = "all") -> bytes:
        return json.dumps({"enabled": enabled, "allowed_actions": allowed_actions}).encode("utf-8")

    def _make_urlopen(self, secret_scanning: str = "enabled", push_protection: str = "enabled", actions_enabled: bool = True):
        def _urlopen(request: object, timeout: float = 15) -> "TestValidateGhasProbe._FakeResponse":
            url = request.full_url  # type: ignore[attr-defined]
            if url.endswith("/actions/permissions"):
                return self._FakeResponse(200, self._actions_body(enabled=actions_enabled))
            if url.endswith("/secret-scanning/alerts"):
                if secret_scanning != "enabled":  # pragma: allowlist secret -- control-state enum, not a secret
                    # Real GitHub behavior: this endpoint 404s when secret scanning is disabled
                    # for the repo -- exactly the case this probe exists to catch.
                    raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)  # type: ignore[arg-type]
                return self._FakeResponse(200, b"[]")
            return self._FakeResponse(200, self._repo_body(secret_scanning, push_protection))

        return _urlopen

    # -- CHECK: validate_ghas_probe(failed) --

    def test_check_passes_all_controls_enabled(self) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=self._make_urlopen()),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed == []

    def test_check_fails_on_disabled_control(self) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch(
                "scripts.checks.misc.validate_ghas_probe.urlopen",
                side_effect=self._make_urlopen(secret_scanning="disabled"),
            ),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed != []
        assert "disabled" in failed[0]

    def test_check_reports_disabled_control_despite_alerts_endpoint_404(self) -> None:
        """Regression: a 404 from the alerts endpoint (GitHub's real behavior when secret
        scanning is disabled) must not be swallowed as a generic transport error that discards
        the already-fetched disabled-control state and reads as a clean SKIP."""
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch(
                "scripts.checks.misc.validate_ghas_probe.urlopen",
                side_effect=self._make_urlopen(secret_scanning="disabled"),
            ),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed != []
        assert "scanning_status=disabled" in failed[0]

    def test_check_skips_when_token_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GHAS_PROBE_TOKEN", raising=False)
        with patch("scripts.checks.misc.validate_ghas_probe.urlopen") as mock_urlopen:
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed == []
        mock_urlopen.assert_not_called()

    def test_check_skips_on_auth_error(self) -> None:
        def _raise_401(request: object, timeout: float = 15) -> None:
            raise urllib.error.HTTPError(url="x", code=401, msg="Unauthorized", hdrs=None, fp=None)  # type: ignore[arg-type]

        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=_raise_401),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed == []

    def test_check_skips_on_transport_error(self) -> None:
        def _raise_url_error(request: object, timeout: float = 15) -> None:
            raise urllib.error.URLError("network unreachable")

        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=_raise_url_error),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert failed == []

    def test_check_never_prints_token(self, capsys: pytest.CaptureFixture) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "super-secret-token"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=self._make_urlopen()),
        ):
            failed: list[str] = []
            validate_ghas_probe(failed)
        assert "super-secret-token" not in capsys.readouterr().out

    # -- RUNNER: _run_cli() --

    def test_runner_returns_zero_when_all_enabled(self) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=self._make_urlopen()),
        ):
            assert _ghas_run_cli() == 0

    def test_runner_nonzero_on_disabled_control(self) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch(
                "scripts.checks.misc.validate_ghas_probe.urlopen",
                side_effect=self._make_urlopen(actions_enabled=False),
            ),
        ):
            assert _ghas_run_cli() != 0

    def test_runner_nonzero_on_disabled_secret_scanning_despite_alerts_404(self) -> None:
        """Regression: same alerts-endpoint-404 scenario as the CHECK, exercised via the
        loud-fail runner."""
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch(
                "scripts.checks.misc.validate_ghas_probe.urlopen",
                side_effect=self._make_urlopen(secret_scanning="disabled"),
            ),
        ):
            assert _ghas_run_cli() != 0

    def test_runner_nonzero_when_token_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GHAS_PROBE_TOKEN", raising=False)
        with patch("scripts.checks.misc.validate_ghas_probe.urlopen") as mock_urlopen:
            assert _ghas_run_cli() != 0
        mock_urlopen.assert_not_called()

    def test_runner_nonzero_on_auth_error(self) -> None:
        def _raise_403(request: object, timeout: float = 15) -> None:
            raise urllib.error.HTTPError(url="x", code=403, msg="Forbidden", hdrs=None, fp=None)  # type: ignore[arg-type]

        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=_raise_403),
        ):
            assert _ghas_run_cli() != 0

    def test_runner_nonzero_on_transport_error(self) -> None:
        def _raise_url_error(request: object, timeout: float = 15) -> None:
            raise urllib.error.URLError("network unreachable")

        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "tok"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=_raise_url_error),
        ):
            assert _ghas_run_cli() != 0

    def test_runner_never_prints_token(self, capsys: pytest.CaptureFixture) -> None:
        with (
            patch.dict("os.environ", {"GHAS_PROBE_TOKEN": "super-secret-token"}),
            patch("scripts.checks.misc.validate_ghas_probe.urlopen", side_effect=self._make_urlopen()),
        ):
            _ghas_run_cli()
        assert "super-secret-token" not in capsys.readouterr().out


class TestPreRoadmapGuardSelection:
    """ci-rca-cd25-ratification-tier-gap -- select_roadmap_guard_tests() dynamically pulls tests/ files that reference
    a roadmap YAML into the --pre fast tier's changed_tests set whenever a roadmap YAML
    appears in the diff, so live-roadmap guard tests stop being tier_misplaced (they used
    to run only in the full post-merge tier)."""

    select_roadmap_guard_tests = staticmethod(_validate.select_roadmap_guard_tests)

    def _make_tests_dir(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_roadmap_guard.py").write_text('ROADMAP = "ROADMAP-PLATFORM.yaml"\n', encoding="utf-8")
        (tests_dir / "test_unrelated.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        pycache_dir = tests_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "test_roadmap_guard.cpython-312.pyc").write_bytes(b"ROADMAP-PLATFORM.yaml")

    def test_roadmap_yaml_in_diff_selects_guard_tests(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PLATFORM.yaml"], repo_root=tmp_path)
        assert result == ["tests/test_roadmap_guard.py"]

    def test_no_roadmap_yaml_in_diff_does_not_force_select(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["scripts/validate.py"], repo_root=tmp_path)
        assert result == []

    def test_pycache_paths_excluded(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PLATFORM.yaml"], repo_root=tmp_path)
        assert all("__pycache__" not in f and f.endswith(".py") for f in result)

    def test_product_roadmap_yaml_also_triggers_selection(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_product_guard.py").write_text('ROADMAP = "ROADMAP-PRODUCT.yaml"\n', encoding="utf-8")
        result = self.select_roadmap_guard_tests(["docs/ROADMAP-PRODUCT.yaml"], repo_root=tmp_path)
        assert result == ["tests/test_product_guard.py"]


class TestValidateTierFloor:
    """T3.17 (VF-04): deterministic V-tier floor over schema_version-2 plan scope."""

    FIXTURES = Path(__file__).parent / "fixtures" / "plan_documents"

    def _copy_as_plan(self, src_name: str, tmp_path: Path, data: dict | None = None) -> None:
        import yaml

        if data is None:
            with (self.FIXTURES / src_name).open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        target = tmp_path / f"PLAN-{data['slug']}.yaml"
        target.write_text(yaml.safe_dump(data), encoding="utf-8")

    def test_empty_plans_dir_passes(self, tmp_path: Path, capsys) -> None:
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []
        assert "no PLAN-*.yaml files to validate" in capsys.readouterr().out

    def test_lambda_code_file_in_scope_below_v2_fails(self, tmp_path: Path, capsys) -> None:
        self._copy_as_plan("tier_floor_violation_v2.yaml", tmp_path)
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert "Deterministic V-tier floor validation" in failed
        assert "below floor V3" in capsys.readouterr().out

    def test_tier_waiver_rescues_lambda_code_violation(self, tmp_path: Path) -> None:
        import yaml

        with (self.FIXTURES / "tier_floor_violation_v2.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["tier_waiver"] = "conscious V2: handler change is comment-only"
        self._copy_as_plan("tier_floor_violation_v2.yaml", tmp_path, data=data)
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []

    def test_v1_plan_below_floor_skipped_grandfathered(self, tmp_path: Path) -> None:
        import yaml

        with (self.FIXTURES / "tier_floor_violation_v2.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["schema_version"] = 1
        data["slug"] = "zz-v1-below-floor-demo"
        data["plan_path"] = "docs/plans/PLAN-zz-v1-below-floor-demo.yaml"
        target = tmp_path / "PLAN-zz-v1-below-floor-demo.yaml"
        target.write_text(yaml.safe_dump(data), encoding="utf-8")
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []

    def test_tf_in_scope_forces_v3(self, tmp_path: Path) -> None:
        import yaml

        with (self.FIXTURES / "valid_v2.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["scope"] = [{"file": "terraform/personal/foo.tf", "action": "Modify", "purpose": "tf change"}]
        target = tmp_path / f"PLAN-{data['slug']}.yaml"
        target.write_text(yaml.safe_dump(data), encoding="utf-8")
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert "Deterministic V-tier floor validation" in failed

    def test_python_only_scope_floors_to_v2_and_passes_at_v2(self, tmp_path: Path) -> None:
        self._copy_as_plan("valid_v2.yaml", tmp_path)
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []

    def test_docs_only_scope_floors_to_v1(self, tmp_path: Path) -> None:
        import yaml

        with (self.FIXTURES / "valid_v2.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["scope"] = [{"file": "docs/PROJECT_CONTEXT.md", "action": "Modify", "purpose": "docs change"}]
        data["verification_tier"] = "V1"
        target = tmp_path / f"PLAN-{data['slug']}.yaml"
        target.write_text(yaml.safe_dump(data), encoding="utf-8")
        failed: list[str] = []
        validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []

    def test_alias_matches_registered_check(self) -> None:
        assert validate_tier_floor is _validate.validate_tier_floor

    def test_lambda_manifest_load_failure_treated_as_no_code_files(self, tmp_path: Path) -> None:
        from scripts.checks.roadmap import validate_tier_floor as _tier_floor_module

        with patch.object(_tier_floor_module.lambda_manifest, "load_all", side_effect=RuntimeError("boom")):
            self._copy_as_plan("valid_v2.yaml", tmp_path)
            failed: list[str] = []
            validate_tier_floor(failed, plans_dir=tmp_path)
        assert failed == []

    def test_stub_manifest_skipped(self, tmp_path: Path) -> None:
        from scripts.checks.roadmap import validate_tier_floor as _tier_floor_module
        from scripts.lambda_manifest import LambdaManifest

        stub_manifest = LambdaManifest(
            artifact="stub.zip",
            handlers=["src/lambdas/ducklake_catalog_dr/handler.py"],
            status="stub",
        )
        with patch.object(_tier_floor_module.lambda_manifest, "load_all", return_value={"stub": stub_manifest}):
            self._copy_as_plan("tier_floor_violation_v2.yaml", tmp_path)
            failed: list[str] = []
            validate_tier_floor(failed, plans_dir=tmp_path)
        # The stub manifest's handler is skipped, so the fixture's scope file (which
        # matches only that stub handler) is not treated as Lambda code -- floors to V2.
        assert failed == []

    def test_excluded_handler_path_skipped(self, tmp_path: Path) -> None:
        from scripts.checks.roadmap import validate_tier_floor as _tier_floor_module
        from scripts.lambda_manifest import LambdaManifest

        excluded_manifest = LambdaManifest(
            artifact="excluded.zip",
            handlers=["src/lambdas/ducklake_catalog_dr/handler.py"],
            excludes=["src/lambdas/ducklake_catalog_dr/handler.py"],
            status="active",
        )
        with patch.object(_tier_floor_module.lambda_manifest, "load_all", return_value={"excluded": excluded_manifest}):
            self._copy_as_plan("tier_floor_violation_v2.yaml", tmp_path)
            failed: list[str] = []
            validate_tier_floor(failed, plans_dir=tmp_path)
        # The only manifest's handler is excludes-listed, so no code files are derived
        # and the fixture's Lambda scope file no longer forces a V3 floor.
        assert failed == []


# ---------------------------------------------------------------------------
# validate_vp_replay (T3.15 c2, VF-01, Decision 104) -- audit-wave-6-vp-replay
# ---------------------------------------------------------------------------


def _vp_replay_plan_dict(slug: str, verification_plan: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "slug": slug,
        "intent": "Fixture plan for validate_vp_replay unit tests.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture",
        "scope": [{"file": "scripts/dummy.py", "action": "Modify", "purpose": "test fixture"}],
        "acceptance_criteria": ["dummy criterion"],
        "verification_plan": verification_plan,
        "execution_steps": ["dummy step"],
    }


def _write_vp_replay_plan(tmp_path: Path, slug: str, verification_plan: list[dict]) -> str:
    import yaml as _yaml  # noqa: PLC0415

    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(_yaml.dump(_vp_replay_plan_dict(slug, verification_plan)), encoding="utf-8")
    return rel


class TestValidateVpReplay:
    """Tests for validate_vp_replay() (T3.15 c2, VF-01) via the changed_files/root injection seam."""

    def test_vp_replay_no_plan_in_diff_is_noop_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_vp_replay_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        """A plan path present in changed_files but absent on disk (deleted in the diff) is a no-op."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_vp_replay_hermetic_step_failing_command_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-fail",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that fails.",
                    "command": "exit 1",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_vp_replay_hermetic_step_missing_literal_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-literal",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command whose output lacks the expected literal.",
                    "command": "echo something-else",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("expected-literal" in f for f in failed)

    def test_vp_replay_hermetic_step_passing_command_is_clean(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-pass",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo expected-literal",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_vp_replay_non_hermetic_and_post_deploy_steps_are_excluded_but_listed(self, tmp_path: Path, capsys) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-excluded",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic pre-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 2,
                    "phase": "post-deploy",
                    "hermetic": True,
                    "action": "Hermetic but post-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 3,
                    "phase": "post-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic post-deploy step -- phase disqualifies it regardless of hermetic marker.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (not-hermetic)" in out
        assert f"EXCLUDED: {rel}:2 (post-deploy)" in out
        assert f"EXCLUDED: {rel}:3 (post-deploy)" in out

    def test_vp_replay_timeout_path_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-timeout",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that hangs past the per-step timeout.",
                    "command": "sleep 5",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.PER_STEP_TIMEOUT_SECONDS", 0.1):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("TIMEOUT" in f for f in failed)

    def test_vp_replay_load_error_path_is_skipped_with_note(self, tmp_path: Path, capsys) -> None:
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "PLAN-vpr-bad.yaml").write_text("not: [valid, plan, shape", encoding="utf-8")
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-bad.yaml"], root=tmp_path)
        out = capsys.readouterr().out
        assert failed == []
        assert "SKIP" in out and "load error" in out

    def test_vp_replay_import_error_reddens_distinctly_from_content_error(self, tmp_path: Path) -> None:
        """A broken scripts.plan_document import is an infra failure -- it must redden failed[],
        not be downgraded to a silent SKIP alongside routine content-validation errors."""
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-importerror",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Irrelevant -- load fails before any step runs.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.plan_document.load", side_effect=ImportError("broken plan_document")):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("vp-replay" in f and "could not import" in f for f in failed)

    def test_vp_replay_aggregate_step_count_budget_guard(self, tmp_path: Path) -> None:
        steps = [
            {
                "step": i,
                "phase": "pre-deploy",
                "hermetic": True,
                "action": "quick pass",
                "command": "true",
                "expected": "n/a",
                "fix_if": "n/a",
            }
            for i in range(1, 5)
        ]
        rel = _write_vp_replay_plan(tmp_path, "vpr-budget", steps)
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 2):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("budget exceeded" in f for f in failed)

    def test_vp_replay_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files()."""
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            validate_vp_replay(failed)
        assert failed == []


def _write_oidc_tf(tmp_path: Path, body: str) -> None:
    oidc_path = tmp_path / "terraform" / "personal" / "oidc.tf"
    oidc_path.parent.mkdir(parents=True, exist_ok=True)
    oidc_path.write_text(body, encoding="utf-8")


class TestValidateInvokeImpliesResolve:
    """Tests for validate_invoke_implies_resolve() (T2.34:c2, Decision 104)."""

    def test_invoke_implies_resolve_passes_on_real_composed_oidc_tf(self) -> None:
        """The real terraform/personal/oidc.tf: all invoking roles (branch, pr, plan, drift)
        resolve SSM via source_policy_documents composition -- zero failures."""
        failed: list[str] = []
        validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_vacuous_pass_for_non_invoking_role(self, tmp_path: Path) -> None:
        """A role whose composed statements never invoke the DuckLake reader/writer passes
        without needing SSM at all."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "github_ci_noop" {
              statement {
                sid       = "S3List"
                effect    = "Allow"
                actions   = ["s3:ListBucket"]
                resources = ["*"]
              }
            }

            resource "aws_iam_role_policy" "github_ci_noop" {
              name   = "agent-platform-github-ci-noop"
              role   = aws_iam_role.github_ci_noop.id
              policy = data.aws_iam_policy_document.github_ci_noop.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_fails_when_composition_omits_ssm(self, tmp_path: Path) -> None:
        """A role that invokes the ducklake writer but never composes an SSM-granting
        document is a genuine T2.34:c2 violation (rec-2363-class drift)."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "github_ci_violator" {
              statement {
                sid    = "DuckLakeInvokeCI"
                effect = "Allow"
                actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"]
                resources = [
                  aws_lambda_function.ducklake_writer.arn,
                  "${aws_lambda_function.ducklake_writer.arn}:*",
                ]
              }
            }

            resource "aws_iam_role_policy" "github_ci_violator" {
              name   = "agent-platform-github-ci-violator"
              role   = aws_iam_role.github_ci_violator.id
              policy = data.aws_iam_policy_document.github_ci_violator.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert len(failed) == 1
        assert "github_ci_violator" in failed[0]
        assert "lacks ssm:Get*" in failed[0]

    def test_invoke_implies_resolve_passes_via_transitive_source_composition(self, tmp_path: Path) -> None:
        """A role composing a document that itself sources the SSM fragment (two levels of
        source_policy_documents) still resolves -- composition is followed transitively."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "ci_ssm_refresh_read" {
              statement {
                sid       = "SSMParameterRead"
                effect    = "Allow"
                actions   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
                resources = ["arn:aws:ssm:eu-west-2:1234567890:parameter/agent-platform/*"]
              }
            }

            data "aws_iam_policy_document" "ci_full_refresh_read" {
              source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

              statement {
                sid       = "TfstateRead"
                effect    = "Allow"
                actions   = ["s3:GetObject"]
                resources = ["arn:aws:s3:::agent-platform-data-lake/tfstate/personal/*"]
              }
            }

            data "aws_iam_policy_document" "github_ci_composer" {
              source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]

              statement {
                sid    = "DuckLakeWriterInvoke"
                effect = "Allow"
                actions = ["lambda:InvokeFunction"]
                resources = [
                  aws_lambda_function.ducklake_writer.arn,
                ]
              }
            }

            resource "aws_iam_role_policy" "github_ci_composer" {
              name   = "agent-platform-github-ci-composer"
              role   = aws_iam_role.github_ci_composer.id
              policy = data.aws_iam_policy_document.github_ci_composer.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_fails_loud_when_no_policy_documents_found(self, tmp_path: Path) -> None:
        """An oidc.tf that no longer matches the expected HCL shape fails loud rather than
        silently passing vacuously (Decision 55)."""
        _write_oidc_tf(tmp_path, "# empty -- no aws_iam_policy_document or aws_iam_role_policy blocks\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert len(failed) == 1
        assert "no aws_iam_policy_document / aws_iam_role_policy blocks found" in failed[0]
