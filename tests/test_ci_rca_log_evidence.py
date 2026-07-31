from __future__ import annotations

import json
import runpy
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.ci_rca.log_evidence import (
    SCHEMA,
    bound_text,
    extract_body,
    main,
    publish_envelope,
    recovery_url,
    validate_envelope,
)


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


def test_invalid_positive_limits_and_unsafe_parsed_url(monkeypatch) -> None:
    with pytest.raises(ValueError, match="positive"):
        bound_text("body", 0, 1)
    monkeypatch.setattr(
        "scripts.ci_rca.log_evidence.urlsplit",
        lambda _url: type("Parsed", (), {"scheme": "http", "hostname": "github.com", "query": "", "username": None})(),
    )
    with pytest.raises(ValueError, match="unsafe"):
        recovery_url("owner/repo", "1")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value.update(limits=None), "missing limit"),
        (lambda value: value["limits"].update(max_bytes=1), "exceeds"),
        (lambda value: value["limits"].update(observed_bytes=None), "unknown omitted"),
        (lambda value: value["limits"].update(observed_bytes="2"), "invalid observed"),
        (lambda value: value.update(failed_jobs=[]), "missing failed job"),
        (lambda value: value["failed_jobs"][0].update(job_id=None), "invalid failed job"),
        (lambda value: value["failed_jobs"][0].update(failed_steps=None), "invalid failed step"),
        (lambda value: value["failed_jobs"][0]["failed_steps"][0].update(step_index=True), "invalid failed step"),
        (lambda value: value.update(fallback_selection=None), "missing fallback"),
        (lambda value: value["fallback_selection"].update(unqueried_reason="aggregate_limit"), "unqueried job reason"),
        (lambda value: value.update(schema="wrong"), "schema"),
        (lambda value: value.update(body=""), "body is empty"),
        (lambda value: value.update(identity=None), "missing retrieval identity"),
        (lambda value: value.update(recovery=None), "recovery reference"),
        (lambda value: value["recovery"].update(state="unknown"), "recovery reference"),
    ],
)
def test_validation_rejects_each_invalid_envelope_class(mutate, message: str) -> None:
    envelope = _envelope()
    mutate(envelope)
    with pytest.raises(ValueError, match=message):
        validate_envelope(envelope)


def test_validation_rejects_boolean_limit_count() -> None:
    envelope = _envelope("x")
    envelope["limits"]["max_lines"] = True
    with pytest.raises(ValueError, match="invalid retrieval limit"):
        validate_envelope(envelope)


def test_cli_validates_extracts_and_reports_invalid_input(tmp_path: Path, capsys) -> None:
    source = tmp_path / "evidence.json"
    body = tmp_path / "body.log"
    publish_envelope(source, _envelope())
    assert main(["--validate", str(source), "--extract-body", str(body)]) == 0
    assert body.read_text(encoding="utf-8") == "one\ntwo\n"
    source.write_text("not json", encoding="utf-8")
    assert main(["--validate", str(source)]) == 1
    assert "::error::" in capsys.readouterr().out


def test_module_entrypoint(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "evidence.json"
    publish_envelope(source, _envelope())
    monkeypatch.setattr(sys, "argv", ["log_evidence", "--validate", str(source)])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("scripts.ci_rca.log_evidence", run_name="__main__")
    assert exc_info.value.code == 0
