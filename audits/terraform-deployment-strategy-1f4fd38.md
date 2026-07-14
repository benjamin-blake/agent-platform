# Terraform Deployment Strategy Audit (1f4fd38)

## Autonomy posture

The current strategy is **mostly agent-first and frontier-maturity** for today's single-account sandbox. Routine infrastructure changes route through PRs touching `terraform/personal/**`, saved plans, the deterministic Terraform guard, digest-fed subagent review, and same-plan apply. Lambda code deploys are intentionally separate from Terraform and now have governed DuckLake and prod-class workflows with scoped deploy roles, deploy records, and smoke gates. Reconcile is the right recovery direction: it reads the red convergence commit from the durable record rather than asking an operator to supply a target SHA.

The audit did not find a need for more human gates. Existing gates are property-matched: bootstrap/admin authority, trust expansion, out-of-budget IAM, destroy/replace, and future SIT/PROD/manual approval are the right places to keep humans. The improvement theme is reducing interpretation load so agents do not have to re-derive the same rules from prose, workflow comments, and historical decisions.

## Top simplification moves

1. **Normalize deploy channel state into `build-lambda.yaml` (TDS-01).** The deploy workflows are safe, but `deploy-paths.yaml` embeds detailed channel state in one long status scalar. Move role-provisioned variables, bootstrap-window behavior, deploy record prefixes, smoke gates, and fallback commands into typed per-channel fields.
2. **Make Reconcile the single routine red-record recovery verb (TDS-03).** `reconcile.yml` is input-free for the target commit, but `terraform-apply-sandbox.yml` still exposes `acknowledge_red_commit`. Keep that only as a labelled non-default compatibility path or retire it after confirming no active runbook depends on it.
3. **Correct landed provider-lock wording (TDS-02).** The personal Terraform lock file is already unignored and present; the environment taxonomy still describes it as ignored/recommended. This is a stale-contract cleanup, not an unbuilt supply-chain control.

## Gates to keep now

- `tf-gated-apply` approval for out-of-budget IAM, trust-policy changes, destroy/replace, and non-create Neon mutations. The deterministic guard detects the class, but it is not the authorization boundary for trust expansion.
- Operator-only bootstrap/admin authority changes. The system should not self-amend the IAM authority that grants its own apply power.
- Deploy-role bootstrap variables until the scoped roles are provisioned. The current workflow behavior avoids silent green deployed states by emitting `deployed=true` only after real deploys and checking deploy-record freshness before smoke.

## Gates to defer to future environments

SIT/PROD manual apply and second-approver controls remain future-state, correctly tied to dedicated accounts and real-capital/product-risk triggers. Absence of those accounts is not a current defect, and importing that ceremony into sandbox would reduce agent autonomy without property-matching a current risk.

## Highest-leverage next move

**TDS-01 / MOVE-01** is highest leverage because it converts the remaining deploy-code narrative blob into structured contract data that agents and validators can consume. It preserves existing workflow safety while reducing rediscovery cost across deploy, recovery, and break-glass decisions.

## Metadata notes

- `origin/main` was unavailable in this harness, so the audit used `HEAD` (`1f4fd38`) as the audited base and filename stem.
- Dedup was not degraded: preflight pulled recommendation/decision caches.
- `validate --pre` did not pass in this origin-less harness: repository-level differential verification attempted to add a worktree at `origin/main` and failed with `fatal: invalid reference: origin/main`; several unrelated HEAD admission checks also returned command 127. The deliverable YAML parse passed.
