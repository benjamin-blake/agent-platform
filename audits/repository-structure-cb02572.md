# Repository Structure Audit -- companion report (cb02572)

Executed per `docs/audit-prompts/AUDIT-repository-structure.md` against `origin/main` at
`cb02572`. System of record: `audits/repository-structure-cb02572.yaml`. 8 findings survived
adjudication (0 critical, 1 high, 5 medium, 2 low); 4 of the 10 seeded candidates resolved to
deliberate, decided structure and were rejected with their owning controls named.

## Verdicts

- **Q1 Internal logic: partial.** Placement is predictable and machine-backed across most of
  the tree (src/ packages + Lambda manifests, tests' enforced location rule, config's decided
  three-zone split, terraform's account/role subtrees, .claude's L3/L4 separation). Two
  surfaces have no stateable rule: the `scripts/` root (71 files, six named prefix families
  sitting beside three nested subpackages that prove the alternative) and the `docs/` root
  (31 files of ~10 classes, of which the reports/spike/loose-audit classes landed by accident).
- **Q2 Agent-optimization: partial.** The canonical content surfaces are genuinely agent-first
  (schema-validated YAML roadmap/contracts/plans/manifests; on-demand skills). The discovery
  layer is the weak stratum: the hand-maintained File Router has three dead pointers and stale
  rows with no checking mechanism, context-locality is under-used exactly where edit-time
  invariants already exist (4 `CLAUDE.md` vs 10 `README.md`; the config bundling rules live in
  non-auto-loading READMEs), and the 357-file flat plans corpus has no lifecycle. Locality is
  under-used, not over-used -- all four existing `CLAUDE.md` files are accurate and earn their
  cost.
- **Q3 Frontier benchmark: partial.** Met: domain separation (EC1), enforced import boundaries
  (EC3 -- four import-linter contracts wired into both validate tiers), ADR-plus decision
  convention (EC8), sanctioned minimal root (EC10), segregated derived artifacts (EC11).
  Missed: flat-vs-nested discipline (EC4) and a machine-checked discovery index (EC6). The
  CODEOWNERS absence is deliberately *not* counted: researched, it is costless in a
  single-owner repo -- the real EC6 miss is the drifting prose router. One researched property
  was added (EC12, instruction-surface single-sourcing): missed for the `.github/instructions/`
  survivors, which sit outside the declared instruction architecture.
- **Q4 End-state convergence: partial.** Mostly converging: T-1.7 and T-1.8 are complete and
  mechanically consumed, CD.24's copytree retirement is realized in `build_lambda.py`, T5.3's
  survivors are explicitly owned by T4.12, Decision 115's handoffs directory is verifiably
  gone, and the plan corpus is mid one-way `.md -> .yaml` migration. Divergence pockets: the
  `scripts/` root is accreting *against* open rec-164 (filed 2026-04 citing "30+ files"; now
  71), and the audit-artifact legacy scatter plus router drift accumulate with no owner.

## Per-surface dispositions and maturity

| Surface | Maturity | Disposition |
|---|---|---|
| S1 root/audits/logs/bin/migrations | frontier | keep |
| S2 scripts/ | strong | reorganize-in-place (nest six families, one PR each) |
| S3 src/ | frontier | keep (two-home handler state resolves via owned items) |
| S4 tests/ | frontier | keep (extend mapping rule for basename collisions) |
| S5 docs/ | strong | consolidate (audit legacy, reports home, plans archive, machine index) |
| S6 config/ + terraform/ | frontier | keep (fix README drift; add config/CLAUDE.md) |
| S7 .claude/ + .github/ | strong | consolidate (executor instructions to one home) |

`src/` is the frontier exemplar: import-contract-enforced boundaries including a pure-data-layer
contract for `src.schemas`, per-Lambda manifest directories whose `handlers:` keys explicitly
bridge the legacy handler home, and a directory `CLAUDE.md` exactly where deploy invariants
bite. `terraform/` is a close second (the repo's best local affordance at 339 lines, retired
artifacts annotated rather than silently deleted).

## Findings (severity order)

- **RS-04 (high, novel, S5)** -- the canonical File Router (`docs/PROJECT_CONTEXT.md:115`) is
  hand-maintained prose with three confirmed dead pointers (`GEMINI.md`,
  `docs/AGENT_WORKFLOW.md`, `scripts/bedrock_client.py`), a stale plan-artefact row
  (contradicts Decision 85), and a Lambda-handlers row that omits the CD.24-canonical home.
  Nothing checks it; the doc-freshness monitor that might is disabled pending T4.12. Same-class
  drift corroborates (`config/agent/README.md` names a dead subtree; the instruction contract's
  cleanup note cites completed T5.3). Fix: convert to `docs/contracts/file-router.yaml` + a
  registered link-validity check.
- **RS-01 (medium, planned-insufficient via rec-164, S2)** -- 71 flat `scripts/` root files
  with six prefix families (`ci_rca_*` x7, `session_*`, `sync_*`, roadmap/plan, `ops_*`,
  `llm_*`). rec-164 owns the territory but is stale and carries no hazard sequencing -- the
  `ci_rca` family alone has 166 external references (workflow, scheduled agent, verification
  registry, roadmap, tests).
- **RS-02 (medium, novel, shared S1/S5)** -- audit artifacts across four homes: two live by
  design (prompts in `docs/audit-prompts/`, outputs in `audits/`), plus unowned legacy scatter
  (`docs/audit-reports/` x8, loose `docs/AUDIT-*` x3) and a live banner pointing at two dead
  legacy paths. C3 adjudicated on the merits: `audits/` **is** the right single output home --
  this audit's write location is also its recommendation.
- **RS-03 (medium, novel, S5)** -- no placement rule for the `docs/` root's unowned classes
  (REPORT-*, spike notes, loose audit files); the owned classes (INTENT-*, DECISIONS*,
  SESSION_LOG*) shrink on their own roadmap schedules and are excluded.
- **RS-05 (medium, novel, shared S2/S5/S6)** -- context-locality under-use: add exactly three
  `CLAUDE.md` files (scripts/, config/, docs/) carrying invariants that today live in
  non-auto-loading surfaces or nowhere.
- **RS-06 (medium, novel, S7)** -- executor instructions split across `.github/instructions/`
  and `config/agent/executor/prompts/` while the canonical contract names only the latter; the
  cleanup owner pointer is stale (T5.3 complete; T4.12's scope omits `instructions/`);
  `behavioral-invariants.md` is orphaned. Consolidate while the Decision 67 freeze makes it
  cheap.
- **RS-07 (low, novel, S5)** -- 357 flat plans (195 deprecated-format `.md`); adopt
  archive-on-supersession (`docs/plans/archive/`); `find_plan.py` resolves exact
  current-branch slugs, so archiving completed plans is lookup-safe.
- **RS-08 (low, novel, S4)** -- the enforced test-location rule collapses on basename
  collisions: `tests/test_handler.py` is a self-described shim for six `handler.py` files whose
  real tests use an out-of-rule naming convention. Extend the mapping, delete the shim.

## Rejected candidates (deliberate structure, control named in the YAML)

**C2** Lambda two-home state: CD.24 ratified + T-1.8 built; manifests machine-declare the
bridge; every legacy occupant has a retirement owner. **C4** flat tests: machine-enforced
derivable location, pytest-endorsed; only the collision crack survives (RS-08). **C6**
ROADMAP-PRODUCT prose mirror: KG.1-decided recovery artefact with a supersession banner and a
Lambda-asset coupling; residual dead pointers ride RS-02's fix. **C10** root inventory: every
file in a sanctioned or documented class (CD.23/Decision 111 portal; documented requirements
quartet).

## Proposed target tree (delta only; all surgical)

```
docs/contracts/file-router.yaml        <- File Router table (machine index, CI link-checked)
scripts/checks/hygiene/validate_placement.py   <- new placement + link-validity check
scripts/{ci_rca,session,sync,roadmap,llm}/     <- six root families nested (ops/ last/deferred)
scripts/CLAUDE.md, config/CLAUDE.md, docs/CLAUDE.md   <- context-locality adds
audits/legacy/                         <- docs/audit-reports/*, docs/AUDIT-test-hermeticity.yaml
docs/audit-prompts/                    <- absorbs the two loose docs/AUDIT-PROMPT-*.md
docs/plans/reports/                    <- REPORT-*.md, ducklake-spike-findings.md
docs/plans/archive/                    <- completed deprecated-format PLAN-*.md (lagged .yaml sweep)
config/agent/executor/instructions/    <- the six live .github/instructions/executor-* files
```

Sequencing: (1) machine index + link check first -- it is the safety net that makes every later
move CI-caught; (2) inert consolidations; (3) CLAUDE.md adds; (4) scripts families one PR each
(`ci_rca/` first; bundle-completeness gate when manifest-named files move); (5) executor
instructions while the freeze holds; (6) `ops/` family and plans archive last.

## Highest-leverage change

**RS-04.** Effort S, zero file moves, no migration hazard -- and it converts the entire target
tree from risky to routine: once discovery is a machine-checked registry, every relocation is a
one-row update that CI verifies, and the active misdirection (dead pointers on the designated
L2 lookup surface) stops compounding.
