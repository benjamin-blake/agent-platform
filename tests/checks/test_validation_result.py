from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks import validation_result


def test_clear_removes_stale_result(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("stale", encoding="utf-8")
    validation_result.clear(path)
    assert not path.exists()


def test_write_completed_is_bounded_atomic_and_secret_free(tmp_path: Path) -> None:
    path = tmp_path / "debug" / "result.json"
    git = MagicMock(returncode=0, stdout="abc123\n")
    with patch("scripts.checks.validation_result.subprocess.run", return_value=git):
        record = validation_result.write_completed(
            started_at="2026-01-01T00:00:00+00:00", exit_code=1, failed_checks=["lint"], path=path
        )
    assert json.loads(path.read_text(encoding="utf-8")) == record
    assert record["git_head"] == "abc123"
    assert record["failed_checks"] == ["lint"]
    assert not list(path.parent.glob("*.tmp"))
    assert "secret" not in path.read_text(encoding="utf-8").lower()


def test_visible_writer_warns_without_raising(capsys) -> None:
    with patch("scripts.checks.validation_result.write_completed", side_effect=OSError("disk full")):
        validation_result.write_completed_visible(started_at="now", exit_code=0, failed_checks=[])
    assert "WARNING: validation evidence could not be written: OSError" in capsys.readouterr().out
