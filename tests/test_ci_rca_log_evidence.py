from __future__ import annotations

import json
import runpy
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.ci_rca.fingerprint import error_signature_from_log_tail
from scripts.ci_rca.log_evidence import (
    SCHEMA,
    bound_text,
    bound_text_windowed,
    extract_body,
    main,
    publish_envelope,
    read_envelope,
    recovery_url,
    validate_envelope,
)
from tests.fixtures.ci_rca.oversized_validate_log import build_log


def _envelope(body: str = "one\ntwo\n") -> dict:
    bounded, limits = bound_text(body, 100, 10)
    return {
        "schema": SCHEMA,
        "identity": {"repository": "owner/repo", "run_id": 42},
        "failed_jobs": [{"job_id": 7, "conclusion": "failure", "failed_steps": [{"step_index": 2, "conclusion": "failure"}]}],
        "retrieval_path": "primary",
        "scope": [
            {
                "job_id": 7,
                "steps": [
                    {"step_index": 1, "conclusion": "success", "log_retrieved": False},
                    {"step_index": 2, "conclusion": "failure", "log_retrieved": True},
                ],
            }
        ],
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
    for step in envelope["scope"][0]["steps"]:
        step["log_retrieved"] = False
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


class TestFingerprintInputPinned:
    """VP step 1 (AC11): error_signature_from_log_tail over the post-change envelope's body
    equals a FROZEN GOLDEN SIGNATURE captured from origin/main BEFORE any source edit in this
    plan -- not a same-tree recomputation (which would be tautological) -- so Decision 142's
    non-pytest fingerprint keyspace provably does not fork. This module never touches `body`;
    a differing signature means scope data leaked into it (a source-edit constraint violation)."""

    _GOLDEN_BODY = (
        "Run pytest tests/\n"
        "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
        "Error: process completed with exit code 1\n"
    )
    _GOLDEN_SIGNATURE = "pytest::process completed with exit code 1"

    def test_post_change_envelope_body_signature_matches_frozen_golden(self, tmp_path: Path) -> None:
        bounded, limits = bound_text(self._GOLDEN_BODY, 1024, 100)
        envelope = {
            "schema": SCHEMA,
            "identity": {"repository": "owner/repo", "run_id": 42},
            "failed_jobs": [
                {"job_id": 7, "conclusion": "failure", "failed_steps": [{"step_index": 1, "conclusion": "failure"}]}
            ],
            "retrieval_path": "primary",
            "scope": [{"job_id": 7, "steps": [{"step_index": 1, "conclusion": "failure", "log_retrieved": True}]}],
            "fallback_selection": {"queried_job_ids": [7], "unqueried_job_ids": [], "unqueried_reason": None},
            "body": bounded,
            "limits": limits,
            "recovery": {"url": "https://github.com/owner/repo/actions/runs/42", "state": "available"},
        }
        source = tmp_path / "evidence.json"
        publish_envelope(source, envelope)
        published = read_envelope(source)
        assert published["body"] == self._GOLDEN_BODY
        assert error_signature_from_log_tail(published["body"], "pytest") == self._GOLDEN_SIGNATURE


class TestScopeDeclarationCounterfactuals:
    """VP step 2 (AC1/AC2/AC6): the scope block is enforced and accepts the full conclusion
    domain, including success/skipped steps, a null-conclusion not-started step, and a
    truncated body -- volume truncation is orthogonal to scope validation."""

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda value: value.update(scope=None),
            lambda value: value["scope"][0]["steps"].pop(),  # narrower than failed_steps
            lambda value: value["scope"][0]["steps"].append(
                {"step_index": 1, "conclusion": "success", "log_retrieved": False}
            ),  # duplicate index
            lambda value: value["scope"][0]["steps"][1].update(conclusion="success"),  # disagrees with failed_steps
            lambda value: value["scope"][0]["steps"][1].update(log_retrieved=False),  # contradicts retrieval_path
            lambda value: value["scope"][0].update(job_id="7"),  # job_id not an int
            lambda value: value["scope"].append(deepcopy(value["scope"][0])),  # duplicate job entry
            lambda value: value["scope"][0].update(steps="oops"),  # steps is not a list
            lambda value: value["scope"][0]["steps"].append("oops"),  # malformed step entry
            lambda value: value.update(scope=[]),  # scope job set does not match failed jobs
        ],
    )
    def test_rejects_scope_counterfactuals(self, mutate) -> None:
        envelope = _envelope()
        mutate(envelope)
        with pytest.raises(ValueError):
            validate_envelope(envelope)

    def test_well_formed_envelope_validates(self) -> None:
        envelope = _envelope()
        assert validate_envelope(envelope) is envelope

    def test_success_and_skipped_steps_validate(self) -> None:
        envelope = _envelope()
        envelope["scope"][0]["steps"].append({"step_index": 3, "conclusion": "skipped", "log_retrieved": False})
        assert validate_envelope(envelope) is envelope

    def test_null_conclusion_step_in_cancelled_job_validates(self) -> None:
        envelope = _envelope()
        envelope["failed_jobs"] = [
            {"job_id": 7, "conclusion": "cancelled", "failed_steps": [{"step_index": 2, "conclusion": "cancelled"}]}
        ]
        envelope["scope"] = [
            {
                "job_id": 7,
                "steps": [
                    {"step_index": 1, "conclusion": None, "log_retrieved": False},
                    {"step_index": 2, "conclusion": "cancelled", "log_retrieved": True},
                ],
            }
        ]
        assert validate_envelope(envelope) is envelope

    def test_truncated_body_envelope_validates(self) -> None:
        envelope = _envelope()
        envelope["limits"].update(
            complete=False,
            truncation_reason="byte_limit",
            observed_bytes=envelope["limits"]["included_bytes"] + 5,
            observed_lines=envelope["limits"]["included_lines"],
            omitted_bytes=5,
            omitted_lines=0,
        )
        assert validate_envelope(envelope) is envelope


class TestBoundTextWindowed:
    """ci-rca-evidence-fidelity: head + elision marker + tail within the SAME budget bound_text
    uses -- the mechanism that keeps an oversized validate.py log's "Failed checks:" tail inside
    the published body instead of being dropped by a head-only truncation."""

    def test_fits_entirely_behaves_like_bound_text(self) -> None:
        body, limits = bound_text_windowed("one\ntwo\n", 100, 10)
        assert body == "one\ntwo\n"
        assert limits["complete"] is True
        assert limits["truncation_reason"] is None
        assert limits["omitted_bytes"] == 0
        assert limits["omitted_lines"] == 0

    def test_rejects_non_positive_limits(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            bound_text_windowed("body", 0, 1)
        with pytest.raises(ValueError, match="positive"):
            bound_text_windowed("body", 1, 0)

    def test_truncates_with_head_and_tail_present(self) -> None:
        text = "".join(f"line{i}\n" for i in range(1000))
        body, limits = bound_text_windowed(text, 200, 20)
        assert limits["complete"] is False
        assert limits["truncation_reason"] == "head_tail_window"
        assert body.startswith("line0\n")
        assert body.rstrip("\n").endswith("line999")
        assert "[elided]" in body

    def test_balance_invariant_holds(self) -> None:
        text = "".join(f"line{i}\n" for i in range(1000))
        _, limits = bound_text_windowed(text, 200, 20)
        assert limits["observed_bytes"] == limits["included_bytes"] + limits["omitted_bytes"]
        assert limits["observed_lines"] == limits["included_lines"] + limits["omitted_lines"]

    def test_included_never_exceeds_budget(self) -> None:
        text = "".join(f"line{i}\n" for i in range(1000))
        _, limits = bound_text_windowed(text, 200, 20)
        assert limits["included_bytes"] <= 200
        assert limits["included_lines"] <= 20

    def test_real_oversized_fixture_retains_tail_anchor(self) -> None:
        from scripts.ci_rca.log_evidence import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES

        body, limits = bound_text_windowed(build_log(), DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES)
        assert "Failed checks:" in body
        assert "Coverage below 100%" in body
        assert limits["truncation_reason"] == "head_tail_window"

    def test_budget_too_small_for_marker_degrades_to_plain_bound_text(self) -> None:
        """max_bytes smaller than the elision marker itself must not emit a marker-only body
        that overflows the declared budget -- it degrades to plain head truncation instead."""
        text = "".join(f"line{i}\n" for i in range(1000))
        body, limits = bound_text_windowed(text, 5, 1000)
        assert limits["complete"] is False
        assert limits["truncation_reason"] == "head_tail_window"
        assert "[elided]" not in body

    def test_budget_too_small_for_marker_by_line_count_degrades_to_plain_bound_text(self) -> None:
        text = "".join(f"line{i}\n" for i in range(1000))
        body, limits = bound_text_windowed(text, 100_000, 1)
        assert limits["complete"] is False
        assert limits["truncation_reason"] == "head_tail_window"
        assert "[elided]" not in body

    def test_budget_too_small_for_marker_but_content_fits_stays_complete(self) -> None:
        """Degraded path still delegates to bound_text's own complete-fit case -- content that
        fits under the tiny byte budget must not be force-marked truncated."""
        body, limits = bound_text_windowed("hi\n", 5, 1000)
        assert body == "hi\n"
        assert limits["complete"] is True


class TestHeadTailWindowAndDrainCeilingReasons:
    """Both new truncation reasons (head_tail_window, drain_ceiling) must be admitted by BOTH
    hardcoded reason sets: _validate_limits (the body-vs-limits reason) and _validate_selection
    (the unqueried-fallback-job reason) -- the latter is consulted only on a fallback job that
    went unqueried, so missing it there is latent, not immediate."""

    @pytest.mark.parametrize("reason", ["head_tail_window", "drain_ceiling"])
    def test_reason_admitted_by_validate_limits(self, reason: str) -> None:
        envelope = _envelope()
        body, limits = bound_text_windowed("".join(f"line{i}\n" for i in range(1000)), 200, 20)
        envelope["body"] = body
        envelope["limits"] = limits
        envelope["limits"]["truncation_reason"] = reason
        assert validate_envelope(envelope) is envelope

    @pytest.mark.parametrize("reason", ["head_tail_window", "drain_ceiling"])
    def test_reason_admitted_by_validate_selection_unqueried_path(self, reason: str) -> None:
        envelope = _envelope()
        envelope["retrieval_path"] = "fallback"
        envelope["fallback_selection"] = {
            "queried_job_ids": [],
            "unqueried_job_ids": [7],
            "unqueried_reason": "aggregate_limit",
        }
        for step in envelope["scope"][0]["steps"]:
            step["log_retrieved"] = False
        envelope["limits"].update(
            complete=False,
            truncation_reason=reason,
            observed_bytes=None,
            observed_lines=None,
            omitted_bytes=None,
            omitted_lines=None,
        )
        assert validate_envelope(envelope) is envelope

    def test_windowed_envelope_publishes_and_round_trips(self, tmp_path: Path) -> None:
        """Windowed-envelope validation through publish_envelope: an oversized body windowed via
        bound_text_windowed publishes and reads back with its tail anchor intact."""
        text = "".join(f"line{i}\n" for i in range(1000)) + "Failed checks:\n  - Coverage below 100%\n"
        body, limits = bound_text_windowed(text, 400, 40)
        envelope = _envelope()
        envelope["body"] = body
        envelope["limits"] = limits
        source = tmp_path / "evidence.json"
        publish_envelope(source, envelope)
        read_back = read_envelope(source)
        assert read_back["limits"]["truncation_reason"] == "head_tail_window"
        assert "Failed checks:" in read_back["body"]
