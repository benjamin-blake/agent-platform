"""Unit tests for scripts.ci_rca.designed_refusal (100% coverage).

Covers the fail-closed predicate's four behaviours (PLAN-ci-rca-ops-plane-coverage VP step 1):
skip when only a declared designed-refusal job failed; do NOT skip when an undeclared job also
failed; do NOT skip on an empty job set; do NOT skip on a `{}` or unparseable jobs file.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci_rca.designed_refusal import (
    DESIGNED_REFUSAL_JOBS,
    _load_jobs_payload,
    is_designed_refusal,
    main,
    resolve_failing_jobs,
)


class TestResolveFailingJobs:
    def test_single_failing_job(self) -> None:
        payload = {"jobs": [{"name": "reconcile-gate", "conclusion": "failure"}]}
        assert resolve_failing_jobs(payload) == {"reconcile-gate"}

    def test_ignores_non_failing_jobs(self) -> None:
        payload = {
            "jobs": [
                {"name": "reconcile-gate", "conclusion": "failure"},
                {"name": "deploy-maintenance", "conclusion": "success"},
            ]
        }
        assert resolve_failing_jobs(payload) == {"reconcile-gate"}

    def test_empty_dict_yields_empty_set(self) -> None:
        assert resolve_failing_jobs({}) == set()

    def test_non_dict_payload_yields_empty_set(self) -> None:
        assert resolve_failing_jobs([]) == set()  # type: ignore[arg-type]

    def test_non_list_jobs_key_yields_empty_set(self) -> None:
        assert resolve_failing_jobs({"jobs": "not-a-list"}) == set()

    def test_non_dict_job_entry_ignored(self) -> None:
        payload = {"jobs": ["not-a-dict", {"name": "reconcile-gate", "conclusion": "failure"}]}
        assert resolve_failing_jobs(payload) == {"reconcile-gate"}

    def test_missing_name_ignored(self) -> None:
        payload = {"jobs": [{"conclusion": "failure"}]}
        assert resolve_failing_jobs(payload) == set()


class TestIsDesignedRefusal:
    def test_skips_when_only_declared_job_failed(self) -> None:
        payload = {"jobs": [{"name": "reconcile-gate", "conclusion": "failure"}]}
        assert is_designed_refusal("deploy-ducklake-lambdas", payload) is True

    def test_does_not_skip_when_undeclared_job_also_failed(self) -> None:
        payload = {
            "jobs": [
                {"name": "reconcile-gate", "conclusion": "failure"},
                {"name": "deploy-maintenance", "conclusion": "failure"},
            ]
        }
        assert is_designed_refusal("deploy-ducklake-lambdas", payload) is False

    def test_does_not_skip_on_empty_job_set(self) -> None:
        payload = {"jobs": []}
        assert is_designed_refusal("deploy-ducklake-lambdas", payload) is False

    def test_does_not_skip_on_empty_payload(self) -> None:
        assert is_designed_refusal("deploy-ducklake-lambdas", {}) is False

    def test_does_not_skip_for_undeclared_slug(self) -> None:
        payload = {"jobs": [{"name": "reconcile-gate", "conclusion": "failure"}]}
        assert is_designed_refusal("rec-autoclose", payload) is False

    def test_does_not_skip_when_only_undeclared_job_failed(self) -> None:
        payload = {"jobs": [{"name": "some-other-job", "conclusion": "failure"}]}
        assert is_designed_refusal("deploy-ducklake-lambdas", payload) is False


class TestLoadJobsPayload:
    def test_reads_valid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "jobs.json"
        p.write_text(json.dumps({"jobs": [{"name": "x", "conclusion": "failure"}]}), encoding="utf-8")
        assert _load_jobs_payload(p) == {"jobs": [{"name": "x", "conclusion": "failure"}]}

    def test_empty_object_file(self, tmp_path: Path) -> None:
        p = tmp_path / "jobs.json"
        p.write_text("{}", encoding="utf-8")
        assert _load_jobs_payload(p) == {}

    def test_unparseable_file_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "jobs.json"
        p.write_text("not json at all {{{", encoding="utf-8")
        assert _load_jobs_payload(p) == {}

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert _load_jobs_payload(tmp_path / "does-not-exist.json") == {}

    def test_non_dict_json_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "jobs.json"
        p.write_text("[]", encoding="utf-8")
        assert _load_jobs_payload(p) == {}


class TestMain:
    def test_prints_skip_true_for_declared_job_only(self, tmp_path: Path, capsys) -> None:
        p = tmp_path / "jobs.json"
        p.write_text(json.dumps({"jobs": [{"name": "reconcile-gate", "conclusion": "failure"}]}), encoding="utf-8")
        rc = main(["--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "skip=true"

    def test_prints_skip_false_when_undeclared_job_also_failed(self, tmp_path: Path, capsys) -> None:
        p = tmp_path / "jobs.json"
        p.write_text(
            json.dumps(
                {
                    "jobs": [
                        {"name": "reconcile-gate", "conclusion": "failure"},
                        {"name": "deploy-maintenance", "conclusion": "failure"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        rc = main(["--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "skip=false"

    def test_prints_skip_false_on_empty_job_set(self, tmp_path: Path, capsys) -> None:
        p = tmp_path / "jobs.json"
        p.write_text(json.dumps({"jobs": []}), encoding="utf-8")
        rc = main(["--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "skip=false"

    def test_prints_skip_false_on_unparseable_jobs_file(self, tmp_path: Path, capsys) -> None:
        p = tmp_path / "jobs.json"
        p.write_text("{{{not json", encoding="utf-8")
        rc = main(["--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "skip=false"

    def test_prints_skip_false_on_empty_object_jobs_file(self, tmp_path: Path, capsys) -> None:
        p = tmp_path / "jobs.json"
        p.write_text("{}", encoding="utf-8")
        rc = main(["--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "skip=false"


class TestDeclaredJobsMapping:
    def test_only_deploy_ducklake_lambdas_declared(self) -> None:
        assert dict(DESIGNED_REFUSAL_JOBS) == {"deploy-ducklake-lambdas": frozenset({"reconcile-gate"})}


class TestCliMain:
    # This module is already imported at collection time (for the direct-call tests above), so
    # it is already in sys.modules by the time runpy re-executes it below -- the standard, benign
    # runpy caveat for this pattern (docs.python.org/3/library/runpy.html).
    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_runpy_main_prints_skip_and_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        p = tmp_path / "jobs.json"
        p.write_text(json.dumps({"jobs": [{"name": "reconcile-gate", "conclusion": "failure"}]}), encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            ["designed_refusal", "--jobs-json", str(p), "--workflow-slug", "deploy-ducklake-lambdas"],
        )
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("scripts.ci_rca.designed_refusal", run_name="__main__")
        assert exc_info.value.code == 0
        assert capsys.readouterr().out.strip() == "skip=true"
