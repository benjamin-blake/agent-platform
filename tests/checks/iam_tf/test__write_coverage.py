"""Tests for the DISCOVERY-DRIVEN write-coverage submodule (design (a), PLAN-iam-write-surface-completion).

Mirror of scripts/checks/iam_tf/_write_coverage.py. Covers the WRITE_COVERAGE map, WRITE_EXEMPT_TYPES,
_write_grant_present, and check_write_coverage's two loud-fail directions -- including the one that
used to be DEAD CODE: a discovered terraform/personal resource type that is neither
WRITE_COVERAGE-mapped nor exempt. The pre-fix version of that branch was
`rtype in APPLY_WRITTEN_TYPES and rtype not in WRITE_COVERAGE` with
`APPLY_WRITTEN_TYPES = frozenset(WRITE_COVERAGE)` -- unsatisfiable by construction, and reachable in
tests only by monkeypatching the frozenset. That monkeypatch test is deliberately GONE: it asserted
against a branch the production path could never reach, which is the opposite of a regression test.

The lifecycle-companion tests moved to test__write_companions.py and the symmetry tests live in
test__write_symmetry.py (Decision 128 decomposition -- no test module imports another).
"""

from __future__ import annotations

from scripts.checks import _common
from scripts.checks.iam_tf._read_coverage import (
    _BOOTSTRAP_DIR_REL,
    _PERSONAL_DIR_REL,
    _parse_bootstrap_statements,
    _parse_managed_policy_statements,
    _read_root_text,
    _scan_resources,
)
from scripts.checks.iam_tf._write_coverage import (
    _INSTANCE_PROFILE_PREFIX,
    _ROLE_PREFIX,
    WRITE_COVERAGE,
    WRITE_EXEMPT_TYPES,
    _write_exemption,
    _write_grant_present,
    check_write_coverage,
)


def _stmt(actions: list[str], resources_raw: str, effect: str = "Allow") -> dict:
    return {"sid": None, "actions": actions, "resources_raw": resources_raw, "effect": effect}


def _covered_statements() -> list[dict]:
    """A synthetic policy that write-covers the four types the fixtures below declare."""
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
    ]


_COVERED_RESOURCES = [
    ("aws_lambda_function", "fn", "prod.tf"),
    ("aws_cloudwatch_log_group", "lg", "prod.tf"),
    ("aws_cloudwatch_metric_alarm", "alarm", "prod.tf"),
    ("aws_cloudwatch_event_rule", "rule", "prod.tf"),
]


def _real_apply_statements() -> list[dict]:
    """The REAL apply grant surface: the inline identity policy UNION the managed reads policy."""
    text = _read_root_text(_common.ROOT / _BOOTSTRAP_DIR_REL)
    inline = _parse_bootstrap_statements(text, "github_ci_apply")
    assert inline, "could not parse the real github_ci_apply policy -- has the HCL shape changed?"
    return inline + _parse_managed_policy_statements(text, "github_ci_apply_reads")


class TestWriteCoverageMap:
    def test_every_entry_has_actions_and_marker(self) -> None:
        for rtype, spec in WRITE_COVERAGE.items():
            assert spec["write_actions"], rtype
            assert spec["resource_marker"], rtype

    def test_no_type_is_both_mapped_and_exempt(self) -> None:
        # An exemption says "this type needs no write grant"; a mapping says "here is its write
        # grant". A type in both would make the discovery loop's verdict order-dependent.
        assert set(WRITE_COVERAGE) & set(WRITE_EXEMPT_TYPES) == set()

    def test_every_exemption_carries_a_justification(self) -> None:
        for rtype, why in WRITE_EXEMPT_TYPES.items():
            assert why.strip(), rtype

    def test_sns_subscription_requires_only_the_topic_scopable_verb(self) -> None:
        """sns:Unsubscribe / sns:SetSubscriptionAttributes have NO resource type in SNS's IAM model,
        so they are unscopeable and DENIED BY DESIGN rather than granted account-wide. Requiring them
        here would force a Resource "*" grant back into SNSTopicWrite -- the exact widening the
        denial exists to prevent."""
        spec = WRITE_COVERAGE["aws_sns_topic_subscription"]
        assert spec["write_actions"] == ("sns:Subscribe",)
        assert spec["resource_marker"] == "agent-platform-alerts"

    def test_instance_profile_marker_is_not_the_role_prefix(self) -> None:
        """The marker whose absence made a grant inert: iam:RemoveRoleFromInstanceProfile authorizes
        on the instance-profile resource type, so its marker must never collapse into the role one."""
        assert _INSTANCE_PROFILE_PREFIX == "instance-profile/agent-platform-*"
        assert _INSTANCE_PROFILE_PREFIX != _ROLE_PREFIX

    def test_data_sources_are_exempt_by_prefix(self) -> None:
        # A terraform data source is refreshed, never written -- its obligation is read coverage.
        assert _write_exemption("data:aws_secretsmanager_secret_version") is not None
        assert _write_exemption("data:aws_some_future_source") is not None
        assert _write_exemption("aws_lambda_function") is None


class TestWriteGrantPresent:
    def test_present_when_all_actions_on_marker(self) -> None:
        assert _write_grant_present(_covered_statements(), WRITE_COVERAGE["aws_lambda_function"]) is True

    def test_absent_when_action_missing(self) -> None:
        # Only CreateFunction granted; UpdateFunctionConfiguration missing -> not covered.
        stmts = [_stmt(["lambda:CreateFunction"], '["...function:agent-platform-*"]')]
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_lambda_function"]) is False

    def test_absent_when_marker_missing(self) -> None:
        # Right action, a Resource with no "alarm:" token -> not covered.
        stmts = [_stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:sns:...:agent-platform-alerts"]')]
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_cloudwatch_metric_alarm"]) is False


class TestCheckWriteCoverage:
    def test_fully_covered_no_findings(self) -> None:
        failed: list[str] = []
        n = check_write_coverage(_covered_statements(), _COVERED_RESOURCES, failed, "k:")
        assert failed == []
        assert n == len(_COVERED_RESOURCES)

    def test_missing_write_grant_fails_loud(self) -> None:
        stmts = [s for s in _covered_statements() if "lambda:CreateFunction" not in s["actions"]]
        failed: list[str] = []
        check_write_coverage(stmts, _COVERED_RESOURCES, failed, "k:")
        assert any("aws_lambda_function" in f and "no covering write grant" in f for f in failed)
        assert all(f.startswith("k:") for f in failed)

    def test_discovered_unmapped_type_fails_loud(self) -> None:
        """THE branch that was dead code before design (a): a real terraform/personal resource of a
        type with no WRITE_COVERAGE entry and no exemption. No monkeypatching -- the production path
        reaches this directly from the resource sweep."""
        resources = [*_COVERED_RESOURCES, ("aws_sfn_state_machine", "pipeline", "prod.tf")]
        failed: list[str] = []
        check_write_coverage(_covered_statements(), resources, failed, "k:")
        assert len(failed) == 1, failed
        assert "aws_sfn_state_machine" in failed[0]
        assert "pipeline in prod.tf" in failed[0]
        assert "neither WRITE_COVERAGE-mapped nor WRITE_EXEMPT_TYPES-exempt" in failed[0]
        assert failed[0].startswith("k:")

    def test_discovered_exempt_types_pass(self) -> None:
        """The other half of the discovery loop: a justified exemption is not a finding."""
        resources = [
            *_COVERED_RESOURCES,
            ("neon_project", "catalog", "neon.tf"),
            ("null_resource", "bootstrap", "neon.tf"),
            ("data:aws_secretsmanager_secret_version", "neon_api_key", "neon.tf"),
        ]
        failed: list[str] = []
        n = check_write_coverage(_covered_statements(), resources, failed, "k:")
        assert failed == []
        assert n == len(_COVERED_RESOURCES)

    def test_mapped_type_absent_from_the_tree_is_not_asserted(self) -> None:
        """Discovery-gating, mirroring the read side: a WRITE_COVERAGE type with no resource left in
        terraform/personal imposes no grant obligation, and re-arms the moment one reappears."""
        failed: list[str] = []
        n = check_write_coverage(_covered_statements(), [], failed, "k:")
        assert failed == []
        assert n == 0

        failed_again: list[str] = []
        check_write_coverage(_covered_statements(), [("aws_sns_topic", "alerts", "prod.tf")], failed_again, "k:")
        assert any("aws_sns_topic" in f and "no covering write grant" in f for f in failed_again)


class TestRealTree:
    """The live tree: every discovered type is classified, and every mapped type's grant is present."""

    def test_real_tree_write_coverage_passes(self) -> None:
        resources, _, _ = _scan_resources(_common.ROOT / _PERSONAL_DIR_REL)
        failed: list[str] = []
        n = check_write_coverage(_real_apply_statements(), resources, failed, "k:")
        assert failed == []
        # Design (a) is live: the pre-fix table hand-listed 5 types against 31 discovered ones.
        assert n > 5, n

    def test_real_tree_has_no_unclassified_type(self) -> None:
        resources, _, _ = _scan_resources(_common.ROOT / _PERSONAL_DIR_REL)
        discovered = {rtype for rtype, _, _ in resources}
        unclassified = {r for r in discovered if r not in WRITE_COVERAGE and _write_exemption(r) is None}
        assert unclassified == set()
