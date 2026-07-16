"""CLI main() + --emit-dir concern: tests/ci_rca/evidence/test_main_emit.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestMain, TestEmitDir.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.ci_rca.evidence import main


class TestEmitDir:
    def test_emit_dir_writes_local_bundle(self, log_file, taxonomy_file, tmp_path, capsys):
        """--emit-dir writes <dir>/<sha>.json independent of S3 outcome and prints BUNDLE_LOCAL=<path>."""
        emit_dir = tmp_path / "emit"
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca.evidence._upload_to_s3"):
                    with patch("scripts.ci_rca.evidence._resolve_bucket", return_value="test-bucket"):
                        main(
                            [
                                "--log-file",
                                str(log_file),
                                "--workflow-name",
                                "CI",
                                "--workflow-run-id",
                                "42",
                                "--taxonomy-path",
                                str(taxonomy_file),
                                "--emit-dir",
                                str(emit_dir),
                            ]
                        )
        out = capsys.readouterr().out
        assert "BUNDLE_LOCAL=" in out
        local_line = next(ln for ln in out.splitlines() if ln.startswith("BUNDLE_LOCAL="))
        local_path = local_line.split("=", 1)[1]
        assert Path(local_path).exists()
        parsed = json.loads(Path(local_path).read_bytes())
        assert "sha256" in parsed
        assert len(parsed["sha256"]) == 64

    def test_emit_dir_writes_on_s3_failure(self, log_file, taxonomy_file, tmp_path, capsys):
        """--emit-dir writes the local bundle even when S3 upload fails."""
        import scripts.ci_rca.evidence as ev_mod

        emit_dir = tmp_path / "emit_fail"
        original_pending = ev_mod._PENDING_DIR
        ev_mod._PENDING_DIR = tmp_path / "pending"
        try:
            with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
                with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                    with patch("scripts.ci_rca.evidence._upload_to_s3", side_effect=Exception("S3 down")):
                        with patch("scripts.ci_rca.evidence._resolve_bucket", return_value="test-bucket"):
                            main(
                                [
                                    "--log-file",
                                    str(log_file),
                                    "--workflow-name",
                                    "CI",
                                    "--workflow-run-id",
                                    "99",
                                    "--taxonomy-path",
                                    str(taxonomy_file),
                                    "--emit-dir",
                                    str(emit_dir),
                                ]
                            )
        finally:
            ev_mod._PENDING_DIR = original_pending
        out = capsys.readouterr().out
        assert "BUNDLE_LOCAL=" in out
        local_line = next(ln for ln in out.splitlines() if ln.startswith("BUNDLE_LOCAL="))
        local_path = local_line.split("=", 1)[1]
        assert Path(local_path).exists()
        parsed = json.loads(Path(local_path).read_bytes())
        assert "sha256" in parsed


class TestMain:
    def test_missing_log_file_exits(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            main(["--log-file", str(tmp_path / "nope.log"), "--workflow-name", "CI", "--workflow-run-id", "1"])
        assert exc_info.value.code != 0

    def test_print_bundle(self, log_file, taxonomy_file, capsys):
        with patch("scripts.ci_rca.tier_map.probe_runtime", return_value=("median=50ms", 0.05)):
            with patch("scripts.ci_rca.tier_map.build_tier_membership", return_value={}):
                with patch("scripts.ci_rca.evidence._upload_to_s3"):
                    with patch("scripts.ci_rca.evidence._resolve_bucket", return_value="test-bucket"):
                        main(
                            [
                                "--log-file",
                                str(log_file),
                                "--workflow-name",
                                "CI",
                                "--workflow-run-id",
                                "1",
                                "--taxonomy-path",
                                str(taxonomy_file),
                                "--print-bundle",
                            ]
                        )
        out = capsys.readouterr().out
        assert "BUNDLE_SHA=" in out
