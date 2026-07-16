"""CONCERN: the facade CLI main() dispatch (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: all nine test_main_*
tests exercising scripts/ducklake_neon_smoke_test.py's own main() -- direct-gate dispatch,
churn-incontainer dispatch, lambda-attach dispatch, lambda-gate loud-fail, and canary dispatch.
main() is defined in the facade module itself (not in any scripts/ducklake_smoke/ submodule).
"""

from __future__ import annotations

import pytest

import scripts.ducklake_neon_smoke_test as smoke


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


def test_main_lambda_churn_incontainer_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke, "lambda_churn_incontainer", lambda profile=None, region="eu-west-2": print("CHURN_INCONTAINER ok")
    )
    assert smoke.main(["--lambda-churn-incontainer"]) == 0
    assert "CHURN_INCONTAINER" in capsys.readouterr().out


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


def test_main_canary_rehearsal_dispatch(monkeypatch, capsys):
    """--canary-rehearsal CLI flag dispatches to canary_rehearsal()."""
    monkeypatch.setattr(
        smoke,
        "canary_rehearsal",
        lambda profile=None, region="eu-west-2", json_output=False: print("CANARY_REHEARSAL OK"),
    )
    assert smoke.main(["--canary-rehearsal"]) == 0
    assert "CANARY_REHEARSAL OK" in capsys.readouterr().out
