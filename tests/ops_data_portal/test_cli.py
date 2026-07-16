"""Tests for the scripts/ops_portal/cli.py argv-dispatch surface (scripts.ops_data_portal.main).

Split out of the former tests/test_ops_data_portal.py monolith (rec-2709 Wave 3).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")

from tests.fixtures.ops_portal_records import VALID_FIELDS as _VALID_FIELDS  # noqa: E402


class TestCLI:
    """Tests for the CLI entrypoint."""

    def test_cli_file_rec_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec prints the writer-allocated rec ID to stdout."""
        recs_file = tmp_path / ".recommendations-log.jsonl"

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-700"}),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(
                [
                    "--file-rec",
                    "--title",
                    "CLI test rec",
                    "--file",
                    "scripts/ops_data_portal.py",
                    "--context",
                    "Testing the CLI entrypoint for file_rec -- this context satisfies the 80-char minimum.",
                    "--acceptance",
                    "grep -q ops_data_portal scripts/ops_data_portal.py",
                    "--effort",
                    "XS",
                    "--priority",
                    "Low",
                    "--source",
                    "planning",
                    "--risk",
                    "low",
                ]
            )

        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-700" in captured.out

    def test_cli_file_rec_missing_required(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --file-rec exits 1 and prints error when required fields missing."""
        from scripts.ops_data_portal import main

        rc = main(["--file-rec", "--title", "Only title"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_cli_update_rec_success(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --update-rec calls update_rec and prints confirmation."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(["--update-rec", "rec-042", "--status", "closed"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-042" in captured.out

    def test_cli_enqueue_findings_dispatches(self, tmp_path: Path) -> None:
        """CLI --enqueue-findings calls enqueue_findings with the given path and profile."""
        jsonl_file = tmp_path / "findings.jsonl"
        jsonl_file.write_text("", encoding="utf-8")

        with patch(
            "scripts.ops_data_portal.enqueue_findings",
            return_value={"enqueued": 0, "invalid": 0, "skipped": 0},
        ) as mock_enqueue:
            from scripts.ops_data_portal import main

            rc = main(["--enqueue-findings", str(jsonl_file)])

        assert rc == 0
        mock_enqueue.assert_called_once_with(Path(str(jsonl_file)), profile=None)

    def test_cli_backfill_decisions_md_dispatches(self, capsys: pytest.CaptureFixture) -> None:
        """CLI --backfill-decisions-md runs the ETL and exits 1 when any row failed."""
        with patch(
            "scripts.ops_data_portal.backfill_decisions_from_md",
            return_value={"written": 5, "failed": 0, "skipped": 1},
        ) as mock_backfill:
            from scripts.ops_data_portal import main

            rc = main(["--backfill-decisions-md"])

        assert rc == 0
        mock_backfill.assert_called_once_with(profile=None)
        assert '"written": 5' in capsys.readouterr().out

        with patch(
            "scripts.ops_data_portal.backfill_decisions_from_md",
            return_value={"written": 4, "failed": 1, "skipped": 0},
        ):
            from scripts.ops_data_portal import main

            assert main(["--backfill-decisions-md"]) == 1
