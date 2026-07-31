"""Tests for the unobserved_steps stamp-and-echo cross-check (check-5), split into its own
guard-free module (PLAN-ci-rca-evidence-scope-declaration).

Deliberately NOT co-located with tests/ops_data_portal/test_ci_rca_runtime.py: that module
carries a module-level `pytest.importorskip("duckdb")` (line 22), which is absent from
pr-validate's fast tier requirements (requirements-fast + requirements-dev only) -- the whole
module would skip there, and the interactive VP-replay gate reads that as a hard failure (exit
4, no collectors) rather than a benign skip, per the sibling PLAN-ci-rca-abstention-and-citation's
CI job 91219816511. This module imports scripts.ops_data_portal directly with no duckdb
dependency.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import scripts.ops_data_portal as p
from scripts.ops_portal import ci_rca_schema as _ci_rca_schema_mod

_REC_2923_SCOPE = [
    {
        "job_id": 30615075007,
        "steps": [
            {"step_index": 15, "conclusion": "failure", "log_retrieved": True},
            {"step_index": 16, "conclusion": "skipped", "log_retrieved": False},
            {"step_index": 17, "conclusion": "success", "log_retrieved": False},
        ],
    }
]


def _make_bundle(tmp_path: Path, *, scope: list[dict[str, Any]] | None = None, **overrides: Any) -> tuple[str, dict[str, Any]]:
    """Write a valid bundle JSON to tmp_path/logs/.ci-rca-evidence-pending/<sha>.json -- mirrors
    TestCiRcaCrossCheckSpine._make_bundle in test_ci_rca_runtime.py, with a retrieval_evidence.scope
    block when `scope` is given (omitted entirely to model a pre-this-plan bundle)."""
    bundle_data: dict[str, Any] = {
        "earliest_viable_gate": "pre",
        "escape_mode": "tier_misplaced",
        "vacuous_pass": False,
    }
    if scope is not None:
        bundle_data["retrieval_evidence"] = {"scope": scope}
    bundle_data.update(overrides)
    payload = {k: v for k, v in bundle_data.items() if k != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    sha = hashlib.sha256(encoded).hexdigest()
    bundle_data["sha256"] = sha
    pending_dir = tmp_path / "logs" / ".ci-rca-evidence-pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / f"{sha}.json").write_bytes(
        json.dumps(bundle_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    )
    return sha, bundle_data


def _ctx_v2(**detection_gap_overrides: Any) -> dict[str, Any]:
    dg = {
        "earliest_viable_gate": "pre",
        "actual_gate_that_caught_it": "CI",
        "gap_explanation": "test gap explanation with enough chars for the field, cites scripts/validate.py:1",
    }
    dg.update(detection_gap_overrides)
    return {
        "schema_version": 2,
        "proximate_cause": "x" * 100,
        "why_chain": ["a " * 25, "b " * 25, "c " * 25 + "systemic scripts/validate.py:1"],
        "detection_gap": dg,
        "recurrence_class": "novel",
        "corrective_action": "x" * 100,
        "preventive_action": "x" * 100,
    }


class TestUnobservedStepsStampAndEcho:
    """check-5: unobserved_steps (agent echo) vs unobserved_steps_authoritative (code stamp)."""

    def test_stamp_lands_even_with_no_agent_echo(self, tmp_path: Path) -> None:
        """AC7: unobserved_steps_authoritative is stamped from the verified bundle regardless of
        whether the agent supplied unobserved_steps at all; the (absent) echo key is untouched."""
        sha, _ = _make_bundle(tmp_path, scope=_REC_2923_SCOPE)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # warn mode: must not raise

        assert ctx["unobserved_steps_authoritative"] == [
            {"job_id": 30615075007, "step_index": 16},
            {"job_id": 30615075007, "step_index": 17},
        ]
        assert "unobserved_steps" not in ctx

    def test_rec_2923_replay_stamps_in_warn_raises_in_strict(self, tmp_path: Path) -> None:
        """Replaying rec-2923's shape (no echo, scope marking steps 16/17 unretrieved) trips
        check-5: tags cross_check_check_5 in warn mode, raises in strict mode."""
        sha, _ = _make_bundle(tmp_path, scope=_REC_2923_SCOPE)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)
        assert ctx["warn_mode_reject"]["reasons"] == ["cross_check_check_5"]

        ctx2 = _ctx_v2()
        ctx2["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("CI_RCA_STRICT_MODE: strict\n", encoding="utf-8")
        with (
            patch.object(_ci_rca_schema_mod, "ROOT", tmp_path),
            patch("scripts.ops_data_portal._FEATURE_FLAGS_YAML", flags_file),
        ):
            with pytest.raises(ValueError, match="check-5"):
                p._run_ci_rca_cross_check(ctx2)

    def test_exact_match_echo_is_not_stamped(self, tmp_path: Path) -> None:
        """An exact-pair-set echo (order-insensitive) is not stamped, and the echo itself
        survives alongside the stamp untouched."""
        sha, _ = _make_bundle(tmp_path, scope=_REC_2923_SCOPE)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        echo = [
            {"job_id": 30615075007, "step_index": 17},
            {"job_id": 30615075007, "step_index": 16},
        ]
        ctx["unobserved_steps"] = list(echo)

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)

        assert ctx.get("warn_mode_reject") is None
        assert ctx["unobserved_steps"] == echo

    @pytest.mark.parametrize(
        "echo",
        [
            pytest.param([{"job_id": 30615075007, "step_index": 16}], id="subset"),
            pytest.param(
                [
                    {"job_id": 30615075007, "step_index": 16},
                    {"job_id": 30615075007, "step_index": 17},
                    {"job_id": 30615075007, "step_index": 15},
                ],
                id="superset",
            ),
            pytest.param([{"job_id": 30615075007, "step_index": 3}], id="wrong-set"),
            pytest.param([16, 17], id="flat-index"),
        ],
    )
    def test_mismatched_echo_shapes_are_stamped(self, tmp_path: Path, echo: Any) -> None:
        sha, _ = _make_bundle(tmp_path, scope=_REC_2923_SCOPE)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        ctx["unobserved_steps"] = echo

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)

        assert ctx["warn_mode_reject"]["reasons"] == ["cross_check_check_5"]

    def test_malformed_scope_entries_are_skipped_not_crashed(self, tmp_path: Path) -> None:
        """A malformed scope entry (not a dict, or missing a valid job_id) is silently skipped
        by _unobserved_pairs_from_scope rather than crashing the cross-check spine; well-formed
        sibling entries still contribute their pairs."""
        scope = [
            "not-a-dict",
            {"steps": [{"step_index": 1, "conclusion": "success", "log_retrieved": False}]},  # missing job_id
            {
                "job_id": 1,
                "steps": [{"step_index": 4, "conclusion": "skipped", "log_retrieved": False}],
            },
        ]
        sha, _ = _make_bundle(tmp_path, scope=scope)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)

        assert ctx["unobserved_steps_authoritative"] == [{"job_id": 1, "step_index": 4}]

    def test_bundle_with_no_scope_degrades_silently(self, tmp_path: Path) -> None:
        """A bundle carrying no retrieval_evidence.scope (pre-dating this plan) skips the stamp
        and check-5 entirely -- even a would-be-mismatched echo raises no issue."""
        sha, _ = _make_bundle(tmp_path, scope=None)
        ctx = _ctx_v2()
        ctx["evidence_bundle_ref"] = {"sha256": sha, "s3_uri": "", "upload_status": "ok"}
        ctx["unobserved_steps"] = [{"job_id": 1, "step_index": 1}]

        with patch.object(_ci_rca_schema_mod, "ROOT", tmp_path):
            p._run_ci_rca_cross_check(ctx)  # must not raise

        assert "unobserved_steps_authoritative" not in ctx
        assert ctx.get("warn_mode_reject") is None
