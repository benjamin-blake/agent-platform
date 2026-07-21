# src/lambdas/ — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Deploy channel (Decision 125/126)

The DuckLake Lambdas here (`ducklake_writer`, `ducklake_reader`, `ducklake_maintenance`,
`ducklake_catalog_dr`) are `terraform/personal`-managed and now code/infra-DECOUPLED (#544:
`lifecycle { ignore_changes = [source_code_hash] }`). The governed code-deploy workflow is
`.github/workflows/deploy-ducklake-lambdas.yml`; see `docs/contracts/deploy-paths.yaml` for the
authoritative channel status. Local `bin/venv-python -m
scripts.build_lambda --ducklake-only --deploy` is break-glass only, not the routine channel.

No standing rationale here (Decision 86) — see `docs/contracts/environment-taxonomy.md` section 5
for the classification SoT, `docs/contracts/build-lambda.yaml`'s `deploy_channels` for the
artifact->channel mapping, and Decision 125 for the ratification rationale.

`data-pipeline` and `ops-compaction` here are ALSO `terraform/personal`-managed as of T2.43
(`terraform/personal/prod_lambdas.tf`, the `decoupled_build_pipeline` class) and decoupled from
day one; their governed code-deploy channel is `.github/workflows/deploy-prod-lambdas.yml` — see
`src/data/handlers/CLAUDE.md`.
