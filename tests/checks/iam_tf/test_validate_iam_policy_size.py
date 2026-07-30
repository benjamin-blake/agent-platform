"""Tests for the bootstrap IAM policy-size precondition gate (H3 / PLAN-iam-write-surface-completion).

Presence + correct-constant only -- there is no renderer to test (H3: no HCL rendering, no
minification, no var substitution in the fast tier). Every negative asserts a LOUD failure: a
missing precondition, a precondition naming the other container's limit, a precondition that only
mentions the limit in its error_message prose, one written inside a comment, and the vacuous
zero-resource case all produce findings rather than a silent pass.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_iam_policy_size import POLICY_SIZE_LIMITS, validate_iam_policy_size

_INLINE_LIMIT = POLICY_SIZE_LIMITS["aws_iam_role_policy"]
_MANAGED_LIMIT = POLICY_SIZE_LIMITS["aws_iam_policy"]


def _run(tmp_path: Path, tf: str, filename: str = "github_ci_apply.tf") -> list[str]:
    bootstrap = tmp_path / "terraform" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (bootstrap / filename).write_text(tf, encoding="utf-8")
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_iam_policy_size(failed)
    return failed


def _policy_resource(rtype: str, name: str, lifecycle: str) -> str:
    return f"""
resource "{rtype}" "{name}" {{
  name   = "agent-platform-{name}"
  policy = local.{name}_policy_json
{lifecycle}
}}
"""


def _precondition(limit: int, local_name: str) -> str:
    return f"""
  lifecycle {{
    precondition {{
      condition     = length(jsonencode(jsondecode(local.{local_name}_policy_json))) <= {limit}
      error_message = "policy exceeds its limit."
    }}
  }}
"""


# ---------------------------------------------------------------------------
# Positive
# ---------------------------------------------------------------------------


def test_real_tree_passes() -> None:
    """The live terraform/bootstrap tree carries a correct precondition on every policy resource."""
    failed: list[str] = []
    validate_iam_policy_size(failed)
    assert failed == [], failed


def test_inline_role_policy_with_correct_limit_passes(tmp_path: Path) -> None:
    tf = _policy_resource("aws_iam_role_policy", "apply", _precondition(_INLINE_LIMIT, "apply"))
    assert _run(tmp_path, tf) == []


def test_managed_policy_with_correct_limit_passes(tmp_path: Path) -> None:
    tf = _policy_resource("aws_iam_policy", "reads", _precondition(_MANAGED_LIMIT, "reads"))
    assert _run(tmp_path, tf) == []


def test_all_three_policy_containers_pass_together(tmp_path: Path) -> None:
    """The post-split shape: one inline role policy + two managed policies, each at its own limit."""
    tf = (
        _policy_resource("aws_iam_role_policy", "apply", _precondition(_INLINE_LIMIT, "apply"))
        + _policy_resource("aws_iam_policy", "reads", _precondition(_MANAGED_LIMIT, "reads"))
        + _policy_resource("aws_iam_policy", "boundary", _precondition(_MANAGED_LIMIT, "boundary"))
    )
    assert _run(tmp_path, tf) == []


def test_second_precondition_may_carry_the_limit(tmp_path: Path) -> None:
    """A lifecycle block may hold several preconditions; ANY of them may be the size assertion."""
    lifecycle = f"""
  lifecycle {{
    precondition {{
      condition     = var.account_id != ""
      error_message = "account_id must be set."
    }}
    precondition {{
      condition     = length(jsonencode(jsondecode(local.reads_policy_json))) <= {_MANAGED_LIMIT}
      error_message = "too big."
    }}
  }}
"""
    assert _run(tmp_path, _policy_resource("aws_iam_policy", "reads", lifecycle)) == []


def test_inline_jsonencode_with_interpolations_still_parses(tmp_path: Path) -> None:
    """Braces from an "${var.account_id}" interpolation must not break block extraction."""
    tf = f"""
resource "aws_iam_policy" "boundary" {{
  name = "agent-platform-boundary"
  policy = jsonencode({{
    Statement = [
      {{
        Sid      = "DenyBoundaryPolicyModification"
        Effect   = "Deny"
        Resource = ["arn:aws:iam::${{var.account_id}}:policy/agent-platform-github-ci-apply-reads"]
      }}
    ]
  }})
{_precondition(_MANAGED_LIMIT, "boundary")}
}}
"""
    assert _run(tmp_path, tf) == []


def test_attachment_resource_is_not_a_policy_container(tmp_path: Path) -> None:
    """aws_iam_role_policy_attachment holds no document, so it needs no precondition."""
    tf = (
        _policy_resource("aws_iam_policy", "reads", _precondition(_MANAGED_LIMIT, "reads"))
        + """
resource "aws_iam_role_policy_attachment" "reads" {
  role       = aws_iam_role.github_ci_apply.name
  policy_arn = aws_iam_policy.reads.arn
}
"""
    )
    assert _run(tmp_path, tf) == []


# ---------------------------------------------------------------------------
# Negative -- each must FAIL LOUD
# ---------------------------------------------------------------------------


def test_policy_with_no_lifecycle_fails(tmp_path: Path) -> None:
    failed = _run(tmp_path, _policy_resource("aws_iam_policy", "reads", ""))
    assert len(failed) == 1
    assert "declares no lifecycle precondition" in failed[0]
    assert str(_MANAGED_LIMIT) in failed[0]


def test_lifecycle_without_precondition_fails(tmp_path: Path) -> None:
    lifecycle = """
  lifecycle {
    ignore_changes = [tags]
  }
"""
    failed = _run(tmp_path, _policy_resource("aws_iam_role_policy", "apply", lifecycle))
    assert len(failed) == 1
    assert "declares no lifecycle precondition" in failed[0]


def test_inline_role_policy_naming_the_managed_limit_fails(tmp_path: Path) -> None:
    """6144 on an INLINE role policy would silently permit a ~4 KB overflow past every plan."""
    tf = _policy_resource("aws_iam_role_policy", "apply", _precondition(_MANAGED_LIMIT, "apply"))
    failed = _run(tmp_path, tf)
    assert len(failed) == 1
    assert "WRONG limit constant" in failed[0]
    assert str(_MANAGED_LIMIT) in failed[0]


def test_managed_policy_naming_the_inline_limit_fails(tmp_path: Path) -> None:
    """10240 on a customer-managed policy asserts a ceiling AWS will reject 4 KB earlier."""
    tf = _policy_resource("aws_iam_policy", "reads", _precondition(_INLINE_LIMIT, "reads"))
    failed = _run(tmp_path, tf)
    assert len(failed) == 1
    assert "WRONG limit constant" in failed[0]
    assert str(_INLINE_LIMIT) in failed[0]


def test_precondition_naming_no_recognised_limit_fails(tmp_path: Path) -> None:
    tf = _policy_resource("aws_iam_policy", "reads", _precondition(4096, "reads"))
    failed = _run(tmp_path, tf)
    assert len(failed) == 1
    assert "no recognised limit constant" in failed[0]


def test_limit_only_in_error_message_prose_fails(tmp_path: Path) -> None:
    """The constant must be in the CONDITION -- prose in the message asserts nothing."""
    lifecycle = """
  lifecycle {
    precondition {
      condition     = length(local.reads_policy_json) <= 99
      error_message = "reads policy exceeds the 6144 B managed-policy limit."
    }
  }
"""
    failed = _run(tmp_path, _policy_resource("aws_iam_policy", "reads", lifecycle))
    assert len(failed) == 1
    assert "no recognised limit constant" in failed[0]


def test_commented_out_precondition_does_not_count(tmp_path: Path) -> None:
    """A precondition living in a comment is not enforcement -- comment masking must ignore it."""
    lifecycle = f"""
  # lifecycle {{
  #   precondition {{
  #     condition = length(jsonencode(jsondecode(local.reads_policy_json))) <= {_MANAGED_LIMIT}
  #   }}
  # }}
"""
    failed = _run(tmp_path, _policy_resource("aws_iam_policy", "reads", lifecycle))
    assert len(failed) == 1
    assert "declares no lifecycle precondition" in failed[0]


def test_resource_header_inside_a_comment_is_not_a_resource(tmp_path: Path) -> None:
    """A commented-out resource must neither be checked nor count towards the discovery floor."""
    tf = (
        _policy_resource("aws_iam_policy", "reads", _precondition(_MANAGED_LIMIT, "reads"))
        + '\n# resource "aws_iam_role_policy" "retired_example" {\n#   policy = local.dead\n# }\n'
    )
    assert _run(tmp_path, tf) == []


def test_no_policy_resources_fails_loud(tmp_path: Path) -> None:
    """A parser break (or a genuine relocation out of the root) must never pass vacuously."""
    tf = """
resource "aws_iam_role" "github_ci_apply" {
  name = "agent-platform-github-ci-apply"
}
"""
    failed = _run(tmp_path, tf)
    assert len(failed) == 1
    assert "no aws_iam_role_policy / aws_iam_policy resources discovered" in failed[0]


def test_no_tf_files_fails_loud(tmp_path: Path) -> None:
    (tmp_path / "terraform" / "bootstrap").mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_iam_policy_size(failed)
    assert len(failed) == 1
    assert "no .tf files" in failed[0]


def test_unbalanced_resource_block_fails_loud(tmp_path: Path) -> None:
    tf = 'resource "aws_iam_policy" "reads" {\n  policy = local.reads_policy_json\n'
    failed = _run(tmp_path, tf)
    assert any("cannot parse the resource block" in f for f in failed)


def test_findings_are_per_resource(tmp_path: Path) -> None:
    """Two broken containers produce two findings -- the gate does not stop at the first."""
    tf = _policy_resource("aws_iam_role_policy", "apply", "") + _policy_resource("aws_iam_policy", "reads", "")
    failed = _run(tmp_path, tf)
    assert len(failed) == 2
    assert any("aws_iam_role_policy.apply" in f for f in failed)
    assert any("aws_iam_policy.reads" in f for f in failed)


def test_limits_are_the_aws_hard_limits() -> None:
    assert POLICY_SIZE_LIMITS["aws_iam_role_policy"] == 10240
    assert POLICY_SIZE_LIMITS["aws_iam_policy"] == 6144
