# Handoff: Apply ducklake-lambda-runtime (T2.17 / CD.33)

```yaml
handoff: ducklake-lambda-runtime-apply
repo: benjamin-blake/agent-platform
branch: claude/intelligent-shannon-SGq6J
head: 95aefc3
tier: T2.17
decisions: [81, 77, 35, 78, 55, 76]
reason: >-
  Apply creates NEW IAM roles + inline policies, which trips the Decision-77 deterministic guard
  (scripts/terraform_apply_guard.py, fail-closed on any IAM/trust change). The change therefore
  routes to the MANUAL agent_platform_admin (PlatformAdmin) path, NOT push-to-main auto-apply.
origin_container: >-
  PlatformDev only -- cannot assume PlatformAdmin (sts:AssumeRole AccessDenied, verified); the
  static user (agent-service-account) is also denied. The origin container structurally cannot apply.
target_profile: agent_platform_admin        # PlatformAdmin: iam:* + admin Lambda + secretsmanager + datalake
terraform_dir: terraform/personal
backend_config: backend-sandbox.hcl         # init -backend-config=backend-sandbox.hcl
var_file: terraform.personal.tfvars         # gitignored; supplies aws_profile + account id + region
state: s3://agent-platform-data-lake/tfstate/personal/sandbox/terraform.tfstate  # eu-west-2, use_lockfile
profile_surfaces:
  backend_state: ambient AWS_PROFILE (no profile pinned in backend-sandbox.hcl) -> export AWS_PROFILE=agent_platform_admin
  provider: var.aws_profile (from terraform.personal.tfvars)
artifacts_staged_s3:                         # current for HEAD; uploaded by the origin session 2026-06-05 22:29Z
  - { key: lambda-packages/ducklake-writer.zip,           bytes: 61705 }
  - { key: lambda-packages/ducklake-reader.zip,           bytes: 50813 }
  - { key: lambda-packages/ducklake-deps-layer.zip,       bytes: 26532100 }
  - { key: lambda-packages/ducklake-extensions-layer.zip, bytes: 34335068 }
plan_expectation: "~13 ADDs, no destroy/replace, no trust-policy diff on platform_admin/platform_dev"
post_deploy_gates: [EC1, EC4, EC6, EC7, EC8, EC10, EC11]   # loud-fail (Decision 55), each stop-and-RCA
order_invariant: apply BEFORE merge (post-merge CD plan is then a no-op; the IAM guard passes on no-op)
pre_merge_cleanup: "git rm this file before opening the PR -- transient handoff, must not land on main"
```

## Why this is handed off

The origin (PlatformDev) container ran the build, review, and `validate`, and pushed the branch
merge-ready. It cannot run the apply: PlatformDev has no `iam:*` and cannot assume `PlatformAdmin`
(verified `AccessDenied`), and no admin profile is configured there. This apply needs
`agent_platform_admin`, which your container has.

## Preconditions (your container)

- `agent_platform_admin` profile configured (PlatformAdmin).
- `terraform/personal/terraform.personal.tfvars` present (gitignored; carries
  `aws_profile = "agent_platform_admin"`, account id, region).
- `terraform` CLI installed.
- `export AWS_PROFILE=agent_platform_admin` (the S3 backend uses ambient creds; the provider uses
  `var.aws_profile` from the tfvars).

## Artifacts are already staged in S3 -- do NOT rebuild

The four zips listed in `artifacts_staged_s3` are current for `95aefc3` (the last commit was a
deploy-profile fix that does not change zip contents). The Terraform resources create the layers and
functions directly from these S3 objects; `source_code_hash` is `try(filemd5(local-zip), null)`, so
the apply succeeds with no local zips. Rebuilding the `ducklake-extensions` layer is the fiddly part
and it is already done -- only re-run `build_lambda --ducklake-only` if you specifically want a
non-null `source_code_hash` for future drift detection. Verify with:

```bash
aws s3 ls s3://agent-platform-data-lake/lambda-packages/ --profile agent_platform_admin | grep duck
```

## Sequence (IAM precedes code -- terraform/CLAUDE.md)

```bash
# 0. checkout + init
export AWS_PROFILE=agent_platform_admin
git fetch origin claude/intelligent-shannon-SGq6J && git checkout claude/intelligent-shannon-SGq6J
terraform -chdir=terraform/personal init -backend-config=backend-sandbox.hcl

# 1. PLAN -> present to the human BEFORE apply (terraform/CLAUDE.md hard rule)
terraform -chdir=terraform/personal plan -var-file=terraform.personal.tfvars -out=ducklake.tfplan

# 2. APPLY (only after the human approves the plan)
terraform -chdir=terraform/personal apply ducklake.tfplan

# 3. DEPLOY code from S3 (activates function code)
bin/venv-python -m scripts.build_lambda --ducklake-only --deploy --profile agent_platform_admin
```

## Plan gate -- what the plan MUST show

~13 pure **ADD**s, no destroy/replace:

- 2 exec roles (`ducklake_writer`, `ducklake_reader`) + their inline runtime policies
  (`DuckLakeWriterRuntime`, `DuckLakeReaderRuntime`)
- 1 new inline policy `DuckLakeBreakGlass` on the **existing** `platform_admin` role (additive)
- 2 layer versions (deps, extensions), 2 CloudWatch log groups, 2 Lambda functions, 2 AWS_IAM
  function URLs, 4 outputs

STOP-and-RCA if:

- any destroy/replace, OR
- any diff to the `platform_admin` / `platform_dev` **trust / assume-role** policy (lockout guard --
  PlatformAdmin is the role you are assuming). The only PlatformAdmin change must be the additive
  `DuckLakeBreakGlass` inline policy.

If the first plan surfaces an `AccessDenied` refresh-read on a new data-plane action, that is the
documented AWS-provider refresh behavior (terraform/CLAUDE.md) -- add it scoped and re-plan; do not
force.

## Post-deploy EC gates (T2.17 -- loud-fail, Decision 55)

Run from the checkout (each gate resolves the Function URL via `terraform -chdir=terraform/personal
output -raw ...`, so `terraform/personal` must be initialized and `AWS_PROFILE` set). Each gate is
stop-and-RCA on failure -- never relax a threshold.

```bash
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-attach      --profile agent_platform_admin  # EC1  ATTACH-in-Lambda over TLS
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-ingress     --profile agent_platform_admin  # EC4  AWS_IAM unsigned=403/signed=200
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-reader      --profile agent_platform_admin  # EC1  closed read-only boundary (write denied)
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-idempotency --profile agent_platform_admin  # EC10 idempotent ULID append
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-partition   --profile agent_platform_admin  # EC6  partition prune
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-inlining    --profile agent_platform_admin  # EC11 inlining disabled
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-loudfail    --profile agent_platform_admin  # EC7  schema/OCC loud-fail
bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn       --profile agent_platform_admin  # EC8  in-region churn / real latency budget
```

Optional independent pre-checks against Neon directly (runnable before the apply -- they hit the
catalog, not the Lambdas): `--attach`, `--churn-gate`, `--restore-drill`.

## PR + merge (Decision 76 web flow) -- apply BEFORE merge

1. Remove this handoff so it does not enter `main`: `git rm docs/handoffs/HANDOFF-ducklake-lambda-runtime-apply.md && git commit`.
2. Open PR `main` <- `claude/intelligent-shannon-SGq6J` via `mcp__github__create_pull_request`.
3. Wait for the fast `--pre` PR tier (event-driven via `subscribe_pr_activity`; end the turn, the
   webhook wakes the session -- do not `sleep`).
4. Squash-merge: `merge_pull_request(merge_method="squash")`.

Ordering rationale: `terraform/personal/**` auto-applies on push-to-main behind the Decision-77
guard, which fails closed on IAM. If you merge first, the post-merge CD apply blocks (safely, no-op).
Apply manually first; after merge the post-merge plan is empty and the guard passes on the no-op,
converging clean.

## Close-out

T2.17 closes once the 8 EC gates are green post-deploy. Update `docs/ROADMAP-PLATFORM.yaml` and
`docs/SESSION_LOG.md`, and file the close-out via `scripts.ops_data_portal` (`file_rec` / `update_rec`;
`update_rec` needs Athena via the `agent_platform` profile). The break-glass catalog-attach surface is
documented in `docs/runbooks/ducklake-catalog-operations.md` (Section 1).
