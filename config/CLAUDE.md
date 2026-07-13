# config/ - directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Three-zone layout (T-1.7)
`config/` splits into three zones by who loads a file and whether it ships in a Lambda zip:

- Root (shared): `config.yaml` (active, gitignored copy/symlink), `config.company.yaml`,
  `config.personal.yaml`, `config.yaml.example` -- runtime config loaded by `src.common.config`.
  BUNDLED into Lambda zips.
- `lambda/<name>/`: per-Lambda runtime payloads, bundled into `<name>.zip` by
  `scripts/build_lambda.py`. BUNDLED (that Lambda only).
- `agent/<consumer>/`: agent-consumed config (DQ rules, executor prompts, IAM runner manifest,
  verification registry, cost-reconciliation baselines). NOT bundled into any Lambda zip -- only
  Claude Code agents and CI scripts read it.

## Invariant: config/agent/ is never Lambda-bundled
`build_lambda.py` bundles ONLY the shared root config and the artifact's `config/lambda/<name>/`
payload (per-Lambda manifest, Decision 79 / CD.24). `config/agent/**` is out of every zip. Editing
a file here changes agent/CI behaviour, not deployed Lambda behaviour -- and a Lambda-bundling plan
must NOT assume `config/agent/` files reach the function. (This is why `config/agent/` does not
trigger the Lambda Deployment Assessment in `/plan`.)

## Authoritative rules live here, not in a companion README (Decision 127)
`config/README.md` and `config/agent/README.md` (retired per Decision 127 B2) were curated portal
projections of the zone/bundling rules above (CD.23). A companion human-prose doc alongside a
CLAUDE.md is the drift-by-design anti-pattern; this file is now the sole authority for
`config/`'s placement and bundling rules -- do not reintroduce a README here to restate them.
