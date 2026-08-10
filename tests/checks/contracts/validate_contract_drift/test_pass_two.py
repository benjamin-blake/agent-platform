"""VP step 7: Pass 2 -- amendment log, the three-way base resolution union, and conformance
loss."""

from __future__ import annotations

import pytest

from scripts.checks.contracts import _population

from .conftest import validate_contract_drift


@pytest.fixture(autouse=True)
def _resolving_evaluator(monkeypatch):
    monkeypatch.setattr(_population, "resolve_evaluator", lambda *a, **k: (True, "bypassed for this test module"))


class TestPassTwo:
    def test_content_change_without_amendment_entry_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        base = class_d_yaml(contract_id="amend", subject="amend-subject", extra={"note": "old"})
        head = class_d_yaml(contract_id="amend", subject="amend-subject", extra={"note": "new"})
        write_contract(tmp_path, "amend.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/amend.yaml"],
                changed=["docs/contracts/amend.yaml"],
                show_map={"docs/contracts/amend.yaml": base},
                batch_map={"docs/contracts/amend.yaml": base},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("amend.yaml" in f and "amendment" in f for f in failed), failed

    def test_comment_only_edit_passes(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        base = class_d_yaml(contract_id="comm", subject="comm-subject", evaluator={"check": "validate_placement"})
        head = "# just a comment\n" + base
        write_contract(tmp_path, "comm.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/comm.yaml"],
                changed=["docs/contracts/comm.yaml"],
                show_map={"docs/contracts/comm.yaml": base},
                batch_map={"docs/contracts/comm.yaml": base},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == [], failed

    def test_rename_still_resolves_base_and_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        base = class_d_yaml(contract_id="ren", subject="ren-subject", extra={"note": "old"})
        head = class_d_yaml(contract_id="ren", subject="ren-subject", extra={"note": "new"})
        write_contract(tmp_path, "renamed.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/old.yaml"],
                changed=["docs/contracts/renamed.yaml"],
                show_map={"docs/contracts/old.yaml": base},
                renames={"docs/contracts/renamed.yaml": "docs/contracts/old.yaml"},
                batch_map={},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("renamed.yaml" in f and "amendment" in f for f in failed), failed

    def test_edited_contract_id_still_resolves_base_via_path_and_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        base = class_d_yaml(contract_id="old-id", subject="idedit-subject", extra={"note": "old"})
        head = class_d_yaml(contract_id="new-id", subject="idedit-subject", extra={"note": "new"})
        write_contract(tmp_path, "idedit.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/idedit.yaml"],
                changed=["docs/contracts/idedit.yaml"],
                show_map={"docs/contracts/idedit.yaml": base},
                batch_map={"docs/contracts/idedit.yaml": base},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("idedit.yaml" in f and "amendment" in f for f in failed), failed

    def test_id_match_across_a_rewrite_past_the_rename_threshold_still_resolves_and_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        base = class_d_yaml(contract_id="shared-id", subject="idmatch-subject", extra={"note": "old"})
        head = class_d_yaml(contract_id="shared-id", subject="idmatch-subject", extra={"note": "totally rewritten"})
        write_contract(tmp_path, "idmatch.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/original.yaml"],
                changed=["docs/contracts/idmatch.yaml"],
                show_map={"docs/contracts/original.yaml": base},
                renames={},  # git -M did NOT detect a rename (past its similarity threshold)
                batch_map={"docs/contracts/original.yaml": base},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("idmatch.yaml" in f and "amendment" in f for f in failed), failed

    def test_conformance_loss_when_head_deletes_the_contract_block(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        base = class_d_yaml(contract_id="cl", subject="cl-subject")
        head = "not_a_contract_anymore: true\n"
        write_contract(tmp_path, "cl.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                merge_base="BASE0000",
                ls_tree=["docs/contracts/cl.yaml"],
                changed=["docs/contracts/cl.yaml"],
                show_map={"docs/contracts/cl.yaml": base},
                batch_map={"docs/contracts/cl.yaml": base},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cl.yaml" in f and "conformance-loss" in f for f in failed), failed
