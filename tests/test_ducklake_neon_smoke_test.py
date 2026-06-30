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
from src.common.ducklake_version import pinned_duckdb_version

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
    fake_duckdb = types.SimpleNamespace(connect=lambda: con, __version__=pinned_duckdb_version())
    monkeypatch.setattr(smoke.ducklake_runtime.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    monkeypatch.setattr(smoke.ducklake_runtime.ducklake_spike, "_set_s3_credentials", lambda c, profile=None: None)
    smoke._open_attached(_DSN, profile=None)
    attach_sql = [s for s in con.executed if s.startswith("ATTACH")]
    assert len(attach_sql) == 1
    assert "ducklake:postgres:" in attach_sql[0]
    # Smoke attaches its OWN meta-schema (rec-2099) -- never the production ducklake_ops catalog.
    assert "META_SCHEMA 'ducklake_smoke'" in attach_sql[0]
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
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False} for _ in range(8)],
    )
    metrics = smoke.churn_gate(dsn=_DSN)
    assert metrics["collision_rate"] == 0.0


def test_churn_gate_fetches_dsn_when_absent(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(
        smoke, "_run_churn_burst", lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False}]
    )
    assert smoke.churn_gate()["collision_rate"] == 0.0


def test_churn_gate_loud_fails(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
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
    pin = pinned_duckdb_version()
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__=pin))
    assert smoke._engine_tag() == f"duckdb-{pin}"


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
    assert (
        smoke._consistent_pg_dump(_DSN, engine_tag=f"duckdb-{pinned_duckdb_version()}", dump_path="/tmp/x.sql") == "/tmp/x.sql"
    )


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
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(smoke, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill(dsn=_DSN, scratch_dsn=smoke._derive_scratch_dsn(_DSN)) is True


def test_restore_drill_defaults_dsn_and_scratch(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(smoke, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill() is True


def test_restore_drill_loud_fails_on_lost_probe(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(smoke, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
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
        smoke.subprocess,
        "run",
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
    pin = pinned_duckdb_version()
    _patch_gate(monkeypatch, {"version": pin, "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
    smoke.lambda_attach()
    assert f"LAMBDA_ATTACH OK version={pin} source=layer" in capsys.readouterr().out


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
    _patch_gate(
        monkeypatch,
        {
            "history_pruned": True,
            "history_files_scanned": 1,
            "history_total": 3,
            "current_partitions_scanned": 1,
            "current_files_scanned": 1,
            "current_total": 4,
        },
    )
    smoke.lambda_partition()
    assert "PARTITION OK history_pruned=true" in capsys.readouterr().out


def test_lambda_partition_fails(monkeypatch):
    _patch_gate(
        monkeypatch,
        {
            "history_pruned": False,
            "history_files_scanned": 3,
            "history_total": 3,
            "current_partitions_scanned": 2,
            "current_files_scanned": 4,
            "current_total": 4,
        },
    )
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


def _churn_single_body(**kw) -> dict:
    """Default per-invocation churn_single response body for fan-out lambda_churn tests."""
    base = {
        "ok": True,
        "latency_ms": 500.0,
        "collided": False,
        "connect_ms": 120.0,
        "commit_ms": 380.0,
        "cpu_ms": 200.0,
        "occ_retries": 0,
        "wall_ms": 500.0,
    }
    base.update(kw)
    return base


def _patch_fanout_churn(monkeypatch, per_invocation_body=None):
    """Patch _function_url + _sigv4_invoke for the fan-out lambda_churn (including pre-warm phase).

    Handles three payload types: attach_check (pre-warm), churn_single setup=True, churn_single normal.
    """
    monkeypatch.setattr(smoke, "_function_url", lambda role: "https://writer")
    body = per_invocation_body or _churn_single_body()

    def fake_invoke(url, payload, **kw):
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        return _Resp(200, body)

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)


def test_lambda_churn_fanout_ok(monkeypatch, capsys):
    _patch_fanout_churn(monkeypatch)
    smoke.lambda_churn()
    out = capsys.readouterr().out
    assert "CHURN OK collision_rate=0.0 p95_commit_ms=500.0 endpoint=direct" in out
    assert "within_budget=True" in out
    assert "wall_cpu_ratio=2.5" in out


def test_lambda_churn_fanout_n_concurrent_calls(monkeypatch):
    """CHURN_WRITERS pre-warm + 1 setup + CHURN_WRITERS fan-out calls are issued in order."""
    call_payloads: list[dict] = []
    monkeypatch.setattr(smoke, "_function_url", lambda role: "https://writer")

    def fake_invoke(url, payload, **kw):
        call_payloads.append(dict(payload))
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        return _Resp(200, _churn_single_body())

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    smoke.lambda_churn()
    prewarm_calls = [p for p in call_payloads if p.get("action") == "attach_check"]
    setup_calls = [p for p in call_payloads if p.get("setup")]
    normal_calls = [p for p in call_payloads if not p.get("setup") and p.get("action") != "attach_check"]
    assert len(prewarm_calls) == smoke.CHURN_WRITERS
    assert len(setup_calls) == 1
    assert len(normal_calls) == smoke.CHURN_WRITERS
    assert all(p.get("action") == "churn_single" for p in normal_calls)
    assert sorted(p.get("writer_id") for p in normal_calls) == list(range(smoke.CHURN_WRITERS))


def test_lambda_churn_fanout_aggregation_breakdown(monkeypatch, capsys):
    """Aggregated breakdown fields are computed correctly from N per-invocation bodies."""
    _patch_fanout_churn(monkeypatch, _churn_single_body(connect_ms=120.0, cpu_ms=200.0, wall_ms=500.0))
    smoke.lambda_churn()
    out = capsys.readouterr().out
    assert "p95_connect_ms=120.0" in out
    assert "wall_cpu_ratio=2.5" in out
    assert "total_occ_retries=0" in out


def test_lambda_churn_fanout_collision_rate_loudfail(monkeypatch):
    """Collision rate over budget triggers SmokeTestFailure."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: "https://writer")
    idx = [0]

    def fake_invoke(url, payload, **kw):
        if payload.get("action") == "attach_check":
            return _Resp(200, {"version": pinned_duckdb_version(), "source": "layer", "connect_ms": 12.0, "commit_ms": 3.0})
        if payload.get("setup"):
            return _Resp(200, {"ok": True, "setup": True})
        collided = idx[0] < (smoke.CHURN_WRITERS // 2 + 1)
        idx[0] += 1
        return _Resp(200, _churn_single_body(collided=collided))

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN FAIL"):
        smoke.lambda_churn()


def test_lambda_churn_fanout_latency_loudfail(monkeypatch):
    """p95 wall latency over budget triggers SmokeTestFailure."""
    _patch_fanout_churn(
        monkeypatch,
        _churn_single_body(latency_ms=smoke.COMMIT_LATENCY_BUDGET_MS + 1.0, wall_ms=smoke.COMMIT_LATENCY_BUDGET_MS + 1.0),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN FAIL"):
        smoke.lambda_churn()


def test_churn_constants_imported_from_runtime():
    from src.common import ducklake_runtime

    assert smoke.OCC_COLLISION_RATE_BUDGET == ducklake_runtime.OCC_COLLISION_RATE_BUDGET
    assert smoke.COMMIT_LATENCY_BUDGET_MS == ducklake_runtime.COMMIT_LATENCY_BUDGET_MS
    assert smoke.CHURN_WRITERS == ducklake_runtime.CHURN_WRITERS
    assert smoke.CHURN_WRITES_PER_WRITER == ducklake_runtime.CHURN_WRITES_PER_WRITER


def test_lambda_churn_incontainer_prints_breakdown(monkeypatch, capsys):
    """lambda_churn_incontainer prints diagnostic breakdown and does NOT raise on over-budget."""
    _patch_gate(
        monkeypatch,
        {
            "collision_rate": 0.0,
            "p95_commit_ms": 8780.0,
            "within_budget": False,
            "endpoint": "direct",
            "breakdown": {
                "wall_cpu_ratio": 10.35,
                "p95_connect_ms": 900.0,
                "p95_cpu_ms": 850.0,
                "total_occ_retries": 0,
            },
        },
    )
    smoke.lambda_churn_incontainer()  # must NOT raise
    out = capsys.readouterr().out
    assert "CHURN_INCONTAINER" in out
    assert "wall_cpu_ratio=10.35" in out
    assert "within_budget=False" in out


def test_lambda_churn_incontainer_budget_pass_still_no_raise(monkeypatch, capsys):
    """lambda_churn_incontainer does not raise even when within_budget=True (always diagnostic)."""
    _patch_gate(monkeypatch, {"collision_rate": 0.0, "p95_commit_ms": 500.0, "within_budget": True, "breakdown": {}})
    smoke.lambda_churn_incontainer()
    assert "CHURN_INCONTAINER" in capsys.readouterr().out


def test_main_lambda_churn_incontainer_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke, "lambda_churn_incontainer", lambda profile=None, region="eu-west-2": print("CHURN_INCONTAINER ok")
    )
    assert smoke.main(["--lambda-churn-incontainer"]) == 0
    assert "CHURN_INCONTAINER" in capsys.readouterr().out


def test_lambda_reader_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": True})

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    smoke.lambda_reader()
    assert "READER OK rows=3 write_denied=true" in capsys.readouterr().out


def _warm_reuse_invoker():
    """Fake _sigv4_invoke: 1st attach_check is cold (reused=False), subsequent are warm (reused=True)."""
    state = {"attach_calls": 0}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "reset_warm_connection":
            state["attach_calls"] = 0
            return _Resp(200, {"ok": True, "reset": True})
        if action == "attach_check":
            state["attach_calls"] += 1
            cold = state["attach_calls"] == 1
            return _Resp(200, {"ok": True, "connect_ms": 80.0 if cold else 0.0, "connect_reused": not cold})
        if action == "write":
            return _Resp(200, {"ok": True, "occ_retries": 0})
        return _Resp(200, {"ok": True})

    return fake_invoke


def test_lambda_warm_reuse_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(smoke, "_sigv4_invoke", _warm_reuse_invoker())
    smoke.lambda_warm_reuse(json_output=True)
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["role"] == "reader"
    assert result["warm_reuse_observed"] is True
    assert result["warm_connect_ms"] == 0.0
    assert result["reconnect_ok"] is True


def test_lambda_warm_reuse_writer_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(smoke, "_sigv4_invoke", _warm_reuse_invoker())
    smoke.lambda_warm_reuse_writer(json_output=True)
    result = json.loads(capsys.readouterr().out)
    assert result["role"] == "writer"
    assert result["warm_reuse_observed"] is True
    assert result["write_ok"] is True


def test_lambda_warm_reuse_fails_when_no_reuse(monkeypatch):
    """If reuse is never observed (connect_reused stays False), the gate loud-fails."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")

    def never_reused(url, payload, **kw):
        if payload["action"] == "attach_check":
            return _Resp(200, {"ok": True, "connect_ms": 80.0, "connect_reused": False})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(smoke, "_sigv4_invoke", never_reused)
    with pytest.raises(smoke.SmokeTestFailure, match="warm reuse not observed"):
        smoke.lambda_warm_reuse()


def test_lambda_reader_boundary_broken_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")

    def fake_invoke(url, payload, **kw):
        if payload["action"] == "read_current":
            return _Resp(200, {"row_count": 3})
        return _Resp(200, {"write_denied": False})  # boundary broken

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="READER FAIL"):
        smoke.lambda_reader()


def test_lambda_maintenance_merge_ok(monkeypatch, capsys):
    """VP9: maintenance merge with force_recreate_tables=True; asserts files_after_merge <= files_before."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    invoked = {}

    def fake_invoke(url, payload, **kw):
        invoked["payload"] = payload
        return _Resp(200, {"ok": True, "files_before": 3, "files_after_merge": 2, "elapsed_ms": 45.0})

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    smoke.lambda_maintenance_merge()
    out = capsys.readouterr().out
    assert "MAINTENANCE_MERGE OK files_before=3 files_after_merge=2" in out
    assert invoked["payload"] == {"action": "merge", "force_recreate_tables": True}


def test_lambda_maintenance_merge_empty_smoke_catalog_ok(monkeypatch, capsys):
    """VP9: works on a fresh environment where smoke tables were just created (files_before=0)."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        smoke,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": True, "files_before": 0, "files_after_merge": 0, "elapsed_ms": 12.0}),
    )
    smoke.lambda_maintenance_merge()
    assert "MAINTENANCE_MERGE OK files_before=0 files_after_merge=0" in capsys.readouterr().out


def test_lambda_maintenance_merge_files_grew_fails(monkeypatch):
    """VP9: loud-fail when files_after_merge > files_before (merge expanded the catalog)."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        smoke,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": True, "files_before": 2, "files_after_merge": 5}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="files grew after merge"):
        smoke.lambda_maintenance_merge()


def test_lambda_maintenance_merge_not_ok_fails(monkeypatch):
    """VP9: loud-fail when maintenance returns ok=False."""
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        smoke,
        "_sigv4_invoke",
        lambda url, payload, **kw: _Resp(200, {"ok": False, "error": "catalog error"}),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="MAINTENANCE_MERGE FAIL"):
        smoke.lambda_maintenance_merge()


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


# ---------------------------------------------------------------------------
# T2.19: production gates (ops read-your-write, churn re-gate, pg_restore drill)
# ---------------------------------------------------------------------------


def test_ops_read_your_write_ok(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}
    written = {}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "write_ops":
            written.update(payload["record"])
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            if payload["record"]["id"].startswith("test-absent"):
                return _Resp(409, {"error_type": "referential"})
            state["status"] = payload["record"]["status"]
            return _Resp(200, {"ok": True})
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        return _Resp(200, {})

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    smoke.ops_read_your_write()
    assert "OPS_RYW OK" in capsys.readouterr().out
    # The probe row persists (writer has no delete verb); it must carry the DQ NOT-NULL columns
    # so it does not red the ops_recommendations data-quality checks while it lingers.
    for col in ("automatable", "file", "context", "acceptance"):
        assert written.get(col) is not None, f"probe missing DQ-required column {col!r}"


def test_ops_read_your_write_absent_not_409_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        if action == "update_ops" and not payload["record"]["id"].startswith("test-absent"):
            state["status"] = "closed"
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            return _Resp(200, {"ok": True})  # absent update wrongly succeeds -> boundary broken
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(smoke, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="expected 409"):
        smoke.ops_read_your_write()


def test_ops_churn_regate_delegates(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "lambda_churn", lambda profile=None, region="eu-west-2": None)
    smoke.ops_churn_regate()
    assert "OPS_CHURN_REGATE OK" in capsys.readouterr().out


def test_catalog_restore_drill_ok(monkeypatch, capsys):
    # T2.19: catalog_restore_drill now INVOKES the maintenance restore_drill action over 443 (the
    # pg_dump/pg_restore runs inside AWS -- no Neon 5432 from CC-web). Mock the URL + the invoke.
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        smoke,
        "_sigv4_invoke",
        lambda url, p, **kw: _Resp(200, {"ok": True, "restored": True, "probe_id": "drill-probe", "pg_version": "16"}),
    )
    smoke.catalog_restore_drill()
    assert "CATALOG_RESTORE_DRILL OK" in capsys.readouterr().out


def test_catalog_restore_drill_probe_lost_fails(monkeypatch):
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(200, {"ok": True, "restored": False}))
    with pytest.raises(smoke.SmokeTestFailure, match="did not restore"):
        smoke.catalog_restore_drill()


# ---------------------------------------------------------------------------
# DUCKLAKE_ALLOW_DIRECT_GATE guard (churn_gate + restore_drill refuse without env)
# ---------------------------------------------------------------------------


def test_churn_gate_refused_without_direct_gate_env(monkeypatch):
    """churn_gate raises SmokeTestFailure with DIRECT_GATE_REFUSED when env var absent."""
    monkeypatch.delenv("DUCKLAKE_ALLOW_DIRECT_GATE", raising=False)
    with pytest.raises(smoke.SmokeTestFailure, match="DIRECT_GATE_REFUSED"):
        smoke.churn_gate(dsn=_DSN)


def test_churn_gate_proceeds_with_direct_gate_env(monkeypatch):
    """churn_gate does NOT raise the guard error when DUCKLAKE_ALLOW_DIRECT_GATE=1 is set."""
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        smoke,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 1.0, "collided": False}],
    )
    metrics = smoke.churn_gate(dsn=_DSN)
    assert "collision_rate" in metrics


def test_restore_drill_refused_without_direct_gate_env(monkeypatch):
    """restore_drill raises SmokeTestFailure with DIRECT_GATE_REFUSED when env var absent."""
    monkeypatch.delenv("DUCKLAKE_ALLOW_DIRECT_GATE", raising=False)
    with pytest.raises(smoke.SmokeTestFailure, match="DIRECT_GATE_REFUSED"):
        smoke.restore_drill(dsn=_DSN)


def test_restore_drill_proceeds_with_direct_gate_env(monkeypatch):
    """restore_drill does NOT raise the guard error when DUCKLAKE_ALLOW_DIRECT_GATE=1 is set."""
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(smoke, "_engine_tag", lambda: "duckdb-test")
    monkeypatch.setattr(smoke, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(smoke, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(smoke, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(smoke, "_verify_probe", lambda scratch, probe, profile=None: True)
    result = smoke.restore_drill(dsn=_DSN, scratch_dsn=smoke._derive_scratch_dsn(_DSN))
    assert result is True


# ---------------------------------------------------------------------------
# OQ.12 canary_rehearsal orchestration
# ---------------------------------------------------------------------------


_FAKE_BRANCH_ID = "br-fake-canary-abc"
_FAKE_BRANCH_HOST = "br-fake-canary-abc.us-east-2.aws.neon.tech"
_FAKE_PROJECT_ID = "proj-fake-123"


def _stub_canary_rehearsal(monkeypatch, *, clone_ok=True, ryw_ok=True):
    """Stub all subprocess/AWS/Neon API calls for canary_rehearsal unit tests."""
    _fake_arns = {
        "ducklake-deps-layer": "arn:fake:1",
        "ducklake-extensions-layer": "arn:fake:2",
        "ducklake-pgclient-layer": "arn:fake:3",
    }
    monkeypatch.setattr(smoke, "_publish_candidate_layers", lambda **kw: _fake_arns)
    monkeypatch.setattr(smoke, "_get_function_role_arn", lambda fn, **kw: "arn:aws:iam::ACCOUNT_ID_PLACEHOLDER:role/fake-role")
    monkeypatch.setattr(smoke, "_canary_create_function", lambda fn, **kw: None)
    monkeypatch.setattr(smoke, "_canary_delete_function", lambda fn, **kw: True)

    monkeypatch.setattr(smoke.neon_api, "fetch_api_key", lambda profile=None: "fake-api-key")
    monkeypatch.setattr(smoke.neon_api, "resolve_project_id", lambda api_key, name="ducklake-catalog": _FAKE_PROJECT_ID)
    monkeypatch.setattr(
        smoke.neon_api,
        "create_branch",
        lambda api_key, project_id: {"branch_id": _FAKE_BRANCH_ID, "host": _FAKE_BRANCH_HOST},
    )
    monkeypatch.setattr(smoke.neon_api, "delete_branch", lambda api_key, project_id, branch_id: None)

    def _fake_invoke(fn, payload, **kw):
        action = payload.get("action", "")
        if action == "catalog_reinit":
            return {"ok": True, "meta_schema": payload.get("meta_schema"), "reinitialized": True}
        if action == "create_tables":
            return {"ok": True}
        if action == "write":
            return {"ok": True, "ulid": "fake-ulid"}
        if action == "read_current":
            if not ryw_ok:
                return {"rows": []}
            return {"rows": [{"rec_id": payload.get("rec_id", "x")}]}
        if action == "clone_catalog":
            if not clone_ok:
                return {"ok": False, "error": "clone failed"}
            return {"ok": True, "meta_schema": "ducklake_ops", "branch_host": payload.get("branch_host"), "cloned": True}
        return {}

    monkeypatch.setattr(smoke, "_lambda_invoke_cli", _fake_invoke)

    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}.lambda-url")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(200, {"ok": True}))

    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""))


def test_canary_rehearsal_happy_path(monkeypatch, capsys):
    """Full happy-path: all gates pass, teardown completes, prints CANARY_REHEARSAL OK."""
    _stub_canary_rehearsal(monkeypatch)
    smoke.canary_rehearsal()
    out = capsys.readouterr().out
    assert "CANARY_REHEARSAL OK" in out
    assert "CANARY_ATTACH OK" in out
    assert "CANARY_RYW OK" in out
    assert "CANARY_CLONE_CATALOG OK" in out


def test_canary_rehearsal_json_output(monkeypatch):
    """json_output=True emits machine-readable JSON with expected keys including branch fields."""
    _stub_canary_rehearsal(monkeypatch)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        smoke.canary_rehearsal(json_output=True)

    import json

    lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("{")]
    assert lines, "No JSON line found in output"
    data = json.loads(lines[-1])
    assert data["attach_ok"] is True
    assert data["ryw_ok"] is True
    assert data["clone_ok"] is True
    assert data["torn_down"]["canary_functions"] is True
    assert data["torn_down"]["scratch_meta"] is True
    assert data["torn_down"]["scratch_s3_prefix"] is True
    assert data["torn_down"]["branch"] is True
    assert data["scratch"]["branch_id"] == _FAKE_BRANCH_ID
    assert data["scratch"]["meta_schema"] != "ducklake_ops"
    assert "_canary_rehearsal" in data["scratch"]["data_path"]


def test_canary_rehearsal_scratch_meta_isolated(monkeypatch):
    """Scratch meta-schema must be _CANARY_SCRATCH_META, never the production ducklake_ops."""
    _stub_canary_rehearsal(monkeypatch)
    import contextlib
    import io
    import json

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        smoke.canary_rehearsal(json_output=True)

    data = json.loads([ln for ln in buf.getvalue().splitlines() if ln.startswith("{")][-1])
    assert data["scratch"]["meta_schema"] == smoke._CANARY_SCRATCH_META
    assert data["scratch"]["meta_schema"] != "ducklake_ops"


def test_canary_rehearsal_ryw_fail_raises(monkeypatch):
    """RYW failure (empty rows from reader) raises SmokeTestFailure (Decision 55)."""
    _stub_canary_rehearsal(monkeypatch, ryw_ok=False)
    with pytest.raises(smoke.SmokeTestFailure, match="CANARY_RYW FAIL"):
        smoke.canary_rehearsal()


def test_canary_rehearsal_clone_catalog_fail_raises(monkeypatch):
    """clone_catalog returning ok=False raises SmokeTestFailure."""
    _stub_canary_rehearsal(monkeypatch, clone_ok=False)
    with pytest.raises(smoke.SmokeTestFailure, match="CANARY_CLONE_CATALOG FAIL"):
        smoke.canary_rehearsal()


def test_canary_rehearsal_functions_torn_down_on_error(monkeypatch):
    """Ephemeral Lambda functions are deleted even when a gate fails (finally block)."""
    deleted = []
    _td_arns = {"ducklake-deps-layer": "arn:1", "ducklake-extensions-layer": "arn:2", "ducklake-pgclient-layer": "arn:3"}
    monkeypatch.setattr(smoke, "_publish_candidate_layers", lambda **kw: _td_arns)
    monkeypatch.setattr(smoke, "_get_function_role_arn", lambda fn, **kw: "arn:role")
    monkeypatch.setattr(smoke, "_canary_create_function", lambda fn, **kw: None)
    monkeypatch.setattr(smoke, "_canary_delete_function", lambda fn, **kw: deleted.append(fn) or True)
    monkeypatch.setattr(smoke, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(smoke, "_sigv4_invoke", lambda url, p, **kw: _Resp(200, {"ok": True}))
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(smoke.neon_api, "fetch_api_key", lambda profile=None: "fake-api-key")
    monkeypatch.setattr(smoke.neon_api, "resolve_project_id", lambda api_key, name="ducklake-catalog": _FAKE_PROJECT_ID)
    monkeypatch.setattr(
        smoke.neon_api, "create_branch", lambda api_key, project_id: {"branch_id": _FAKE_BRANCH_ID, "host": _FAKE_BRANCH_HOST}
    )
    monkeypatch.setattr(smoke.neon_api, "delete_branch", lambda api_key, project_id, branch_id: None)

    def _raise_on_attach(fn, payload, **kw):
        if payload.get("action") == "catalog_reinit":
            return {"ok": True}
        if payload.get("action") == "create_tables":
            raise smoke.SmokeTestFailure("attach failed")
        return {}

    monkeypatch.setattr(smoke, "_lambda_invoke_cli", _raise_on_attach)

    with pytest.raises(smoke.SmokeTestFailure, match="attach failed"):
        smoke.canary_rehearsal()

    assert len(deleted) == len(smoke._CANARY_FUNCTION_NAMES), "All ephemeral functions must be deleted in finally"


def test_main_canary_rehearsal_dispatch(monkeypatch, capsys):
    """--canary-rehearsal CLI flag dispatches to canary_rehearsal()."""
    monkeypatch.setattr(
        smoke,
        "canary_rehearsal",
        lambda profile=None, region="eu-west-2", json_output=False: print("CANARY_REHEARSAL OK"),
    )
    assert smoke.main(["--canary-rehearsal"]) == 0
    assert "CANARY_REHEARSAL OK" in capsys.readouterr().out


def test_canary_rehearsal_budget_constants_unchanged():
    """CHURN constants used in _canary_churn must still come from ducklake_runtime (Decision 55)."""
    from src.common import ducklake_runtime

    assert smoke.CHURN_WRITERS == ducklake_runtime.CHURN_WRITERS
    assert smoke.COMMIT_LATENCY_BUDGET_MS == ducklake_runtime.COMMIT_LATENCY_BUDGET_MS
    assert smoke.OCC_COLLISION_RATE_BUDGET == ducklake_runtime.OCC_COLLISION_RATE_BUDGET


def test_canary_rehearsal_scratch_meta_teardown_false_on_sigv4_error(monkeypatch):
    """torn_down['scratch_meta'] is False (not raised) when _sigv4_invoke raises (H-2 failure branch)."""
    import contextlib
    import io
    import json as _json

    _stub_canary_rehearsal(monkeypatch)

    def _raise_sigv4(url, payload, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(smoke, "_sigv4_invoke", _raise_sigv4)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        smoke.canary_rehearsal(json_output=True)

    data = _json.loads([ln for ln in buf.getvalue().splitlines() if ln.startswith("{")][-1])
    assert data["torn_down"]["scratch_meta"] is False
    assert data["torn_down"]["canary_functions"] is True


def test_canary_rehearsal_branch_host_passed_to_clone(monkeypatch):
    """Neon branch_host must be included in the clone_catalog event payload (Decision 100)."""
    clone_events = []

    _stub_canary_rehearsal(monkeypatch)

    def _capture_invoke(fn, payload, **kw):
        if payload.get("action") == "clone_catalog":
            clone_events.append(payload.copy())

        if payload.get("action") == "catalog_reinit":
            return {"ok": True}
        if payload.get("action") == "create_tables":
            return {"ok": True}
        if payload.get("action") == "write":
            return {"ok": True, "ulid": "fake-ulid"}
        if payload.get("action") == "read_current":
            return {"rows": [{"rec_id": payload.get("rec_id", "x")}]}
        if payload.get("action") == "clone_catalog":
            return {"ok": True, "meta_schema": "ducklake_ops", "branch_host": payload.get("branch_host"), "cloned": True}
        return {}

    monkeypatch.setattr(smoke, "_lambda_invoke_cli", _capture_invoke)

    smoke.canary_rehearsal()

    assert len(clone_events) == 1, "clone_catalog must be invoked exactly once"
    assert clone_events[0].get("branch_host") == _FAKE_BRANCH_HOST, (
        "branch_host from Neon create_branch must be forwarded to clone_catalog event"
    )
    clone_data_path = clone_events[0].get("data_path", "")
    assert clone_data_path.startswith("s3://") and clone_data_path.endswith("/ducklake/"), (
        f"clone_catalog event must carry the production data_path (s3://<bucket>/ducklake/), got {clone_data_path!r}"
    )


def test_canary_rehearsal_delete_branch_called_on_clone_failure(monkeypatch):
    """delete_branch must be called in finally even when clone_catalog returns ok=False."""
    deleted = []

    _stub_canary_rehearsal(monkeypatch, clone_ok=False)
    monkeypatch.setattr(
        smoke.neon_api,
        "delete_branch",
        lambda api_key, project_id, branch_id: deleted.append(branch_id),
    )

    with pytest.raises(smoke.SmokeTestFailure, match="CANARY_CLONE_CATALOG FAIL"):
        smoke.canary_rehearsal()

    assert deleted == [_FAKE_BRANCH_ID], "delete_branch must be called in finally even when clone fails"


def _stub_invoke_response(monkeypatch, return_value):
    """Stub subprocess.run + the response-file read so _lambda_invoke_cli returns `return_value`."""
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    import builtins
    import json as _json

    real_open = builtins.open

    def _fake_open(path, *a, **kw):
        if isinstance(path, str) and path.endswith("response.json"):
            import io

            return io.StringIO(_json.dumps(return_value))
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", _fake_open)


def test_lambda_invoke_cli_unwraps_function_url_envelope(monkeypatch):
    """_lambda_invoke_cli unwraps the {statusCode, body} envelope, returning the parsed body dict."""
    envelope = {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": '{"ok": true, "x": 1}'}
    _stub_invoke_response(monkeypatch, envelope)
    out = smoke._lambda_invoke_cli("fn", {"action": "catalog_reinit"}, profile=None, region="eu-west-2")
    assert out == {"ok": True, "x": 1}


def test_lambda_invoke_cli_passes_through_raw_error(monkeypatch):
    """A handler runtime error (no statusCode/body) is returned as-is for the caller to inspect."""
    err = {"errorMessage": "boom", "errorType": "RuntimeError"}
    _stub_invoke_response(monkeypatch, err)
    out = smoke._lambda_invoke_cli("fn", {"action": "create_tables"}, profile=None, region="eu-west-2")
    assert out == err
    assert out.get("ok") is None


def test_lambda_invoke_cli_loud_fails_on_nonzero_rc(monkeypatch):
    """A non-zero CLI exit raises SmokeTestFailure (Decision 55)."""
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=254, stdout="", stderr="boom")
    )
    with pytest.raises(smoke.SmokeTestFailure, match="lambda invoke fn failed"):
        smoke._lambda_invoke_cli("fn", {"action": "x"}, profile=None, region="eu-west-2")


def test_wait_function_active_invokes_waiter(monkeypatch):
    """_wait_function_active runs `lambda wait function-active-v2` for the named function."""
    captured = {}

    def _run(cmd, **kw):
        captured["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", _run)
    smoke._wait_function_active("ducklake-maintenance-canary-ephemeral", profile="p", region="eu-west-2")
    cmd = captured["cmd"]
    assert "wait" in cmd
    assert "function-active-v2" in cmd
    assert "ducklake-maintenance-canary-ephemeral" in cmd


def test_wait_function_active_loud_fails_on_waiter_error(monkeypatch):
    """A non-zero waiter exit raises SmokeTestFailure (Decision 55 -- never race the first invoke)."""
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda cmd, **kw: types.SimpleNamespace(returncode=255, stdout="", stderr="Waiter FunctionActiveV2 failed"),
    )
    with pytest.raises(smoke.SmokeTestFailure, match="wait function-active-v2"):
        smoke._wait_function_active("fn", profile=None, region="eu-west-2")
