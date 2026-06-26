# DuckLake Catalog Operations Runbook

```yaml
runbook: ducklake-catalog-operations
tier: T2.17-T2.18
decisions: [84, 81, 82, 78, 39, 37, 35, 77, 79, 62, 55]
exit_criteria: [EC3, EC12]
sections:
  - id: 1
    title: PlatformAdmin break-glass catalog-attach (inspect/repair)
    control: CD.33 O-1
  - id: 2
    title: OQ.12 DuckLake/DuckDB version-bump clone-rehearsal policy
    control: OQ.12
  - id: 3
    title: Maintenance pipeline -- cadences, guardrails, circuit breaker, manual invoke
    control: CD.33 clause 5-6 / Decision 81 clause 6
  - id: 4
    title: Catalog disaster-recovery (CD.34) -- DR Lambda, SNS alert wiring, co-tuning knobs
    control: CD.34 O-2 / Decision 82
  - id: 5
    title: ops_compaction decommission (T2.19-gated)
    control: Decision 78 clause 7 / Decision 70
catalog:
  backend: Neon serverless Postgres (DIRECT endpoint, sslmode=require)
  dsn_secret: ducklake-neon-catalog-dsn
  dsn_secret_arn_output: ducklake_neon_catalog_dsn_secret_arn
  meta_schema: ducklake_ops
  catalog_alias: ops_catalog
  data_path: s3://agent-platform-data-lake/ducklake-neon-smoke/
  data_path_relocation: |
    Fixed at catalog-init and stored in the Neon metadata. DuckLake's OVERRIDE_DATA_PATH
    is a per-session override ONLY -- it does NOT persist the stored value (verified live).
    Relocating the catalog therefore requires reinitialising it (drop the meta_schema and
    re-ATTACH at the new path), not an override. Code aligns to the stored path, never the reverse.
  pinned_duckdb_version: "1.5.4"  # SSOT: config/lambda/ducklake/version.yaml
  pinned_ducklake_version: "v1.0"
  extension_platform: linux_amd64
```

## Section 1 -- PlatformAdmin break-glass catalog-attach (CD.33 O-1)

The closed reader/writer boundary (Decision 81) means every routine ops read transits `ducklake_reader`
and every write transits `ducklake_writer`. The ONLY sanctioned out-of-band access to the catalog is an
**audited PlatformAdmin break-glass**: a read-only ATTACH for inspect/repair when a Lambda path is wedged
(e.g. a stuck snapshot, an orphaned-file question, a schema drift investigation).

Authority for the break-glass read is the explicit, named `DuckLakeBreakGlass` inline policy on the
`PlatformAdmin` role (`terraform/personal/platform_roles.tf`): `secretsmanager:GetSecretValue` on the Neon
DSN ARN + `s3:GetObject`/`s3:ListBucket` on the `ducklake-*` prefixes. It grants READ only -- a break-glass
session cannot mutate the catalog data.

### Preconditions

- Assume the `agent_platform_admin` (PlatformAdmin) role. Verify:
  `aws sts get-caller-identity --profile agent_platform_admin`
- DuckDB at the SSOT-pinned version locally. Check:
  `bin/venv-python -c "import duckdb; from src.common.ducklake_version import pinned_duckdb_version; assert duckdb.__version__ == pinned_duckdb_version(), (duckdb.__version__, pinned_duckdb_version())"`.
  The break-glass ATTACH uses the SAME pinned version as the runtime (OQ.12 lockstep).

### Inspect (read-only ATTACH)

The runtime's own connection authority backs the break-glass attach -- there is one ATTACH implementation
(`src/common/ducklake_runtime.py::open_connection`). Use the dev-mode opener (network INSTALL) from an
egress-permitted host, or point `extension_directory` at a local baked copy.

```bash
# 1. Confirm the credential is reachable (read the DSN secret under the break-glass grant).
aws secretsmanager get-secret-value \
  --secret-id ducklake-neon-catalog-dsn \
  --profile agent_platform_admin --region eu-west-2 \
  --query SecretString --output text >/dev/null && echo "DSN_READABLE"

# 2. Read-your-write inspect via the smoke test's restore drill (ATTACHes the catalog, verifies a probe).
bin/venv-python -m scripts.ducklake_neon_smoke_test --restore-drill --profile agent_platform_admin
```

For an ad-hoc inspect from a Python REPL (read-only):

```python
from src.common import ducklake_runtime as rt
dsn = rt.fetch_dsn(profile="agent_platform_admin")
con = rt.open_connection(dsn=dsn, data_path="s3://agent-platform-data-lake/ducklake-neon-smoke/")
# Inspect catalog metadata (snapshots, files, schema) -- READ ONLY.
print(con.execute("SELECT * FROM ducklake_snapshots('ops_catalog')").fetchall())
print(con.execute("SELECT count(*) FROM ducklake_list_files('ops_catalog', 'ducklake_smoke_history')").fetchone())
con.close()
```

### Repair

Repairs are deliberately NOT automated. Any mutation (snapshot expiry, orphan cleanup, schema fix) is a
human decision recorded as a Decision/recommendation, then executed via the maintenance pipeline (T2.18)
or a one-off reviewed script -- never silently from a break-glass REPL. If a repair is unavoidable in the
moment (incident), record exactly what was run in the incident log and file a follow-up recommendation to
encode the fix into the maintenance pipeline (Decision 55: no silent workarounds).

### Drill (EC12)

The break-glass path is drilled by the V3 verification step:
`bin/venv-python -m scripts.ducklake_neon_smoke_test --restore-drill` under `agent_platform_admin`, which
performs a consistent `pg_dump` -> scratch Neon restore -> DuckDB read-your-write verification. A green
drill proves the credential grant, the ATTACH, and the read path end-to-end.

## Section 2 -- OQ.12 DuckLake/DuckDB version-bump clone-rehearsal policy

DuckLake `v1.0` is lockstep with the DuckDB version pinned in
`config/lambda/ducklake/version.yaml` (the single source of truth / SSOT for all derive surfaces).
The catalog schema, the DuckLake extension, and the DuckDB engine move together. The runtime asserts
this at every connection (`src/common/ducklake_runtime.py::assert_duckdb_version`, loud-fail
`VersionMismatchError`). All derive surfaces load the pin through the shared loader
(`src/common/ducklake_version.py::pinned_duckdb_version()`); the ducklake-version-lockstep
`validate.py` gate enforces that no derive surface diverges from the SSOT.

**First exercised bump:** `1.5.3` → `1.5.4` (PLAN-duckdb-pin-bump-1-5-4, 2026-06-26).
A 1.5.4 engine successfully reads a 1.5.3-authored catalog clone (no on-disk migration needed).

```yaml
version_bump_surfaces:
  - config/lambda/ducklake/version.yaml          # SOLE EDITABLE -- change ONLY this value
  - requirements.txt                              # DERIVED -- sync via scripts/sync_ducklake_version.py
  - s3://agent-platform-data-lake/ducklake-extensions/<new-version>/  # re-seeded baked extensions
  # (src/common/ducklake_runtime.py and scripts/build_lambda.py derive via pinned_duckdb_version() --
  #  no edits needed when version.yaml is the sole change point)
```

### Environment constraint (where the rehearsal runs)

**Canonical pre-deploy path (CC-web compatible): `--canary-rehearsal`.**
All TCP/5432 happens server-side inside ephemeral Lambda canaries; the orchestrator communicates
over HTTPS/443 only (PLAN-oq12-clone-rehearsal-lambda / rec-2357). The direct-connection gates
(`--churn-gate`, `--restore-drill`) are privileged-env-only break-glass paths for non-CC-web
hosts with outbound TCP/5432 (a laptop, PySR compute node, or eu-west-2 bastion).

**Direct-gate guard (Decision-88 egress acknowledgement):** `--churn-gate` and `--restore-drill`
refuse to run unless `DUCKLAKE_ALLOW_DIRECT_GATE=1` is set in the environment. Setting it
acknowledges that the caller has TCP/5432 access and accepts that the direct path is NOT
available from CC-web. DO NOT set this inside CC-web to work around a 5432 timeout -- that
is a structural block, not a transient network error.

### Clone-rehearsal gate (mandatory before any production bump)

1. **Pin candidate.** Edit `duckdb_version` in `config/lambda/ducklake/version.yaml` on a branch.
   Run `bin/venv-python -m scripts.sync_ducklake_version` to sync `requirements.txt`.
   Run `bin/venv-python -m scripts.validate --pre` to confirm the ducklake-version-lockstep gate passes.
2. **Re-seed extensions.** Fetch `ducklake`/`httpfs`/`postgres_scanner` for `vX.Y.Z/linux_amd64` and upload to
   `s3://agent-platform-data-lake/ducklake-extensions/vX.Y.Z/` (the build's S3 fallback). Confirm the local
   DuckDB `X.Y.Z` can LOAD all three from a baked `extension_directory` with autoload/autoinstall OFF.
3. **Build and upload candidate layers.**
   ```
   bin/venv-python -m scripts.build_lambda --ducklake-only --profile agent_platform
   ```
   This uploads `ducklake-deps-layer.zip`, `ducklake-extensions-layer.zip`, and
   `ducklake-pgclient-layer.zip` plus the three function zips to S3.
4. **Run the canary rehearsal from CC-web (canonical, no TCP/5432).**
   ```
   bin/venv-python -m scripts.ducklake_neon_smoke_test --canary-rehearsal --profile agent_platform [--json]
   ```
   The orchestrator: publishes candidate layers, creates ephemeral writer/reader/maintenance canaries
   pointed at a scratch meta-schema + scratch S3 prefix + scratch Neon DB, proves ATTACH + churn
   (unchanged CD.33 budgets) + RYW + real-prod read-clone (`action_clone_catalog`), then tears down
   all ephemeral resources. Passes all EC gates on the candidate engine. NEVER touches `ducklake_ops`
   or the production DATA_PATH.
5. **Compatibility decision.** If the canary rehearsal is green, file a Decision recording the bump
   and the rehearsal evidence, then roll the production layer (`--deploy`). If it regresses, STOP --
   do not bump; RCA the regression (Decision 55). Never relax the runtime version-assert to paper
   over a mismatch.

### Rollback

The pinned-version assert means a half-applied bump fails CLOSED (the runtime refuses to attach on a
mismatch) rather than silently writing with an incompatible engine. To roll back, revert the four surfaces
to the prior pin and redeploy the prior layer; the cloned catalog used for rehearsal is discarded.

## Section 3 -- Maintenance pipeline (T2.18 / CD.33 clause 5-6 / Decision 81 clause 6)

### Cadences

```yaml
maintenance_cadences:
  daily_merge:
    schedule: "cron(0 4 * * ? *)"    # 04:00 UTC
    action: merge
    description: "Non-destructive: flush_inlined_data + merge_adjacent_files only"
    destructive: false
    mechanism: EventBridge rule -> agent-platform-ducklake-maintenance Lambda (action=merge)
  weekly_gc:
    schedule: "cron(0 5 ? * SUN *)"  # 05:00 UTC Sunday
    action: gc
    description: "Guarded destructive: full 5-step sequence with circuit breaker"
    destructive: true
    mechanism: EventBridge rule -> agent-platform-ducklake-maintenance Lambda (action=gc)
```

Cadence mechanism rationale: EventBridge-scheduled Lambda per Decision 62 / CD.29 -- a single
deterministic Lambda needs no Step Functions state machine (Decision 39), and the Lambda posture
is consistent with T2.17 (writer/reader). A new GH Actions surface for non-CI scheduled work
would be a new ingress surface without benefit (CD.29).

Table scope (T2.18 FP-A): `ducklake_smoke_history` + `ducklake_smoke_current`. Expansion to the
full `ducklake_ops` catalog and all `ops_*` business tables is a T2.19 exit criterion -- the code
carries an explicit forward-pointer constant (`src/common/ducklake_maintenance.py::MAINTENANCE_SCOPE_NOTE`).

### Guardrail constants (CD.33 H1/R-3/O-3/M-3 / Decision 81 clause 6)

```yaml
guardrails:
  snapshot_retain_days: 30        # expire_snapshots: older_than = now - 30 days
  file_cleanup_grace_days: 7      # cleanup_old_files + delete_orphaned_files: older_than = now - 7 days
  snapshot_floor: 2               # never expire below the 2 most-recent snapshots
  gc_breaker_file_fraction: 0.20  # abort if would-delete > 20% of tracked files
  gc_breaker_bytes: 10_737_418_240  # 10 GiB -- abort if would-delete > 10 GiB
  cleanup_all_in_scheduled_runs: never  # NEVER pass cleanup_all=True in scheduled runs
```

These are module-level constants in `src/common/ducklake_maintenance.py`. They are tunable knobs
but NEVER relaxed to make a gate pass (Decision 55). Changing them requires a Decision superseding CD.33.

### Circuit breaker (CD.33 H1)

The circuit breaker runs PRE-DESTRUCTIVE (before any `CALL` that deletes S3 objects):

1. Aggregate all tracked files across scoped tables (via `ducklake_list_files`).
2. Dry-run `ducklake_cleanup_old_files` + `ducklake_delete_orphaned_files` to count would-be deletions.
3. If `(would_delete / total) > 20%` OR `would_delete_bytes > 10 GiB`, raise `DuckLakeMaintenanceError`
   and abort (no destructive call is issued).
4. On abort, emit `MaintenanceBreakerTrip=1` to the `DuckLakeMaintenance` CloudWatch namespace.

**Reading the alarm (FP-B):** the `ducklake-maintenance-circuit-breaker` CloudWatch alarm fires
when `MaintenanceBreakerTrip >= 1` in a 5-minute window. As of T2.18 FP-B, `alarm_actions` is
wired to the shared personal-account SNS topic (`agent-platform-alerts`). An email notification
is sent on alarm state entry. Confirm the SNS subscription is active (not `PendingConfirmation`)
before relying on the page-out; check with:
```bash
aws sns list-subscriptions-by-topic \
  --topic-arn $(terraform -chdir=terraform/personal output -raw alerts_topic_arn) \
  --profile agent_platform
```

When the breaker fires, do NOT raise the threshold to pass. RCA the file accumulation:
- Is the expiry cutoff too recent (< 30 days)?
- Did a previous cleanup run fail silently, leaving many expired-but-not-cleaned files?
- Is there a bug in the orphan path producing large volumes of orphaned files?

### Manual invoke runbook

```bash
# Invoke daily merge manually (safe, non-destructive):
aws lambda invoke \
  --function-name agent-platform-ducklake-maintenance \
  --payload '{"action":"merge"}' \
  --profile agent_platform \
  --region eu-west-2 \
  /tmp/merge-response.json && cat /tmp/merge-response.json

# Invoke weekly GC manually (guarded, emits metrics):
aws lambda invoke \
  --function-name agent-platform-ducklake-maintenance \
  --payload '{"action":"gc"}' \
  --profile agent_platform \
  --region eu-west-2 \
  /tmp/gc-response.json && cat /tmp/gc-response.json

# Forced-threshold breaker probe (VP step 11 / diagnostic):
aws lambda invoke \
  --function-name agent-platform-ducklake-maintenance \
  --payload '{"action":"breaker_probe"}' \
  --profile agent_platform \
  --region eu-west-2 \
  /tmp/breaker-response.json && cat /tmp/breaker-response.json
# Expect: statusCode=500, breaker_tripped=true (if any deletable files exist).

# Check singleton concurrency (reserved_concurrent_executions must be 1):
aws lambda get-function-concurrency \
  --function-name agent-platform-ducklake-maintenance \
  --profile agent_platform

# Check EventBridge schedule rules:
aws events list-rules \
  --name-prefix agent-platform-ducklake-maintenance \
  --profile agent_platform
```

### Singleton constraint (Decision 81 clause 6)

`reserved_concurrent_executions = 1` is set on the maintenance Lambda. This is intentional: the
maintenance pipeline must not run concurrently with itself (overlapping GC passes on the same
catalog could corrupt the cleanup state). This differs from the ducklake_writer Lambda (Decision
81 clause 3), which has NO reserved concurrency so its OCC model is not artificially constrained.
The distinction is documented in `terraform/personal/ducklake_maintenance.tf` to pre-empt a
reviewer keyword-collision flag.

### T2.19 expansion forward pointer

The maintenance scope for T2.18 FP-A/FP-B is `ducklake_smoke_*`. At T2.19, the scope GENERALISES
to the full `ducklake_ops` catalog and all real `ops_*` business tables. The code carries an
explicit constant (`MAINTENANCE_SCOPE_NOTE` in `src/common/ducklake_maintenance.py`) with the
expansion instructions. No code change is needed in the primitives themselves -- the table list is
passed in at call time.

The hot_merge cadence (`HOT_TABLE_SCOPE`) follows the same expansion pattern: currently scoped to
`ducklake_smoke_*`, expanding to the real high-write-rate `ops_recommendations`/`ops_decisions`
tables at T2.19 when the DuckLake writer is the live write path and real dead-file rates exist to
tune against.

## Section 4 -- Catalog disaster-recovery (T2.18 FP-B / CD.34 / Decision 82)

### Cadence and format

```yaml
catalog_dr:
  lambda: agent-platform-ducklake-catalog-dr
  schedule: "cron(0 3 * * ? *)"    # 03:00 UTC daily
  pg_dump_flags: "--format=custom --serializable-deferrable"
  format_note: >-
    --format=custom is compressed and supports selective/parallel restore via pg_restore.
    Diverges from the T2.16b restore-drill format (plain SQL; restores via psql).
    T2.19 carry: the T2.19 restore-drill gate must be updated to use pg_restore for the
    custom-format dump (the existing _restore_dump / restore_drill in the smoke test uses psql).
  key_format: "catalog-dr/{YYYY}/{MM}/{DD}/ducklake-catalog-pg{PG}-duckdb{DUCKDB}-{ts}.dump"
  retention_days: 30     # tunable to 7 (S3 lifecycle rule); re-baseline on engine bump (OQ.12)
  engine_version_tag: "PG16 + duckdb {pin} in both S3 key and object metadata; pin derived from config/lambda/ducklake/version.yaml at Lambda boot"
  metric: "CatalogDumpSuccess=1 to CloudWatch DuckLakeCatalogDR namespace on success"
  loud_fail: "Non-zero pg_dump exit raises CatalogDrError BEFORE emitting the metric (Decision 55)"
```

### Freshness alarm

The `ducklake-catalog-dr-freshness` CloudWatch alarm uses evaluation-period math to implement a
>25h lookback (CloudWatch's `period` ceiling is 86400s/24h):

```yaml
freshness_alarm:
  metric: CatalogDumpSuccess
  namespace: DuckLakeCatalogDR
  period: 3600           # 1-hour buckets
  evaluation_periods: 25
  datapoints_to_alarm: 25  # ALL 25 hourly periods must have < 1 success to alarm
  comparison_operator: LessThanThreshold
  threshold: 1
  treat_missing_data: breaching  # a missed invocation counts as failing
  alarm_actions: [aws_sns_topic.alerts.arn]  # shared SNS topic (Decision 39)
```

When the freshness alarm fires, the DR Lambda has not produced a successful dump in over 25 hours.
Investigate:
1. Check CloudWatch Logs for `/aws/lambda/agent-platform-ducklake-catalog-dr`.
2. Check EventBridge rule state: `aws events list-rules --name-prefix agent-platform-ducklake-catalog-dr --profile agent_platform`
3. If the rule is ENABLED but no invocation occurred, check Lambda concurrency + throttle metrics.
4. If the dump failed: check the error in logs; if the Neon endpoint is unreachable, check Neon
   console; if pg_dump exited non-zero, the error string is in the Lambda log + in the 5xx response.

### SNS alert wiring (Decision 39)

One shared personal-account SNS topic (`agent-platform-alerts`) is the `alarm_actions` target
for both maintenance alarms:

| Alarm | Triggers on |
|---|---|
| `ducklake-maintenance-circuit-breaker` | `MaintenanceBreakerTrip >= 1` in a 5-minute window |
| `ducklake-catalog-dr-freshness` | No `CatalogDumpSuccess` in any of the last 25 hourly periods |

The SNS email subscription endpoint is set in `terraform/personal/terraform.personal.tfvars`
(`alerts_email = "..."`). The file is gitignored -- no email address is committed to source.

**Activating page-out:** after the first `terraform apply` that creates the SNS resources, AWS
sends a subscription-confirmation email. The recipient must click the confirmation link before
the page-out is live. Verify subscription status:
```bash
aws sns list-subscriptions-by-topic \
  --topic-arn $(terraform -chdir=terraform/personal output -raw alerts_topic_arn) \
  --profile agent_platform
# Subscription SubscriptionArn must be a real ARN (not "PendingConfirmation").
```

### Co-tuning knobs (T2.18 FP-B / CD.34)

The GC circuit-breaker thresholds are env-configurable on the maintenance Lambda:

```yaml
co_tuning_knobs:
  GC_BREAKER_FILE_FRACTION:
    default: "0.20"  # FP-A shipped value; DO NOT change without a Decision superseding CD.33
    env_var: GC_BREAKER_BYTES
    purpose: "Abort GC if would-delete fraction exceeds this threshold"
  GC_BREAKER_BYTES:
    default: "10737418240"  # 10 GiB
    env_var: GC_BREAKER_BYTES
    purpose: "Abort GC if would-delete bytes exceed this threshold"
```

These are a **tunability mechanism, not a relaxation**. The FP-A defaults (>20% files / >10 GiB)
remain the shipped values. Changing them to make a gate pass is a Decision-55 violation.

At T2.19, when the real `ops_*` tables are in DuckLake and actual dead-file rates are observable,
the numeric tuning is reviewed and a Decision filed if adjustment is warranted. FP-B lands the
mechanism; the numeric tuning is a T2.19 carry item.

### Manual invoke

```bash
# Invoke the DR Lambda manually (initiates pg_dump -> S3 -> metric):
aws lambda invoke \
  --function-name agent-platform-ducklake-catalog-dr \
  --profile agent_platform \
  --region eu-west-2 \
  /tmp/dr-response.json && cat /tmp/dr-response.json
# Expect: {"ok": true, "s3_key": "catalog-dr/...", "dump_bytes": ..., "pg_version": "16", ...}

# Invoke hot_merge manually (merge-only, non-destructive):
aws lambda invoke \
  --function-name agent-platform-ducklake-maintenance \
  --payload '{"action":"hot_merge"}' \
  --profile agent_platform \
  --region eu-west-2 \
  /tmp/hot-merge-response.json && cat /tmp/hot-merge-response.json
# Expect: {"ok": true, "action": "hot_merge", "files_before": N, "files_after": M}

# Check DR schedule and freshness alarm:
aws events list-rules --name-prefix agent-platform-ducklake-catalog-dr --profile agent_platform
aws cloudwatch describe-alarms \
  --alarm-names ducklake-maintenance-circuit-breaker ducklake-catalog-dr-freshness \
  --query 'MetricAlarms[].{Name:AlarmName,Actions:AlarmActions,State:StateValue}' \
  --profile agent_platform
```

### T2.19 restore-drill carry item

The T2.16b restore drill (`restore_drill` / `_restore_dump` in `ducklake_neon_smoke_test.py`)
restores a PLAIN-SQL dump via `psql`. The FP-B scheduled DR uses `--format=custom` which requires
`pg_restore`. The T2.19 restore-drill gate ("catalog rebuilt from the daily S3 pg_dump passes
read-your-write before cutover") MUST update the restore mechanism to `pg_restore`. This is a
T2.19 exit criterion; it is not a blocker for FP-B (FP-B produces dumps; production restore
drills are T2.19 scope).

## Section 5 -- ops_compaction decommission runbook (T2.19-gated)

**CURRENT STATE (Decision 84):** `ops_compaction` serves ONLY the not-yet-migrated staging
paths (`ops_session_log`, `ops_execution_plans`, telemetry). The migrated tables (recs,
decisions, priority_queue) never touch it -- their reads AND writes transit the DuckLake closed
boundary, and `sync_ops.drain` quarantines their outbox dirs. Do NOT disable or remove it before
the T2.26 disposition of the remaining tables (the rec-2113 restore drill gates the demolition).

The deprecation marker in `src/data/handlers/ops_compaction_handler.py` and the `notes` line in
`src/lambdas/ops-compaction/manifest.yaml` are informational only -- no behavioural change.

### T2.19-gated disable/removal sequence

Execute the following steps ONLY after T2.19 "DuckLake ops write/read migration" is complete and
the DuckLake writer is the proven live write path:

```yaml
decommission_steps:
  gate: T2.26 disposition of ops_session_log/ops_execution_plans complete + rec-2113 restore drill passed (Decision 84)
  steps:
    - id: 1
      action: Disable the S3 trigger on agent-platform-ops-compaction
      how: Remove aws_lambda_event_source_mapping or aws_s3_bucket_notification in terraform
      safety: Verify ops writes still land in DuckLake after disabling (read-your-write probe)
    - id: 2
      action: Retire the Lambda function (set reserved_concurrent_executions=0 or delete)
      how: terraform remove aws_lambda_function.ops_compaction (+ IAM role + log group)
      safety: Monitor ops_portal writes for 24h to confirm no regression
    - id: 3
      action: Archive the code (mark manifest status=retired)
      how: Set status=retired in src/lambdas/ops-compaction/manifest.yaml
    - id: 4
      action: File a Decision recording the retirement
      how: bin/venv-python -m scripts.ops_data_portal file_decision ...
  decision_required: true
  decision_refs: [78, 70]
```

Do NOT skip the 24h monitoring window (step 2) -- a partial cutover could leave a write path open
that drains to the old Iceberg store, causing ops data loss.

## Section 6 -- T2.19 ops cutover, rollback, and restore-drill (Decision 81 / Decision 82)

> **SUPERSEDED (Decision 84, 2026-06-11):** the `OPS_STORAGE_BACKEND` flag is retired; DuckLake is
> the sole ops backend and the commands below that set the flag are historical (the env var is
> ignored). Retained for the cutover audit trail only.

The ops persistence layer WAS selected by the `OPS_STORAGE_BACKEND` env flag, read by
`scripts/ops_data_portal.py`, `src/common/iceberg_reader.make_reader`, and
`scripts/data_quality_runner.py`:

| Value | Transport | Status |
|-------|-----------|--------|
| `ducklake` (**default**, signed off 2026-06-09) | closed `ducklake_writer` / `ducklake_reader` Function-URL boundary | the live recs backend |
| `iceberg` | `OpsWriter()` staging + Athena/Iceberg reader | rollback target; retained (intact, `ops_compaction` live) |

Scope: ONLY `ops_recommendations` is on DuckLake. `ops_decisions`, `ops_session_log`,
`ops_execution_plans`, `ops_priority_queue` remain on Athena/Iceberg (DEFERRED).

The Single-Portal caller surface (`file_rec`/`update_rec`/`file_decision`/`update_decision`/`sync`)
is identical on both backends -- only the transport underneath swaps.

### Cutover sequence -- HISTORICAL RECORD (performed 2026-06-09; seed tooling REMOVED at sign-off)

This is the sequence that performed the recs cutover. The one-time migration tooling -- the maintenance
`seed_ops_recommendations` action AND its `--emit-recs-seed-payload` payload emitter -- was REMOVED at
step 8 (closed boundary, Decision 81 cl.7), so steps 4 and 7 below are NOT directly re-runnable today.
**Re-seeding is now a break-glass operation: git-revert the sign-off removal commit (restores BOTH the
action and the emitter), redeploy maintenance, re-seed, then re-remove.** See "Break-glass re-seed" below.

```bash
# 1. Build the ducklake zips (writer, reader, maintenance, catalog-dr) and upload to S3.
bin/venv-python -m scripts.build_lambda --ducklake-only

# 2. Apply the IAM widening + DUCKLAKE_DATA_PATH smoke->prod flip. PRESENT THE PLAN TO A HUMAN FIRST.
#    The IAM change trips the Decision-77 fail-closed guard -> manual agent_platform_admin path.
terraform -chdir=terraform/personal plan      # review: no destroys (ops_compaction stays live)
terraform -chdir=terraform/personal apply      # via agent_platform_admin, after confirmation

# 3. Deploy the writer/reader code.
bin/venv-python -m scripts.build_lambda --ducklake-only --deploy

# 4. [seed tooling removed at step 8 -- break-glass only now] Drain the Iceberg outbox, then seed
#    DuckLake from Iceberg current-state + verify parity (excl. Decision-70 tombstones). The migration
#    seed was the maintenance `seed_ops_recommendations` action, fed by `--emit-recs-seed-payload`:
OPS_STORAGE_BACKEND=iceberg bin/venv-python -m scripts.ops_data_portal --sync
#   (historically) emit the payload + SigV4-invoke the maintenance seed action (parity=PASS in-Lambda).
#   NOTE: ~812 sequential SCD2 writes can approach the 300s Lambda timeout; if it times out, raise the
#   maintenance timeout temporarily (900s) and invoke synchronously (--cli-read-timeout 900, AWS_MAX_ATTEMPTS=1),
#   then restore. Re-seeding is idempotent (DROP+recreate); it also purges any leaked `test-*` selftest probe.

# 5. Sign-off gates (any FAIL stops the cutover -- Decision 55, never relax a budget):
bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-read-your-write     # write_ops->read; absent->409
bin/venv-python -m scripts.ducklake_neon_smoke_test --ops-churn-regate        # EC8 4-writer, 2000ms/0.20
OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.data_quality_runner   # DQ PASS (clause-8 incl.)
# NOTE: the pg_restore restore-drill (--catalog-restore-drill) is DEFERRED at sign-off -- see below.

# 6. Rollback rehearsal (both backends serve recs reads; Iceberg + ops_compaction intact):
OPS_STORAGE_BACKEND=iceberg  bin/venv-python -m scripts.ops_data_portal --selftest-read
OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-read
# NOTE (CC-web): the `iceberg` --selftest-read uses pyiceberg's direct-S3 (pyarrow) reader, which does
# NOT resolve the PlatformDev assume-role chain from CC-web (ACCESS_DENIED on the metadata HeadObject,
# even though the role + Athena CAN read it). The Iceberg rollback path is proven instead via Athena
# (`session_preflight._run_athena_query` / `sync_ops`), which IS the read-cache rebuild path. Data intact.

# 7. CUTOVER SIGN-OFF: flip the default to ducklake (the atomic doc + ROADMAP update lands with this),
#    then prove the portal write+read path on DuckLake:
OPS_STORAGE_BACKEND=ducklake bin/venv-python -m scripts.ops_data_portal --selftest-roundtrip
# The roundtrip leaves a throwaway `test-roundtrip-*` probe (automatable unset -> would fail DQ). At
# sign-off it was purged by re-running the step-4 seed. POST-REMOVAL there is no seed action, so if you
# run --selftest-roundtrip again you must purge the probe via the break-glass re-seed below, or avoid
# running it against the live backend (prefer OPS_STORAGE_BACKEND=iceberg for a throwaway proof).

# 8. POST-SIGN-OFF: remove the seed_ops_recommendations action (+ the --emit-recs-seed-payload emitter)
#    and redeploy maintenance -- the closed boundary now admits recs writes only via portal -> writer.
bin/venv-python -m scripts.build_lambda --ducklake-only --deploy
```

### Break-glass re-seed (post-removal)

The seed action and its emitter are no longer deployed. To re-seed DuckLake recs from Iceberg
current-state (e.g. catalog corruption with the Iceberg snapshot still intact):

1. `git revert` (or cherry-pick the pre-removal blob of) the sign-off commit that removed
   `action_seed_ops_recommendations` from `src/lambdas/ducklake_maintenance/handler.py` and
   `emit_recs_seed_payload` from `scripts/ducklake_neon_smoke_test.py`.
2. `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` to redeploy maintenance with the
   restored action.
3. Emit the payload + SigV4-invoke the maintenance `seed_ops_recommendations` action (idempotent
   DROP+recreate; ~812 writes may need the 900s-timeout workaround above).
4. Re-remove the action + emitter and redeploy to restore the closed boundary.
```

### Rollback (one step, real)

Set `OPS_STORAGE_BACKEND=iceberg` (env, or revert the default in the three flag sites). The portal
immediately resumes the `OpsWriter()`/Athena path; the Iceberg tables + `ops_compaction` are intact
(they were never retired). No data migration is needed to roll back. Re-run `scripts.ops_data_portal
--sync` to refresh the local cache from Iceberg (via Athena).

### Restore drill (CD.33 O-2 as amended by CD.34) -- DEFERRED at sign-off (Decision 81 cl.7)

**The `pg_restore` restore drill was NOT executed at the 2026-06-09 recs sign-off.** The pgclient
Lambda layer ships `pg_dump` but NOT `pg_restore` (adding it needs a non-CC-web operator AL2023-ABI
layer rebuild), so `--catalog-restore-drill` / the maintenance `restore_drill` action fail with
`FileNotFoundError: /opt/bin/pg_restore`. This deviation is ACCEPTED (human-directed) with compensating
controls:

1. The daily `pg_dump`-to-S3 export (`--format=custom`, `src/common/catalog_dr.run_catalog_dump`) runs.
2. A `>25h` freshness CloudWatch alarm fires if the daily export stops.
3. Neon's own native PITR / branch backups provide an independent restore path.
4. The Iceberg recs snapshot is retained as the flagged `OPS_STORAGE_BACKEND=iceberg` rollback target.

**HARD GATE (follow-up rec filed in this cutover's PHASE 3):** the `pg_restore` restore drill MUST pass
before the NEXT ops table migrates to DuckLake. When the pgclient layer ships `pg_restore`:

```bash
bin/venv-python -m scripts.ducklake_neon_smoke_test --catalog-restore-drill
# RESTORE helper: src/common/catalog_dr.build_pg_restore_cmd / run_pg_restore (--clean --exit-on-error).
```

### Closed boundary / break-glass (OQ.7, Decision 81 cl.7)

Every ops read transits `ducklake_reader`; every write transits `ducklake_writer`. There is NO Athena
escape hatch on the `ducklake` backend (`ops_data_portal` does not fall back to Athena when
`OPS_STORAGE_BACKEND=ducklake`). The only break-glass is the audited PlatformAdmin principal reading
the Neon catalog credential (Secrets Manager) + S3, plus the catalog-DR PITR export -- see Section 1.
