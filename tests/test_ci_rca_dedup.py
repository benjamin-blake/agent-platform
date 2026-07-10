"""Unit tests for scripts.ci_rca.dedup (100% coverage).

All tests inject finder/bumper callables -- no live DuckLake reader or portal writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.ci_rca.dedup import BundleVerdict, DedupResult, _load_fingerprints, decide, main


class TestDecide:
    def test_all_bundles_matched_dedupes(self):
        finder = MagicMock(side_effect=lambda fp: {"fp-a": "rec-1", "fp-b": "rec-2"}[fp])
        bumper = MagicMock()
        result = decide(["fp-a", "fp-b"], finder=finder, bumper=bumper)

        assert result.run_agent is False
        assert result.deduped is True
        assert bumper.call_count == 2
        bumper.assert_any_call("rec-1")
        bumper.assert_any_call("rec-2")

    def test_novel_fingerprint_always_runs_agent(self):
        """Decision 55 guard: a genuinely-novel fingerprint always results in run-agent."""
        finder = MagicMock(return_value=None)
        bumper = MagicMock()
        result = decide(["fp-novel"], finder=finder, bumper=bumper)

        assert result.run_agent is True
        assert result.deduped is False
        bumper.assert_not_called()

    def test_mixed_set_runs_agent_but_still_bumps_matched(self):
        """A matched bundle is skipped+bumped independently of a co-occurring novel bundle --
        the fix for the all-or-nothing bug (a single miss no longer skips bumping the rest)."""
        finder = MagicMock(side_effect=lambda fp: {"fp-matched": "rec-1", "fp-novel": None}[fp])
        bumper = MagicMock()
        result = decide(["fp-matched", "fp-novel"], finder=finder, bumper=bumper)

        assert result.run_agent is True
        bumper.assert_called_once_with("rec-1")
        verdicts = {v.fingerprint: v for v in result.verdicts}
        assert verdicts["fp-matched"].run_agent is False
        assert verdicts["fp-matched"].matched_rec_id == "rec-1"
        assert verdicts["fp-novel"].run_agent is True
        assert verdicts["fp-novel"].matched_rec_id is None

    def test_force_rca_bypasses_all_lookups(self):
        finder = MagicMock()
        bumper = MagicMock()
        result = decide(["fp-a", "fp-b"], force_rca=True, finder=finder, bumper=bumper)

        assert result.run_agent is True
        assert result.force_rca is True
        finder.assert_not_called()
        bumper.assert_not_called()

    def test_empty_fingerprint_list_fails_closed(self):
        """Zero evidence bundles at all -- fail closed (Decision 55), run the agent."""
        finder = MagicMock()
        result = decide([], finder=finder)

        assert result.run_agent is True
        assert result.verdicts == []
        finder.assert_not_called()

    def test_missing_fingerprint_string_treated_as_novel(self):
        finder = MagicMock()
        bumper = MagicMock()
        result = decide([""], finder=finder, bumper=bumper)

        assert result.run_agent is True
        finder.assert_not_called()
        bumper.assert_not_called()
        assert result.verdicts[0].matched_rec_id is None

    def test_default_finder_and_bumper_used_when_not_injected(self):
        """No finder/bumper injected -- falls back to the real ci_rca_runtime helpers."""
        import scripts.ci_rca.dedup as dedup_mod

        with (
            pytest.MonkeyPatch.context() as mp,
        ):
            mock_find = MagicMock(return_value="rec-9")
            mock_bump = MagicMock()
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: mock_find(fp))
            mp.setattr(dedup_mod, "_default_bumper", lambda rec_id, profile=None: mock_bump(rec_id))
            result = decide(["fp-a"])

        assert result.deduped is True
        mock_find.assert_called_once_with("fp-a")
        mock_bump.assert_called_once_with("rec-9")


class TestLoadFingerprints:
    def test_reads_fingerprint_from_each_bundle(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))
        (tmp_path / "b.json").write_text(json.dumps({"fingerprint": "fp-b"}))

        fps = _load_fingerprints(tmp_path)

        assert sorted(fps) == ["fp-a", "fp-b"]

    def test_missing_fingerprint_key_yields_empty_string(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"failure_category": "unknown"}))

        fps = _load_fingerprints(tmp_path)

        assert fps == [""]

    def test_malformed_json_yields_empty_string(self, tmp_path: Path):
        (tmp_path / "a.json").write_text("not-json{")

        fps = _load_fingerprints(tmp_path)

        assert fps == [""]

    def test_no_bundle_files_yields_empty_list(self, tmp_path: Path):
        assert _load_fingerprints(tmp_path) == []


class TestMain:
    def test_deduped_true_when_all_matched(self, tmp_path: Path, capsys):
        import scripts.ci_rca.dedup as dedup_mod

        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: "rec-1")
            mp.setattr(dedup_mod, "_default_bumper", lambda rec_id, profile=None: None)
            rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=true" in out
        assert "matches open rec-1" in out

    def test_deduped_false_on_novel(self, tmp_path: Path, capsys):
        import scripts.ci_rca.dedup as dedup_mod

        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-novel"}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dedup_mod, "_default_finder", lambda fp, profile=None: None)
            rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "has no open match" in out

    def test_force_rca_flag(self, tmp_path: Path, capsys):
        (tmp_path / "a.json").write_text(json.dumps({"fingerprint": "fp-a"}))

        rc = main(["--bundles-dir", str(tmp_path), "--force-rca"])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "force_rca=true" in out

    def test_missing_bundles_dir_treated_as_no_evidence(self, tmp_path: Path, capsys):
        rc = main(["--bundles-dir", str(tmp_path / "nonexistent")])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "No evidence bundles found" in out

    def test_bundle_with_no_fingerprint_prints_marker(self, tmp_path: Path, capsys):
        (tmp_path / "a.json").write_text(json.dumps({"failure_category": "unknown"}))

        rc = main(["--bundles-dir", str(tmp_path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert "deduped=false" in out
        assert "Bundle has no fingerprint" in out


class TestDataclasses:
    def test_bundle_verdict_fields(self):
        v = BundleVerdict(fingerprint="fp-a", matched_rec_id="rec-1", run_agent=False)
        assert v.fingerprint == "fp-a"
        assert v.matched_rec_id == "rec-1"
        assert v.run_agent is False

    def test_dedup_result_deduped_property(self):
        assert DedupResult(run_agent=True).deduped is False
        assert DedupResult(run_agent=False).deduped is True
