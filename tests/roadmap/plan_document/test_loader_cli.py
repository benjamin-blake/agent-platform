"""Tests for scripts/roadmap/plan_document.py -- file loading, CLI, and validate_plan_documents
integration, covering the T1.11 exit criteria.

Split from the former tests/test_plan_document.py monolith (PLAN-decompose-test-plan-document,
Decision 128 decompose-by-default): TestLoader, TestCli, TestValidateIntegration relocated
verbatim.
"""

from __future__ import annotations

import shutil

import pytest
from pydantic import ValidationError

from scripts.checks.roadmap.validate_plan_documents import validate_plan_documents
from scripts.roadmap.plan_document import load, main, validate_paths
from tests.fixtures.plan_document_helpers import FIXTURES


class TestLoader:
    def test_load_valid_file(self, tmp_path):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        doc = load(target)
        assert doc.slug == "zz-valid-demo"

    def test_load_malformed_fixture_fails_on_command(self, tmp_path):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        with pytest.raises(ValidationError, match="non-empty executable command"):
            load(target)

    def test_filename_slug_guard(self, tmp_path):
        target = tmp_path / "PLAN-wrong-name.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        with pytest.raises(ValueError, match="does not match slug"):
            load(target)

    def test_validate_paths_reports_failures(self, tmp_path):
        good = tmp_path / "PLAN-zz-valid-demo.yaml"
        bad = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", good)
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", bad)
        failures = validate_paths([good, bad])
        assert len(failures) == 1
        assert failures[0][0] == bad


class TestCli:
    def test_main_pass_on_valid(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        assert main([str(target)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_main_fail_on_malformed(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        assert main([str(target)]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_main_default_glob_empty_dir(self, tmp_path, capsys):
        assert main([], plans_root=tmp_path) == 0
        assert "no PLAN-*.yaml files found" in capsys.readouterr().out

    def test_main_default_glob_finds_files(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        assert main([], plans_root=tmp_path) == 0
        assert "PASS" in capsys.readouterr().out


class TestValidateIntegration:
    def test_validate_plan_documents_passes_on_valid_dir(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-valid-demo.yaml"
        shutil.copy(FIXTURES / "valid.yaml", target)
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert failed == []
        assert "PASS" in capsys.readouterr().out

    def test_validate_plan_documents_fails_on_malformed(self, tmp_path, capsys):
        target = tmp_path / "PLAN-zz-malformed-demo.yaml"
        shutil.copy(FIXTURES / "malformed_missing_command.yaml", target)
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert "Plan document schema validation" in failed
        assert "FAIL" in capsys.readouterr().out

    def test_validate_plan_documents_empty_dir_passes(self, tmp_path, capsys):
        failed: list[str] = []
        validate_plan_documents(failed, plans_dir=tmp_path)
        assert failed == []
        assert "no PLAN-*.yaml files to validate" in capsys.readouterr().out
