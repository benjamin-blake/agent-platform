"""Unit tests for scripts/contracts.py -- the loader, $ref resolver, and status state machine.

Hermetic: fixture YAMLs are materialised under tmp_path inside each test (no committed
fixtures, no sockets, no shared state). Compatible with pytest-socket / pytest-randomly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.contracts import (
    ContractValidationError,
    load_all_contracts,
    load_contract,
    load_contract_meta,
    resolve_refs,
    validate_status_transition,
)


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _class_c_target(field_name: str = "registry_key", *, enforced: bool = True, chained: bool = False) -> dict:
    field: dict = (
        {"$ref": "docs/contracts/other.yaml#/contract/fields/x"}
        if chained
        else {
            "type": "str",
            "iceberg_type": "string",
            "nullable": False,
            "description": "Canonical source registry key.",
            "semantics": "Open-set lineage key.",
            "dq_intent": {"not_null": {"enforced": enforced}},
        }
    )
    return {
        "contract": {
            "id": "source-lineage",
            "class": "C",
            "contract_version": 1,
            "status": "ratified",
            "ratified_via": "test-decision",
        },
        "fields": {field_name: field},
    }


def _class_a_with_ref(ref: str = "docs/contracts/source-lineage.yaml#/contract/fields/registry_key", **field_extra) -> dict:
    source_field: dict = {"$ref": ref}
    source_field.update(field_extra)
    return {
        "contract": {
            "id": "ops_recommendations",
            "class": "A",
            "contract_version": 1,
            "status": "ratified",
            "ratified_via": "test-decision",
        },
        "fields": {
            "id": {"type": "str", "nullable": False, "description": "id"},
            "source": source_field,
        },
    }


class TestRefResolver:
    def test_ref_resolves_with_local_override(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        doc = load_contract(
            _write(
                tmp_path / "ops_recommendations.yaml",
                _class_a_with_ref(
                    dq_intent_local={"not_null": {"enforced": True, "write_time": True}},
                    joins=["lineage_join_source_to_agent_type"],
                ),
            )
        )
        resolved = resolve_refs(doc, tmp_path)
        assert resolved["id"].type == "str"  # inline field passes through
        src = resolved["source"]
        assert src.ref is None  # ref collapsed after resolution
        assert src.description == "Canonical source registry key."  # target definition layered in
        assert src.dq_intent == {"not_null": {"enforced": True, "write_time": True}}  # local override on top
        assert src.joins == ["lineage_join_source_to_agent_type"]

    def test_inline_field_passes_through(self, tmp_path: Path) -> None:
        doc = load_contract(
            _write(
                tmp_path / "c.yaml",
                {
                    "contract": {"id": "x", "class": "A", "contract_version": 1, "status": "draft"},
                    "fields": {"id": {"type": "str", "nullable": False}},
                },
            )
        )
        resolved = resolve_refs(doc, tmp_path)
        assert resolved["id"].type == "str"

    def test_governance_notes_local_layered(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        doc = load_contract(
            _write(
                tmp_path / "a.yaml",
                _class_a_with_ref(
                    governance_notes_local="Tighter local note.",
                ),
            )
        )
        resolved = resolve_refs(doc, tmp_path)
        assert resolved["source"].governance_notes == "Tighter local note."

    def test_override_on_target_without_dq_intent_allowed(self, tmp_path: Path) -> None:
        # Target field carries no dq_intent, so a local dq_intent_local adds (does not loosen).
        _write(
            tmp_path / "source-lineage.yaml",
            {
                "contract": {
                    "id": "source-lineage",
                    "class": "C",
                    "contract_version": 1,
                    "status": "ratified",
                    "ratified_via": "test-decision",
                },
                "fields": {"registry_key": {"type": "str", "nullable": False, "description": "key"}},
            },
        )
        doc = load_contract(
            _write(
                tmp_path / "a.yaml",
                _class_a_with_ref(
                    dq_intent_local={"not_null": {"enforced": True}},
                ),
            )
        )
        resolved = resolve_refs(doc, tmp_path)
        assert resolved["source"].dq_intent == {"not_null": {"enforced": True}}

    def test_amendment_log_local_layered(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        doc = load_contract(
            _write(
                tmp_path / "a.yaml",
                _class_a_with_ref(
                    amendment_log=[{"date": "2026-07-01", "semantic_break": False, "change_class": "join_add"}],
                ),
            )
        )
        resolved = resolve_refs(doc, tmp_path)
        assert resolved["source"].amendment_log[0].change_class.value == "join_add"


class TestRejectsMalformed:
    def test_non_mapping_yaml_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ContractValidationError):
            load_contract(path)

    def test_invalid_yaml_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("contract: {id: x\n  : : :\n", encoding="utf-8")
        with pytest.raises(ContractValidationError):
            load_contract(path)

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractValidationError):
            load_contract(tmp_path / "nope.yaml")

    def test_schema_violation_rejected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "a.yaml",
            {
                "contract": {
                    "id": "x",
                    "class": "A",
                    "contract_version": 1,
                    "status": "ratified",
                    "ratified_via": "test-decision",
                },
            },
        )  # Class A without fields
        with pytest.raises(ContractValidationError):
            load_contract(path)

    def test_duplicate_inline_and_ref_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        doc = load_contract(
            _write(
                tmp_path / "a.yaml",
                _class_a_with_ref(
                    description="An inline definition alongside the ref -- forbidden.",
                ),
            )
        )
        with pytest.raises(ContractValidationError, match="duplicate"):
            resolve_refs(doc, tmp_path)

    def test_chained_ref_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target(chained=True))
        doc = load_contract(_write(tmp_path / "a.yaml", _class_a_with_ref()))
        with pytest.raises(ContractValidationError, match="chained"):
            resolve_refs(doc, tmp_path)

    def test_dangling_target_file_rejected(self, tmp_path: Path) -> None:
        doc = load_contract(_write(tmp_path / "a.yaml", _class_a_with_ref()))
        with pytest.raises(ContractValidationError, match="target file does not exist"):
            resolve_refs(doc, tmp_path)

    def test_dangling_target_field_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target(field_name="other_key"))
        doc = load_contract(_write(tmp_path / "a.yaml", _class_a_with_ref()))
        with pytest.raises(ContractValidationError, match="no field"):
            resolve_refs(doc, tmp_path)

    def test_loosening_override_rejected(self, tmp_path: Path) -> None:
        _write(tmp_path / "source-lineage.yaml", _class_c_target(enforced=True))
        doc = load_contract(
            _write(
                tmp_path / "a.yaml",
                _class_a_with_ref(
                    dq_intent_local={"not_null": {"enforced": False}},
                ),
            )
        )
        with pytest.raises(ContractValidationError, match="loosen"):
            resolve_refs(doc, tmp_path)

    def test_malformed_ref_no_fragment_rejected(self, tmp_path: Path) -> None:
        doc = load_contract(_write(tmp_path / "a.yaml", _class_a_with_ref(ref="docs/contracts/source-lineage.yaml")))
        with pytest.raises(ContractValidationError, match="no '#'"):
            resolve_refs(doc, tmp_path)

    def test_malformed_ref_bad_pointer_rejected(self, tmp_path: Path) -> None:
        doc = load_contract(
            _write(tmp_path / "a.yaml", _class_a_with_ref(ref="docs/contracts/source-lineage.yaml#/contract/governance"))
        )
        with pytest.raises(ContractValidationError, match="malformed"):
            resolve_refs(doc, tmp_path)

    def test_ref_pointer_names_no_field_rejected(self, tmp_path: Path) -> None:
        doc = load_contract(_write(tmp_path / "a.yaml", _class_a_with_ref(ref="x.yaml#/contract/fields/")))
        with pytest.raises(ContractValidationError, match="names no field"):
            resolve_refs(doc, tmp_path)


class TestLoadAll:
    def test_skips_non_ritual_and_loads_ritual(self, tmp_path: Path) -> None:
        # Pre-ritual free-form doc (top-level version:, no contract.class) -- must be skipped.
        _write(tmp_path / "read-engine.yaml", {"version": 3, "engine": "duckdb"})
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        loaded = load_all_contracts(tmp_path)
        assert set(loaded) == {"source-lineage"}

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        assert load_all_contracts(tmp_path / "does-not-exist") == {}

    def test_unparseable_yaml_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "broken.yaml").write_text("key: : :\n  - bad\n", encoding="utf-8")
        _write(tmp_path / "source-lineage.yaml", _class_c_target())
        loaded = load_all_contracts(tmp_path)
        assert set(loaded) == {"source-lineage"}

    def test_non_mapping_yaml_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
        loaded = load_all_contracts(tmp_path)
        assert loaded == {}


class TestFieldSpecDerivation:
    """Verify FieldSpec derivation block addition (T0.12.5 / contracts_schema.py)."""

    def test_derivation_block_round_trips(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "a.yaml",
            {
                "contract": {
                    "id": "x",
                    "class": "A",
                    "contract_version": 1,
                    "status": "ratified",
                    "ratified_via": "test-decision",
                },
                "fields": {
                    "priority": {
                        "type": "int",
                        "nullable": False,
                        "description": "Priority level.",
                        "derivation": {
                            "formula": "source_priority_map[source]",
                            "inputs": ["source"],
                            "recompute_trigger": "source change",
                            "failure_policy": "fallback_priority",
                        },
                    }
                },
            },
        )
        doc = load_contract(path)
        assert doc.fields is not None
        assert doc.fields["priority"].derivation is not None
        assert doc.fields["priority"].derivation["formula"] == "source_priority_map[source]"

    def test_unknown_field_key_still_rejected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "a.yaml",
            {
                "contract": {
                    "id": "x",
                    "class": "A",
                    "contract_version": 1,
                    "status": "ratified",
                    "ratified_via": "test-decision",
                },
                "fields": {
                    "id": {
                        "type": "str",
                        "nullable": False,
                        "description": "id",
                        "unknown_key_not_in_schema": "value",
                    }
                },
            },
        )
        with pytest.raises(ContractValidationError):
            load_contract(path)


class TestStatusTransitions:
    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("draft", "ratified"),
            ("draft", "provisional_v0"),
            ("provisional_v0", "ratified"),
            ("provisional_v0", "deprecated"),
            ("provisional_v0", "superseded"),
            ("ratified", "deprecated"),
            ("ratified", "superseded"),
        ],
    )
    def test_legal_transitions_allowed(self, old: str, new: str) -> None:
        assert validate_status_transition(old, new) is True

    def test_deprecated_revival_forbidden_by_default(self) -> None:
        # Default-forbidden, NOT permanent terminality: the ceremonial N+1 revival lives
        # elsewhere; this default helper rejects deprecated as a source state.
        with pytest.raises(ContractValidationError, match="forbidden"):
            validate_status_transition("deprecated", "ratified")

    def test_other_forbidden_transition_rejected(self) -> None:
        with pytest.raises(ContractValidationError, match="forbidden"):
            validate_status_transition("ratified", "draft")

    def test_unknown_old_status_rejected(self) -> None:
        with pytest.raises(ContractValidationError, match="unknown"):
            validate_status_transition("retired", "ratified")

    def test_unknown_new_status_rejected(self) -> None:
        with pytest.raises(ContractValidationError, match="unknown"):
            validate_status_transition("ratified", "retired")

    @pytest.mark.parametrize("new", ["ratified", "deprecated", "superseded"])
    def test_active_outbound_edges_allowed(self, new: str) -> None:
        assert validate_status_transition("active", new) is True

    @pytest.mark.parametrize("old", ["draft", "provisional_v0", "ratified", "deprecated"])
    def test_no_inbound_edge_to_active(self, old: str) -> None:
        # active (contracts-first-class-migration) is grandfather-only -- no transition rule
        # produces it, from any source state.
        with pytest.raises(ContractValidationError, match="forbidden"):
            validate_status_transition(old, "active")


def _class_d_envelope(**overrides: object) -> dict:
    envelope = {
        "id": "cd-test",
        "class": "D",
        "contract_version": 1,
        "status": "ratified",
        "ratified_via": "test-decision",
        "subject": "cd-test-subject",
        "evaluator": {"check": "validate_placement"},
    }
    envelope.update(overrides)
    return envelope


class TestLoadContractMeta:
    def test_class_d_envelope_validates_with_arbitrary_body_keys(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "d.yaml",
            {
                "contract": _class_d_envelope(),
                "some_heterogeneous_mechanism_section": {"a": "b", "c": [1, 2, 3]},
            },
        )
        meta = load_contract_meta(path)
        assert meta.id == "cd-test"
        assert meta.class_.value == "D"
        assert meta.subject == "cd-test-subject"
        assert meta.evaluator.check == "validate_placement"

    def test_missing_subject_raises(self, tmp_path: Path) -> None:
        envelope = _class_d_envelope()
        del envelope["subject"]
        path = _write(tmp_path / "d.yaml", {"contract": envelope})
        with pytest.raises(ContractValidationError):
            load_contract_meta(path)

    def test_missing_evaluator_raises(self, tmp_path: Path) -> None:
        envelope = _class_d_envelope()
        del envelope["evaluator"]
        path = _write(tmp_path / "d.yaml", {"contract": envelope})
        with pytest.raises(ContractValidationError):
            load_contract_meta(path)

    def test_ratified_without_ratified_via_raises(self, tmp_path: Path) -> None:
        envelope = _class_d_envelope()
        del envelope["ratified_via"]
        path = _write(tmp_path / "d.yaml", {"contract": envelope})
        with pytest.raises(ContractValidationError):
            load_contract_meta(path)

    def test_grandfathered_file_carrying_active_status_loads(self, tmp_path: Path) -> None:
        # The guard against reintroducing the sweep-blocking contradiction: a grandfathered file
        # legitimately carrying active status must still LOAD at the schema layer (this plan's
        # own substrate must never block the population sweep).
        envelope = _class_d_envelope(status="active", ratified_via=None)
        path = _write(tmp_path / "d.yaml", {"contract": envelope})
        meta = load_contract_meta(path)
        assert meta.status.value == "active"

    def test_none_grandfathered_evaluator_is_unrepresentable(self, tmp_path: Path) -> None:
        # rec-3059 wave 2: the grandfather-only none_grandfathered kind is retired -- it is no
        # longer representable at ALL, not merely unresolving, so load_contract_meta must reject
        # it at the schema layer just like any other malformed evaluator.
        route = {
            "reason": "pre-ritual free-form doc, pending future ratification",
            "consumer": "scripts/some_consumer.py",
            "mechanism": "assert some_field matches reality",
            "blocker": "no check reads it yet",
            "shape": "check",
        }
        envelope = _class_d_envelope(evaluator={"none_grandfathered": route})
        path = _write(tmp_path / "d.yaml", {"contract": envelope})
        with pytest.raises(ContractValidationError):
            load_contract_meta(path)

    def test_no_top_level_contract_block_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "d.yaml", {"not_contract": {}})
        with pytest.raises(ContractValidationError, match="no top-level"):
            load_contract_meta(path)

    def test_top_level_non_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "d.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ContractValidationError, match="YAML mapping"):
            load_contract_meta(path)

    def test_unreadable_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ContractValidationError, match="cannot read"):
            load_contract_meta(tmp_path / "does_not_exist.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "d.yaml"
        path.write_text("{bad: [unclosed", encoding="utf-8")
        with pytest.raises(ContractValidationError, match="invalid YAML"):
            load_contract_meta(path)


class TestLoadAllContractsSkipsClassD:
    def test_class_d_file_is_skipped_not_raised(self, tmp_path: Path) -> None:
        # load_all_contracts must never construct a ContractDocument for a Class D file -- that
        # would raise, and a caller wrapping this in a bare `except Exception: pass` (e.g.
        # context_docs.py) would silently swallow it and kill the whole provisional-contract
        # scan. Class D is explicitly skipped instead.
        _write(tmp_path / "d.yaml", {"contract": _class_d_envelope()})
        contracts = load_all_contracts(tmp_path)
        assert contracts == {}

    def test_class_a_still_loads_alongside_an_ignored_class_d_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "d.yaml", {"contract": _class_d_envelope()})
        _write(
            tmp_path / "a.yaml",
            {
                "contract": {
                    "id": "alpha",
                    "class": "A",
                    "contract_version": 1,
                    "status": "draft",
                },
                "fields": {
                    "f1": {
                        "type": "str",
                        "nullable": False,
                        "description": "d",
                        "semantics": "s",
                        "populated_by": "writer",
                        "dq_intent": {"not_null": {"enforced": True}},
                    }
                },
            },
        )
        contracts = load_all_contracts(tmp_path)
        assert set(contracts) == {"alpha"}
