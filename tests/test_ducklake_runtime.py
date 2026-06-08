"""Tests for src/common/ducklake_runtime.py (T2.17 / CD.33, 100% coverage).

All network/duckdb mocked -- no live catalog. The live proof is the [post-deploy] verification-plan
steps; these tests prove the derivation rules, the schema gate, the OCC loud-fail, the version
assert, and the partition DDL composition.
"""

from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

from src.common import ducklake_runtime as rt

pytestmark = pytest.mark.unit

_DSN = {
    "host": "ep-test-123.eu-west-2.aws.neon.tech",
    "dbname": "ducklake_ops",
    "username": "ducklake_ops",
    "password": "secret-pw",  # pragma: allowlist secret -- fake fixture value
    "sslmode": "require",
    "meta_schema": "ducklake_ops",
}

_SEMANTICS = {
    "fields": {
        "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
        "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
        "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "payload": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    }
}


class FakeCon:
    """DuckDB-connection double: records (sql, params); simulates OCC + hard failures + reads."""

    def __init__(
        self,
        *,
        created_lookup: list | None = None,
        occ_fail_times: int = 0,
        hard_fail_substr: str | None = None,
        read_rows: list | None = None,
        rollback_raises: bool = False,
    ):
        self.executed: list[tuple[str, list | None]] = []
        self._created_lookup = created_lookup  # None/[] -> insert path; [(ts,)] -> update path
        self._occ_fail_times = occ_fail_times
        self._merge_hist_calls = 0
        self._hard_fail_substr = hard_fail_substr
        self._read_rows = read_rows or []
        self._rollback_raises = rollback_raises
        self._last = ""
        self.description = [
            ("ulid",),
            ("rec_id",),
            ("payload",),
            ("created_timestamp",),
            ("last_updated_timestamp",),
        ]
        self.closed = False

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))
        if self._rollback_raises and sql == "ROLLBACK":
            raise RuntimeError("no active transaction")
        if self._hard_fail_substr and self._hard_fail_substr in sql:
            raise ValueError("hard failure -- not a collision")
        if rt.SMOKE_HISTORY_TABLE in sql and sql.startswith("MERGE INTO"):
            self._merge_hist_calls += 1
            if self._merge_hist_calls <= self._occ_fail_times:
                raise RuntimeError("could not serialize access due to concurrent update")
        return self

    def fetchall(self):
        if self._last.startswith("SELECT created_timestamp"):
            return self._created_lookup or []
        if self._last.startswith("SELECT ulid"):
            return self._read_rows
        return []

    def merge_history_params(self) -> list[list]:
        """All params bound to the history MERGE, one per attempt."""
        return [p for sql, p in self.executed if rt.SMOKE_HISTORY_TABLE in sql and sql.startswith("MERGE INTO")]


# ---------------------------------------------------------------------------
# mint_write_identity
# ---------------------------------------------------------------------------


def test_mint_write_identity_default_now():
    wid = rt.mint_write_identity()
    assert len(wid.ulid) == 26
    assert wid.timestamp.tzinfo is not None


def test_mint_write_identity_explicit_now():
    moment = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    wid = rt.mint_write_identity(now=moment)
    assert wid.timestamp == moment
    assert len(wid.ulid) == 26


# ---------------------------------------------------------------------------
# assert_duckdb_version
# ---------------------------------------------------------------------------


def test_assert_duckdb_version_match():
    fake = types.SimpleNamespace(__version__="1.5.3")
    assert rt.assert_duckdb_version(fake) == "1.5.3"


def test_assert_duckdb_version_mismatch_raises():
    fake = types.SimpleNamespace(__version__="1.5.2")
    with pytest.raises(rt.VersionMismatchError, match="version mismatch"):
        rt.assert_duckdb_version(fake)


def test_assert_duckdb_version_resolves_default(monkeypatch):
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__="1.5.3"))
    assert rt.assert_duckdb_version() == "1.5.3"


# ---------------------------------------------------------------------------
# fetch_dsn / libpq_conninfo
# ---------------------------------------------------------------------------


def test_fetch_dsn_success(monkeypatch):
    captured = {}

    class _Client:
        def get_secret_value(self, SecretId):
            captured["secret_id"] = SecretId
            return {"SecretString": json.dumps(_DSN)}

    class _Session:
        def __init__(self, profile_name=None):
            captured["profile"] = profile_name

        def client(self, name):
            captured["client"] = name
            return _Client()

    import boto3

    monkeypatch.setattr(boto3, "Session", _Session)
    out = rt.fetch_dsn(profile="agent_platform")
    assert out["host"] == _DSN["host"]
    assert captured["secret_id"] == rt.DSN_SECRET_ID
    assert captured["client"] == "secretsmanager"


def test_fetch_dsn_missing_key_raises(monkeypatch):
    bad = {k: v for k, v in _DSN.items() if k != "password"}

    class _Client:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps(bad)}

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def client(self, name):
            return _Client()

    import boto3

    monkeypatch.setattr(boto3, "Session", _Session)
    with pytest.raises(RuntimeError, match="missing required keys"):
        rt.fetch_dsn()


def test_libpq_conninfo_explicit_and_default_sslmode():
    assert "sslmode=require" in rt.libpq_conninfo(_DSN)
    no_ssl = {k: v for k, v in _DSN.items() if k != "sslmode"}
    out = rt.libpq_conninfo(no_ssl)
    assert "sslmode=require" in out
    assert "host=ep-test-123.eu-west-2.aws.neon.tech" in out


# ---------------------------------------------------------------------------
# open_connection (dev INSTALL vs baked LOAD)
# ---------------------------------------------------------------------------


def _patch_duckdb(monkeypatch, con):
    fake_duckdb = types.SimpleNamespace(connect=lambda: con, __version__="1.5.3")
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    monkeypatch.setattr(rt.ducklake_spike, "_set_s3_credentials", lambda c, profile=None: None)


def test_open_connection_dev_mode_installs(monkeypatch):
    con = FakeCon()
    _patch_duckdb(monkeypatch, con)
    out = rt.open_connection(dsn=_DSN, data_path="s3://x/y/")
    assert out is con
    sqls = [s for s, _ in con.executed]
    assert any("INSTALL ducklake" in s for s in sqls)
    assert any(s.startswith("ATTACH 'ducklake:postgres:") for s in sqls)
    assert any("META_SCHEMA 'ducklake_ops'" in s for s in sqls)
    assert any("ducklake_default_data_inlining_row_limit=0" in s for s in sqls)
    assert any(s == "SET threads=1" for s in sqls)


def test_open_connection_baked_mode_failclosed(monkeypatch):
    con = FakeCon()
    _patch_duckdb(monkeypatch, con)
    rt.open_connection(dsn=_DSN, data_path="s3://x/y/", extension_directory="/opt/duckdb_extensions")
    sqls = [s for s, _ in con.executed]
    assert any("extension_directory=" in s for s in sqls)
    assert any("autoinstall_known_extensions=false" in s for s in sqls)
    assert any("autoload_known_extensions=false" in s for s in sqls)
    assert any("custom_extension_repository=''" in s for s in sqls)
    assert any(s == "LOAD postgres" for s in sqls)
    assert not any("INSTALL" in s for s in sqls)  # fail-closed: no network INSTALL
    assert any(s == "SET threads=1" for s in sqls)  # vCPU-starvation fix applies on the baked path too


def test_open_connection_with_shared_creds(monkeypatch):
    con = FakeCon()
    fake_duckdb = types.SimpleNamespace(connect=lambda: con, __version__="1.5.3")
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    creds = ("AKIA", "secret", "token", "eu-west-2")  # pragma: allowlist secret
    rt.open_connection(dsn=_DSN, data_path="s3://x/y/", _creds=creds)
    sqls = [s for s, _ in con.executed]
    assert any("s3_access_key_id=" in s for s in sqls)
    assert any("s3_session_token=" in s for s in sqls)


def test_open_connection_shared_creds_no_token(monkeypatch):
    con = FakeCon()
    fake_duckdb = types.SimpleNamespace(connect=lambda: con, __version__="1.5.3")
    monkeypatch.setattr(rt.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    creds = ("AKIA", "secret", None, "eu-west-2")  # pragma: allowlist secret
    rt.open_connection(dsn=_DSN, data_path="s3://x/y/", _creds=creds)
    sqls = [s for s, _ in con.executed]
    assert not any("s3_session_token=" in s for s in sqls)


# ---------------------------------------------------------------------------
# field semantics loading
# ---------------------------------------------------------------------------


def test_field_semantics_path_env_override(monkeypatch):
    monkeypatch.setenv(rt._FIELD_SEMANTICS_ENV, "/custom/fs.yaml")
    assert str(rt._field_semantics_path()) == "/custom/fs.yaml"


def test_field_semantics_path_default(monkeypatch):
    monkeypatch.delenv(rt._FIELD_SEMANTICS_ENV, raising=False)
    assert rt._field_semantics_path() == rt._DEFAULT_FIELD_SEMANTICS_PATH


def test_load_field_semantics_explicit_path(tmp_path):
    p = tmp_path / "fs.yaml"
    p.write_text("fields:\n  rec_id:\n    role: input\n", encoding="utf-8")
    out = rt.load_field_semantics(p)
    assert out["fields"]["rec_id"]["role"] == "input"


def test_load_field_semantics_real_contract(monkeypatch):
    monkeypatch.delenv(rt._FIELD_SEMANTICS_ENV, raising=False)
    out = rt.load_field_semantics()
    assert "ulid" in out["fields"]
    assert out["fields"]["ulid"]["role"] == "derived"


# ---------------------------------------------------------------------------
# schema_gate -- loud-fail
# ---------------------------------------------------------------------------


def test_schema_gate_accepts_valid_record():
    rt.schema_gate({"rec_id": "rec-1", "payload": "x"}, _SEMANTICS)
    rt.schema_gate({"rec_id": "rec-1"}, _SEMANTICS)  # payload nullable
    rt.schema_gate({"rec_id": "rec-1", "payload": None}, _SEMANTICS)


def test_schema_gate_raises_on_unknown_field():
    with pytest.raises(rt.SchemaGateError, match="unknown field"):
        rt.schema_gate({"rec_id": "rec-1", "bogus": "x"}, _SEMANTICS)


def test_schema_gate_raises_on_supplied_derived_field():
    with pytest.raises(rt.SchemaGateError, match="derived"):
        rt.schema_gate({"rec_id": "rec-1", "ulid": "01ABC"}, _SEMANTICS)


def test_schema_gate_raises_on_missing_required():
    with pytest.raises(rt.SchemaGateError, match="missing or null"):
        rt.schema_gate({"payload": "x"}, _SEMANTICS)


def test_schema_gate_raises_on_null_required():
    with pytest.raises(rt.SchemaGateError, match="missing or null"):
        rt.schema_gate({"rec_id": None, "payload": "x"}, _SEMANTICS)


def test_schema_gate_raises_on_mistyped_field():
    with pytest.raises(rt.SchemaGateError, match="expected str"):
        rt.schema_gate({"rec_id": 123}, _SEMANTICS)


def test_schema_gate_raises_on_empty_required():
    with pytest.raises(rt.SchemaGateError, match="empty"):
        rt.schema_gate({"rec_id": ""}, _SEMANTICS)


def test_schema_gate_loads_default_semantics(monkeypatch):
    monkeypatch.delenv(rt._FIELD_SEMANTICS_ENV, raising=False)
    rt.schema_gate({"rec_id": "rec-1", "payload": "x"})  # uses the real contract


# ---------------------------------------------------------------------------
# create_scd2_tables
# ---------------------------------------------------------------------------


def test_create_scd2_tables_applies_partitions():
    con = FakeCon()
    rt.create_scd2_tables(con)
    sqls = [s for s, _ in con.executed]
    assert any("SET PARTITIONED BY (day(created_timestamp))" in s for s in sqls)
    assert any("SET PARTITIONED BY (bucket(8, rec_id))" in s for s in sqls)
    assert not any(s.startswith("DROP TABLE") for s in sqls)


def test_create_scd2_tables_force_recreate_drops_first():
    con = FakeCon()
    rt.create_scd2_tables(con, force_recreate=True)
    sqls = [s for s, _ in con.executed]
    drops = [i for i, s in enumerate(sqls) if s.startswith("DROP TABLE")]
    creates = [i for i, s in enumerate(sqls) if s.startswith("CREATE TABLE")]
    assert len(drops) == 2
    assert min(drops) < min(creates)  # drops precede creates


# ---------------------------------------------------------------------------
# churn gate budget constants (rec-2091: single source in ducklake_runtime)
# ---------------------------------------------------------------------------


def test_churn_budget_constants_values():
    assert rt.COMMIT_LATENCY_BUDGET_MS == 2000.0
    assert rt.OCC_COLLISION_RATE_BUDGET == 0.20
    assert rt.CHURN_WRITERS == 4  # Decision 82: N steered 8->4; budget VALUES (above) unchanged
    assert rt.CHURN_WRITES_PER_WRITER == 5


# ---------------------------------------------------------------------------
# is_occ_collision / backoff
# ---------------------------------------------------------------------------


def test_is_occ_collision_true_and_false():
    assert rt.is_occ_collision(Exception("ERROR: could not serialize access")) is True
    assert rt.is_occ_collision(Exception("transaction conflict detected")) is True
    assert rt.is_occ_collision(Exception("relation does not exist")) is False


def test_occ_backoff_sleeps():
    slept: list[float] = []
    rt._occ_backoff(3, sleep=slept.append)
    assert len(slept) == 1
    assert 0.0 <= slept[0] <= rt.OCC_MAX_BACKOFF_S


# ---------------------------------------------------------------------------
# write_scd2 -- the core derivation + idempotency + OCC tests
# ---------------------------------------------------------------------------


def test_write_scd2_insert_path():
    con = FakeCon(created_lookup=[])  # no existing -> insert
    wid = rt.mint_write_identity(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = rt.write_scd2(con, {"rec_id": "rec-1", "payload": "v1"}, identity=wid, semantics=_SEMANTICS)
    assert result.ulid == wid.ulid
    assert result.created_timestamp == wid.timestamp
    assert result.occ_retries == 0
    # both MERGEs + COMMIT executed
    sqls = [s for s, _ in con.executed]
    assert any(rt.SMOKE_HISTORY_TABLE in s and s.startswith("MERGE") for s in sqls)
    assert any(rt.SMOKE_CURRENT_TABLE in s and s.startswith("MERGE") for s in sqls)
    assert sqls.count("COMMIT") == 1


def test_created_timestamp_carried_on_update():
    carried = datetime(2025, 12, 1, tzinfo=timezone.utc)
    con = FakeCon(created_lookup=[(carried,)])  # existing row -> update path carries created
    wid = rt.mint_write_identity(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = rt.write_scd2(con, {"rec_id": "rec-1", "payload": "v2"}, identity=wid, semantics=_SEMANTICS)
    # created carried from the existing row, NOT re-stamped to identity.timestamp
    assert result.created_timestamp == carried
    assert result.last_updated_timestamp == wid.timestamp
    # the history MERGE bound the carried created_timestamp (param index 3)
    hist_params = con.merge_history_params()[0]
    assert hist_params[3] == carried


def test_last_updated_minted_once():
    con = FakeCon(created_lookup=[], occ_fail_times=2)  # fail twice then succeed
    wid = rt.mint_write_identity(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    rt.write_scd2(con, {"rec_id": "rec-1"}, identity=wid, semantics=_SEMANTICS, sleep=lambda s: None)
    # last_updated_timestamp (param index 4) identical across every attempt
    last_updated = {tuple([p[4]]) for p in con.merge_history_params()}
    assert last_updated == {(wid.timestamp,)}


def test_ulid_minted_once_outside_retry():
    """The ULID is minted once and is the SAME across the lookup->merge->retry sequence."""
    con = FakeCon(created_lookup=[], occ_fail_times=3)
    wid = rt.mint_write_identity()
    rt.write_scd2(con, {"rec_id": "rec-1"}, identity=wid, semantics=_SEMANTICS, sleep=lambda s: None)
    ulids = {p[0] for p in con.merge_history_params()}
    assert ulids == {wid.ulid}  # identical on every attempt


def test_ulid_stable_across_retry():
    """A retried write reuses its ULID; the number of attempts equals fails+1, all same ULID."""
    con = FakeCon(created_lookup=[], occ_fail_times=2)
    wid = rt.mint_write_identity()
    rt.write_scd2(con, {"rec_id": "rec-1"}, identity=wid, semantics=_SEMANTICS, sleep=lambda s: None)
    attempts = con.merge_history_params()
    assert len(attempts) == 3  # 2 failures + 1 success
    assert all(p[0] == wid.ulid for p in attempts)


def test_write_scd2_mints_identity_when_absent():
    con = FakeCon(created_lookup=[])
    result = rt.write_scd2(con, {"rec_id": "rec-1"}, semantics=_SEMANTICS)
    assert len(result.ulid) == 26


def test_occ_retry_exhaustion_raises():
    con = FakeCon(created_lookup=[], occ_fail_times=99)  # always collide
    wid = rt.mint_write_identity()
    with pytest.raises(rt.OCCRetryExhaustedError, match="exhausted"):
        rt.write_scd2(con, {"rec_id": "rec-1"}, identity=wid, semantics=_SEMANTICS, max_attempts=3, sleep=lambda s: None)
    # ULID still minted once across all exhausted attempts
    assert {p[0] for p in con.merge_history_params()} == {wid.ulid}


def test_write_scd2_non_occ_error_propagates():
    con = FakeCon(created_lookup=[], hard_fail_substr=rt.SMOKE_HISTORY_TABLE)
    with pytest.raises(ValueError, match="hard failure"):
        rt.write_scd2(con, {"rec_id": "rec-1"}, semantics=_SEMANTICS)
    # rolled back, did not retry
    assert any(s == "ROLLBACK" for s, _ in con.executed)


def test_write_scd2_schema_gate_blocks_before_catalog():
    con = FakeCon(created_lookup=[])
    with pytest.raises(rt.SchemaGateError):
        rt.write_scd2(con, {"rec_id": "rec-1", "bogus": "x"}, semantics=_SEMANTICS)
    assert con.executed == []  # gate fires before any SQL


def test_write_scd2_emits_metrics():
    con = FakeCon(created_lookup=[], occ_fail_times=1)
    emitted: list[tuple[str, float]] = []
    rt.write_scd2(
        con,
        {"rec_id": "rec-1"},
        semantics=_SEMANTICS,
        metric_sink=lambda n, v: emitted.append((n, v)),
        sleep=lambda s: None,
    )
    names = {n for n, _ in emitted}
    assert names == {"OccRetryCount", "CommitLatencyMs"}
    occ = next(v for n, v in emitted if n == "OccRetryCount")
    assert occ == 1.0


def test_write_scd2_loads_default_semantics(monkeypatch):
    monkeypatch.delenv(rt._FIELD_SEMANTICS_ENV, raising=False)
    con = FakeCon(created_lookup=[])
    result = rt.write_scd2(con, {"rec_id": "rec-1", "payload": "x"})  # default contract
    assert result.rec_id == "rec-1"


# ---------------------------------------------------------------------------
# _safe_rollback / _emit_write_metrics
# ---------------------------------------------------------------------------


def test_safe_rollback_swallows_error():
    con = FakeCon(rollback_raises=True)
    rt._safe_rollback(con)  # must not raise


def test_emit_write_metrics_none_sink_noop():
    rt._emit_write_metrics(None, 1, 2.0)  # no raise, no-op


# ---------------------------------------------------------------------------
# read_current
# ---------------------------------------------------------------------------


def test_read_current_all():
    rows = [("01A", "rec-1", "p", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))]
    con = FakeCon(read_rows=rows)
    out = rt.read_current(con)
    assert out[0]["rec_id"] == "rec-1"
    assert out[0]["ulid"] == "01A"


def test_read_current_by_rec_id():
    con = FakeCon(read_rows=[])
    rt.read_current(con, rec_id="rec-1")
    sql = con.executed[-1][0]
    assert "WHERE rec_id = ?" in sql
    assert con.executed[-1][1] == ["rec-1"]


def test_read_current_with_limit():
    con = FakeCon(read_rows=[])
    rt.read_current(con, limit=5)
    assert "LIMIT 5" in con.executed[-1][0]


# ---------------------------------------------------------------------------
# emit_metric / make_metric_sink
# ---------------------------------------------------------------------------


def test_emit_metric_with_injected_client():
    calls = []

    class _CW:
        def put_metric_data(self, **kwargs):
            calls.append(kwargs)

    rt.emit_metric("OccRetryCount", 2.0, client=_CW())
    assert calls[0]["Namespace"] == rt.CLOUDWATCH_NAMESPACE
    assert calls[0]["MetricData"][0]["MetricName"] == "OccRetryCount"


def test_emit_metric_swallows_client_error():
    class _CW:
        def put_metric_data(self, **kwargs):
            raise RuntimeError("throttled")

    rt.emit_metric("X", 1.0, client=_CW())  # must not raise


def test_emit_metric_boto3_path(monkeypatch):
    calls = []

    class _CW:
        def put_metric_data(self, **kwargs):
            calls.append(kwargs)

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def client(self, name):
            return _CW()

    import boto3

    monkeypatch.setattr(boto3, "Session", _Session)
    rt.emit_metric("X", 1.0)
    assert len(calls) == 1


def test_make_metric_sink_units():
    captured = []

    class _CW:
        def put_metric_data(self, **kwargs):
            captured.append(kwargs["MetricData"][0])

    sink = rt.make_metric_sink(client=_CW())
    sink("CommitLatencyMs", 12.5)
    sink("OccRetryCount", 1.0)
    units = {d["MetricName"]: d["Unit"] for d in captured}
    assert units["CommitLatencyMs"] == "Milliseconds"
    assert units["OccRetryCount"] == "Count"


# ---------------------------------------------------------------------------
# T2.19: table-parameterized ops_* schemas (write/read/gate over the real tables)
# ---------------------------------------------------------------------------


def test_resolve_table_spec_smoke_is_backcompat():
    """table=None resolves the smoke pair with the historical column order (T2.17 back-compat)."""
    spec = rt.resolve_table_spec(None)
    assert spec.history_table == rt.SMOKE_HISTORY_TABLE
    assert spec.current_table == rt.SMOKE_CURRENT_TABLE
    assert spec.merge_key == "rec_id"
    assert [c for c, _ in spec.ordered_columns] == [
        "ulid",
        "rec_id",
        "payload",
        "created_timestamp",
        "last_updated_timestamp",
    ]


def test_resolve_table_spec_ops_recommendations():
    """ops_recommendations resolves merge_key=id, ulid-lead, timestamps-tail, id-bucket partition."""
    spec = rt.resolve_table_spec("ops_recommendations")
    assert spec.merge_key == "id"
    cols = [c for c, _ in spec.ordered_columns]
    assert cols[0] == "ulid"
    assert cols[1] == "id"  # merge key first among inputs
    assert cols[-2:] == ["created_timestamp", "last_updated_timestamp"]
    assert "bucket(8, id)" == spec.partition_current
    # array/int/bool columns are present with their real types
    assert spec.fields["dependencies"]["sql_type"] == "VARCHAR[]"
    assert spec.fields["automatable"]["sql_type"] == "BOOLEAN"
    assert spec.fields["execution_steps"]["sql_type"] == "BIGINT"


def test_resolve_table_spec_unknown_raises():
    with pytest.raises(rt.SchemaGateError, match="unknown ops table"):
        rt.resolve_table_spec("ops_not_a_table")


def test_py_type_map_extended_for_ops_columns():
    """The gate type map covers arrays/ints/booleans for the real ops columns (T2.19)."""
    assert rt._PY_TYPE_FOR_SQL["BIGINT"] is int
    assert rt._PY_TYPE_FOR_SQL["BOOLEAN"] is bool
    assert rt._PY_TYPE_FOR_SQL["VARCHAR[]"] is list
    assert rt._PY_TYPE_FOR_SQL["BIGINT[]"] is list


def test_schema_gate_ops_accepts_valid_record():
    """A valid ops_recommendations record (arrays, bool, int) passes the table-parameterized gate."""
    record = {
        "id": "rec-1",
        "status": "open",
        "title": "t",
        "automatable": True,
        "dependencies": ["rec-2", "rec-3"],
        "execution_steps": 4,
    }
    rt.schema_gate(record, table="ops_recommendations")  # no raise


def test_schema_gate_ops_rejects_unknown_field():
    with pytest.raises(rt.SchemaGateError, match="unknown field"):
        rt.schema_gate({"id": "rec-1", "status": "open", "bogus": "x"}, table="ops_recommendations")


def test_schema_gate_ops_rejects_derived_ulid():
    with pytest.raises(rt.SchemaGateError, match="derived"):
        rt.schema_gate({"id": "rec-1", "status": "open", "ulid": "01XYZ"}, table="ops_recommendations")


def test_schema_gate_ops_requires_merge_key_and_status():
    with pytest.raises(rt.SchemaGateError, match="missing or null"):
        rt.schema_gate({"status": "open"}, table="ops_recommendations")  # id missing


def test_schema_gate_ops_rejects_mistyped_bool():
    with pytest.raises(rt.SchemaGateError, match="expected bool"):
        rt.schema_gate({"id": "rec-1", "status": "open", "automatable": "yes"}, table="ops_recommendations")


def test_schema_gate_ops_rejects_mistyped_array():
    with pytest.raises(rt.SchemaGateError, match="expected list"):
        rt.schema_gate({"id": "rec-1", "status": "open", "tags": "not-a-list"}, table="ops_recommendations")


def test_build_merge_sql_ops_recommendations_uses_id_key():
    """The generated MERGE SQL targets the ops tables and keys current on id (not rec_id)."""
    spec = rt.resolve_table_spec("ops_recommendations")
    hist_sql = rt._build_merge_history_sql(spec)
    curr_sql = rt._build_merge_current_sql(spec)
    assert "ops_recommendations_history" in hist_sql
    assert "ON t.ulid = s.ulid" in hist_sql
    assert "ops_recommendations_current" in curr_sql
    assert "ON t.id = s.id" in curr_sql
    # created_timestamp is carried, never in the UPDATE SET; id (merge key) is not updated either.
    assert "created_timestamp = s.created_timestamp" not in curr_sql
    assert "id = s.id" not in curr_sql.split("WHEN MATCHED THEN UPDATE SET")[1].split("WHEN NOT MATCHED")[0]


def test_write_scd2_ops_binds_columns_in_order(monkeypatch):
    """write_scd2(table=...) binds ulid, then inputs (id first), then created/updated -- in column order."""
    con = FakeCon(created_lookup=None)  # insert path (no existing row)
    moment = datetime(2026, 6, 8, tzinfo=timezone.utc)
    identity = rt.mint_write_identity(now=moment)
    record = {"id": "rec-1", "status": "open", "title": "t", "automatable": False, "execution_steps": 2}
    result = rt.write_scd2(con, record, table="ops_recommendations", identity=identity)
    assert result.rec_id == "rec-1"
    # The history MERGE params: positional, matching ordered_columns.
    spec = rt.resolve_table_spec("ops_recommendations")
    ordered = [c for c, _ in spec.ordered_columns]
    hist_params = [p for sql, p in con.executed if "ops_recommendations_history" in sql and sql.startswith("MERGE INTO")]
    assert len(hist_params) == 1
    params = hist_params[0]
    assert params[0] == identity.ulid
    assert params[ordered.index("id")] == "rec-1"
    assert params[ordered.index("status")] == "open"
    assert params[ordered.index("created_timestamp")] == moment
    assert params[ordered.index("last_updated_timestamp")] == moment


def test_write_scd2_ops_require_exists_loud_fails_on_absent():
    """update path (require_exists=True) raises ReferentialError when the merge key is absent."""
    con = FakeCon(created_lookup=None)  # no existing current row
    record = {"id": "rec-absent", "status": "closed"}
    with pytest.raises(rt.ReferentialError, match="absent"):
        rt.write_scd2(con, record, table="ops_recommendations", require_exists=True)
    # The MERGE must NOT have run (rolled back before any write).
    merged = [sql for sql, _ in con.executed if sql.startswith("MERGE INTO")]
    assert merged == []


def test_write_scd2_ops_require_exists_proceeds_when_present():
    """update path proceeds and carries the original created_timestamp when the row exists."""
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    con = FakeCon(created_lookup=[(original,)])  # existing current row
    record = {"id": "rec-1", "status": "closed"}
    result = rt.write_scd2(con, record, table="ops_recommendations", require_exists=True)
    assert result.created_timestamp == original  # carried, not re-stamped
    assert any(sql.startswith("MERGE INTO") for sql, _ in con.executed)


def test_create_scd2_tables_ops_ddl_has_real_types(monkeypatch):
    con = FakeCon()
    rt.create_scd2_tables(con, table="ops_decisions", force_recreate=True)
    ddl = [sql for sql, _ in con.executed if sql.startswith("CREATE TABLE")]
    assert any("ops_decisions_history" in s for s in ddl)
    assert any("related_decisions BIGINT[]" in s for s in ddl)
    assert any("decision_id BIGINT" in s for s in ddl)
    # partition ALTERs applied before first write
    alters = [sql for sql, _ in con.executed if "SET PARTITIONED BY" in sql]
    assert any("bucket(8, id)" in s for s in alters)


def test_ops_table_names_lists_all_five():
    names = rt.ops_table_names()
    assert "ops_recommendations" in names
    assert "ops_decisions" in names
    assert "ops_priority_queue" in names
    assert len(names) == 5


def test_read_current_ops_table_projects_and_filters():
    """read_current(table=...) selects the ops column set and filters on the merge key."""
    rows = [("01U", "rec-1", "open")]

    class _Cur:
        description = [("ulid",), ("id",), ("status",)]

        def __init__(self):
            self.sql = ""
            self.params = None

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params
            return self

        def fetchall(self):
            return rows

    con = _Cur()
    out = rt.read_current(con, table="ops_recommendations", key="rec-1", limit=10)
    assert "ops_recommendations_current" in con.sql
    assert "WHERE id = ?" in con.sql and "LIMIT 10" in con.sql
    assert con.params == ["rec-1"]
    assert out == [{"ulid": "01U", "id": "rec-1", "status": "open"}]


def test_read_history_orders_newest_first():
    class _Cur:
        description = [("ulid",)]

        def __init__(self):
            self.sql = ""

        def execute(self, sql, params=None):
            self.sql = sql
            return self

        def fetchall(self):
            return [("01B",), ("01A",)]

    con = _Cur()
    out = rt.read_history(con, table="ops_decisions", key="dec-1")
    assert "ops_decisions_history" in con.sql
    assert "ORDER BY last_updated_timestamp DESC" in con.sql
    assert out == [{"ulid": "01B"}, {"ulid": "01A"}]


def test_query_current_substitutes_tbl():
    class _Cur:
        description = [("violation",)]

        def __init__(self):
            self.sql = ""

        def execute(self, sql, params=None):
            self.sql = sql
            return self

        def fetchall(self):
            return [(0,)]

    con = _Cur()
    out = rt.query_current(con, table="ops_recommendations", sql="SELECT COUNT(*) violation FROM {tbl}")
    assert "ops_catalog.ops_recommendations_current" in con.sql
    assert out == [{"violation": 0}]


# ---------------------------------------------------------------------------
# Closed-boundary read-only verb guard (code-review Critical #1)
# ---------------------------------------------------------------------------


def test_assert_read_only_sql_allows_select_and_with():
    rt.assert_read_only_sql("SELECT 1 FROM {tbl}")
    rt.assert_read_only_sql("  with x as (select 1) select * from x")  # case-insensitive, leading ws


@pytest.mark.parametrize(
    "bad",
    [
        "DROP TABLE ops_catalog.ops_recommendations_current",
        "DELETE FROM {tbl}",
        "ALTER TABLE {tbl} ADD COLUMN x INT",
        "UPDATE {tbl} SET status='x'",
        "INSERT INTO {tbl} VALUES (1)",
    ],
)
def test_assert_read_only_sql_rejects_writes(bad):
    with pytest.raises(rt.SchemaGateError, match="read-only boundary"):
        rt.assert_read_only_sql(bad)


def test_assert_read_only_sql_rejects_multistatement():
    with pytest.raises(rt.SchemaGateError, match="multi-statement"):
        rt.assert_read_only_sql("SELECT 1; DROP TABLE x")


def test_query_current_enforces_read_only():
    class _Cur:
        description = [("v",)]

        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return [(0,)]

    with pytest.raises(rt.SchemaGateError, match="read-only boundary"):
        rt.query_current(_Cur(), table="ops_recommendations", sql="DROP TABLE {tbl}")
