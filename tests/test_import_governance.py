"""Tests for scripts/import_governance.py -- 100% coverage including anti-vacuous-pass cases."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.import_governance import (
    _fast_tier_budget_breach_open,
    _kg13_tier_item_filed,
    _normalize_pkg,
    _read_executor_concurrency,
    check_lockfile_sync,
    evaluate_bazel_revisit_trigger,
    run_import_contracts,
)

ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# run_import_contracts
# ---------------------------------------------------------------------------


class TestRunImportContracts:
    def test_passes_on_clean_tree(self) -> None:
        """Contracts pass green on the unmodified repository tree."""
        passed, output = run_import_contracts()
        assert passed, f"Expected contracts to pass, got:\n{output}"
        assert "kept" in output.lower() or "KEPT" in output

    def test_negative_illegal_import_detected(self, tmp_path: Path) -> None:
        """Anti-vacuous-pass: an injected illegal import is detected by lint-imports."""
        # Create a minimal importlinter config with a forbidden contract
        importlinter_cfg = tmp_path / ".importlinter"
        importlinter_cfg.write_text(
            "[importlinter]\n"
            "root_packages =\n"
            "    mypkg\n\n"
            "[importlinter:contract:test-forbidden]\n"
            "name = src.a must not import src.b\n"
            "type = forbidden\n"
            "source_modules =\n"
            "    mypkg.a\n"
            "forbidden_modules =\n"
            "    mypkg.b\n",
            encoding="utf-8",
        )
        # Create a minimal two-module package that violates the contract
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "b.py").write_text("X = 1\n", encoding="utf-8")
        (pkg / "a.py").write_text("from mypkg import b  # forbidden import\n", encoding="utf-8")

        lint_imports_bin = Path(sys.executable).parent / "lint-imports"
        cmd: list[str] = [str(lint_imports_bin)] if lint_imports_bin.exists() else ["lint-imports"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=tmp_path,
        )
        assert result.returncode != 0, "Expected lint-imports to report a violation for the injected forbidden import"
        combined = result.stdout + result.stderr
        assert "broken" in combined.lower() or "BROKEN" in combined

    def test_contracts_invoke_lint_imports(self) -> None:
        """run_import_contracts shells out to lint-imports; verify the returned output is non-empty."""
        passed, output = run_import_contracts()
        assert len(output) > 0, "Expected non-empty output from lint-imports"


# ---------------------------------------------------------------------------
# check_lockfile_sync
# ---------------------------------------------------------------------------


class TestCheckLockfileSync:
    def test_passes_on_committed_lockfile(self) -> None:
        """check_lockfile_sync passes when requirements.lock is in sync with requirements.txt."""
        in_sync, message = check_lockfile_sync()
        assert in_sync, f"Expected lockfile to be in sync, got: {message}"
        assert "pins all" in message

    def test_missing_lock_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails when requirements.lock is absent."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\n", encoding="utf-8")

        with patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt), patch(
            "scripts.import_governance._REQUIREMENTS_LOCK", tmp_path / "requirements.lock"
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "not found" in msg or "requirements.lock" in msg

    def test_missing_top_level_package_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails when a top-level package from requirements.txt is absent from the lock."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\nmypackage>=1.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        # Lock only pins requests, missing mypackage
        req_lock.write_text("requests==2.31.0\n", encoding="utf-8")

        with patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt), patch(
            "scripts.import_governance._REQUIREMENTS_LOCK", req_lock
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "mypackage" in msg or "missing" in msg.lower()

    def test_missing_requirements_txt_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails gracefully when requirements.txt is absent."""
        with patch("scripts.import_governance._REQUIREMENTS_TXT", tmp_path / "requirements.txt"):
            in_sync, msg = check_lockfile_sync()
        assert not in_sync
        assert "not found" in msg or "requirements.txt" in msg

    def test_extras_are_normalized(self, tmp_path: Path) -> None:
        """Packages with extras (e.g. pyiceberg[glue,duckdb]) are found in the lockfile."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("pyiceberg[glue,duckdb]>=0.11.1\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("pyiceberg[duckdb,glue]==0.11.1\n", encoding="utf-8")

        with patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt), patch(
            "scripts.import_governance._REQUIREMENTS_LOCK", req_lock
        ):
            in_sync, msg = check_lockfile_sync()

        assert in_sync, f"Expected extras-normalized package to be found; got: {msg}"

    def test_comments_and_blanks_skipped(self, tmp_path: Path) -> None:
        """Comments and blank lines in requirements.txt are ignored."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("# core\nrequests>=2.0\n\n# dev\npytest>=7.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("requests==2.31.0\npytest==7.4.0\n", encoding="utf-8")

        with patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt), patch(
            "scripts.import_governance._REQUIREMENTS_LOCK", req_lock
        ):
            in_sync, msg = check_lockfile_sync()

        assert in_sync


# ---------------------------------------------------------------------------
# evaluate_bazel_revisit_trigger
# ---------------------------------------------------------------------------


class TestEvaluateBazelRevisitTrigger:
    def test_dormant_at_concurrency_one(self) -> None:
        """Trigger is dormant when executor concurrency == 1 (current state)."""
        with patch("scripts.import_governance._read_executor_concurrency", return_value=1):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert not fired
        assert "DORMANT" in msg
        assert "concurrency=1" in msg

    def test_does_not_fire_when_concurrency_gt1_but_no_second_condition(self) -> None:
        """Trigger stays dormant when concurrency > 1 but neither KG.13 nor breach is present."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=False),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert not fired
        assert "DORMANT" in msg

    def test_fires_when_concurrency_gt1_and_kg13_filed(self) -> None:
        """Trigger fires when concurrency > 1 AND KG.13 is filed."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=True),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "ADVISORY" in msg
        assert "KG.13" in msg

    def test_fires_when_concurrency_gt1_and_budget_breach(self) -> None:
        """Trigger fires when concurrency > 1 AND a budget breach is open."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=3),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=False),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=True),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "ADVISORY" in msg
        assert "breach" in msg.lower() or "budget" in msg.lower()

    def test_advisory_message_does_not_auto_act(self) -> None:
        """Fired trigger message is advisory only -- no auto-action language."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=True),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "No automatic action" in msg or "Decision 55" in msg


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------


class TestNormalizePkg:
    def test_lowercases(self) -> None:
        assert _normalize_pkg("Requests") == "requests"

    def test_replaces_hyphens(self) -> None:
        assert _normalize_pkg("import-linter") == "import_linter"

    def test_replaces_dots(self) -> None:
        assert _normalize_pkg("zope.interface") == "zope_interface"


class TestReadExecutorConcurrency:
    def test_returns_one_when_no_capabilities(self, tmp_path: Path) -> None:
        missing = tmp_path / "capabilities.yaml"
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 1

    def test_reads_concurrency_from_yaml(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "config" / "agent" / "executor"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "capabilities.yaml").write_text("concurrency: 4\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 4

    def test_defaults_to_one_on_parse_error(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "config" / "agent" / "executor"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "capabilities.yaml").write_text("not: valid: yaml: :\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 1


class TestKg13TierItemFiled:
    def test_false_when_no_roadmap(self, tmp_path: Path) -> None:
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _kg13_tier_item_filed()

    def test_true_when_id_present(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "docs" / "ROADMAP-PLATFORM.yaml"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text("tier_items:\n  - id: KG.13\n    name: foo\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert _kg13_tier_item_filed()

    def test_false_when_id_absent(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "docs" / "ROADMAP-PLATFORM.yaml"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text("tier_items:\n  - id: T3.11\n    name: foo\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _kg13_tier_item_filed()


class TestFastTierBudgetBreachOpen:
    def test_false_when_no_log(self, tmp_path: Path) -> None:
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _fast_tier_budget_breach_open()

    def test_true_when_open_budget_breach_rec(self, tmp_path: Path) -> None:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / ".recommendations-log.jsonl"
        log.write_text(
            json.dumps({"status": "open", "title": "fast tier budget breach exceeded"}) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert _fast_tier_budget_breach_open()

    def test_false_when_rec_is_closed(self, tmp_path: Path) -> None:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / ".recommendations-log.jsonl"
        log.write_text(
            json.dumps({"status": "closed", "title": "fast tier budget breach exceeded"}) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _fast_tier_budget_breach_open()
