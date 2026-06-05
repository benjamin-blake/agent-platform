"""Tests for scripts/ducklake_neon_smoke_test.py (T2.16b / CD.34 DuckLake Neon smoke test).

100% line coverage with ALL network mocked -- no live boto3 / duckdb / pg_dump / psql calls. The live
proof is the [post-deploy] verification-plan steps; these tests prove the orchestration + loud-fail
logic, not the live endpoint.
"""

from __future__ import annotations

import json
import types

import pytest

import scripts.ducklake_neon_smoke_test as smoke

_DSN = {
    "host": "ep-test-123.eu-west-2.aws.neon.tech",
    "dbname": "ducklake_ops",
    "username": "ducklake_ops",
    "password": "secret-pw",  # pragma: allowlist secret -- fake fixture value, not a real credential
    "sslmode": "require",
    "meta_schema": "ducklake_ops",
}


class FakeCon:
    """Minimal DuckDB-connection double: records executed SQL, optional per-substring raises."""

    def __init__(self, fetch_results=None, raise_on=None):
        self.executed: list[str] = []
        self._fetch_results = fetch_results if fetch_results is not None else []
        self._raise_on = raise_on or {}
        self.closed = False

    def execute(self, sql):
        for sub, exc in self._raise_on.items():
            if sub in sql:
                raise exc
        self.executed.append(sql)
        return self

    def fetchall(self):
        return self._fetch_results

    def close(self):
        self.closed = True


def _completed(returncode=0, stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# fetch_dsn
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
    out = smoke.fetch_dsn(profile="agent_platform")
    assert out["host"] == _DSN["host"]
    assert captured["secret_id"] == smoke.DSN_SECRET_ID
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
        smoke.fetch_dsn()


# ---------------------------------------------------------------------------
# _libpq_conninfo / _dsn_uri
# ---------------------------------------------------------------------------


def test_libpq_conninfo_uses_explicit_sslmode():
    out = smoke._libpq_conninfo(_DSN)
    assert "sslmode=require" in out
    assert "host=ep-test-123.eu-west-2.aws.neon.tech" in out


def test_libpq_conninfo_defaults_sslmode_when_absent():
    dsn = {k: v for k, v in _DSN.items() if k != "sslmode"}
    assert "sslmode=require" in smoke._libpq_conninfo(dsn)


def test_dsn_uri_default_and_explicit_sslmode():
    assert smoke._dsn_uri(_DSN).startswith("postgresql://ducklake_ops:secret-pw@")  # pragma: allowlist secret
    no_ssl = {k: v for k, v in _DSN.items() if k != "sslmode"}
    assert smoke._dsn_uri(no_ssl).endswith("?sslmode=require")


# ---------------------------------------------------------------------------
# _open_attached
# ---------------------------------------------------------------------------


def test_open_attached_delegates_to_runtime(monkeypatch):
    """_open_attached now delegates to ducklake_runtime.open_connection (single ATTACH impl)."""
    con = FakeCon()
    captured = {}

    def fake_open(**kwargs):
        captured.update(kwargs)
        return con

    monkeypatch.setattr(smoke.ducklake_runtime, "open_connection", fake_open)
    out = smoke._open_attached(_DSN, profile="agent_platform")
    assert out is con
    assert captured["dsn"] is _DSN
    assert captured["extension_directory"] is None  # dev/smoke mode = network INSTALL
    assert captured["profile"] == "agent_platform"
    assert captured["data_path"] == smoke.SMOKE_DATA_PATH


def test_open_attached_real_attach_composition(monkeypatch):
    """Through the real runtime: dev-mode INSTALL + a single ATTACH with META_SCHEMA."""
    con = FakeCon()
    fake_duckdb = types.SimpleNamespace(connect=lambda: con, __version__="1.5.3")
    monkeypatch.setattr(smoke.ducklake_runtime.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    monkeypatch.setattr(smoke.ducklake_runtime.ducklake_spike, "_set_s3_credentials", lambda c, profile=None: None)
    smoke._open_attached(_DSN, profile=None)
    attach_sql = [s for s in con.executed if s.startswith("ATTACH")]
    assert len(attach_sql) == 1
    assert "ducklake:postgres:" in attach_sql[0]
    assert "META_SCHEMA 'ducklake_ops'" in attach_sql[0]
    assert any("INSTALL postgres" in s for s in con.executed)


# ---------------------------------------------------------------------------
# attach_roundtrip
# ---------------------------------------------------------------------------


def test_attach_roundtrip_with_explicit_dsn(monkeypatch):
    con = FakeCon(fetch_results=[(1,)])
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    assert smoke.attach_roundtrip(dsn=_DSN) == 1
    assert con.closed is True


def test_attach_roundtrip_fetches_dsn_when_absent(monkeypatch):
    con = FakeCon(fetch_results=[(1,)])
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    assert smoke.attach_roundtrip() == 1


# ---------------------------------------------------------------------------
# OCC classification + single writer
# ---------------------------------------------------------------------------


def test_is_occ_collision_true_and_false():
    assert smoke._is_occ_collision(Exception("ERROR: could not serialize access")) is True
    assert smoke._is_occ_collision(Exception("relation does not exist")) is False


def test_single_writer_commit_clean(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    out = smoke._single_writer_commit(0, _DSN)
    assert out["collided"] is False
    assert con.closed is True
    assert sum(1 for s in con.executed if s.startswith("INSERT")) == smoke.CHURN_WRITES_PER_WRITER


def test_single_writer_commit_counts_occ_collision(monkeypatch):
    con = FakeCon(raise_on={"INSERT": Exception("could not serialize access due to concurrent update")})
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    out = smoke._single_writer_commit(1, _DSN)
    assert out["collided"] is True
    assert con.closed is True


def test_single_writer_commit_reraises_non_occ(monkeypatch):
    con = FakeCon(raise_on={"INSERT": ValueError("hard failure -- not a collision")})
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    with pytest.raises(ValueError, match="hard failure"):
        smoke._single_writer_commit(2, _DSN)
    assert con.closed is True


# ---------------------------------------------------------------------------
# burst + evaluation
# ---------------------------------------------------------------------------


def test_run_churn_burst_invokes_worker_per_writer():
    seen = []

    def fake_worker(i, dsn, profile=None, _creds=None):
        seen.append(i)
        return {"latency_ms": 1.0, "collided": False}

    results = smoke._run_churn_burst(_DSN, writers=3, worker=fake_worker)
    assert len(results) == 3
    assert sorted(seen) == [0, 1, 2]


def test_p95_empty_and_nonempty():
    assert smoke._p95([]) == 0.0
    assert smoke._p95([10.0, 20.0, 30.0, 40.0]) == 40.0


def test_evaluate_churn_pass():
    results = [{"latency_ms": 10.0, "collided": False} for _ in range(8)]
    passed, metrics = smoke._evaluate_churn(results)
    assert passed is True
    assert metrics["collision_rate"] == 0.0
    assert metrics["writers"] == 8.0


def test_evaluate_churn_fails_on_collision_rate():
    results = [{"latency_ms": 10.0, "collided": True} for _ in range(3)] + [{"latency_ms": 10.0, "collided": False}]
    passed, metrics = smoke._evaluate_churn(results)
    assert passed is False
    assert metrics["collision_rate"] == 0.75


def test_evaluate_churn_fails_on_latency():
    results = [{"latency_ms": smoke.COMMIT_LATENCY_BUDGET_MS + 1.0, "collided": False} for _ in range(4)]
    passed, _ = smoke._evaluate_churn(results)
    assert passed is False


def test_evaluate_churn_empty_passes():
    passed, metrics = smoke._evaluate_churn([])
    assert passed is True
    assert metrics["collision_rate"] == 0.0
    assert metrics["p95_latency_ms"] == 0.0


# ---------------------------------------------------------------------------
# churn_gate
# ---------------------------------------------------------------------------


def _stub_churn_gate_prelude(monkeypatch):
    """Stub the pre-warm + STS-prefetch prelude that churn_gate runs before the burst.

    churn_gate now opens one connection (pre-warm) and resolves AWS credentials once before
    spawning the 8 concurrent workers (STS-contention fix). Tests mock both to keep the unit
    test offline.
    """
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None, _creds=None: FakeCon())

    class _FrozenCreds:
        access_key = "ak"  # pragma: allowlist secret
        secret_key = "sk"  # pragma: allowlist secret
        token = None

    class _Session:
        region_name = "eu-west-2"

        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return types.SimpleNamespace(get_frozen_credentials=lambda: _FrozenCreds())

    import boto3

    monkeypatch.setattr(boto3, "Session", _Session)


def test_churn_gate_pass_returns_metrics(monkeypatch):
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False} for _ in range(8)],
    )
    metrics = smoke.churn_gate(dsn=_DSN)
    assert metrics["collision_rate"] == 0.0


def test_churn_gate_fetches_dsn_when_absent(monkeypatch):
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(
        smoke, "_run_churn_burst", lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False}]
    )
    assert smoke.churn_gate()["collision_rate"] == 0.0


def test_churn_gate_loud_fails(monkeypatch):
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 1.0, "collided": True} for _ in range(8)],
    )
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN_GATE FAIL"):
        smoke.churn_gate(dsn=_DSN)


# ---------------------------------------------------------------------------
# _engine_tag / _run
# ---------------------------------------------------------------------------


def test_engine_tag_with_version(monkeypatch):
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__="1.5.3"))
    assert smoke._engine_tag() == "duckdb-1.5.3"


def test_engine_tag_without_version(monkeypatch):
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace())
    assert smoke._engine_tag() == "duckdb-unknown"


def test_run_passes_text_flags(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed(0)

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    out = smoke._run(["pg_dump", "--version"])
    assert out.returncode == 0
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"
    assert captured["kwargs"]["check"] is False


# ---------------------------------------------------------------------------
# pg_dump / restore subprocess wrappers
# ---------------------------------------------------------------------------


def test_consistent_pg_dump_success(monkeypatch):
    monkeypatch.setattr(smoke, "_run", lambda cmd: _completed(0))
    assert smoke._consistent_pg_dump(_DSN, engine_tag="duckdb-1.5.3", dump_path="/tmp/x.sql") == "/tmp/x.sql"


def test_consistent_pg_dump_loud_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_run", lambda cmd: _completed(1, stderr="permission denied"))
    with pytest.raises(smoke.SmokeTestFailure, match="pg_dump"):
        smoke._consistent_pg_dump(_DSN, engine_tag="t", dump_path="/tmp/x.sql")


def test_restore_dump_success(monkeypatch):
    monkeypatch.setattr(smoke, "_run", lambda cmd: _completed(0))
    smoke._restore_dump("/tmp/x.sql", _DSN)  # no raise


def test_restore_dump_loud_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_run", lambda cmd: _completed(2, stderr="syntax error"))
    with pytest.raises(smoke.SmokeTestFailure, match="psql restore"):
        smoke._restore_dump("/tmp/x.sql", _DSN)


# ---------------------------------------------------------------------------
# probe write/verify + scratch derive
# ---------------------------------------------------------------------------


def test_write_probe_creates_and_inserts(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    smoke._write_probe(_DSN, "tok-abc")
    assert any("CREATE TABLE" in s and "restore_probe" in s for s in con.executed)
    assert any("INSERT" in s and "tok-abc" in s for s in con.executed)
    assert con.closed is True


def test_verify_probe_found(monkeypatch):
    con = FakeCon(fetch_results=[("tok-abc",)])
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    assert smoke._verify_probe(_DSN, "tok-abc") is True
    assert con.closed is True


def test_verify_probe_missing(monkeypatch):
    con = FakeCon(fetch_results=[])
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    assert smoke._verify_probe(_DSN, "tok-abc") is False


def test_derive_scratch_dsn_suffixes_dbname():
    scratch = smoke._derive_scratch_dsn(_DSN)
    assert scratch["dbname"] == "ducklake_ops_restore_drill"
    assert scratch["host"] == _DSN["host"]
    assert _DSN["dbname"] == "ducklake_ops"  # original not mutated


# ---------------------------------------------------------------------------
# restore_drill
# ---------------------------------------------------------------------------


def test_restore_drill_success_explicit_dsns(monkeypatch):
    monkeypatch.setattr(smoke, "_engine_tag", lambda: "duckdb-1.5.3")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill(dsn=_DSN, scratch_dsn=smoke._derive_scratch_dsn(_DSN)) is True


def test_restore_drill_defaults_dsn_and_scratch(monkeypatch):
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(smoke, "_engine_tag", lambda: "duckdb-1.5.3")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill() is True


def test_restore_drill_loud_fails_on_lost_probe(monkeypatch):
    monkeypatch.setattr(smoke, "_engine_tag", lambda: "duckdb-1.5.3")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: False)
    with pytest.raises(smoke.SmokeTestFailure, match="read-your-write probe missing"):
        smoke.restore_drill(dsn=_DSN)


# ---------------------------------------------------------------------------
# main dispatch
# ---------------------------------------------------------------------------


def test_main_attach(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "attach_roundtrip", lambda profile=None: 1)
    assert smoke.main(["--attach"]) == 0
    assert "ATTACH OK rows=1" in capsys.readouterr().out


def test_main_churn_gate(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "churn_gate", lambda profile=None: {"collision_rate": 0.1, "p95_latency_ms": 12.0})
    assert smoke.main(["--churn-gate"]) == 0
    assert "CHURN_GATE PASS" in capsys.readouterr().out


def test_main_restore_drill(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "restore_drill", lambda profile=None: True)
    assert smoke.main(["--restore-drill"]) == 0
    assert "RESTORE_OK read-your-write verified" in capsys.readouterr().out


def test_main_loud_fail_returns_1(monkeypatch, capsys):
    def _boom(profile=None):
        raise smoke.SmokeTestFailure("CHURN_GATE FAIL: over budget")

    monkeypatch.setattr(smoke, "churn_gate", _boom)
    assert smoke.main(["--churn-gate"]) == 1
    assert "CHURN_GATE FAIL" in capsys.readouterr().err


def test_main_requires_a_mode():
    with pytest.raises(SystemExit):
        smoke.main([])


# ---------------------------------------------------------------------------
# In-Lambda invoke gates (T2.17) -- URL resolution, SigV4 invoke, gate assertions
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def test_function_url_from_env(monkeypatch):
    monkeypatch.setenv(smoke.WRITER_URL_ENV, "https://writer.lambda-url/")
    assert smoke._function_url("writer") == "https://writer.lambda-url"


def test_function_url_from_terraform(monkeypatch):
    monkeypatch.delenv(smoke.READER_URL_ENV, raising=False)
    monkeypatch.setattr(
        smoke.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="https://reader.url\n", stderr=""),
    )
    assert smoke._function_url("reader") == "https://reader.url"


def test_function_url_missing_raises(monkeypatch):
    monkeypatch.delenv(smoke.WRITER_URL_ENV, raising=False)
    monkeypatch.setattr(smoke.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(smoke.SmokeTestFailure, match="cannot reach"):
        smoke._function_url("writer")


def test_sigv4_invoke_signs(monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["headers"] = headers
        return _Resp(200, {"ok": True})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    class _FC:
        access_key = "ak"  # pragma: allowlist secret
        secret_key = "sk"  # pragma: allowlist secret
        token = None

    class _Session:
        def __init__(self, profile_name=None):
            pass

        def get_credentials(self):
            return types.SimpleNamespace(get_frozen_credentials=lambda: _FC())

    import boto3

    monkeypatch.setattr(boto3, "Session", _Session)
    resp = smoke._sigv4_invoke("https://x", {"action": "attach_check"}, sign=True)
    assert resp.status_code == 200
    assert "Authorization" in captured["headers"]  # SigV4 added an Authorization header


def test_sigv4_invoke_unsigned(monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["headers"] = headers
        return _Resp(403)

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    resp = smoke._sigv4_invoke("https://x", {"action": "attach_check"}, sign=False)
    assert resp.status_code == 403
    assert "Authorization" not in captured["headers"]


def test_ok_json_status_mismatch_raises():
    with pytest.raises(smoke.SmokeTestFailure, match="unexpected status"):
        smoke._ok_json(_Resp(500, text="boom"))


def _patch_gate(monkeypatch, payload, status=200):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(status, payload))


def test_lambda_attach_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"version": "1.5.3", "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
    smoke.lambda_attach()
    assert "LAMBDA_ATTACH OK version=1.5.3 source=layer" in capsys.readouterr().out


def test_lambda_attach_wrong_version_fails(monkeypatch):
    _patch_gate(monkeypatch, {"version": "1.5.2", "source": "layer", "connect_ms": 1, "commit_ms": 1})
    with pytest.raises(smoke.SmokeTestFailure, match="LAMBDA_ATTACH FAIL"):
        smoke.lambda_attach()


def test_lambda_ingress_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: "https://w")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(200 if kw.get("sign", True) else 403))
    smoke.lambda_ingress()
    assert "INGRESS OK unsigned=403 signed=200" in capsys.readouterr().out


def test_lambda_ingress_fails_when_unsigned_allowed(monkeypatch):
    monkeypatch.setattr(smoke, "_function_url", lambda role: "https://w")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(200))  # unsigned also 200
    with pytest.raises(smoke.SmokeTestFailure, match="INGRESS FAIL"):
        smoke.lambda_ingress()


def test_lambda_idempotency_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"ulid_reused": True, "history_rows": 1, "current_rows": 1})
    smoke.lambda_idempotency()
    assert "IDEMPOTENCY OK ulid_reused=true history_rows=1 current_rows=1" in capsys.readouterr().out


def test_lambda_idempotency_fails(monkeypatch):
    _patch_gate(monkeypatch, {"ulid_reused": True, "history_rows": 2, "current_rows": 1})
    with pytest.raises(smoke.SmokeTestFailure, match="IDEMPOTENCY FAIL"):
        smoke.lambda_idempotency()


def test_lambda_partition_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {
        "history_pruned": True, "history_files_scanned": 1, "history_total": 3,
        "current_partitions_scanned": 1, "current_files_scanned": 1, "current_total": 4,
    })
    smoke.lambda_partition()
    assert "PARTITION OK history_pruned=true" in capsys.readouterr().out


def test_lambda_partition_fails(monkeypatch):
    _patch_gate(monkeypatch, {
        "history_pruned": False, "history_files_scanned": 3, "history_total": 3,
        "current_partitions_scanned": 2, "current_files_scanned": 4, "current_total": 4,
    })
    with pytest.raises(smoke.SmokeTestFailure, match="PARTITION FAIL"):
        smoke.lambda_partition()


def test_lambda_inlining_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"inlined_rows": 0, "s3_parquet": 2, "occ_conflicts_handled": True})
    smoke.lambda_inlining()
    assert "INLINING OK inlined_rows=0 s3_parquet=2" in capsys.readouterr().out


def test_lambda_inlining_fails(monkeypatch):
    _patch_gate(monkeypatch, {"inlined_rows": 5, "s3_parquet": 0, "occ_conflicts_handled": True})
    with pytest.raises(smoke.SmokeTestFailure, match="INLINING FAIL"):
        smoke.lambda_inlining()


def test_lambda_loudfail_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"schema_reject": "raised", "occ_exhaust": "raised", "silent_drop": False})
    smoke.lambda_loudfail()
    assert "LOUDFAIL OK schema_reject=raised occ_exhaust=raised silent_drop=false" in capsys.readouterr().out


def test_lambda_loudfail_fails(monkeypatch):
    _patch_gate(monkeypatch, {"schema_reject": "not_raised", "occ_exhaust": "raised", "silent_drop": False})
    with pytest.raises(smoke.SmokeTestFailure, match="LOUDFAIL FAIL"):
        smoke.lambda_loudfail()


def test_lambda_churn_ok(monkeypatch, capsys):
    _patch_gate(monkeypatch, {"collision_rate": 0.0, "p95_commit_ms": 500.0, "endpoint": "direct", "within_budget": True})
    smoke.lambda_churn()
    assert "CHURN OK collision_rate=0.0 p95_commit_ms=500.0 endpoint=direct" in capsys.readouterr().out


def test_lambda_churn_over_budget_fails(monkeypatch):
    _patch_gate(monkeypatch, {"collision_rate": 0.0, "p95_commit_ms": 5000.0, "endpoint": "direct", "within_budget": False})
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN FAIL"):
        smoke.lambda_churn()


def test_lambda_reader_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": True})

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    smoke.lambda_reader()
    assert "READER OK rows=3 write_denied=true" in capsys.readouterr().out


def test_lambda_reader_boundary_broken_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": False})  # boundary broken

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="READER FAIL"):
        smoke.lambda_reader()


def test_main_lambda_attach_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "lambda_attach", lambda profile=None, region="eu-west-2": print("LAMBDA_ATTACH OK stub"))
    assert smoke.main(["--lambda-attach"]) == 0
    assert "LAMBDA_ATTACH OK" in capsys.readouterr().out


def test_main_lambda_gate_loud_fail_returns_1(monkeypatch, capsys):
    def _boom(profile=None, region="eu-west-2"):
        raise smoke.SmokeTestFailure("READER FAIL: boundary")

    monkeypatch.setattr(smoke, "lambda_reader", _boom)
    assert smoke.main(["--lambda-reader"]) == 1
    assert "READER FAIL" in capsys.readouterr().err
