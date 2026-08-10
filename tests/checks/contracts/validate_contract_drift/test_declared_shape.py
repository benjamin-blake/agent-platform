"""VP step 1: a NEW file with neither a ritual nor a valid Class D shape must fail, naming the
file and the missing shape; the baseline-present twin passes as grandfathered."""

from __future__ import annotations

from .conftest import validate_contract_drift


class TestDeclaredShapeObligation:
    def test_new_file_with_neither_shape_fails_naming_file_and_shape(
        self, tmp_path, install_fake_git, write_contract, FakeGit
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "freeform.yaml", "some_key: some_value\nanother: 1\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        matches = [f for f in failed if "freeform.yaml" in f]
        assert matches, failed
        assert any("no ritual" in f and "no valid Class D shape" in f for f in matches)

    def test_baseline_present_freeform_file_is_grandfathered(
        self, tmp_path, install_fake_git, write_contract, FakeGit
    ) -> None:
        text = "some_key: some_value\nanother: 1\n"
        write_contract(tmp_path, "freeform.yaml", text)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/freeform.yaml"],
                show_map={"docs/contracts/freeform.yaml": text},
                batch_map={},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_malformed_class_value_on_new_file_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "badclass.yaml", "contract:\n  id: bad\n  class: Q\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("badclass.yaml" in f and "no valid Class D shape" in f for f in failed)

    def test_unreachable_origin_main_skips_declared_shape_new_check(self, tmp_path, install_fake_git, write_contract) -> None:
        import subprocess

        def _unreachable(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        install_fake_git(_unreachable)
        write_contract(tmp_path, "freeform.yaml", "some_key: some_value\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []
