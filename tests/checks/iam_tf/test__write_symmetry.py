"""Tests for the two mechanical symmetry rules (design (c)).

Mirror of scripts/checks/iam_tf/_write_symmetry.py. Both rules get a POSITIVE and a NEGATIVE case,
because a symmetry rule that cannot fail is worse than no rule (it manufactures false confidence):

  rule 1  a Tag* with no matching Untag* at an overlapping Resource FAILS; the ssm alias pair
          (AddTagsToResource / RemoveTagsFromResource) resolves rather than false-positiving.
  rule 2  a read marker narrower than the widest write marker FAILS; a NAMED exemption suppresses
          exactly one type and nothing else; the transitive-skip set IS
          _read_coverage.TRANSITIVE_TYPES by IDENTITY, not a copy -- the hand-copied variant is the
          exact root cause this plan exists to remove.

Self-contained (no cross-test imports): every fixture below is this module's own.
"""

from __future__ import annotations

import pytest

from scripts.checks import _common
from scripts.checks.iam_tf import _write_symmetry as symmetry
from scripts.checks.iam_tf._read_coverage import (
    _BOOTSTRAP_DIR_REL,
    TRANSITIVE_TYPES,
    _parse_bootstrap_statements,
    _parse_managed_policy_statements,
    _read_root_text,
)
from scripts.checks.iam_tf._write_symmetry import (
    ALIAS_TAG_PAIRS,
    READ_SCOPE_PARITY_EXEMPT,
    TAG_SYMMETRY_EXEMPT,
    TRANSITIVE_SKIP_TYPES,
    _arn_covers,
    _untag_counterpart,
    check_read_write_scope_parity,
    check_tag_untag_symmetry,
)

_FN_PREFIX = "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"
_FN_LITERAL = "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"
_PARAM_PREFIX = "arn:aws:ssm:eu-west-2:1234567890:parameter/agent-platform/*"


def _stmt(actions: list[str], resources: list[str], effect: str = "Allow") -> dict:
    raw = ", ".join(f'"{r}"' for r in resources)
    return {"sid": None, "actions": actions, "resources_raw": f"[{raw}]", "effect": effect}


def _real_apply_statements() -> list[dict]:
    text = _read_root_text(_common.ROOT / _BOOTSTRAP_DIR_REL)
    inline = _parse_bootstrap_statements(text, "github_ci_apply")
    assert inline, "could not parse the real github_ci_apply policy -- has the HCL shape changed?"
    return inline + _parse_managed_policy_statements(text, "github_ci_apply_reads")


class TestUntagCounterpart:
    def test_regular_pair(self) -> None:
        assert _untag_counterpart("logs:TagLogGroup") == "logs:UntagLogGroup"
        assert _untag_counterpart("iam:TagOpenIDConnectProvider") == "iam:UntagOpenIDConnectProvider"

    def test_alias_pair(self) -> None:
        assert _untag_counterpart("ssm:AddTagsToResource") == "ssm:RemoveTagsFromResource"

    def test_non_tag_actions_return_none(self) -> None:
        for action in ("glue:GetTags", "dynamodb:ListTagsOfResource", "s3:PutBucketTagging", "iam:UntagRole"):
            assert _untag_counterpart(action) is None, action

    def test_alias_table_is_a_spelling_map_not_a_suppression_list(self) -> None:
        for tag_action, untag_action in ALIAS_TAG_PAIRS.items():
            assert tag_action.split(":")[0] == untag_action.split(":")[0]


class TestTagUntagSymmetry:
    def test_matched_pair_passes(self) -> None:
        stmts = [_stmt(["logs:TagLogGroup", "logs:UntagLogGroup"], ["arn:aws:logs:::log-group:/aws/lambda/x-*"])]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert failed == []

    def test_tag_without_untag_fails_loud(self) -> None:
        """The pre-fix tree's exact shape: logs:TagLogGroup granted, logs:UntagLogGroup absent."""
        stmts = [_stmt(["logs:CreateLogGroup", "logs:TagLogGroup"], ["arn:aws:logs:::log-group:/aws/lambda/x-*"])]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "'logs:TagLogGroup'" in failed[0] and "'logs:UntagLogGroup'" in failed[0]
        assert failed[0].startswith("k:")

    def test_untag_at_a_disjoint_resource_fails_loud(self) -> None:
        """Presence is not enough: the counterpart must overlap the tag grant's Resource scope."""
        stmts = [
            _stmt(["iam:TagRole"], ["arn:aws:iam::1234567890:role/agent-platform-*"]),
            _stmt(["iam:UntagRole"], ["arn:aws:iam::1234567890:role/some-other-role"]),
        ]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "'iam:TagRole'" in failed[0]

    def test_alias_pair_resolves_without_false_positive(self) -> None:
        stmts = [_stmt(["ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"], [_PARAM_PREFIX])]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert failed == []

    def test_alias_tag_without_its_removal_counterpart_fails_loud(self) -> None:
        stmts = [_stmt(["ssm:PutParameter", "ssm:AddTagsToResource"], [_PARAM_PREFIX])]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "'ssm:RemoveTagsFromResource'" in failed[0]

    def test_deny_statement_tag_action_is_not_asserted(self) -> None:
        stmts = [_stmt(["logs:TagLogGroup"], ["arn:aws:logs:::log-group:/x"], effect="Deny")]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert failed == []

    def test_named_exemption_suppresses_exactly_that_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(symmetry, "TAG_SYMMETRY_EXEMPT", {"logs:TagLogGroup": "why this one is one-way"})
        stmts = [
            _stmt(["logs:TagLogGroup"], ["arn:aws:logs:::log-group:/x-*"]),
            _stmt(["events:TagResource"], ["arn:aws:events:::rule/x-*"]),
        ]
        failed: list[str] = []
        check_tag_untag_symmetry(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "'events:TagResource'" in failed[0]

    def test_every_declared_exemption_carries_a_justification(self) -> None:
        for action, why in TAG_SYMMETRY_EXEMPT.items():
            assert why.strip(), action


class TestArnCovers:
    def test_wildcard_read_covers_everything(self) -> None:
        assert _arn_covers("*", "arn:aws:s3:::anything") is True

    def test_prefix_read_covers_narrower_write(self) -> None:
        assert _arn_covers(
            "arn:aws:secretsmanager:::secret:agent-platform-*", "arn:aws:secretsmanager:::secret:agent-platform-x-*"
        )

    def test_narrower_read_does_not_cover_wider_write(self) -> None:
        assert _arn_covers(_FN_LITERAL, _FN_PREFIX) is False

    def test_exact_match_covers(self) -> None:
        assert _arn_covers(_FN_LITERAL, _FN_LITERAL) is True


class TestReadWriteScopeParity:
    def _covering_statements(self) -> list[dict]:
        return [
            _stmt(["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"], [_FN_PREFIX]),
            _stmt(["lambda:Get*", "lambda:List*"], [_FN_PREFIX]),
        ]

    def _narrow_read_statements(self) -> list[dict]:
        return [
            _stmt(["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"], [_FN_PREFIX]),
            _stmt(["lambda:Get*", "lambda:List*"], [_FN_LITERAL]),
        ]

    def _only(self, failed: list[str], rtype: str) -> list[str]:
        return [f for f in failed if f"{rtype!r}" in f]

    def test_read_at_least_as_wide_as_write_passes(self) -> None:
        failed: list[str] = []
        check_read_write_scope_parity(self._covering_statements(), failed, "k:")
        assert self._only(failed, "aws_lambda_function") == []

    def test_read_narrower_than_widest_write_marker_fails_loud(self) -> None:
        failed: list[str] = []
        check_read_write_scope_parity(self._narrow_read_statements(), failed, "k:")
        findings = self._only(failed, "aws_lambda_function")
        assert len(findings) == 1, failed
        assert "no read grant covers that scope" in findings[0]
        assert findings[0].startswith("k:")

    def test_named_exemption_suppresses_exactly_one_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The exemption must be surgical: exempting aws_lambda_function must not also suppress a
        different type's parity violation."""
        stmts = [
            *self._narrow_read_statements(),
            _stmt(["events:PutRule"], ["arn:aws:events:::rule/agent-platform-*"]),
            _stmt(["events:Describe*", "events:List*"], ["arn:aws:events:::rule/agent-platform-known-rule"]),
        ]
        baseline: list[str] = []
        check_read_write_scope_parity(stmts, baseline, "k:")
        assert self._only(baseline, "aws_lambda_function")
        assert self._only(baseline, "aws_cloudwatch_event_rule")

        monkeypatch.setattr(symmetry, "READ_SCOPE_PARITY_EXEMPT", {"aws_lambda_function": "named, justified exception"})
        exempted: list[str] = []
        check_read_write_scope_parity(stmts, exempted, "k:")
        assert self._only(exempted, "aws_lambda_function") == []
        assert self._only(exempted, "aws_cloudwatch_event_rule")

    def test_unclassifiable_type_fails_loud_rather_than_skipping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            symmetry,
            "WRITE_COVERAGE",
            {"aws_thing": {"write_actions": ("svc:CreateThing",), "resource_marker": "thing/x"}},
        )
        failed: list[str] = []
        check_read_write_scope_parity([_stmt(["svc:CreateThing"], ["thing/x"])], failed, "k:")
        assert len(failed) == 1, failed
        assert "no read classification" in failed[0]
        assert "silently vacuous" in failed[0]

    def test_transitive_skip_set_is_the_read_coverage_set_by_identity(self) -> None:
        """H1: a hand-copied skip set is the exact root cause this plan removes -- the plan's own
        first draft hand-listed 10 of the 11 members, omitting aws_secretsmanager_secret_version."""
        assert TRANSITIVE_SKIP_TYPES is TRANSITIVE_TYPES
        assert TRANSITIVE_SKIP_TYPES is symmetry.TRANSITIVE_SKIP_TYPES

    def test_transitive_types_are_skipped_not_asserted(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A transitive type has no read markers of its own, so it is skipped -- LOUDLY, with a
        printed line per type, never silently."""
        stmts = [_stmt(["lambda:AddPermission", "lambda:RemovePermission"], [_FN_PREFIX])]
        failed: list[str] = []
        check_read_write_scope_parity(stmts, failed, "k:")
        assert self._only(failed, "aws_lambda_permission") == []
        out = capsys.readouterr().out
        assert "parity SKIPPED aws_lambda_permission" in out

    def test_iam_role_is_the_named_parity_exemption_citing_its_decisions(self) -> None:
        why = READ_SCOPE_PARITY_EXEMPT["aws_iam_role"]
        assert "Decision 129 pt 2" in why
        assert "pt 4(iii)" in why
        assert "Decision 144 pt 5" in why

    def test_iam_role_is_the_SOLE_parity_exemption(self) -> None:
        """aws_secretsmanager_secret was the obvious candidate for a second entry and deliberately
        did NOT become one: the Secrets Manager READ split (value-free metadata prefixed to
        secret:agent-platform-*, GetSecretValue enumerated) makes that type pass rule 2 HONESTLY.
        An exemption would have recorded the gap instead of closing it, so this set stays at one --
        a new entry must be a reviewed decision, never an AccessDenied remediation side effect."""
        assert set(READ_SCOPE_PARITY_EXEMPT) == {"aws_iam_role"}

    def test_secrets_manager_parity_fails_loud_without_the_metadata_read_prefix(self) -> None:
        """NEGATIVE half of the real-tree case below: writes at secret:agent-platform-* with reads
        only at enumerated ARNs is exactly the pre-fix tree, and it must fail loudly."""
        base = "arn:aws:secretsmanager:eu-west-2:1234567890:secret:"
        secret_prefix = f"{base}agent-platform-*"
        enumerated = f"{base}agent-platform-github-pat-*"  # pragma: allowlist secret -- ARN shape
        stmts = [
            _stmt(["secretsmanager:CreateSecret", "secretsmanager:DeleteSecret"], [secret_prefix]),
            _stmt(["secretsmanager:Describe*", "secretsmanager:GetResourcePolicy"], [enumerated]),
        ]
        failed: list[str] = []
        check_read_write_scope_parity(stmts, failed, "k:")
        findings = self._only(failed, "aws_secretsmanager_secret")
        assert len(findings) == 1, failed
        assert "no read grant covers that scope" in findings[0]
        assert findings[0].startswith("k:")


class TestFacadeWiring:
    """Anti-dead-code regression: both rules must be reached from the REGISTERED check."""

    def test_registered_check_calls_both_symmetry_rules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.checks.iam_tf import validate_ci_refresh_read_coverage as facade

        called: list[str] = []
        monkeypatch.setattr(facade, "check_tag_untag_symmetry", lambda s, f, k: called.append("rule1"))
        monkeypatch.setattr(facade, "check_read_write_scope_parity", lambda s, f, k: called.append("rule2"))
        facade.validate_ci_refresh_read_coverage([])
        assert called == ["rule1", "rule2"]


class TestRealTree:
    def test_real_tree_passes_tag_untag_symmetry(self) -> None:
        failed: list[str] = []
        check_tag_untag_symmetry(_real_apply_statements(), failed, "k:")
        assert failed == []

    def test_real_tree_passes_read_write_scope_parity(self) -> None:
        """POSITIVE half: the live github_ci_apply grant surface satisfies rule 2 for every
        write-managed type -- including aws_secretsmanager_secret, which the Secrets Manager read
        split fixed honestly rather than by exemption."""
        failed: list[str] = []
        check_read_write_scope_parity(_real_apply_statements(), failed, "k:")
        assert failed == []

    def test_real_tree_secrets_read_prefix_covers_the_metadata_write_prefix(self) -> None:
        """The specific parity finding this change closes: the secret:agent-platform-* write scope
        is now covered by a read grant at the SAME prefix, so a newly created secret is
        refresh-readable on the NEXT plan instead of AccessDenying."""
        failed: list[str] = []
        check_read_write_scope_parity(_real_apply_statements(), failed, "k:")
        assert [f for f in failed if "aws_secretsmanager_secret" in f] == []
