# AUDIT PROMPT: Repository Structure

You are a senior software architect auditing the *physical structure* of a public,
agent-operated monorepo (`agent-platform`). Execute this brief exactly as written in a fresh
session. It is self-contained: do not ask clarifying questions, and do not read this file's
provenance. Everything you need is below or in the repository at the branch you check out.

---

## 1. TASK

Audit the repository's physical structure -- its directory topology, file placement, naming
conventions, and discoverability -- along three axes:

1. **Internal logic**: is placement predictable and consistent, or has organic growth produced
   placement-by-accident?
2. **Agent-optimization**: is the tree shaped for agent navigation and context economy (the
   repo's stated North Star is "the repo is for agents")?
3. **End-state convergence**: does the current tree move toward the destination the platform
   roadmap spells out, or accumulate debt that roadmap will have to unwind?

You benchmark against frontier repository practices (an external checklist is pinned in section 7,
which you may extend with bounded web research per section 11), and you PLAN a target shape:
your deliverables include a concrete proposed target directory tree (the to-be map) planned to
the roadmap end-state, per-surface actionable dispositions, and a findings list.

The seven audited surfaces (all built; enumerated in section 4) are the repository's major trees.

**Deliverables** -- the ONLY files you create or modify in the repository tree:
- `audits/repository-structure-<sha>.yaml` (structured; the system of record)
- `audits/repository-structure-<sha>.md` (companion report, prose, <= ~1500 words)

where `<sha>` is the short sha of `origin/main` you audit (section 16). Regenerating gitignored
local caches per section 5 is expected and does not breach the write boundary; never commit them.

You DRAFT; the human DISPOSES. You move no files, reorganize nothing, and open a PR for review.
A proposed target tree is a proposal, not an applied change.

---

## 2. CANDIDATE OBSERVATIONS vs VERDICTS -- the epistemic contract

This prompt hands you FACTS and CANDIDATE hypotheses. It never hands you verdicts. Every
candidate in section 10 is a neutrally-phrased observation you must adjudicate by tracing it in
the repository yourself.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** A run that merely confirms the
candidates below has failed. Some candidates will resolve to deliberate, decided structure with a
sound rationale -- when so, say so and put them in `rejected_candidates`.

Per-candidate adjudication enum, and where each verdict lands:
- **CONFIRMED structural defect** (traced, no sufficient compensating control) -> `findings[]`,
  `roadmap_crossref.classification = novel`.
- **Planned, but the owning roadmap item's remedy is insufficient or unbuilt** -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt`.
- **Planned and fully covered by an owning item, OR a deliberate decided structure** ->
  `rejected_candidates[]` (name the compensating control / decision).
- **Not a defect** (sound as-is) -> `rejected_candidates[]` (name why).

Severity is never inherited from this prompt's framing. You assign it after judgment (section 15).

---

## 3. READ FIRST -- disambiguation traps

Recon surfaced terms and targets that invite a misread. Internalize these before you trace
anything:

- **"structure" = physical directory/file topology (IN SCOPE)** vs **"structured data" /
  agent-first content-format (CONTEXT ONLY, OUT OF SCOPE).** The repo has a decided principle
  that canonical content is machine-parseable YAML over prose (CD.13, Decision 110). That is the
  *content-format* axis. This audit is about *where files live and how the tree is shaped*, not
  whether a given file's contents are YAML vs prose -- except where prose-vs-machine duplication
  is itself a placement/topology fact (e.g. a `.md` mirror sitting beside its `.yaml` source).
- **Assess LAYOUT, not subsystem correctness.** The verification harness, telemetry model,
  executor, DQ system, and CI-RCA each have their own audits under `audits/`. Do NOT re-audit
  their logic or design. You assess only where their code/config/docs sit in the tree and whether
  that placement is coherent.
- **Two Lambda homes** (`src/lambdas/<slug>/handler.py` and `src/data/handlers/*_handler.py`)
  may be an in-progress migration toward per-Lambda packaging manifests (CD.24). Trace whether
  the split is a deliberate migration state before flagging it as disorder.
- **`.github/prompts/` and `.github/agents/` still contain files** despite a "legacy .github
  prompts/agents retirement" item marked complete (T5.3). The survivors are the intentional
  *scheduled-agent* surfaces; full-directory retirement is separately owned. Do not flag the
  survivors as leftover debt.
- **`docs/INTENT-*.md` at the docs root are grandfathered** and scheduled for extract-and-delete
  (T5.5, Decision 86). Do not file "delete the INTENT docs" as a novel finding; you MAY assess
  whether their current placement/handling is optimal in the interim.
- **Multiple product-roadmap YAMLs are intentional.** The platform hosts multiple products;
  `docs/ROADMAP-PRODUCT.yaml` and `docs/ROADMAP-SEMANTO.yaml` are per-product roadmaps under the
  multi-product topology (CD.32). Do NOT propose merging the product YAMLs. A prose `.md` mirror
  of a `.yaml` roadmap is a separate matter (see candidate C6).

---

## 4. SCOPE

**Audited surfaces** (re-derive every count yourself -- section 5 trust-nothing rule):

- **S1 -- Root / top-level**: files and dotfiles at the repository root, plus the set of
  top-level directories.
- **S2 -- `scripts/`**: automation, checks, executor, verifiers.
- **S3 -- `src/`**: `data/`, `lambdas/`, `common/`, `schemas/`, `meta_learner/`, `live/`, `lab/`,
  `execution/`.
- **S4 -- `tests/`**: the test suite and its fixtures.
- **S5 -- `docs/`**: docs root, `plans/`, `contracts/`, `audit-prompts/`, `audit-reports/`,
  `intent-migration/`, `dq/`, `runbooks/`.
- **S6 -- `config/` + `terraform/`**: the declarative / infrastructure surface (config manifests
  and Terraform).
- **S7 -- Agent-instruction surfaces**: `.claude/` (commands, skills, hooks, agents) and
  `.github/` (workflows, instructions, prompts, agents).

**Shared vocabulary**:
- *Surface* = one of S1-S7 above.
- *Placement rule* = a predictable, stateable rule that determines where a new file of a given
  class belongs.
- *Artifact class* = a category of file that should have a single canonical home (e.g. "a Lambda
  handler", "an audit output", "a per-product roadmap").
- *Context-locality* = a Claude-Code-on-the-web loading mechanism: a per-directory `CLAUDE.md` is
  loaded into agent context only when a file in that directory is read. It is a lever for scoping
  context to where it is needed rather than loading everything ambiently.
- *Frontier practice* = a named, externally-recognized repository-structure convention (section 7
  checklist).

**Out of scope** (one line each):
- Subsystem correctness/design (verification, telemetry, executor, DQ, CI-RCA) -- layout only.
- Content correctness of any individual file -- you assess placement, not prose quality.
- AWS/account/infra behavior -- only where `terraform/` files sit in the tree.
- Git history, commit conventions, PR mechanics -- structure of the working tree only.

**Trust-nothing clause**: obtain every file, line, count, and size by reading the repository
yourself -- trust no number quoted in this prompt. Re-derive counts with `git ls-files`. Record
any anchor that does not resolve in `meta.stale_anchors`, and note in `meta.contract_notes` any
file this prompt cites where the tree has diverged from what section 10 states.

---

## 5. SETUP

Run these read-only commands to ground yourself (all are safe; none mutate the tree):

```bash
git fetch origin main
git rev-parse --short origin/main            # this sha is <sha> everywhere below
git ls-files | wc -l                         # total tracked files
git ls-files <dir> | awk -F/ 'NF==2' | wc -l # root-file count of a directory
```

Populate the dedup caches (section 13 depends on them):

```bash
bin/venv-python -m scripts.session_preflight --roadmap-detail full
```

This writes `logs/.preflight-report.json` and refreshes `logs/.recommendations-log.jsonl`.

**Degraded-dedup hatch**: IF cache-gen fails (creds/egress down): do NOT abort -- set
`meta.degraded_dedup = true`, mark every `roadmap_crossref` confidence as HYPOTHESIS and every
`dedup_hit_count` as null, and proceed using direct `rg` over `docs/ROADMAP-PLATFORM.yaml`,
`docs/DECISIONS.md`, and `logs/.recommendations-log.jsonl` as a best-effort substitute.

**Web-research availability** (section 11): if this session cannot browse the web, set
`meta.web_research_available = false` and assess section 7's checklist from the pinned list
alone -- never block on missing browsing.

Repo-wide `validate.py` is advisory outside CI. A clean YAML parse of your two deliverables is
the real pre-push gate. If an unrelated `validate --pre` check fails, record it in
`meta.contract_notes` and do NOT fix it -- that is outside your write boundary.

---

## 6. NORTH STAR

The bar you judge each surface against. These are principles, not mechanical rules -- argue each
surface against them; do not pattern-match.

- **NS.4 -- "The repo is for agents."** Structure exists to make agents fast and unambiguous:
  an agent should locate the right file from an intent without scanning, and load minimal tokens
  to do so. This is a bar you judge each surface against, not an absolute.
- **Predictable placement.** There should be a stateable rule for where any new file of a given
  class belongs, and existing files should obey it. Like things live together; each artifact
  class has one canonical home.
- **Context economy.** The tree's shape should minimize what an agent must load. Per-directory
  `CLAUDE.md` context-locality, subtree boundaries, and index/router files are levers here. A
  bar to judge, not a mandate to maximize CLAUDE.md count.
- **Machine-parseability / self-description.** Discovery should lean on machine-readable indices
  and manifests, not hand-maintained prose that drifts. (Content-format decisions are decided --
  section 3 trap 1 -- but a *structural* index that is prose-only and drift-prone is fair game.)
- **Convergence over accretion.** The tree should move toward the roadmap end-state (section 4's
  surfaces reconciled against ROADMAP-PLATFORM.yaml), not accumulate parallel homes and orphans
  that the roadmap must later unwind. This is a bar you judge each surface against.

The `rebuild_vs_refactor` stance in `docs/ROADMAP-PLATFORM.yaml` is load-bearing: the Python
codebase (`scripts/`, `src/`, `tests/`) is **refactored surgically, not rewritten**. Greenfield
rewrite is explicitly retired (R.1) because 70+ ratified decisions are load-bearing context.
Every disposition and target-tree proposal you make MUST be achievable by surgical
move/rename/consolidate steps -- never "start over".

---

## 7. THE QUESTIONS

Answer each as a first-class entry in `question_answers`. Pinned per-question verdict enums below.

- **Q1 -- Internal logic.** Is file placement across S1-S7 logical and internally consistent, or
  has organic growth produced placement-by-accident? Is there a stateable placement rule per
  surface, and do files obey it? Verdict enum: `sufficient | partial | insufficient`.

- **Q2 -- Agent-optimization.** Is the tree optimized for agent consumption specifically --
  discoverability (locate-without-scanning), context economy (load-minimal, including
  per-directory `CLAUDE.md` context-locality), and machine-parseable indexing? Explicitly weigh
  whether context-locality is under- or over-used given the CC-web loading model. Verdict enum:
  `sufficient | partial | insufficient`.

- **Q3 -- Frontier-practice benchmark.** How does the structure measure against frontier
  repository practices? Assess property-by-property against this EXTERNAL CHECKLIST (this list is
  the floor; section 11 lets you extend it with bounded research). This checklist is the SOLE
  source the maturity top tier reads.
  - EC1: Top-level domain separation with no catch-all bucket (code / tests / docs / config /
    infra / tooling each have a clear home).
  - EC2: Tests mirror the source tree (a test's location is derivable from the file under test).
  - EC3: Enforced package/import boundaries (an import graph that is declared and checked).
  - EC4: Flat-vs-nested discipline (a directory with a large flat file count and clear prefix
    families is subdivided).
  - EC5: Single canonical home per artifact class (one Lambda location, one audit-output
    location, one home per roadmap axis).
  - EC6: Machine-readable discovery/ownership index kept in sync (CODEOWNERS, a file router, or
    equivalent) rather than tribal knowledge.
  - EC7: Agent-affordance conventions (`AGENTS.md`, per-directory `CLAUDE.md`, or an
    `llms.txt`-style pointer set) present and coherent.
  - EC8: Decision-record convention with stable IDs (ADR-style).
  - EC9: Naming-convention uniformity (case, separators, prefix taxonomy consistent within and
    across surfaces).
  - EC10: Root-directory minimalism (few root files beyond standard dotfiles and portal files).
  - EC11: Generated/derived artifacts segregated from source and gitignored.
  Verdict enum: `sufficient | partial | insufficient`. Add
  `external_checklist: [{property, rating: met|partial|missed, evidence, evidence_kind:
  static|researched}]` to this question's answer. `partial` requires an argued, property-matched
  compensating control in `evidence`.

- **Q4 -- End-state convergence.** Reconcile the current tree against the ROADMAP-PLATFORM
  end-state (`docs/ROADMAP-PLATFORM.yaml`: `north_star`, `rebuild_vs_refactor`,
  `foundation_already_shipped`, and structure-touching tier_items -- e.g. T-1.7, T5.3, T5.5,
  T3.14, CD.23, CD.24). Is each surface converging toward the destination, or diverging /
  accumulating debt the roadmap must unwind? Verdict enum: `aligned | partial | divergent`.

- **Q5 -- Per-surface disposition.** For each of S1-S7, what is the actionable disposition, given
  the surgical-refactor stance (section 6)? Populate the `surface_dispositions` decision block
  (section 14). Verdict enum per surface:
  `keep | reorganize-in-place | consolidate | split | defer`.

- **Q6 -- Questions the requester did not think to ask.** Use the
  `{q: Q6, answers: [{question, answer, basis}]}` shape. Seed candidates you MUST answer and
  extend:
  - Does the inversion "more human `README.md` than agent `CLAUDE.md`" matter for an agent-first
    repo, and what is the right ratio/placement?
  - Should there be an enforced, machine-checked placement rule (a linter/validator that fails
    when a file lands in the wrong home), and where would it live?
  - Does the target tree create migration hazard for the many path constants embedded in prompts,
    configs, and `validate.py` checks -- and how should a move be sequenced to stay safe?
  - What is the smallest high-leverage first move (the one reorganization that unlocks the most)?

---

## 8. RUBRIC

Rate each surface S1-S7 on each dimension. Pinned rating enum:
`strong | adequate | weak | absent | n/a`. `n/a` is correct and costless where a dimension does
not structurally apply -- never manufacture a rating or a finding to fill a cell. Record ratings
in `rubric_ratings` with `evidence` (`file:line` or a surface/count anchor).

- **VD1 -- Discoverability.** Can an agent locate the right file from an intent without scanning?
- **VD2 -- Placement consistency.** Do like things live together; is there a predictable rule for
  where a new file goes, and is it obeyed?
- **VD3 -- Loading efficiency / context economy.** Is the surface shaped so agents load minimal
  tokens? Weigh per-directory `CLAUDE.md` context-locality and subtree boundaries.
- **VD4 -- Machine-parseability / self-description.** Structured manifests/indices vs drift-prone
  prose for *discovery* purposes.
- **VD5 -- Naming conventions.** Consistent case/separators/prefix taxonomy; no
  two-things-one-name.
- **VD6 -- Roadmap convergence.** Does the surface's current shape move toward or away from the
  end-state?
- **VD7 -- Frontier-practice alignment.** Does the surface match the section 7 checklist
  properties that apply to it?

Coverage invariant: every question is served by >= 1 dimension; every dimension is referenced by
>= 1 question or deep-dive. (Q1<-VD1,VD2,VD5; Q2<-VD1,VD3,VD4; Q3<-VD7; Q4<-VD6; Q5<-all.)

---

## 9. DEEP-DIVES

Each feeds named questions and needs end-to-end tracing beyond a rubric cell.

- **DD-A -- `scripts/` flat-root vs nested subpackages (feeds Q1, Q3/EC4, Q5).** Enumerate the
  root-level files of `scripts/` and the prefix families among them (e.g. `ci_rca_*`, `sync_*`,
  `session_*`, roadmap/plan, `ops_*`, llm/model). Contrast with the already-nested
  `scripts/checks/` subtree. Trace what a move would cost: which prompt files, config manifests,
  `validate.py` check paths, and import statements reference `scripts/<file>` directly. A
  disposition here must state the migration hazard.

- **DD-B -- Lambda-code homes (feeds Q1/EC5, Q4, Q5).** Trace both `src/lambdas/<slug>/handler.py`
  and `src/data/handlers/*_handler.py`. Determine, from `src/lambdas/*/manifest.yaml`,
  `scripts/build_lambda.py`, and CD.24 in the roadmap, whether the two homes are a deliberate
  migration state (per-Lambda manifests superseding whole-`src/` copytrees) or an unresolved
  split. Your verdict decides whether C2 is a finding or a rejected candidate.

- **DD-C -- Audit-artifact homes and `docs/` root scatter (feeds Q1/EC5, Q2, Q5).** Trace where
  audit artifacts are written (`audits/`, `docs/audit-prompts/`, `docs/audit-reports/`, and any
  loose `docs/AUDIT-*.md`/`.yaml`), and which producers write to which (the `/audit` command/skill
  and the audit executor). Inventory the `docs/` root file classes and whether a placement rule
  exists. This deep-dive most directly informs the proposed target tree for `docs/`.

- **DD-D -- Context-locality coverage (feeds Q2, Q3/EC7, Q6).** Inventory every `CLAUDE.md` and
  every `README.md` in the tree. For each major subtree lacking a `CLAUDE.md`, judge whether
  local context would reduce ambient loading. Assess the human/agent index inversion. Produce a
  concrete recommendation set (which directories warrant a `CLAUDE.md`), respecting that adding
  one is only worthwhile where it earns its context cost.

---

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every entry was observed at compose time;
re-verify each before relying on it (section 5 trust-nothing), and re-derive counts with
`git ls-files`. Facts are stated neutrally and carry no verdict.

File-count observations (re-derive):
- Total tracked files: ~1026. By top-level dir (descending): `docs` ~437, `scripts` ~179,
  `tests` ~168, `src` ~59, `terraform` ~40, `config` ~34, `.github` ~31, `.claude` ~24,
  `audits` ~20, `logs` ~10, `bin` ~4.
- `scripts/`: ~71 files directly at its root; subtrees `checks/` (~86, itself nested into
  `ci_guards/`, `contracts/`, `deps/`, `executor/`, `hygiene/`, ...), `executor/` (~13),
  `verifiers/` (~7). Anchor: `git ls-files scripts | awk -F/ 'NF==2'` and `.../ 'NF>2{print $2}'`.
- Prefix families among `scripts/` root files include `ci_rca_*` (~7 files), `sync_*` (~3),
  `session_*` (~3), `product_roadmap*`/`platform_roadmap`/`plan_*`/`find_plan`, `ops_*`, and
  `llm_*`/`model_registry`.
- `src/lambdas/`: per-Lambda dirs each with `handler.py` + `manifest.yaml` (e.g. `ducklake_reader`,
  `ducklake_writer`, `ducklake_maintenance`, `ducklake_catalog_dr`) plus `data-pipeline/` and
  `ops-compaction/` (manifest-only). `src/data/handlers/`: `*_handler.py` files
  (`fetch_handler.py`, `feature_handler.py`, `write_handler.py`, `maintenance_handler.py`,
  `discovery_handler.py`, `scheduled_agent_handler.py`, `findings_processor_handler.py`,
  `ops_compaction_handler.py`, `agent_telemetry.py`) plus a `CLAUDE.md`.
- `scripts/build_lambda.py` builds per-Lambda artefacts from `src/lambdas/<slug>/manifest.yaml`;
  CD.24 in `docs/ROADMAP-PLATFORM.yaml` describes retiring whole-`src/`/whole-`config/` copytrees
  in favor of per-Lambda manifests. Re-derive the current copytree/manifest state from the file.
- `tests/`: ~142 files directly at its root; subtrees `fixtures/` (~19) and `test_verifiers/` (~7).
  A `tests/CLAUDE.md` exists.
- `docs/`: ~31 files at root; subtrees `plans/` (~357), `contracts/` (~29), `audit-reports/` (~8),
  `audit-prompts/` (~8), `dq/` (~2), `intent-migration/` (~1), `runbooks/` (~1).
- `docs/` root file classes observed: `INTENT-*.md` (~13 files), `AUDIT-PROMPT-*.md` and
  `AUDIT-*.yaml` (loose, e.g. `AUDIT-PROMPT-platform-roadmap-audit.md`,
  `AUDIT-test-hermeticity.yaml`), `ROADMAP-*` (`ROADMAP-PLATFORM.yaml`, `ROADMAP-PRODUCT.yaml`,
  `ROADMAP-PRODUCT.md`, `ROADMAP-SEMANTO.yaml`), `ARCHITECTURE*.md`, `REPORT-*.md`,
  `SESSION_LOG*.md`, `DECISIONS*.md`, `PROJECT_CONTEXT.md`, `GETTING_STARTED.md`,
  `CHANGELOG.md`, `ducklake-spike-findings.md`.
- Audit outputs exist under top-level `audits/` (~20 files, `.yaml`+`.md` pairs) AND
  `docs/audit-prompts/` (compose-time prompts) AND `docs/audit-reports/`.
- `CLAUDE.md` files: 4 total -- root (`CLAUDE.md`, whose entire content is `@AGENTS.md`),
  `src/data/handlers/CLAUDE.md`, `terraform/CLAUDE.md`, `tests/CLAUDE.md`. `README.md` files: ~10
  (root, plus several under `config/` and `terraform/`).
- Root directory holds ~28 tracked entries, including portal files (`README.md`, `AGENTS.md`,
  `CLAUDE.md`, `EVALUATION-PROMPTS.yaml`, `SECURITY.md`, `LICENCE`), build/config
  (`setup.py`, `pyproject.toml`, `requirements.txt`, `requirements.lock`, `requirements-fast.txt`,
  `requirements-dev.txt`, `.importlinter`, `.pre-commit-config.yaml`, `.secrets.baseline`,
  `.mcp.json`), and dirs.
- `.claude/`: `commands/` (~5), `skills/` (~8), `hooks/` (~7), `agents/` (~2), `settings.json`,
  `statusline.py`. `.github/`: `workflows/` (~14), `instructions/` (~7), `prompts/` (~7),
  `agents/` (~1), `dependabot.yml`, `pull_request_template.md`.

Governing decisions / roadmap items (read the cited anchors; do not trust these summaries):
- `docs/ROADMAP-PLATFORM.yaml`: `north_star.principles` (NS.1-NS.5), `rebuild_vs_refactor`
  (surgical refactor of `scripts/`/`src/`/`tests/`; R.1 greenfield-rewrite retired),
  `foundation_already_shipped`, and tier_items T-1.7 (config/ split -- complete), T5.3 (legacy
  .github prompts/agents retirement -- complete, scheduled survivors intentional), T5.5 (INTENT-*
  extraction -- deferred post-MVP), T3.14 (repo-wide context-budget metric -- deferred),
  candidate_decisions CD.13 (agent-first structured content), CD.23 (curated human portal is a
  projection), CD.24 (per-Lambda packaging manifests), CD.32 (multi-product topology).
- `docs/DECISIONS.md`: Decision 86 (no new standing prose-architecture docs), Decision 110
  (ROADMAP-PLATFORM.yaml as the agent-first structured-data exemplar), Decision 111 (curated
  portal), Decision 115 (docs/handoffs/ pattern retired).
- `AGENTS.md` / `CLAUDE.md`: "Agent-First Repository" section; the 5-layer instruction
  architecture (L1 CLAUDE.md/AGENTS.md, L2 PROJECT_CONTEXT.md, L3 `.claude/commands/`, L4
  `.claude/skills/`, L5 executor prompts).
- `docs/PROJECT_CONTEXT.md`: the "File Router" table (a hand-maintained discovery index).

---

## 11. EMPIRICAL PASS -- bounded frontier-repo research

Section 7's EC1-EC11 checklist is the floor and is assessable statically from the repo. You MAY
extend it with web research, under hard bounds:

- Consult **no more than 8** named external repositories or published structure standards
  (e.g. well-regarded monorepo layouts, Python `src`-layout guidance, ADR conventions,
  agent-affordance conventions such as `AGENTS.md`/`llms.txt`). Do NOT exceed 8. Name each source.
- For each external property you add or each EC row you corroborate, tag the evidence
  `evidence_kind: researched`; properties assessed from the repo alone are `evidence_kind:
  static`. Static and researched findings are weighed equally at equal severity; do not let a
  researched ideal outrank an observed repo fact.
- If this session cannot browse (section 5), set `meta.web_research_available = false` and assess
  EC1-EC11 from the pinned list alone. This is a valid, non-degraded run for everything except
  net-new external properties.

Counterfactual test for any frontier-practice finding: "would a competent agent, dropped into
this repo cold, actually be slowed or misled by this -- or is the frontier practice cosmetic
here?" A practice the repo omits without cost is not a finding.

---

## 12. METHOD

Phases, in order. Synthesis and maturity are LAST.

- **P1 -- Read.** Run section 5 setup. Re-derive the section 10 counts. Read the cited roadmap
  and decision anchors.
- **P2 -- Trace.** Adjudicate each section 10 candidate against the repo. Walk each surface S1-S7.
- **P3 -- Deep-dive.** Execute DD-A..DD-D.
- **P4 -- Empirical.** Section 11 bounded research (if available).
- **P5 -- Rate.** Fill `rubric_ratings` for every applicable (surface x dimension) cell.
- **P6 -- Dedup.** Section 13 for every prospective finding.
- **P7 -- Synthesize.** Compose findings, `surface_dispositions`, the `proposed_target_tree`,
  `rejected_candidates`, `question_answers`, then compute per-surface maturity (section 15) LAST.

---

## 13. DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the search:

- `rg` the roadmap (`docs/ROADMAP-PLATFORM.yaml`), decisions (`docs/DECISIONS.md`), and the
  recommendations cache (`logs/.recommendations-log.jsonl`) for the finding's subject.
- Record `dedup_search_terms` and `dedup_hit_count` on the finding.
- A hit means the territory is owned: classify `planned-insufficient` or `planned-unbuilt` (with
  `item_ids`) and assess sufficiency -- it is NOT a fresh `novel` discovery. A finding with no
  recorded negative search is a HYPOTHESIS, not CONFIRMED.

**Deliberate-constraints do-not-flag list** (each with its owner -- do not file these as defects):
- Agent-first / machine-parseable-over-prose for canonical *content* (CD.13, Decision 110, NS.4).
- No new standing prose-architecture docs under `docs/` (Decision 86) -- do not propose new prose
  docs as a remedy.
- The curated human portal (`README.md`, `AGENTS.md`, `EVALUATION-PROMPTS.yaml`, `SECURITY.md`)
  is an allowed projection, not duplication (CD.23, Decision 111).
- `config/` per-Lambda/agent-consumed split already done (T-1.7 complete).
- Legacy `.github/prompts`+`.github/agents` retirement in progress; scheduled-agent survivors are
  intentional (T5.3).
- INTENT-* extraction/retirement deferred post-MVP (T5.5, Decision 86).
- Per-Lambda packaging manifests are the decided direction (CD.24); the `src/lambdas/` manifest
  layout is intended.
- Multiple per-product roadmap YAMLs are intentional under multi-product topology (CD.32).
- Greenfield rewrite is retired (R.1) -- never propose a rewrite; surgical refactor only.
- `docs/handoffs/` pattern already retired (Decision 115) -- do not resurrect it.

---

## 14. OUTPUT

Write `audits/repository-structure-<sha>.yaml` with this exact top-level shape (enums inline;
rename nothing):

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>, methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6, S7],
         degraded_dedup: false, web_research_available: true,
         contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q3, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       external_checklist: [{property: EC1, rating: met|partial|missed, evidence: "",
                             evidence_kind: static|researched}]}   # one row per EC1..EC11 (+ any researched additions)
    - {q: Q4, verdict: aligned|partial|divergent, basis: [], prose: ""}
    - {q: Q5, verdict: see surface_dispositions, basis: [], prose: ""}   # points to the decision block
    - {q: Q6, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
  surface_dispositions:            # the Q5 decision block, one entry per surface S1..S7
    S1: {verdict: keep|reorganize-in-place|consolidate|split|defer, mechanism: "",
         what_changes: "", cost: "", rationale: "", confidence: CONFIRMED|HYPOTHESIS}
    # ... S2..S7
  proposed_target_tree:            # the to-be map, planned to the roadmap end-state
    principles: [<the placement rules the target tree enforces>]
    nodes:
      - {path: "<dir-or-file>", role: "<one line>", moves_from: [<current paths, if any>],
         rationale: "", roadmap_basis: [<tier/decision ids>], migration_hazard: ""}
    sequencing: [<ordered surgical steps: what moves first and why, path-constant safety>]
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
    # ... S2..S7
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|surface-count", note: ""}
    # every applicable (surface x dimension) cell
  findings:
    - {id: RS-01, surface: S1..S7|shared, question: Q1..Q6, dimension: VD1..VD7,
       title: "", evidence: "file:line|count-anchor", evidence_kind: static|observed|researched,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: relocate|consolidate|split|rename|index|enforce|clarify,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale: "", confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [<finding ids>],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [<finding or roadmap ids>],
                    note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [<finding ids>],
            highest_leverage_change: <finding id>,
            maturity_S1: "", maturity_S2: "", maturity_S3: "", maturity_S4: "",
            maturity_S5: "", maturity_S6: "", maturity_S7: ""}
```

Then write `audits/repository-structure-<sha>.md` (<= ~1500 words): the executive layer a human
reads first -- verdicts per question, the proposed target tree rendered readably, the per-surface
dispositions, and the highest-leverage change. Prose, no padding.

**COUNTING INVARIANT** (state it and obey it): `findings[]` is the SOLE enumerated list.
`total_findings = len(findings) = novel_count + planned_insufficient_count +
planned_unbuilt_count`. Fully-covered candidates and deliberate structures live in
`rejected_candidates`, NOT `findings`. `rubric_ratings`, `question_answers`,
`surface_dispositions`, and `proposed_target_tree` are systems-of-record referenced FROM findings,
never re-counted. `top_improvements` and `highest_leverage_change` MUST be finding ids.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why the control would
FAIL if the defect were real. `CONFIRMED` requires the behavior traced to `file:line` or a
re-derived count; anything less is `HYPOTHESIS`.

---

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing.

- **critical** = the structure actively causes wrong or unsafe agent action (e.g. an artifact
  class with two homes such that an agent writes to or reads the wrong one, producing silent
  divergence).
- **high** = a placement/discoverability defect that materially slows or misdirects agents across
  many sessions AND whose compensating controls you judged insufficient.
- **medium** = redundancy / inconsistency / scatter with a clear surgical fix and no active
  breakage.
- **low** = naming/clarity/cosmetic.

Compensating-control rule: a control lowers severity only if it PROPERTY-MATCHES -- it must
exercise the same property AND fail if the defect were real (apply the counterfactual to the
control). A hand-maintained index that itself drifts does not neutralize a discoverability defect
unless you can show it is actually kept in sync.

**Maturity** -- compute LAST, per surface, top-down, first match wins. Pin these thresholds:
- **frontier** = 0 open critical AND 0 open high findings on that surface, AND every EC property
  that applies to the surface is rated `met` or `partial` (never `missed`) in Q3's
  `external_checklist`. The top rating remains reachable if you argued a property-matched
  compensating control -- this framing does not foreclose it.
- **strong** = 0 critical AND <= 1 high on the surface.
- **solid** = <= 1 critical on the surface.
- **nascent** = otherwise.

---

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This
   sha IS the audited tree; use it in both deliverable filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/repository-structure-<sha> origin/main` so the PR diff is exactly the two
   deliverable files. (This is a deliberate exception to the usual session-branch rule: the audit
   session needs a clean two-file diff off the audited base. The CI signal-green comment wake
   fires only on `claude/*` PRs and is irrelevant here -- you end your turn without merging; the
   human disposes of the PR.)
3. Repo-wide validation is advisory outside CI: a clean YAML parse of your two deliverables is the
   real pre-push gate. An unrelated `validate --pre` failure is recorded in `meta.contract_notes`,
   never fixed.
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign`
   (use `--no-gpg-sign` only if signing is unavailable). Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review) with title
   `audit: repository structure (S1-S7 topology, agent-optimization, end-state convergence)` and
   a body = a 2-3 sentence lede plus the `summary:` block in a yaml fence. Then END THE TURN -- do
   NOT poll, do NOT merge, do NOT subscribe, do NOT self-approve.

---

## 17. GUARDRAILS

- **Write boundary (closed list)**: the ONLY files you create or modify in the tree are
  `audits/repository-structure-<sha>.yaml` and `audits/repository-structure-<sha>.md`.
  Regenerating gitignored local caches per section 5 is expected and is not a breach; never commit
  them. You move, rename, and delete NOTHING else -- the target tree is a proposal.
- **Precision over volume.** Fewer than ~6 surviving findings is a valid result -- state it; do
  NOT pad. A padded finding on a sound structure is a worse outcome than a short list.
- **No verdict smuggling in your own output**: state the fact, then convict. A candidate that
  traces to sound, decided structure belongs in `rejected_candidates` with its owning decision --
  that is a successful adjudication, not a gap in the audit.
- **Surgical only**: every proposed change and every target-tree node must be reachable by
  move/rename/consolidate/index steps. Never propose a rewrite; R.1 is retired.
- **Stay in layout.** If you find a subsystem *logic* defect while tracing placement, note it in
  one line in the relevant finding's `note` and move on -- it is out of scope; do not audit it.
