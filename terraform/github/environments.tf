# GitHub Environment: tf-gated-apply (CD.35 Wave 3 / T2.22 / Decision 92).
#
# This Environment gates the post-merge apply job for the guard fail-closed set
# (IAM/trust/destroy diffs that exit 2 from scripts/terraform_apply_guard.py). A job
# declaring `environment: tf-gated-apply` does NOT start until the required reviewer
# (benjamin-blake) approves in GitHub Actions -- this is the authorization boundary for
# the fail-closed set within github_ci_apply's existing IAM scope.
#
# Key constraints:
#   - prevent_self_review = false: sole-developer repo; the only reviewer must be able to
#     approve (prevent_self_review=true would wedge the pipeline permanently).
#   - deployment_branch_policy: protected_branches = true restricts the gated job to the
#     protected main branch; custom_branch_policies = false.
#   - Reviewer user IDs are supplied at apply time via var.gated_apply_reviewer_user_ids
#     (mirrors the admin_bypass_actor_id convention); they are NOT committed with a literal
#     default. Resolve before applying: `gh api /user --jq .id` or GitHub MCP get_me.
#
# Authorization boundary: the Environment gates the post-merge apply JOB -- it is NOT a PR
# required status check (that would wedge autonomous fix-merges, Decision 83). The gated
# job assumes the existing agent-platform-github-ci-apply role (trust UNCHANGED, pinned to
# refs/heads/main); the Environment is the gate, not an OIDC environment claim in the sub
# (a known GitHub footgun -- the sub is still refs/heads/main, see oidc.tf comment).
#
# Broader IAM changes beyond github_ci_apply's current scope remain admin-gated until T2.23.
#
# NEVER add this resource to any auto-apply workflow path (README.md / Decision 77):
# terraform/github/ is human-gated LOCAL apply only; the guard cannot inspect github_* diffs.

resource "github_repository_environment" "tf_gated_apply" {
  repository          = github_repository.this.name
  environment         = "tf-gated-apply"
  prevent_self_review = false

  reviewers {
    users = var.gated_apply_reviewer_user_ids
  }

  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}
