# Plan

## Intent
Stand up the first Lambda functions in the personal AWS account -- `ducklake_writer` + `ducklake_reader` --
that ATTACH to the live Neon serverless-Postgres DuckLake catalog over TLS with DuckDB extensions pre-baked
into a layer and versions pinned, then prove the CD.33 runtime primitives (idempotent ULID/MERGE append,
`current` write-through projection, schema gate, OCC retry, partition prune, inlining disabled) via in-Lambda
smoke tests. This implements platform roadmap tier-item **T2.17** and contributes to the North Star by making
the DuckLake operational lakehouse runnable -- the substrate every future self-improvement write lands on.
It also finally MEASURES the in-region Lambda->Neon connection+commit latency that T2.16b's churn gate could
only project.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (deploys new Lambda functions to the personal account and invokes them via AWS_IAM-signed Function URLs
against the live Neon catalog + S3; smoke gates are tagged `[post-deploy]`).

## Plan Path
docs/plans/PLAN-ducklake-lambda-runtime.md

## Phase
Platform roadmap **T2** (full state migration to personal account). T2.17 builds the DuckLake Lambda runtime;
its dependencies T2.16 (RDS catalog, complete 2026-06-03) and T2.16b (Neon migration + RDS retirement,
complete 2026-06-05) are both done. The maintenance pipeline (T2.18) and the production ops write/read cutover
+ DQ + DR drill (T2.19 / FP-B) remain downstream and are explicitly OUT of scope here.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `config/lambda/ducklake/field_semantics.yaml` | Create | **Field Semantics Contract** -- machine-readable map of every SCD2-envelope field to `input` vs `derived` + the exact derivation rule, key role, partition role, nullability. Drives the schema gate, the derivation engine, and the per-field verification. Bundled as an asset into both Lambda zips. |
| `src/common/ducklake_runtime.py` | Create | Single ATTACH/connection authority + the CD.33 write/read primitives: Secrets-Manager DSN fetch, baked-extension connection, version-assert, ULID/timestamp minting, schema gate, `write_scd2` shared merge helper (history INSERT-if-not-matched-on-ULID + `current` MERGE in one txn) with bounded OCC retry, partitioned-table DDL, inlining-off, CloudWatch metrics, `read_current`. |
| `src/lambdas/ducklake_writer/__init__.py` | Create | Package marker. |
| `src/lambdas/ducklake_writer/handler.py` | Create | Writer Lambda entrypoint; action dispatch (`attach_check`, `create_tables`, `write`, `idempotency_probe`, `partition_probe`, `inlining_probe`, `churn`); accepts `force_recreate_tables`. Write-scoped role. |
| `src/lambdas/ducklake_writer/manifest.yaml` | Create | CD.24 per-Lambda manifest (`status: active`, `artifact: ducklake-writer.zip`). |
| `src/lambdas/ducklake_reader/__init__.py` | Create | Package marker. |
| `src/lambdas/ducklake_reader/handler.py` | Create | Reader Lambda entrypoint; actions (`attach_check`, `read_current`, `partition_prune_check`); read-only. Read-scoped role. |
| `src/lambdas/ducklake_reader/manifest.yaml` | Create | CD.24 per-Lambda manifest (`status: active`, `artifact: ducklake-reader.zip`). |
| `config/lambda/ducklake-writer/.gitkeep` | Create | Per-Lambda config dir (manifest `config:` entry). |
| `config/lambda/ducklake-reader/.gitkeep` | Create | Per-Lambda config dir. |
| `scripts/build_lambda.py` | Modify | Add `PINNED_DUCKDB_VERSION="1.5.3"`, `build_ducklake_deps_layer()` (duckdb==1.5.3 + psycopg2-binary + python-ulid), `build_ducklake_extensions_layer()` (stage ducklake/httpfs/postgres `.duckdb_extension` for v1.5.3/linux_amd64), and writer/reader into the build + function-name->S3-key deploy map + layer S3 upload; **add a hard 262 MB zip+layer size assertion that fails the build** (today there is only a non-fatal WARN at >250 MB on the deps layer -- the CLAUDE.md-recommended hard assert does not yet exist). |
| `scripts/lambda_manifest.py` | Modify | Add an `excludes: list[str]` field to the `LambdaManifest` schema and honour it in `stage_bundle()` (skip excluded paths during copy), `compute_affected_artifacts()` (excluded changed files do not mark the artifact affected), and `derive_lambda_file_patterns()`. This keeps the new DuckLake code out of the `data-pipeline`/`ops-compaction` zips and out of their affected-set. |
| `src/lambdas/data-pipeline/manifest.yaml` | Modify | Add `excludes: [src/common/ducklake_runtime.py, src/lambdas/ducklake_writer, src/lambdas/ducklake_reader]` so the wildcard `includes: - src/` no longer drags DuckLake runtime code into `data-pipeline.zip`. |
| `src/lambdas/ops-compaction/manifest.yaml` | Modify | Same `excludes` -- preserves the deliberately-minimal `ops-compaction` zip (262 MB ceiling) and the closed boundary. |
| `tests/test_lambda_manifest.py` | Modify | Cover the `excludes` field: schema acceptance, `stage_bundle` skipping, and `compute_affected_artifacts` filtering. |
| `scripts/ducklake_neon_smoke_test.py` | Modify | Delegate the ATTACH/connection to `ducklake_runtime` (one implementation, no drift); add `--lambda-attach`, `--lambda-idempotency`, `--lambda-partition`, `--lambda-inlining`, `--lambda-churn`, `--lambda-ingress`, `--lambda-reader` SigV4 Function-URL invoke gates. |
| `requirements.txt` | Modify | Add `python-ulid` pin; annotate the duckdb floor as lockstep-pinned to `==1.5.3` in the Lambda layer (the repo floor stays `>=1.5.3`; the Lambda layer pins exact and the runtime asserts equality). |
| `terraform/personal/ducklake_lambdas.tf` | Create | Two Lambda functions, write/read-scoped execution roles, `ducklake-deps` + `ducklake-extensions` layer versions, Function URLs (`authorization_type=AWS_IAM`), CloudWatch log groups, Secrets-Manager read grant on the DSN ARN, outputs. |
| `terraform/personal/platform_roles.tf` | Modify | PlatformAdmin break-glass grant: `secretsmanager:GetSecretValue` on the DSN ARN + `s3:GetObject`/`ListBucket` on the ducklake prefix (CD.33 O-1). IAM change -- human-gated apply. |
| `docs/runbooks/ducklake-catalog-operations.md` | Create | Two structured sections: (1) PlatformAdmin catalog-attach inspect/repair break-glass runbook (CD.33 O-1); (2) OQ.12 DuckLake/DuckDB version-bump clone-rehearsal policy. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Correct "DuckDB 1.5.2" -> "1.5.3" in all occurrences + the OQ.12 note (deliberate amendment per the spike-validated pair); set T2.17 `status: complete` + `completed_at` + `progress_note` at the end. |
| `tests/test_ducklake_runtime.py` | Create | 100% coverage of `ducklake_runtime` (derivations, schema gate, OCC retry loud-fail, version-assert, partition DDL). |
| `tests/test_ducklake_writer_handler.py` | Create | 100% coverage of the writer handler (action dispatch, mocked runtime). |
| `tests/test_ducklake_reader_handler.py` | Create | 100% coverage of the reader handler. |
| `tests/test_ducklake_neon_smoke_test.py` | Modify | Update for the delegation refactor + the new in-Lambda invoke gates (mocked). |
| `tests/test_build_lambda.py` | Modify | Cover the two new layer-build functions + writer/reader build/deploy wiring (mocked subprocess/network). |

## Bundled Recommendations
None bundled as required. Aligned-but-optional (surfaced, not included): rec-2034 (thread `profile` kwarg
through `ducklake_spike.handler()`) and rec-2087 (Neon free-tier public-endpoint egress posture). rec-2087 is
a posture concern better resolved alongside the T2.19 closed-boundary work; rec-2034 touches spike code not in
this runtime's hot path. Leave both open.

## Infrastructure Dependencies
| Resource | Type | Apply path | Timing |
|----------|------|------------|--------|
| `aws_iam_role.ducklake_writer` / `.ducklake_reader` (+ inline policies) | New IAM roles | **Human-gated** via `agent_platform_admin`. New IAM roles trip the Decision-77 deterministic guard (`scripts/terraform_apply_guard.py`, fail-closed on any IAM/trust change), so the whole `terraform/personal` apply for this change routes to the manual `agent_platform_admin` path, NOT push-to-main auto-apply (Decision 35 + Decision 77). | **Pre-deploy.** IAM must precede `build_lambda --deploy` (terraform CLAUDE.md IAM-precedence rule). |
| PlatformAdmin break-glass grant (`platform_roles.tf`) | IAM policy change | Human-gated via `agent_platform_admin` (same guard trip). | Pre-deploy. |
| `aws_lambda_layer_version.ducklake_deps` / `.ducklake_extensions` | New layers (from S3) | Same human-gated apply. The layer zips are uploaded to S3 by `build_lambda` BEFORE the apply. | Pre-deploy; the layer S3 objects must exist at plan/apply time (`try()`-guard the hash). |
| `aws_lambda_function.ducklake_writer` / `.ducklake_reader` | New functions (from S3) | Same human-gated apply. `s3_key = lambda-packages/ducklake-{writer,reader}.zip`; `source_code_hash` wrapped in `try()` per terraform CLAUDE.md. | Pre-deploy apply creates the functions; `build_lambda --deploy` then updates code. |
| `aws_lambda_function_url.*` (AWS_IAM) | New Function URLs | Same apply. | Pre-deploy. |
| `aws_cloudwatch_log_group.*` | New log groups | Same apply. | Pre-deploy. |

**Handler convention:** both handlers accept a `force_recreate_tables` event field (idempotent re-run of the
table-DDL smoke path), satisfying the Lambda `force_{param}` convention.

**Affected-artifact assessment (Decision 79 / CD.24):** the existing `data-pipeline` + `ops-compaction`
manifests declare `includes: - src/`, so without intervention every new `src/...` file marks them affected (and
copies the DuckLake source into their zips). This plan adds a manifest `excludes` field and sets it on both,
so `compute_affected_artifacts(<this plan's scope files>)` returns **exactly `{ducklake_writer, ducklake_reader}`**.
Only those two active artifacts are built/deployed/smoke-tested; `data-pipeline` and `ops-compaction` are NOT
rebuilt or redeployed (verified by VP). DuckDB/psycopg2/ulid live ONLY in the `ducklake-deps` layer attached to
the two new functions -- never in the existing zips.

**Build/apply/deploy ordering (chicken-and-egg resolution):**
1. `build_lambda --skip-upload=false` (no `--deploy`): build + upload the two function zips AND the two layer
   zips to `s3://<bucket>/lambda-packages/`.
2. `terraform -chdir=terraform/personal plan` -> present to human -> human-gated `apply` via
   `agent_platform_admin` (creates roles, layers, functions referencing the S3 objects, Function URLs, log
   groups, break-glass grant).
3. `build_lambda --deploy` updates the function code from S3.
4. Run the `[post-deploy]` in-Lambda smoke gates.

## Field Semantics Contract (the handhold surface)
This is the artifact the human is walked through field-by-field BEFORE any table DDL or write path is written
(see Constraints + Ordered Step 2). It is realised as `config/lambda/ducklake/field_semantics.yaml` and is the
single source the schema gate, the derivation engine, and the verification assertions all read.

Representative SCD2 smoke-table pair (real `ops_*` business schema is T2.19): `ducklake_smoke_history` (append
source of truth) + `ducklake_smoke_current` (Type-1 write-through projection), in META_SCHEMA `ducklake_ops`,
DATA_PATH `s3://agent-platform-data-lake/ducklake-neon-smoke/` (the live catalog's init-pinned path;
the data_path is fixed at catalog-init and DuckLake's OVERRIDE_DATA_PATH does not persist, so code
aligns to the stored path).

| Field | Role | Deterministic derivation | Key / partition role | Nullable | Verified by |
|-------|------|--------------------------|----------------------|----------|-------------|
| `ulid` | derived | Monotonic ULID minted **once at op start, OUTSIDE the OCC-retry loop**; reused on every retry | `history` logical PK; idempotency key | no | VP idempotency probe: retry -> identical ULID -> MERGE dedups to 1 row |
| `rec_id` | input | DynamoDB-allocated upstream; validated exist (update) / not-exist (new) | natural key + `current` MERGE key | no | VP current-uniqueness: same `rec_id` x2 -> 1 current row, 2 history rows |
| `created_timestamp` | derived | `now()` at first insert; **carried unchanged on update (never re-stamped)** | `history` partition: `day(created_timestamp)` | no | VP partition probe: update -> same day-partition; date-filter prunes |
| `last_updated_timestamp` | derived | High-precision `now()` minted **once outside the retry loop**, stable per write | SCD2 ordering (tiebreak by `ulid`) | no | VP: stable across retries; latest-per-id deterministic |
| `payload` | input | none (opaque business field stand-in) | -- | yes | VP schema gate: unknown/mis-typed field -> loud-fail |

Partition transforms (applied via `ALTER ... SET PARTITIONED BY` at table creation, BEFORE first write --
post-ALTER-only semantics M-5): `history` -> `day(created_timestamp)`; `current` -> `bucket(8, rec_id)`.
Inlining disabled: `ducklake_default_data_inlining_row_limit = 0` set on the connection before first write.

## Acceptance Criteria
Mapped 1:1 to the 13 T2.17 `exit_criteria` bullets in `docs/ROADMAP-PLATFORM.yaml` (the block at ~lines
3465-3477; EC# = bullet order):
- [ ] (EC1) DuckLake Lambdas reach the Neon catalog over TLS (no VPC attach); ATTACH succeeds in the Lambda
      execution context with `sslmode=require` + SNI on pinned DuckDB 1.5.3.
- [ ] (EC2) `ducklake`+`httpfs`+`postgres` extensions pre-baked in a Lambda layer; `autoinstall_known_extensions`
      + `autoload_known_extensions` disabled; `custom_extension_repository` set fail-closed; no network INSTALL
      at runtime.
- [ ] (EC3) DuckLake v1.0 + DuckDB **1.5.3** pinned lockstep; a runtime version-assert fails loudly on mismatch;
      OQ.12 clone-rehearsal version-bump policy documented.
- [ ] (EC4) Function-URL + AWS_IAM ingress confirmed unaffected by the no-VPC config (unsigned -> 403; SigV4 from
      the function's role -> 200).
- [ ] (EC5) Per-Lambda CD.24 manifests filed for `ducklake_writer` and `ducklake_reader` (`status: active`).
- [ ] (EC6) Partition-prune smoke test: a date-filtered query against the ALTER-partitioned `history` table
      demonstrably prunes partitions; the `current` lookup/MERGE scan footprint is bounded.
- [ ] (EC7) `ducklake_writer` fails loudly on schema-gate rejection and OCC-retry exhaustion; no silent drop.
- [ ] (EC8) Connection handling per the T2.16b gate: catalog writes use the Neon DIRECT endpoint; in-region
      Lambda churn + commit latency measured and within the CD.33 OCC budget (the real measurement).
- [ ] (EC9) OCC-retry count + commit-latency metrics emitted to CloudWatch.
- [ ] (EC10) Idempotent append verified: a retried write reuses its ULID and MERGE-on-ULID de-duplicates (no
      double-append); ULID + `last_updated_timestamp` minted once, outside the OCC-retry loop.
- [ ] (EC11) Inlining disabled for the smoke tables: `ducklake_default_data_inlining_row_limit=0` honoured on
      1.5.3 (smoke-test upstream issue #921); concurrency probe covers issues #233/#376.
- [ ] (EC12) PlatformAdmin break-glass: granted the Neon DSN secret + S3 read; a DuckDB catalog-attach
      inspect/repair runbook exists and is drilled.
- [ ] (EC13) Per-Lambda build + deploy + smoke-test for `ducklake_writer` and `ducklake_reader` (V3).
- [ ] Affected-artifact hygiene: `compute_affected_artifacts(<scope src files>)` returns exactly
      `{ducklake_writer, ducklake_reader}`; the `data-pipeline`/`ops-compaction` bundles gain no
      `ducklake_runtime`/`ducklake_writer`/`ducklake_reader` paths (DuckDB/psycopg2/ulid stay in the
      `ducklake-deps` layer only).
- [ ] `build_lambda.py` hard-fails (non-zero exit) if any function zip or layer exceeds the 262 MB Lambda limit.
- [ ] Single-Portal NOTE honoured: no `ops_*` governance table is writable via the T2.17 Function URLs (smoke
      tables only); production portal wiring deferred to T2.19 (Decision 78/81).
- [ ] `bin/venv-python -m scripts.validate` passes.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Field Semantics Contract well-formed: every `derived` field carries a non-empty `derivation` | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('config/lambda/ducklake/field_semantics.yaml')); f=d['fields']; assert all(v.get('derivation') for v in f.values() if v['role']=='derived'), [k for k,v in f.items() if v['role']=='derived' and not v.get('derivation')]; print('FIELDS_OK')"` | prints `FIELDS_OK` | add the missing derivation rule |
| 2 | pre-deploy | `ducklake_runtime` unit suite (derivations, schema gate, OCC loud-fail, version-assert, partition DDL) at 100% | `bin/venv-python -m pytest tests/test_ducklake_runtime.py -q` | pass | fix derivation/gate/retry logic |
| 3 | pre-deploy | The discriminating derivation/gate tests exist **by name** (not via fragile `-k` selectors -- repo "Pytest -k" gotcha): ULID-once-outside-retry, ULID-stable-across-retry, created-carried-on-update, last_updated-once, schema-gate-raises, OCC-exhaustion-raises | `bin/venv-python -c "import pathlib; s=pathlib.Path('tests/test_ducklake_runtime.py').read_text(); req=['ulid_minted_once_outside_retry','ulid_stable_across_retry','created_timestamp_carried_on_update','last_updated_minted_once','schema_gate_raises_on_unknown_field','occ_retry_exhaustion_raises']; missing=[r for r in req if f'def test_{r}' not in s]; assert not missing, missing; print('DERIV_TESTS_PRESENT')"` | prints `DERIV_TESTS_PRESENT` | add the missing test(s) by the exact name |
| 4 | pre-deploy | Handlers covered; manifests parse + are `status: active` | `bin/venv-python -m pytest tests/test_ducklake_writer_handler.py tests/test_ducklake_reader_handler.py -q && bin/venv-python -c "from scripts.lambda_manifest import load_all; m=load_all(); assert m['ducklake_writer'].status=='active' and m['ducklake_reader'].status=='active'; print('MANIFEST_OK')"` | pass + `MANIFEST_OK` | fix handler/manifest |
| 5 | pre-deploy | **Affected-artifact set** (Decision 79): only the two new slugs are affected by this plan's `src/` changes | `bin/venv-python -c "from scripts.lambda_manifest import compute_affected_artifacts as c; a=set(c(['src/common/ducklake_runtime.py','src/lambdas/ducklake_writer/handler.py','src/lambdas/ducklake_reader/handler.py'])); assert a=={'ducklake_writer','ducklake_reader'}, a; print('AFFECTED_OK')"` | prints `AFFECTED_OK` | add/fix the `excludes` on data-pipeline/ops-compaction |
| 6 | pre-deploy | **No-bloat**: neither existing zip gains DuckLake code | `bin/venv-python -c "import subprocess as s; out=s.check_output(['bin/venv-python','-m','scripts.build_lambda','--list-bundle','data-pipeline']).decode()+s.check_output(['bin/venv-python','-m','scripts.build_lambda','--list-bundle','ops-compaction']).decode(); assert 'ducklake_runtime' not in out and 'ducklake_writer' not in out and 'ducklake_reader' not in out, 'BLOAT'; print('NO_BLOAT')"` | prints `NO_BLOAT` | honour `excludes` in `stage_bundle` |
| 7 | pre-deploy | **Extension availability** for the baked-from-URL path (v1.5.3/linux_amd64); else the operator-seeded S3 fallback exists | `bin/venv-python -c "import urllib.request as u; [u.urlopen('https://extensions.duckdb.org/v1.5.3/linux_amd64/%s.duckdb_extension.gz' % e).close() for e in ('ducklake','httpfs','postgres')]; print('EXT_AVAIL_URL')"` | prints `EXT_AVAIL_URL`; OR (egress blocked) `aws s3 ls s3://agent-platform-data-lake/ducklake-extensions/v1.5.3/ --profile agent_platform` lists 3 `.duckdb_extension` files | if neither, seed the S3 fallback from a network-permitted host (Step 0) |
| 8 | pre-deploy | Build the zips + layers (no deploy); extensions layer holds the 3 pinned extensions | `bin/venv-python -m scripts.build_lambda --skip-upload && bin/venv-python -c "import zipfile,glob; z=zipfile.ZipFile(sorted(glob.glob('lambda-packages/ducklake-extensions*-layer.zip'))[-1]); names='\n'.join(z.namelist()); assert all(f'duckdb_extensions/v1.5.3/linux_amd64/{e}.duckdb_extension' in names for e in ('ducklake','httpfs','postgres')), names; print('EXT_LAYER_OK')"` | builds; prints `EXT_LAYER_OK` | fix layer staging / extension fetch |
| 9 | pre-deploy | `build_lambda` unit suite incl. the **hard 262 MB size assert** (raises on oversize) + the two new layer builders | `bin/venv-python -m pytest tests/test_build_lambda.py -q` | pass | add the `sys.exit`/raise size guard; fix layer builders |
| 10 | pre-deploy | Terraform validates + plan is presentable | `terraform -chdir=terraform/personal init -backend=false -input=false >/dev/null && terraform -chdir=terraform/personal validate` | `Success! The configuration is valid.` | fix HCL |
| 11 | pre-deploy | Full presubmit (identical to CI) | `bin/venv-python -m scripts.validate` | PASS | address before merge |
| 12 | post-deploy | **ATTACH-in-Lambda**: writer Function URL `attach_check` -> ATTACH ok, `duckdb.__version__==1.5.3`, extensions loaded from `/opt` (not network); reports connect+commit ms | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-attach` | `LAMBDA_ATTACH OK version=1.5.3 source=layer connect_ms=<n> commit_ms=<n>` | inspect CloudWatch logs; fix extension_directory / DSN / role |
| 13 | post-deploy | **AWS_IAM ingress** unaffected: unsigned -> 403, SigV4 -> 200 (EC4) | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-ingress` | `INGRESS OK unsigned=403 signed=200` | check Function-URL auth type |
| 14 | post-deploy | **Idempotent append** (EC10): retried write reuses ULID; MERGE dedups to 1 history row | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-idempotency` | `IDEMPOTENCY OK ulid_reused=true history_rows=1 current_rows=1` | hoist ULID mint; fix MERGE-on-ULID |
| 15 | post-deploy | **Partition prune** (EC6) with a concrete predicate: date-filtered `history` query scans fewer files than total; single-key `current` lookup touches <=1 bucket-partition and scans fewer than total current files | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-partition` | `PARTITION OK history_pruned=true history_files_scanned<history_total current_partitions_scanned<=1 current_files_scanned<current_total` | confirm ALTER-before-first-write; `day(created_timestamp)` / `bucket(8,rec_id)` |
| 16 | post-deploy | **Inlining disabled** (EC11): `inlined_rows=0`; S3 Parquet present immediately; concurrency probe clean | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-inlining` | `INLINING OK inlined_rows=0 s3_parquet>=1 occ_conflicts_handled=true` | set row_limit=0; smoke #921/#233/#376 |
| 17 | post-deploy | **Schema-gate + OCC loud-fail in Lambda** (EC7): bad field -> 4xx with raised error; forced retry-exhaustion -> loud 5xx, no silent drop | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-loudfail` | `LOUDFAIL OK schema_reject=raised occ_exhaust=raised silent_drop=false` | ensure raise, not swallow |
| 18 | post-deploy | **In-region churn/latency** (EC8): concurrent writers on the DIRECT endpoint; p95 within CD.33 budget | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-churn` | `CHURN OK collision_rate<=0.20 p95_commit_ms<=2000 endpoint=direct` (numbers reported) | if p95 fails from in-region, RCA the latency (Decision 55), do not silently relax the budget |
| 19 | post-deploy | **Closed reader path** (EC1/boundary): reader returns `current` rows; reader role cannot write | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-reader` | `READER OK rows>=1 write_denied=true` | scope the read role read-only |
| 20 | post-deploy | **Metrics** (EC9): OCC-retry + commit-latency metrics present in CloudWatch after the writes | `aws cloudwatch list-metrics --namespace DuckLakeWriter --profile agent_platform --region eu-west-2 --query "Metrics[?MetricName=='OccRetryCount'||MetricName=='CommitLatencyMs'].MetricName" --output text` | both metric names listed | add `PutMetricData` emit |
| 21 | post-deploy | **Break-glass drill** (EC12): PlatformAdmin attaches the catalog read-only and inspects per the runbook | `bin/venv-python -m scripts.ducklake_neon_smoke_test --restore-drill` then follow `docs/runbooks/ducklake-catalog-operations.md` Section 1 attach step under `agent_platform_admin` | runbook attach + inspect succeeds; read-your-write verified | fix the grant / runbook step |

## Constraints
- **Handhold gate (human request):** Before writing any table DDL or the `write_scd2` path, the implementer
  MUST present the Field Semantics Contract and walk the human through EACH field's role and derivation, and
  get explicit confirmation. Every `derived` field must have (a) a derivation rule in the YAML and (b) a unit
  assertion. Deterministic fields (`ulid`, `created_timestamp`, `last_updated_timestamp`, partition transforms)
  are derived exactly once and in the right place (mint outside the OCC-retry loop; `created_timestamp` carried,
  never re-stamped).
- **Single-Portal invariant (Decision 78/81):** the AWS_IAM Function URLs are a T2.17 smoke-test ingress ONLY.
  No `ops_*` governance table is writable via this path; production writes still transit
  `scripts/ops_data_portal.py` -- wiring is deferred to T2.19. Add an explicit deferral note in the writer
  handler docstring citing Decision 78/81.
- **Loud-fail, no rescue loops (Decision 55):** schema-gate rejection and OCC-retry exhaustion raise; never a
  silent drop or Athena fallback. The baked-extension posture is fail-closed (no network INSTALL).
- **Version lockstep (OQ.12):** the Lambda layer pins `duckdb==1.5.3` and the extension binaries are built for
  v1.5.3/linux_amd64; a runtime assert (`duckdb.__version__ == PINNED_DUCKDB_VERSION`) fails loudly on mismatch.
  A version bump follows the clone-rehearsal policy in the runbook.
- **Terraform (Decision 35 + 77):** new IAM roles + the break-glass grant trip the fail-closed guard; apply is
  human-gated via `agent_platform_admin` and precedes any code deploy. `filemd5()`/`file()` on the zips/layers
  wrapped in `try()`. ASCII hyphens only in tag values.
- **Lambda packaging (Decision 79 / CD.24 / CD.16):** both manifests `status: active`; deps in dedicated layers
  (`ducklake-deps`, NOT the data-pipeline deps layer). Stay under the ~262 MB zip+layers limit -- this plan ADDS
  a hard size assertion to `build_lambda.py` that fails the build on breach (today there is only a non-fatal
  `WARN` at >250 MB on the deps layer; the CLAUDE.md-recommended hard assert does not yet exist -- do not lean
  on a guard that is not there).
- **Affected-artifact hygiene (Decision 79 / CD.24):** the new DuckLake code is kept out of `data-pipeline` and
  `ops-compaction` via a manifest `excludes` field, so `compute_affected_artifacts(<scope>)` returns ONLY
  `ducklake_writer` + `ducklake_reader` and the two existing prod Lambdas are neither bloated nor redeployed.
  This preserves the deliberately-minimal `ops-compaction` zip and the closed boundary.
- **Test coverage:** every new source file gets a test file at 100% coverage (`test_coverage_checker`). Mock
  `duckdb`, `boto3`, and `subprocess`/network in unit tests; never invoke the live catalog from unit tests.
- **Agent-first:** the Field Semantics Contract and the runbook are the only new docs; both are structured.
  Correct the roadmap's native YAML; do not add a companion narrative doc.
- Python 3.12+, type hints, `async` for I/O where applicable; ruff line length 127; no emojis; `bin/venv-python`
  for all Python; bash only.

## Context
- **Why now:** T2.16 + T2.16b are complete; Neon is live (DSN secret `ducklake-neon-catalog-dsn` with outputs
  `ducklake_neon_catalog_dsn_secret_arn` + `ducklake_neon_catalog_host_direct`); CD.33 runtime architecture is
  ratified (Decision 81). T2.17 is `next_eligible` on the platform roadmap.
- **First Lambda in the personal account:** `terraform/personal/` currently has only IAM roles -- no Lambda /
  Function-URL / layer pattern. This plan establishes it. Model packaging on `src/lambdas/data-pipeline` +
  `ops-compaction` (manifest SSOT) and the existing `build_deps_layer()` layer build.
- **Reuse, no drift:** `scripts/ducklake_neon_smoke_test.py::_open_attached/fetch_dsn/_libpq_conninfo` already
  implement the Neon TLS ATTACH (`ATTACH 'ducklake:postgres:{conninfo}' AS ops_catalog (DATA_PATH ...,
  META_SCHEMA 'ducklake_ops')`). These move into `ducklake_runtime` and the smoke test imports them, so there
  is ONE ATTACH implementation. The dev path uses network `INSTALL`; the Lambda path uses the baked layer
  (`extension_directory` + autoload off + `custom_extension_repository` fail-closed) -- one function, an
  `extension_directory` parameter selects the mode.
- **Version (resolved):** the spike validated **DuckDB 1.5.3** (`docs/ducklake-spike-findings.md` metrics) and
  `requirements.txt:13` floors `duckdb>=1.5.3`. The roadmap text "1.5.2" is an authoring error; this plan pins
  1.5.3 and corrects the roadmap as a deliberate amendment (human-confirmed).
- **Latency is the headline risk:** T2.16b's churn gate passed the OCC-collision sub-gate but the latency
  sub-gate was NOT MET in any available test env (residential p95 ~4.7s; CC-web TCP/5432 egress-blocked) and was
  waived-with-rationale on the projection that an in-region Lambda strips residential RTT. VP step 18 is the
  first real in-region measurement; if it fails, RCA the latency (Decision 55) -- do NOT silently relax the
  CD.33 budget constants.
- **Affected-artifact exclusion (why the `excludes` field):** the existing stub lambdas already land in
  `data-pipeline.zip` via its wildcard `includes: - src/`; adding `src/common/ducklake_runtime.py` +
  `src/lambdas/ducklake_*` would therefore mark `data-pipeline` AND `ops-compaction` as affected (and copy
  DuckLake source into them). Rather than redeploy two unrelated prod Lambdas, this plan adds a manifest
  `excludes` field (honoured in `stage_bundle`, `compute_affected_artifacts`, `derive_lambda_file_patterns`)
  and sets it on both -- the architecturally correct fix that keeps `ops-compaction` minimal and the boundary
  closed (plan-critique blocking finding 1).
- **Extension-fetch pre-flight + vendored fallback (ownership):** `build_ducklake_extensions_layer()` fetches
  the `.duckdb_extension` files from `https://extensions.duckdb.org/v1.5.3/linux_amd64/`. The spike proved 1.5.3
  via network `INSTALL`, not via this baked-from-URL path, so Step 0 (pre-flight) verifies all three of
  `ducklake`/`httpfs`/`postgres` are published for that exact build. If the build host's egress to
  `extensions.duckdb.org` is blocked (the same egress class that motivated baking), the OPERATOR seeds the
  vendored fallback `s3://agent-platform-data-lake/ducklake-extensions/v1.5.3/` from a network-permitted host
  BEFORE the build; the build then prefers the S3 fallback. VP step 7 gates this (plan-critique should-fix 3).
- **Size assert added (not assumed):** there is no hard size assertion in `build_lambda.py` today (only a
  non-fatal `WARN`); this plan adds the CLAUDE.md-recommended hard assert and a unit test (VP step 9)
  (plan-critique blocking finding 2).
- **Decision flags (scout, FLAGS_FOUND, both NOTE):** (1) Single-Portal -- handled by the smoke-table scope +
  deferral note above; (2) version pin -- resolved to 1.5.3 by human decision.
- **Decisions cited:** 81 (CD.33 runtime arch), 78 (DuckLake adoption), 79 (per-Lambda deploy gating), 77
  (sandbox auto-apply guard), 35 (terraform human-gate), 37 (Secrets Manager runtime-fetch), 48 (V3 tier), 55
  (loud-fail). Related: 67, 69 (invariant carried by 78), 44 (`build_lambda` is not executor machinery).
- **Out of scope (downstream tiers):** the `ducklake_maintenance` Lambda (T2.18); production `ops_*` table
  cutover, `ops_data_portal` transport swap, DQ enforcement, DR restore drill, closed-boundary production
  verification (T2.19 / FP-B).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `claude/...`).
- [ ] `docs/PROJECT_CONTEXT.md` read.
- [ ] `docs/DECISIONS.md` decisions 81/78/79/77/35/37/48/55 reviewed (via the cited summaries).
- [ ] All Scope-table files located/readable; `scripts/ducklake_neon_smoke_test.py`, `src/common/ducklake_spike.py`,
      `scripts/build_lambda.py`, `scripts/lambda_manifest.py`, `terraform/personal/neon_ducklake_catalog.tf` read.
- [ ] `aws sts get-caller-identity --profile agent_platform` succeeds (post-deploy gates + smoke tests).
- [ ] `agent_platform_admin` available for the human-gated terraform apply.
- [ ] Acceptance Criteria + the 13 EC mapping understood and verifiable.

## Ordered Execution Steps
0. **Pre-flight: extension availability + fallback seeding (VP step 7).** Confirm `ducklake`, `httpfs`, and
   `postgres` are all published downloadable extensions for the exact `v1.5.3/linux_amd64` build at
   `extensions.duckdb.org` (the spike proved 1.5.3 via network `INSTALL`, not the baked-from-URL path). If the
   build host's egress to `extensions.duckdb.org` is blocked OR any extension is unpublished for that build,
   the OPERATOR seeds the vendored fallback `s3://agent-platform-data-lake/ducklake-extensions/v1.5.3/` (the
   three `.duckdb_extension` files) from a network-permitted host before the layer build. Do not proceed to the
   layer build until one source is confirmed.
1. **Pins.** `requirements.txt`: add a `python-ulid` pin; annotate the `duckdb>=1.5.3` floor noting the Lambda
   layer pins `==1.5.3` (lockstep). No other floor changes.
2. **Field Semantics Contract.** Author `config/lambda/ducklake/field_semantics.yaml` (the table above).
   **HANDHOLD GATE:** present it to the human, walk through each field's role + derivation, get explicit
   confirmation before proceeding. Do not write table DDL until confirmed.
3. **`src/common/ducklake_runtime.py`.** Implement: `fetch_dsn`/`libpq_conninfo` (moved from the smoke test);
   `open_connection(*, dsn, extension_directory=None, data_path, profile=None)` (baked-extension mode when
   `extension_directory` set: `SET extension_directory`, `autoinstall_known_extensions=false`,
   `autoload_known_extensions=false`, `custom_extension_repository=''`, then `LOAD ducklake/httpfs/postgres`,
   S3 creds, ATTACH over the DIRECT endpoint + `sslmode=require`); `assert_duckdb_version()`;
   `mint_write_identity()` (monotonic ULID + high-precision timestamp, once); `load_field_semantics()`;
   `schema_gate()` (loud-fail); `create_scd2_tables()` (CREATE history+current, `ALTER ... SET PARTITIONED BY`
   day(created_timestamp) / bucket(8,rec_id) BEFORE first write, `ducklake_default_data_inlining_row_limit=0`);
   `write_scd2()` (one txn: history MERGE-on-ULID insert-if-not-matched + `current` MERGE from in-hand delta;
   bounded OCC retry backoff+jitter, loud-fail on exhaustion; mint hoisted OUT of the loop); `read_current()`;
   `emit_metric()` (CloudWatch). Add `tests/test_ducklake_runtime.py` (100%).
4. **Refactor the smoke test.** `scripts/ducklake_neon_smoke_test.py` delegates ATTACH/connection to
   `ducklake_runtime`; update `tests/test_ducklake_neon_smoke_test.py`.
5. **Writer Lambda.** `src/lambdas/ducklake_writer/{__init__.py,handler.py,manifest.yaml}` (action dispatch;
   docstring deferral note re Single-Portal). `tests/test_ducklake_writer_handler.py` (100%).
6. **Reader Lambda.** `src/lambdas/ducklake_reader/{__init__.py,handler.py,manifest.yaml}` (read-only).
   `tests/test_ducklake_reader_handler.py` (100%). Add `config/lambda/ducklake-{writer,reader}/.gitkeep`.
7. **Packaging machinery (excludes + size assert + build).**
   (a) `scripts/lambda_manifest.py`: add an `excludes: list[str]` field to `LambdaManifest` and honour it in
   `stage_bundle()` (skip excluded paths during the `includes` copy), `compute_affected_artifacts()` (an
   excluded changed file does not mark the artifact affected), and `derive_lambda_file_patterns()`. Set
   `excludes: [src/common/ducklake_runtime.py, src/lambdas/ducklake_writer, src/lambdas/ducklake_reader]` on
   both `src/lambdas/data-pipeline/manifest.yaml` and `src/lambdas/ops-compaction/manifest.yaml`. Update
   `tests/test_lambda_manifest.py`. Prove with VP steps 5-6.
   (b) `scripts/build_lambda.py`: add `PINNED_DUCKDB_VERSION="1.5.3"`; a **hard 262 MB size assertion** that
   `sys.exit`/raises (not just WARNs) for any function zip or layer; `build_ducklake_deps_layer()`
   (duckdb==1.5.3 + psycopg2-binary + python-ulid); `build_ducklake_extensions_layer()` (prefer the Step-0
   S3 fallback if present, else fetch
   `https://extensions.duckdb.org/v1.5.3/linux_amd64/{ducklake,httpfs,postgres}.duckdb_extension.gz`, gunzip,
   stage under `duckdb_extensions/v1.5.3/linux_amd64/`); add writer/reader to the build + the
   function-name->S3-key deploy map + the layer S3 upload. Update `tests/test_build_lambda.py` (incl. a size-
   assert-raises test).
8. **In-Lambda smoke gates.** Add the `--lambda-*` SigV4 Function-URL invoke gates to
   `scripts/ducklake_neon_smoke_test.py` (sign with botocore SigV4Auth; assert the documented OK strings).
9. **Terraform.** `terraform/personal/ducklake_lambdas.tf` (functions, write/read roles, deps+extensions layer
   versions from S3, Function URLs AWS_IAM, log groups, Secrets read grant on the DSN ARN, outputs). Reference
   `aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn` directly (same root module). `handler =
   "src.lambdas.ducklake_writer.handler.handler"` (verify against the staged zip root). `try()` the hashes.
10. **Break-glass grant.** `terraform/personal/platform_roles.tf`: add the PlatformAdmin DSN-secret-read +
    S3-read-on-ducklake-prefix statement (IAM -> human-gated apply).
11. **Runbook.** `docs/runbooks/ducklake-catalog-operations.md`: Section 1 break-glass catalog-attach
    inspect/repair (O-1); Section 2 OQ.12 clone-rehearsal version-bump policy.
12. **Roadmap correction.** `docs/ROADMAP-PLATFORM.yaml`: "1.5.2" -> "1.5.3" everywhere + the OQ.12 note.
13. **Run the pre-deploy Verification Plan** (steps 1-11). Loop until green. Then build + upload zips/layers to
    S3 (`build_lambda --skip-upload=false`, no `--deploy`).
14. **Human-gated terraform apply.** `terraform -chdir=terraform/personal plan` -> present to human -> apply via
    `agent_platform_admin` (roles, layers, functions, Function URLs, log groups, break-glass grant).
15. **Deploy code.** `bin/venv-python -m scripts.build_lambda --deploy` (updates the two functions).
16. **Execute the post-deploy Verification Plan** (steps 12-21). Loop until pass. If a V3 step fails
    unrecoverably (esp. step 18 latency), STOP and analyse root cause (Decision 55) -- do not relax CD.33
    budgets or add a rescue loop.
17. **Close out the roadmap.** Set T2.17 `status: complete` + `completed_at` + a `progress_note` capturing the
    measured in-region latency numbers and the EC coverage.
18. **Report:** what was implemented, the per-field derivation confirmations, the measured latency, and the full
    Verification Plan results.

## Work Areas (STRATEGIC plans only)
N/A -- this is an IMPLEMENTATION plan.
