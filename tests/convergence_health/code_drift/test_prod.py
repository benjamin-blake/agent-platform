"""Unit tests for scripts.convergence_health.code_drift's prod-class alarm (T2.43 / Decision
125/126), including the reachability oracle (Decision 103) that fixed the 2026-08-17 incident:
the workflow_dispatch recovery-deploy case that caused it (a recorded sha postdating the latest
prod-source commit must report FRESH, never stale), and fail-closed behaviour on a null,
unresolvable, or empty recorded/latest sha. Split out of the retired single-file
convergence_health drift-test monolith (PLAN-convergence-health-prod-drift-red).

Free of live AWS/git dependencies: the S3 client, git runner, and portal caller are injected.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

# boto3 is imported at MODULE scope even though the tests reference it only via
# patch("boto3.Session") strings. This makes the file's heavy-dep requirement visible to the
# fast tier's cheap `--collect-only` pass so pr-validate defers it PROACTIVELY to the full
# post-merge tier, instead of catching it REACTIVELY -- which re-runs the entire changed-test set
# a second time after a runtime ModuleNotFoundError and roughly doubles the pytest cost. boto3 is
# deliberately excluded from requirements-fast.txt; the full tier runs this file. See
# scripts/checks/_scaffolding.py::partition_changed_tests_by_collectability.
import boto3  # noqa: F401

from scripts.convergence_health import detect_prod_code_drift, find_open_prod_drift_rec

from .conftest import GitRunnerStub, _FakeDeployRecordsS3, _RecordingS3

_ALL_PROD_FUNCTIONS = {
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
    "agent-platform-ops-compaction",
}


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
        stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_OLD": "SHA_OLD"})
        result = detect_prod_code_drift(
            git_runner=stub,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=self._acts_caller(acts),
            open_recs=[],
        )
        assert result["action"] == "file"
        assert acts.count("file") == 1

    def test_one_function_stale_still_files_exactly_one(self) -> None:
        """Only the dispatcher is behind main -- ANY stale function triggers ONE rec, not per-function."""
        acts: list[str] = []
        stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_NEW": "SHA_NEW", "SHA_OLD": "SHA_OLD"})
        s3 = _FakeDeployRecordsS3(
            default_sha="SHA_NEW",
            sha_by_function={"agent-platform-scheduled-agent-dispatcher": "SHA_OLD"},
        )
        result = detect_prod_code_drift(
            git_runner=stub,
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
        stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_OLD": "SHA_OLD"})
        result = detect_prod_code_drift(
            git_runner=stub,
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
        detect_prod_code_drift(
            git_runner=lambda argv: "SHA_OLD",
            s3_client=_RecordingS3(seen_functions, expected_key_prefix="deploy-records/prod/"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert seen_functions == _ALL_PROD_FUNCTIONS

    def test_git_runner_receives_prod_source_pathspecs(self) -> None:
        stub = GitRunnerStub(head_latest="SHA_OLD", reachable={"SHA_OLD": "SHA_OLD"})
        detect_prod_code_drift(
            git_runner=stub,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert ["git", "rev-parse", "--is-shallow-repository"] in stub.calls
        head_calls = [c for c in stub.calls if c[:4] == ["git", "log", "-1", "--format=%H"] and c[4] == "--"]
        assert len(head_calls) == 1
        argv = head_calls[0]
        assert "src/data/handlers" in argv
        assert "config/lambda/data-pipeline" in argv
        assert "config/lambda/ops-compaction" in argv

    def test_prod_source_pathspecs_includes_outbox_retirement_sole_home(self) -> None:
        """PLAN-opswriter-never-drain-guard: the sole home is a prod source, so an edit to it
        triggers the governed deploy and is visible to the drift sensor (rec-2929)."""
        from scripts.convergence_health import PROD_SOURCE_PATHSPECS

        assert "src/common/outbox_retirement.py" in PROD_SOURCE_PATHSPECS

    def test_rec_fields_shape_on_file(self) -> None:
        captured: dict[str, Any] = {}

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            if action == "file":
                captured.update(fields)
            return "rec-999"

        stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_OLD": "SHA_OLD"})
        detect_prod_code_drift(
            git_runner=stub,
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
            stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_OLD": "SHA_OLD"})
            result = detect_prod_code_drift(
                git_runner=stub,
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                open_recs=[],
            )
        fr.assert_called_once()
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_no_portal_caller_uses_real_update_rec_for_update(self) -> None:
        existing = {"id": "rec-210", "source": "prod_code_drift", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            stub = GitRunnerStub(head_latest="SHA_NEW", reachable={"SHA_OLD": "SHA_OLD"})
            result = detect_prod_code_drift(
                git_runner=stub,
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
        assert run.called
        assert run.call_count >= 2  # shallow-history guard + HEAD latest lookup, at minimum
        assert result == {"action": "none", "rec_id": None}


class TestReachabilityOracle:
    """Decision 103: freshness is reachability, not equality. Covers the exact incident scenario
    (a workflow_dispatch recovery deploy stamping a sha that postdates the latest prod-source
    commit) plus every fail-closed-on-uncertainty case named in the plan's constraints."""

    def test_dispatch_deploy_postdating_latest_source_commit_is_fresh(self) -> None:
        """The 2026-08-17 incident case: the deployed sha (149c36b, a workflow_dispatch run) is
        NEWER than the latest prod-source commit (d024e63f) but never itself touches prod source
        -- so it does not equal latest_sha, yet the reachability oracle must still report FRESH."""
        stub = GitRunnerStub(
            head_latest="d024e63fd024e63fd024e63fd024e63fd024e63f",
            reachable={"149c36b149c36b149c36b149c36b149c36b149c3": "d024e63fd024e63fd024e63fd024e63fd024e63f"},
        )
        result = detect_prod_code_drift(
            git_runner=stub,
            s3_client=_FakeDeployRecordsS3(default_sha="149c36b149c36b149c36b149c36b149c36b149c3"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert result == {"action": "none", "rec_id": None}

    def test_null_source_git_sha_field_on_a_present_record_is_stale(self) -> None:
        """A break-glass local deploy sets source_git_sha: null (no GITHUB_SHA). This drives an
        explicit null FIELD through a real, present record (distinct from test_missing_record_
        counts_as_stale, which covers an absent record entirely) -- fail closed either way."""
        import io
        import json

        class _NullShaS3:
            def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
                body = json.dumps({"code_sha256": "abc", "source_git_sha": None}).encode()
                return {"Body": io.BytesIO(body)}

        stub = GitRunnerStub(head_latest="SHA_NEW")
        result = detect_prod_code_drift(
            git_runner=stub,
            s3_client=_NullShaS3(),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_unresolvable_recorded_sha_is_stale(self) -> None:
        """A recorded sha the reachability lookup cannot resolve (git exits non-zero, stdout
        empty -- GitRunnerStub's default `reachable.get(sha, "")`) reports stale, not fresh."""
        stub = GitRunnerStub(head_latest="SHA_NEW", reachable={})  # every sha lookup misses -> ""
        result = detect_prod_code_drift(
            git_runner=stub,
            s3_client=_FakeDeployRecordsS3(default_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_empty_latest_sha_treats_every_function_as_stale(self) -> None:
        """The empty-latest_sha guard: if HEAD's own latest-source-commit lookup fails to resolve
        (empty string), every function is fail-closed to stale rather than trivially "matching"
        an empty comparison target."""
        stub = GitRunnerStub(head_latest="", reachable={"SHA_OLD": ""})
        result = detect_prod_code_drift(
            git_runner=stub,
            s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
            portal_caller=lambda a, f: "rec-x",
            open_recs=[],
        )
        assert result["action"] == "file"

    def test_shallow_clone_fails_loud(self) -> None:
        """convergence-health.yml checks out with fetch-depth 0; a regression to a shallow clone
        must fail loud (Decision 55 anti-masking) rather than silently reporting drift."""
        stub = GitRunnerStub(is_shallow=True)
        try:
            detect_prod_code_drift(
                git_runner=stub,
                s3_client=_FakeDeployRecordsS3(default_sha="SHA_OLD"),
                portal_caller=lambda a, f: "rec-x",
                open_recs=[],
            )
            raise AssertionError("expected RuntimeError for a shallow clone")
        except RuntimeError as exc:
            assert "shallow" in str(exc)
