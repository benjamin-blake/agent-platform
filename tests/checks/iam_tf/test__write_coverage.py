"""Tests for the write-coverage submodule (Decision 128 decomposition + Decision 144 c5, DEP-01).

Mirror of scripts/checks/iam_tf/_write_coverage.py. Covers the WRITE_COVERAGE map, _write_grant_present,
and check_write_coverage's two loud-fail directions (missing write grant; apply-written type with no
WRITE_COVERAGE entry)."""

from __future__ import annotations

from scripts.checks.iam_tf._write_coverage import (
    APPLY_WRITTEN_TYPES,
    WRITE_COVERAGE,
    _write_grant_present,
    check_write_coverage,
)


def _stmt(actions: list[str], resources_raw: str) -> dict:
    return {"sid": None, "actions": actions, "resources_raw": resources_raw}


def _fully_covered_apply_statements() -> list[dict]:
    """A synthetic apply policy that write-covers every WRITE_COVERAGE type."""
    return [
        _stmt(
            ["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"],
            '["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"]',
        ),
        _stmt(
            ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
            '["arn:aws:logs:eu-west-2:1234567890:log-group:/aws/lambda/agent-platform-*"]',
        ),
        _stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:cloudwatch:eu-west-2:1234567890:alarm:agent-platform-*"]'),
        _stmt(["events:PutRule"], '["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-*"]'),
        _stmt(["iam:CreateRole"], '["arn:aws:iam::1234567890:role/agent-platform-*"]'),
    ]


class TestWriteCoverageMap:
    def test_apply_written_types_all_mapped(self) -> None:
        # Every declared apply-written type has a WRITE_COVERAGE entry (structural invariant).
        assert APPLY_WRITTEN_TYPES <= set(WRITE_COVERAGE)

    def test_every_entry_has_actions_and_marker(self) -> None:
        for rtype, spec in WRITE_COVERAGE.items():
            assert spec["write_actions"], rtype
            assert spec["resource_marker"], rtype


class TestWriteGrantPresent:
    def test_present_when_all_actions_on_marker(self) -> None:
        stmts = _fully_covered_apply_statements()
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_lambda_function"]) is True

    def test_absent_when_action_missing(self) -> None:
        # Only CreateFunction granted; UpdateFunctionConfiguration missing -> not covered.
        stmts = [_stmt(["lambda:CreateFunction"], '["...function:agent-platform-*"]')]
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_lambda_function"]) is False

    def test_absent_when_marker_missing(self) -> None:
        # Right actions, wrong resource (no marker) -> not covered.
        stmts = [_stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:cloudwatch:...:alarm:something-else-*"]')]
        # marker "alarm:" IS a substring of the resource, so this one is covered -- use a resource
        # with no "alarm:" token to prove the negative branch.
        stmts_no_marker = [_stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:sns:...:agent-platform-alerts"]')]
        assert _write_grant_present(stmts_no_marker, WRITE_COVERAGE["aws_cloudwatch_metric_alarm"]) is False
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_cloudwatch_metric_alarm"]) is True


class TestCheckWriteCoverage:
    def test_fully_covered_no_findings(self) -> None:
        failed: list[str] = []
        n = check_write_coverage(_fully_covered_apply_statements(), [], failed, "k:")
        assert failed == []
        assert n == len(WRITE_COVERAGE)

    def test_missing_write_grant_fails_loud(self) -> None:
        # Drop the lambda grant -> aws_lambda_function is not write-covered.
        stmts = [s for s in _fully_covered_apply_statements() if "lambda:CreateFunction" not in s["actions"]]
        failed: list[str] = []
        check_write_coverage(stmts, [], failed, "k:")
        assert any("aws_lambda_function" in f and "no covering write grant" in f for f in failed)
        assert all(f.startswith("k:") for f in failed)

    def test_unmapped_apply_written_type_fails_loud(self, monkeypatch) -> None:
        # Simulate a new apply-written type declared without a WRITE_COVERAGE entry.
        import scripts.checks.iam_tf._write_coverage as wc

        monkeypatch.setattr(wc, "APPLY_WRITTEN_TYPES", frozenset(WRITE_COVERAGE) | {"aws_sfn_state_machine"})
        resources = [("aws_sfn_state_machine", "pipeline", "prod.tf")]
        failed: list[str] = []
        wc.check_write_coverage(_fully_covered_apply_statements(), resources, failed, "k:")
        assert any("aws_sfn_state_machine" in f and "no\n" not in f and "WRITE_COVERAGE entry" in f for f in failed)
