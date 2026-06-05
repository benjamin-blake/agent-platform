# Plan

## Intent
Retire the now-redundant T2.16 RDS PostgreSQL DuckLake catalog (the largest live AWS cost line, ~$12-15/mo)
and prune the transitional IAM grants that existed only to support it, completing the T2.16b RDS->Neon catalog
migration and returning the Decision-77 sandbox terraform pipeline to a clean-green push run. This is a
self-improving-platform cost + simplicity win (NS.3) taken while the catalog's blast radius is provably zero
(nothing consumes it until the T2.19 cutover; live ops remain Iceberg/Athena).

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (live RDS destroy + live DuckDB-against-Neon ATTACH/churn proof + live IAM apply changes + a clean-green
sandbox push-run verification + ops-portal rec dispositions; steps tagged `[pre-destroy]` / `[post-destroy]`
/ `[post-prune]` / `[post-merge]`).

## Plan Path
docs/plans/PLAN-ducklake-rds-retirement.md

## Phase
Platform roadmap **T2.16b** ("DuckLake catalog migration to Neon + RDS retirement", `status: in_progress`,
effort M). This plan executes **Phase 2** (the RDS retirement + IAM prune). Phase 0+1 (Neon provider, project,
scoped role/database, DSN secret, Neon-aware apply guard, smoke-test CLI, roadmap posture revision) shipped in
PRs #72/#73 and were stabilised through three sandbox-pipeline grant rounds (#75/#76/#77). Enacts candidate
decision **CD.34** (`state: pending`; ratification as Decision 82 is deferred -- see Context). Authored by
`docs/REPORT-ducklake-catalog-neon-migration.md` and the prior `docs/plans/PLAN-ducklake-catalog-neon-migration-impl.md`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ducklake_neon_smoke_test.py` | Invoke (no edit) | Run `--attach` + `--churn-gate` against the live Neon DSN as the **hard pre-destroy proof gate**. Existing CLI from Phase 1. |
| `terraform/personal/rds_ducklake_catalog.tf` | Delete | Destroy `aws_db_instance.ducklake_catalog` + subnet group + SG (+ ingress/egress rules) + parameter group + the 2 default-VPC data sources + the 5 outputs. Two-step (`deletion_protection=false` THEN destroy); final snapshot `ducklake-catalog-final-snapshot` retained as the sole recovery artifact. Closes rec-2062/2068/2069; dispositions rec-2064. |
| `terraform/personal/variables.tf` | Modify | Remove the 3 now-unreferenced RDS vars (`ducklake_catalog_ingress_cidrs`, `ducklake_catalog_db_name`, `ducklake_catalog_instance_class`). KEEP `neon_region_id` + `neon_org_id` (Neon stack). |
| `terraform/personal/oidc.tf` | Modify | Remove the 5 PRUNE-marked transitional `aws_iam_role_policy.github_ci_apply` Sids (`RDSDuckLakeCatalogRead`, `RDSDuckLakeCatalogParameterGroupModify`, `EC2NetworkingDescribeForRDS`, `KMSDescribeForRDS`, `SecretsManagerRDSMasterSecretRead`). KEEP `IAMPlatformRolesRead` (permanent) + `SecretsManagerDuckLakeNeonDSN` + `SecretsManagerNeonAPIKeyRead` (Neon). Closes rec-2078. **Sequenced after the destroy** -- these Sids are on the CI auto-apply role (the sandbox push-plan), NOT the manual-destroy role, so they do not gate the destroy; they must stay only until the RDS is out of state + main code, else the automated push-plan reds on RDS refresh-reads. |
| `terraform/personal/platform_roles.tf` | Modify | Remove the entire `aws_iam_role_policy.platform_admin_ducklake_catalog` (`PlatformDuckLakeCatalogProvisioning`: RDS/EC2/KMS/snapshot/secret-tag grant). Closes rec-2065/2066. **Sequenced AFTER the destroy** -- the destroy consumes `rds:DeleteDBInstance` from this policy. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Flip T2.16b `status: in_progress` -> `complete` + update `progress_note` to record Phase 2 (Neon proven, RDS retired, IAM pruned, rec dispositions). No `DECISIONS.md` edit (CD.34 stays pending; ratification deferred). |
| `logs/.recommendations-log.jsonl` (via `scripts/ops_data_portal.py`) | Disposition (portal only) | Close rec-2062/2064/2065/2066/2068/2069/2078/2080; WONTFIX rec-2063; close rec-2067 (RDS SG gone) + re-file a new rec for the Neon public-endpoint egress posture; leave rec-2079 open (follow-on). Single-Portal invariant -- never edit the JSONL directly. |

## Bundled Recommendations
Dispositioned by this retirement (not separately implemented):
- **rec-2062 / rec-2068 / rec-2069** -- close by `rds_ducklake_catalog.tf` deletion (RDS instance gone; the
  hardcoded identifier / perf-insights / master-username findings are moot).
- **rec-2064** -- close/disposition: `engine_version="16"` major-only is moot once the instance is destroyed;
  the Neon DR primitive is a logical `pg_dump`, which tolerates Postgres-minor drift on restore.
- **rec-2065 / rec-2066** -- close by `PlatformDuckLakeCatalogProvisioning` removal (the `snapshot:*` wildcard
  and `kms:DescribeKey/CreateGrant` Resource concerns vanish with the policy).
- **rec-2078** -- close: this plan IS the prune of all 5 transitional `github_ci_apply` Sids.
- **rec-2080** -- close: the live RDS master-secret ARN
  (`...:secret:rds!db-eed12c7d-...`) is confirmed to match the `secret:rds!*` wildcard (human-verified during
  the prior `/implement` session); the VP-9-ARN-annotation question is answered, and the Sid is being pruned anyway.
- **rec-2063** -- WONTFIX for this retirement: `delete_automated_backups=true` wipes PITR, but the catalog is
  provably unused and the single final snapshot loses nothing. (The `=false` flip would apply only if retirement
  were ever deferred past the T2.19 cutover.)
- **rec-2067** -- close (the RDS SG with `0.0.0.0/0 -1` egress is deleted) AND **re-file** a new rec capturing
  the egress-least-privilege concern as it transfers to the Neon public-endpoint posture (dynamic egress; not
  silently closed).
- **rec-2079** -- leave OPEN (post-Phase-2 cleanup: consolidate `IAMRoleReconcile` + `IAMPlatformRolesRead`
  Sids in `github_ci_apply`). Out of scope here; noted as a follow-on.

## Infrastructure Dependencies
**Destroyed (Phase 2, human-gated manual `agent_platform_admin` apply -- the Decision-77 guard fail-closes on a
`delete`, so this CANNOT auto-apply):** `aws_db_instance.ducklake_catalog` (final snapshot retained),
`aws_db_subnet_group.ducklake_catalog`, `aws_security_group.ducklake_catalog` + its ingress/egress rules,
`aws_db_parameter_group.ducklake_catalog_force_ssl`, the `data.aws_vpc.default` + `data.aws_subnets.default`
data sources, the 5 `ducklake_catalog_*` outputs, the `PlatformDuckLakeCatalogProvisioning` inline policy, and
the 5 transitional `github_ci_apply` Sids.

**Reference sweep (clean):** `grep` confirms no other `.tf`, `.py`, `.yaml`, or `.md` (outside the RDS file and
historical plan/report docs) references the RDS resources, the 5 outputs, the data sources, or the 3 vars. The
sole external hit is the `ducklake_catalog_db_name` variable *declaration* in `variables.tf` (itself removed).
Nothing is stranded.

**Apply path + sequencing (Decision 35 + Decision 77) -- ORDER IS LOAD-BEARING:**
1. **Pre-destroy proof gate (hard-stop):** `--attach` + `--churn-gate` against live Neon. If either fails, STOP
   and file a rec; do NOT destroy the safety net (Decision 55).
2. **RDS destroy** (manual `agent_platform_admin` = the **PlatformAdmin** role): the destroy is planned and run
   under PlatformAdmin, whose `PlatformDuckLakeCatalogProvisioning` policy holds `rds:DeleteDBInstance` plus the
   RDS/EC2/KMS describes needed to refresh + plan it -- so that policy is therefore still present. RDS leaves
   shared S3 state.
3. **IAM prune AFTER the destroy** (manual `agent_platform_admin`): remove the 5 `github_ci_apply` Sids and the
   `PlatformDuckLakeCatalogProvisioning` policy. **Two distinct roles, two distinct reasons -- do not conflate:**
   (i) the `PlatformDuckLakeCatalogProvisioning` removal MUST follow the destroy because the destroy (run as
   PlatformAdmin) consumes `rds:DeleteDBInstance` FROM that policy -- removing it first AccessDenies the destroy
   (this is the genuine "#75 in reverse" dependency, and the only strictly load-bearing IAM ordering).
   (ii) the 5 `github_ci_apply` Sids are on the CI auto-apply role (the sandbox push-plan), NOT the
   manual-destroy role, so they are irrelevant to the destroy's success; they must stay only until the RDS is
   out of state + out of main's code, because while main still declares the RDS the automated push-plan
   refresh-reads it and would AccessDenied (the clean-green-push reason). Net order is unchanged: proof ->
   destroy -> prune both -> merge.
4. **Clean merge:** with shared state already matching the branch code, the post-merge sandbox push plan is a
   no-op -> guard exit 0 -> CI green on the first push (no manual re-dispatch).

**Why branch-first manual apply (the CI-green technique):** both the RDS destroy (a `delete`) and the IAM
changes (CI-role/IAM-sensitive) trip the Decision-77 guard's fail-closed gate, so the sandbox pipeline cannot
auto-apply them. Applying them manually on the branch BEFORE merge means the post-merge push run sees no diff.
This is precisely why PRs #75-#77 reds-then-dispatch-succeeded: the role cannot apply its own grant through the
guarded pipeline. The deeper structural fix (so grants never need a manual apply) is deferred to the
post-retrospective CI redesign (see Follow-on).

**Resurrection-window constraint:** between the RDS destroy (step 2, state now says RDS gone) and the Phase 2
merge (step 4, main code still declares the RDS until then), do NOT push any other `terraform/personal/**`
change to `main` and do NOT manually `workflow_dispatch` the sandbox-apply. A sandbox run in that window plans
against main's code (RDS present) vs state (RDS gone) and would plan a **create** -- which the guard ALLOWS
(verified against `terraform_apply_guard.evaluate_plan`: it blocks `delete` / non-create `neon_*` /
non-inert IAM-sensitive, but a pure RDS `create` returns exit 0) -- re-provisioning the just-destroyed RDS.
(The IAM prune has no such risk: re-adding a policy is IAM-sensitive, so a stray run fail-closes.)
**Tightening + contingency:** stage all branch code changes and get `validate.py` + the PR `--pre` tier green
FIRST, then run the destroy + both IAM prunes and merge in one tight sequence so the window is minutes, not
hours. If a stray sandbox run nonetheless re-provisions the RDS during the window, the contingency is to simply
re-run the manual destroy -- the first destroy's `ducklake-catalog-final-snapshot` already exists and is
retained, and the re-created instance is empty and discarded (timestamp the second snapshot id per VP-3).

**Lambda deployment assessment (Decision 79 / CD.16 / CD.24):** the only Lambda-packaged scope file is
`docs/ROADMAP-PLATFORM.yaml` -- `compute_affected_artifacts(<changed files>)` returns
`{'data-pipeline': ['docs/ROADMAP-PLATFORM.yaml']}`, whose `src/lambdas/data-pipeline/manifest.yaml` is
`status: active` (packaged into `agent-platform-scheduled-agent-dispatcher`). **Per-Lambda deploy DEFERRED
(justified):** the dispatcher is DISABLED (`SCHEDULED_AGENTS_ENABLED="false"` + both EventBridge rules
`state=DISABLED` in `terraform/scheduled_agents.tf`), so the packaged roadmap has no live consumer and this is
a doc-content-only edit. No standalone build/`--deploy`/smoke-test step is gated. **Condition:** if the
implementer re-enables the agents in the same change, add the `data-pipeline`
`build_lambda` + `--deploy` + `run_scheduled_agent --smoke-test` steps (V3). No other scope file is
Lambda-packaged (the `.tf`, the smoke test, and the ops portal are not bundled).

## Acceptance Criteria
- [ ] `scripts.ducklake_neon_smoke_test --attach` prints `ATTACH OK rows=1` and `--churn-gate` prints
      `CHURN_GATE PASS collision_rate=... p95_latency_ms=...` against the live Neon catalog BEFORE any destroy
      step runs.
- [ ] `terraform/personal/rds_ducklake_catalog.tf` is deleted; the 3 `ducklake_catalog_*` vars are removed from
      `variables.tf`; the live RDS instance `ducklake-catalog` is gone with `ducklake-catalog-final-snapshot`
      retained (`available`).
- [ ] The 5 transitional `github_ci_apply` Sids are gone from live IAM AND from `oidc.tf`; `IAMPlatformRolesRead`
      + both Neon Sids remain.
- [ ] `aws_iam_role_policy.platform_admin_ducklake_catalog` (`PlatformDuckLakeCatalogProvisioning`) is removed
      from `platform_roles.tf` and from live IAM (`get-role-policy` -> `NoSuchEntity`).
- [ ] `grep -c 'PRUNE: remove with T2.16b Phase 2' terraform/personal/oidc.tf` == `0` (all 5 PRUNE markers gone).
- [ ] A `terraform plan` on the branch shows NO `ducklake_catalog` RDS actions and NO
      `platform_admin_ducklake_catalog` / `github_ci_apply` IAM changes (at most the known rec-2061
      `null_resource` no-op may appear).
- [ ] The post-merge `terraform-apply-sandbox` **push** run on `main` for the merge commit completes
      `conclusion: success` with NO manual `workflow_dispatch`.
- [ ] `docs/ROADMAP-PLATFORM.yaml` T2.16b is `status: complete`; `bin/venv-python -m scripts.platform_roadmap`
      validates.
- [ ] Rec dispositions landed via the ops portal (rec-2078/2065/2066/2062/2064/2068/2069/2080 closed; rec-2063
      WONTFIX; rec-2067 closed + new Neon-egress rec filed; rec-2079 left open).
- [ ] `bin/venv-python -m scripts.validate` passes (Linux/CC-web; the 7 Windows-only local failures are
      BLOCKED-by-env, CI Linux is canon).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-destroy] | **HARD GATE** -- DuckDB ATTACH round-trip against live Neon | `bin/venv-python -m scripts.ducklake_neon_smoke_test --attach` | prints `ATTACH OK rows=1` (sslmode=require, SNI, pinned DuckDB, `META_SCHEMA 'ducklake_ops'`) | SNI/sslmode/secret/endpoint/`META_SCHEMA` wrong -> **STOP, do NOT destroy**, file a rec (Decision 55) |
| 2 | [pre-destroy] | **HARD GATE** -- connection-churn / OCC gate against live Neon | `bin/venv-python -m scripts.ducklake_neon_smoke_test --churn-gate` | prints `CHURN_GATE PASS collision_rate=... p95_latency_ms=...` (collision rate + commit latency incl. cold-resume within CD.33's OCC budget) | exceeds budget -> implement an app-side pool + re-run; do NOT relax the threshold; do NOT destroy (Decision 55) |
| 3 | [pre-destroy] | Final-snapshot name is free (no collision) | `aws rds describe-db-snapshots --db-snapshot-identifier ducklake-catalog-final-snapshot --profile agent_platform_admin 2>&1 \| grep -q 'DBSnapshotNotFound' && echo SNAPSHOT_NAME_FREE` | prints `SNAPSHOT_NAME_FREE` | a snapshot already exists -> timestamp the `final_snapshot_identifier` before destroy |
| 4 | [post-destroy] | RDS instance is gone | `aws rds describe-db-instances --db-instance-identifier ducklake-catalog --profile agent_platform_admin 2>&1 \| grep -q 'DBInstanceNotFound' && echo RDS_GONE` | prints `RDS_GONE` | instance still present -> the two-step destroy did not complete; re-check `deletion_protection` flip then destroy |
| 5 | [post-destroy] | Final snapshot retained (the rollback artifact) | `aws rds describe-db-snapshots --db-snapshot-identifier ducklake-catalog-final-snapshot --profile agent_platform_admin --query 'DBSnapshots[0].Status' --output text` | prints `available` | no snapshot -> destroy ran with `skip_final_snapshot=true` or a name collision; STOP and RCA before merging |
| 6 | [post-prune] | 5 transitional Sids gone from LIVE `github_ci_apply` (and the kept Sids retained) | `aws iam get-role-policy --role-name agent-platform-github-ci-apply --policy-name agent-platform-github-ci-apply --profile agent_platform_admin --query 'PolicyDocument.Statement[].Sid' --output text > /tmp/cisids.txt; ! grep -qE 'RDSDuckLakeCatalog\|EC2NetworkingDescribeForRDS\|KMSDescribeForRDS\|SecretsManagerRDSMasterSecretRead' /tmp/cisids.txt && grep -q 'IAMPlatformRolesRead' /tmp/cisids.txt && grep -q 'SecretsManagerDuckLakeNeonDSN' /tmp/cisids.txt && echo SIDS_PRUNED` | prints `SIDS_PRUNED` -- none of the 5 pruned Sids present (the `RDSDuckLakeCatalog` prefix covers BOTH `...Read` and `...ParameterGroupModify`) AND the kept `IAMPlatformRolesRead` + `SecretsManagerDuckLakeNeonDSN` still present | no `SIDS_PRUNED` -> a pruned Sid still live OR a kept Sid missing; re-apply `-target=aws_iam_role_policy.github_ci_apply` |
| 7 | [post-prune] | `PlatformDuckLakeCatalogProvisioning` removed from live IAM | `aws iam get-role-policy --role-name PlatformAdmin --policy-name PlatformDuckLakeCatalogProvisioning --profile agent_platform_admin 2>&1 \| grep -q 'NoSuchEntity' && echo POLICY_GONE` | prints `POLICY_GONE` | policy still attached -> run the cleanup apply (it must run AFTER the destroy) |
| 8 | [post-prune] | PRUNE markers + RDS resources gone from the tree; plan is RDS/IAM-clean | `grep -c 'PRUNE: remove with T2.16b Phase 2' terraform/personal/oidc.tf` ; then `cd terraform/personal && rm -rf .terraform/providers && terraform init -backend-config=backend-sandbox.hcl -reconfigure -input=false >/dev/null && terraform plan -input=false -no-color \| tee /tmp/p2plan.txt; grep -qE 'aws_db_instance.ducklake_catalog\|aws_security_group.ducklake_catalog\|aws_db_parameter_group.ducklake_catalog\|platform_admin_ducklake_catalog\|RDSDuckLakeCatalog' /tmp/p2plan.txt && echo PLAN_DIRTY \|\| echo PLAN_CLEAN` | grep count `0`; plan prints `PLAN_CLEAN` (at most a known rec-2061 `null_resource` no-op) | count != 0 or `PLAN_DIRTY` -> a removal was missed or live state diverged; reconcile before merge |
| 9 | [pre-merge] | Full presubmit (CI parity) | `bin/venv-python -m scripts.validate` | `PASS` | address before merge. (On Windows the 7 known path/pyiceberg failures are BLOCKED-by-env; run on Linux/CC-web where CI is canon.) |
| 10 | [post-merge] | Clean-green sandbox **push** run on main (no manual dispatch) | GitHub MCP: `mcp__github__actions_list` `list_workflow_runs` for `terraform-apply-sandbox.yml`, branch `main`, filter `event=push`; inspect the run whose `head_sha` == the merge commit | that run's `conclusion` == `success` (plan -> guard exit 0 -> subagent PROCEED -> apply no-op) | the push run reds -> live state diverged from merged code; diagnose the diff (do NOT paper over with a dispatch) |
| 11 | [post-merge] | Roadmap schema validates with T2.16b complete | `bin/venv-python -m scripts.platform_roadmap` | prints `PASS` (T2.16b resolves; status complete) | schema/referential error in the edited entry |
| 12 | [post-merge] | Rec dispositions landed | `bin/venv-python -m scripts.sync_ops pull >/dev/null 2>&1; for id in rec-2078 rec-2065 rec-2066 rec-2062 rec-2080; do grep -h "\"$id\"" logs/.recommendations-log.jsonl \| tail -1 \| grep -q '"status": "closed"' && echo "$id closed" \|\| echo "$id NOT closed"; done` | each prints `<id> closed` | a rec still open -> re-run the `update_rec` portal call for it |

## Constraints
- **Apply governance (Decision 35 + Decision 77):** the RDS destroy AND both IAM removals fail-close the
  Decision-77 guard, so they route to **manual `agent_platform_admin` (or `platform_breakglass`) applies**,
  human-gated, run branch-first. The guard step NEVER gets `continue-on-error`.
- **Sequencing (load-bearing):** proof gate -> RDS destroy -> IAM prune (both policies) -> merge. The
  `PlatformDuckLakeCatalogProvisioning` removal MUST follow the destroy -- the destroy, run as PlatformAdmin,
  consumes `rds:DeleteDBInstance` FROM that policy, so removing it first AccessDenies the destroy (the one
  strictly load-bearing IAM ordering). The 5 `github_ci_apply` Sids are on the CI auto-apply role (the sandbox
  push-plan), not the manual-destroy role, so they do NOT gate the destroy; keep them only until the RDS is out
  of state + main code, or the automated push-plan reds on RDS refresh-reads. Never let an intervening
  `terraform/personal/**` push or manual dispatch hit `main` between the destroy and the merge
  (resurrection window).
- **Smoke-test honesty (Decision 55):** the ATTACH + churn gates loud-fail. A failed gate is a stop-and-RCA
  signal (file a rec), NOT a trigger to relax a threshold or destroy the RDS anyway. No rescue agents or
  workaround loops.
- **Two-step destroy + rollback:** flip `deletion_protection=false` and apply, THEN delete the file and apply
  to destroy. `skip_final_snapshot=false` + `final_snapshot_identifier="ducklake-catalog-final-snapshot"`
  (already in the file) is the rollback substitute for the skipped pg_dump restore-drill. Partial-failure
  rollback: if the destroy aborts after `deletion_protection` is off, re-enable it to avoid a
  live-but-unprotected DB.
- **Single Portal invariant:** ALL rec dispositions go through `scripts.ops_data_portal` (`update_rec`/`file_rec`);
  call `get_rec_write_guidance()` before `file_rec` for the new Neon-egress rec. NEVER edit
  `logs/.recommendations-log.jsonl` directly (`validate.py` fails CI). `update_rec`/`file_rec` need the
  `agent_platform` (PlatformDev) Athena chain.
- **Executor boundary (Decision 44, affirmed not violated):** editing `oidc.tf` / `platform_roles.tf` /
  `terraform_apply_guard`-adjacent CI tooling is NOT an executor self-modification violation -- this is a
  human-run `/implement`, and per Decision 79's precedent CI/guard tooling is not executor machinery. None of
  the scope files are in Decision 44's boundary table.
- **Provider-cache contamination gotcha:** `terraform init -backend-config=backend-sandbox.hcl -reconfigure`
  (apply path) and `terraform init -backend=false` (the `validate.py` path) leave incompatible `.terraform/`
  states (lock-hash mismatch). Run `rm -rf terraform/personal/.terraform/providers` when switching between the
  two init modes.
- **No `DECISIONS.md` edit:** CD.34 stays pending; this plan does not ratify it (see Context). No emojis; ASCII
  hyphens; ruff line length 127; `bin/venv-python` for all Python; Bash syntax only.

## Context
- **State-of-the-world (human-verified, post-#77 `/implement` session):** the RDS catalog is LIVE but never
  exercised by DuckLake (`ducklake-catalog.ch2m62sow8g1.eu-west-2.rds.amazonaws.com:5432`, DB `ducklake_catalog`;
  master secret `...:secret:rds!db-eed12c7d-...` -> matches the `rds!*` wildcard, answering rec-2080). The Neon
  project (`ep-billowing-sun-abqkgmrh.eu-west-2.aws.neon.tech`) + DSN secret (`ducklake-neon-catalog-dsn-z6ouv3`)
  are provisioned, but **DuckLake-against-Neon is UNPROVEN** -- no ATTACH/churn/restore was ever run (SESSION_LOG
  has no Neon entries; the roadmap progress_note says "live Neon apply + RDS retirement (Phase 2) pending").
  Hence VP-1/VP-2 are hard gates. The github_ci_apply live policy was diffed clean against `oidc.tf` (no drift).
  Sandbox-apply round 3 (run 27018479923) applied the codified `apply_method` flip; live state and
  `terraform/personal/` are in sync; `grep -c 'PRUNE: remove with T2.16b Phase 2' oidc.tf` == 5.
- **Decision scout (NO_FLAGS):** CITE Decision 35 (destroy human-gated), Decision 77 (sandbox fail-closed
  guard), Decision 78/CD.31 (the catalog being retired), Decision 37 (Secrets Manager runtime-fetch),
  Decision 48 (V3), Decision 55 (loud-fail). NOTE (affirm compliance) Decision 44 (CI/guard != executor
  machinery, per Decision 79) + Decision 70 (rec dispositions are portal lifecycle ops, not physical deletion).
  RELATED: Decision 81/CD.33 (the OCC budget the churn gate fits within), Decision 73 (the clean-green push
  model), Decision 76 (web MCP merge flow).
- **CD.34 ratification deferred (open decision, default = defer):** ratifying CD.34 as the log-decision
  Decision 82 (the CD.31->Decision 78 / CD.33->Decision 81 precedent) is a `DECISIONS.md` edit. To keep this
  plan tight and Decision-writing in the separate retrospective, CD.34 stays pending here. The implementer may
  ratify it in the retrospective/governance follow-on. T2.16b can be `complete` while CD.34 is pending (CD.34
  also gates T2.17-T2.19).
- **Branch freshness:** 0 commits behind `origin/main` at planning time; no Scope-file divergence
  (main_freshness clean).
- **Known drift (do NOT fix here):** open rec-2061 notes `main.tf` Athena-DDL `null_resource` hashes drift from
  S3 state; a `terraform plan` may surface it as a harmless no-op. VP-8 tolerates it.
- **Network/creds dependency:** Phase 2 needs `agent_platform_admin` for the privileged applies, `agent_platform`
  (Athena) for rec dispositions, and egress to the Neon endpoint + `extensions.duckdb.org` for VP-1/VP-2. Run
  from a network-permitted context (the planning container currently shows an AWS DNS-resolution failure; the
  `/implement` session must verify the chain with `aws sts get-caller-identity --profile agent_platform_admin`
  first).

## Follow-on (separate deliverables -- NOT part of this plan's execution)
Per the human's direction ("keep the Phase 2 plan tight; don't bundle"), the retrospective and the CI
structural redesign are SEPARATE follow-on plans, authored after this Phase 2 lands. Captured here only as a
durable pointer:
- **Retrospective Decision** (file in `docs/DECISIONS.md` via the log-decision path), title e.g. *"Iterative-discovery
  convention scope + CI self-grant bootstrap"*, recording: (1) plan-vs-reality drift on the Neon `org_id`
  (codified post-hoc in #73 -- planner could not know without the Neon API; mark external-provider pre-existing
  fields "discover-during-impl"); (2) iterative-discovery IAM churn (#75->#76->#77 = 3 rounds; cap at 1-2 +
  auto-escalate, OR pre-grant from a provider-5.x refresh-action lookup table); (3) the `github_ci_apply`
  self-grant bootstrap (every PR touching the role's own policy reds its push run by design); (4) VP-8
  local-vs-CI Windows divergence (7 tests fail locally, pass on Linux CI -- skipif or install pyiceberg, or
  formalise "local VP-8 BLOCKED-by-env is acceptable when CI is authoritative"); (5) plan-scope-vs-convergence
  tension (allow iterative-discovery to extend plan scope when each round is documented + the boundary preserved).
  Record the guard-self-grant-exception option as explicitly REJECTED.
- **2-3 follow-on tier_items:** (a) a pre-grant analysis script that intersects changed resources with AWS
  provider 5.x refresh-time actions to cap iterative-discovery at 1 round; (b) the CI-role self-grant redesign
  ("terraform CI green" structural fix -- e.g. move `github_ci_apply` IAM under a separate `terraform/bootstrap/`
  root applied out-of-band, vs the branch-first-pragma interim); (c) cross-platform pytest hermeticity.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (Decisions 35, 37, 44, 48, 55, 77, 78 in particular)
- [ ] `aws sts get-caller-identity --profile agent_platform_admin` and `--profile agent_platform` both succeed
      (privileged applies + Athena rec writes)
- [ ] Neon egress reachable from this context (VP-1/VP-2 can run), else arrange a network-permitted run
- [ ] All files in the Scope table located and readable; the 5 PRUNE-marked Sids + the
      `platform_admin_ducklake_catalog` policy located
- [ ] Acceptance Criteria + the load-bearing sequencing (proof -> destroy -> prune -> merge) understood

## Ordered Execution Steps

### Phase 2a -- prove Neon (hard gate; do this FIRST, before touching the RDS)
1. **Run VP-1 (`--attach`) and VP-2 (`--churn-gate`)** against the live Neon catalog. If EITHER fails: STOP,
   file a recommendation via `scripts.ops_data_portal` describing the failure, and do NOT proceed to any destroy
   step (the RDS stays as the safety net until Neon is proven). Decision 55 -- no workaround loops.

### Phase 2b -- retire the RDS (manual `agent_platform_admin`, branch-first, irreversible)
2. **Pre-destroy snapshot-name check (VP-3):** confirm no `ducklake-catalog-final-snapshot` already exists; if it
   does, set a timestamped `final_snapshot_identifier` in `rds_ducklake_catalog.tf` before the destroy.
3. **Two-step destroy, step 1:** edit `terraform/personal/rds_ducklake_catalog.tf` to set
   `deletion_protection = false`. From the admin container:
   `rm -rf terraform/personal/.terraform/providers && cd terraform/personal && terraform init -backend-config=backend-sandbox.hcl -reconfigure -input=false && terraform apply` (in-place update; guard not involved -- manual apply).
4. **Two-step destroy, step 2:** delete `terraform/personal/rds_ducklake_catalog.tf` and remove the 3
   `ducklake_catalog_*` vars from `variables.tf`. `terraform apply` -> destroys the instance + SG + subnet group
   + parameter group + data sources + outputs; the final snapshot is created. Run VP-4 + VP-5 (RDS gone, snapshot
   `available`). If the destroy aborts mid-way, re-enable `deletion_protection` (Decision 55 partial-failure rollback).

### Phase 2c -- prune the transitional IAM (manual `agent_platform_admin`, AFTER the destroy)
5. **Prune `github_ci_apply` Sids:** remove the 5 PRUNE-marked Sids from `aws_iam_role_policy.github_ci_apply`
   in `oidc.tf` (keep `IAMPlatformRolesRead` + both Neon Sids). Apply targeted:
   `terraform apply -target=aws_iam_role_policy.github_ci_apply`. Run VP-6. (This role is the sandbox
   push-plan's, NOT the manual-destroy's -- the prune does not gate the destroy; it is sequenced here so that by
   merge time the RDS is out of state and the live policy matches the pruned code, giving a clean push-plan.)
6. **Remove `PlatformDuckLakeCatalogProvisioning`:** delete the entire
   `aws_iam_role_policy.platform_admin_ducklake_catalog` block from `platform_roles.tf`. `terraform apply`
   (AdminOps `iam:*` covers `DeleteRolePolicy`). Run VP-7. (Ordering: this MUST be after step 4 -- the destroy,
   run as PlatformAdmin, consumes `rds:DeleteDBInstance` FROM this policy; removing it first AccessDenies the
   destroy. This is the one strictly load-bearing IAM ordering.)
7. **Confirm the tree + plan are clean (VP-8):** `grep -c 'PRUNE: remove with T2.16b Phase 2' oidc.tf` == 0; a
   branch `terraform plan` shows no RDS/`ducklake_catalog` IAM actions (at most the rec-2061 `null_resource`
   no-op). Remember the `rm -rf .terraform/providers` between the `-reconfigure` apply init and any
   `-backend=false` validate init.

### Phase 2d -- roadmap, validate, clean merge
8. **Update `docs/ROADMAP-PLATFORM.yaml`:** T2.16b `status: in_progress` -> `complete`; update `progress_note`
   to record Phase 2 (Neon proven via VP-1/2, RDS retired with final snapshot, IAM pruned, recs dispositioned).
   Do NOT edit `DECISIONS.md` (CD.34 stays pending). Run VP-11 (`platform_roadmap`).
9. **Full presubmit (VP-9):** `bin/venv-python -m scripts.validate` -> PASS. Commit all branch changes.
10. **Merge (Decision 76 web MCP flow):** push the branch; open the PR via `mcp__github__create_pull_request`
    (base `main`); `subscribe_pr_activity` and end the turn for the fast `--pre` tier; on green, squash-merge via
    `mcp__github__merge_pull_request(merge_method="squash")`. Merge promptly to close the resurrection window;
    do not push other `terraform/personal/**` changes to main in between.
11. **Confirm clean-green push run (VP-10):** verify the post-merge `terraform-apply-sandbox` **push** run for
    the merge SHA is `success` (the apply is a no-op because state already matches) -- NO manual dispatch.

### Phase 2e -- rec dispositions (ops portal; needs the `agent_platform` Athena chain)
12. Via `scripts.ops_data_portal` (`update_rec`): close rec-2062/2064/2065/2066/2068/2069/2078/2080 with
    execution notes; WONTFIX rec-2063; close rec-2067 (RDS SG deleted). Call `get_rec_write_guidance()` then
    `file_rec` for a NEW rec capturing the Neon public-endpoint egress-least-privilege concern. Leave rec-2079
    open. Run VP-12 to confirm closures landed.
13. **Execute the full Verification Plan** -- run each VP step in phase order; loop until green. If a V3 step
    fails unrecoverably, STOP and analyse root cause (Decision 55); for a destroy failure, re-enable
    `deletion_protection` rather than leaving a live-but-unprotected catalog.
14. **Report:** the VP-1/2 proof outputs, the `terraform` destroy/apply summaries, the RDS-gone +
    final-snapshot confirmation, the IAM-prune confirmations, the clean-green push-run link, the roadmap flip,
    and the rec dispositions. Note the retrospective + CI redesign as the queued follow-on.
