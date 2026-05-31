# Plan

## Intent
Close the T2.12 public-repo security gate deferred under CD.20. A planning-time git-history blast-radius audit (run via subagent) found NO must-rotate secrets and an already-scrubbed history (single orphan-commit baseline from the public migration). The work is therefore NOT a history rewrite: it is (a) a trivial HEAD-only parameterization of a post-scrub-reintroduced AWS account-id literal, (b) document-and-accept of the residual identifier-class exposures via a recorded decision, and (c) standing up the deferred detective/preventive controls -- GHAS secret scanning + push protection, branch-protection ruleset, CodeQL, Dependabot, and the fork-PR Actions policy -- as code via an ISOLATED, human-gated Terraform module that is deliberately kept OFF the `terraform/personal/**` auto-apply path. A SECURITY.md vulnerability-reporting pointer is added. The plan file self-deletes as the final step (it carries the masked exposure enumeration).

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
claude/t2-12-public-sweep-7JT2c

## Phase
Platform-tier hardening. Roadmap tier_item **T2.12** ("public-repo security gate", deferred per CD.20). Sits beside the T2.13 public-flip / post-flip-verification neighbourhood and the T2.15 CI verification-coverage-restoration debt. Aligned: this plan satisfies the CD.20 exit criteria directly.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `SECURITY.md` | Create | Minimal private vulnerability-reporting pointer (GitHub private security advisories + maintainer contact). States it is the CD.20 projection; notes T2.11b may enrich later. ASCII-only, no emojis. |
| `.github/dependabot.yml` | Create | Dependabot version + security updates for two ecosystems: `pip` (root `requirements*.txt`) and `github-actions` (`/`). Weekly schedule, grouped minor/patch, sensible open-PR cap. |
| `.github/workflows/codeql.yml` | Create | GitHub CodeQL Default-style advanced workflow, `language: python`, triggers: `pull_request` to `main` + `push` to `main` + weekly `schedule`. Uses Node-24 action majors (`github/codeql-action/*@v3`, `actions/checkout@v5`). Concurrency-guarded. |
| `terraform/github/main.tf` | Create | New ISOLATED root module: `terraform { required_providers { github } }` + S3 backend (own state key `tfstate/github/terraform.tfstate` in `agent-platform-data-lake`, `use_lockfile = true`) + `provider "github"` (owner `benjamin-blake`, token from `var.github_token`). |
| `terraform/github/repo.tf` | Create | `github_repository` (GHAS: `advanced_security`, `secret_scanning`, `secret_scanning_push_protection` = enabled; preserve existing repo metadata to avoid clobber -- see Constraints), `github_repository_ruleset` for `main` (require PR + 0/1 review, require status checks `validate (pre)` / the CD.21 PR check names, block force-push + deletion, require linear history) WITH an explicit `bypass_actors` admin escape hatch, `github_actions_repository_permissions` (fork-PR approval = `all_outside_collaborators`; default workflow token = read). |
| `terraform/github/variables.tf` | Create | `github_token` (sensitive, no default -- supplied at apply from Secrets Manager export), `github_owner`, `repository_name`, `admin_bypass_actor_id`. |
| `terraform/github/README.md` | Create | Human-gated LOCAL apply runbook: where the PAT lives (Secrets Manager `GITHUB_PAT_SECRET_ARN` pattern), required PAT scopes (`repo`, `admin:repo_hook`, `read:org`), the exact `aws secretsmanager get-secret-value ... | export GITHUB_TOKEN` + `terraform -chdir=terraform/github plan/apply` sequence, the lockout-recovery note, and the explicit statement that this module is NEVER on any auto-apply trigger. |
| `terraform/github/.terraform.lock.hcl` | Create | Provider lock for `integrations/github` -- COMMITTED (overriding the repo-wide gitignore of lockfiles) so the new privileged surface is version-pinned. See Constraints. |
| `.github/workflows/terraform-apply-sandbox.yml` | Modify | Replace the literal personal account-id in the inline comment (masked `...7169`) with a non-literal placeholder / `vars.AWS_ACCOUNT_ID` reference. Comment-only edit; no workflow logic change. |
| `docs/plans/PLAN-ci-health-restoration.md` | Modify | Replace the one prose occurrence of the literal account-id (`...7169`) with a placeholder token. Doc-only edit. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Mark T2.12 `status` progressed; record that history-rewrite was assessed and rejected (no secrets); link the recorded decision id. If T2.12 lacks the new sub-criteria, refine `exit_criteria` to match what shipped (controls-as-code + accept-decision), not a rewrite. |
| `AGENTS.md` | Modify | Remove (or convert to "DONE") the "T2.12 security gate deferred (CD.20)" Temporary Operational Constraints bullet once controls are in place; add a one-line operational runbook pointer to `terraform/github/README.md`. |

## Bundled Recommendations
None. Preflight surfaced no open `ci_rca` or security recs targeting these files. This is roadmap-tier-sourced work (T2.12), not rec-sourced.

## Infrastructure Dependencies
- **New isolated Terraform root module `terraform/github/`** managing GitHub repo settings via the `integrations/github` provider. It is deliberately a SEPARATE root module with its own state key, kept OFF every auto-apply trigger (`terraform-apply-sandbox.yml` path filter is `terraform/personal/**` only -- `terraform/github/**` matches nothing). Applied **human-gated, locally**, per `terraform/CLAUDE.md`'s default human-gated class.
- **Why isolated (the core architectural decision):** `terraform/personal/**` auto-applies FROM GitHub Actions via OIDC role `agent-platform-github-ci-apply` (pinned to `refs/heads/main`), and that apply is gated by `scripts/terraform_apply_guard.py`, which inspects ONLY `aws_iam_*` resource types + `assume_role_policy` diffs. GitHub provider resources (`github_repository_ruleset`, `github_actions_repository_permissions`, etc.) are INVISIBLE to that guard -- so a branch-protection change on the auto-apply path would apply UNGATED and could lock out the very push-to-main flow the workflow depends on. Isolation + human-gated local apply removes this entire risk class. (See Decision 77 / `docs/contracts/environment-taxonomy.md`.)
- **GitHub token:** an admin-scoped PAT (or GitHub App token) stored in AWS Secrets Manager (matching the existing `GITHUB_PAT_SECRET_ARN` pattern used by the Lambda dispatcher). NOT committed; NOT placed in any Actions secret consumed by an auto-apply workflow. Provisioned by the human operator at apply time. This plan does not create the secret -- the runbook documents its required shape.
- **No `terraform/personal/` mutation.** No AWS IAM/infra is created or changed by this plan's own deliverables. The only AWS touchpoint is the human reading an existing/operator-provisioned Secrets Manager value at apply time.

## Acceptance Criteria
- [ ] `SECURITY.md` exists at repo root, ASCII-only, names the private reporting channel, and is discoverable by GitHub's "Security policy" panel.
- [ ] `.github/dependabot.yml` parses (valid schema) and registers `pip` + `github-actions` ecosystems.
- [ ] `.github/workflows/codeql.yml` parses, scans `python`, and a CodeQL run completes `success` on the branch / first PR.
- [ ] `terraform/github/` `terraform validate` passes and `terraform plan` is clean/non-destructive against the live repo (run locally with the PAT exported). The plan shows GHAS enable + ruleset create + Actions-policy set, and shows NO destroy/replace of the `github_repository` itself.
- [ ] The `main` branch-protection ruleset includes a working **admin bypass actor** (verified by reading it back; an in-band escape hatch exists).
- [ ] The personal account-id literal `...7169` no longer appears in `.github/workflows/terraform-apply-sandbox.yml` or `docs/plans/PLAN-ci-health-restoration.md` (`git grep` for the value returns only this plan file, which is then deleted).
- [ ] A decision is recorded (via `python -m scripts.ops_data_portal`) capturing the accept-exposure disposition (identifiers acceptable; no history rewrite; account-id parameterized at HEAD). Masked findings only.
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses; T2.12 reflects progressed status + the decision id.
- [ ] The "T2.12 security gate deferred (CD.20)" constraint is removed/marked done in `AGENTS.md`.
- [ ] `bin/venv-python -m scripts.validate` (full presubmit) exits 0.
- [ ] Remote CI is green on the branch (authoritative gate, CD.21).
- [ ] Final step: `docs/plans/PLAN-t2-12-public-sweep.md` is deleted and the deletion is committed.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-merge | Validate Dependabot + CodeQL YAML schema | `bin/venv-python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/dependabot.yml','.github/workflows/codeql.yml']]; print('ok')"` | `ok` | Parse error -> fix indentation/keys |
| 2 | pre-merge | Terraform fmt + validate the new module (no apply) | `terraform -chdir=terraform/github init -backend=false && terraform -chdir=terraform/github validate && terraform -chdir=terraform/github fmt -check` | validate `Success`, fmt clean | Provider/source error -> fix `required_providers`; fmt -> run `fmt` |
| 3 | pre-merge (operator, needs PAT) | Plan the GitHub module against live repo | `export GITHUB_TOKEN=$(aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text --profile agent_platform) && terraform -chdir=terraform/github init && terraform -chdir=terraform/github plan` | Plan shows GHAS enable + ruleset create + Actions-policy set; NO destroy/replace of `github_repository` | Plan wants to recreate/clobber the repo -> add `import` blocks or align `github_repository` args to current state (Constraints) |
| 4 | pre-merge | Account-id literal gone from the two HEAD files | `git grep -nI 707578707169 -- .github/ docs/ \| grep -v PLAN-t2-12-public-sweep.md` | No matches | Stale literal remains -> parameterize it |
| 5 | pre-merge | Confirm `terraform/github/**` is NOT on any auto-apply trigger | `grep -rn "terraform/" .github/workflows/terraform-apply-sandbox.yml` | Path filter shows only `terraform/personal/**`; no `terraform/github` match | A trigger references the new module -> remove it (must stay human-gated) |
| 6 | pre-merge | Roadmap + decision wiring | `bin/venv-python -m scripts.platform_roadmap` then confirm decision via `python -m scripts.ops_data_portal` sync/read | T2.12 progressed; decision id resolvable | YAML parse error -> fix; decision missing -> file it |
| 7 | pre-merge | Full presubmit (CI-identical) | `bin/venv-python -m scripts.validate` | Exit 0 | Any check fails -> address before push |
| 8 | apply (operator, human-gated) | Apply the GitHub module locally; read back ruleset + GHAS | `terraform -chdir=terraform/github apply` then verify via `mcp__github__*` / GitHub UI | GHAS on; ruleset on `main` with admin bypass actor; fork-PR policy set | Apply error -> diagnose; if a ruleset risks merge-lockout, confirm bypass actor before proceeding |
| 9 | post-apply (verification, manual-UI) | Confirm detective controls active | GitHub UI Security tab / `mcp__github__list_dependabot_alerts` etc. | Secret scanning + push protection ON; Dependabot enabled; CodeQL results appear | A control off -> re-check the corresponding resource / repo-level toggle. NOTE: a PAT lacking `security_events` returns 403 on alert-LIST reads -- verify those in the UI, not via API |
| 10 | post-merge (remote) | Push branch; confirm remote CI green + CodeQL run | `git push -u origin claude/t2-12-public-sweep-7JT2c` then watch CI + CodeQL via `mcp__github__*` | CI conclusion `success`; CodeQL `success` | CI red -> read failed logs, fix, repeat. Do NOT merge until green |
| 11 | final | Delete the plan file and commit | `git rm docs/plans/PLAN-t2-12-public-sweep.md && git commit -m "Remove T2.12 plan file post-implementation"` | Plan file gone from tree; enumeration not persisted | n/a |

## Constraints
- **The hard "don't" (Decision 77 / environment-taxonomy):** do NOT add the `github` provider or any `github_*` resource to `terraform/personal/`, and do NOT add `terraform/github/**` to any apply-workflow path filter. `terraform_apply_guard.py` is AWS-IAM-only and blind to GitHub resources; auto-applying branch-protection changes ungated risks a self-lockout. This module is human-gated LOCAL apply, full stop.
- **Lockout mitigation is mandatory.** The `main` ruleset MUST carry an explicit `bypass_actors` admin entry (the repo-admin / the App) so a human always retains an in-band escape hatch. Apply ruleset changes deliberately; after apply, confirm the squash-merge-to-main flow still works (it is the trigger for the AWS auto-apply workflow). Keep the UI-revoke recovery note in the README.
- **Do not clobber the live repository.** `github_repository` manages an EXISTING repo -- use `import` blocks (or `terraform import`) and set args to match current metadata (description, visibility=public, topics, features) so `plan` does not propose recreate/destroy. Verify Step 3 shows no repo replacement before any apply.
- **Commit the GitHub module's `.terraform.lock.hcl`** (override the repo-wide lockfile gitignore for this path) -- the auto-apply surface gitignores its lock, but this privileged GitHub surface must be version-pinned to limit provider supply-chain risk.
- **No history rewrite.** A second `git filter-repo` on the public repo would rewrite every SHA, break all forks/clones/open PRs, and buys nothing (no must-rotate secret survives). The audit verdict is ACCEPT + parameterize-at-HEAD. Do NOT attempt a rewrite.
- **Output hygiene.** Mask sensitive identifiers (last-4) anywhere they must be referenced in commits/decisions/docs. Never write a fresh verbatim enumeration of identifiers into a persisted artifact -- the plan file (which holds the masked enumeration) is deleted at the end as belt-and-suspenders.
- **Operational data governance.** Record the accept-decision via `python -m scripts.ops_data_portal` (file the decision through the portal; call `get_rec_write_guidance()` semantics where applicable). Never edit `logs/.decisions-index.jsonl` directly. No `OpsWriter.write()` from cache.
- **Platform commands.** `bin/venv-python`; Bash syntax; ASCII hyphens; no emojis; type hints if any Python is touched (none expected).
- **Branch discipline.** Never commit on `main`. Work on `claude/t2-12-public-sweep-7JT2c`.
- **Merge flow (Decision 76).** Web merge uses `mcp__github__*`: open PR via `create_pull_request`, await the `--pre` tier via `subscribe_pr_activity` (end the turn; do not `sleep`), squash-merge via `merge_pull_request(merge_method="squash")`. Do NOT open a PR unless the user asks.

## Context
- **Audit verdict (planning-time subagent, full tree + all 27 commits across all refs):** NO must-rotate live secrets -- zero AWS keys (AKIA/ASIA), zero GitHub tokens (only `github_pat_xxxx` placeholders), zero private keys, zero IAM principal ids (AIDA/AROA). The gitignored secret source `terraform/personal/terraform.personal.tfvars` was NEVER committed. History is structurally clean because the public migration (`docs/plans/PLAN-public-migration.md`) abandoned the regex `filter-repo` approach and instead collapsed all 919 commits / 24 branches into a single orphan "Initial commit" (`4bd5850`), deleted 43 sensitive files, applied case-insensitive substitutions over that one commit, and delete-and-recreated the repo. A pre-scrub backup lives OFF-repo at `../mlsbx-prescrub-backup.git`.
- **The one genuine residual:** the personal AWS account-id `...7169`, a POST-scrub regression re-introduced in commits during the CI-health-restoration work, present in exactly 2 HEAD files (a comment in `terraform-apply-sandbox.yml`, a prose line in `PLAN-ci-health-restoration.md`). An account-id is NOT a credential -- exploitability is effectively nil (any use requires a valid IAM principal + secret, none of which exist in-repo; OIDC trust is scoped to `repo:benjamin-blake/agent-platform` ref conditions). Cheap HEAD-only parameterization restores the migration plan's "no committed account-id literal" intent.
- **ACCEPT-class identifiers (documented, not scrubbed):** AWS-managed layer account `...8345` (public AWSSDKPandas), Canonical AMI owner `...9477`, placeholder example ids, dormant LEGACY work-account bucket names `bblake-*` / `formulas-*` (NOT provisioned in the personal account per `docs/PROJECT_CONTEXT.md` + `terraform/CLAUDE.md`), live `agent-platform-*` bucket names (identifiers; access blocked if S3 Block Public Access is on), and the intentional public owner identity (Benjamin Blake / GitHub noreply). None are credentials; all routinely appear in published IaC.
- **Terraform apply model (planning-time subagent):** two independent root modules. `terraform/` (root, work-account) is retained per CD.21 but NO LONGER APPLIED (local state, SSO profile). `terraform/personal/` is the ONLY applied module -- S3 backend (`agent-platform-data-lake`, key `tfstate/personal/sandbox/terraform.tfstate`, `use_lockfile`), AWS provider only, applied FROM `.github/workflows/terraform-apply-sandbox.yml` on push-to-main with path filter `terraform/personal/**`, authed via OIDC role `agent-platform-github-ci-apply` (refs/heads/main only), gated by `terraform_apply_guard.py` (fail-closed on delete / `aws_iam_*` change / `assume_role_policy` diff) + a subagent plan-review requiring a literal `PROCEED`. The OIDC role grants AWS-only perms -- zero GitHub API access. The repo uses NO GitHub provider today. These facts drive the isolated-module design above.
- **Decisions cited (decision-scout gate):**
  - **CD.20** -- the deferral this plan closes (GHAS secret scanning + push protection, branch protection w/ required checks, CodeQL, Dependabot, fork-PR approval policy). This plan's deliverables map 1:1 to its enumerated items.
  - **CD.21** -- CI now runs on GitHub-hosted runners via OIDC; the required-status-check NAMES for the branch-protection ruleset must match the actual CD.21 check names (`validate (pre)` / the PR-tier workflow). Confirm exact names at implement time before pinning them in the ruleset.
  - **Decision 77 / `docs/contracts/environment-taxonomy.md`** -- the sandbox auto-apply guard model; mandates keeping GitHub resources OFF that path (the guard cannot see them).
  - **Decision 76** -- web merge flow via `mcp__github__*`.
  - **Decision 72** -- this plan's premise (history audit) is now RESOLVED; no ci-rca rec is involved (not rec-sourced; roadmap-tier-sourced).
- **Decision flags (decision-scout, dispositions):**
  - *SECURITY.md overlap (WARN)* -- a future T2.11b may own a richer SECURITY.md. Disposition (human-approved): author a MINIMAL pointer now with a scope-claim note that T2.11b may enrich it. No conflict.
  - *CD.21 status-check-name NOTE* -- handled (confirm names at implement time, VP-adjacent).
  - *Decision 77 path-isolation NOTE* -- handled by the isolated-module design.
  - *Gate-ordering NOTE* -- handled (human-gated local apply, never auto).
- **Out-of-band items this plan can only FLAG (human action, not executable here):**
  1. Confirm S3 Block Public Access is enabled on the live `agent-platform-*` buckets (the one exposure where posture matters).
  2. Confirm the off-repo `../mlsbx-prescrub-backup.git` (which DOES contain the original pre-scrub PII) is not on any public surface.
  3. Provision the admin GitHub PAT in Secrets Manager before running Step 3/8.
- **Verification constraint:** the admin PAT may lack the `security_events` scope, so post-enablement alert-LIST reads (Dependabot/secret/code-scanning) can return 403 -- those checks are manual-UI (VP step 9), while file-presence, Terraform plan/validate, CodeQL run-status, and ruleset read-back are automatable.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `claude/t2-12-public-sweep-7JT2c`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` entries read (CD.20, CD.21, Decision 72, 76, 77)
- [ ] `docs/contracts/environment-taxonomy.md` read (auto-apply guard scope)
- [ ] `.github/workflows/terraform-apply-sandbox.yml` + `scripts/terraform_apply_guard.py` read (confirm path filter + guard scope before designing the module's apply posture)
- [ ] Existing repo metadata (description, topics, visibility, features) captured for the `github_repository` import (avoid clobber)
- [ ] CD.21 required-status-check names confirmed for the ruleset
- [ ] Operator has provisioned the admin GitHub PAT in Secrets Manager
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`SECURITY.md`** -- create a minimal, ASCII-only vulnerability-reporting policy: point to GitHub private security advisories ("Report a vulnerability" / private advisory) as the primary channel plus the maintainer contact; one line noting this is the CD.20 projection and a future T2.11b may enrich it. No secrets, no internal infra detail.
2. **`.github/dependabot.yml`** -- author version-2 config: `pip` ecosystem (root, pointing at the actual requirements file(s); confirm their paths), `github-actions` ecosystem (`/`). Weekly schedule, grouped minor/patch updates, reasonable `open-pull-requests-limit`. Validate schema.
3. **`.github/workflows/codeql.yml`** -- author the advanced CodeQL workflow: `python` only, triggers `pull_request`/`push` to `main` + weekly `schedule` + `workflow_dispatch`; Node-24 action majors (`actions/checkout@v5`, `github/codeql-action/init|analyze@v3`); `security-events: write` permission; concurrency group. Do NOT add a CodeQL gate to `ci.yml`/`validate.py` (it runs as its own workflow); per the Merge protocol invariant, nothing is added to `ci.yml` here.
4. **`terraform/github/` module** -- create `main.tf` (required_providers `integrations/github ~> 6`, S3 backend with own key `tfstate/github/terraform.tfstate` + `use_lockfile`, `provider "github"` using `var.github_token` + owner), `variables.tf` (sensitive `github_token`, `github_owner`, `repository_name`, `admin_bypass_actor_id`), `repo.tf` (`github_repository` with GHAS blocks + import-aligned metadata; `github_repository_ruleset` on `main` with required PR/checks/linear-history/no-force-push/no-deletion AND `bypass_actors` admin entry; `github_actions_repository_permissions` fork-PR = `all_outside_collaborators`, default token read). Run `terraform fmt`. Commit `.terraform.lock.hcl` for this path (override gitignore -- add a negation entry or `git add -f`).
5. **`terraform/github/README.md`** -- write the human-gated LOCAL apply runbook: PAT location (Secrets Manager arn, required scopes `repo`/`admin:repo_hook`/`read:org`), the exact `aws secretsmanager get-secret-value ... | export GITHUB_TOKEN` + `terraform -chdir=terraform/github init/plan/apply` sequence, the explicit "NEVER on any auto-apply trigger" statement, the bypass-actor lockout-recovery note, and the UI-revoke recovery path. Match the AGENTS.md runbook style.
6. **Account-id parameterization (HEAD-only)** -- in `.github/workflows/terraform-apply-sandbox.yml` replace the literal `...7169` in the comment with a non-literal placeholder / `vars.AWS_ACCOUNT_ID` reference (comment-only; no logic change). In `docs/plans/PLAN-ci-health-restoration.md` replace the prose literal with a placeholder token. Confirm via VP step 4.
7. **Record the accept-decision** -- via `python -m scripts.ops_data_portal`, file a decision capturing: history audited at planning time, no must-rotate secrets, identifier-class exposures accepted, account-id parameterized at HEAD, no history rewrite, controls-as-code stood up. Masked findings only. Capture the returned decision id for the roadmap link.
8. **`docs/ROADMAP-PLATFORM.yaml`** -- progress T2.12 status; note the rewrite-rejected rationale and link the decision id; refine `exit_criteria` to reflect what shipped (controls-as-code + accept-decision + parameterization) if they currently presume a rewrite. Confirm parse via `scripts.platform_roadmap`.
9. **`AGENTS.md`** -- remove (or mark DONE) the "T2.12 security gate deferred (CD.20)" Temporary Operational Constraints bullet; add a one-line operational-runbook pointer to `terraform/github/README.md`.
10. **Execute Verification Plan** -- VP steps 1-7 locally (loop to green). VP step 8 (apply) + step 9 (post-apply UI verification) are operator/human-gated -- run when the PAT is available; if a ruleset risks merge-lockout, confirm the bypass actor first. Then VP step 10 (push + remote CI/CodeQL). If a V3 step fails unrecoverably, stop and root-cause (Decision 55) -- do not loop workarounds.
11. **Report + flag out-of-band items** -- summarise changes, local + remote verification results, the decision id, and the three human-action flags (S3 BPA confirm, off-repo backup confirm, PAT provisioning). Note that VP step 8/9 require the operator apply.
12. **Self-delete the plan file** -- `git rm docs/plans/PLAN-t2-12-public-sweep.md` and commit (per user direction: the plan carries the masked enumeration; remove it post-implementation). This is the final step.
