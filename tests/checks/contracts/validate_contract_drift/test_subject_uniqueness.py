"""VP step 6: subject uniqueness, per-file self-collision, and topic-equals-subject."""

from __future__ import annotations

import pytest

from scripts.checks.contracts import _population

from .conftest import validate_contract_drift


@pytest.fixture(autouse=True)
def _resolving_evaluator(monkeypatch):
    """Subject uniqueness is orthogonal to evaluator resolution (VP step 2's own concern) --
    bypass resolution here so a synthetic fixture's evaluator {check: validate_placement} always
    resolves regardless of the fixture's own (arbitrary) basename."""
    monkeypatch.setattr(_population, "resolve_evaluator", lambda *a, **k: (True, "bypassed for this test module"))


class TestSubjectUniqueness:
    def test_two_files_sharing_a_subject_fail(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            tmp_path,
            "one.yaml",
            class_d_yaml(contract_id="one", subject="shared-subject", evaluator={"check": "validate_placement"}),
        )
        write_contract(
            tmp_path,
            "two.yaml",
            class_d_yaml(contract_id="two", subject="shared-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("subject" in f and "shared-subject" in f and "duplicates" in f for f in failed), failed

    def test_subject_colliding_with_ritual_id_fails(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a, class_d_yaml
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(tmp_path, "ritual.yaml", valid_class_a(contract_id="ritual-id"))
        write_contract(
            tmp_path,
            "clash.yaml",
            class_d_yaml(contract_id="clash", subject="ritual-id", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("clash.yaml" in f and "subject" in f and "collides" in f for f in failed), failed

    def test_ritual_contract_declaring_its_own_id_passes(self) -> None:
        # A guard against a self-collision false positive in the union-building step -- ritual
        # ids only seed the namespace here and are never cross-checked against each other.
        errors = _population.check_subject_uniqueness(
            class_d_subjects={},
            ritual_ids={"a.yaml": "same-id", "b.yaml": "same-id"},
        )
        assert errors == []

    def test_self_collision_never_flagged(self) -> None:
        errors = _population.check_subject_uniqueness(
            class_d_subjects={"solo.yaml": "solo-subject"},
            ritual_ids={"solo.yaml": "solo-subject"},
        )
        assert errors == []

    def test_topic_differs_from_subject_fails(self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml) -> None:
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        router_path = tmp_path / "file-router.yaml"
        router_path.write_text(
            "routes:\n  - topic: mismatched-topic\n    targets: [docs/contracts/mismatch.yaml]\n",
            encoding="utf-8",
        )
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            contracts_dir,
            "mismatch.yaml",
            class_d_yaml(contract_id="mismatch", subject="actual-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=contracts_dir, router_path=router_path)
        assert any("mismatch.yaml" in f and "subject" in f and "differs from" in f for f in failed), failed

    def test_matching_topic_and_subject_passes(
        self, tmp_path, install_fake_git, write_contract, FakeGit, class_d_yaml
    ) -> None:
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        router_path = tmp_path / "file-router.yaml"
        router_path.write_text(
            "routes:\n  - topic: matched-subject\n    targets: [docs/contracts/matched.yaml]\n",
            encoding="utf-8",
        )
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        write_contract(
            contracts_dir,
            "matched.yaml",
            class_d_yaml(contract_id="matched", subject="matched-subject", evaluator={"check": "validate_placement"}),
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=contracts_dir, router_path=router_path)
        assert not any("subject" in f for f in failed), failed
