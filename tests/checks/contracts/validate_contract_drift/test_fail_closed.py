"""VP step 10: fail-closed hardening and the loud advisory-skip."""

from __future__ import annotations

from .conftest import validate_contract_drift


class TestFailClosed:
    def test_missing_docs_contracts_directory_fails(self, tmp_path) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path / "does_not_exist")
        assert failed != []
        assert any("does not exist" in f for f in failed)

    def test_non_utf8_file_is_a_cat1_defect_not_a_traceback(self, tmp_path, install_fake_git, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        (tmp_path / "badenc.yaml").write_bytes(b"contract:\n  id: \xff\xfe bad bytes\n")
        failed: list[str] = []
        # Must not raise -- a raised UnicodeDecodeError here would be the exact defect this
        # step exists to close.
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("badenc.yaml" in f and "cat-1" in f for f in failed), failed

    def test_origin_main_unreachable_advisory_skips_without_failing(
        self, tmp_path, install_fake_git, write_contract, class_d_yaml, capsys
    ) -> None:
        import subprocess

        def _unreachable(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        install_fake_git(_unreachable)
        write_contract(
            tmp_path,
            "self.yaml",
            class_d_yaml(contract_id="self", subject="self-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        # Must NOT fail merely because origin/main is unreachable.
        assert not any("fail-closed" in f for f in failed), failed
        out = capsys.readouterr().out
        assert "advisory-SKIP" in out
        assert "Census:" in out  # uniqueness/shape/evaluator resolution and the census still run
