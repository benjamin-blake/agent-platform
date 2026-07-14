# docs/ - directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

## docs/ root allowlist (RS-03)
The `docs/` root (depth-1 files) holds ONLY canonical governance surfaces; every other class lives
in a subtree. A new file at the docs root fails `validate_placement` unless it is an allowlisted
governance file or a grandfathered retiring-set member. The machine-readable allowlist is the
`docs_root_allowlist:` key in `docs/contracts/file-router.yaml` (the single source of truth the
check reads) -- register a genuinely-new governance surface there, never by loosening the check.

Allowed governance root files: `CHANGELOG.md`, `CLAUDE.md` (this file), `PROJECT_CONTEXT.md`, and
the roadmaps (`ROADMAP-PLATFORM.yaml`, `ROADMAP-PRODUCT.md`, `ROADMAP-PRODUCT.yaml`,
`ROADMAP-SEMANTO.yaml`).

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
| Operator procedures (agent-led) | `procedure:` blocks in `docs/contracts/*.yaml` |
| INTENT-migration manifest | `docs/intent-migration/` |

Audit OUTPUTS live in `audits/`, not under `docs/`. The discovery index is
`docs/contracts/file-router.yaml`.

`docs/runbooks/` is a RETIRING class (Decision 127): the existing
`docs/runbooks/ducklake-catalog-operations.md` is grandfathered, but no new file may be added
there -- new operator procedures are `procedure:` blocks in the owning contract, per the row above.

## Plans lifecycle (RS-07)
`docs/plans/` root holds ACTIVE plans (not yet merged-and-verified) plus the still-at-root `.yaml`
history (see the lagged-sweep note below). The archival criterion is deterministic and
machine-checkable: a depth-1 `docs/plans/` file is archived iff its extension is `.md` -- `.md` is
the deprecated pre-T1.11 planning format, superseded one-way by the schema-validated `.yaml`
format (Decision 85), so every depth-1 `.md` is definitionally pre-standard/superseded and belongs
under `docs/plans/archive/` (in-tree history, out of the hot glob path) -- keeps the active-set
glob cheap without deleting Decision 85 history. The first sweep (195 pre-existing `PLAN-*.md`
files) landed at RS-07 (repository-structure restructure, phase P6); `docs/plans/archive/` was
created BY that sweep, not merely "on first archival" as this section previously read.

Completed `.yaml` plans are explicitly OUT of this criterion for now: a `.yaml` plan's
"completed" status is a judgment call (merged-and-verified), not a cheap extension check, so its
archival is deliberately LAGGED to a future, separately-scoped sweep rather than evaluated
per-plan at completion time -- this avoids a standing done/not-done classifier in the hot
`/plan` and `/implement` load path. Until that lagged sweep lands, completed `.yaml` plans remain
at the `docs/plans/` root alongside active ones; do not hand-move an individual `.yaml` plan to
`archive/` outside that sweep. `docs/contracts/file-router.yaml`'s `prose_allowlist.allowed_globs`
entry `docs/plans/**/*.md` already covers `docs/plans/archive/*.md` via its recursive `**`
matcher, so no file-router edit was needed for the RS-07 move.
