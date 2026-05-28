# Plan

## Intent
Move CI execution from GitHub-hosted runners (consuming the 2000 min/month free tier) to a
permanent self-hosted EC2 runner inside the project's existing AWS estate. Eliminates the monthly
minute-cap exhaustion that forces branch-protection to remain disabled, and unblocks
cc-scheduled-agents Phase 4 (daily cron auto-merge PRs) by removing per-run GitHub Actions billing.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/self-hosted-runner

## Phase
Platform (parallel with Phase 2 schema backfill)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `terraform/ec2_runner.tf` | Create | EC2 t3.small, IAM role + instance profile, egress-only security group |
| `.github/workflows/ci.yml` | Modify | Switch both jobs from `ubuntu-latest` to `[self-hosted, linux]` |
| `docs/DECISIONS.md` | Modify | Decision 68: self-hosted runner as canonical CI execution environment |
| `CLAUDE.md` | Modify | Runner ops runbook (start/stop, re-registration, health check) |
| `docs/PROJECT_CONTEXT.md` | Modify | Infrastructure table and gotchas section updated |

## Bundled Recommendations
- **rec-598** (Stand up self-hosted GitHub Actions runner on EC2 with SSO substrate) -- this plan
  fulfils it. Close on completion via `python -m scripts.ops_data_portal --close rec-598 ...`.

## Infrastructure Dependencies

### New resources
| Resource | Type | Purpose |
|----------|------|---------|
| `aws_security_group.github_runner` | SG | Egress HTTPS-only; no inbound rules |
| `aws_iam_role.github_runner` | IAM Role | EC2 service principal; CI AWS access |
| `aws_iam_policy.github_runner_ci` | IAM Policy | Least-privilege: Athena/S3/DynamoDB/Glue |
| `aws_iam_role_policy_attachment.github_runner_ci` | Attachment | Binds policy to role |
| `aws_iam_instance_profile.github_runner` | Instance Profile | Attaches role to EC2 |
| `aws_instance.github_runner` | EC2 t3.small | Runner process host; Ubuntu 22.04 LTS |

### IAM permissions (least-privilege)
| Service | Actions | Reason |
|---------|---------|--------|
| Athena | `StartQueryExecution`, `GetQueryExecution`, `GetQueryResults`, `ListWorkGroups` | DQ runner, preflight Athena queries |
| S3 | `GetObject`, `PutObject` on log bucket + Athena results prefix | Log reads, query result staging |
| DynamoDB | `GetItem`, `Query`, `Scan` on `agent-platform-*` tables | ID allocation, rec/decision reads |
| Glue | `GetDatabase`, `GetTable`, `GetPartitions` | Iceberg catalog reads |

### Timing constraints
- `terraform plan` output must be presented to the human and approved before `terraform apply`.
- `terraform apply` is non-automatable: human executes and approves.
- Runner binary installation (`config.sh`) requires a GitHub registration token that expires in
  60 minutes. Human must complete installation within that window after Terraform apply.
- ci.yml change must not be merged to main until the runner is confirmed Idle in GitHub Settings.

## Acceptance Criteria
- [ ] `terraform plan` reports `Plan: 6 to add, 0 to change, 0 to destroy`
- [ ] EC2 instance `agent-platform-runner` appears running in eu-west-2 console
- [ ] Runner appears as `online` in GitHub Settings → Actions → Runners
- [ ] A CI run on this branch is picked up by the self-hosted runner (job log confirms runner name)
- [ ] `validate.py --ci` passes on the runner (no ProfileNotFound; credentials resolve via instance metadata delegation)
- [ ] Decision 68 committed to `docs/DECISIONS.md`
- [ ] Runner ops runbook committed to `CLAUDE.md`
- [ ] `docs/PROJECT_CONTEXT.md` infrastructure section updated
- [ ] rec-598 closed as resolved

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | [pre-deploy] | Terraform plan diff correct | `cd terraform && terraform plan 2>&1 \| grep "^Plan:"` | `Plan: 6 to add, 0 to change, 0 to destroy` | Wrong count -- review ec2_runner.tf for missing or extra resources |
| 2 | [post-deploy] | EC2 instance running | `aws ec2 describe-instances --filters "Name=tag:Name,Values=agent-platform-runner" --profile company-aws-profile --query "Reservations[].Instances[].State.Name" --output text` | `running` | Not running -- check EC2 console for launch errors; review AMI data source |
| 3 | [post-deploy] | AWS credentials resolve on EC2 | SSH to instance: `aws sts get-caller-identity --profile company-aws-profile` | Returns JSON with correct account ID | ProfileNotFound -- verify `~/.aws/config` `Ec2InstanceMetadata` delegation block was written by user_data |
| 4 | [post-deploy] | Runner registered and Idle | `gh api repos/{owner}/{repo}/actions/runners --jq '.runners[] \| select(.name=="agent-platform-runner") \| .status'` | `online` | Not listed -- re-run `config.sh` with a fresh token and restart systemd service |
| 5 | [post-deploy] | CI job routes to self-hosted runner | `git commit --allow-empty -m "ci: verify self-hosted runner routing" && git push && sleep 30 && gh run list --branch agent/self-hosted-runner --limit 1 --json databaseId --jq '.[0].databaseId' \| xargs gh run view --log \| grep "runner.name"` | Output contains `agent-platform-runner` | Still showing ubuntu-latest -- verify ci.yml runs-on change is committed to this branch |
| 6 | [post-deploy] | Full validate.py --ci passes | `gh run list --branch agent/self-hosted-runner --limit 1 --json conclusion,status --jq '.[0]'` | `{"conclusion":"success","status":"completed"}` | Failure -- fetch logs with `gh run view --log-failed` and diagnose; AccessDenied in logs means missing IAM action; add to policy and re-plan |

## Constraints
- No STRATEGIC plans (Decision 67). This plan is IMPLEMENTATION.
- Lambda deployment deferred (Decision 67). This plan does not touch Lambda-packaged files.
- Do not attach `AdministratorAccess` or any AWS-managed broad policy to the instance role.
  Least-privilege only; extend the policy only when a new CI check requires it.
- No inbound security group rules. The runner dials out to `api.github.com` (HTTPS); no inbound
  port is needed or acceptable.
- Egress restricted to TCP 443 only; do not add `0.0.0.0/0` all-traffic egress.
- No OIDC federation (SCP blocks per Decision 36). IAM instance role with `Ec2InstanceMetadata`
  credential source is the correct pattern.
- **Warm runner is explicitly out of scope.** Build cold-start only (full checkout + pip install
  per job). The persistent venv/workspace pattern carries a non-trivial state-drift risk
  (corrupted or stale venv causes false-green CI) and requires a dedicated risk assessment and
  drift-enforcement plan before implementation.

## Context
- **Decision 36 (AWS Auth):** No IAM users or OIDC. This plan uses EC2 instance role with
  `Ec2InstanceMetadata` credential delegation -- within the spirit of Decision 36 (avoids OIDC
  federation, avoids IAM users). The runner is infrastructure, not an automation agent.
- **Decision 37 (Scheduled agents via Lambda):** The runner unblocks cc-scheduled-agents Phase 4
  (daily cron) which was blocked by per-run GitHub Actions billing. Each cron-fired agent PR/merge
  incurs ~23 CI minutes; on a self-hosted runner those minutes are free.
- **Decision 67 (Deferred):** EC2 runner is not Lambda-packaged. This plan is unaffected.
- **rec-598 origin:** This rec was filed as a prerequisite for the two-tier validation migration
  (Decision 60) and for cc-scheduled-agents Phase 4. Both unblocked upon runner registration.
- **SCD data transfer boundary:** Code execution moves to the project's EC2 instance. AWS
  credentials never leave the instance (instance metadata, no env var injection into GitHub).
  Residual: job logs (stdout/stderr of CI steps) stream to GitHub's log storage. This is
  equivalent to the current GitHub-hosted runner posture for log content; what changes is WHERE
  code executes. Ensure tests never print classified data values (symbol lists, strategy names)
  to keep log content non-classified.
- **Warm runner (future intent, not built here):** The intended long-term evolution is a
  pre-warmed runner with pip dependencies pre-installed and a persistent checkout. This eliminates
  cold-start overhead (~2 min per job for pip install). Before implementing: a dedicated plan
  covering (a) hash-gating the venv against `requirements.txt` on every job pickup to prevent
  stale-dependency false-greens, (b) workspace reset on branch switch, and (c) concurrency-safe
  workspace locking. Record this intent in Decision 68 as a named future phase.
- **cc-scheduled-agents Phase 4:** Unblocked once runner is Idle. Phase 4 planning session can
  begin immediately after verification step 6 passes.
- **Branch protection (consequence):** Once the runner is stable and CI is reliably green, branch
  protection (`required_status_checks`) can be enabled on `main`. This is a follow-up action for
  the human after a 1-week runner stability observation window.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently on `agent/self-hosted-runner`)
- [ ] `docs/PROJECT_CONTEXT.md` read in full
- [ ] `docs/DECISIONS.md` read (latest: Decision 67; next: Decision 68)
- [ ] `terraform/variables.tf` read (region: `eu-west-2`, profile: `company-aws-profile`,
  project_name: `agent-platform`)
- [ ] `terraform/main.tf` read (provider `aws ~> 5.0`; `default_tags` confirmed)
- [ ] `CLAUDE.md` Lambda runbook section read (model for runner runbook structure)
- [ ] IAM actions enumerated from `validate.py --ci` code paths requiring AWS

## Ordered Execution Steps

1. **Write `terraform/ec2_runner.tf`**
   - `data "aws_ami" "ubuntu_22_04"`: latest Ubuntu 22.04 LTS (Canonical owner
     `099720109477`, `hvm-ssd`, `ubuntu-jammy-22.04-amd64-server-*`) in `eu-west-2`.
   - `aws_security_group.github_runner`: no ingress rules; egress TCP 443 to `0.0.0.0/0`
     (GitHub API + S3 + AWS service endpoints).
   - `aws_iam_role.github_runner`: assume policy for `ec2.amazonaws.com`.
   - `aws_iam_policy.github_runner_ci`: inline JSON with least-privilege actions listed in the
     Infrastructure Dependencies table above. Scope S3 and DynamoDB actions to
     `agent-platform-*` resource ARNs.
   - `aws_iam_role_policy_attachment.github_runner_ci`: attach policy to role.
   - `aws_iam_instance_profile.github_runner`: wraps the role for EC2 attachment.
   - `aws_instance.github_runner`: `t3.small`, AMI from data source, `eu-west-2`,
     `iam_instance_profile = aws_iam_instance_profile.github_runner.name`,
     `vpc_security_group_ids`, `associate_public_ip_address = true`.
     `user_data` script: installs `git`, `curl`, `unzip`, `python3.12`, `python3-pip`,
     `jq`; creates `/home/ubuntu/actions-runner` directory; writes
     `/home/ubuntu/.aws/config` with `[profile company-aws-profile]` block delegating to
     `credential_source = Ec2InstanceMetadata`. Does NOT install the runner binary
     (registration token expires; human completes this step).
   - Tags: `Name = "agent-platform-runner"`, `Purpose = "GitHub Actions self-hosted runner"`,
     plus provider `default_tags` (Project, Environment, ManagedBy, Owner, CostCenter).

2. **Modify `.github/workflows/ci.yml`**
   - Change `validate-python` job: `runs-on: ubuntu-latest` → `runs-on: [self-hosted, linux]`.
   - Change `terraform-validate` job: same substitution.
   - Add comment above each: `# Self-hosted runner (see Decision 68 and CLAUDE.md runbook).`

3. **Write Decision 68 to `docs/DECISIONS.md`**
   Insert as the new leading decision (above Decision 67). Content:
   - Problem: 2000 min/month free tier exhausted at current PR velocity; branch protection
     disabled as workaround; cc-scheduled-agents Phase 4 blocked.
   - Decision: EC2 self-hosted runner (`t3.small`, Ubuntu 22.04, `eu-west-2`) as canonical
     CI execution environment. IAM instance role with `Ec2InstanceMetadata` credential
     delegation replaces SSO profile requirement in CI.
   - Cold-start only for Phase 1. Warm runner is a named future phase requiring its own
     risk assessment (hash-gate venv, workspace reset, concurrency locking).
   - SCD data transfer boundary documented (code execution on EC2; log streaming to GitHub
     is the residual risk; classified data must not appear in test output).
   - Consequences: branch protection can be re-enabled after 1-week stability window;
     cc-scheduled-agents Phase 4 unblocked.
   - Status: Decided 2026-05-08.

4. **Write runner ops runbook to `CLAUDE.md`**
   Add section "Self-hosted GitHub Actions runner" after the Lambda runbook. Cover:
   - Start/stop: `sudo systemctl start/stop actions.runner.*`
   - Check status: `sudo systemctl status actions.runner.*`
   - Re-registration (token expires): stop service, run `./config.sh remove`, generate new
     token from GitHub Settings → Actions → Runners → New self-hosted runner, run
     `./config.sh --url ... --token ...`, restart service.
   - Health check: `gh api repos/{owner}/{repo}/actions/runners --jq '.runners[]'`
   - IAM permission boundary: do not extend beyond the policy in `terraform/ec2_runner.tf`.
     If a new CI check needs AWS access, add the specific action to the policy and run
     `terraform apply`.
   - Warm runner future intent: see Decision 68. Do not add persistent venv caching without
     the drift-enforcement plan in place.
   - SSH access: EC2 instance is in default VPC, public IP. Key pair name is in
     `terraform/ec2_runner.tf`. Use `ssh -i ~/.ssh/agent-platform.pem ubuntu@<public-ip>`.
   - The `~/.aws/config` credential delegation block (written by user_data, must be present
     for `boto3.Session(profile_name="company-aws-profile")` to resolve via instance metadata):
     ```ini
     [profile company-aws-profile]
     credential_source = Ec2InstanceMetadata
     region = eu-west-2
     ```
     If this block is absent (user_data failure), recreate it manually on the EC2 instance
     and re-run verification step 3.

5. **Update `docs/PROJECT_CONTEXT.md`**
   - Add row to infrastructure table: `GitHub Actions runner | EC2 t3.small, eu-west-2 |
     terraform/ec2_runner.tf`.
   - Add gotcha: "Self-hosted runner credential pattern: the runner uses an IAM instance role
     delegated via `~/.aws/config` `credential_source = Ec2InstanceMetadata`. Tests that
     call `boto3.Session(profile_name='company-aws-profile')` work on the runner without code
     changes. The SSO profile on the runner is a local alias to instance metadata, not a real
     SSO session."
   - Add note to scheduled agents row: "cc-scheduled-agents Phase 4 (cron) requires the
     self-hosted runner (Decision 68) to avoid per-run GitHub Actions billing."

6. **Execute Verification Plan step 1** -- run `terraform plan`, capture output, present to
   human. Wait for explicit approval before noting plan is ready for human execution.

7. **DEFERRED (human action):** Execute `terraform apply`. Then SSH to EC2 and complete
   runner registration following the CLAUDE.md runbook written in step 4. Specifically:
   ```bash
   cd ~/actions-runner
   curl -o actions-runner-linux-x64.tar.gz -L \
     https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64-*.tar.gz
   tar xzf ./actions-runner-linux-x64.tar.gz
   ./config.sh --url https://github.com/{owner}/{repo} --token <TOKEN_FROM_GITHUB_SETTINGS>
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
   Token is obtained from: GitHub repo → Settings → Actions → Runners → New self-hosted runner.
   Token expires in 60 minutes; complete within that window.

8. **Execute Verification Plan steps 2-6** -- confirm runner Idle, credentials resolve, CI
   routes correctly, `validate.py --ci` passes green.

9. **Close rec-598:**
   ```bash
   python -m scripts.ops_data_portal --close rec-598 \
     --resolution "Fulfilled by PLAN-self-hosted-runner. EC2 t3.small runner registered in eu-west-2."
   ```

10. Report: what was built, terraform output summary, runner status, CI pass confirmation.
    Note: branch protection enablement is a follow-up human action after 1-week stability window.
