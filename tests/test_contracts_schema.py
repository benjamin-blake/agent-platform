"""Unit tests for scripts/contracts_schema.py -- the ritual contract Pydantic schema.

Hermetic: every fixture is constructed in-test (no committed fixture files, no sockets, no
shared module-level state). Compatible with pytest-socket / pytest-randomly (T3.6).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.contracts_schema import (
    AmendmentLogEntry,
    ChangeClass,
    ContractClass,
    ContractDocument,
    ContractGovernance,
    ContractMeta,
    ContractStatus,
    FieldSpec,
    VerbSpec,
)


def _class_a_doc() -> dict:
    return {
        "contract": {
            "id": "ops_recommendations",
            "class": "A",
            "contract_version": 1,
            "status": "ratified",
            "ratified_at": "2026-05-21",
            "description": "Class A contract for ops_recommendations.",
            "projects_to": {"pydantic_model": "src/schemas/rec.py::RecPayload"},
            "governance": {
                "table_class": "SCD2_append_only",
                "partition_by": "day(last_updated_timestamp)",
                "dedup_view": "ops_recommendations_current",
            },
            "amendment_policy": {"default": "forward_compat_only"},
        },
        "fields": {
            "id": {
                "type": "str",
                "iceberg_type": "string",
                "nullable": False,
                "description": "Recommendation id.",
                "semantics": "DynamoDB-allocated; SCD2.",
                "dq_intent": {"not_null": {"enforced": True}},
                "governance_notes": "Immutable once written.",
                "amendment_log": [],
            },
            "source": {
                "$ref": "docs/contracts/source-lineage.yaml#/contract/fields/registry_key",
                "dq_intent_local": {"not_null": {"enforced": True, "write_time": True}},
                "joins": ["lineage_join_source_to_agent_type"],
                "amendment_log": [],
            },
        },
        "previous_versions": [],
    }


def _class_b_doc() -> dict:
    return {
        "contract": {
            "id": "lambda-log-rec",
            "class": "B",
            "contract_version": 1,
            "status": "provisional_v0",
            "ratified_at": "2026-05-21",
            "description": "Verb contract for the log-rec Lambda.",
            "governance": {"auth_type": "AWS_IAM", "principal_classes": ["PlatformDev"]},
        },
        "verbs": {
            "POST": {
                "payload_schema_ref": "docs/contracts/ops_recommendations.yaml::contract",
                "response_codes": {200: "ok", 400: "validation error"},
                "typed_errors": {"VALIDATION_ERROR": "payload failed validation"},
            }
        },
        "audit_invariants": ["Every successful write emits a structured log line."],
        "amendment_log": [],
        "previous_versions": [],
    }


def _class_c_doc() -> dict:
    return {
        "contract": {
            "id": "source-lineage",
            "class": "C",
            "contract_version": 1,
            "status": "ratified",
            "description": "Canonical source lineage key contract.",
        },
        "governance": {
            "registry_path": "config/agent/data_quality/source_registry.yaml",
            "validation_path": "scripts/ops_data_portal.py",
            "human_initiated_value": "manual",
        },
        "joins_using_this_key": ["lineage_join_source_to_agent_type"],
        "governance_notes": "Graduated from routing-enum to lineage-key 2026-05-06.",
        "amendment_log": [
            {
                "date": "2026-05-06",
                "semantic_break": True,
                "change_class": "accepted_values_extend",
                "migration_story": "No backfill; filter on created_timestamp.",
            }
        ],
        "previous_versions": [],
    }


class TestValidContracts:
    def test_class_a_accepted(self) -> None:
        doc = ContractDocument.model_validate(_class_a_doc())
        assert doc.contract.class_ is ContractClass.A
        assert doc.contract.status is ContractStatus.ratified
        assert doc.fields is not None
        assert doc.fields["source"].ref is not None

    def test_class_b_accepted(self) -> None:
        doc = ContractDocument.model_validate(_class_b_doc())
        assert doc.contract.class_ is ContractClass.B
        assert doc.verbs is not None
        assert doc.verbs["POST"].response_codes == {200: "ok", 400: "validation error"}

    def test_class_c_accepted(self) -> None:
        doc = ContractDocument.model_validate(_class_c_doc())
        assert doc.contract.class_ is ContractClass.C
        assert doc.fields is None
        assert doc.verbs is None
        assert doc.governance is not None
        assert doc.amendment_log is not None
        assert doc.amendment_log[0].change_class is ChangeClass.accepted_values_extend

    def test_amendment_log_entry_optional_fields(self) -> None:
        entry = AmendmentLogEntry(date="2026-07-15", semantic_break=False, change_class=ChangeClass.prose_improvement)
        assert entry.summary is None
        assert entry.migration_story is None

    def test_governance_superset_model(self) -> None:
        gov = ContractGovernance(table_class="SCD2_append_only", auth_type="AWS_IAM")
        assert gov.table_class == "SCD2_append_only"
        assert gov.auth_type == "AWS_IAM"

    def test_verbspec_defaults(self) -> None:
        verb = VerbSpec()
        assert verb.payload_schema_ref is None
        assert verb.response_codes is None
        assert verb.typed_errors is None

    def test_fieldspec_ref_alias_round_trip(self) -> None:
        spec = FieldSpec.model_validate({"$ref": "docs/contracts/x.yaml#/contract/fields/y"})
        assert spec.ref == "docs/contracts/x.yaml#/contract/fields/y"
        assert spec.model_dump(by_alias=True)["$ref"] == spec.ref

    def test_contractmeta_class_alias(self) -> None:
        meta = ContractMeta.model_validate({"id": "x", "class": "A", "contract_version": 2, "status": "draft"})
        assert meta.class_ is ContractClass.A
        assert meta.contract_version == 2


class TestRejectsMalformed:
    def test_unknown_field_rejected(self) -> None:
        doc = _class_a_doc()
        doc["contract"]["unexpected_key"] = "boom"
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_unknown_top_level_field_rejected(self) -> None:
        doc = _class_a_doc()
        doc["surprise"] = True
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_missing_contract_version_rejected(self) -> None:
        doc = _class_a_doc()
        del doc["contract"]["contract_version"]
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_bad_status_rejected(self) -> None:
        doc = _class_a_doc()
        doc["contract"]["status"] = "retired"
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_bad_change_class_rejected(self) -> None:
        doc = _class_c_doc()
        doc["amendment_log"][0]["change_class"] = "vibe_shift"
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_bad_contract_class_rejected(self) -> None:
        doc = _class_a_doc()
        doc["contract"]["class"] = "D"
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_class_a_without_fields_rejected(self) -> None:
        doc = _class_a_doc()
        del doc["fields"]
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_class_a_with_verbs_rejected(self) -> None:
        doc = _class_a_doc()
        doc["verbs"] = {"POST": {}}
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_class_b_without_verbs_rejected(self) -> None:
        doc = _class_b_doc()
        del doc["verbs"]
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_class_b_with_fields_rejected(self) -> None:
        doc = _class_b_doc()
        doc["fields"] = {"x": {"type": "str"}}
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_class_c_may_own_ref_target_fields(self) -> None:
        # Class C owns canonical cross-system field definitions (Invariant 5); fields allowed.
        doc = _class_c_doc()
        doc["fields"] = {"registry_key": {"type": "str", "nullable": False}}
        validated = ContractDocument.model_validate(doc)
        assert validated.fields is not None
        assert validated.fields["registry_key"].type == "str"

    def test_class_c_with_verbs_rejected(self) -> None:
        doc = _class_c_doc()
        doc["verbs"] = {"POST": {}}
        with pytest.raises(ValidationError):
            ContractDocument.model_validate(doc)

    def test_amendment_log_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AmendmentLogEntry.model_validate(
                {"date": "2026-07-15", "semantic_break": False, "change_class": "prose_improvement", "extra": 1}
            )

    def test_fieldspec_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FieldSpec.model_validate({"type": "str", "not_a_field": True})
