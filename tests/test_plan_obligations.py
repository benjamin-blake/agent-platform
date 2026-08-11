"""Tests for scripts/roadmap/plan_obligations.py (plan-obligation-closure)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.roadmap import plan_obligations


def _base_scope() -> dict:
    return {
        "schema_version": 4,
        "plan_type": "IMPLEMENTATION",
        "slug": "fixture-probe",
        "plan_path": "docs/plans/PLAN-fixture-probe.yaml",
        "scope": [
            {"file": "scripts/checks/roadmap/validate_x.py", "action": "Create", "purpose": "p"},
            {"file": "scripts/checks/roadmap/_manifest.py", "action": "Modify", "purpose": "p"},
            {"file": "config/ci_rca_taxonomy.yaml", "action": "Modify", "purpose": "p"},
            {"file": "tests/checks/roadmap/test_validate_x.py", "action": "Create", "purpose": "p"},
        ],
    }


def _write(tmp_path: Path, data: dict, name: str = "PLAN-fixture-probe.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestLoadObligationMap:
    def test_real_contract_loads(self) -> None:
        rules, error = plan_obligations.load_obligation_map()
        assert error is None
        assert rules
        assert any(rule.get("trigger") for rule in rules)

    def test_missing_contract_reports_error_never_raises(self, tmp_path: Path) -> None:
        rules, error = plan_obligations.load_obligation_map(tmp_path / "absent.yaml")
        assert rules == []
        assert error is not None and "could not read" in error

    def test_malformed_yaml_reports_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("key: [unterminated", encoding="utf-8")
        rules, error = plan_obligations.load_obligation_map(bad)
        assert rules == []
        assert error is not None and "could not parse" in error

    def test_non_mapping_top_level_reports_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("- 1\n- 2\n", encoding="utf-8")
        rules, error = plan_obligations.load_obligation_map(bad)
        assert rules == []
        assert error is not None and "not a YAML mapping" in error

    def test_missing_registration_surfaces_key_reports_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("contract:\n  id: x\n", encoding="utf-8")
        rules, error = plan_obligations.load_obligation_map(bad)
        assert rules == []
        assert error is not None and "registration_surfaces" in error


class TestEvaluatePlan:
    def test_complete_plan_zero_findings(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _base_scope())
        assert plan_obligations.evaluate_plan(path) == []

    def test_missing_manifest_entry_named_by_path(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "scripts/checks/roadmap/_manifest.py"]
        path = _write(tmp_path, data)
        findings = plan_obligations.evaluate_plan(path)
        assert any("scripts/checks/roadmap/_manifest.py" in f for f in findings)

    def test_missing_taxonomy_row_named_by_path(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "config/ci_rca_taxonomy.yaml"]
        path = _write(tmp_path, data)
        findings = plan_obligations.evaluate_plan(path)
        assert any("config/ci_rca_taxonomy.yaml" in f for f in findings)

    def test_missing_mirror_test_named_by_path(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "tests/checks/roadmap/test_validate_x.py"]
        path = _write(tmp_path, data)
        findings = plan_obligations.evaluate_plan(path)
        assert any("tests/checks/roadmap/test_validate_x.py" in f for f in findings)

    def test_sub_v4_plan_grandfathered(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["schema_version"] = 3
        data["scope"] = [{"file": "scripts/checks/roadmap/validate_y.py", "action": "Create", "purpose": "p"}]
        path = _write(tmp_path, data)
        assert plan_obligations.evaluate_plan(path) == []

    def test_non_implementation_plan_grandfathered(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["plan_type"] = "STRATEGIC"
        data["scope"] = [{"file": "scripts/checks/roadmap/validate_y.py", "action": "Create", "purpose": "p"}]
        path = _write(tmp_path, data)
        assert plan_obligations.evaluate_plan(path) == []

    def test_absent_file_reports_finding_never_raises(self, tmp_path: Path) -> None:
        findings = plan_obligations.evaluate_plan(tmp_path / "PLAN-absent.yaml")
        assert findings and "could not read" in findings[0]

    def test_malformed_yaml_reports_finding_never_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "PLAN-bad.yaml"
        bad.write_text("key: [unterminated", encoding="utf-8")
        findings = plan_obligations.evaluate_plan(bad)
        assert findings and "could not parse" in findings[0]

    def test_non_mapping_plan_reports_finding_never_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "PLAN-bad.yaml"
        bad.write_text("- 1\n- 2\n", encoding="utf-8")
        findings = plan_obligations.evaluate_plan(bad)
        assert findings and "not a YAML mapping" in findings[0]

    def test_malformed_contract_surfaces_as_finding_never_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _base_scope())
        with patch.object(plan_obligations, "_CONTRACT_PATH", tmp_path / "absent-contract.yaml"):
            findings = plan_obligations.evaluate_plan(path)
        assert findings and "could not read" in findings[0]

    def test_action_gate_ignores_modify_of_check_module_pattern(self, tmp_path: Path) -> None:
        """A Modify (not Create) row matching the trigger pattern never obligates companions."""
        data = _base_scope()
        data["scope"] = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Modify", "purpose": "p"}]
        path = _write(tmp_path, data)
        assert plan_obligations.evaluate_plan(path) == []


class TestDeriveFindingsEdgeCases:
    """Direct coverage of _derive_findings/_scope_rows' malformed-rule defensive branches --
    a malformed docs/contracts/plan-obligations.yaml entry must be skipped, never raise."""

    def test_scope_rows_non_list_scope_returns_empty(self) -> None:
        assert plan_obligations._scope_rows({"scope": "not-a-list"}) == []

    def test_rule_with_non_dict_trigger_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [{"trigger": "not-a-dict", "requires": []}]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_rule_with_empty_file_pattern_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [{"trigger": {"file_pattern": ""}, "requires": []}]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_rule_with_invalid_regex_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [{"trigger": {"file_pattern": "("}, "requires": []}]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_rule_with_non_list_requires_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [{"trigger": {"file_pattern": r"^scripts/checks/(?P<domain>[^/]+)/.*\.py$"}, "requires": "not-a-list"}]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_non_dict_requirement_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [{"trigger": {"file_pattern": r"^scripts/checks/(?P<domain>[^/]+)/.*\.py$"}, "requires": ["not-a-dict"]}]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_requirement_with_empty_path_template_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [
            {
                "trigger": {"file_pattern": r"^scripts/checks/(?P<domain>[^/]+)/.*\.py$"},
                "requires": [{"label": "x", "path_template": ""}],
            }
        ]
        assert plan_obligations._derive_findings(scope, rules) == []

    def test_requirement_with_unresolvable_template_group_skipped(self) -> None:
        scope = [{"file": "scripts/checks/roadmap/validate_x.py", "action": "Create"}]
        rules = [
            {
                "trigger": {"file_pattern": r"^scripts/checks/(?P<domain>[^/]+)/.*\.py$"},
                "requires": [{"label": "x", "path_template": "{undeclared_group}/foo.py"}],
            }
        ]
        assert plan_obligations._derive_findings(scope, rules) == []


class TestNetNewV4ImplementationPlanPaths:
    def test_never_globs_docs_plans(self) -> None:
        with patch.object(plan_obligations._common, "get_status_aware_diff", return_value=[]) as mock_diff:
            with patch.object(Path, "glob") as mock_glob:
                assert plan_obligations.net_new_v4_implementation_plan_paths() == []
                mock_glob.assert_not_called()
        mock_diff.assert_called_once()

    def test_filters_to_added_v4_implementation_plans(self, tmp_path: Path) -> None:
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        good = plans_dir / "PLAN-fixture-probe.yaml"
        good.write_text(yaml.safe_dump(_base_scope()), encoding="utf-8")
        legacy_data = _base_scope()
        legacy_data["schema_version"] = 3
        legacy_data["slug"] = "legacy"
        legacy_data["plan_path"] = "docs/plans/PLAN-legacy.yaml"
        (plans_dir / "PLAN-legacy.yaml").write_text(yaml.safe_dump(legacy_data), encoding="utf-8")
        diff = [
            ("A", "docs/plans/PLAN-fixture-probe.yaml"),
            ("A", "docs/plans/PLAN-legacy.yaml"),
            ("M", "docs/plans/PLAN-modified-not-added.yaml"),
        ]
        with patch.object(plan_obligations._common, "get_status_aware_diff", return_value=diff):
            with patch.object(plan_obligations, "ROOT", tmp_path):
                paths = plan_obligations.net_new_v4_implementation_plan_paths()
        assert paths == [good]

    def test_absent_or_malformed_diff_entry_never_raises(self) -> None:
        diff = [("A", "docs/plans/PLAN-does-not-exist.yaml")]
        with patch.object(plan_obligations._common, "get_status_aware_diff", return_value=diff):
            assert plan_obligations.net_new_v4_implementation_plan_paths() == []

    def test_non_added_status_skipped(self) -> None:
        diff = [("M", "docs/plans/PLAN-plan-obligation-closure.yaml")]
        with patch.object(plan_obligations._common, "get_status_aware_diff", return_value=diff):
            assert plan_obligations.net_new_v4_implementation_plan_paths() == []

    def test_non_plan_path_skipped(self) -> None:
        diff = [("A", "docs/plans/README.md")]
        with patch.object(plan_obligations._common, "get_status_aware_diff", return_value=diff):
            assert plan_obligations.net_new_v4_implementation_plan_paths() == []


class TestBuildReport:
    def test_complete_plan_reports_no_findings(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _base_scope())
        report = plan_obligations.build_report(path)
        assert "no unmet registration obligations" in report

    def test_incomplete_plan_reports_each_finding(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "config/ci_rca_taxonomy.yaml"]
        path = _write(tmp_path, data)
        report = plan_obligations.build_report(path)
        assert "config/ci_rca_taxonomy.yaml" in report


class TestMainCli:
    def test_cli_always_exits_zero_on_unmet_obligations(self, tmp_path: Path) -> None:
        data = _base_scope()
        data["scope"] = [r for r in data["scope"] if r["file"] != "config/ci_rca_taxonomy.yaml"]
        path = _write(tmp_path, data)
        assert plan_obligations.main(["--plan", str(path)]) == 0

    def test_cli_always_exits_zero_on_absent_plan(self, tmp_path: Path) -> None:
        assert plan_obligations.main(["--plan", str(tmp_path / "PLAN-absent.yaml")]) == 0

    def test_cli_subprocess_never_mutates_tree(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", cwd=plan_obligations.ROOT
        ).stdout
        rc = subprocess.run(
            [
                "bin/venv-python",
                "-m",
                "scripts.roadmap.plan_obligations",
                "--plan",
                "docs/plans/PLAN-plan-obligation-closure.yaml",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=plan_obligations.ROOT,
        ).returncode
        after = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", cwd=plan_obligations.ROOT
        ).stdout
        assert rc == 0
        assert before == after
