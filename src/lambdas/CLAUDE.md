# src/lambdas/ — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Deploy channel (Decision 125)

The DuckLake Lambdas here (`ducklake_writer`, `ducklake_reader`, `ducklake_maintenance`,
`ducklake_catalog_dr`) are `terraform/personal`-managed and currently code/infra-COUPLED
(`source_code_hash=try(filemd5(zip),null)`, no `ignore_changes` lifecycle). Target: decoupled via
a dedicated governed code-deploy CD channel. Local `bin/venv-python -m scripts.build_lambda
--ducklake-only --deploy` is break-glass only, not the routine channel.

No standing rationale here (Decision 86) — see `docs/contracts/environment-taxonomy.md` section 5
for the classification SoT, `docs/contracts/build-lambda.yaml`'s `deploy_channels` for the
artifact->channel mapping, and Decision 125 for the ratification rationale.

`data-pipeline` and `ops-compaction` here are NOT `terraform/personal`-managed; they deploy via
the decoupled `build_lambda --deploy` path — see `src/data/handlers/CLAUDE.md`.
