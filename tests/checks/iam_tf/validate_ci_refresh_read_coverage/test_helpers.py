"""Branch-level tests for the private parse/resolve helpers in
scripts/checks/iam_tf/validate_ci_refresh_read_coverage.py (rec-2702 anti-recurrence,
PLAN-ci-apply-grant-coupling). Concern-split module (rec-2709 Wave 1) -- see
test_end_to_end.py and test_real_tree.py for the other two modules of this package."""

from pathlib import Path

import pytest

from scripts.checks.iam_tf.validate_ci_refresh_read_coverage import (
    _action_matches,
    _extract_bracket_block,
    _extract_capitalized_field,
    _literal_or_prefix_match,
    _parse_bootstrap_statements,
    _resolve_role_statements,
    _resolve_value,
    _resource_covered,
    _scan_resources,
    _split_top_level_objects,
)


class TestValidateCiRefreshReadCoverageHelpers:
    """Branch-level tests for the private helpers in validate_ci_refresh_read_coverage.py
    (rec-2702 anti-recurrence, PLAN-ci-apply-grant-coupling). End-to-end / acceptance-shaped
    tests live in tests/test_validate_ci_refresh_read_coverage.py; this class exists so this
    module's own coverage (measured via this file, per the scripts/checks/** convention) is
    complete."""

    def test_extract_bracket_block_unbalanced_raises(self) -> None:
        with pytest.raises(ValueError, match="Unbalanced brackets"):
            _extract_bracket_block("[a, b", 0)

    def test_split_top_level_objects_empty_on_no_braces(self) -> None:
        assert _split_top_level_objects("no braces here") == []

    def test_extract_capitalized_field_no_match_returns_empty(self) -> None:
        assert _extract_capitalized_field('Sid = "X"', "Action") == ([], "")

    def test_extract_capitalized_field_single_string_form(self) -> None:
        values, raw = _extract_capitalized_field('Resource = "*"', "Resource")
        assert values == ["*"]
        assert raw == '"*"'

    def test_parse_bootstrap_statements_missing_role_block_returns_empty(self) -> None:
        assert _parse_bootstrap_statements("# nothing here", "github_ci_apply") == []

    def test_parse_bootstrap_statements_missing_statement_array_returns_empty(self) -> None:
        text = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "x"
  policy = jsonencode({
    Version = "2012-10-17"
  })
}
"""
        assert _parse_bootstrap_statements(text, "github_ci_apply") == []

    def test_resolve_value_none_input_returns_none(self) -> None:
        assert _resolve_value(None, {}, {}) is None

    def test_resolve_value_depth_guard_returns_none(self) -> None:
        assert _resolve_value('"x"', {}, {}, _depth=7) is None

    def test_resolve_value_literal(self) -> None:
        assert _resolve_value('"agent-platform-known"', {}, {}) == "agent-platform-known"

    def test_resolve_value_local_ref_resolves(self) -> None:
        assert _resolve_value("local.my_name", {"my_name": "agent-platform-x"}, {}) == "agent-platform-x"

    def test_resolve_value_local_ref_undefined_returns_none(self) -> None:
        assert _resolve_value("local.undefined_local", {}, {}) is None

    def test_resolve_value_resource_ref_resolves_transitively(self) -> None:
        attr_index = {("aws_lambda_function", "known_fn"): {"function_name": "local.fn_name"}}
        locals_map = {"fn_name": "agent-platform-known-fn"}
        assert (
            _resolve_value("aws_lambda_function.known_fn.function_name", locals_map, attr_index) == "agent-platform-known-fn"
        )

    def test_resolve_value_resource_ref_missing_attr_returns_none(self) -> None:
        assert _resolve_value("aws_lambda_function.missing_fn.function_name", {}, {}) is None

    def test_resolve_value_unresolvable_format_returns_none(self) -> None:
        assert _resolve_value("some_weird_expression()", {}, {}) is None

    def test_literal_or_prefix_match_skips_bare_wildcard_entry_when_literal_only(self) -> None:
        raw = '"*", "arn:aws:iam::1234567890:role/agent-platform-known-role"'
        assert _literal_or_prefix_match("agent-platform-known-role", raw, literal_only=True) is True

    def test_literal_or_prefix_match_prefix_branch(self) -> None:
        raw = '"arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"'
        assert _literal_or_prefix_match("agent-platform-new-fn", raw) is True

    def test_literal_or_prefix_match_no_match(self) -> None:
        raw = '"arn:aws:lambda:eu-west-2:1234567890:function:other-prefix-*"'
        assert _literal_or_prefix_match("agent-platform-new-fn", raw) is False

    def test_literal_or_prefix_match_enumerated_iam_substring_collision_rejected(self) -> None:
        """H-finding (code-review 2026-07-15): a short enumerated role name that is a substring
        PREFIX of a longer, unrelated enumerated ARN must NOT be reported as covered -- the match
        is `/`/`:`-segment boundary-anchored, not raw substring containment (Decision 35/98/55)."""
        raw = '"arn:aws:iam::1234567890:role/agent-platform-github-ci-prod-deploy"'
        # 'agent-platform-github-ci-pr' is a literal substring of '...-prod-deploy' but NOT a
        # whole ARN segment -- must be rejected under the enumerated-IAM (literal_only) path.
        assert _literal_or_prefix_match("agent-platform-github-ci-pr", raw, literal_only=True) is False
        # ...while the correctly-enumerated exact ARN still matches.
        exact = '"arn:aws:iam::1234567890:role/agent-platform-github-ci-pr"'
        assert _literal_or_prefix_match("agent-platform-github-ci-pr", exact, literal_only=True) is True

    def test_literal_or_prefix_match_secrets_manager_suffix(self) -> None:
        """A Secrets-Manager `<name>-*` ARN (the `*` stands in for SM's random 6-char suffix)
        covers the resource named `<name>` -- the suffix direction, boundary-anchored so a
        shorter unrelated name does not match a longer secret stub."""
        raw = '"arn:aws:secretsmanager:eu-west-2:1234567890:secret:agent-platform-github-pat-*"'
        assert _literal_or_prefix_match("agent-platform-github-pat", raw) is True
        # A shorter unrelated name must NOT match the longer secret stub (strict `<name><sep>` shape).
        assert _literal_or_prefix_match("agent-platform-github", raw) is False

    def test_literal_or_prefix_match_empty_stub_wildcard_skipped(self) -> None:
        """A wildcard entry whose pre-`*` part collapses to nothing after stripping separators
        (e.g. a bare `/*`) yields no stub -- it is skipped, never a spurious prefix match."""
        assert _literal_or_prefix_match("agent-platform-anything", '"/*"') is False

    def test_action_matches_wildcard_pattern_matches_literal_action(self) -> None:
        assert _action_matches(("secretsmanager:Describe*",), ["secretsmanager:DescribeSecret"]) is True

    def test_action_matches_exact_pattern_requires_exact(self) -> None:
        assert _action_matches(("iam:GetRole",), ["iam:GetRolePolicy"]) is False
        assert _action_matches(("iam:GetRole",), ["iam:GetRole"]) is True

    def test_resource_covered_via_terraform_reference(self) -> None:
        statements = [{"actions": ["sns:Get*"], "resources_raw": "aws_sns_topic.alerts.arn"}]
        assert _resource_covered("aws_sns_topic", "alerts", "agent-platform-alerts", ("sns:Get*",), statements) is True

    def test_resource_covered_no_matching_action(self) -> None:
        statements = [{"actions": ["s3:GetObject"], "resources_raw": '"*"'}]
        assert _resource_covered("aws_sns_topic", "alerts", "agent-platform-alerts", ("sns:Get*",), statements) is False

    def test_resolve_role_statements_missing_drift_returns_none(self) -> None:
        oidc_text = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name   = "test-plan"
  role   = "test-plan-role"
  policy = data.aws_iam_policy_document.github_ci_plan.json
}

data "aws_iam_policy_document" "github_ci_plan" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}
"""
        assert _resolve_role_statements(oidc_text) is None

    def test_scan_resources_finds_s3_bucket_and_locals(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True)
        (personal_dir / "main.tf").write_text(
            """
locals {
  bucket_name = "agent-platform-data-lake"
}

resource "aws_s3_bucket" "data_lake" {
  bucket = local.bucket_name
}
""",
            encoding="utf-8",
        )
        resources, locals_map, attr_index = _scan_resources(personal_dir)
        assert ("aws_s3_bucket", "data_lake", "main.tf") in resources
        assert locals_map["bucket_name"] == "agent-platform-data-lake"
        assert attr_index[("aws_s3_bucket", "data_lake")]["bucket"] == "local.bucket_name"

    def test_scan_resources_finds_data_secret_version(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True)
        (personal_dir / "neon.tf").write_text(
            """
data "aws_secretsmanager_secret_version" "neon_api_key" {
  secret_id = "neon-api-key"
}
""",
            encoding="utf-8",
        )
        resources, _locals_map, attr_index = _scan_resources(personal_dir)
        assert ("data:aws_secretsmanager_secret_version", "neon_api_key", "neon.tf") in resources
        assert attr_index[("data:aws_secretsmanager_secret_version", "neon_api_key")]["secret_id"] == '"neon-api-key"'

    def test_resource_covered_wildcard_branch(self) -> None:
        statements = [{"actions": ["logs:Describe*"], "resources_raw": '"*"'}]
        assert _resource_covered("aws_cloudwatch_log_group", "any", None, ("logs:Describe*",), statements) is True

    def test_resolve_resource_name_none_for_wildcard_only_spec(self) -> None:
        """A wildcard-only type (e.g. aws_cloudwatch_log_group) has no name_attrs -- resolution
        short-circuits to None rather than attempting attribute extraction."""
        from scripts.checks.iam_tf.validate_ci_refresh_read_coverage import _resolve_resource_name

        spec = {"read_actions": ("logs:Describe*", "logs:List*"), "name_attrs": None}
        assert _resolve_resource_name("aws_cloudwatch_log_group", "any", spec, {}, {}) is None

    def test_resource_covered_literal_name_match(self) -> None:
        statements = [
            {
                "actions": ["lambda:Get*"],
                "resources_raw": '"arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"',
            }
        ]
        assert (
            _resource_covered("aws_lambda_function", "known_fn", "agent-platform-known-fn", ("lambda:Get*",), statements)
            is True
        )
