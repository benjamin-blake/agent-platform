from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_rca.evidence_input import load_retrieval_input
from scripts.ci_rca.log_evidence import SCHEMA, bound_text, publish_envelope


def _write_input(tmp_path: Path, *, run_id: int = 42, state: str = "available") -> tuple[Path, Path]:
    body_path = tmp_path / "body.log"
    body_path.write_text("failure\n", encoding="utf-8")
    _, limits = bound_text("failure\n", 100, 10)
    envelope_path = tmp_path / "envelope.json"
    publish_envelope(
        envelope_path,
        {
            "schema": SCHEMA,
            "identity": {"repository": "owner/repo", "run_id": run_id},
            "failed_jobs": [{"job_id": 1, "conclusion": "failure", "failed_steps": []}],
            "retrieval_path": "primary",
            "scope": [{"job_id": 1, "steps": []}],
            "fallback_selection": {"queried_job_ids": [1], "unqueried_job_ids": [], "unqueried_reason": None},
            "body": "failure\n",
            "limits": limits,
            "recovery": {"url": f"https://github.com/owner/repo/actions/runs/{run_id}", "state": state},
        },
    )
    return envelope_path, body_path


def test_load_retrieval_input_returns_typed_provenance(tmp_path: Path) -> None:
    envelope, body = _write_input(tmp_path)
    result = load_retrieval_input(envelope, body, 42)
    assert "body" not in result
    assert result["identity"]["run_id"] == 42


def test_load_retrieval_input_rejects_mismatched_body(tmp_path: Path) -> None:
    envelope, body = _write_input(tmp_path)
    body.write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_retrieval_input(envelope, body, 42)


def test_load_retrieval_input_rejects_expired_recovery(tmp_path: Path) -> None:
    envelope, body = _write_input(tmp_path, state="expired")
    with pytest.raises(ValueError, match="expired"):
        load_retrieval_input(envelope, body, 42)


def test_load_retrieval_input_rejects_mismatched_run_id(tmp_path: Path) -> None:
    envelope, body = _write_input(tmp_path)
    with pytest.raises(ValueError, match="run identity"):
        load_retrieval_input(envelope, body, 43)


class TestScopePropagation:
    """VP step 4 (AC16): load_retrieval_input carries `scope` into retrieval_evidence, and a v1
    envelope (pre-dating this plan's schema bump) is rejected."""

    def test_scope_reaches_retrieval_evidence(self, tmp_path: Path) -> None:
        envelope, body = _write_input(tmp_path)
        result = load_retrieval_input(envelope, body, 42)
        assert result["scope"] == [{"job_id": 1, "steps": []}]

    def test_v1_envelope_is_rejected(self, tmp_path: Path) -> None:
        body_path = tmp_path / "body.log"
        body_path.write_text("failure\n", encoding="utf-8")
        _, limits = bound_text("failure\n", 100, 10)
        envelope_path = tmp_path / "v1_envelope.json"
        envelope_path.write_text(
            json.dumps(
                {
                    "schema": "ci-rca-log-evidence/v1",
                    "identity": {"repository": "owner/repo", "run_id": 42},
                    "failed_jobs": [{"job_id": 1, "conclusion": "failure", "failed_steps": []}],
                    "retrieval_path": "primary",
                    "scope": [{"job_id": 1, "steps": []}],
                    "fallback_selection": {"queried_job_ids": [1], "unqueried_job_ids": [], "unqueried_reason": None},
                    "body": "failure\n",
                    "limits": limits,
                    "recovery": {"url": "https://github.com/owner/repo/actions/runs/42", "state": "available"},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="invalid retrieval evidence schema"):
            load_retrieval_input(envelope_path, body_path, 42)
