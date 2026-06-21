variable "github_token" {
  description = "GitHub admin PAT. Supplied at apply time from Secrets Manager -- never committed. Required scopes: repo, admin:repo_hook, read:org."
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub organisation or user that owns the repository."
  type        = string
  default     = "benjamin-blake"
}

variable "repository_name" {
  description = "GitHub repository name managed by this module."
  type        = string
  default     = "agent-platform"
}

variable "admin_bypass_actor_id" {
  description = "GitHub actor ID granted ruleset bypass. Use 5 for the built-in Repository Admin role (anyone with admin permission). Supplied at apply time."
  type        = number
  default     = 5
}

variable "gated_apply_reviewer_user_ids" {
  description = "List of GitHub numeric user IDs required to approve the tf-gated-apply Environment gate before the gated-apply job may execute. Supplied at apply time -- never committed with a literal default. Resolve before applying: `gh api /user --jq .id` (authenticated as the reviewer) or the GitHub MCP get_me tool."
  type        = list(number)
}
