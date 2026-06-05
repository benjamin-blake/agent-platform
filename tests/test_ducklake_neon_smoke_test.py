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


def test_open_attached_composes_attach(monkeypatch):
    con = FakeCon()
    fake_duckdb = types.SimpleNamespace(connect=lambda: con)
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: fake_duckdb)
    monkeypatch.setattr(smoke.ducklake_spike, "_set_s3_credentials", lambda c, profile=None: None)

    out = smoke._open_attached(_DSN, profile=None)
    assert out is con
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
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    out = smoke._single_writer_commit(0, _DSN)
    assert out["collided"] is False
    assert con.closed is True
    assert sum(1 for s in con.executed if s.startswith("INSERT")) == smoke.CHURN_WRITES_PER_WRITER


def test_single_writer_commit_counts_occ_collision(monkeypatch):
    con = FakeCon(raise_on={"INSERT": Exception("could not serialize access due to concurrent update")})
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    out = smoke._single_writer_commit(1, _DSN)
    assert out["collided"] is True
    assert con.closed is True


def test_single_writer_commit_reraises_non_occ(monkeypatch):
    con = FakeCon(raise_on={"INSERT": ValueError("hard failure -- not a collision")})
    monkeypatch.setattr(smoke, "_open_attached", lambda dsn, profile=None: con)
    with pytest.raises(ValueError, match="hard failure"):
        smoke._single_writer_commit(2, _DSN)
    assert con.closed is True


# ---------------------------------------------------------------------------
# burst + evaluation
# ---------------------------------------------------------------------------


def test_run_churn_burst_invokes_worker_per_writer():
    seen = []

    def fake_worker(i, dsn, profile=None):
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


def test_churn_gate_pass_returns_metrics(monkeypatch):
    monkeypatch.setattr(
        smoke, "_run_churn_burst", lambda dsn, profile=None: [{"latency_ms": 5.0, "collided": False} for _ in range(8)]
    )
    metrics = smoke.churn_gate(dsn=_DSN)
    assert metrics["collision_rate"] == 0.0


def test_churn_gate_fetches_dsn_when_absent(monkeypatch):
    monkeypatch.setattr(smoke, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(smoke, "_run_churn_burst", lambda dsn, profile=None: [{"latency_ms": 5.0, "collided": False}])
    assert smoke.churn_gate()["collision_rate"] == 0.0


def test_churn_gate_loud_fails(monkeypatch):
    monkeypatch.setattr(
        smoke, "_run_churn_burst", lambda dsn, profile=None: [{"latency_ms": 1.0, "collided": True} for _ in range(8)]
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
