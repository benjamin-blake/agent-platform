# Plan

## Intent

Enable the scheduled agents workflow to authenticate with AWS via OIDC federation, eliminating the need for static credentials that cannot be created due to company SCP restrictions, and documenting the constraint to prevent future agents from suggesting blocked IAM user creation.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-oidc-workflow

## Phase

Phase 1: Core Infrastructure (maintenance — enables scheduled agents deployed in prior session)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| terraform/data_pipeline.tf | Modify | Add GitHub Actions OIDC provider and IAM role with trust policy |
| .github/workflows/scheduled-agents.yml | Modify | Replace static credentials with OIDC role assumption |
| .github/copilot-instructions.md | Modify | Add SCP restriction gotcha (iam:CreateUser blocked) |
| .github/copilot_instructions.md | Modify | Add same SCP restriction gotcha (keep both files in sync) |
| docs/GETTING_STARTED.md | Modify | Update scheduled agents setup to reflect OIDC (no AWS secrets) |
| docs/DECISIONS.md | Modify | Add Decision 36 documenting OIDC choice over static credentials |

## Bundled Recommendations

- rec-083 (closed but referenced): "Workflow uses static AWS credentials instead of OIDC federation" — this plan completes the tracked migration

## Infrastructure Dependencies

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing |
|----------|-----------------|------------------------------|---------------|
| aws_iam_openid_connect_provider.github_actions | create (if not exists) | No | pre-merge |
| aws_iam_role.github_actions_agent_logs | create | Yes (workflow uses role ARN) | pre-merge |
| aws_iam_role_policy_attachment.github_actions_agent_logs | create | No | pre-merge |

### Deploy Timing Guidance

**Pre-merge required:** The workflow references the role ARN directly. The role must exist before the workflow runs, otherwise the OIDC token exchange will fail with "role not found".

### Rollback Notes

```bash
terraform destroy -target=aws_iam_role_policy_attachment.github_actions_agent_logs
terraform destroy -target=aws_iam_role.github_actions_agent_logs
# OIDC provider is shared — only destroy if no other roles use it
```

## Acceptance Criteria

- [ ] `terraform plan` shows OIDC provider and role to be created (or provider already exists)
- [ ] `terraform apply` succeeds (human-confirmed)
- [ ] Workflow file uses `aws-actions/configure-aws-credentials@v4` with `role-to-assume`
- [ ] Workflow file has `id-token: write` permission
- [ ] Workflow file does NOT reference `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`
- [ ] Both copilot instructions files contain SCP restriction gotcha
- [ ] GETTING_STARTED.md scheduled agents section updated for OIDC
- [ ] Manual trigger of `doc-freshness` agent succeeds (smoke test)
- [ ] `python scripts/validate.py` exits 0
- [ ] All tests pass

## Constraints

- Company SCP denies `iam:CreateUser` — must use IAM roles via OIDC
- Terraform changes require human-confirmed `terraform apply` (Decision 35)
- OIDC provider URL is fixed: `https://token.actions.githubusercontent.com`
- Trust policy must be scoped to this repository only

## Context

- Decision 35: Terraform workflow integration requires plan/apply gates
- Decision 24: Agents use sandbox only; promotion is human-triggered
- rec-083: Previously closed with "OIDC migration tracked as separate task"
- Known Gotcha: Duplicate copilot instruction files — must update both

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Phase A: Terraform Dry-Run (SCP Validation)

1. **Run terraform plan to verify SCP permits role creation.** Before writing any Terraform code, run `terraform plan` with the existing configuration to confirm the AWS session is valid. This step exists to catch SCP blocks early.

### Phase B: Terraform Changes

2. **Add OIDC provider data source and conditional resource to `terraform/data_pipeline.tf`.** Append after the existing `aws_iam_policy.agent_logs_s3_access` block:
   - `data "aws_iam_openid_connect_provider" "github_actions"` — looks up existing provider
   - `resource "aws_iam_openid_connect_provider" "github_actions"` with `count = 0` if data source found, `count = 1` otherwise
   - `locals` block to resolve provider ARN from whichever path was taken

3. **Add IAM role for GitHub Actions to `terraform/data_pipeline.tf`.** Create `aws_iam_role.github_actions_agent_logs` with:
   - Trust policy allowing `sts:AssumeRoleWithWebIdentity` from the OIDC provider
   - Condition: `token.actions.githubusercontent.com:sub` = `repo:benjamin-blake/agent-platform:*`
   - Condition: `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com`

4. **Attach the existing S3 policy to the role.** Create `aws_iam_role_policy_attachment.github_actions_agent_logs` attaching `aws_iam_policy.agent_logs_s3_access.arn` to the role.

5. **Add output for the role ARN.** Add `output "github_actions_agent_logs_role_arn"` so the ARN is visible after apply.

6. **Run `terraform fmt` and `terraform validate`.** Fix any formatting or syntax errors before proceeding.

### Phase C: Infrastructure Deployment Gate (Human Required)

7. **Run `terraform plan -out=tfplan` and present output to human.** Show the planned changes. Wait for human to say "apply" before proceeding. If human says "defer", mark as post-merge task and skip to Step 9.

8. **Run `terraform apply tfplan` after human confirmation.** Record the output role ARN for use in Step 9.

### Phase D: Workflow Changes

9. **Update `.github/workflows/scheduled-agents.yml` permissions.** Add `id-token: write` to both top-level and job-level `permissions` blocks (required for OIDC token request).

10. **Replace the "Configure AWS credentials" step.** Remove the existing `env:` block with static credentials and the `aws configure set` commands. Replace with:
    ```yaml
    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@v4
      with:
        role-to-assume: arn:aws:iam::REDACTED-ACCOUNT-ID:role/agent-platform-github-actions-agent-logs
        aws-region: eu-west-2
    ```

11. **Remove static credential references from workflow comments.** Update the header comments to reflect OIDC is now in use; remove references to `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` secrets.

### Phase E: Documentation Updates

12. **Add SCP restriction gotcha to `.github/copilot-instructions.md`.** In the Known Gotchas section, add:
    ```
    - **Company SCP blocks IAM user creation (Important):** The sandbox account has a Service Control Policy denying `iam:CreateUser`. Do not suggest creating IAM users or access keys. Use GitHub Actions OIDC federation with IAM roles instead. See Decision 36 in `docs/DECISIONS.md`.
    ```

13. **Add the same gotcha to `.github/copilot_instructions.md`.** Keep both files in sync per the "Duplicate copilot instruction files" gotcha.

14. **Update `docs/GETTING_STARTED.md` scheduled agents section.** Remove the AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY secret instructions. Replace with:
    - OIDC is pre-configured via Terraform
    - Only secret needed is `COPILOT_PAT`
    - Link to Decision 36 for rationale

15. **Add Decision 36 to `docs/DECISIONS.md`.** Document the choice of OIDC over static credentials, including:
    - Context: SCP blocks iam:CreateUser
    - Decision: Use GitHub Actions OIDC federation
    - Rationale: Short-lived credentials, no secrets to rotate, company policy compliant

### Phase F: Validation

16. **Run `pytest tests/` — all tests must pass before proceeding.**

17. **Run `python scripts/validate.py` — must exit 0.**

18. **Report what was implemented and any design decisions made during implementation.**

### Phase G: Human Verification Steps (Post-Merge)

> These steps are performed by the human after the PR is merged.

19. **Create GitHub PAT with `copilot` scope.** Go to https://github.com/settings/tokens → Generate new token (classic) → Select `copilot` scope → Copy token.

20. **Add `COPILOT_PAT` secret to repository.** Go to repository Settings → Secrets and variables → Actions → New repository secret → Name: `COPILOT_PAT`, Value: the PAT from Step 19.

21. **Trigger `doc-freshness` agent as smoke test.** Go to Actions → Scheduled Agents → Run workflow → Agent: `doc-freshness` → Run. Verify the "Configure AWS credentials" step shows "Assuming role arn:aws:iam::REDACTED-ACCOUNT-ID:role/..." and completes successfully.

22. **Verify S3 output exists.** Run `aws s3 ls s3://bblake-platform-agent-logs/ --region eu-west-2 --recursive` and confirm a new `.jsonl` file from the smoke test run.
