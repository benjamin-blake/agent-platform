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
CI checks are registered via `@register(...)` and tier-sequenced by per-domain declarative
manifests (Decision 169, amends Decision 104) -- `scripts/validate.py` is NEVER touched. Add the
module under `scripts/checks/<domain>/`, decorate it `@register(...)`, and add one `Entry(name=,
module=, attr=, ...)` literal (bare string literals for `module=`/`attr=` -- never a combined
`"module:attr"` form, never computed; see `docs/contracts/check-manifest.yaml`) to that domain's
`scripts/checks/<domain>/_manifest.py`. Set `pre=True` (+ `pre_globs=` if the check should be
gated to specific changed paths) for `--pre` membership, and `full_segment=` (one of
`scripts.checks._schema.SEGMENT_TOKENS`) for full-tier membership; a check may be unsequenced
(neither) if it is invoked directly elsewhere (the sole instance: `validate_terraform_try`, called
inside the `terraform_checks` scaffold bundle).

Dispatch is `scripts.checks.registry.resolve(name)(failed)` -- `resolve()` imports the Entry's
defining module and does a late-bound `getattr` at CALL TIME (never caching the resolved
callable), so `unittest.mock.patch("<the check's defining module>.<name>", ...)` intercepts a real
dispatch pass. There is no facade re-export in `scripts/validate.py` to add or patch against.
`scripts/checks/deps/validate_check_manifests.py` (registered in both tiers) enforces the
manifest grammar; add a mirror test at `tests/checks/<domain>/test__manifest.py`-adjacent files
(see the 18 existing ones) if your domain's manifest doesn't already have one.
