"""VP step 4: Class-A AND Class-B smuggling detection, by literal name and by shape."""

from __future__ import annotations

from .conftest import validate_contract_drift


def _write_d_body(write_contract, tmp_path, name: str, extra_yaml: str) -> None:
    text = (
        "contract:\n"
        "  id: smug\n"
        "  class: D\n"
        "  contract_version: 1\n"
        "  status: ratified\n"
        "  ratified_via: test\n"
        "  subject: smug-subject\n"
        "  evaluator:\n"
        "    check: validate_placement\n"
        f"{extra_yaml}"
    )
    write_contract(tmp_path, name, text)


class TestSmuggling:
    def test_literal_fields_key_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        _write_d_body(write_contract, tmp_path, "smug1.yaml", "fields:\n  f1:\n    type: string\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("smug1.yaml" in f and "smuggling" in f for f in failed), failed

    def test_literal_verbs_key_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        _write_d_body(write_contract, tmp_path, "smug2.yaml", "verbs:\n  v1:\n    payload_schema_ref: x\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("smug2.yaml" in f and "smuggling" in f for f in failed), failed

    def test_field_shaped_renamed_key_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        extra = (
            "columns:\n"
            "  c1:\n"
            "    type: string\n"
            "    nullable: false\n"
            "    description: A column\n"
            "  c2:\n"
            "    type: int\n"
            "    nullable: true\n"
            "    description: Another\n"
        )
        _write_d_body(write_contract, tmp_path, "smug3.yaml", extra)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("smug3.yaml" in f and "smuggling" in f and "field-shaped" in f for f in failed), failed

    def test_verb_shaped_renamed_key_fails(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        extra = (
            "operations:\n"
            "  op1:\n"
            "    payload_schema_ref: foo.yaml#/x\n"
            "    response_codes:\n"
            "      200: ok\n"
            "  op2:\n"
            "    payload_schema_ref: bar.yaml#/y\n"
            "    typed_errors:\n"
            "      NotFound: does not exist\n"
        )
        _write_d_body(write_contract, tmp_path, "smug4.yaml", extra)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("smug4.yaml" in f and "smuggling" in f and "verb-shaped" in f for f in failed), failed

    def test_genuine_heterogeneous_mechanism_body_passes(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=0, merge_base="BASE0000", ls_tree=[]))
        extra = (
            "shape_grammar:\n"
            "  declared_shape_obligation: a prose description of the rule\n"
            "  extension_and_depth: another prose description\n"
            "ratchet:\n"
            "  grandfathered_max: 0\n"
        )
        _write_d_body(write_contract, tmp_path, "smug5.yaml", extra)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert not any("smug5.yaml" in f and "smuggling" in f for f in failed), failed
