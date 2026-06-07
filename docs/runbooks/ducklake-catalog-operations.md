# DuckLake Catalog Operations Runbook

```yaml
runbook: ducklake-catalog-operations
tier: T2.17-T2.18
decisions: [81, 78, 37, 35, 77, 79, 62, 39]
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
  pinned_duckdb_version: "1.5.3"
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
- DuckDB `1.5.3` available locally (`bin/venv-python -c "import duckdb; print(duckdb.__version__)"`).
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

DuckLake `v1.0` is lockstep with DuckDB `1.5.3`: the catalog schema, the DuckLake extension, and the DuckDB
engine move together. The runtime asserts this at every connection
(`src/common/ducklake_runtime.py::assert_duckdb_version`, loud-fail `VersionMismatchError`), and the Lambda
layer pins `duckdb==1.5.3` exactly (`scripts/build_lambda.py::PINNED_DUCKDB_VERSION`). A version bump is
therefore a coordinated change across four surfaces, gated by a clone-rehearsal:

```yaml
version_bump_surfaces:
  - requirements.txt                                   # duckdb floor
  - scripts/build_lambda.py PINNED_DUCKDB_VERSION      # layer pin + extension URL/version
  - src/common/ducklake_runtime.py PINNED_DUCKDB_VERSION  # runtime assert
  - s3://agent-platform-data-lake/ducklake-extensions/<new-version>/  # re-seeded baked extensions
```

### Clone-rehearsal gate (mandatory before any production bump)

1. **Pin candidate.** Bump all four surfaces to the candidate `duckdb==X.Y.Z` / DuckLake version on a branch.
2. **Re-seed extensions.** Fetch `ducklake`/`httpfs`/`postgres_scanner` for `vX.Y.Z/linux_amd64` and upload to
   `s3://agent-platform-data-lake/ducklake-extensions/vX.Y.Z/` (the build's S3 fallback). Confirm the local
   DuckDB `X.Y.Z` can LOAD all three from a baked `extension_directory` with autoload/autoinstall OFF.
3. **Clone the catalog.** `pg_dump` the live Neon catalog into a scratch Neon database (the restore-drill
   path already does this). NEVER rehearse against the live catalog.
4. **Rehearse read+write on the clone.** Run the writer + reader smoke gates (`--lambda-*`) against a
   Lambda built on the candidate layer, pointed at the cloned catalog + a scratch DATA_PATH. All EC gates
   (attach, idempotency, partition, inlining, loud-fail, churn, reader) must pass on the new version.
5. **Compatibility decision.** If the clone rehearsal is green, file a Decision recording the bump and the
   rehearsal evidence, then roll the production layer. If it regresses, STOP -- do not bump; RCA the
   regression (Decision 55). Never relax the runtime version-assert to paper over a mismatch.

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

**Reading the alarm (FP-A):** the `ducklake-maintenance-circuit-breaker` CloudWatch alarm fires
when `MaintenanceBreakerTrip >= 1` in a 5-minute window. In T2.18 FP-A, `alarm_actions = []` --
no SNS page fan-out exists yet. You must CHECK the alarm state manually or via the CloudWatch
console. FP-B wires the alarm to a shared personal-account SNS topic.

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

The maintenance scope for T2.18 FP-A is `ducklake_smoke_*`. At T2.19, the scope GENERALISES to
the full `ducklake_ops` catalog and all real `ops_*` business tables. The code carries an explicit
constant (`MAINTENANCE_SCOPE_NOTE` in `src/common/ducklake_maintenance.py`) with the expansion
instructions. No code change is needed in the primitives themselves -- the table list is passed
in at call time.
