"""Tests for scripts/ci_rca_filing.py -- extract_filed_rec_id and CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.ci_rca_filing import extract_filed_rec_id


def _write(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "output.json"
    f.write_text(content, encoding="utf-8")
    return f


class TestExtractFiledRecId:
    def test_mention_only_returns_none(self, tmp_path: Path) -> None:
        content = "Agent processed rec-123 and rec-456 from the backlog."
        assert extract_filed_rec_id(_write(tmp_path, content)) is None

    def test_filed_marker_returns_id(self, tmp_path: Path) -> None:
        content = "Some output\nFILED: rec-123\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) == "rec-123"

    def test_filed_none_returns_none(self, tmp_path: Path) -> None:
        content = "Could not file.\nFILED: none\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) is None

    def test_filed_none_case_insensitive(self, tmp_path: Path) -> None:
        content = "FILED: NONE\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) is None

    def test_multiple_markers_returns_last(self, tmp_path: Path) -> None:
        content = "FILED: rec-100\nSome stuff\nFILED: rec-200\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) == "rec-200"

    def test_filed_none_then_real_marker_returns_id(self, tmp_path: Path) -> None:
        # An earlier FILED: none must NOT suppress a later real marker (last wins).
        content = "FILED: none\nReconsidered after retry.\nFILED: rec-123\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) == "rec-123"

    def test_real_marker_then_filed_none_returns_none(self, tmp_path: Path) -> None:
        # A trailing FILED: none is the authoritative final signal -> absence.
        content = "FILED: rec-123\nFiling rolled back.\nFILED: none\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) is None

    def test_marker_with_leading_whitespace(self, tmp_path: Path) -> None:
        content = "  FILED: rec-456  \n"
        assert extract_filed_rec_id(_write(tmp_path, content)) == "rec-456"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert extract_filed_rec_id(tmp_path / "nonexistent.json") is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        assert extract_filed_rec_id(_write(tmp_path, "")) is None

    def test_malformed_json_fallback_finds_marker(self, tmp_path: Path) -> None:
        content = "Some stderr line\n{invalid json\nFILED: rec-789\n"
        assert extract_filed_rec_id(_write(tmp_path, content)) == "rec-789"

    def test_json_envelope_result_field_searched(self, tmp_path: Path) -> None:
        result_text = "I analysed the CI run.\nRoot cause: missing dependency.\nFILED: rec-333\n"
        envelope = json.dumps({"result": result_text, "type": "result"})
        assert extract_filed_rec_id(_write(tmp_path, envelope)) == "rec-333"

    def test_json_envelope_with_escaped_newlines_in_result(self, tmp_path: Path) -> None:
        result_text = "Step 1: read logs\nFILED: rec-999\n"
        envelope = json.dumps({"result": result_text})
        assert extract_filed_rec_id(_write(tmp_path, envelope)) == "rec-999"

    def test_filed_none_in_json_result(self, tmp_path: Path) -> None:
        result_text = "Nothing to file.\nFILED: none\n"
        envelope = json.dumps({"result": result_text})
        assert extract_filed_rec_id(_write(tmp_path, envelope)) is None

    def test_bare_rec_mention_in_json_result_returns_none(self, tmp_path: Path) -> None:
        result_text = "Reviewed existing rec-500 for context."
        envelope = json.dumps({"result": result_text})
        assert extract_filed_rec_id(_write(tmp_path, envelope)) is None

    def test_realistic_json_envelope_with_multi_turn_output(self, tmp_path: Path) -> None:
        result_text = (
            "Turn 1: reading logs\n"
            "Turn 5: classifying failure as dependency gap\n"
            "rec-850 is similar but not the same\n"
            "Turn 29: filing recommendation\n"
            "FILED: rec-2025\n"
        )
        envelope = json.dumps({"result": result_text, "stop_reason": "end_turn", "usage": {}})
        assert extract_filed_rec_id(_write(tmp_path, envelope)) == "rec-2025"

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "FILED: rec-111\n")
        assert extract_filed_rec_id(path) == "rec-111"

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "FILED: rec-222\n")
        assert extract_filed_rec_id(str(path)) == "rec-222"


class TestCLI:
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "scripts.ci_rca_filing", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_cli_exits_0_and_prints_id(self, tmp_path: Path) -> None:
        f = tmp_path / "out.json"
        f.write_text("FILED: rec-42\n", encoding="utf-8")
        result = self._run(str(f))
        assert result.returncode == 0
        assert result.stdout.strip() == "rec-42"
        assert result.stderr == ""

    def test_cli_exits_1_when_no_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "out.json"
        f.write_text("Agent mentioned rec-100 but did not file.", encoding="utf-8")
        result = self._run(str(f))
        assert result.returncode == 1
        assert result.stdout.strip() == ""

    def test_cli_exits_1_for_filed_none(self, tmp_path: Path) -> None:
        f = tmp_path / "out.json"
        f.write_text("FILED: none\n", encoding="utf-8")
        result = self._run(str(f))
        assert result.returncode == 1
        assert result.stdout.strip() == ""

    def test_cli_exits_1_when_no_args(self) -> None:
        result = self._run()
        assert result.returncode == 1

    def test_cli_prints_only_id_no_extra_whitespace(self, tmp_path: Path) -> None:
        f = tmp_path / "out.json"
        f.write_text("FILED: rec-77\n", encoding="utf-8")
        result = self._run(str(f))
        assert result.returncode == 0
        assert result.stdout == "rec-77\n"
