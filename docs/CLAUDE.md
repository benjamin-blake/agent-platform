# docs/ - directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## docs/ root allowlist (RS-03)
The `docs/` root (depth-1 files) holds ONLY canonical governance surfaces; every other class lives
in a subtree. A new file at the docs root fails `validate_placement` unless it is an allowlisted
governance file or a grandfathered retiring-set member. The machine-readable allowlist is the
`docs_root_allowlist:` key in `docs/contracts/file-router.yaml` (the single source of truth the
check reads) -- register a genuinely-new governance surface there, never by loosening the check.

Allowed governance root files: `ARCHITECTURE.md`, `ARCHITECTURE-WORKFLOW.md`, `CHANGELOG.md`,
`CLAUDE.md` (this file), `GETTING_STARTED.md`, `PROJECT_CONTEXT.md`, and the roadmaps
(`ROADMAP-PLATFORM.yaml`, `ROADMAP-PRODUCT.md`, `ROADMAP-PRODUCT.yaml`, `ROADMAP-SEMANTO.yaml`).

Grandfathered retiring sets (allowed now, retire on their own schedule -- do not add to them):
`INTENT-*.md` (owner T5.5; existence separately gated by `validate_intent_doc_freeze` via
`docs/intent-migration/MANIFEST.yaml`), `DECISIONS.md` / `DECISIONS_ARCHIVE.md` (owner T1.5),
`SESSION_LOG.md` / `SESSION_LOG_ARCHIVE.md` (owner T2.26 / T-1.9).

## Class -> home map
Every non-governance doc class has a subtree home; put new files there, not at the root:

| Class | Home |
|---|---|
| Plan documents (`PLAN-{slug}.yaml`) | `docs/plans/` |
| Machine-readable contracts | `docs/contracts/` |
| Audit prompts (`AUDIT-{slug}.md`) | `docs/audit-prompts/` |
| REPORT-ONLY deliverables + spike notes | `docs/plans/reports/` |
| Data-quality docs | `docs/dq/` |
| Operator procedures (agent-led) | `procedure:` blocks in `docs/contracts/*.yaml` |
| INTENT-migration manifest | `docs/intent-migration/` |

Audit OUTPUTS live in `audits/`, not under `docs/`. The discovery index is
`docs/contracts/file-router.yaml`.

`docs/runbooks/` is a RETIRING class (Decision 127): the existing
`docs/runbooks/ducklake-catalog-operations.md` is grandfathered, but no new file may be added
there -- new operator procedures are `procedure:` blocks in the owning contract, per the row above.

## Plans lifecycle (RS-07)
`docs/plans/` root holds only ACTIVE plans (not yet merged-and-verified). Completed and
deprecated-format plans move under `docs/plans/archive/` (in-tree history, out of the hot glob
path) -- keeps the active-set glob cheap without deleting Decision 85 history. The archive sweep
itself is RS-07; `docs/plans/archive/` is created on first archival.
