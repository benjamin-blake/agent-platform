# DuckLake Catalog Operations Runbook

```yaml
runbook: ducklake-catalog-operations
tier: T2.17
decisions: [81, 78, 37, 35, 77]
exit_criteria: [EC3, EC12]
sections:
  - id: 1
    title: PlatformAdmin break-glass catalog-attach (inspect/repair)
    control: CD.33 O-1
  - id: 2
    title: OQ.12 DuckLake/DuckDB version-bump clone-rehearsal policy
    control: OQ.12
catalog:
  backend: Neon serverless Postgres (DIRECT endpoint, sslmode=require)
  dsn_secret: ducklake-neon-catalog-dsn
  dsn_secret_arn_output: ducklake_neon_catalog_dsn_secret_arn
  meta_schema: ducklake_ops
  catalog_alias: ops_catalog
  data_path: s3://agent-platform-data-lake/ducklake-runtime-smoke/
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
con = rt.open_connection(dsn=dsn, data_path="s3://agent-platform-data-lake/ducklake-runtime-smoke/")
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
