# scripts/ - directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## Placement: root vs subpackage
`scripts/` root holds only entry points (run as `python -m scripts.<name>`) and genuine unclassed
singles. Any prefix family of >= 3 related modules is a subpackage, not loose root files -- the
existing `scripts/checks/`, `scripts/executor/`, `scripts/verifiers/` packages prove the pattern.

- Governs NEW files now: do not add a third `scripts/<prefix>_*.py` sibling at the root -- create
  `scripts/<prefix>/` and place it there.
- Existing un-nested families (`ci_rca_*`, `session_*`, `sync_*`, `roadmap`/`plan_*`, `llm_*`,
  `ops_*`) are grandfathered; they migrate under the RS-01 subpackaging plans (rec-164), one
  family per PR with a same-commit reference rewrite. Do not migrate them ad hoc.

## Invocation
Always invoke `bin/venv-python` (never bare `python`/`python3`) -- the wrapper auto-detects the
platform and resolves the correct venv binary. Each Bash tool call is independent; do not rely on
`source .venv/bin/activate`.

## Adding a validate.py check
CI checks are registered, not hand-wired into `scripts/validate.py`. Add the module under
`scripts/checks/<domain>/`, decorate it `@register(...)`, and insert its name in the ordered tier
sequence(s) in `scripts/checks/registry.py`. `scripts/validate.py` is the single source of truth
for CI gates (AGENTS.md merge protocol) -- never add a CI check without adding it here first.
