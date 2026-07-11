# scripts/ - directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Placement: root vs subpackage
`scripts/` root holds only entry points (run as `python -m scripts.<name>`) and genuine unclassed
singles. Any prefix family of >= 3 related modules is a subpackage, not loose root files -- the
existing `scripts/checks/`, `scripts/executor/`, `scripts/verifiers/` packages prove the pattern.

- Governs NEW files now: do not add a third `scripts/<prefix>_*.py` sibling at the root -- create
  `scripts/<prefix>/` and place it there.
- Only `ops_*` remains grandfathered un-nested (owner T-1.24); it migrates under the final RS-01
  subpackaging plan (rec-164) with a same-commit reference rewrite. Do not migrate it ad hoc.
- Nested homes so far (RS-01 / rec-164): `scripts/ci_rca/` (evidence, filing, taxonomy, tier_map,
  probe_health, back_validation, vacuous_pass), `scripts/session/` (preflight, postflight,
  metrics), `scripts/sync/` (ops, recommendations, ducklake_version), `scripts/roadmap/`
  (platform_roadmap, product_roadmap(_schema), plan_document, plan_audit, find_plan -- names
  kept), `scripts/llm/` (client, utils -- prefix stripped; model_registry,
  github_models_client -- names kept). Pending: `scripts/ops/` (ops_data_portal, ops_writer;
  T-1.24; highest fan-out, deliberately deferred).
- The `scripts_root_allowlist` key in `docs/contracts/file-router.yaml` (enforced by
  `validate_placement`) now makes "scripts/ root = entry points + declared singles" machine-checked:
  every depth-1 `scripts/` file must be allowlisted or match a grandfathered glob (currently just
  the `ops_*` pair), or the build fails.

## Invocation
Always invoke `bin/venv-python` (never bare `python`/`python3`) -- the wrapper auto-detects the
platform and resolves the correct venv binary. Each Bash tool call is independent; do not rely on
`source .venv/bin/activate`.

## Adding a validate.py check
CI checks are registered, not hand-wired into `scripts/validate.py`. Add the module under
`scripts/checks/<domain>/`, decorate it `@register(...)`, and insert its name in the ordered tier
sequence(s) in `scripts/checks/registry.py`. `scripts/validate.py` is the single source of truth
for CI gates (AGENTS.md merge protocol) -- never add a CI check without adding it here first.
