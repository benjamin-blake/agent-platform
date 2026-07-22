"""Tests for scripts/ci/plan_digest.py (DEP-07 saved-plan digest emit/verify).

Covers: emit() returns the sha256 hex of the bytes; verify() passes on a matching reference;
verify() FAILS CLOSED on a mismatched reference and on an empty/missing/whitespace reference --
the substitution and the no-reference cases both fail closed (T2.46 c2).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.ci.plan_digest import PlanDigestError, emit, main, verify

# ---------------------------------------------------------------------------
# emit()
# ---------------------------------------------------------------------------


def test_emit_returns_sha256_hex(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"terraform plan bytes")
    expected = hashlib.sha256(b"terraform plan bytes").hexdigest()
    assert emit(plan) == expected


def test_emit_is_deterministic_for_same_bytes(tmp_path: Path) -> None:
    plan_a = tmp_path / "a.bin"
    plan_b = tmp_path / "b.bin"
    plan_a.write_bytes(b"identical content")
    plan_b.write_bytes(b"identical content")
    assert emit(plan_a) == emit(plan_b)


def test_emit_differs_for_different_bytes(tmp_path: Path) -> None:
    plan_a = tmp_path / "a.bin"
    plan_b = tmp_path / "b.bin"
    plan_a.write_bytes(b"content one")
    plan_b.write_bytes(b"content two")
    assert emit(plan_a) != emit(plan_b)


def test_emit_raises_oserror_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        emit(tmp_path / "does-not-exist.bin")


# ---------------------------------------------------------------------------
# verify() -- matching reference passes
# ---------------------------------------------------------------------------


def test_verify_passes_on_matching_reference(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"reviewed plan bytes")
    reference = hashlib.sha256(b"reviewed plan bytes").hexdigest()
    verify(plan, reference)  # must not raise


# ---------------------------------------------------------------------------
# verify() -- FAILS CLOSED: mismatch and empty/missing/whitespace reference
# ---------------------------------------------------------------------------


def test_verify_fails_closed_on_mismatched_reference(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"substituted plan bytes")
    reference = hashlib.sha256(b"original reviewed bytes").hexdigest()
    with pytest.raises(PlanDigestError, match="digest mismatch"):
        verify(plan, reference)


def test_verify_fails_closed_on_empty_reference(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"plan bytes")
    with pytest.raises(PlanDigestError, match="missing/empty reference"):
        verify(plan, "")


def test_verify_fails_closed_on_none_reference(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"plan bytes")
    with pytest.raises(PlanDigestError, match="missing/empty reference"):
        verify(plan, None)


def test_verify_fails_closed_on_whitespace_only_reference(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"plan bytes")
    with pytest.raises(PlanDigestError, match="missing/empty reference"):
        verify(plan, "   \n\t  ")


def test_verify_strips_surrounding_whitespace_before_comparing(tmp_path: Path) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"plan bytes")
    reference = hashlib.sha256(b"plan bytes").hexdigest()
    verify(plan, f"  {reference}\n")  # must not raise -- surrounding whitespace is not a mismatch


def test_verify_raises_oserror_on_missing_plan_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        verify(tmp_path / "absent.bin", "somereference")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def test_main_emit_prints_digest_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"cli emit bytes")
    rc = main(["emit", str(plan)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == hashlib.sha256(b"cli emit bytes").hexdigest()


def test_main_emit_fails_on_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["emit", str(tmp_path / "nope.bin")])
    assert rc == 1
    assert "cannot read" in capsys.readouterr().err


def test_main_verify_matching_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"cli verify bytes")
    reference = hashlib.sha256(b"cli verify bytes").hexdigest()
    rc = main(["verify", str(plan), reference])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_verify_mismatch_exits_nonzero_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"substituted bytes")
    rc = main(["verify", str(plan), hashlib.sha256(b"different bytes").hexdigest()])
    assert rc == 1
    assert "digest mismatch" in capsys.readouterr().err


def test_main_verify_empty_reference_exits_nonzero_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    plan = tmp_path / "plan.bin"
    plan.write_bytes(b"plan bytes")
    rc = main(["verify", str(plan), ""])
    assert rc == 1
    assert "missing/empty reference" in capsys.readouterr().err


def test_main_verify_missing_plan_file_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["verify", str(tmp_path / "absent.bin"), "somereference"])
    assert rc == 1
    assert "cannot read" in capsys.readouterr().err


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        main([])
