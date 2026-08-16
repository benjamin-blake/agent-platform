"""Regression coverage for the census bucket-identity bug found in code review: every Pass 1
rejection path must land the file in EXACTLY ONE of ritual/declared/grandfathered/skipped so
`Census.bucket_identity_holds()` never fires a spurious extra failure on top of the real one.

Each case here asserts `failed` contains EXACTLY the one expected violation -- not just `any(...)`
membership -- so a future rejection path that forgets to increment a bucket fails loudly here
instead of shipping green (the gap the reviewer's Critical finding identified: no test asserted
exact failure-list shape on any rejection path)."""

from __future__ import annotations

import dataclasses

from scripts.checks.contracts import _population

from .conftest import validate_contract_drift


class TestCensusIdentityBackstop:
    def test_backstop_fires_if_the_identity_ever_breaks_again(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a, monkeypatch
    ) -> None:
        # Defensive backstop, not expected to fire in normal operation now that every rejection
        # path increments a bucket -- proven here by forcing bucket_identity_holds() to lie, so
        # the backstop's own message-append line is exercised and confirmed to work.
        monkeypatch.setattr(_population.Census, "bucket_identity_holds", lambda self: False)
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "alpha.yaml", valid_class_a())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("census" in f and "bucket identity failed" in f for f in failed), failed


class TestCensusAccountingOnEveryRejectionPath:
    def test_smuggling_rejection_is_the_only_failure(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "smug.yaml",
            "contract:\n"
            "  id: smug\n"
            "  class: D\n"
            "  contract_version: 1\n"
            "  status: ratified\n"
            "  ratified_via: t\n"
            "  subject: smug-subject\n"
            "  evaluator:\n"
            "    check: validate_placement\n"
            "fields:\n"
            "  f1:\n"
            "    type: string\n",
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 1, failed
        assert "smuggling" in failed[0]

    def test_schema_error_rejection_is_the_only_failure(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        # Valid Class D shape (class: D) but fails ContractMeta schema validation: no subject.
        write_contract(
            tmp_path,
            "bad.yaml",
            "contract:\n"
            "  id: bad\n"
            "  class: D\n"
            "  contract_version: 1\n"
            "  status: draft\n"
            "  evaluator:\n"
            "    check: validate_placement\n",
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 1, failed
        assert "schema" in failed[0]

    def test_new_file_status_active_rejection_is_the_only_failure(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "active.yaml",
            class_d_yaml(status="active", ratified_via=None, evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 1, failed
        assert "status: active" in failed[0]

    def test_census_line_carries_no_evaluator_none_grandfathered_field(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a, capsys
    ) -> None:
        # rec-3059 wave 2: the retired evaluator_none_grandfathered bucket must not survive in
        # either the Census dataclass's own field set or the printed census line.
        assert "evaluator_none_grandfathered" not in {f.name for f in dataclasses.fields(_population.Census)}
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "alpha.yaml", valid_class_a())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        printed = capsys.readouterr().out
        assert "evaluator_none_grandfathered" not in printed

    def test_evaluator_does_not_resolve_rejection_is_the_only_failure(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "unresolved.yaml",
            class_d_yaml(evaluator={"check": "validate_placement"}),  # basename never mentioned
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 1, failed
        assert "evaluator" in failed[0]

    def test_new_unshaped_file_rejection_is_the_only_failure(
        self, tmp_path, install_fake_git, write_contract, FakeGit
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "freeform.yaml", "some_key: value\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 1, failed
        assert "no ritual" in failed[0]

    def test_census_never_fires_alongside_any_single_rejection(
        self, tmp_path, install_fake_git, write_contract, FakeGit
    ) -> None:
        # Multiple distinct rejection shapes in one run -- each contributes exactly one failure,
        # and the census identity holds throughout (no aggregate spurious entry either).
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "freeform.yaml", "some_key: value\n")
        write_contract(
            tmp_path,
            "smug.yaml",
            "contract:\n"
            "  id: smug2\n"
            "  class: D\n"
            "  contract_version: 1\n"
            "  status: ratified\n"
            "  ratified_via: t\n"
            "  subject: smug2-subject\n"
            "  evaluator:\n"
            "    check: validate_placement\n"
            "verbs:\n"
            "  v1:\n"
            "    payload_schema_ref: x\n",
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert len(failed) == 2, failed
        assert not any("census" in f for f in failed), failed
