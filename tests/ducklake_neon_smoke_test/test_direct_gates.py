"""CONCERN: scripts/ducklake_smoke/direct_gates.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: attach_roundtrip, OCC
classification + _single_writer_commit, the churn burst/evaluation primitives, churn_gate (with
the _stub_churn_gate_prelude helper), _engine_tag/_run (with the _completed helper), the
pg_dump/psql subprocess wrappers, the restore-probe write/verify + scratch-DSN derivation,
restore_drill, and the DUCKLAKE_ALLOW_DIRECT_GATE guard for both direct gates.
"""

from __future__ import annotations

import types

# boto3 is imported at MODULE scope even though the tests reference it only via a LAZY
# `import boto3` inside the _stub_churn_gate_prelude helper (shared by the churn_gate tests). This
# makes the file's heavy-dep requirement visible to the fast tier's cheap `--collect-only` pass so
# pr-validate defers it PROACTIVELY to the full post-merge tier, instead of catching it REACTIVELY.
# boto3 is deliberately excluded from requirements-fast.txt. See
# scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401
import pytest

import scripts.ducklake_neon_smoke_test as smoke
from scripts.ducklake_smoke import core, direct_gates
from src.common.ducklake_version import pinned_duckdb_version
from tests.fixtures.ducklake_smoke_fakes import _DSN, FakeCon


def test_attach_roundtrip_with_explicit_dsn(monkeypatch):
    con = FakeCon(fetch_results=[(1,)])
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None: con)
    assert smoke.attach_roundtrip(dsn=_DSN) == 1
    assert con.closed is True


def test_attach_roundtrip_fetches_dsn_when_absent(monkeypatch):
    con = FakeCon(fetch_results=[(1,)])
    monkeypatch.setattr(core, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None: con)
    assert smoke.attach_roundtrip() == 1


def test_is_occ_collision_true_and_false():
    assert smoke._is_occ_collision(Exception("ERROR: could not serialize access")) is True
    assert smoke._is_occ_collision(Exception("relation does not exist")) is False


def test_single_writer_commit_clean(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    out = smoke._single_writer_commit(0, _DSN)
    assert out["collided"] is False
    assert con.closed is True
    assert sum(1 for s in con.executed if s.startswith("INSERT")) == smoke.CHURN_WRITES_PER_WRITER


def test_single_writer_commit_counts_occ_collision(monkeypatch):
    con = FakeCon(raise_on={"INSERT": Exception("could not serialize access due to concurrent update")})
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    out = smoke._single_writer_commit(1, _DSN)
    assert out["collided"] is True
    assert con.closed is True


def test_single_writer_commit_reraises_non_occ(monkeypatch):
    con = FakeCon(raise_on={"INSERT": ValueError("hard failure -- not a collision")})
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None, _creds=None: con)
    with pytest.raises(ValueError, match="hard failure"):
        smoke._single_writer_commit(2, _DSN)
    assert con.closed is True


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


def _stub_churn_gate_prelude(monkeypatch):
    """Stub the pre-warm + STS-prefetch prelude that churn_gate runs before the burst.

    churn_gate now opens one connection (pre-warm) and resolves AWS credentials once before
    spawning the 8 concurrent workers (STS-contention fix). Tests mock both to keep the unit
    test offline.
    """
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None, _creds=None: FakeCon())

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

    monkeypatch.setattr(boto3, "Session", _Session)


def test_churn_gate_pass_returns_metrics(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        direct_gates,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False} for _ in range(8)],
    )
    metrics = smoke.churn_gate(dsn=_DSN)
    assert metrics["collision_rate"] == 0.0


def test_churn_gate_fetches_dsn_when_absent(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(core, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(
        direct_gates, "_run_churn_burst", lambda dsn, profile=None, _creds=None: [{"latency_ms": 5.0, "collided": False}]
    )
    assert smoke.churn_gate()["collision_rate"] == 0.0


def test_churn_gate_loud_fails(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    _stub_churn_gate_prelude(monkeypatch)
    monkeypatch.setattr(
        direct_gates,
        "_run_churn_burst",
        lambda dsn, profile=None, _creds=None: [{"latency_ms": 1.0, "collided": True} for _ in range(8)],
    )
    with pytest.raises(smoke.SmokeTestFailure, match="CHURN_GATE FAIL"):
        smoke.churn_gate(dsn=_DSN)


def test_engine_tag_with_version(monkeypatch):
    pin = pinned_duckdb_version()
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace(__version__=pin))
    assert smoke._engine_tag() == f"duckdb-{pin}"


def test_engine_tag_without_version(monkeypatch):
    monkeypatch.setattr(smoke.ducklake_spike, "_require_duckdb", lambda: types.SimpleNamespace())
    assert smoke._engine_tag() == "duckdb-unknown"


def _completed(returncode=0, stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


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


def test_consistent_pg_dump_success(monkeypatch):
    monkeypatch.setattr(direct_gates, "_run", lambda cmd: _completed(0))
    assert (
        smoke._consistent_pg_dump(_DSN, engine_tag=f"duckdb-{pinned_duckdb_version()}", dump_path="/tmp/x.sql") == "/tmp/x.sql"
    )


def test_consistent_pg_dump_loud_fails(monkeypatch):
    monkeypatch.setattr(direct_gates, "_run", lambda cmd: _completed(1, stderr="permission denied"))
    with pytest.raises(smoke.SmokeTestFailure, match="pg_dump"):
        smoke._consistent_pg_dump(_DSN, engine_tag="t", dump_path="/tmp/x.sql")


def test_restore_dump_success(monkeypatch):
    monkeypatch.setattr(direct_gates, "_run", lambda cmd: _completed(0))
    smoke._restore_dump("/tmp/x.sql", _DSN)  # no raise


def test_restore_dump_loud_fails(monkeypatch):
    monkeypatch.setattr(direct_gates, "_run", lambda cmd: _completed(2, stderr="syntax error"))
    with pytest.raises(smoke.SmokeTestFailure, match="psql restore"):
        smoke._restore_dump("/tmp/x.sql", _DSN)


def test_write_probe_creates_and_inserts(monkeypatch):
    con = FakeCon()
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None: con)
    smoke._write_probe(_DSN, "tok-abc")
    assert any("CREATE TABLE" in s and "restore_probe" in s for s in con.executed)
    assert any("INSERT" in s and "tok-abc" in s for s in con.executed)
    assert con.closed is True


def test_verify_probe_found(monkeypatch):
    con = FakeCon(fetch_results=[("tok-abc",)])
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None: con)
    assert smoke._verify_probe(_DSN, "tok-abc") is True
    assert con.closed is True


def test_verify_probe_missing(monkeypatch):
    con = FakeCon(fetch_results=[])
    monkeypatch.setattr(direct_gates, "_open_attached", lambda dsn, profile=None: con)
    assert smoke._verify_probe(_DSN, "tok-abc") is False


def test_derive_scratch_dsn_suffixes_dbname():
    scratch = smoke._derive_scratch_dsn(_DSN)
    assert scratch["dbname"] == "ducklake_ops_restore_drill"
    assert scratch["host"] == _DSN["host"]
    assert _DSN["dbname"] == "ducklake_ops"  # original not mutated


def test_restore_drill_success_explicit_dsns(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(direct_gates, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
    monkeypatch.setattr(direct_gates, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(direct_gates, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(direct_gates, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(direct_gates, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill(dsn=_DSN, scratch_dsn=smoke._derive_scratch_dsn(_DSN)) is True


def test_restore_drill_defaults_dsn_and_scratch(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(core, "fetch_dsn", lambda profile=None: _DSN)
    monkeypatch.setattr(direct_gates, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
    monkeypatch.setattr(direct_gates, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(direct_gates, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(direct_gates, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(direct_gates, "_verify_probe", lambda scratch, probe, profile=None: True)
    assert smoke.restore_drill() is True


def test_restore_drill_loud_fails_on_lost_probe(monkeypatch):
    monkeypatch.setenv("DUCKLAKE_ALLOW_DIRECT_GATE", "1")
    monkeypatch.setattr(direct_gates, "_engine_tag", lambda: f"duckdb-{pinned_duckdb_version()}")
    monkeypatch.setattr(direct_gates, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(direct_gates, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(direct_gates, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(direct_gates, "_verify_probe", lambda scratch, probe, profile=None: False)
    with pytest.raises(smoke.SmokeTestFailure, match="read-your-write probe missing"):
        smoke.restore_drill(dsn=_DSN)


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
        direct_gates,
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
    monkeypatch.setattr(direct_gates, "_engine_tag", lambda: "duckdb-test")
    monkeypatch.setattr(direct_gates, "_write_probe", lambda dsn, probe, profile=None: None)
    monkeypatch.setattr(direct_gates, "_consistent_pg_dump", lambda dsn, engine_tag, dump_path: dump_path)
    monkeypatch.setattr(direct_gates, "_restore_dump", lambda dump_path, scratch: None)
    monkeypatch.setattr(direct_gates, "_verify_probe", lambda scratch, probe, profile=None: True)
    result = smoke.restore_drill(dsn=_DSN, scratch_dsn=smoke._derive_scratch_dsn(_DSN))
    assert result is True
