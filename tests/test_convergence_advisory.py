"""Tests for scripts/ci/convergence_advisory.py (Decision 172 PR-2).

Asserts the six-way partition VP step 5 requires: NoSuchKey (pass-on-absent), credential/
authorization failure, red record, pending_gated, green, and empty-body/unparseable JSON --
the exact conflation the pre-extraction inline body in terraform-apply-sandbox.yml's
advisory-status job exhibited (a credential failure and a genuinely absent record both folded
into pass-on-absent green; an unparseable record aborted under inherited errexit).
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from scripts.ci.convergence_advisory import ERROR, FAILURE, SUCCESS, classify, main


class TestNoSuchKeyPassOnAbsent:
    def test_nosuchkey_is_success_pass_on_absent(self) -> None:
        state, desc = classify(1, "An error occurred (NoSuchKey) when calling ...", "")
        assert state == SUCCESS
        assert "pass-on-absent" in desc

    def test_404_variant_is_also_pass_on_absent(self) -> None:
        state, desc = classify(1, "fatal error: 404 Not Found", "")
        assert state == SUCCESS
        assert "pass-on-absent" in desc


class TestCredentialFailure:
    def test_non_nosuchkey_read_error_is_error_unverified(self) -> None:
        state, desc = classify(1, "An error occurred (AccessDenied) when calling GetObject", "")
        assert state == ERROR
        assert "UNVERIFIED" in desc

    def test_credential_failure_is_never_success(self) -> None:
        """The exact defect this extraction closes: a credential failure must never fold into
        the same pass-on-absent green outcome as a genuinely absent record."""
        state, _ = classify(1, "Unable to locate credentials", "")
        assert state != SUCCESS


class TestEmptyOrUnparseable:
    def test_empty_body_is_error_not_pass_on_absent_green(self) -> None:
        state, desc = classify(0, "", "")
        assert state == ERROR
        assert "UNVERIFIED" in desc

    def test_whitespace_only_body_is_error(self) -> None:
        state, _ = classify(0, "", "   \n  ")
        assert state == ERROR

    def test_unparseable_json_is_error_never_an_abort(self) -> None:
        state, desc = classify(0, "", "{not valid json")
        assert state == ERROR
        assert "UNVERIFIED" in desc

    def test_non_object_json_is_error(self) -> None:
        state, _ = classify(0, "", "[1, 2, 3]")
        assert state == ERROR


class TestRedRecord:
    def test_red_status_is_failure(self) -> None:
        body = json.dumps({"status": "red", "commit_sha": "abc123"})
        state, desc = classify(0, "", body)
        assert state == FAILURE
        assert "abc123" in desc
        assert "non-converged" in desc


class TestPendingGated:
    def test_pending_gated_marker_is_success_with_routed_pending_description(self) -> None:
        body = json.dumps({"status": "green", "pending_gated": {"commit_sha": "def456"}})
        state, desc = classify(0, "", body)
        assert state == SUCCESS
        assert "def456" in desc
        assert "pending-gated" in desc

    def test_pending_gated_is_distinguishable_from_plain_green(self) -> None:
        plain_state, plain_desc = classify(0, "", json.dumps({"status": "green"}))
        pending_body = json.dumps({"status": "green", "pending_gated": {"commit_sha": "x"}})
        pending_state, pending_desc = classify(0, "", pending_body)
        assert plain_state == pending_state == SUCCESS
        assert plain_desc != pending_desc


class TestGreen:
    def test_converged_green_is_success(self) -> None:
        state, desc = classify(0, "", json.dumps({"status": "green"}))
        assert state == SUCCESS
        assert "converged" in desc

    def test_missing_status_key_defaults_to_green_shaped_success(self) -> None:
        state, _ = classify(0, "", json.dumps({"commit_sha": "abc"}))
        assert state == SUCCESS


class TestMainNeverRaises:
    def test_main_prints_state_and_description_lines(self, capsys) -> None:
        env = {"RC": "0", "S3_STDERR": "", "REC_JSON": json.dumps({"status": "green"})}
        with patch.dict(os.environ, env, clear=False):
            rc = main([])
        assert rc == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == SUCCESS
        assert "converged" in out[1]

    def test_main_never_raises_on_malformed_env(self, capsys) -> None:
        env = {"RC": "not-an-int", "S3_STDERR": "", "REC_JSON": "{also not json"}
        with patch.dict(os.environ, env, clear=False):
            rc = main([])
        assert rc == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] in (SUCCESS, ERROR)

    def test_main_survives_an_unexpected_internal_exception(self, capsys) -> None:
        """A defensive check: even if classify() itself somehow raised, main() must still print
        a state/description pair and exit 0 rather than crash the advisory-status job."""
        with patch("scripts.ci.convergence_advisory.classify", side_effect=RuntimeError("boom")):
            rc = main([])
        assert rc == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == ERROR
        assert "UNVERIFIED" in out[1]
