# Import the existing repository so Terraform manages it without recreating it.
# Run: terraform -chdir=terraform/github import github_repository.this agent-platform
# Or use the import block below (Terraform 1.5+).
import {
  to = github_repository.this
  id = var.repository_name
}

resource "github_repository" "this" {
  name       = var.repository_name
  visibility = "public"

  # GitHub Advanced Security: secret scanning + push protection (T2.12 / CD.20).
  security_and_analysis {
    # advanced_security is omitted: GitHub Advanced Security is always-on for PUBLIC repos;
    # setting it via the API errors ("always available for public repositories"). The repo
    # went public at T2.13 (2026-05-30), so only secret scanning + push protection are managed.
    secret_scanning {
      status = "enabled"
    }
    secret_scanning_push_protection {
      status = "enabled"
    }
  }

  # Preserve existing repo metadata. Terraform will read the live state on first plan;
  # ignore_changes prevents accidental resets of description/topics/features on subsequent plans.
  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      description,
      homepage_url,
      topics,
      has_issues,
      has_projects,
      has_wiki,
      has_discussions,
      has_downloads,
      allow_merge_commit,
      allow_squash_merge,
      allow_rebase_merge,
      allow_auto_merge,
      allow_update_branch,
      delete_branch_on_merge,
      archived,
    ]
  }
}

# Branch-protection ruleset for main (T2.12 / CD.20).
# Required status checks use the LIVE check-run names from ci.yml jobs 'pr-validate' and
# 'terraform-validate' (NOT the placeholder 'validate (pre)' -- see VP step 4 / ci.yml:16,138).
# bypass_actors carries an admin escape hatch: actor_id=5 = Repository Admin role so a human
# always retains an in-band escape from lockout.
resource "github_repository_ruleset" "main_protection" {
  repository  = github_repository.this.name
  name        = "main-protection"
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["refs/heads/main"]
      exclude = []
    }
  }

  bypass_actors {
    actor_id    = var.admin_bypass_actor_id
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_approving_review_count   = 0
      required_review_thread_resolution = false
    }

    required_status_checks {
      required_check {
        # integration_id = 0 uses GitHub's legacy "any integration" semantics, which is
        # the documented approach for GitHub Actions checks in the Terraform provider.
        context        = "pr-validate"
        integration_id = 0
      }
      required_check {
        context        = "terraform-validate"
        integration_id = 0
      }
      # strict = false: allows merging a branch that is not up-to-date with main.
      # Intentional for the Decision 76 squash-merge flow (sole-developer project);
      # the ruleset still requires green status checks before any merge.
      strict_required_status_checks_policy = false
    }

    required_linear_history = true
  }
}

# Actions settings: all actions allowed (filtered by the ruleset gate), but Actions
# are explicitly enabled. Restricts which action types may run (a future addition).
resource "github_actions_repository_permissions" "this" {
  repository      = github_repository.this.name
  allowed_actions = "all"
  enabled         = true
}

# Workflow permissions: default token = read-only; GitHub Actions cannot approve PRs.
# Restricts the blast radius of a compromised workflow -- the GITHUB_TOKEN cannot
# self-approve or write without an explicit permissions: block in the workflow file.
# Note: the GitHub UI "fork pull request approval" policy (require approval from all
# outside collaborators) is not exposed by this provider attribute; set it manually
# in repo Settings -> Actions -> Fork pull request workflows from outside collaborators.
resource "github_workflow_repository_permissions" "this" {
  repository                       = github_repository.this.name
  default_workflow_permissions     = "read"
  can_approve_pull_request_reviews = false
}
