"""VP step 5: extension, depth and case conformance, including the pre-authorised .md path."""

from __future__ import annotations

from scripts.checks.contracts import _population

from .conftest import validate_contract_drift


class TestExtensionDepth:
    def test_new_yml_extension_is_governed(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        # "governed" means SCANNED and subject to the declared-shape rules -- not silently
        # ignored for its extension the way a .md or nested file is (see the other tests below).
        # The evaluator here deliberately does not resolve (an unrelated concern, VP step 2), so
        # the file is expected to fail -- but on an (evaluator) tag, never an (extension) tag,
        # proving it was scanned and shape-classified rather than skipped.
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "governed.yml",
            class_d_yaml(contract_id="yml1", subject="yml1-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert not any("extension" in f and "governed.yml" in f for f in failed), failed
        assert any("evaluator" in f and "governed.yml" in f for f in failed), failed

    def test_new_md_file_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "new-doc.md", "# Just prose\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("new-doc.md" in f and "extension" in f for f in failed), failed

    def test_new_nested_yaml_fails(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        (tmp_path / "sub").mkdir()
        write_contract(
            tmp_path / "sub",
            "nested.yaml",
            class_d_yaml(contract_id="nested", subject="nested-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("sub/nested.yaml" in f and "extension" in f for f in failed), failed

    def test_single_baseline_md_member_passes_as_grandfathered(
        self, tmp_path, install_fake_git, write_contract, FakeGit
    ) -> None:
        """The environment-taxonomy markdown contract was converted to the declared Class D contract
        environment-taxonomy.yaml (CFG-11 conversion) -- delegate-cli.md is now the sole
        remaining baseline-present grandfathered .md member."""
        write_contract(tmp_path, "delegate-cli.md", "# delegate cli\n")
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/delegate-cli.md"],
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed

    def test_case_variation_is_not_governed(self) -> None:
        assert _population.is_governed_extension_depth("foo.yaml")
        assert _population.is_governed_extension_depth("foo.yml")
        assert not _population.is_governed_extension_depth("foo.YAML")
        assert not _population.is_governed_extension_depth("foo.Yaml")
        assert not _population.is_governed_extension_depth("sub/foo.yaml")
        assert not _population.is_governed_extension_depth("foo.md")

    def test_conformance_admitted_set_equals_globbed_set(self, tmp_path) -> None:
        for name in ["a.yaml", "b.yml", "c.YAML", "d.md", "e.yaml.bak"]:
            (tmp_path / name).write_text("x: 1\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "f.yaml").write_text("x: 1\n", encoding="utf-8")

        globbed = {p.name for p in [*tmp_path.glob("*.yaml"), *tmp_path.glob("*.yml")]}
        admitted = {
            f.relative_to(tmp_path).as_posix()
            for f in _population.scan_tree(tmp_path)
            if _population.is_governed_extension_depth(f.relative_to(tmp_path).as_posix())
        }
        assert admitted == globbed == {"a.yaml", "b.yml"}
