from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.ci_rca.log_evidence import SCHEMA, bound_text, extract_body, publish_envelope, recovery_url, validate_envelope


def _envelope(body: str = "one\ntwo\n") -> dict:
    bounded, limits = bound_text(body, 100, 10)
    return {
        "schema": SCHEMA,
        "identity": {"repository": "owner/repo", "run_id": 42},
        "failed_jobs": [{"job_id": 7, "conclusion": "failure", "failed_steps": [{"step_index": 2, "conclusion": "failure"}]}],
        "retrieval_path": "primary",
        "fallback_selection": {"queried_job_ids": [7], "unqueried_job_ids": [], "unqueried_reason": None},
        "body": bounded,
        "limits": limits,
        "recovery": {"url": "https://github.com/owner/repo/actions/runs/42", "state": "available"},
    }


def test_exact_utf8_byte_and_line_limits() -> None:
    body, metadata = bound_text("aé\nnext\n", 4, 5)
    assert body == "aé\n"
    assert metadata == {
        "max_bytes": 4,
        "max_lines": 5,
        "observed_bytes": 9,
        "observed_lines": 2,
        "included_bytes": 4,
        "included_lines": 1,
        "omitted_bytes": 5,
        "omitted_lines": 1,
        "complete": False,
        "truncation_reason": "byte_limit",
    }


def test_atomic_publish_and_validated_extract(tmp_path: Path) -> None:
    source = tmp_path / "evidence.json"
    body = tmp_path / "body.log"
    publish_envelope(source, _envelope())
    extract_body(source, body)
    assert body.read_text(encoding="utf-8") == "one\ntwo\n"
    assert json.loads(source.read_text(encoding="utf-8"))["schema"] == SCHEMA


@pytest.mark.parametrize("repo,run", [("owner/repo?token=x", "1"), ("owner/repo", "0"), ("x", "1")])
def test_recovery_url_rejects_injection(repo: str, run: str) -> None:
    with pytest.raises(ValueError):
        recovery_url(repo, run)


def test_validation_rejects_body_metadata_mismatch() -> None:
    envelope = _envelope()
    envelope["body"] += "extra"
    with pytest.raises(ValueError, match="does not match"):
        validate_envelope(envelope)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(retrieval_path="whole_run"),
        lambda value: value["failed_jobs"].append(deepcopy(value["failed_jobs"][0])),
        lambda value: value["failed_jobs"][0].update(conclusion="success"),
        lambda value: value["failed_jobs"][0]["failed_steps"].append({"step_index": 2, "conclusion": "failure"}),
        lambda value: value["limits"].update(complete=True, truncation_reason="byte_limit"),
        lambda value: value["limits"].update(observed_bytes=999),
        lambda value: value["fallback_selection"].update(queried_job_ids=[], unqueried_job_ids=[]),
    ],
)
def test_validation_rejects_inconsistent_typed_fields(mutate) -> None:
    envelope = _envelope()
    mutate(envelope)
    with pytest.raises(ValueError):
        validate_envelope(envelope)


def test_atomic_extract_preserves_previous_body_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "evidence.json"
    destination = tmp_path / "body.log"
    destination.write_text("previous", encoding="utf-8")
    publish_envelope(source, _envelope())
    monkeypatch.setattr("scripts.ci_rca.log_evidence.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        extract_body(source, destination)
    assert destination.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob(".body.log.*")) == []


def test_expired_recovery_refuses_body_extraction(tmp_path: Path) -> None:
    source = tmp_path / "expired.json"
    envelope = _envelope()
    envelope["recovery"]["state"] = "expired"
    publish_envelope(source, envelope)
    with pytest.raises(ValueError, match="expired"):
        extract_body(source, tmp_path / "body.log")


def test_unqueried_fallback_jobs_require_unknown_incomplete_counts() -> None:
    envelope = _envelope()
    envelope["retrieval_path"] = "fallback"
    envelope["fallback_selection"] = {
        "queried_job_ids": [],
        "unqueried_job_ids": [7],
        "unqueried_reason": "aggregate_limit",
    }
    with pytest.raises(ValueError, match="unknown incomplete"):
        validate_envelope(envelope)

    envelope["limits"].update(
        complete=False,
        truncation_reason="byte_limit",
        observed_bytes=None,
        observed_lines=None,
        omitted_bytes=None,
        omitted_lines=None,
    )
    assert validate_envelope(envelope) is envelope
