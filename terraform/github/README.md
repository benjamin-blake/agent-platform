# terraform/github -- GitHub repository settings (human-gated, LOCAL apply only)

This module manages GitHub repository settings for `benjamin-blake/agent-platform` via the
`integrations/github` Terraform provider: GitHub Advanced Security (secret scanning + push
protection), the `main` branch-protection ruleset, and Actions permissions.

## NEVER auto-apply this module

The `terraform-apply-sandbox.yml` workflow path filter is `terraform/personal/**`. This module
(`terraform/github/**`) matches nothing in that filter and is intentionally excluded. Adding it
to any auto-apply workflow is FORBIDDEN (Decision 77 / `docs/contracts/environment-taxonomy.md`):
`terraform_apply_guard.py` is AWS-IAM-only and cannot inspect `github_*` resource diffs; a
branch-protection change applied ungated could lock out the push-to-main flow the workflow depends
on. Apply this module locally, by hand, every time.

## Prerequisites

- Terraform 1.10+ (`cat config/terraform-version`)
- AWS credentials for the `agent_platform` profile (to read the GitHub PAT from Secrets Manager)
- A GitHub admin PAT stored in Secrets Manager. Required scopes: `repo`, `admin:repo_hook`, `read:org`.

## Apply runbook

```bash
# 1. Export the GitHub PAT from Secrets Manager.
export GITHUB_TOKEN=$(aws secretsmanager get-secret-value \
  --secret-id <GITHUB_PAT_SECRET_ARN> \
  --query SecretString \
  --output text \
  --profile agent_platform)

# 2. Initialise (uses the S3 backend in agent-platform-data-lake).
terraform -chdir=terraform/github init

# 3. Plan -- review carefully before applying.
#    STOP if plan shows any destroy/replace of github_repository OR any unintended
#    in-place reset of description/homepage/topics/visibility/features.
#    An in-place UPDATE that resets metadata is NOT a destroy and must also be absent.
terraform -chdir=terraform/github plan -var="admin_bypass_actor_id=5"

# 4. Apply -- only after plan is confirmed safe.
terraform -chdir=terraform/github apply -var="admin_bypass_actor_id=5"
```

## Lockout recovery

If the ruleset is applied with incorrect required-status-check names and merges are blocked:
1. Use the bypass actor (repo Admin role, actor_id=5) to merge a fix branch directly, OR
2. Disable the ruleset via the GitHub UI: repo Settings -> Rules -> Rulesets -> main-protection -> Disable.

## First-time import

On a fresh state, Terraform will use the `import` block in `repo.tf` to import the existing
`agent-platform` repository rather than recreating it. Verify the plan shows no replacement.
If the import block is not supported by your Terraform version, run:
```bash
terraform -chdir=terraform/github import github_repository.this agent-platform
```

## Ruleset check-run names

The required status checks are pinned to the LIVE check-run names (`pr-validate`,
`terraform-validate`) from `.github/workflows/ci.yml` jobs. Do not change these to the
placeholder `validate (pre)`. A wrong name silently provides no gate or locks out all merges.

## Fork pull request approval (manual step post-apply)

The `github_workflow_repository_permissions` resource sets the default workflow token to read-only
and disables GitHub Actions PR self-approval. The strict "fork PR approval = all outside
collaborators" policy is NOT exposed by the Terraform provider v6 and must be set manually
after apply:
- Repo Settings -> Actions -> General -> Fork pull request workflows from outside collaborators
- Select: "Require approval for all outside collaborators"
