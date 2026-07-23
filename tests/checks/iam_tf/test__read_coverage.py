"""Tests for the read-coverage submodule (Decision 128 decomposition of validate_ci_refresh_read_coverage).

Mirror of scripts/checks/iam_tf/_read_coverage.py. Relocated from the pre-decomposition package's
test_helpers.py (the helpers moved into _read_coverage), importing the helpers directly from the
submodule, plus direct tests for _classify / _resolve_resource_name / _check_resource so the extracted
module is independently covered."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks.iam_tf._read_coverage import (
    CHECKED_TYPES,
    _action_matches,
    _check_resource,
    _classify,
    _extract_bracket_block,
    _extract_capitalized_field,
    _literal_or_prefix_match,
    _parse_bootstrap_statements,
    _resolve_resource_name,
    _resolve_role_statements,
    _resolve_value,
    _resource_covered,
    _scan_resources,
    _split_top_level_objects,
)


class TestReadCoverageHelpers:
    """Branch-level tests for the private parse/resolve/match helpers in _read_coverage.py."""

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

    def test_parse_bootstrap_statements_parses_statements(self) -> None:
        text = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "x"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
      }
    ]
  })
}
"""
        stmts = _parse_bootstrap_statements(text, "github_ci_apply")
        assert len(stmts) == 1
        assert stmts[0]["sid"] == "LambdaRead"
        assert stmts[0]["actions"] == ["lambda:Get*"]

    def test_parse_bootstrap_statements_resolves_hoisted_local(self) -> None:
        """rec-2793 hoist pattern (github_ci_apply.tf): `policy = local.X` referencing a
        `locals { X = jsonencode({ Statement = [...] }) }` block elsewhere in the file (the
        lifecycle-precondition-cannot-reference-self workaround)."""
        text = """
locals {
  github_ci_apply_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = local.github_ci_apply_policy_json
}
"""
        stmts = _parse_bootstrap_statements(text, "github_ci_apply")
        assert len(stmts) == 1
        assert stmts[0]["sid"] == "LambdaRead"
        assert stmts[0]["actions"] == ["lambda:Get*"]

    def test_parse_bootstrap_statements_hoisted_local_undefined_returns_empty(self) -> None:
        """The `policy = local.X` reference exists but no `X = jsonencode({...})` assignment is
        found anywhere in the file -- fails closed (empty), not an exception."""
        text = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = local.nonexistent_policy_json
}
"""
        assert _parse_bootstrap_statements(text, "github_ci_apply") == []

    def test_parse_bootstrap_statements_hoisted_local_missing_statement_returns_empty(self) -> None:
        """The referenced local exists but its jsonencode(...) body has no Statement key."""
        text = """
locals {
  github_ci_apply_policy_json = jsonencode({
    Version = "2012-10-17"
  })
}

resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = local.github_ci_apply_policy_json
}
"""
        assert _parse_bootstrap_statements(text, "github_ci_apply") == []

    def test_parse_bootstrap_statements_neither_inline_nor_local_returns_empty(self) -> None:
        """Neither an inline Statement array nor a `policy = local.X` indirection -- e.g. a
        `policy = data.aws_iam_policy_document.x.json` reference (not this parser's shape)."""
        text = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = data.aws_iam_policy_document.github_ci_apply.json
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
        raw = '"arn:aws:iam::1234567890:role/agent-platform-github-ci-prod-deploy"'
        assert _literal_or_prefix_match("agent-platform-github-ci-pr", raw, literal_only=True) is False
        exact = '"arn:aws:iam::1234567890:role/agent-platform-github-ci-pr"'
        assert _literal_or_prefix_match("agent-platform-github-ci-pr", exact, literal_only=True) is True

    def test_literal_or_prefix_match_secrets_manager_suffix(self) -> None:
        raw = '"arn:aws:secretsmanager:eu-west-2:1234567890:secret:agent-platform-github-pat-*"'
        assert _literal_or_prefix_match("agent-platform-github-pat", raw) is True
        assert _literal_or_prefix_match("agent-platform-github", raw) is False

    def test_literal_or_prefix_match_empty_stub_wildcard_skipped(self) -> None:
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

    def test_resource_covered_wildcard_branch(self) -> None:
        statements = [{"actions": ["logs:Describe*"], "resources_raw": '"*"'}]
        assert _resource_covered("aws_cloudwatch_log_group", "any", None, ("logs:Describe*",), statements) is True

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

    def test_resolve_role_statements_missing_planner_returns_none(self) -> None:
        """T2.49 / DEP-12: github_ci_plan + github_ci_drift merged into the single
        github_ci_planner role -- when its role-policy block is entirely absent, resolution
        fails (the negative branch of the (now single-entry) resolution loop)."""
        oidc_text = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*"]
    resources = ["*"]
  }
}
"""
        assert _resolve_role_statements(oidc_text) is None

    def test_resolve_role_statements_success_returns_planner(self) -> None:
        oidc_text = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_ci_planner" {
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}

data "aws_iam_policy_document" "github_ci_planner" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}
"""
        result = _resolve_role_statements(oidc_text)
        assert result is not None
        assert set(result) == {"planner"}

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


class TestClassifyAndResolveName:
    def test_classify_checked_type(self) -> None:
        spec, literal_only = _classify("aws_lambda_function")
        assert spec is CHECKED_TYPES["aws_lambda_function"]
        assert literal_only is False

    def test_classify_enumerated_iam_type_is_literal_only(self) -> None:
        spec, literal_only = _classify("aws_iam_role")
        assert spec is not None
        assert literal_only is True

    def test_classify_unmapped_returns_none(self) -> None:
        spec, literal_only = _classify("aws_kms_key")
        assert spec is None
        assert literal_only is False

    def test_resolve_resource_name_none_for_wildcard_only_spec(self) -> None:
        spec = {"read_actions": ("logs:Describe*", "logs:List*"), "name_attrs": None}
        assert _resolve_resource_name("aws_cloudwatch_log_group", "any", spec, {}, {}) is None

    def test_resolve_resource_name_resolves_literal(self) -> None:
        spec = CHECKED_TYPES["aws_lambda_function"]
        attr_index = {("aws_lambda_function", "fn"): {"function_name": '"agent-platform-fn"'}}
        assert _resolve_resource_name("aws_lambda_function", "fn", spec, {}, attr_index) == "agent-platform-fn"

    def test_resolve_resource_name_strips_oidc_url_scheme(self) -> None:
        spec = CHECKED_TYPES["aws_iam_openid_connect_provider"]
        attr_index = {("aws_iam_openid_connect_provider", "gh"): {"url": '"https://token.actions.githubusercontent.com"'}}
        assert (
            _resolve_resource_name("aws_iam_openid_connect_provider", "gh", spec, {}, attr_index)
            == "token.actions.githubusercontent.com"
        )

    def test_resolve_resource_name_unresolvable_returns_none(self) -> None:
        spec = CHECKED_TYPES["aws_lambda_function"]
        attr_index = {("aws_lambda_function", "fn"): {"function_name": "local.undefined"}}
        assert _resolve_resource_name("aws_lambda_function", "fn", spec, {}, attr_index) is None


class TestCheckResource:
    _KEY = "k:"

    def _covered_apply_stmts(self, resource: str) -> dict:
        return {"apply": [{"actions": ["lambda:Get*", "lambda:List*"], "resources_raw": f'"{resource}"'}]}

    def test_transitive_type_not_checked(self) -> None:
        findings, was_checked = _check_resource("aws_lambda_permission", "perm", "f.tf", {}, {}, {"apply": []}, self._KEY)
        assert findings == []
        assert was_checked is False

    def test_unmapped_type_fails_loud(self) -> None:
        findings, was_checked = _check_resource("aws_kms_key", "k", "f.tf", {}, {}, {"apply": []}, self._KEY)
        assert was_checked is False
        assert len(findings) == 1
        assert "unmapped resource type" in findings[0]

    def test_unresolvable_name_reports_finding(self) -> None:
        attr_index = {("aws_lambda_function", "fn"): {"function_name": "local.undefined"}}
        findings, was_checked = _check_resource("aws_lambda_function", "fn", "f.tf", {}, attr_index, {"apply": []}, self._KEY)
        assert was_checked is False
        assert len(findings) == 1
        assert "could not resolve a name/id" in findings[0]

    def test_covered_resource_no_findings(self) -> None:
        resource = "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-fn"
        attr_index = {("aws_lambda_function", "fn"): {"function_name": '"agent-platform-fn"'}}
        findings, was_checked = _check_resource(
            "aws_lambda_function", "fn", "f.tf", {}, attr_index, self._covered_apply_stmts(resource), self._KEY
        )
        assert findings == []
        assert was_checked is True

    def test_uncovered_resource_reports_finding(self) -> None:
        attr_index = {("aws_lambda_function", "fn"): {"function_name": '"agent-platform-fn"'}}
        role_statements = {"apply": [{"actions": ["s3:GetObject"], "resources_raw": '"*"'}]}
        findings, was_checked = _check_resource(
            "aws_lambda_function", "fn", "f.tf", {}, attr_index, role_statements, self._KEY
        )
        assert was_checked is True
        assert len(findings) == 1
        assert "is not refresh-read-covered" in findings[0]
