"""Tests for validate_tier_floor() -- T3.17 (VF-04) deterministic V-tier floor."""

from pathlib import Path
from unittest.mock import patch

import scripts.validate as _validate_module
from scripts.checks.roadmap.validate_tier_floor import validate_tier_floor


class TestValidateTierFloor:
    """T3.17 (VF-04): deterministic V-tier floor over schema_version-2 plan scope."""

    FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "plan_documents"

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
        assert validate_tier_floor is _validate_module.validate_tier_floor

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
