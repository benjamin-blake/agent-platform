# Terraform — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

Some rules below restate root rules for proximity. Root `CLAUDE.md` is authoritative if they ever drift.

## Hard rules
- **Optional artifacts**: Always wrap `filemd5()` and `file()` calls on optional artifacts with `try()`. Bad: `source_code_hash = filemd5("build/lambda.zip")`. Good: `source_code_hash = try(filemd5("build/lambda.zip"), md5(file("module_file.tf")))`.
- **ASCII tag values**: Plain ASCII hyphens (`-`) only in Lambda tag values. No em dashes — they fail in AWS API serialisation.
- **Plan before apply**: Plans modifying `.tf` files must present `terraform plan` output to the human before any `terraform apply`. Apply model: see `docs/contracts/environment-taxonomy.md` Axis A + Guard classification subsection (sole SoT, Decision 77). Short form: sandbox auto-applies behind the deterministic guard; in-budget IAM inline-policy/attachment UPDATEs on managed boundary-carrying roles now auto-apply (T2.25); trust/destroy/out-of-budget IAM route to gated-apply. SIT/PROD remain human-gated and are future-state. See `planning` skill, Step 4 (Infrastructure Assessment).
- **IAM precedence**: If a change modifies IAM (`*.tf` IAM resources or roles attached to Lambdas), `terraform apply` must precede any Lambda code deploy.

## AWS context
- Region: `eu-west-2`
- Account: personal platform account (ID supplied via gitignored `terraform/personal/terraform.personal.tfvars`; never committed).
- Profile: `agent_platform` (PlatformDev, runtime) for agent operations; `agent_platform_admin` (PlatformAdmin) for provisioning (creates IAM + OIDC).
- Glue database: `agent_platform` (personal module). Retained legacy `.tf` files at the repo root still reference `trading_formulas_db` (artefacts from a prior account; not applied).
- Personal-account infra lives in the isolated `terraform/personal/` root module (own provider + state). Legacy `.tf` files in `terraform/` are retained as architectural-evolution artefacts per CD.21 but no longer applied; only `terraform/personal/` is live.
- The personal account has no SCP restricting IAM users or external OIDC (Decisions 36/37 do not apply to this account). OIDC provider + CI roles are created in `terraform/personal/oidc.tf`.

## Running terraform/personal/ on CC-web (no local machine; vars come from remote state)
**This project runs ONLY on Claude Code on the web. There is no operator local machine.**

**Third-party-provider init is github.com-egress-blocked by default (Decision 119), MIRROR-ENABLED
on a synced admin container (Decision 120):** the CC-web outbound proxy scopes github.com to
repo-scoped API calls, so a stock CC-web session CANNOT `terraform init` `terraform/personal` via a
direct fetch -- the `kislerdm/neon` provider's authentication-checksum fetch permanently 403s on
github.com. `hashicorp/*` providers (releases.hashicorp.com) init fine regardless. Decision 119 named
an S3-backed `provider_installation` `filesystem_mirror` as its reversal mechanism; Decision 120
realized it: `.github/workflows/terraform-provider-mirror-seed.yml` (the sole egress-having actor)
seeds `s3://agent-platform-data-lake/tf-provider-mirror/`, and `bin/setup-cloud-env.sh` syncs it
locally on `INSTALL_TERRAFORM=1` containers, resolving `config/terraform/cc-web.tfrc` and setting
`TF_CLI_CONFIG_FILE` -- gated on a successful, non-empty sync (an empty/stale sync leaves
`TF_CLI_CONFIG_FILE` unset rather than exporting a config that excludes `kislerdm/*` from `direct`
with nothing in the mirror to serve). With that mirror synced, local `terraform init` of
`terraform/personal` succeeds with no github.com fetch (see the "Operator-only / break-glass
(Decision 120)" section below for when this is used).

This RELAXES but does NOT REMOVE the CI-delegation: routine (non-admin) `terraform validate`/`plan`/`apply`
for `terraform/personal` remain CI-mediated and authoritative regardless of any given container's
mirror state -- `validate` via the required `terraform-validate` job (Decision 83); `plan`/`apply` via
the speculative-plan + apply-the-saved-plan pipeline described below (Decision 77 / Decision 92). The
mirror-enabled local-init path exists for the ADMIN container's interactive human-gated apply loop
(IAM/trust/destroy changes that guard-BLOCK the CD pipeline, Decision 94 escape hatch; hand-applied
recovery) -- it is not a general invitation to bypass the CI pipeline for routine changes. See
Decision 119 for the original constraint and Decision 120 for the realized reversal mechanism and its
own reversal conditions (mirror sync ceasing to be maintained falls back to this section's original
CI-delegated posture with no code change required).

`terraform/personal/terraform.personal.tfvars` is **gitignored** (`.gitignore`:
`terraform/**/terraform.personal.tfvars`), so it is NOT in the fresh clone and there is no standalone
`s3://.../terraform.personal.tfvars` object to fetch -- do not go looking for that file. The four
no-default vars (`account_id`, `owner_email`, `platform_dev_external_id`, `platform_admin_external_id`)
are recoverable from the **remote Terraform state in S3**, which IS the source of truth:
- State: `s3://agent-platform-data-lake/tfstate/personal/sandbox/terraform.tfstate` (region `eu-west-2`),
  wired via `terraform -chdir=terraform/personal init -backend-config=backend-sandbox.hcl`.
- The values live as resource attributes in that state: `account_id` in every resource ARN;
  the two ExternalIds in the IAM roles' `assume_role_policy` trust documents (`sts:ExternalId` condition);
  `owner_email` in resource tags / the SNS subscription endpoint. `account_id` is also obtainable from
  `aws sts get-caller-identity`.
- After `init`, recover them with `terraform state show` / a parse of the state JSON, then pass via `-var`
  (or a regenerated, still-gitignored tfvars) for `plan`.
- **Never paste these values into chat, a PR, or any committed file** -- the ExternalIds are AssumeRole
  trust secrets and the account id is shape-blocked by the pre-commit `never-commit` hook.

**Deployment model (Decision 126):** the PR -> CI apply pipeline below is the default, ambient
path. Local/manual apply is operator-only break-glass, not a routine agent action -- see
"Operator-only / break-glass" below. Full intent -> trigger -> recovery wayfinding:
`docs/contracts/deploy-paths.yaml`. Guard classification (what auto-applies vs what blocks) is
authoritative SOLELY in `docs/contracts/environment-taxonomy.md` Axis A + Guard classification
(T2.25 / Decision 92 point 5) -- the table below names the channel, it does not restate that
classification.

| Want | Do | If blocked |
|---|---|---|
| Apply a guard-PASS (non-IAM or in-budget IAM) `terraform/personal` change | Open a PR; CD (`terraform-apply-sandbox.yml`) plans on the PR and applies the SAME reviewed plan.bin at merge (T2.21, no re-plan) | N/A -- this is the primary path |
| Apply an out-of-budget IAM / trust / destroy `terraform/personal` change | Open a PR; CD routes to the `tf-gated-apply` GitHub Environment | Approve in GitHub Actions (benjamin-blake); CD applies the same reviewed plan.bin -- never from a laptop |
| Recover from a red convergence record (failed/refused apply, or drift) | Run `terraform-apply-sandbox` via `workflow_dispatch` acknowledge-and-retry (names the red commit / open rec id) AFTER the `ci-rca` rec is reviewed (Decision 55/72) | Nothing auto-remediates; T2.37 (Reconcile, not yet landed) will be the lower-friction path |
| Apply `terraform/` (legacy hashicorp/*-only roots) or `terraform/github` | Same PR -> CD path where a workflow exists | See "Operator-only / break-glass" below |
| Apply `terraform/bootstrap`, or apply `terraform/personal` by hand (bootstrap, reversing a manual admin change, or a guard-BLOCKed case with no CD path yet) | Operator action only | See "Operator-only / break-glass" below |

**Agents never run terraform apply as a self-directed, routine action; operators may always invoke it directly. The sole agent exception is the human-gated break-glass admin tier below -- an agent may execute `terraform apply` there only after a human has reviewed the plan and explicitly directed it (Decision 126).**

**Sticky + observed (CD.35 / T2.20 Wave 1):** the apply job reads a durable convergence record as
a precondition and refuses on red (never overwrites on refusal), writes the record green/red
(always-run) after apply, and apply failures wire into `ci-rca` -- a later green run can no longer
mask an earlier apply failure. See "Convergence anchor" below for the full mechanism.

**Concurrency tradeoff (correct-by-design):** a gated-apply job pending human approval holds the
`terraform-apply-sandbox` concurrency group (`cancel-in-progress: false`), so later auto-applies queue
behind it. This is intentional: serialisation prevents the saved plan.bin from going stale during the
pending window, and applies must serialise on shared tfstate regardless. Expected cost is low (near-zero
gated frequency). If an approval is abandoned, reject it in the GitHub Actions UI to release the queue.

### Operator-only / break-glass (Decision 120)

NOT the default agent path. Retained -- not deleted -- for bootstrap, reversing a manual admin
change, and the guard-BLOCK / out-of-budget-IAM cases the CD pipeline cannot yet apply on its own
(Decision 94 escape hatch). Its danger is that it is ambient, not that it exists (Decision 126);
it is sequenced for quarantine into a dedicated operator runbook once the T2.37 heal button
(Reconcile) lands and is verified -- T2.41 `depends_on: [T2.37]`, do not remove this path before
its replacement works.

If a human operator wants to apply any change by hand: the CC-web agent supports the iterative
loop `terraform plan` -> PRESENT -> human accepts -> agent runs `terraform apply`. Never apply
without presenting the plan and getting acceptance first (Decision 77). **This loop requires
local `terraform init` to have succeeded.**
- Valid with no proxy dependency for `hashicorp/*`-only roots (`terraform/`, `terraform/github`,
  `terraform/bootstrap`) -- local `terraform init` succeeds unconditionally.
- For `terraform/personal` (third-party `kislerdm/neon` provider): a stock CC-web session CANNOT
  locally init it (Decision 119, direct github.com fetch 403s) -- use the CI-mediated
  speculative-plan + apply-the-saved-plan pipeline instead for routine changes. On an ADMIN
  container with the S3 filesystem_mirror synced (Decision 120 -- `bin/setup-cloud-env.sh` ran
  with `INSTALL_TERRAFORM=1` and the sync succeeded, so `TF_CLI_CONFIG_FILE` is set), local init
  DOES succeed and this loop IS available for `terraform/personal`.
- Recover the four no-default tfvars from remote state / Secrets Manager as described above
  regardless of which init path was used; never paste their values into chat, a PR, or any
  committed file.

**Apply posture (record-backed sandbox CD, CD.35 / T2.20 Wave 1):** sandbox CD auto-apply
(`.github/workflows/terraform-apply-sandbox.yml`; push-to-main touching `terraform/personal/**` auto-applies
behind the guard + subagent plan review). It sources all no-default root-module variables from the
`agent-platform-terraform-personal-tfvars` Secrets Manager secret: the apply role's `SecretsManagerTfvarsRead`
grant fetches the secret body to `terraform.personal.tfvars`, which is passed to `terraform plan` via
`-var-file`. New no-default variables only require updating that secret -- no per-variable workflow edit.
`TF_VAR_aws_profile=""` is the sole remaining env override (blanks the named-profile default so the OIDC
credential env vars take effect).

### Speculative plan + apply-the-saved-plan (CD.35 / T2.21 Wave 2)

Wave 2 closes the review->apply loop: a PR that touches `terraform/personal/**` now gets a
speculative plan (human-readable, guard-verdict-annotated) BEFORE it lands, and at merge the
SAME reviewed plan.bin is applied -- not a re-plan.

**Speculative-plan job** (`speculative-plan` in `terraform-apply-sandbox.yml`):
- Triggers on `pull_request` paths `terraform/personal/**`; same-repo fork-gated (`if: head.repo.full_name == github.repository`).
- Assumes `agent-platform-github-ci-plan` (tfstate-read, tfplan-write; no convergence write, no tfstate write/delete).
- Runs `terraform plan -lock=false` (read-only; the plan role cannot take the S3 native lock).
- Runs the unmodified guard to capture the **PREDICTED** verdict (advisory; the merge-time verdict is authoritative).
- Persists `plan.bin` to `s3://agent-platform-data-lake/tfplan/personal/<pr-head-sha>.bin`.
- Scrubs account_id + ExternalIds from the comment; self-fails if any 12-digit sequence survives (public-repo safety).
- Posts the redacted plan diff + predicted verdict as a PR comment.
- Does NOT add a required status check (Decision 83 / CD.20 -- a required check wedges autonomous fix-merges).

**Apply-the-saved-plan path** (push to main in `apply-sandbox`):
- Resolves the PR head SHA from the merge commit (`gh api .../commits/<sha>/pulls`).
- Fetches `tfplan/personal/<pr-head-sha>.bin` from S3; `terraform show -json` -> plan.json.
- **No re-plan**: if no PR is found or no saved object exists, the step fails closed (exit 1). Recovery is the existing `workflow_dispatch` acknowledge-and-retry (which re-plans fresh -- the only human-reviewed re-plan path).
- Runs the guard against the saved plan's plan.json at merge time (authoritative verdict; **no `continue-on-error`** -- Decision 77 no-TOCTOU preserved).
- Applies `plan.bin` -- the exact artefact reviewed on the PR.
- Convergence record `plan_sha` is set to `sha256(plan.bin)` on the push path; null on `workflow_dispatch` (dispatch uses a fresh plan not persisted to S3).

**`workflow_dispatch` path** (unchanged except gating):
- The `Terraform plan` step is now `if: github.event_name == 'workflow_dispatch'` -- dispatch is the only auto-apply path that re-plans.
- Use dispatch for the acknowledge-and-retry unlatch (naming the red commit or rec-id) OR for out-of-band applies (e.g. rolling back a manual admin change).

**Stale saved plan (fail-closed, Decision 55 / CD.35)**:
- Terraform's native staleness check errors if the saved plan.bin's state serial is stale.
- The apply step exits non-zero -> the always-run convergence record write sets `status=red` -> ci-rca files a `source=ci_rca` rec.
- Recovery: `workflow_dispatch` acknowledge-and-retry (re-plans fresh, human-reviewed). NO silent re-plan-and-apply; the push path has no fallback.

**tfplan/personal/ S3 prefix**:
- `s3://agent-platform-data-lake/tfplan/personal/<pr-head-sha>.bin` -- write-IAM is `github_ci_plan` only; read is `github_ci_apply` via its existing `DataLakeObjectIO` bucket-wide grant.
- Objects are inert once the speculative-plan job is removed; prune optionally.

**Capability split (github_ci_pr vs github_ci_plan)**:
- `github_ci_pr`: athena/iceberg reads, convergence record read, DuckLake invoke. **No tfstate read** (fork-safe; `simulate-principal-policy` returns implicitDeny on `s3:GetObject tfstate/...`).
- `github_ci_plan`: tfstate READ, tfplan WRITE, full refresh-read surface (mirrors apply-role plan-time reads). No convergence write, no tfstate write/delete, no DeleteObject anywhere.
- Fork gating: enforced at the WORKFLOW JOB level (`if: head.repo.full_name == github.repository`) -- NOT the OIDC trust condition. Trust mirrors `github_ci_pr` (pull_request sub). The job gate + read-only policy together give the desired fork isolation.

**Role creation is guard-BLOCKED**:
- `github_ci_plan` is a new IAM role -- the guard exits 2 (IAM_SENSITIVE_TYPES). It lands via `agent_platform_admin` apply BEFORE the first PR that exercises the speculative-plan job. The job's `continue-on-error` on the assume-role step covers the bootstrap window.

### Alarm-only scheduled drift detection (CD.35 Wave 5 / T2.24)

Closes the last convergence gap: an hourly scheduled workflow (`terraform-drift.yml`) detects
out-of-band infra drift without auto-applying.

**Cron cadence:** `17 * * * *` (hourly, offset off the top of the hour).

**Exit-code semantics:**
- `0` -- no change; cycle is clean, no action.
- `2` -- drift (changes detected); see "Drift signal" below.
- `1` -- error; if stderr matches `"Error acquiring the state lock"` it is a lock-held skip
  (an in-flight apply holds the native S3 lock -> exit 0, no alarm, no rec, record untouched).
  Any other `exit 1` is a genuine error: the run fails loudly; no rec is filed and no red flip
  occurs (drift != error).

**Native-lock coexistence:** the drift plan runs `-lock=true -lock-timeout=120s`. The
`github_ci_drift` role has `s3:PutObject + s3:DeleteObject` scoped to the EXACT lock object key
`tfstate/personal/sandbox/terraform.tfstate.tflock` (terraform's conditional-put acquire + delete
release), and NO write on the state object `terraform.tfstate` itself. Serialisation with apply
is via the native S3 lock only -- there is no shared GHA concurrency group between
`terraform-drift` and `terraform-apply-sandbox`.

**Drift signal (ec=2):** on a green->red transition:
1. Merge-write the convergence record red (preserves all existing fields; adds `drift_detected_at`,
   `drift_run_url`, `drift_reason`).
2. File a rec directly via the ops portal: `source=tf_drift`, `priority=High`.

**Dedup -- one red = one signal:** if the record is already red (from a prior drift cycle OR a
failed apply), the workflow logs "already red; not re-alarming" and exits 0. No duplicate rec is
filed. The already-red state folds all concurrent or subsequent drift signals into one open rec
until the apply-dispatch unlatch clears it.

**Drift NEVER writes the record green.** Green is written solely by a converged apply
(`terraform-apply-sandbox`), so a clean drift cycle can never mask a prior apply-failure red.
The convergence writer set is now `{github_ci_apply (Wave 1), github_ci_drift (Wave 5)}`.

**Recovery -- dispatch-ack unlatch:** resolve the drift by running `terraform-apply-sandbox`
via `workflow_dispatch` (naming the red commit or the open rec id in `acknowledge_red_commit`).
A successful apply writes green; close the `tf_drift` rec via the `Resolves:` trailer or
`update_rec` portal call.

**github_ci_drift IAM (least-privilege):** tfstate READ + scoped `.tflock` PutObject/DeleteObject +
`convergence/personal/*` GetObject/PutObject + ducklake-WRITER InvokeFunction/InvokeFunctionUrl
(NOT the reader; Decision 84 closed boundary) + same refresh-time read surface as
`github_ci_plan`. No state-object write, no tfplan, no resource mutation, no IAM write.

**Role creation is guard-BLOCKED (admin-create path -- Decision 98):** `github_ci_drift` is a new
IAM role -- the guard exits 2 (IAM_SENSITIVE_TYPES). The T2.23 authority budget (IAMRoleCreateBounded)
scopes in-budget CreateRole to branch+pr only, so the gated-apply pipeline CANNOT mint a new peer CI
role. The ONLY working create path for `github_ci_drift` is `agent_platform_admin` (-target apply of
`terraform/personal/oidc.tf`). Procedure:
(1) Probe whether `github_ci_plan`'s `IAMCIRolesRead` already includes the drift ARN:
    `aws iam get-role-policy --role-name agent-platform-github-ci-plan --policy-name agent-platform-github-ci-plan --profile agent_platform_admin | python3 -c "import sys,json,urllib.parse; d=json.load(sys.stdin); s=next(x for x in json.loads(urllib.parse.unquote(d['PolicyDocument']))['Statement'] if x.get('Sid')=='IAMCIRolesRead'); print('PRESENT' if any('drift' in r for r in s['Resource']) else 'ABSENT')"`
(2) Always include `aws_iam_role.github_ci_drift` and `aws_iam_role_policy.github_ci_drift`; include
    `-target=aws_iam_role_policy.github_ci_plan` ONLY if the probe returned ABSENT (the failed
    apply may have landed it; a PRESENT result means a no-op target is harmless but not required).
(3) Present the plan to the human (Decision 77), apply under `agent_platform_admin`.
(4) Add the drift ARN to `IAMRolesRead` in `terraform/bootstrap/github_ci_apply.tf`
    (read-only refresh grant; does NOT widen the IAM-WRITE budget) and admin-apply that root
    separately.
(5) Verify global convergence (untargeted `terraform plan -detailed-exitcode` exits 0) BEFORE
    dispatching the acknowledge-and-retry.
The workflow carries `continue-on-error` on the assume-role step to cover the bootstrap window.

**Drift recs vs ci-rca recs:** drift recs use `source=tf_drift` and are filed DIRECTLY via the
ops portal (no ci-rca agent). ci-rca's model is log-RCA over a FAILED CI run; drift is a
state-vs-code delta from a SUCCESSFUL plan (ec=2) and has no failure log to RCA (Decision 72/92).

### Convergence anchor (CD.35 / T2.20 Wave 1)

The server-side anti-masking anchor. All four pieces live in `terraform-apply-sandbox.yml` + `oidc.tf`:

- **Durable record:** `s3://agent-platform-data-lake/convergence/personal/sandbox.json`
  (`{status, commit_sha, run_id, run_url, timestamp, plan_sha}`; `plan_sha` is null until Wave 2 saved
  plans). Its OWN S3 prefix, **outside `tfstate/`**, so the read-only PR role reads it without ever seeing
  tfstate. Write-IAM is the **sanctioned writer set {github_ci_apply, github_ci_drift} among the CI
  roles** -- enforced in `oidc.tf` / `terraform/bootstrap/github_ci_apply.tf` by `ConvergenceRecordWrite`
  on each writer (apply: Wave 1; drift: Wave 5 / T2.24), the explicit `DenyConvergenceRecordWrite` on
  `github_ci_branch` (ci-rca / `agent/*` CI keep read, never write/delete the record), and the PR role's
  read-only `S3ReadConvergenceRecord`. This is the integrity anchor -- a commit status alone is spoofable.
  (The residual admin / `platform_breakglass` write path is not yet IAM-fenced; full privilege-tiering --
  the pipeline's own IAM to a bootstrap root -- landed at Wave 4 / T2.23 (`terraform/bootstrap/`).
  "Unbypassable" is scoped to merge-path CI actors, per CD.35 5.5d.)
- **Red-record refusal = the SOLE hard block.** The apply job's read-precondition refuses (emits the
  distinguishable marker `CONVERGENCE_RED`, exits non-zero, and does **NOT** overwrite the record) when the
  record is red. Unbypassable by any merge-path actor. An **absent** record = first-apply-allowed
  (pass-on-absent); the first apply writes the first record (no human seed -- preserves apply-only write-IAM).
- **Advisory `terraform-converged` PR status (NOT a required check).** A read-only `pull_request` job
  (`github_ci_pr` role, `S3ReadConvergenceRecord`) posts it for visibility. Deliberately advisory: a required
  check would wedge the autonomous fix-merge once a record is red, or be admin-bypassed anyway
  (`main-protection` `strict=false`, admin `bypass_mode=always`, Decision 83). Do **not** add it to the
  ruleset's `required_status_checks`.
- **Dispatch-ack unlatch = the ONLY way to clear red.** A red record clears **only** when an apply from a
  `workflow_dispatch` acknowledge-and-retry run succeeds; its `acknowledge_red_commit` input names the red
  commit SHA (or the open rec id). A plain push never clears red (auto-allow-descendants is rejected -- on
  linear-history main every commit is a descendant). The dispatch actor + input are the audit trail; the
  agent may dispatch via the GitHub MCP actions trigger **after** the `ci-rca` rec is reviewed (Decision
  55/72) -- nothing auto-remediates. Refusals-while-red dedupe to the one open red-record rec (ci-rca anchors
  on the record's commit). Serialisation is the existing workflow `concurrency` group
  (`cancel-in-progress: false`).

## Out-of-band IAM grants (drift -- not managed by this module)

The `PlatformDev` and `PlatformAdmin` roles pre-exist the module and are now BOTH codified (see the
CODIFIED bullets below). The only item still applied out-of-band via the `platform_breakglass` IAM
user (full admin) and NOT codified in `terraform/personal/` is the redundant `AgentPlatformRuntime`
inline policy (slated for removal) -- re-creating infra elsewhere will not restore it; reapply manually if needed.

- **`PlatformAdmin` + `PlatformDataLakeProvisioning` (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`;
  datalake policy narrowed to least-privilege 2026-05-30):**
  `aws_iam_role.platform_admin` (import ID `PlatformAdmin`, `max_session_duration = 3600`) plus its two inline
  policies -- `aws_iam_role_policy.platform_admin_ops` (`AdminOps`: identity admin -- `iam:*` + admin Lambda +
  secretsmanager) and `aws_iam_role_policy.platform_admin_datalake` (`PlatformDataLakeProvisioning`: the data-plane
  rights AdminOps lacks). The datalake grant is required so `terraform apply` under `agent_platform_admin` can
  provision + manage the data lake, workgroup, Glue DB, and counters table. It is ENUMERATED least-privilege (no
  `glue:*`/`athena:*`/`s3:*`/`dynamodb:*` service wildcards; no legacy `bblake-platform-*` ARNs), scoped to the
  agent-platform data lake: Glue actions on the catalog + `agent_platform` DB + its tables; Athena manage on the
  `agent-platform-production` workgroup (+ account-level query-status reads that don't support resource scoping);
  `s3` bucket-config + object IO on `agent-platform-data-lake` only; DynamoDB TABLE-level actions (NOT item-level
  -- counter VALUES are PlatformDev runtime's domain) on `agent-platform-counters` only. The action set mirrors the
  `github_ci_apply` CI role's data-plane statements. NOTE: the set includes refresh-time READS the AWS provider
  (v5.100) issues on every `plan` -- `glue:GetTags`, `dynamodb:DescribeContinuousBackups`/`DescribeTimeToLive` --
  which apply does not exercise but `plan` (and therefore CD) requires; do not prune them as "unused". IMPORT the
  role before apply; the trust policy MUST show NO change in `plan` (lockout guard -- this is the role the apply
  assumes). If a future module addition needs a new data-plane action, expect the FIRST `plan` after the apply to
  surface it as an AccessDenied refresh read; add it (scoped) and re-apply with `-refresh=false` (state is fresh
  from the apply), then a full `plan` converges.
- **PlatformDev runtime grant (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`):** the
  `agent_platform` (PlatformDev) runtime role is now Terraform-managed. `aws_iam_role.platform_dev`
  (imported, ID `PlatformDev`) sets `max_session_duration = 36000` (was 3600 -- the 3600 max blocked
  CC-web's 10h unattended sessions); `aws_iam_role_policy.platform_dev_runtime` codifies the `DailyOps`
  inline policy (Athena query on `agent-platform-production`; S3 read-write on `agent-platform-data-lake`;
  DynamoDB on `agent-platform-counters`; Glue read + table mutations). Applied via `platform_breakglass`
  with `-target` on the two role resources (the unrelated `null_resource` Athena-DDL replacements from a
  later main.tf edit were deliberately excluded). Trust policy verified unchanged at apply time.
  Reconciliation at import time (the role was NOT permissionless, contrary to the prior PENDING note):
    - A stale pre-rename `DailyOps` (dead `bblake-*` targets + a live Bedrock invoke-model grant) already
      existed and was imported; the apply overwrote it with the agent-platform grant. Net live capability
      dropped: the Bedrock invoke-model grant (treated as unused -- `AgentPlatformRuntime` never granted Bedrock
      and ops works without it; no Bedrock consumer was found for this role, but no exhaustive audit was run).
    - A separate out-of-band `AgentPlatformRuntime` inline policy already granted the same agent-platform
      ops set, so ops calls succeeded both before and after this change. It is now a redundant duplicate of
      the codified `DailyOps`. FOLLOW-UP: remove `AgentPlatformRuntime` via `platform_breakglass`.

Follow-up (remaining): remove the now-redundant `AgentPlatformRuntime` inline policy via `platform_breakglass`
(its grants are fully covered by the codified `DailyOps`). A formal Decision recording the static-key credential
model (PlatformDev + PlatformAdmin codification, Decision-57 SSO-recovery supersession) is filed via the ops portal.

- **DuckLake IAM read-wildcard closure (PLAN-terraform-sandbox-convergence-closure, 2026-06-18; SSM List* completion PLAN-ci-apply-ssm-list-closure rec-2276, 2026-06-18, `github_ci_apply` inline policy, out-of-band admin apply):**
  The iterative-discovery anti-pattern for `github_ci_apply` refresh-READ grants (rec-2223 round, rec-2251 round) is
  permanently closed. Eight READ-only Sids use per-service wildcards (`Describe*/List*` or `Get*/List*`) scoped to the
  same resource ARNs as before: `CloudWatchLogsRead`, `LambdaRead`, `EventBridgeRead`, `SNSRead`, `CloudWatchAlarmsRead`,
  `SecretsManagerNeonAPIKeyRead`, `SecretsManagerTfvarsRead`, `SSMParameterRead`. WRITE Sids (`EventBridgeWrite`,
  `CloudWatchAlarmsWrite`, `LambdaPermissionWrite`, `SSMFeatureFlagsManage`, `ConvergenceRecordWrite`,
  `IAMRoleReconcile`, `OIDCProviderReconcile`) remain enumerated and ARN-scoped (no wildcards). IAM read Sids
  (`IAMRolesRead`) remain enumerated per Decision 35 (policy defined in `terraform/bootstrap/github_ci_apply.tf`).
  `SSMParameterRead` grants `ssm:Get*/Describe*/List*` scoped to `parameter/agent-platform/*` (the original
  closure shipped `Get*/Describe*`; `ssm:ListTagsForResource` is a `List*`-class action the AWS provider calls
  on every `aws_ssm_parameter` refresh, surfaced by rec-2276 as a missed gap on the first apply-sandbox run
  under the `github_ci_apply` CI identity -- the SSM List* completion round landed with rec-2276).
  All eight READ Sids now use per-service wildcards covering all refresh-read actions (`Describe*/List*` or
  `Get*/List*` for seven Sids; `Get*/Describe*/List*` for `SSMParameterRead`); no further iterative-discovery
  rounds are expected.

## Athena workgroup rules
- `agent-platform-production` (engine v3) — OPTIMIZE, MERGE writes, all production queries (personal module).
- `primary` (engine v2, default) — **do not use** for Iceberg DML or VACUUM. v2 doesn't support full Iceberg semantics.

## Athena/Iceberg DDL gotchas
- `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS`. Issue one column per statement; ignore "already exists" errors.
- `CREATE TABLE IF NOT EXISTS` does not update TBLPROPERTIES on an existing table. Use `ALTER TABLE SET TBLPROPERTIES` instead.
- `VACUUM` requires engine v3. Always use `WorkGroup='agent-platform-production'`.
- Iceberg integer promotion: prior writes may have promoted `int` → `bigint`. Re-declaring as `int` fails ("Cannot change column type: long -> int"). Detect and honour existing promoted types.

## Lambda interaction
- Lambda zipped deployment limit ~262144000 bytes. `scripts/build_lambda.py` asserts this.
- Lambda runtime: Python 3.12.
- Layer: `AWSSDKPandas-Python312:22` (managed) + extras layer.

For Lambda deployment workflow rules, see `src/data/handlers/CLAUDE.md`.
