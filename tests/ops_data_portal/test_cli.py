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
                    "grep -q ops_data_portal scripts/ops_data_portal.py && grep -q file_rec scripts/ops_data_portal.py",
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

    def test_cli_update_rec_context(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI --update-rec --context routes the new context into the update_rec write payload."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")
        new_context = "Updated context via the CLI --update-rec path -- this replacement clears the 80-char floor."

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(["--update-rec", "rec-042", "--context", new_context])

        assert rc == 0
        captured = capsys.readouterr()
        assert "rec-042" in captured.out
        _, call_rec = mock_dl_write.call_args[0]
        assert call_rec["context"] == new_context

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

    # -- --dry-run write-fidelity (ops-portal-write-fidelity, rec-2945) --

    @staticmethod
    def _file_rec_argv(**overrides: str) -> list[str]:
        """Build a complete, otherwise-succeeding --file-rec argv from _VALID_FIELDS."""
        values = {
            "title": _VALID_FIELDS["title"],
            "file": _VALID_FIELDS["file"],
            "context": _VALID_FIELDS["context"],
            "acceptance": _VALID_FIELDS["acceptance"],
            "effort": _VALID_FIELDS["effort"],
            "priority": _VALID_FIELDS["priority"],
            "source": _VALID_FIELDS["source"],
            **overrides,
        }
        argv = ["--file-rec"]
        for flag, value in values.items():
            argv.extend([f"--{flag}", value])
        return argv

    def test_cli_dry_run_rejected_for_file_rec(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """An otherwise-complete --file-rec plus --dry-run must loud-fail, not silently write."""
        recs_file = tmp_path / ".recommendations-log.jsonl"
        argv = self._file_rec_argv(risk=_VALID_FIELDS["risk"]) + ["--dry-run"]

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-701"}) as mock_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(argv)

        assert rc == 1
        mock_write.assert_not_called()
        assert "--dry-run" in capsys.readouterr().err

    def test_cli_dry_run_rejected_for_update_rec(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """An otherwise-complete --update-rec plus --dry-run must loud-fail, not silently write."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(["--update-rec", "rec-042", "--status", "closed", "--dry-run"])

        assert rc == 1
        mock_write.assert_not_called()
        assert "--dry-run" in capsys.readouterr().err

    def test_cli_dry_run_still_previews_for_purge_postmortems(self, capsys: pytest.CaptureFixture) -> None:
        """--dry-run --purge-postmortems-for is the one action that implements it; no regression."""
        with patch(
            "scripts.ops_data_portal.purge_postmortems_for",
            return_value={"would_supersede": 0},
        ) as mock_purge:
            from scripts.ops_data_portal import main

            rc = main(["--purge-postmortems-for", "rec-042", "--dry-run"])

        assert rc == 0
        mock_purge.assert_called_once_with("rec-042", dry_run=True, profile=None)

    # -- --update-rec field-fidelity (ops-portal-write-fidelity, rec-2866) --

    def test_cli_update_rec_threads_title_acceptance_priority_verification(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """--update-rec threads title/acceptance/priority/verification into the write payload."""
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_dl_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(
                [
                    "--update-rec",
                    "rec-042",
                    "--title",
                    "NEW TITLE",
                    "--acceptance",
                    "grep -q NEW scripts/ops_data_portal.py",
                    "--priority",
                    "Critical",
                    "--verification",
                    "bin/venv-python -m pytest tests/ops_data_portal/test_cli.py -q",
                ]
            )

        assert rc == 0
        _, call_rec = mock_dl_write.call_args[0]
        assert call_rec["title"] == "NEW TITLE"
        assert call_rec["acceptance"] == "grep -q NEW scripts/ops_data_portal.py"
        assert call_rec["priority"] == "Critical"
        assert call_rec["verification"] == "bin/venv-python -m pytest tests/ops_data_portal/test_cli.py -q"

    def _assert_update_rec_flag_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, extra_argv: list[str], flag_name: str
    ) -> None:
        existing = {**_VALID_FIELDS, "id": "rec-042", "date": "2026-01-01"}
        recs_file = tmp_path / ".recommendations-log.jsonl"
        recs_file.write_text(json.dumps(existing) + "\n", encoding="utf-8")

        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(["--update-rec", "rec-042", "--status", "closed", *extra_argv])

        assert rc == 1
        mock_write.assert_not_called()
        assert flag_name in capsys.readouterr().err

    def test_cli_update_rec_rejects_file_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--update-rec --file must loud-fail: file is derived-field-adjacent, not updatable via the CLI."""
        self._assert_update_rec_flag_rejected(tmp_path, capsys, ["--file", "some/other/file.py"], "--file")

    def test_cli_update_rec_rejects_effort_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--update-rec --effort must loud-fail: effort is derived-field-adjacent, not updatable via the CLI."""
        self._assert_update_rec_flag_rejected(tmp_path, capsys, ["--effort", "L"], "--effort")

    def test_cli_update_rec_rejects_risk_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--update-rec --risk must loud-fail: risk is derived, never agent-set (Decision 65)."""
        self._assert_update_rec_flag_rejected(tmp_path, capsys, ["--risk", "high"], "--risk")

    def test_cli_update_rec_rejects_source_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--update-rec --source must loud-fail: source is filing provenance, immutable after filing."""
        self._assert_update_rec_flag_rejected(tmp_path, capsys, ["--source", "planning"], "--source")

    def test_cli_update_rec_rejects_context_v2_json_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """--update-rec --context-v2-json must loud-fail: update_rec has no such parameter."""
        self._assert_update_rec_flag_rejected(tmp_path, capsys, ["--context-v2-json", "{}"], "--context-v2-json")

    def test_cli_update_rec_requires_at_least_one_field(self, capsys: pytest.CaptureFixture) -> None:
        """--update-rec with no mutable field supplied preserves the pre-existing empty-updates error."""
        from scripts.ops_data_portal import main

        rc = main(["--update-rec", "rec-042"])

        assert rc == 1
        assert "ERROR" in capsys.readouterr().err

    def test_cli_update_rec_success_message_names_applied_fields(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """A successful --update-rec prints exactly which fields were applied."""
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

            rc = main(["--update-rec", "rec-042", "--status", "closed", "--priority", "High"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "priority" in out
        assert "status" in out

    def test_cli_update_rec_flag_dest_classification_is_exhaustive(self) -> None:
        """Every dest in the two rec argument groups is classified by exactly one table."""
        from scripts.ops_portal.cli import _UPDATE_REC_FIELD_MAP, _UPDATE_REC_REJECTIONS, _build_parser

        parser = _build_parser()
        rec_group_dests: set[str] = set()
        for group in parser._action_groups:
            if group.title in {"--file-rec fields", "--update-rec fields"}:
                rec_group_dests.update(action.dest for action in group._group_actions)

        threaded = set(_UPDATE_REC_FIELD_MAP)
        rejected = set(_UPDATE_REC_REJECTIONS)

        assert threaded & rejected == set(), f"overlap between threaded and rejected: {threaded & rejected}"
        assert rec_group_dests == threaded | rejected, (
            f"unclassified: {rec_group_dests - (threaded | rejected)}; stale: {(threaded | rejected) - rec_group_dests}"
        )

    # -- --file-rec risk-optional (ops-portal-write-fidelity, rec-2826) --

    def test_cli_file_rec_risk_optional_omitted(self, tmp_path: Path) -> None:
        """--file-rec succeeds without --risk; the persisted risk is the formula-derived value."""
        from scripts.ops_data_portal import compute_risk

        recs_file = tmp_path / ".recommendations-log.jsonl"
        expected_risk = compute_risk(_VALID_FIELDS["file"], _VALID_FIELDS["effort"])

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-702"}) as mock_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(self._file_rec_argv())

        assert rc == 0
        _, written_rec = mock_write.call_args[0]
        assert written_rec["risk"] == expected_risk

    def test_cli_file_rec_risk_optional_supplied_is_backward_compatible(self, tmp_path: Path) -> None:
        """--file-rec still accepts --risk; the persisted value is unchanged (always formula-derived)."""
        from scripts.ops_data_portal import compute_risk

        recs_file = tmp_path / ".recommendations-log.jsonl"
        expected_risk = compute_risk(_VALID_FIELDS["file"], _VALID_FIELDS["effort"])
        supplied_risk = next(r for r in ("low", "medium", "high") if r != expected_risk)

        with (
            patch("scripts.ops_data_portal._ducklake_write", return_value={"key": "rec-703"}) as mock_write,
            patch("scripts.ops_data_portal._sync_table"),
            patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        ):
            from scripts.ops_data_portal import main

            rc = main(self._file_rec_argv(risk=supplied_risk))

        assert rc == 0
        _, written_rec = mock_write.call_args[0]
        assert written_rec["risk"] == expected_risk
