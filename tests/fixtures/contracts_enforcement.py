"""Shared test doubles for the tests/contracts_enforcement/ concern-split package (rec-2709 Wave 11).

Cross-module shared helper hoisted out of the former tests/test_contracts_enforcement.py monolith:
_make_class_a_doc, used by both test_contract_checks.py and test_provisional_triggers.py. An
importable tests/fixtures/ module -- exempt from the no-cross-test-import guard because its name
does not start with test_ (tests/CLAUDE.md).
"""

from __future__ import annotations

from scripts.contracts_schema import (
    AmendmentLogEntry,
    ContractClass,
    ContractDocument,
    ContractMeta,
    ContractStatus,
    FieldSpec,
)


def _make_class_a_doc(
    *,
    contract_id: str = "test-a",
    status: ContractStatus = ContractStatus.draft,
    description: str | None = "A contract",
    fields: dict | None = None,
    amendment_log: list[AmendmentLogEntry] | None = None,
    ratified_via: str | None = None,
) -> ContractDocument:
    """Build a minimal Class A ContractDocument for testing.

    ratified_via defaults to a placeholder whenever status is ratified (contracts-first-class-
    migration: ContractMeta now requires ratified_via for any ratified status) -- callers testing
    the missing-ratified_via case pass ratified_via=None explicitly alongside status=ratified.
    """
    if fields is None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
    if status is ContractStatus.ratified and ratified_via is None:
        ratified_via = "test-decision"
    return ContractDocument(
        contract=ContractMeta(
            id=contract_id,
            **{"class": ContractClass.A},
            contract_version=1,
            status=status,
            description=description,
            ratified_via=ratified_via,
        ),
        fields=fields,
        amendment_log=amendment_log,
    )
