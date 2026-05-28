"""Tests for scripts.classify_automatable."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.classify_automatable import _is_boundary_file, classify, run


def _make_rec(
    effort: str = "XS",
    risk: str = "low",
    file: str = "scripts/some_file.py",
    status: str = "open",
) -> dict:
    return {
        "id": "rec-999",
        "status": status,
        "effort": effort,
        "risk": risk,
        "file": file,
        "automatable": False,
    }


class TestClassify:
    def test_xs_low_risk_small_file(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "small.py").write_text("x = 1\n" * 100, encoding="utf-8")
        rec = _make_rec(effort="XS", risk="low", file="scripts/small.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is True

    def test_m_effort_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(effort="M")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_high_risk_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(risk="high")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_large_file_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "big.py").write_text("x = 1\n" * 900, encoding="utf-8")
        rec = _make_rec(file="scripts/big.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_boundary_file_rejected(self) -> None:
        rec = _make_rec(file="scripts/executor/plan.py")
        assert classify(rec) is False

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(file="nonexistent.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False


class TestIsBoundaryFile:
    def test_executor_dir(self) -> None:
        assert _is_boundary_file("scripts/executor/step_runner.py") is True

    def test_non_boundary(self) -> None:
        assert _is_boundary_file("scripts/session_preflight.py") is False


class TestRun:
    def test_jsonl_round_trip(self, tmp_path: Path) -> None:
        # Create target files
        (tmp_path / "scripts").mkdir()
        small = tmp_path / "scripts" / "ok.py"
        small.write_text("x = 1\n" * 50, encoding="utf-8")
        big = tmp_path / "scripts" / "big.py"
        big.write_text("x = 1\n" * 900, encoding="utf-8")

        recs = [
            _make_rec(effort="XS", risk="low", file="scripts/ok.py"),
            _make_rec(effort="L", risk="low", file="scripts/big.py"),
        ]
        recs_file = tmp_path / "recs.jsonl"
        recs_file.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n",
            encoding="utf-8",
        )

        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            auto, non_auto = run(recs_file)

        assert auto == 1
        assert non_auto == 1

        lines = [json.loads(ln) for ln in recs_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines[0]["automatable"] is True
        assert lines[1]["automatable"] is False
