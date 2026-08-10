"""Class A/B/C ritual-contract categories 1-8 (CD.25, T-1.12 subset e), migrated verbatim in
spirit from the pre-decomposition tests/checks/contracts/test_validate_contract_drift.py
monolith (T2.56 concern-split, Decision 128).

Pass 2 (diff-aware categories 6 and 7) shells out to git; those tests inject a fake `run` so
the base contract content is supplied deterministically without touching the real repo history.
Pass-1-only tests set merge_base_rc=1 so Pass 2 is skipped (fail-open) and the assertion
isolates the structural category under test.
"""

from __future__ import annotations

import textwrap

from .conftest import validate_contract_drift


# --------------------------------------------------------------------------------------
# Category 1 -- malformed YAML / schema violation
# --------------------------------------------------------------------------------------
class TestCategory1Malformed:
    def test_genuinely_unparseable_yaml_is_surfaced(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "broken.yaml", "contract:\n  id: broken\n  class: A\n  fields: {unclosed: [\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("broken.yaml" in f for f in failed)
        assert any("cat-1" in f for f in failed)

    def test_top_level_non_mapping_is_surfaced(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "listy.yaml", "- just\n- a\n- list\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("listy.yaml" in f and "not a YAML mapping" in f for f in failed)

    def test_schema_violation_is_surfaced(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = "contract:\n  id: nov\n  class: A\n  status: draft\nfields:\n  f1:\n    type: string\n"
        write_contract(tmp_path, "noversion.yaml", text)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("noversion.yaml" in f and "structural" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 2 -- inline Class-A field missing a required descriptive key
# --------------------------------------------------------------------------------------
class TestCategory2RequiredInlineFields:
    def test_inline_field_missing_dq_intent_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat2
              class: A
              contract_version: 1
              status: draft
              description: Cat2
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
            """
        ).strip()
        write_contract(tmp_path, "cat2.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat2.yaml" in f and "dq_intent" in f and "category 2" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 3 -- $ref to a non-existent target file
# --------------------------------------------------------------------------------------
class TestCategory3DanglingRef:
    def test_ref_to_missing_file_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat3
              class: A
              contract_version: 1
              status: draft
              description: Cat3
            fields:
              f1:
                $ref: nonexistent.yaml#/contract/fields/x
            """
        ).strip()
        write_contract(tmp_path, "cat3.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat3.yaml" in f and "ref" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 4 -- $ref chain depth > 1 (a Class A ref to a Class C field that is itself a $ref)
# --------------------------------------------------------------------------------------
class TestCategory4ChainDepth:
    def test_chained_ref_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(
            tmp_path,
            "classc2.yaml",
            textwrap.dedent(
                """
                contract:
                  id: classc2
                  class: C
                  contract_version: 1
                  status: draft
                fields:
                  deep:
                    type: string
                    nullable: false
                    description: Deep field
                    semantics: Deep meaning
                    populated_by: writer
                    dq_intent:
                      not_null:
                        enforced: true
                """
            ).strip()
            + "\n",
        )
        write_contract(
            tmp_path,
            "classc.yaml",
            textwrap.dedent(
                """
                contract:
                  id: classc
                  class: C
                  contract_version: 1
                  status: draft
                fields:
                  shared:
                    $ref: classc2.yaml#/contract/fields/deep
                """
            ).strip()
            + "\n",
        )
        write_contract(
            tmp_path,
            "cat4.yaml",
            textwrap.dedent(
                """
                contract:
                  id: cat4
                  class: A
                  contract_version: 1
                  status: draft
                  description: Cat4
                fields:
                  f1:
                    $ref: classc.yaml#/contract/fields/shared
                """
            ).strip()
            + "\n",
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat4.yaml" in f and "chain" in f.lower() for f in failed)
        assert not any("classc.yaml" in f for f in failed)
        assert not any("classc2.yaml" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 5 -- duplicate inline definition alongside a $ref
# --------------------------------------------------------------------------------------
class TestCategory5DuplicateInline:
    def test_inline_alongside_ref_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat5
              class: A
              contract_version: 1
              status: draft
              description: Cat5
            fields:
              f1:
                $ref: whatever.yaml#/contract/fields/x
                type: string
            """
        ).strip()
        write_contract(tmp_path, "cat5.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat5.yaml" in f and "duplicate" in f.lower() for f in failed)


# --------------------------------------------------------------------------------------
# Category 6 -- description/semantics change without an amendment_log entry (Pass 2)
# --------------------------------------------------------------------------------------
class TestCategory6AmendmentLog:
    def test_description_change_without_amendment_rejected(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a
    ) -> None:
        head = valid_class_a(contract_id="cat6", description="New contract description")
        base = valid_class_a(contract_id="cat6", description="Old contract description")
        write_contract(tmp_path, "cat6.yaml", head)
        install_fake_git(
            FakeGit(merge_base_rc=0, changed=["docs/contracts/cat6.yaml"], show_map={"docs/contracts/cat6.yaml": base})
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat6.yaml" in f and "category 6" in f for f in failed)

    def test_base_show_failure_fails_open(self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a) -> None:
        head = valid_class_a(contract_id="cat6", description="New contract description")
        write_contract(tmp_path, "cat6.yaml", head)
        install_fake_git(FakeGit(merge_base_rc=0, changed=["docs/contracts/cat6.yaml"], show_map={}))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_unparseable_base_fails_open(self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a) -> None:
        head = valid_class_a(contract_id="cat6", description="New contract description")
        write_contract(tmp_path, "cat6.yaml", head)
        install_fake_git(
            FakeGit(
                merge_base_rc=0,
                changed=["docs/contracts/cat6.yaml"],
                show_map={"docs/contracts/cat6.yaml": "{bad: [unclosed"},
            )
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []


# --------------------------------------------------------------------------------------
# Category 7 -- forbidden status transition (Pass 2)
# --------------------------------------------------------------------------------------
class TestCategory7StatusTransition:
    def test_forbidden_transition_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a) -> None:
        head = valid_class_a(contract_id="cat7", status="deprecated")
        base = valid_class_a(contract_id="cat7", status="draft")
        write_contract(tmp_path, "cat7.yaml", head)
        install_fake_git(
            FakeGit(merge_base_rc=0, changed=["docs/contracts/cat7.yaml"], show_map={"docs/contracts/cat7.yaml": base})
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat7.yaml" in f and "category 7" in f for f in failed)
        assert not any("category 6" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 8 -- amendment_log change_class outside the closed vocabulary
# --------------------------------------------------------------------------------------
class TestCategory8BadChangeClass:
    def test_out_of_vocab_change_class_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat8
              class: A
              contract_version: 1
              status: draft
              description: Cat8
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
                dq_intent:
                  not_null:
                    enforced: true
            amendment_log:
              - date: "2026-01-01"
                semantic_break: false
                change_class: bogus_change_class
            """
        ).strip()
        write_contract(tmp_path, "cat8.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat8.yaml" in f and "structural" in f for f in failed)
