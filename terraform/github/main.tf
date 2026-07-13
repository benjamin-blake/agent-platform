# Isolated GitHub-settings root module (T2.12 / CD.20).
#
# WHY isolated: terraform/personal/ auto-applies from GitHub Actions via OIDC; the
# terraform_apply_guard.py is AWS-IAM-only and cannot inspect github_* resource diffs.
# A branch-protection change on that auto-apply path would apply ungated and could lock
# out the push-to-main flow the workflow depends on. This module is human-gated LOCAL
# apply only (see CLAUDE.md). NEVER add terraform/github/** to any apply-workflow path.
#
# Apply: see terraform/github/CLAUDE.md. Export GITHUB_TOKEN from Secrets Manager,
# then: terraform -chdir=terraform/github init && plan && apply.

terraform {
  required_version = ">= 1.10"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    bucket       = "agent-platform-data-lake"
    key          = "tfstate/github/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "github" {
  token = var.github_token
  owner = var.github_owner
}
