"""Tests for src/common/ducklake_scd2_schema.py -- pure schema layer.

Verifies the extracted module in isolation: spec resolution, DDL/MERGE SQL builders, schema gate,
and field-semantics loading. No live catalog or DuckDB connection is required.

VP1 invariant: DDL/MERGE SQL produced here must be byte-identical to what ducklake_runtime
re-exports. Asserted via the identity check in test_builders_re_exported_via_runtime below.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.common import ducklake_runtime as rt
from src.common import ducklake_scd2_schema as schema

pytestmark = pytest.mark.unit

_SEMANTICS = {
    "fields": {
        "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
        "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
        "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "payload": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    }
}


# ---------------------------------------------------------------------------
# VP1 invariant: re-exports are the same objects (byte-identical SQL guaranteed)
# ---------------------------------------------------------------------------


def test_builders_re_exported_via_runtime():
    """The schema module's builders are the exact functions re-exported by the runtime."""
    assert rt._build_merge_history_sql is schema._build_merge_history_sql
    assert rt._build_merge_current_sql is schema._build_merge_current_sql
    assert rt._build_select_existing_created_sql is schema._build_select_existing_created_sql
    assert rt._column_ddl is schema._column_ddl
    assert rt.schema_gate is schema.schema_gate
    assert rt.resolve_table_spec is schema.resolve_table_spec


# ---------------------------------------------------------------------------
# No circular import: runtime -> schema (schema must NOT import runtime)
# ---------------------------------------------------------------------------


def test_no_circular_import():
    """ducklake_scd2_schema must not import ducklake_runtime (one-directional dependency)."""
    import importlib
    import sys

    mod = importlib.import_module("src.common.ducklake_scd2_schema")
    source = getattr(mod, "__file__", "") or ""
    runtime_mod_names = {k for k in sys.modules if "ducklake_runtime" in k}
    assert all("ducklake_scd2_schema" not in k for k in runtime_mod_names)
    for attr in vars(mod).values():
        mod_name = getattr(attr, "__module__", "") or ""
        assert "ducklake_runtime" not in mod_name, f"schema re-imports from runtime: {attr!r}"
    _ = source  # suppress lint


# ---------------------------------------------------------------------------
# Constants in schema (CATALOG_ALIAS, SMOKE_* tables)
# ---------------------------------------------------------------------------


def test_constants_present():
    assert schema.CATALOG_ALIAS == "ops_catalog"
    assert schema.SMOKE_HISTORY_TABLE == "ducklake_smoke_history"
    assert schema.SMOKE_CURRENT_TABLE == "ducklake_smoke_current"


# ---------------------------------------------------------------------------
# _order_columns
# ---------------------------------------------------------------------------


def test_order_columns_ulid_lead_timestamps_tail():
    ordered = schema._order_columns(_SEMANTICS["fields"], "rec_id")
    names = [c for c, _ in ordered]
    assert names[0] == "ulid"
    assert names[1] == "rec_id"  # merge key first among inputs
    assert names[-2:] == ["created_timestamp", "last_updated_timestamp"]


def test_order_columns_other_inputs_middle():
    ordered = schema._order_columns(_SEMANTICS["fields"], "rec_id")
    names = [c for c, _ in ordered]
    assert "payload" in names
    payload_idx = names.index("payload")
    assert payload_idx > 1  # after ulid + merge key
    assert payload_idx < len(names) - 2  # before timestamps


# ---------------------------------------------------------------------------
# resolve_table_spec -- smoke (None) and ops_recommendations
# ---------------------------------------------------------------------------


def test_resolve_smoke_spec():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    assert spec.table is None
    assert spec.history_table == schema.SMOKE_HISTORY_TABLE
    assert spec.current_table == schema.SMOKE_CURRENT_TABLE
    assert spec.merge_key == "rec_id"
    cols = [c for c, _ in spec.ordered_columns]
    assert cols == ["ulid", "rec_id", "payload", "created_timestamp", "last_updated_timestamp"]


def test_resolve_ops_recommendations():
    spec = schema.resolve_table_spec("ops_recommendations")
    assert spec.merge_key == "id"
    cols = [c for c, _ in spec.ordered_columns]
    assert cols[0] == "ulid"
    assert cols[1] == "id"
    assert cols[-2:] == ["created_timestamp", "last_updated_timestamp"]
    assert "bucket(8, id)" == spec.partition_current


def test_resolve_unknown_table_raises():
    with pytest.raises(schema.SchemaGateError, match="unknown ops table"):
        schema.resolve_table_spec("ops_does_not_exist")


# ---------------------------------------------------------------------------
# _column_ddl
# ---------------------------------------------------------------------------


def test_column_ddl_not_null_and_nullable():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    ddl = schema._column_ddl(spec)
    assert "ulid VARCHAR NOT NULL" in ddl
    assert "rec_id VARCHAR NOT NULL" in ddl
    assert "payload VARCHAR" in ddl
    assert "payload VARCHAR NOT NULL" not in ddl  # nullable column has no NOT NULL


# ---------------------------------------------------------------------------
# _build_merge_history_sql
# ---------------------------------------------------------------------------


def test_build_merge_history_sql_structure():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql = schema._build_merge_history_sql(spec)
    assert f"MERGE INTO {schema.CATALOG_ALIAS}.{schema.SMOKE_HISTORY_TABLE} AS t" in sql
    assert "ON t.ulid = s.ulid" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    col_count = len(spec.ordered_columns)
    assert sql.count("?") == col_count  # one placeholder per column


def test_build_merge_history_sql_ops_recommendations():
    spec = schema.resolve_table_spec("ops_recommendations")
    sql = schema._build_merge_history_sql(spec)
    assert "ops_recommendations_history" in sql
    assert "ON t.ulid = s.ulid" in sql


# ---------------------------------------------------------------------------
# _build_merge_current_sql
# ---------------------------------------------------------------------------


def test_build_merge_current_sql_structure():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql = schema._build_merge_current_sql(spec)
    assert f"MERGE INTO {schema.CATALOG_ALIAS}.{schema.SMOKE_CURRENT_TABLE} AS t" in sql
    assert "ON t.rec_id = s.rec_id" in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    # created_timestamp must NOT appear in UPDATE SET (carried, never re-stamped)
    update_portion = sql.split("WHEN MATCHED THEN UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
    assert "created_timestamp = s.created_timestamp" not in update_portion
    assert "rec_id = s.rec_id" not in update_portion  # merge key also not in UPDATE SET


def test_build_merge_current_sql_ops_recommendations():
    spec = schema.resolve_table_spec("ops_recommendations")
    sql = schema._build_merge_current_sql(spec)
    assert "ops_recommendations_current" in sql
    assert "ON t.id = s.id" in sql


# ---------------------------------------------------------------------------
# _build_select_existing_created_sql
# ---------------------------------------------------------------------------


def test_build_select_existing_created_sql():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql = schema._build_select_existing_created_sql(spec)
    assert f"SELECT created_timestamp FROM {schema.CATALOG_ALIAS}.{schema.SMOKE_CURRENT_TABLE}" in sql
    assert "WHERE rec_id = ?" in sql
    assert "status" not in sql


def test_build_select_existing_created_sql_include_status():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql = schema._build_select_existing_created_sql(spec, include_status=True)
    assert sql.startswith("SELECT created_timestamp, status FROM")
    assert "WHERE rec_id = ?" in sql


# ---------------------------------------------------------------------------
# _write_params
# ---------------------------------------------------------------------------


def test_write_params_ordering():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    identity = schema.WriteIdentity(ulid="01TESTULID12345678901234", timestamp=datetime(2026, 6, 8, tzinfo=timezone.utc))
    created_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = {"rec_id": "rec-42", "payload": "hello"}
    params = schema._write_params(spec, record, identity, created_ts)
    names = [c for c, _ in spec.ordered_columns]
    assert params[names.index("ulid")] == identity.ulid
    assert params[names.index("rec_id")] == "rec-42"
    assert params[names.index("payload")] == "hello"
    assert params[names.index("created_timestamp")] == created_ts
    assert params[names.index("last_updated_timestamp")] == identity.timestamp


# ---------------------------------------------------------------------------
# schema_gate
# ---------------------------------------------------------------------------


def test_schema_gate_accepts_valid_smoke_record():
    schema.schema_gate({"rec_id": "rec-1", "payload": "x"}, _SEMANTICS)
    schema.schema_gate({"rec_id": "rec-1"}, _SEMANTICS)  # payload nullable


def test_schema_gate_raises_unknown_field():
    with pytest.raises(schema.SchemaGateError, match="unknown field"):
        schema.schema_gate({"rec_id": "rec-1", "bogus": "x"}, _SEMANTICS)


def test_schema_gate_raises_derived_field():
    with pytest.raises(schema.SchemaGateError, match="derived"):
        schema.schema_gate({"rec_id": "rec-1", "ulid": "01ABC"}, _SEMANTICS)


def test_schema_gate_raises_missing_required():
    with pytest.raises(schema.SchemaGateError, match="missing or null"):
        schema.schema_gate({"payload": "x"}, _SEMANTICS)


def test_schema_gate_raises_mistyped_field():
    with pytest.raises(schema.SchemaGateError, match="expected str"):
        schema.schema_gate({"rec_id": 123}, _SEMANTICS)


def test_schema_gate_raises_empty_required():
    with pytest.raises(schema.SchemaGateError, match="empty"):
        schema.schema_gate({"rec_id": ""}, _SEMANTICS)


def test_schema_gate_ops_table():
    schema.schema_gate({"id": "rec-1", "status": "open", "automatable": True}, table="ops_recommendations")


def test_schema_gate_ops_rejects_mistyped_bool():
    with pytest.raises(schema.SchemaGateError, match="expected bool"):
        schema.schema_gate({"id": "rec-1", "status": "open", "automatable": "yes"}, table="ops_recommendations")


# ---------------------------------------------------------------------------
# _PY_TYPE_FOR_SQL coverage
# ---------------------------------------------------------------------------


def test_py_type_map_covers_ops_types():
    assert schema._PY_TYPE_FOR_SQL["BIGINT"] is int
    assert schema._PY_TYPE_FOR_SQL["BOOLEAN"] is bool
    assert schema._PY_TYPE_FOR_SQL["VARCHAR[]"] is list
    assert schema._PY_TYPE_FOR_SQL["BIGINT[]"] is list


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy():
    assert issubclass(schema.SchemaGateError, schema.DuckLakeRuntimeError)
    assert issubclass(schema.ReferentialError, schema.DuckLakeRuntimeError)
    assert issubclass(schema.AppendOnlyUpdateError, schema.DuckLakeRuntimeError)
    assert issubclass(schema.DuckLakeRuntimeError, RuntimeError)


# ---------------------------------------------------------------------------
# WriteIdentity / WriteResult dataclasses
# ---------------------------------------------------------------------------


def test_write_identity_frozen():
    ts = datetime(2026, 6, 8, tzinfo=timezone.utc)
    wid = schema.WriteIdentity(ulid="01TESTULID12345678901234", timestamp=ts)
    assert wid.ulid == "01TESTULID12345678901234"
    assert wid.timestamp == ts
    with pytest.raises((AttributeError, TypeError)):
        wid.ulid = "changed"  # type: ignore[misc]


def test_write_result_frozen():
    ts = datetime(2026, 6, 8, tzinfo=timezone.utc)
    wr = schema.WriteResult(
        ulid="01U", rec_id="rec-1", occ_retries=0, commit_ms=5.0, created_timestamp=ts, last_updated_timestamp=ts
    )
    assert wr.rec_id == "rec-1"
    with pytest.raises((AttributeError, TypeError)):
        wr.occ_retries = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_field_semantics / _field_semantics_path
# ---------------------------------------------------------------------------


def test_load_field_semantics_from_file(tmp_path):
    p = tmp_path / "fs.yaml"
    p.write_text("fields:\n  rec_id:\n    role: input\n", encoding="utf-8")
    out = schema.load_field_semantics(p)
    assert out["fields"]["rec_id"]["role"] == "input"


def test_field_semantics_path_env_override(monkeypatch):
    monkeypatch.setenv(schema._FIELD_SEMANTICS_ENV, "/custom/fs.yaml")
    assert str(schema._field_semantics_path()) == "/custom/fs.yaml"


def test_field_semantics_path_default(monkeypatch):
    monkeypatch.delenv(schema._FIELD_SEMANTICS_ENV, raising=False)
    assert schema._field_semantics_path() == schema._DEFAULT_FIELD_SEMANTICS_PATH


def test_load_real_contract(monkeypatch):
    monkeypatch.delenv(schema._FIELD_SEMANTICS_ENV, raising=False)
    out = schema.load_field_semantics()
    assert "ulid" in out["fields"]
    assert out["fields"]["ulid"]["role"] == "derived"


# ---------------------------------------------------------------------------
# ops_table_names
# ---------------------------------------------------------------------------


def test_ops_table_names_includes_recommendations():
    names = schema.ops_table_names()
    assert "ops_recommendations" in names
    assert "ops_decisions" in names
    assert len(names) >= 2


# ---------------------------------------------------------------------------
# SQL byte-identity check: schema builders vs runtime re-exports (VP1)
# ---------------------------------------------------------------------------


def test_smoke_merge_history_sql_byte_identical_via_reexport():
    """SQL generated via schema module matches SQL from runtime re-export (byte-identical)."""
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql_from_schema = schema._build_merge_history_sql(spec)
    sql_from_runtime = rt._build_merge_history_sql(spec)
    assert sql_from_schema == sql_from_runtime


def test_smoke_merge_current_sql_byte_identical_via_reexport():
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    sql_from_schema = schema._build_merge_current_sql(spec)
    sql_from_runtime = rt._build_merge_current_sql(spec)
    assert sql_from_schema == sql_from_runtime


def test_ops_merge_history_sql_byte_identical_via_reexport():
    """ops_recommendations merge SQL from schema == from runtime re-export."""
    spec = schema.resolve_table_spec("ops_recommendations")
    sql_from_schema = schema._build_merge_history_sql(spec)
    sql_from_runtime = rt._build_merge_history_sql(spec)
    assert sql_from_schema == sql_from_runtime


def test_ops_merge_current_sql_byte_identical_via_reexport():
    spec = schema.resolve_table_spec("ops_recommendations")
    sql_from_schema = schema._build_merge_current_sql(spec)
    sql_from_runtime = rt._build_merge_current_sql(spec)
    assert sql_from_schema == sql_from_runtime


# ---------------------------------------------------------------------------
# append_only write mode -- schema-layer tests
# ---------------------------------------------------------------------------

_APPEND_ONLY_SEMANTICS: dict = {
    "fields": {
        "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
        "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
        "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
    },
    "ops_tables": {
        "ops_smoke_events": {
            "write_mode": "append_only",
            "status": "smoke",
            "merge_key": "event_id",
            "history_table": "ops_smoke_events_history",
            "partition": {"history": "day(created_timestamp)"},
            "columns": {
                "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
                "event_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
                "event_type": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
                "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
                "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
            },
        }
    },
}


def test_resolve_table_spec_append_only_current_table_none():
    """append_only spec resolves with current_table=None and write_mode='append_only'."""
    spec = schema.resolve_table_spec("ops_smoke_events", _APPEND_ONLY_SEMANTICS)
    assert spec.write_mode == "append_only"
    assert spec.current_table is None
    assert spec.history_table == "ops_smoke_events_history"
    assert spec.merge_key == "event_id"


def test_check_append_only_guard_raises_on_require_exists():
    """check_append_only_guard raises AppendOnlyUpdateError for append_only + require_exists=True."""
    spec = schema.resolve_table_spec("ops_smoke_events", _APPEND_ONLY_SEMANTICS)
    with pytest.raises(schema.AppendOnlyUpdateError, match="append_only"):
        schema.check_append_only_guard(spec, require_exists=True)


def test_check_append_only_guard_noop_for_scd2():
    """check_append_only_guard is a no-op for scd2 tables even with require_exists=True."""
    spec = schema.resolve_table_spec(None, _SEMANTICS)
    assert spec.write_mode == "scd2"
    schema.check_append_only_guard(spec, require_exists=True)  # no raise


def test_check_append_only_guard_noop_when_require_exists_false():
    """check_append_only_guard is a no-op for append_only + require_exists=False."""
    spec = schema.resolve_table_spec("ops_smoke_events", _APPEND_ONLY_SEMANTICS)
    schema.check_append_only_guard(spec, require_exists=False)  # no raise


def test_ops_smoke_events_in_real_ops_table_names():
    """ops_smoke_events appears in ops_table_names() once added to field_semantics.yaml."""
    names = schema.ops_table_names()
    assert "ops_smoke_events" in names


# ---------------------------------------------------------------------------
# rec_history NAMED_READS entry + NAMED_READS_VERSION (T1.16 c4)
# ---------------------------------------------------------------------------


def test_named_reads_version_is_3():
    assert schema.NAMED_READS_VERSION == 3


def test_rec_history_verb_registered():
    rh = schema.NAMED_READS["rec_history"]
    assert rh.table == "ops_recommendations"
    assert rh.params == ("id",)
    assert "{hist}" in rh.sql
    assert "ORDER BY last_updated_timestamp DESC, ulid DESC" in rh.sql


# ---------------------------------------------------------------------------
# Total-order invariant (T1.16 c1): every paginable or trailing-LIMIT verb ends in a unique key
# ---------------------------------------------------------------------------


def test_named_reads_total_order_invariant():
    import re

    def lim(s: str) -> bool:
        return bool(re.search(r"\bLIMIT\s+\d+\s*$", s, re.I))

    def tot(s: str) -> bool:
        return bool(re.search(r"ORDER BY .*\b(id|ulid)\b[^,]*$", s, re.I | re.S))

    bad = [v for v, n in schema.NAMED_READS.items() if (n.paginable or lim(n.sql)) and not tot(n.sql)]
    assert not bad


def test_priority_queue_current_excluded_from_total_order_check():
    """priority_queue_current's LIMIT is a subquery bound, not a trailing output cap -- excluded."""
    entry = schema.NAMED_READS["priority_queue_current"]
    assert not entry.paginable
    import re

    assert not re.search(r"\bLIMIT\s+\d+\s*$", entry.sql, re.I)


def test_ci_rca_open_and_budget_bypass_recent_have_id_tiebreak():
    """The two trailing-LIMIT verbs' ORDER BY carries an `id` tiebreak (reproducible bounded reads)."""
    for verb in ("ci_rca_open", "budget_bypass_recent"):
        sql = schema.NAMED_READS[verb].sql
        assert ", id LIMIT" in sql


def test_open_recs_and_recs_by_title_prefix_are_paginable():
    assert schema.NAMED_READS["open_recs"].paginable is True
    assert schema.NAMED_READS["recs_by_title_prefix"].paginable is True


# ---------------------------------------------------------------------------
# describe_named_reads / describe_write_verbs (CD.10 / CD.15 agent-facing describe surface)
# ---------------------------------------------------------------------------


def test_describe_named_reads_covers_every_verb():
    out = schema.describe_named_reads()
    assert set(out) == set(schema.NAMED_READS)
    entry = out["rec_by_id"]
    assert entry["params"] == ["id"]
    assert entry["params_schema"]["required"] == ["id"]
    assert "table" in entry and "description" in entry and "paginable" in entry


def test_describe_named_reads_no_params_verb():
    out = schema.describe_named_reads()
    assert out["open_recs"]["params"] == []
    assert out["open_recs"]["params_schema"]["required"] == []


def test_describe_write_verbs_covers_registry():
    out = schema.describe_write_verbs()
    assert set(out) == set(schema.VERB_REGISTRY)
    assert set(out) >= {"write_ops", "update_ops", "file_ops", "create_ops_tables"}
    for verb, entry in out.items():
        assert entry["description"], verb
        assert entry["params_schema"]["type"] == "object"


def test_verb_registry_entries_are_writeverb_instances():
    for verb, wv in schema.VERB_REGISTRY.items():
        assert isinstance(wv, schema.WriteVerb)
        assert wv.verb == verb


# ---------------------------------------------------------------------------
# check_rec_status_transition / StatusTransitionError (T1.16 c3, Decision 103)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing,new",
    [
        ("failed", "open"),  # executor restart
        ("open", "superseded"),
        ("closed", "superseded"),
        ("failed", "declined"),
        ("open", "declined"),
        ("open", "closed"),
        ("closed", "closed"),  # same-status write
        ("banana", "open"),  # unrecognised vocab -- permissive skip
        ("open", "banana"),
    ],
)
def test_check_rec_status_transition_allows_live_edges(existing, new):
    schema.check_rec_status_transition("ops_recommendations", existing, new)  # must not raise


@pytest.mark.parametrize("existing", ["closed", "declined", "superseded"])
def test_check_rec_status_transition_rejects_resolved_reactivation(existing):
    with pytest.raises(schema.StatusTransitionError, match="illegal status transition"):
        schema.check_rec_status_transition("ops_recommendations", existing, "open")


def test_check_rec_status_transition_noop_for_undeclared_table():
    """A table absent from STATUS_TRANSITIONS has no DAG -- always a permissive no-op."""
    schema.check_rec_status_transition("ops_decisions", "closed", "open")  # must not raise


def test_status_transition_error_is_ducklake_runtime_error():
    assert issubclass(schema.StatusTransitionError, schema.DuckLakeRuntimeError)
