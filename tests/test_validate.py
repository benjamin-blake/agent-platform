"""Tests for the new functions added to scripts/validate.py in agent/infra-testing-enforcement.

Covers: validate_cli_tools_in_prompts, validate_test_coverage, validate_prompt_compliance,
and the _load_coverage_checker / _load_prompt_compliance helpers.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate", _SCRIPT_PATH)
_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_validate)  # type: ignore[union-attr]
sys.modules["validate"] = _validate

validate_scheduled_agent_logs = _validate.validate_scheduled_agent_logs
validate_cli_tools_in_prompts = _validate.validate_cli_tools_in_prompts
validate_test_coverage = _validate.validate_test_coverage
validate_prompt_compliance = _validate.validate_prompt_compliance
validate_ruff_version_alignment = _validate.validate_ruff_version_alignment
validate_invariants = _validate.validate_invariants
validate_no_underscore_instructions = _validate.validate_no_underscore_instructions
validate_recommendations_schema = _validate.validate_recommendations_schema
validate_complexity = _validate.validate_complexity
validate_sloc_limits = _validate.validate_sloc_limits
validate_cc_limits = _validate.validate_cc_limits
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
            patch("validate._KNOWN_CLI_TOOLS", {"aws"}),
            patch("validate.ROOT", tmp_path),
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
            patch("validate._KNOWN_CLI_TOOLS", {"terraform"}),
            patch("validate.ROOT", tmp_path),
            patch("validate.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert len(failed) == 1
        assert "CLI tool verification" in failed[0]

    def test_skips_comment_lines_in_code_blocks(self, tmp_path: Path) -> None:
        """Lines starting with # inside code blocks are not treated as commands."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\n# aws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("validate._KNOWN_CLI_TOOLS", {"aws"}),
            patch("validate.ROOT", tmp_path),
            patch("validate.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        # aws appears only in a comment — not in referenced, so not checked
        assert failed == []

    def test_no_failures_when_no_md_files(self, tmp_path: Path) -> None:
        """No failures when no markdown files exist in the search dirs."""
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []


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

        with patch("validate._load_coverage_checker", return_value=mock_checker):
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

        with patch("validate._load_coverage_checker", return_value=mock_checker):
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

        with patch("validate._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert len(failed) == 1
        assert "Test coverage check" in failed[0]

    def test_skips_when_checker_not_found(self) -> None:
        """No failures (and no exception) when test_coverage_checker.py is absent."""
        with patch("validate._load_coverage_checker", return_value=None):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []


class TestValidatePromptCompliance:
    """Tests for validate_prompt_compliance()."""

    def test_passes_when_no_violations(self, tmp_path: Path) -> None:
        """No failures when compliance checker reports no violations."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "impl.prompt.md").write_text(
            "## Behavioural Invariants\n```yaml\nretro_lite_per_step: true\n```\n",
            encoding="utf-8",
        )

        mock_compliance = MagicMock()
        mock_compliance.parse_invariants.return_value = {"retro_lite_per_step": True}
        mock_compliance.parse_retro_lite_log.return_value = []
        mock_compliance.parse_execution_state.return_value = None
        mock_compliance.check_retro_lite_compliance.return_value = []

        with (
            patch("validate._load_prompt_compliance", return_value=mock_compliance),
            patch("validate.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_prompt_compliance(failed)

        assert failed == []

    def test_fails_when_violations_found(self, tmp_path: Path) -> None:
        """Appends to failed list when compliance violations are found."""
        prompt_dir = tmp_path / ".github" / "prompts"
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "impl.prompt.md").write_text(
            "## Behavioural Invariants\n```yaml\nretro_lite_per_step: true\n```\n",
            encoding="utf-8",
        )

        mock_compliance = MagicMock()
        mock_compliance.parse_invariants.return_value = {"retro_lite_per_step": True}
        mock_compliance.parse_retro_lite_log.return_value = []
        mock_compliance.parse_execution_state.return_value = {"total_steps": 5, "current_step": 1}
        mock_compliance.check_retro_lite_compliance.return_value = ["retro_lite_per_step: expected 5 entries, found 0"]

        with (
            patch("validate._load_prompt_compliance", return_value=mock_compliance),
            patch("validate.ROOT", tmp_path),
        ):
            failed: list[str] = []
            validate_prompt_compliance(failed)

        assert len(failed) == 1
        assert "Prompt compliance check" in failed[0]

    def test_skips_when_compliance_not_found(self) -> None:
        """No failures when prompt_compliance.py is absent."""
        with patch("validate._load_prompt_compliance", return_value=None):
            failed: list[str] = []
            validate_prompt_compliance(failed)

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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            result = _load_prompt_compliance()
        assert result is None


class TestValidateRuffVersionAlignment:
    """Tests for validate_ruff_version_alignment()."""

    def test_passes_when_versions_match(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text("ruff==0.15.9\n", encoding="utf-8")
        pc = tmp_path / ".pre-commit-config.yaml"
        pc.write_text(
            "repos:\n-   repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.15.9\n    hooks:\n    -   id: ruff\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("validate.ROOT", tmp_path):
            validate_ruff_version_alignment(failed)
        assert failed == []

    def test_fails_when_versions_differ(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text("ruff==0.15.9\n", encoding="utf-8")
        pc = tmp_path / ".pre-commit-config.yaml"
        pc.write_text(
            "repos:\n-   repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.3.0\n    hooks:\n    -   id: ruff\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("validate.ROOT", tmp_path):
            validate_ruff_version_alignment(failed)
        assert "Ruff version alignment" in failed

    def test_fails_when_ruff_not_pinned(self, tmp_path: Path) -> None:
        req = tmp_path / "requirements.txt"
        req.write_text("pytest\n", encoding="utf-8")
        pc = tmp_path / ".pre-commit-config.yaml"
        pc.write_text(
            "repos:\n-   repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.15.9\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("validate.ROOT", tmp_path):
            validate_ruff_version_alignment(failed)
        assert "Ruff version alignment" in failed


class TestValidateEnvironmentTaxonomy:
    """Tests for validate_environment_taxonomy (two-axis vocabulary reservation lint)."""

    def _run(self, tmp_path: Path, files: dict[str, str], changed: list[str]) -> list[str]:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        failed: list[str] = []
        with (
            patch("validate.get_changed_files", return_value=changed),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.get_changed_files", return_value=["docs/gone.md"]),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("validate.run", side_effect=mock_run),
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
            patch("validate.validate_terraform_try"),
            patch("validate.shutil.which", return_value="/usr/bin/terraform"),
            patch("validate.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
        assert failed == []

    def test_skips_terraform_binary_steps_when_not_found(self, capsys: pytest.CaptureFixture) -> None:
        """No terraform binary -> creds-free helper prints a skip and `run` is never invoked."""
        with (
            patch("validate.validate_terraform_try"),
            patch("validate.shutil.which", return_value=None),
            patch("validate.run", side_effect=AssertionError("run must not be called when terraform is absent")),
        ):
            failed: list[str] = []
            _validate.run_terraform_checks(failed)

        captured = capsys.readouterr()
        assert "skipped" in captured.out
        assert failed == []

    def test_creds_free_covers_both_roots(self) -> None:
        """run_terraform_creds_free() runs init -backend=false + validate + fmt for BOTH roots, no plan."""
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
            patch("validate.run", side_effect=mock_run),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)

        chdirs = {arg for cmd in calls for arg in cmd if isinstance(arg, str) and arg.startswith("-chdir=")}
        flat = [tok for cmd in calls for tok in cmd]
        assert "-chdir=terraform" in chdirs
        assert "-chdir=terraform/personal" in chdirs
        assert any("-backend=false" in cmd for cmd in calls)  # creds-free init
        assert all("plan" not in cmd for cmd in calls)  # no creds-needing plan here
        assert "init" in flat and "validate" in flat and "fmt" in flat
        assert failed == []

    def test_creds_free_skips_when_terraform_absent(self, capsys: pytest.CaptureFixture) -> None:
        """run_terraform_creds_free() emits a visible skip and calls nothing when terraform is absent."""
        with (
            patch("validate.shutil.which", return_value=None),
            patch("validate.run", side_effect=AssertionError("run must not be called")),
        ):
            failed: list[str] = []
            _validate.run_terraform_creds_free(failed)
        assert "skipped" in capsys.readouterr().out
        assert failed == []


class TestValidateSubprocessEncoding:
    """Tests for validate_subprocess_encoding()."""

    validate_subprocess_encoding = staticmethod(_validate.validate_subprocess_encoding)

    def test_passes_when_encoding_present(self, tmp_path: Path) -> None:
        """No failure when subprocess.run with text=True also has encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run(["cmd"], text=True, encoding="utf-8")\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_fails_when_encoding_missing(self, tmp_path: Path) -> None:
        """Fails when subprocess.run with text=True has no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text('subprocess.run(["cmd"], capture_output=True, text=True)\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed

    def test_passes_when_no_text_true(self, tmp_path: Path) -> None:
        """No failure when subprocess.run does not use text=True."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ok.py").write_text('subprocess.run(["cmd"], capture_output=True)\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_catches_popen_without_encoding(self, tmp_path: Path) -> None:
        """Fails for subprocess.Popen with text=True and no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_popen.py").write_text('subprocess.Popen(["cmd"], text=True)\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed


class TestValidateSysExecutable:
    """Tests for validate_sys_executable()."""

    validate_sys_executable = staticmethod(_validate.validate_sys_executable)

    def test_passes_when_sys_executable_used(self, tmp_path: Path) -> None:
        """No failure when sys.executable is used."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run([sys.executable, "-m", "pytest"])\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert failed == []

    def test_fails_when_bare_python_used(self, tmp_path: Path) -> None:
        """Fails when bare 'python' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text("subprocess.run(['python', '-m', 'pytest'])\n", encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed

    def test_fails_when_bare_pip_used(self, tmp_path: Path) -> None:
        """Fails when bare 'pip' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_pip.py").write_text('subprocess.run(["pip", "install", "boto3"])\n', encoding="utf-8")
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed

    def test_passes_with_no_tf_files(self, tmp_path: Path) -> None:
        """No failure when terraform directory has no .tf files."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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

        # Wrapper file: using "-p", "@..." is allowed here
        (tmp_path / "scripts" / "copilot_wrapper.py").write_text(
            'cmd.extend(["-p", f"@{prompt_file}"])\n',
            encoding="utf-8",
        )
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

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert failed == []

    def test_fails_on_at_file_without_instruction_in_non_wrapper(self, tmp_path: Path) -> None:
        """Fails when a script other than copilot_wrapper.py uses '-p', '@file' pattern."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        # copilot_wrapper.py: excluded from check
        (tmp_path / "scripts" / "copilot_wrapper.py").write_text("# wrapper\n", encoding="utf-8")
        # Another script that uses the bad pattern
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

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_invariants(failed)

        assert "Invariant checks" in failed
        # Error message must mention the @file gotcha
        # (validated by test passing -- the function adds to failed list)

    def test_fails_on_mock_count_mismatch(self, tmp_path: Path) -> None:
        """Fails when cleanup_after_merge has many subprocess calls but few test mocks."""
        scripts_dir = tmp_path / "scripts" / "executor"
        scripts_dir.mkdir(parents=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        (tmp_path / "scripts" / "copilot_wrapper.py").write_text("# wrapper\n", encoding="utf-8")
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_no_underscore_instructions(failed)

        assert failed == []

    def test_underscore_check_fails_when_file_present(self, tmp_path: Path) -> None:
        """Validation fails when .github/copilot_instructions.md exists."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir(parents=True)
        (github_dir / "copilot_instructions.md").write_text("# ghost\n", encoding="utf-8")

        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert failed == []

    def test_fails_when_acceptance_contains_python_c(self, tmp_path: Path) -> None:
        """An acceptance field containing 'python -c' triggers a schema error."""
        import copy

        bad_rec = copy.deepcopy(self._VALID_REC)
        bad_rec["acceptance"] = '`python -c "import foo; assert foo.bar"`'
        self._write_jsonl(tmp_path, [bad_rec])
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_recommendations_schema(failed)
        assert "Recommendations schema validation" in failed

    def test_skips_when_file_missing(self, tmp_path: Path) -> None:
        """No error when the JSONL file does not exist."""
        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Files with waiver annotation are allowed over limit."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "waivered.py"
        big_file.write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 501,
            encoding="utf-8",
        )

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_allows_under_limit_file(self, tmp_path: Path) -> None:
        """Files under 500 SLOC pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small_file = scripts_dir / "small.py"
        small_file.write_text("x = 1\n" * 100, encoding="utf-8")

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from SLOC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        init_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []


class TestValidateCcLimits:
    """Tests for validate_cc_limits() -- Decision 43 cyclomatic-complexity gate."""

    def test_catches_over_limit_function(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Functions exceeding 20 branches without waiver are flagged by name."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        over_limit = scripts_dir / "big_func.py"
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        over_limit.write_text(f"def heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_alias.py" in e for e in failed)

    def test_allows_whitelisted_portal(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted as the canonical write path."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'OpsWriter().write("ops_recommendations", merged)\n',
            encoding="utf-8",
        )
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []

    def test_clean_script_with_no_warehouse_writes_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only call portal functions (file_rec) pass cleanly."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert "Executor boundary validation" in failed

    def test_boundary_compliant_passes(self, tmp_path: Path) -> None:
        """Open rec with boundary file but automatable:false passes."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["automatable"] = False
        self._write_jsonl(tmp_path, [rec])
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_closed_rec_ignored(self, tmp_path: Path) -> None:
        """Closed rec with boundary file + automatable:true is not flagged."""
        import copy

        rec = copy.deepcopy(self._VALID_REC)
        rec["status"] = "closed"
        self._write_jsonl(tmp_path, [rec])
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert failed == []

    def test_missing_jsonl_skips_gracefully(self, tmp_path: Path) -> None:
        """Missing JSONL file does not raise and does not append to failed."""
        with patch("validate.ROOT", tmp_path):
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
        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_executor_boundary(failed)
        assert "Executor boundary validation" in failed


# ---------------------------------------------------------------------------
# TestValidateOutboxStaleness
# ---------------------------------------------------------------------------


class TestValidateOutboxStaleness:
    """Tests for validate_outbox_staleness()."""

    def test_no_outbox_directory_passes(self, tmp_path: Path, capsys) -> None:
        """No outbox directory: passes with 'No outbox directory' message."""
        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

    def test_ensure_fresh_dq_runs_when_cache_missing(self, tmp_path: Path, capsys) -> None:
        """No dq-latest.json on disk: credential check runs, then data_quality_runner is invoked."""
        with (
            patch("validate.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("validate.run") as mock_run,
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
            patch("validate.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("validate.run") as mock_run,
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

        with patch("validate.ROOT", tmp_path), patch("validate.run") as mock_run:
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
            patch("validate.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("validate.run") as mock_run,
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
            patch("validate.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("validate.run") as mock_run,
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
        with patch("validate.get_changed_files", return_value=[]):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "coverage" in captured.out.lower()
        assert "No changed files" in captured.out

    def test_run_coverage_check_all_covered(self, capsys) -> None:
        """When every changed file is covered, the report says 'All scope files covered'."""
        with (
            patch("validate.get_changed_files", return_value=["scripts/ops_data_portal.py"]),
            patch("scripts.verifiers.check_coverage", return_value=[]),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "All scope files covered" in captured.out

    def test_run_coverage_check_lists_uncovered(self, capsys) -> None:
        """Uncovered files are printed line-by-line under the report header."""
        with (
            patch(
                "validate.get_changed_files",
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
            patch("validate.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("validate.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_warns_no_block_missing_dq_file(self, tmp_path: Path, capsys) -> None:
        """Warns but does not block when dq-latest.json is missing."""
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("validate.run", side_effect=self._make_run()),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.run", side_effect=self._make_run()),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.run", side_effect=self._make_run(old_yaml=old_yaml)),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.run", side_effect=self._make_run(git_show_rc=1)),
            patch("validate.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.accepted_values" in failed[0]

    def test_no_dq_yaml_changes_returns_early(self, tmp_path: Path) -> None:
        """Returns without loading dq-latest.json when no YAML files changed."""
        with (
            patch("validate.run", side_effect=self._make_run(no_changes=True)),
            patch("validate.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_pre_mode_does_not_call_guard(self) -> None:
        """main() --pre does not invoke _check_graduation_guard."""
        with (
            patch("validate._check_graduation_guard") as mock_guard,
            patch("validate.run_lint_checks"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate.run", return_value=MagicMock(stdout="agent/test\n", returncode=0)),
            patch.dict("os.environ", {"_VALIDATE_DEPTH": "0"}),
            patch("sys.argv", ["validate.py", "--pre"]),
        ):
            with pytest.raises(SystemExit):
                _validate.main()
        mock_guard.assert_not_called()


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
        with patch.object(_validate, "ROOT", tmp_path):
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

        original_root = _validate.check_source_registry.__globals__["ROOT"]
        _validate.check_source_registry.__globals__["ROOT"] = tmp_path
        try:
            failed: list[str] = []
            check_source_registry(failed)
            assert failed == [], f"Expected no failures but got: {failed}"
        finally:
            _validate.check_source_registry.__globals__["ROOT"] = original_root

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

        original_root = _validate.check_source_registry.__globals__["ROOT"]
        _validate.check_source_registry.__globals__["ROOT"] = tmp_path
        try:
            failed: list[str] = []
            check_source_registry(failed)
            assert "Source registry CI guard" in failed
        finally:
            _validate.check_source_registry.__globals__["ROOT"] = original_root


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
            patch("validate.run", side_effect=self._make_run(changed)),
            patch("validate.ROOT", tmp_path),
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
        with patch("validate.run", side_effect=self._make_run(changed)):
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
            patch("validate.run", side_effect=self._make_run(changed)),
            patch("validate.ROOT", tmp_path),
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
            patch("validate.run", side_effect=self._make_run(changed)),
            patch("validate.ROOT", tmp_path),
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
        with patch("validate.run", side_effect=self._make_run(changed)):
            failed: list[str] = []
            validate_scheduled_agent_logs(failed)
        assert failed == []

    def test_skips_when_no_files_changed(self) -> None:
        """Skips validation when there are no changed files relative to main."""
        with patch("validate.run", side_effect=self._make_run([])):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert len(failed) == 1
        assert "s3:Get" in failed[0]

    def test_skips_when_manifest_missing(self, tmp_path: Path, capsys) -> None:
        """Gracefully skips if config/agent/validate/iam_runner_manifest.yaml does not exist."""
        with patch("validate.ROOT", tmp_path):
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

        with patch("validate.run", side_effect=mock_run):
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

        with patch("validate.run", side_effect=mock_run):
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

        with patch("validate.run", side_effect=mock_run):
            files = get_changed_files()

        assert files == []


def _pre_mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
    """Shared subprocess mock that handles git branch + everything else."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "agent/test-branch\n"
    return result


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
            patch("validate.get_changed_files", return_value=changed),
            patch("validate.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
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
            patch("validate.get_changed_files", return_value=["scripts/validate.py"]),
            patch("validate.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c and "--picked" in c]
        assert not pytest_cmds

    def test_invokes_pytest_picked_when_test_files_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("validate.get_changed_files", return_value=["scripts/validate.py", "tests/test_validate.py"]),
            patch("validate.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c and "--picked" in c]
        assert pytest_cmds, "pytest --picked not invoked"
        assert "--mode=branch" in pytest_cmds[0]
        assert "not integration" in pytest_cmds[0]

    def test_treats_pytest_exit_5_as_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = "agent/test-branch\n"
            result.returncode = 5 if ("pytest" in cmd and "--picked" in cmd) else 0
            return result

        with (
            patch("validate.get_changed_files", return_value=["tests/test_validate.py"]),
            patch("validate.run", side_effect=exit5_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 1.0]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0


class TestBudgetAssertion:
    """Tests for the 5-minute fast-tier wall-clock budget assertion."""

    def test_exits_1_on_budget_breach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=[0.0, 400.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=[0.0, 400.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 60.0]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0

    def test_budget_constant_is_300(self) -> None:
        assert _FAST_TIER_BUDGET_SECONDS == 300


class TestIgnoreBudgetFlag:
    """Tests for the --ignore-budget escape hatch."""

    def test_bypass_calls_bypass_rec_helper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 60.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 60.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 60.0]),
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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 400.0]),
            patch("validate._file_budget_bypass_rec"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()


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
            patch("validate.get_changed_files", return_value=[]),
            patch("validate.run", side_effect=_pre_mock_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_copilot_multipliers"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=[0.0, 60.0]),
            patch("validate._file_budget_bypass_rec"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0


class TestBudgetBreachRecFiling:
    """Tests for _file_budget_breach_rec and _file_budget_bypass_rec helpers."""

    def test_breach_rec_calls_file_rec_with_budget_breach_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("validate.run", return_value=git_result),
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
            patch("validate.run", return_value=git_result),
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
            patch("validate.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_breach_rec(400.0, [], None)

    def test_bypass_rec_calls_file_rec_with_budget_bypass_source(self) -> None:
        mock_portal = MagicMock()
        git_result = MagicMock(returncode=0, stdout="agent/test\n")

        with (
            patch("validate.run", return_value=git_result),
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
            patch("validate.run", return_value=git_result),
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
            patch("validate.run", return_value=git_result),
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            # Must not raise
            _file_budget_bypass_rec(60.0, [], None)
