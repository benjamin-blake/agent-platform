# terraform/bootstrap -- CI/CD bootstrap root (NEVER auto-apply, admin-only)

This module owns the `github_ci_apply` IAM role and its permissions boundary (authority budget),
isolating the apply role's own IAM from `terraform/personal/` (CD.35 Wave 4 / T2.23). This breaks
the self-grant cycle: the CD pipeline can no longer write the policy that governs the pipeline.

## NEVER auto-apply this module

The `terraform-apply-sandbox.yml` path filter is `terraform/personal/**`. This module
(`terraform/bootstrap/**`) is intentionally excluded and must NEVER be added to any auto-apply
workflow or the `terraform_apply_guard.py` guard path. Apply this module manually, by hand, every
time, using the `agent_platform_admin` profile (PlatformAdmin, `iam:*`).

## Prerequisites

- Terraform 1.10+ (`cat config/terraform-version`)
- AWS credentials for the `agent_platform_admin` profile (PlatformAdmin, `iam:*`).
- The bootstrap S3 state bucket must exist (see One-time provisioning below).
- `account_id` and `owner_email` passed via `-var` or a gitignored tfvars file (never committed).

## One-time provisioning

### 1. Create the dedicated state bucket

The bootstrap state bucket must exist before `terraform init` can succeed. Create it once:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile agent_platform_admin)

aws s3api create-bucket \
  --bucket agent-platform-bootstrap-tfstate \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2 \
  --profile agent_platform_admin

aws s3api put-bucket-versioning \
  --bucket agent-platform-bootstrap-tfstate \
  --versioning-configuration Status=Enabled \
  --profile agent_platform_admin

aws s3api put-bucket-encryption \
  --bucket agent-platform-bootstrap-tfstate \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  --profile agent_platform_admin

aws s3api put-public-access-block \
  --bucket agent-platform-bootstrap-tfstate \
  --public-access-block-configuration \
    'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true' \
  --profile agent_platform_admin
```

### 2. Initialise

```bash
terraform -chdir=terraform/bootstrap init
```

### 3. Prepare variables

Create a gitignored tfvars file (NEVER commit this file):

```bash
# terraform/bootstrap/terraform.bootstrap.tfvars  (gitignored)
account_id  = "707578707169"
owner_email = "benjaminblake94@gmail.com"
```

### 4. Verify the import plan -- STOP if plan shows replace or destroy

The `import {}` blocks in `github_ci_apply.tf` adopt the live role and inline policy without
recreating them. Before applying, verify the plan shows no `replace` or `destroy` for
`aws_iam_role.github_ci_apply` or `aws_iam_role_policy.github_ci_apply`:

```bash
terraform -chdir=terraform/bootstrap plan \
  -var-file=terraform/bootstrap/terraform.bootstrap.tfvars
```

STOP if the plan shows any `destroy` or `replace` for the apply role or its policy. The live
CD apply role must NOT be destroyed -- doing so would break all in-flight CI jobs.

### 5. Apply

```bash
terraform -chdir=terraform/bootstrap apply \
  -var-file=terraform/bootstrap/terraform.bootstrap.tfvars
```

## State-migration ordering (one-time, after first bootstrap apply)

The `aws_iam_role.github_ci_apply` and `aws_iam_role_policy.github_ci_apply` resources currently
live in `terraform/personal/` state. After the bootstrap apply adopts them (the import succeeds),
remove them from the personal state to avoid dual-management:

```bash
# Run AFTER bootstrap apply confirms the import succeeded (no replace/destroy):
terraform -chdir=terraform/personal state rm aws_iam_role.github_ci_apply
terraform -chdir=terraform/personal state rm aws_iam_role_policy.github_ci_apply
```

IMPORTANT: run `state rm` BEFORE the `oidc.tf` removal auto-applies. If `terraform/personal`
still tracks these resources when the `oidc.tf` removal lands in CD, Terraform will plan a destroy.
The ordering is:
1. Bootstrap apply (import succeeds, bootstrap state owns the resources).
2. `terraform state rm` from personal (personal state releases them).
3. `oidc.tf` removal PR merged (CD applies with no destroy, because personal no longer tracks them).

## Ongoing apply runbook

Any change to `github_ci_apply.tf` (e.g. adding a new IAM action to the inline policy or
adjusting the permissions boundary) must be applied manually under `agent_platform_admin`:

```bash
# 1. Plan -- review all IAM diffs carefully.
terraform -chdir=terraform/bootstrap plan \
  -var-file=terraform/bootstrap/terraform.bootstrap.tfvars

# 2. Apply -- only after plan is confirmed safe.
terraform -chdir=terraform/bootstrap apply \
  -var-file=terraform/bootstrap/terraform.bootstrap.tfvars
```

Never add this module to `terraform-apply-sandbox.yml` or any other auto-apply workflow.
