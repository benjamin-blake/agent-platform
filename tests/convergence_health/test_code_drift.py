"""Unit tests for scripts.convergence_health.code_drift (rec-2709 Wave 6 package-mirror).

DuckLake and prod-class code-drift alarms. Free of live AWS/git dependencies: the S3 client,
git runner, and portal caller are injected.
"""

from __future__ import annotations

import io
import json
from typing import Any, Optional
from unittest.mock import MagicMock, patch

# boto3 is imported at MODULE scope even though the tests reference it only via
# patch("boto3.Session") strings. This makes the file's heavy-dep requirement visible to the
# fast tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to the full
# post-merge tier, instead of catching it REACTIVELY -- which re-runs the entire changed-test set
# a second time after a runtime ModuleNotFoundError and roughly doubles the pytest cost. boto3 is
# deliberately excluded from requirements-fast.txt; the full tier runs this file. See
# scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401

from scripts.build_lambda_config import (
    _DUCKLAKE_CATALOG_DR_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_WRITER_FUNCTION,
)
from scripts.convergence_health import (
    detect_ducklake_code_drift,
    detect_prod_code_drift,
    find_open_ducklake_drift_rec,
    find_open_prod_drift_rec,
)

_ALL_DUCKLAKE_FUNCTIONS = {
    _DUCKLAKE_WRITER_FUNCTION,
    _DUCKLAKE_READER_FUNCTION,
    _DUCKLAKE_MAINTENANCE_FUNCTION,
    _DUCKLAKE_CATALOG_DR_FUNCTION,
}


_ALL_PROD_FUNCTIONS = {
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
    "agent-platform-ops-compaction",
}


class _FakeDeployRecordsS3:
    """Minimal S3 stub for read_deploy_record: same source_git_sha for every function's Key,
    unless a per-function override is supplied. A function absent from both sha_by_function and
    default_sha raises (simulating a missing/never-deployed record -> read_deploy_record's
    NoSuchKey path returns None)."""

    def __init__(self, default_sha: Any = None, sha_by_function: Optional[dict[str, str]] = None) -> None:
        self._default_sha = default_sha
        self._sha_by_function = sha_by_function or {}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        function = Key.rsplit("/", 1)[-1].removesuffix(".json")
        sha = self._sha_by_function.get(function, self._default_sha)
        if sha is None:
            raise RuntimeError("NoSuchKey")
        body = json.dumps({"code_sha256": "abc", "source_git_sha": sha}).encode()
        return {"Body": io.BytesIO(body)}


class TestFindOpenDucklakeDriftRec:
    def test_returns_first_matching_rec(self) -> None:
        recs = [
            {"id": "rec-100", "source": "ci_rca", "status": "open"},
            {"id": "rec-101", "source": "ducklake_code_drift", "status": "open"},
            {"id": "rec-102", "source": "ducklake_code_drift", "status": "closed"},
        ]
        result = find_open_ducklake_drift_rec(recs)
        assert result is not None
        assert result["id"] == "rec-101"

    def test_returns_none_when_no_match(self) -> None:
        recs = [{"id": "rec-100", "source": "tf_convergence_stale", "status": "open"}]
        assert find_open_ducklake_drift_rec(recs) is None

    def test_returns_none_on_empty_list(self) -> None:
        assert find_open_ducklake_drift_rec([]) is None


class TestDetectDucklakeCodeDrift:
    def _acts_caller(self, acts: list[str]):
        def _caller(action: str, fields: dict[str, Any]) -> Any:
            acts.append(action)
            return "rec-DRYRUN"

        return _caller

    def test_fresh_all_records_match_no_file(self) -> None:
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result == {"action": "none", "rec_id": None}
        assert acts == []

    def test_stale_all_records_mismatch_files_exactly_one(self) -> None:
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts.count("file") == 1

    def test_one_function_stale_still_files_exactly_one(self) -> None:
        """Only the writer is behind main -- ANY stale function triggers ONE rec, not per-function."""
        acts: list[str] = []
        s3 = _FakeDeployRecordsS3(
            default_sha="SHA_NEW",
            sha_by_function={_DUCKLAKE_WRITER_FUNCTION: "SHA_OLD"},
        )
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=s3,
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts == ["file"]

    def test_missing_record_counts_as_stale(self) -> None:
        """A function with NO deploy record at all (never governed-deployed) is stale, not fresh."""
        acts: list[str] = []
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha=None),  # every get_object raises NoSuchKey
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_dedup_second_stale_tick_updates_not_files(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-321", "source": "ducklake_code_drift", "status": "open"}
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "update", "rec_id": "rec-321"}
        assert acts == ["update"]

    def test_fresh_with_open_rec_closes(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-654", "source": "ducklake_code_drift", "status": "open"}
        result = detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "close", "rec_id": "rec-654"}
        assert acts == ["close"]

    def test_reads_all_four_ducklake_functions(self) -> None:
        seen_functions: set[str] = set()

        class _RecordingS3:
            def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
                function = Key.rsplit("/", 1)[-1].removesuffix(".json")
                seen_functions.add(function)
                body = json.dumps({"code_sha256": "abc", "source_git_sha": "SHA_OLD"}).encode()
                return {"Body": io.BytesIO(body)}

        detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_RecordingS3(),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert seen_functions == _ALL_DUCKLAKE_FUNCTIONS

    def test_git_runner_receives_ducklake_source_pathspecs(self) -> None:
        captured_argv: list[list[str]] = []

        def _runner(argv: list[str]) -> str:
            captured_argv.append(argv)
            return "SHA_OLD"

        detect_ducklake_code_drift(
            git_runner=_runner,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert len(captured_argv) == 1
        argv = captured_argv[0]
        assert argv[:4] == ["git", "log", "-1", "--format=%H"]
        assert "src/common/ducklake_*.py" in argv
        assert "config/lambda/ducklake" in argv

    def test_rec_fields_shape_on_file(self) -> None:
        captured: dict[str, Any] = {}

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            if action == "file":
                captured.update(fields)
            return "rec-999"

        detect_ducklake_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=_caller,
            open_recs=[],
        )
        assert captured["source"] == "ducklake_code_drift"
        assert captured["priority"] == "High"
        assert captured["status"] == "open"
        assert _DUCKLAKE_WRITER_FUNCTION in captured["context"]

    def test_open_recs_none_fetches_live_open_recs(self) -> None:
        with patch("scripts.convergence_health.code_drift._fetch_open_recs", return_value=[]) as fetch:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                portal_caller=lambda a, f: "rec-x",
            )
        fetch.assert_called_once()
        assert result == {"action": "none", "rec_id": None}

    def test_s3_client_none_creates_boto3_session_client(self) -> None:
        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = _FakeDeployRecordsS3(default_sha="SHA_OLD")
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
                profile="agent_platform",
            )
        mock_session.assert_called_once_with(profile_name="agent_platform")
        assert result == {"action": "none", "rec_id": None}

    def test_no_portal_caller_uses_real_file_rec(self) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-live") as fr:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_NEW",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[],
            )
        fr.assert_called_once()
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_no_portal_caller_uses_real_update_rec_for_update(self) -> None:
        # Stale record + already-open rec -> the update action's real (portal_caller=None)
        # update_rec branch. Mirrors escalate()'s test_escalate_update_uses_real_portal_when_no_caller.
        existing = {"id": "rec-210", "source": "ducklake_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_NEW",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[existing],
            )
        ur.assert_called_once()
        assert result == {"action": "update", "rec_id": "rec-210"}

    def test_no_portal_caller_uses_real_update_rec_for_close(self) -> None:
        existing = {"id": "rec-200", "source": "ducklake_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = detect_ducklake_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[existing],
            )
        ur.assert_called_once()
        assert result == {"action": "close", "rec_id": "rec-200"}

    def test_default_git_runner_invokes_subprocess(self) -> None:
        completed = MagicMock(returncode=0, stdout="SHA_FROM_SUBPROCESS\n")
        with patch("scripts.convergence_health.code_drift.subprocess.run", return_value=completed) as run:
            result = detect_ducklake_code_drift(
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_FROM_SUBPROCESS"),
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
            )
        run.assert_called_once()
        assert result == {"action": "none", "rec_id": None}


class TestFindOpenProdDriftRec:
    def test_returns_first_matching_rec(self) -> None:
        recs = [
            {"id": "rec-100", "source": "ci_rca", "status": "open"},
            {"id": "rec-101", "source": "prod_code_drift", "status": "open"},
            {"id": "rec-102", "source": "prod_code_drift", "status": "closed"},
        ]
        result = find_open_prod_drift_rec(recs)
        assert result is not None
        assert result["id"] == "rec-101"

    def test_returns_none_when_no_match(self) -> None:
        recs = [{"id": "rec-100", "source": "ducklake_code_drift", "status": "open"}]
        assert find_open_prod_drift_rec(recs) is None

    def test_returns_none_on_empty_list(self) -> None:
        assert find_open_prod_drift_rec([]) is None


class TestDetectProdCodeDrift:
    def _acts_caller(self, acts: list[str]):
        def _caller(action: str, fields: dict[str, Any]) -> Any:
            acts.append(action)
            return "rec-DRYRUN"

        return _caller

    def test_fresh_all_records_match_no_file(self) -> None:
        acts: list[str] = []
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result == {"action": "none", "rec_id": None}
        assert acts == []

    def test_stale_all_records_mismatch_files_exactly_one(self) -> None:
        acts: list[str] = []
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts.count("file") == 1

    def test_one_function_stale_still_files_exactly_one(self) -> None:
        """Only the dispatcher is behind main -- ANY stale function triggers ONE rec, not per-function."""
        acts: list[str] = []
        s3 = _FakeDeployRecordsS3(
            default_sha="SHA_NEW",
            sha_by_function={"agent-platform-scheduled-agent-dispatcher": "SHA_OLD"},
        )
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=s3,
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts == ["file"]

    def test_missing_record_counts_as_stale(self) -> None:
        """A function with NO deploy record at all (never governed-deployed) is stale, not fresh."""
        acts: list[str] = []
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha=None),  # every get_object raises NoSuchKey
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_dedup_second_stale_tick_updates_not_files(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-321", "source": "prod_code_drift", "status": "open"}
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "update", "rec_id": "rec-321"}
        assert acts == ["update"]

    def test_fresh_with_open_rec_closes(self) -> None:
        acts: list[str] = []
        existing = {"id": "rec-654", "source": "prod_code_drift", "status": "open"}
        result = detect_prod_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[existing],
        )
        assert result == {"action": "close", "rec_id": "rec-654"}
        assert acts == ["close"]

    def test_reads_all_three_prod_functions(self) -> None:
        seen_functions: set[str] = set()

        class _RecordingS3:
            def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
                assert Key.startswith("deploy-records/prod/")
                function = Key.rsplit("/", 1)[-1].removesuffix(".json")
                seen_functions.add(function)
                body = json.dumps({"code_sha256": "abc", "source_git_sha": "SHA_OLD"}).encode()
                return {"Body": io.BytesIO(body)}

        detect_prod_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_RecordingS3(),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert seen_functions == _ALL_PROD_FUNCTIONS

    def test_git_runner_receives_prod_source_pathspecs(self) -> None:
        captured_argv: list[list[str]] = []

        def _runner(argv: list[str]) -> str:
            captured_argv.append(argv)
            return "SHA_OLD"

        detect_prod_code_drift(
            git_runner=_runner,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert len(captured_argv) == 1
        argv = captured_argv[0]
        assert argv[:4] == ["git", "log", "-1", "--format=%H"]
        assert "src/data/handlers" in argv
        assert "config/lambda/data-pipeline" in argv
        assert "config/lambda/ops-compaction" in argv

    def test_rec_fields_shape_on_file(self) -> None:
        captured: dict[str, Any] = {}

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            if action == "file":
                captured.update(fields)
            return "rec-999"

        detect_prod_code_drift(
            git_runner=lambda argv: "SHA_NEW",
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=_caller,
            open_recs=[],
        )
        assert captured["source"] == "prod_code_drift"
        assert captured["priority"] == "High"
        assert captured["status"] == "open"
        assert "agent-platform-scheduled-agent-dispatcher" in captured["context"]

    def test_open_recs_none_fetches_live_open_recs(self) -> None:
        with patch("scripts.convergence_health.code_drift._fetch_open_recs", return_value=[]) as fetch:
            result = detect_prod_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                portal_caller=lambda a, f: "rec-x",
            )
        fetch.assert_called_once()
        assert result == {"action": "none", "rec_id": None}

    def test_s3_client_none_creates_boto3_session_client(self) -> None:
        with patch("boto3.Session") as mock_session:
            mock_session.return_value.client.return_value = _FakeDeployRecordsS3(default_sha="SHA_OLD")
            result = detect_prod_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
                profile="agent_platform",
            )
        mock_session.assert_called_once_with(profile_name="agent_platform")
        assert result == {"action": "none", "rec_id": None}

    def test_no_portal_caller_uses_real_file_rec(self) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-live") as fr:
            result = detect_prod_code_drift(
                git_runner=lambda argv: "SHA_NEW",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[],
            )
        fr.assert_called_once()
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_no_portal_caller_uses_real_update_rec_for_update(self) -> None:
        existing = {"id": "rec-210", "source": "prod_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = detect_prod_code_drift(
                git_runner=lambda argv: "SHA_NEW",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[existing],
            )
        ur.assert_called_once()
        assert result == {"action": "update", "rec_id": "rec-210"}

    def test_no_portal_caller_uses_real_update_rec_for_close(self) -> None:
        existing = {"id": "rec-200", "source": "prod_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = detect_prod_code_drift(
                git_runner=lambda argv: "SHA_OLD",
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[existing],
            )
        ur.assert_called_once()
        assert result == {"action": "close", "rec_id": "rec-200"}

    def test_default_git_runner_invokes_subprocess(self) -> None:
        completed = MagicMock(returncode=0, stdout="SHA_FROM_SUBPROCESS\n")
        with patch("scripts.convergence_health.code_drift.subprocess.run", return_value=completed) as run:
            result = detect_prod_code_drift(
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_FROM_SUBPROCESS"),
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
            )
        run.assert_called_once()
        assert result == {"action": "none", "rec_id": None}
