# Plan

## Intent
Restore the Decision-77 sandbox auto-apply pipeline by granting the CI apply role (`aws_iam_role_policy.github_ci_apply` in `terraform/personal/oidc.tf`) the refresh-time read permissions it currently lacks for resources added after the role was last scoped (PlatformDev/PlatformAdmin IAM roles, the RDS DuckLake catalog stack, and the RDS-managed master secret + KMS metadata). The fix is read-only and bounded by the existing fail-closed guard (`scripts/terraform_apply_guard.py`), preserving Decision 35 / Decision 77 IAM-apply-is-human-gated semantics. Unblocking this pipeline removes the latent block on every push-to-main change in `terraform/personal/**`, including T2.16b Phase 2 (RDS retirement), T2.17 (DuckLake Lambda runtime), and any subsequent platform-roadmap-driven infra work.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-github-ci-apply-refresh-reads.md

## Phase
Soft-warn exception: `ad_hoc_rec` / `hotfix`. The work does not map to any current `tier_items[].id` in `docs/ROADMAP-PLATFORM.yaml`, but it unblocks the auto-apply pipeline that gates roadmap items T2.16b Phase 2 (RDS retirement), T2.17 (DuckLake Lambda runtime), T2.4, T2.8, T2.9, and T2.15. Aligned with queued rec `pending-a59b3828` (named in the user's brief) and supersedes incorrectly-closed `rec-1985`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `terraform/personal/oidc.tf` | Modify `aws_iam_role_policy.github_ci_apply` | Add six refresh-time read statements so `terraform plan` reaches the guard. Five new Sids + one extension of the existing `DataLakeBucketManage` Sid. |
| `docs/plans/PLAN-github-ci-apply-refresh-reads.md` | Create | This plan artefact. |

Read-only context files (not modified -- referenced for action-set mirroring + sequencing rationale):
- `terraform/personal/platform_roles.tf` (mirror source for the RDS/EC2/KMS read sets)
- `terraform/personal/rds_ducklake_catalog.tf` (the transitional resources whose Describe* APIs are missing)
- `terraform/personal/neon_ducklake_catalog.tf` (precedent for the "Phase 0 manual -target apply" sequencing)
- `.github/workflows/terraform-apply-sandbox.yml` (the pipeline being unbroken; identifies the workflow_dispatch target)
- `scripts/terraform_apply_guard.py` (the guard that fails closed on `aws_iam_role_policy` updates and forces the manual apply route)
- `terraform/CLAUDE.md` "Out-of-band IAM grants" section (documents the manual `-refresh=false` iterative-discovery convention)

## Bundled Recommendations
- **Adopts queued rec `pending-a59b3828`** -- the user's brief noted this rec is buffered in `logs/.ops-outbox/` waiting for the next runtime sync. Its title is "Fix sandbox terraform-apply pipeline: github_ci_apply lacks refresh-read perms to plan terraform/personal" with `acceptance: grep -q role/PlatformAdmin terraform/personal/oidc.tf`. This plan's IAMPlatformRolesRead Sid satisfies that acceptance command literally.
- **Supersedes `rec-1985`** (closed) -- "OIDC apply role missing s3:GetBucketAcl + iam:GetRole; sandbox terraform plan AccessDenied". rec-1985 was closed 2026-05-31 as "stale-on-arrival" because the ci-rca dispatch tied it to an unrelated Main Canary failure that PR #18 had already fixed -- but the underlying CI-role permission gap was never fixed and is the same pipeline failure mode this plan addresses. The `s3:GetBucketAcl` + `iam:GetRole` gaps rec-1985 identified are explicitly covered here.

## Infrastructure Dependencies

| # | Resource | Action | Timing | Apply path |
|---|----------|--------|--------|------------|
| 1 | `aws_iam_role_policy.github_ci_apply` (in `terraform/personal/oidc.tf`) | Modify policy document (6 additive read statements) | Post-merge to main, BEFORE the next push-to-main attempts auto-apply | **MANUAL** via `agent_platform_admin` (`platform_breakglass`) with `terraform apply -target=aws_iam_role_policy.github_ci_apply -refresh=false`. The CD pipeline cannot auto-apply this resource (see below). |

**Why a manual targeted apply is required (chicken-and-egg)**: The fix modifies `aws_iam_role_policy`, which is in `IAM_SENSITIVE_TYPES` in `scripts/terraform_apply_guard.py:42-52`. The guard fails closed (exit 2) on any non-no-op/non-read action on an IAM-sensitive resource. So if the merged PR triggered the auto-apply pipeline, the guard would block apply BEFORE the fix can land. The `-target` apply via `agent_platform_admin` is the documented "Phase 0" pattern (mirror: `neon_ducklake_catalog.tf` lines 25-37 + `terraform/CLAUDE.md` "Out-of-band IAM grants"). `-refresh=false` skips a refresh round that would itself trip the same AccessDenied errors we're fixing.

**Pre-merge timing**: pre-merge `terraform validate` + `terraform fmt -check` only. No apply attempt pre-merge.

**Post-merge timing**: human runs the targeted apply from the admin container immediately after merge, then dispatches the workflow to confirm.

## Lambda Deployment Assessment
NONE. No file in scope is Lambda-packaged. `bin/venv-python -m scripts.lambda_manifest --list-patterns` returns patterns under `config/lambda/`, `src/lambdas/`, `src/data/handlers/`, `scripts/llm_client.py`, etc. -- none of which are in this plan's Scope. `terraform/personal/oidc.tf` is infrastructure only.

## Acceptance Criteria
- [ ] `aws_iam_role_policy.github_ci_apply` policy document contains a new Sid `IAMPlatformRolesRead` granting `iam:GetRole`, `iam:GetRolePolicy`, `iam:ListRolePolicies`, `iam:ListAttachedRolePolicies` scoped exactly to `arn:aws:iam::${var.account_id}:role/PlatformDev` + `arn:aws:iam::${var.account_id}:role/PlatformAdmin` (no other role ARNs, no write actions on these roles).
- [ ] Policy document contains three new transitional Sids -- `RDSDuckLakeCatalogRead`, `EC2NetworkingDescribeForRDS`, `KMSDescribeForRDS` -- each carrying an inline `PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion)` comment marker. Action sets mirror `aws_iam_role_policy.platform_admin_ducklake_catalog` exactly, restricted to the Describe-class READ subset (no Create/Modify/Delete on RDS, no SG mutation, no `kms:CreateGrant`).
- [ ] Policy document contains a new transitional Sid `SecretsManagerRDSMasterSecretRead` granting `secretsmanager:DescribeSecret` only (no `GetSecretValue`), scoped to `arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:rds!*`, with the same PRUNE marker.
- [ ] Existing `DataLakeBucketManage` Sid (lines 309-329) is extended with `s3:GetBucketAcl` + `s3:GetBucketOwnershipControls` (the two reads the AWS provider issues on the data-lake bucket that rec-1985 flagged and that the current policy still omits).
- [ ] Each NEW Sid carries the documented "do not prune as 'unused'" comment matching the convention already used for `glue:GetTags` (oidc.tf:348-350) and `dynamodb:DescribeContinuousBackups` (oidc.tf:372-376).
- [ ] `terraform -chdir=terraform/personal validate` exits 0.
- [ ] `terraform fmt -check -recursive terraform/personal/` exits 0.
- [ ] `bin/venv-python -m scripts.validate --pre` exits 0 (lint + format gate; full presubmit run separately).
- [ ] After post-merge manual `-target` apply: `gh workflow run terraform-apply-sandbox.yml --ref main` dispatches a run whose "Terraform plan" step exits 0 (gets past refresh-time reads to the guard). The guard's verdict is whatever the live plan diff happens to produce -- usually exit 0 (no-op, since live state matches main per the brief), but a guard BLOCK (exit 2) is also an acceptable outcome of this fix because it means refresh reads succeeded; the failure mode being fixed is AccessDenied during plan, not the guard's verdict.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm the new IAMPlatformRolesRead Sid is scoped to exactly the two platform role ARNs (no widening) | `grep -E 'role/(PlatformDev|PlatformAdmin)' terraform/personal/oidc.tf \| wc -l` | Output is `2` (one line each, no other matches) | If 0: edit forgot to scope; add the two Resource ARNs. If >2: a third role ARN was added -- remove it. |
| 2 | [pre-deploy] | Confirm the new Sid grants ONLY the four read actions (no write actions on platform roles) | `bin/venv-python -c "import re,json,pathlib; src=pathlib.Path('terraform/personal/oidc.tf').read_text(); m=re.search(r'IAMPlatformRolesRead.*?Resource\s*=\s*\[(.*?)\]', src, re.S); assert m, 'sid IAMPlatformRolesRead missing'; block=src[m.start():m.end()]; assert 'PutRolePolicy' not in block and 'UpdateAssumeRolePolicy' not in block and 'TagRole' not in block and 'AttachRolePolicy' not in block, 'forbidden write action present'; print('OK')"` | Prints `OK` | If asserts fail: a forbidden write action leaked into the new Sid -- delete it. Remember: CI must not be able to mutate the platform roles. |
| 3 | [pre-deploy] | Confirm all 4 transitional Sids carry the PRUNE marker (grep-target for the T2.16b Phase 2 cleanup) | `grep -c 'PRUNE: remove with T2.16b Phase 2' terraform/personal/oidc.tf` | Output is `4` (one per transitional Sid: RDSDuckLakeCatalogRead, EC2NetworkingDescribeForRDS, KMSDescribeForRDS, SecretsManagerRDSMasterSecretRead) | If 3 or fewer: one Sid is missing the marker; grep the Sid names and add the comment to whichever lacks it. |
| 4 | [pre-deploy] | Confirm action sets for the 3 RDS-stack transitional Sids exactly mirror `platform_admin_ducklake_catalog` (no invented actions) | `bin/venv-python -c "import re,pathlib; src=pathlib.Path('terraform/personal/oidc.tf').read_text(); mirror=pathlib.Path('terraform/personal/platform_roles.tf').read_text(); rds_in_mirror={a.strip().strip(',').strip('\"') for a in re.search(r'RDSDescribe.*?Action\s*=\s*\[(.*?)\]', mirror, re.S).group(1).split() if 'rds:' in a}; rds_in_ci={a.strip().strip(',').strip('\"') for a in re.search(r'RDSDuckLakeCatalogRead.*?Action\s*=\s*\[(.*?)\]', src, re.S).group(1).split() if 'rds:' in a}; assert rds_in_ci == rds_in_mirror, f'rds mismatch: CI={rds_in_ci-rds_in_mirror} mirror={rds_in_mirror-rds_in_ci}'; print('rds:OK')"` | Prints `rds:OK` | If mismatch: the CI Sid added or omitted an action vs the platform_admin mirror. Reconcile -- the mirror is authoritative. (EC2/KMS analogous; expand the check or run it three times by editing the Sid names.) |
| 5 | [pre-deploy] | Run terraform formatter check | `terraform fmt -check -recursive terraform/personal/` | Exit code 0; no diff output | If output diff: run `terraform fmt -recursive terraform/personal/` (without `-check`) and re-commit. |
| 6 | [pre-deploy] | Run terraform validate on the personal module | `terraform -chdir=terraform/personal init -input=false -backend-config=backend-sandbox.hcl -reconfigure -upgrade=false && terraform -chdir=terraform/personal validate` | Both commands exit 0; validate output is `Success! The configuration is valid.` | If init fails: backend-sandbox.hcl is gitignored; fall back to `-backend=false` for validate-only purposes (`terraform -chdir=terraform/personal init -backend=false && terraform -chdir=terraform/personal validate`). If validate fails: syntax error in the new HCL -- read the line:col reported and fix. |
| 7 | [pre-deploy] | Run repo presubmit (lint + format) | `bin/venv-python -m scripts.validate --pre` | Exit code 0 | If fail: read the specific check that failed and fix per its message (likely `terraform fmt` or unrelated lint -- this plan should not introduce Python lint issues since no .py files are in scope). |
| 8 | [pre-deploy] | Run full validate (no `--pre` flag -- the CI-equivalent gate) | `bin/venv-python -m scripts.validate` | Exit code 0 | If fail: read the failing check. Note: terraform plan is NOT run by validate.py against the personal module (no AWS creds in local presubmit context); the deferred plan test runs in CI/post-merge. |
| 9 | [post-deploy] | Run the manual targeted apply that the CD pipeline cannot perform on this resource (human action, NOT executed by the implement agent) | **Human action**: from a fresh admin container with `agent_platform_admin` credentials: `cd terraform/personal && terraform init -input=false -backend-config=backend-sandbox.hcl && TF_VAR_account_id=$AWS_ACCOUNT_ID TF_VAR_platform_dev_external_id="$(aws configure get external_id --profile agent_platform)" TF_VAR_platform_admin_external_id="$(aws configure get external_id --profile agent_platform_admin)" TF_VAR_owner_email="217728084+benjamin-blake@users.noreply.github.com" terraform plan -target=aws_iam_role_policy.github_ci_apply -refresh=false -out=plan.bin && terraform show plan.bin` then human reviews the diff (should be ONLY the 6 new statement additions on `aws_iam_role_policy.github_ci_apply`), then `terraform apply plan.bin` | Plan shows EXACTLY one change: `aws_iam_role_policy.github_ci_apply` updated in-place; no resource creates, no destroys, no other resources touched. Apply reports `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.` | If plan shows >1 resource: STOP. The `-target` filter widened unexpectedly; do not apply. Re-scope. If apply fails on a perm AdminOps lacks: AdminOps grants `iam:*` (platform_roles.tf:189-193) so any IAM apply should succeed; if it does not, file a separate rec. |
| 10 | [post-deploy] | Dispatch the sandbox auto-apply pipeline and confirm "Terraform plan" step exits 0 | **Human action**: `gh workflow run terraform-apply-sandbox.yml --ref main` then `gh run watch $(gh run list --workflow=terraform-apply-sandbox.yml --limit 1 --json databaseId --jq '.[0].databaseId')` | "Terraform plan" step exits 0. (Guard verdict may be exit 0 = no-op auto-apply OR exit 2 = BLOCKED requiring manual apply -- both are acceptable; the failure mode being fixed is AccessDenied during plan, not the guard's verdict.) | If "Terraform plan" still fails AccessDenied: iterative-discovery path. Read the workflow log, identify the NEW missing perm(s), add a NEW Sid (or extend an existing one) with the perm scoped per the `platform_roles.tf` mirror convention + the `do not prune as 'unused'` comment, re-run VP-1..8, manually `-target` re-apply, re-dispatch. This is the documented convention (terraform/CLAUDE.md "Out-of-band IAM grants" final paragraph). |
| 11 | [post-deploy] | Confirm no unintended widening of CI privilege (no IAM write on platform roles, no SG mutation, no SecretsManager GetSecretValue on rds!*) | `bin/venv-python -c "import json,subprocess; pol=json.loads(subprocess.check_output(['aws','iam','get-role-policy','--role-name','agent-platform-github-ci-apply','--policy-name','agent-platform-github-ci-apply','--profile','agent_platform_admin','--query','PolicyDocument','--output','json'])); stmts={s['Sid']:s for s in pol['Statement']}; assert 'IAMPlatformRolesRead' in stmts, 'new sid missing post-apply'; iam=stmts['IAMPlatformRolesRead']; assert set(iam['Action'])=={'iam:GetRole','iam:GetRolePolicy','iam:ListRolePolicies','iam:ListAttachedRolePolicies'}, f'unexpected actions: {iam[\"Action\"]}'; assert all('role/PlatformDev' in r or 'role/PlatformAdmin' in r for r in iam['Resource']), 'unexpected resource'; sm=next((s for s in pol['Statement'] if s.get('Sid')=='SecretsManagerRDSMasterSecretRead'), None); assert sm and 'secretsmanager:GetSecretValue' not in sm['Action'], 'GetSecretValue leaked'; print('OK')"` | Prints `OK` | If assert fails: the live policy diverges from the file -- this means VP-9's manual apply didn't apply the file as-intended OR a drifty manual edit happened. Reconcile by reading the diff and re-applying. |

## Constraints
- Read-only IAM/RDS/EC2/KMS/SecretsManager grants only. No write actions on platform roles. No SG/RDS lifecycle. No `secretsmanager:GetSecretValue` on `rds!*`. No `kms:CreateGrant` (only `DescribeKey`).
- Mirror exact action sets from `platform_admin_ducklake_catalog` (terraform/personal/platform_roles.tf:392-540) for the RDS/EC2/KMS Sids; mirror `platform_admin_datalake` for the S3 additions. Do not invent new actions.
- No `Resource: "*"` where resource-level scoping is supported: IAM reads pin the two role ARNs; SM read pins the `rds!*` ARN prefix. RDS/EC2/KMS Describes accept `*` per the AWS IAM docs (those Describe-class APIs do not support resource-level scoping; see `platform_admin_ducklake_catalog` comments on lines 400-401, 452-456, 502-507).
- No rescue agents or workaround loops (Decision 55). The "iterative-discovery" contingency in VP-10 is the documented terraform/CLAUDE.md convention -- it is NOT an unbounded loop; each round must produce a deterministic new perm, scoped, with a comment, then converge.
- The plan itself does not modify IAM live state. VP-9 is a human-executed step. The implement agent stops at VP-8 + the merge; VP-9 + VP-10 + VP-11 are post-merge human actions.

## Context

**Decisions to cite (from Step 6a scout's CITE list)**:
- **Decision 77** -- Two-Axis Environment/Phase Taxonomy + Sandbox Auto-Apply. The plan exists to restore the auto-apply pipeline this decision ratified. Clause 3 (deterministic guard + subagent review as compensating gate) is the mechanism this fix re-enables.
- **Decision 35** -- Terraform Workflow Integration. Decision 77 SCOPED rather than overturned Decision 35: the IAM update cannot auto-apply itself and must be human-applied via `agent_platform_admin`. The manual `-target` apply in VP-9 IS the surviving Decision-35 clause.
- **Decision 78** -- Adopt DuckLake for the operational lakehouse. Adds the RDS catalog (`rds_ducklake_catalog.tf`) whose Describe APIs drove the missing rds:Describe / ec2:Describe / kms:DescribeKey / secretsmanager:DescribeSecret read grants. Transitional Sids exist because of this ratification and must be cited so the T2.16b Phase 2 reversal can grep-find the PRUNE markers.
- **Decision 72** -- Branch Protection Unavailable. Clause 2 ("CI as a signal, not a lock") plus Decision 77 clause 3 establish that the guard + subagent review IS the compensating gate. Cites why no branch-protection-based alternative is considered for this fix.

**Related decisions (from scout's RELATED list)**:
- **Decision 73** -- CI forward-fix model. This plan IS the forward fix for the broken sandbox auto-apply pipeline; the historical rec-1985 misclose is the failure mode Decision 73 anticipates.
- **Decision 79** + **CD.16** + **CD.24** -- Per-Lambda manifest gating. Relevant context: no Lambda artifact is impacted, so V3 stays "real-AWS terraform plan" not "deploy+invoke a Lambda".
- **Decision 76** -- Web MCP merge flow. Step 11 of /plan uses `mcp__github__create_pull_request` + `subscribe_pr_activity` + `merge_pull_request(merge_method="squash")` rather than the `gh` CLI, per this decision.
- **Decision 81** / **CD.33** -- DuckLake ops runtime architecture. Ratified post-T2.16; the RDS catalog stack the new grants cover is the foundation this decision builds on. Aligns the transitional-marker lifecycle ("PRUNE: remove with T2.16b Phase 2") with FP-B / T2.19 timing.
- **CD.31** -- T2.16 ducklake-rds-catalog. The concrete tier_item whose Terraform produced the new IAM-read demands.
- **CD.21** -- GitHub-hosted OIDC CI. The `aws_iam_role_policy.github_ci_apply` resource being modified is the artifact CD.21 created.
- **Decision 67** (STRATEGIC clause retained per Decision 79) -- confirms plan must be IMPLEMENTATION type. This plan declares IMPLEMENTATION.

**Historical incident (rec-1985 misclose)**:
2026-05-31: `rec-1985` was filed by a ci-rca dispatch with this exact problem ("OIDC apply role missing s3:GetBucketAcl + iam:GetRole; sandbox terraform plan AccessDenied"). It was closed `execution_result=already_implemented` with resolution: "Stale-on-arrival: rec-1985 was filed by the VP7 verification dispatch of ci-rca against the historical Main Canary failure (run 26710594834), which diagnosed test_auto_recommendation_sync_in_output / drain_pending. That exact failure was already fixed by PR #18 ... Closing to prevent a false critical hard-block on the next /plan session." This was wrong: the ci-rca dispatch tied the rec to an unrelated test failure, but the *underlying CI-role permission gap* was never fixed. The current planning brief is the re-encounter of the same issue, now with additional missing perms (rds/ec2/kms) surfaced by T2.16 landing. This plan supersedes rec-1985 and explicitly covers its `s3:GetBucketAcl` + `iam:GetRole` findings.

**Sequencing constraint (chicken-and-egg, restated for clarity)**:
The guard's `IAM_SENSITIVE_TYPES` (terraform_apply_guard.py:42-52) includes `aws_iam_role_policy`. The fix updates `aws_iam_role_policy.github_ci_apply`. Therefore the CD pipeline cannot auto-apply this fix even after the PR merges. The manual `-target` apply via `agent_platform_admin` is required as a one-shot bootstrap. After this apply, subsequent pushes to `terraform/personal/**` that do NOT touch IAM-sensitive resources will auto-apply normally.

**Iterative-discovery convention** (terraform/CLAUDE.md "Out-of-band IAM grants" final paragraph): "If a future module addition needs a new data-plane action, expect the FIRST `plan` after the apply to surface it as an AccessDenied refresh read; add it (scoped) and re-apply with `-refresh=false` (state is fresh from the apply), then a full `plan` converges." VP-10's contingency is the same convention applied here. Expect 1-2 rounds at most -- the brief identified the major missing perms; remaining gaps are likely tiny single-action additions.

**Branch divergence (Step 4 Main Divergence Assessment)**: At planning start the local branch was 12 commits behind `origin/main`. The local main was fast-forwarded BEFORE this planning session, so the plan is authored against current HEAD (commit f97efe4e), which includes PR #72 (Neon Phase 0/1) and PR #73 (apply-time fixes). No divergence residual.

**Operational data governance**: the queued rec `pending-a59b3828` is in the local outbox (logs/.ops-outbox/ops_recommendations_pending/) and will surface on the next `bin/venv-python -m scripts.ops_data_portal --sync` from a runtime that has the agent_platform profile attached. The implement agent should NOT manually edit recommendation JSONL files (Single Portal Invariant); the rec will appear naturally via Athena sync. After plan acceptance, the implement agent SHOULD file a follow-on rec via `file_rec` titled "Prune transitional rds/ec2/kms/sm refresh-reads from github_ci_apply after T2.16b Phase 2 RDS retirement", `file=terraform/personal/oidc.tf`, `acceptance: ! grep -E 'PRUNE: remove with T2.16b Phase 2' terraform/personal/oidc.tf` (i.e. all PRUNE markers gone), `priority=Medium`, `effort=XS`, `automatable=false`.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently on `agent/github-ci-apply-refresh-reads`)
- [ ] `docs/PROJECT_CONTEXT.md` read (covered during planning)
- [ ] Relevant DECISIONS read via decision-scout (NO_FLAGS; CITE list resolved)
- [ ] All files in Scope table located and readable (`terraform/personal/oidc.tf` confirmed at HEAD)
- [ ] Context files read (platform_roles.tf, rds_ducklake_catalog.tf, neon_ducklake_catalog.tf, terraform-apply-sandbox.yml, terraform_apply_guard.py, terraform/CLAUDE.md)
- [ ] Acceptance Criteria understood and verifiable
- [ ] `agent_platform_admin` profile available to the human executing VP-9 (verify with `aws sts get-caller-identity --profile agent_platform_admin`)

## Ordered Execution Steps

1. **Edit `terraform/personal/oidc.tf`** -- inside `aws_iam_role_policy.github_ci_apply` (lines 278-466), perform these six edits to the `policy = jsonencode({ Version, Statement = [...] })` document. The edits are additive; preserve every existing Sid byte-for-byte. Maintain Sid ordering: extend `DataLakeBucketManage` in place, then insert the five new Sids in this order AFTER `OIDCProviderReconcile` (line 428) and BEFORE `SecretsManagerDuckLakeNeonDSN` (line 437):

   a. **Extend `DataLakeBucketManage` Sid (lines 309-329)**. After the existing `"s3:GetBucketWebsite"` entry (line 327), add two new entries: `"s3:GetBucketAcl"` and `"s3:GetBucketOwnershipControls"`. Update the inline comment block to note: the additions cover the bucket-attribute reads the provider issues that `platform_admin_datalake` (mirror) already grants but this CI policy omitted -- documented in the rec-1985 finding.

   b. **Insert NEW Sid `IAMPlatformRolesRead`** (PERMANENT, no PRUNE marker). Comment block must explain: (i) this grants the CI apply role refresh-time reads on PlatformDev + PlatformAdmin (required because both roles are imported + managed by platform_roles.tf, so a `plan` of terraform/personal walks them); (ii) explicitly read-only -- the platform roles must not be CI-mutable; (iii) the four actions are the IAM read-quartet that AWS provider 5.x issues on every aws_iam_role plan. Statement:
   ```hcl
   {
     Sid    = "IAMPlatformRolesRead"
     Effect = "Allow"
     Action = [
       "iam:GetRole",
       "iam:GetRolePolicy",
       "iam:ListRolePolicies",
       "iam:ListAttachedRolePolicies",
     ]
     Resource = [
       "arn:aws:iam::${var.account_id}:role/PlatformDev",
       "arn:aws:iam::${var.account_id}:role/PlatformAdmin",
     ]
   },
   ```

   c. **Insert NEW Sid `RDSDuckLakeCatalogRead`** (TRANSITIONAL). Comment block must include: (i) PRUNE marker `# PRUNE: remove with T2.16b Phase 2 (rds_ducklake_catalog.tf deletion)`; (ii) "do not prune as 'unused'" note; (iii) the 12 actions are the exact mirror of `aws_iam_role_policy.platform_admin_ducklake_catalog` Sid `RDSDescribe` (platform_roles.tf:400-417); (iv) Resource `*` because Describe-class RDS APIs do not support resource-level scoping.

   d. **Insert NEW Sid `EC2NetworkingDescribeForRDS`** (TRANSITIONAL). Comment block: PRUNE marker + "do not prune" + mirror reference to `EC2NetworkingDescribe` (platform_roles.tf:452-469). 7 actions: `ec2:DescribeVpcs`, `DescribeVpcAttribute`, `DescribeSubnets`, `DescribeSecurityGroups`, `DescribeSecurityGroupRules`, `DescribeAvailabilityZones`, `DescribeTags`. Resource `*`.

   e. **Insert NEW Sid `KMSDescribeForRDS`** (TRANSITIONAL). Comment block: PRUNE marker + "do not prune" + mirror reference to `KMSMetadataForRDS` (platform_roles.tf:500-515), restricted to READ subset (excludes `kms:CreateGrant` because the CI role only refresh-reads encrypted-storage + managed-secret KMS metadata; it does not provision grants). Single action: `kms:DescribeKey`. Resource `*` (can't pin without ARN-pinning per-account key UUIDs, which drift; widening to `*` is acceptable because IAM provides no write here).

   f. **Insert NEW Sid `SecretsManagerRDSMasterSecretRead`** (TRANSITIONAL). Comment block: PRUNE marker + "do not prune" + cross-reference to the precedent `SecretsManagerNeonAPIKeyRead` Sid (oidc.tf:456-463) for the read-only-secret pattern. Single action: `secretsmanager:DescribeSecret` (NOT `GetSecretValue`). Resource: `"arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:rds!*"`. Inline note that `manage_master_user_password = true` on the RDS instance (rds_ducklake_catalog.tf:166) is what produces the `rds!*` ARN prefix.

2. **Execute Verification Plan VP-1 through VP-8** in order. Loop on failure within each step until pass.

3. **Commit** with message:
   ```
   fix(sandbox-pipeline): grant github_ci_apply refresh-time reads for IAM + RDS stack

   Unbreaks the Decision-77 sandbox auto-apply pipeline by adding six additive
   read-only statements to aws_iam_role_policy.github_ci_apply. Five new Sids
   (IAMPlatformRolesRead permanent; RDSDuckLakeCatalogRead, EC2NetworkingDescribeForRDS,
   KMSDescribeForRDS, SecretsManagerRDSMasterSecretRead transitional with PRUNE markers
   for T2.16b Phase 2) plus s3:GetBucketAcl + s3:GetBucketOwnershipControls extending
   DataLakeBucketManage. Mirrors platform_admin_datalake + platform_admin_ducklake_catalog
   action sets; no write actions, no privilege widening.

   Supersedes rec-1985 (misclosed). Adopts pending-a59b3828.
   Refs: Decision 77, Decision 35, Decision 78, Decision 72.
   ```

4. **Open PR via MCP** (Decision 76):
   - `mcp__github__create_pull_request(owner="benjamin-blake", repo="agent-platform", head="agent/github-ci-apply-refresh-reads", base="main", title="fix(sandbox-pipeline): grant github_ci_apply refresh-time reads for IAM + RDS stack", body=...)`.
   - Body must include: (a) "Phase 0 manual apply REQUIRED post-merge" callout; (b) the exact command for VP-9; (c) the iterative-discovery contingency.

5. **Subscribe + wait for CI**: `mcp__github__subscribe_pr_activity(...)`, end the turn. CI completion arrives as a webhook event.

6. **On green CI wake**: `mcp__github__merge_pull_request(merge_method="squash")` + `mcp__github__unsubscribe_pr_activity(...)`.

7. **File the follow-on prune rec**: call `file_rec` with the cleanup rec described in the Context section. Per AGENTS.md "Single Portal Invariant", use the `file_rec` portal call only -- no direct JSONL edits.

8. **Hand off VP-9 + VP-10 + VP-11 to the human**: the implement agent's mission ends at merge; the post-merge manual apply + workflow dispatch + privilege-widening assertion are human-executed.

9. **Report**: what was implemented, VP-1..8 results, PR URL, file_rec ID for the prune follow-on, the literal command the human needs to run for VP-9.

## Work Areas (STRATEGIC plans only)
N/A -- this plan is IMPLEMENTATION.
