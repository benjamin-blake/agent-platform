# AUDIT: Structural-size governance expansion beyond Python

## TASK

This repository enforces a per-file structural-size limit (500 effective lines) on Python only.
A parallel, independent regime governs agent-instruction markdown by byte count. Between and
around them sit Terraform, YAML, workflow, shell, JSON, HCL and SQL files that no size gate
measures. The repository owner's instinct is that the rule should extend to every file class
except prose and documentation, and has asked for the HOW, not a re-litigation of the WHETHER --
though you must still adjudicate the whether per class, because a class that should be exempt is
a real answer.

Audit whether per-file structural-size governance should extend to each non-prose file class in
this repository and, where it should, design the mechanism. You must reach a per-class verdict, a
verdict on the unit of measure, a verdict on the enforcement mechanism, a verdict on whether the
existing ratchet family is a sound foundation to generalize, a migration path for the files
already over any proposed limit, and draft `## Decision NNN` text ready to paste into
`docs/DECISIONS.md`.

Deliverables: `audits/size-governance-expansion-<sha>.yaml` and
`audits/size-governance-expansion-<sha>.md`. The ONLY files you create or modify in the
repository tree are those two. Regenerating gitignored local caches per SETUP is expected and
does not breach this; never commit them. You draft; the human disposes.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts. Every candidate
below is phrased as something to adjudicate, not something to confirm.

ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.

A run that merely confirms the candidates below has failed.

Adjudicate each candidate to exactly one disposition, and map it to the output contract as
follows:

- CONFIRMED defect, no existing item owns it -> `findings[]`, `roadmap_crossref.classification:
  novel`
- Real, and an existing roadmap item / decision / open recommendation owns the territory but its
  remedy is insufficient -> `findings[]`, classification `planned-insufficient`
- Real, owned by an item whose remedy is adequate but unbuilt -> `findings[]`, classification
  `planned-unbuilt`
- Real, and fully covered by an existing item's built remedy -> `rejected_candidates[]`
- Not a defect -> `rejected_candidates[]`, naming the compensating control and why it
  property-matches

## READ FIRST -- DISAMBIGUATION TRAPS

Six hazards. Each invites a specific misread that would waste most of a session.

1. **"SLOC" names two things.** It is (a) the concrete Python-specific measure in
   `scripts/checks/sloc/_shared.py` -- non-blank, non-`#`-prefixed lines -- and (b) the
   colloquial name for "the 500-line file rule" as a governance concept. This audit is about
   expanding (b). Whether (a) remains the right measurement for an expanded (b) is Q2 and is
   genuinely open.

2. **Prose is already governed, and its relief valve is the OPPOSITE of the SLOC one.** Do not
   treat agent-instruction markdown as an ungoverned gap, and do not port
   decompose-into-a-facade onto it. `config/prose_budgets.yaml` and
   `scripts/checks/prose/prose_limits.py` gate it by BYTES, and that module's docstring argues
   explicitly that splitting a `CLAUDE.md`/`SKILL.md` into fragments does not reduce the ambient
   load an agent must read. Two families, two units, two contradictory relief valves, both
   deliberate. Prose is OUT of scope as an audit target but IN scope as evidence -- it is the
   repository's own worked example of the same problem solved differently.

3. **`terraform` in `_SLOC_EXCLUDE_DIRS` does not mean `.tf` files were considered and exempted.**
   That exclusion list is consumed by a Python-file walker; it excludes Python located under
   `terraform/`. No line-count gate has ever scanned `.tf` files. Absence of coverage here is
   absence of scanning, not a recorded exemption. Verify this yourself before relying on it.

4. **`docs/plans/*.yaml` and `audits/*.yaml` are YAML by extension and workflow artifacts by
   role.** They are also Decision 127 class-(d) sanctioned artefacts. Whether "everything except
   prose and documentation" includes them depends on whether classification keys off extension or
   off role -- which is itself part of what you must decide. Do not assume either reading.

5. **Decision 43 already claims coverage it does not have.** Its structural-limits table declares
   limits "across all repository code, prompts, and agents" and carries rows for `.prompt.md`
   (3000 lines) and `.agent.md` (1500 lines). Those surfaces were deleted at roadmap item T-1.13.
   Those rows are dead letters. Do not read them as live coverage of any current file class.

6. **Ratchet direction is per-registry, not universal.** `config/coverage_baseline.yaml` ratchets
   UP (a minimum that may only rise). `config/sloc_budgets.yaml`, `config/prose_budgets.yaml` and
   `config/mypy_baseline.yaml` ratchet DOWN (a ceiling that may only fall). A generalized engine
   that assumes one direction is wrong for the other.

## SCOPE

### In scope -- file classes to reach a verdict on

Every class below is BUILT and present on disk. Enumerate the current population of each yourself.

| Class | Locations | Role |
|---|---|---|
| Terraform | `terraform/**/*.tf`, `*.hcl`, `*.tfvars` | hand-authored infrastructure |
| Hand-authored config | `config/**/*.yaml` | machine-consumed configuration and registries |
| Machine-readable contracts | `docs/contracts/**/*.yaml` | agent-consumed field/procedure semantics |
| CI workflows and actions | `.github/**/*.yml`, `.github/**/*.yaml` | CI/CD definitions |
| Shell | `**/*.sh`, `bin/*` | setup, hooks, wrappers |
| Lambda manifests | `src/lambdas/*/manifest.yaml` | packaging descriptors |
| Append-only registries | `docs/ROADMAP-PLATFORM.yaml`, `docs/ROADMAP-PRODUCT.yaml` | monotonically growing work-lists |
| Workflow output artifacts | `docs/plans/**/*.yaml`, `audits/**/*.yaml`, `docs/plans/reports/*.yaml` | one file per workflow run |
| Generated / derived | `docs/decisions-index.json`, any file regenerated from a source of truth | projections |
| Data / query | `**/*.sql`, `**/*.json`, `**/*.toml` | miscellaneous structured |

### Context-only, not audit targets

The Python SLOC gate and the prose byte gate are context: you assess whether they are a sound
FOUNDATION to generalize (Q4), not whether they are individually correct. Prose classification
under Decision 127 is settled. `docs/DECISIONS.md` sizing under `validate_decisions_size` is
settled.

### Explicitly out of scope

- Re-opening which prose is sanctioned (Decision 127).
- The warehouse / portal invariants (Decision 84).
- Proposing work for the autonomous executor (frozen, Decision 67).
- Changing the `--pre` versus full two-tier presubmit structure (Decisions 60/73). You may
  recommend which tier a NEW check belongs in; you may not restructure the tiers.
- Cyclomatic complexity. `validate_cc_limits` is Python-AST-specific and has no analogue in the
  classes above. Note it only if an expansion would break it.

### Vocabulary

- **effective lines**: non-blank lines whose first non-whitespace character is not `#`. This is
  what the current Python gate counts. Comment syntax differs by language -- `.tf` uses `#`,
  `//` and `/* */`; JSON has no comments -- so this definition does not port cleanly. That
  non-portability is evidence for Q2, not an incidental detail.
- **ratchet**: a registry of per-file budgets plus a gate, where movement in the tolerant
  direction is unrestricted and movement in the permissive direction requires a marker citing a
  real Decision.
- **relief valve**: the sanctioned way to bring an over-budget file into compliance. The Python
  gate's is decomposition into a facade package. The prose gate's is relocation or deferral, and
  it explicitly forbids decomposition.
- **raise marker**: an inline `# raise-approved: dec-NNN <reason>` comment on a registry entry
  line, validated against a real `## Decision NNN:` header.
- **class**: a set of files sharing a governance-relevant role. Whether class membership is
  determined by extension, by directory, or by provenance is part of what you decide.

### Trust nothing

Obtain every file path, line number, count and size by reading the repository yourself. Trust no
number quoted in this prompt. Re-derive every one. Record any anchor that does not resolve in
`meta.stale_anchors` and proceed -- a stale anchor is never a reason to stop.

## SETUP

Permitted setup, in order:

1. `git fetch origin main` then `git rev-parse --short origin/main`. This sha is the audited
   tree. Use it in both deliverable filenames, in the branch name, and in `meta.audited_commit`.
2. `bin/venv-python -m scripts.session.preflight --roadmap-detail full` -- populates
   `logs/.preflight-report.json` and refreshes `logs/.recommendations-log.jsonl`. DEDUP
   DISCIPLINE depends on these.
3. Read-only measurement of the tree with `bin/venv-python`, `git ls-files`, `rg`, and `wc`.

Degraded paths. Never abort; set the flag, downgrade confidence, proceed.

- IF the preflight cache-generation fails (credentials or egress down): do NOT abort -- set
  `meta.degraded_dedup: true`, mark every `roadmap_crossref` `confidence: HYPOTHESIS` and
  `dedup_hit_count: null`, and proceed using `docs/ROADMAP-PLATFORM.yaml` and `docs/DECISIONS.md`
  on disk as the dedup surfaces.
- **This clone may be shallow.** Check with `git rev-parse --is-shallow-repository`. IF it
  returns `true`, every claim that depends on repository history -- how often budgets were
  raised, how a registry drained over time, whether a decomposition program actually completed --
  is unverifiable. Do NOT deepen the clone. Instead, record
  `meta.contract_notes: "shallow clone; history-dependent claims marked HYPOTHESIS"` and mark
  every such finding `confidence: HYPOTHESIS`. Present-state evidence read off the working tree
  is unaffected and remains CONFIRMED-eligible.
- IF `bin/venv-python` is unavailable, use `python3`; note it in `meta.contract_notes`.
- IF a repository-wide validation run fails for reasons unrelated to this audit, record it in
  `meta.contract_notes` and do NOT fix it. That would breach the write boundary.

## NORTH STAR

Six principles. These are bars you judge each class against, not rules you pattern-match. Argue
with them where a class warrants it -- a well-argued departure is a better result than compliance.

- **NS-A Model portability is the point.** The limit exists so that a lower-tier model
  (Sonnet-class, Gemini-class, Deepseek-class) can hold an entire file it is EDITING in working
  comprehension and change it without collateral error. It is not an aesthetic preference and not
  a proxy for code quality. Any expansion must trace back to this, or name a different and
  explicitly stated purpose for that class.
- **NS-B The gate measures load, not lines.** The count is a proxy for comprehension load. A
  proxy that can be satisfied while the underlying load is unchanged is a broken proxy, and a
  proxy that fires on files carrying no load is a tax.
- **NS-C Relief before restriction.** A binding gate with no real relief valve degrades into
  either a habit of rubber-stamped raises or a blocked repository. If a class has no honest way
  to comply, the gate is not ready for that class.
- **NS-D Fragmentation is not decomposition.** Spreading the same load across more files an agent
  must reassemble is a loss, not a win. Decomposition is a valid relief valve only where the
  agent's actual working set shrinks. The repository has already reasoned this way twice.
- **NS-E Deterministic ratchets beat periodic review.** Governance that depends on someone
  noticing does not survive an autonomous loop.
- **NS-F Proportionate machinery.** Governance must cost less than the failure it prevents,
  counted in config surface, duplicated code, CI wall-time, and the cognitive load of the
  governance itself on the agents subject to it.

## THE QUESTIONS

Answer all eight. Each gets its own entry in `question_answers[]`.

**Q1 -- Should the rule extend, and to which classes?**
Reach a verdict for EVERY class in the SCOPE table. Verdict enum:
`extend-uniform | extend-calibrated | exempt-with-reason | defer`.
`extend-uniform` = same limit and same unit as the Python gate. `extend-calibrated` = governed,
but with a class-specific limit or unit you must specify. `exempt-with-reason` = deliberately
ungoverned, with the reason recorded so it is not re-litigated. `defer` = should be governed but
a named precondition is missing.

**Q2 -- What is the right unit of measure?**
Verdict enum: `keep-effective-lines | unify-on-bytes | per-class-unit | tokens | composite`.
The repository currently uses four units across four gates: effective lines, raw lines, bytes,
and structural-entity count. Assess at minimum: does each unit track NS-A comprehension load for
the class it governs; is it deterministic and dependency-free; can it be satisfied without
reducing load; what does it cost to compute across the whole tree on every CI run. If you
recommend a single unit, state the conversion for each class and how existing budgets migrate. If
you recommend `composite` (e.g. a primary unit plus a companion guard), state which signal binds
and which advises.

**Q3 -- What enforcement mechanism?**
Verdict enum: `generalize-engine | replicate-per-domain | hybrid`.
The existing pattern is: a `config/*.yaml` budget registry, a limit check registered in
`scripts/checks/registry.py`, a raise-guard diffing the registry against `origin/main`, and a
regeneration command. Assess whether extending means one parameterized engine over a class table,
or another instance of the pattern per class. Weigh against NS-F specifically: the raise-guard
has already been duplicated once, and the check modules are themselves subject to the 500-line
rule. Specify: which tier each new check runs in, what the class taxonomy is keyed on, where it
lives, and what happens to the four existing gates under your design.

**Q4 -- Are the previous ratchet successes a sound foundation for a repo-wide rule?**
Verdict enum: `sound-reusable | sound-needs-generalization | unsound-in-this-direction`.
The repository has at least five ratchets: SLOC budgets, prose budgets, mypy error-count baseline,
coverage baseline, and the composite-action shell-body baseline. Identify what is genuinely
load-bearing in the pattern versus incidental to Python. Name any property that worked because
the governed corpus was Python and does not survive the move to declarative, generated, or
write-once files.

**Q5 -- Does the stated rationale transfer to every class?**
Verdict enum:
`transfers-fully | transfers-comprehension-only | needs-distinct-rationale | does-not-transfer`,
answered per class or per class-group.
The owner gives two reasons for the 500-line rule: lower-tier models make fewer mistakes on small
files, and small files make 100 percent test coverage tractable. The second reason has no referent
for `.tf`, `.yaml`, or `.json` -- there is no per-file coverage concept for them. State, for each
class you recommend governing, the ACTUAL purpose the limit serves there. A class governed for a
reason nobody has articulated will be argued away the first time it is inconvenient.

**Q6 -- Migration and grandfathering.**
Verdict enum: `one-time-grandfather | class-exemption | staged-waves | reject`.
Count the files that would breach your recommended limits. Assess: does the installing PR fail its
own new rule; is the grandfather roster bounded and drainable or open-ended; who or what drains it
given the executor is frozen; what is the sequencing. If your recommendation would strand a
population with no drain path, say so plainly rather than assuming a future program.

**Q7 -- Where is this genuinely ahead of industry practice, and where is it merely unusual?**
Verdict enum: `ahead-justified | ahead-unjustified | at-parity | behind`.
The owner's position is that mainstream limits are designed for human readers and this repository's
constraint is designed for autonomous agents, so precedent is thin. Test that position rather than
accepting it. Assess property-by-property against this checklist, recording each in
`external_checklist` as `met | partial | missed` with evidence. `partial` requires an argued,
property-matched compensating control.

- Per-file size lint exists at all (ESLint `max-lines`, Checkstyle `FileLength`, SonarQube
  file-size rules, Pylint `too-many-lines`)
- Limit is enforced as a blocking gate rather than advisory
- Limit applies beyond the primary language to config and infrastructure files
- Baseline/grandfather mechanism for pre-existing violations rather than a flag day
- Ratchet that prevents silent regression
- Escape hatch that is auditable and attributable rather than an anonymous suppression comment
- Measurement unit is defensible for the artifact type rather than inherited from source code
- Limit is calibrated to a stated consumer with a stated failure mode
- Generated and vendored artifacts are distinguished from hand-authored ones by provenance
- Governance mechanism is itself subject to the limits it enforces
- The agent-era premise: evidence that long-context degradation and edit accuracy actually
  motivate a file-size limit for LLM editors, versus the limit being a human-ergonomics
  convention transplanted without re-derivation

The maturity computation reads this field and no other.

**Q8 -- Questions the requester did not think to ask.**
Answer each seed below AND extend the list with anything recon surfaces. Use the
`{q: Q8, answers: [{question, answer, basis}]}` shape.

- Should exemption key off PROVENANCE -- generated, vendored, write-once -- rather than off
  directory name as it does today? What breaks if a generated file lands in a governed directory?
- A universal 500-line limit would make this repository's own `/plan` and `/audit` workflows
  unable to emit a compliant deliverable, since their outputs routinely exceed it. Is that a
  reason to exempt workflow outputs, to cap them, or to change what those workflows emit?
- Is per-file the right granularity at all? Aggressive decomposition converts a size problem into
  a file-count problem. Is a directory-level or package-level aggregate budget needed alongside
  the per-file one, and does the repository have any precedent for one?
- `__init__.py` is unconditionally exempt from the Python gate while decompose-by-default
  manufactures facade `__init__.py` files. Is that a live loophole, a latent one, or correctly
  scoped? Measure the current facade population before answering.
- Candidate decision CD.30 proposes replacing per-changed-file 100 percent coverage with a
  diff-line-coverage ratchet. If CD.30 ratifies, does the coverage half of the owner's stated
  rationale still hold, and does that change the case for any class?
- Does a line-based unit need a companion long-line guard? Read
  `docs/plans/reports/OVERSEER-terraform-deploy-redesign.yaml` and measure it before answering.
- What is the intended interaction with the `map_source_to_test` mirror convention (Decision 131)?
  Governing a new class creates no test-mapping analogue for it. Is that a gap or correctly out
  of scope?
- Is there a class where the right answer is to change how the file is PRODUCED rather than to
  cap it?

## RUBRIC

Rate every in-scope class against every dimension. Enum: `strong | adequate | weak | absent | n/a`.

`n/a` is a correct and costless answer where a dimension does not structurally apply. Never
manufacture a rating or a finding to fill a cell.

- **VD1 comprehension-load fidelity** -- does the proposed measure track what actually degrades a
  lower-tier model's edit accuracy for this class? (serves Q1, Q2, Q5)
- **VD2 relief-valve existence** -- if the gate binds, does a real, non-destructive way to comply
  exist for this class? (serves Q1, Q6; NS-C)
- **VD3 evasion resistance** -- can the gate be satisfied while the load is unchanged, via
  fragmentation, long lines, generated indirection, or moving content to an ungoverned class?
  (serves Q2, Q3; NS-B)
- **VD4 mechanism economy** -- config surface, duplicated code, CI wall-time, and governance
  cognitive load, relative to the failure prevented. (serves Q3, Q4; NS-F)
- **VD5 determinism and portability** -- same verdict on any runner, no network, no model, no
  heavy dependency, cheap enough for every PR. (serves Q2, Q3)
- **VD6 ratchet integrity** -- correct direction, no auto-seed, loud and cited raises, no path to
  regenerate around review. (serves Q3, Q4; NS-E)
- **VD7 migration tractability** -- is the path from today's population to compliance bounded,
  sequenced, and owned? (serves Q6)
- **VD8 doctrine coherence** -- does the expansion cohere with the agent-first one-file principle
  and the repository's own anti-fragmentation reasoning, or contradict it? (serves Q1, Q3, Q8;
  NS-D)

## DEEP-DIVES

**DD-A -- The unit question, traced end to end.** Feeds Q2, Q8. Measure the distribution of bytes
per effective line across each class. Establish whether within-class spread exceeds between-class
spread. Then take the single most divergent file you can find -- one that passes a line-based gate
while being extreme on bytes, or the converse -- and reason concretely about whether a
lower-tier model editing it would struggle. Conclude with what each candidate unit would and would
not have caught. Do not answer Q2 from first principles alone; ground it in this measurement.

**DD-B -- The mechanism, costed.** Feeds Q3, Q4. Read all four existing size gates and both
raise-guards. Establish precisely what is shared, what is duplicated, and what is genuinely
class-specific. Then cost your recommended design: how many new modules, how many new config
files, how many new registry entries, and whether the resulting modules would themselves pass the
500-line rule. A design whose enforcement code breaches the rule it enforces is a finding.

**DD-C -- Class taxonomy and its home.** Feeds Q1, Q3, Q8. The repository already has a
classification surface with routing entries plus allowlists. Determine whether a size-governance
class taxonomy belongs there, in a new contract, or in code, and what the consequences are for
drift when a new file class appears. Establish whether classification should key on extension,
directory, or provenance, and what each choice misclassifies.

**DD-D -- The write-once population.** Feeds Q1, Q5, Q6, Q8. The largest population of oversized
non-Python files consists of workflow outputs. Establish, by reading the workflows that produce
and consume them, whether an agent ever surgically EDITS such a file or only produces and consumes
it whole. Then decide whether NS-A applies to them at all. This single determination moves the
majority of the affected file count, so state it explicitly and defend it.

## GROUNDING MAP

This map exists so you spend your cognition on judgment, not on grep. Every entry was read from
disk during composition. Every one may have rotted. Verify before relying on any of it; record
non-resolving anchors in `meta.stale_anchors` and continue.

### The current Python gate

- `scripts/checks/sloc/_shared.py:13` -- `_SLOC_LIMIT = 500`.
- `scripts/checks/sloc/_shared.py:14` -- `_CC_LIMIT = 20`.
- `scripts/checks/sloc/_shared.py:16` -- `_SLOC_EXCLUDE_DIRS`, containing `pip`,
  `lambda-packages`, `docker`, `terraform`, `.venv`, `node_modules`, `.git`, `personal_scripts`.
- `scripts/checks/sloc/_shared.py:29` -- `iter_gated_py_files()`, the sole scan definition shared
  by the limit check, the regenerator, and the CC check.
- `scripts/checks/sloc/_shared.py:43` -- the scan skips any file named `__init__.py` and any file
  not ending in `.py`.
- `scripts/checks/sloc/sloc_limits.py:80` -- `validate_sloc_limits`. Its effective-line count is
  `[ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]`.
- `scripts/checks/sloc/sloc_limits.py:21` -- `_update_sloc_budgets`, downward-only, documented as
  never seeding a newly-oversized unregistered file.
- `scripts/checks/sloc/validate_sloc_budget_raises.py:79` -- the raise-guard. Parses raw YAML text
  rather than `yaml.safe_load` so the inline marker survives. SKIPs non-failing when `origin/main`
  is unreachable.
- `config/sloc_budgets.yaml` -- the registry. Its header comment states that 24 `tests/` entries
  below are a one-time grandfather per Decision 130. Count the entries actually present, and count
  how many are `tests/`. Compare with the header.

### The parallel prose gate

- `scripts/checks/prose/prose_limits.py:86` -- `validate_prose_limits`, byte-based, over surface
  classes S1/S2/S4/S8.
- `scripts/checks/prose/prose_limits.py:1-22` -- the module docstring states its relief valves are
  relocate, defer, or take a cited raise, and states that fragmenting ambient prose does not
  reduce the load.
- `scripts/checks/prose/prose_budget_raises.py:1-3` -- describes itself as a self-contained mirror
  of `scripts/checks/sloc/validate_sloc_budget_raises.py`.
- `config/prose_budgets.yaml` -- nested by surface class, seeded at current size, two entries carry
  `# raise-approved: dec-150` markers.

### Other size ceilings already in the tree

- `scripts/checks/roadmap/validate_platform_roadmap.py:13` -- `_ROADMAP_MAX_LINES = 10_000`, raw
  lines, citing Decision 114.
- `scripts/checks/decisions/validate_decisions_size.py:20` -- `_DECISIONS_LIVE_MAX_H2 = 120`, a
  structural-entity count.
- `scripts/checks/decisions/validate_decisions_size.py:21` --
  `_DECISIONS_COMBINED_MAX_BYTES = 700_000`.
- `scripts/checks/ci_guards/validate_composite_action_shell_bodies.py` and
  `config/composite_action_body_baseline.yaml` -- a size-adjacent ratchet over inline shell bodies
  in composite actions, measured in effective lines, with a section that permits no raise marker at
  all.

### Sibling ratchets, for the Q4 foundation assessment

- `config/mypy_baseline.yaml` -- error-count ceiling, ratchets down, marker is
  `# baseline-raised: dec-NNN`.
- `config/coverage_baseline.yaml` -- coverage floor, ratchets UP, marker is
  `# baseline-lowered: dec-NNN`.

### Registration and tiers

- `scripts/checks/registry.py:96` -- `pre_sequence()`.
- `scripts/checks/registry.py:117-122` -- in the `--pre` tier: `validate_sloc_limits`,
  `validate_prose_limits`, `validate_sloc_budget_raises`, `validate_prose_budget_raises`.
- `scripts/checks/registry.py:173` -- `full_sequence()`.
- `scripts/checks/registry.py:205-206` -- in the full tier: `validate_sloc_limits` and
  `validate_prose_limits`. Determine for yourself whether the two raise-guards appear in the full
  tier and whether their absence or presence is coherent with their design.

### Classification surfaces

- `docs/contracts/file-router.yaml` -- carries `routes`, `docs_root_allowlist`, `prose_allowlist`
  with `allowed_globs` and `grandfathered_globs`, and `scripts_root_allowlist`. Enforced by
  `scripts/checks/hygiene/validate_placement.py`.
- `docs/CLAUDE.md` -- the class-to-home map for `docs/`.

### Governing decisions

Read each in `docs/DECISIONS.md`; do not rely on these one-line characterizations.

- **Decision 43** -- original structural limits; declares scope as "all repository code, prompts,
  and agents"; the `.prompt.md` and `.agent.md` rows refer to deleted surfaces.
- **Decision 102** -- replaced the binary waiver with the budget registry and the downward ratchet.
- **Decision 104** -- the owner-tagged check registry.
- **Decision 110** -- ratifies `ROADMAP-PLATFORM.yaml` as the agent-first structured-data exemplar.
- **Decision 114** -- raised the roadmap ceiling to 10,000 lines and REJECTED splitting it into
  per-tier files, on the grounds that N files an agent must reassemble is worse than one coherent
  load.
- **Decision 127** -- the sanctioned-prose taxonomy, including class (d) planning and audit
  artefacts.
- **Decision 128** -- decompose by default; raises must be loud and Decision-cited; no auto-seed.
- **Decision 130** -- extended the scan to the whole repository for Python; one-time grandfather of
  24 `tests/` files; states no hand-authored directory is exempt.
- **Decision 131** -- the source-to-test mirror convention.
- **CD.29 and CD.30** in `docs/ROADMAP-PLATFORM.yaml` `candidate_decisions` -- validation as a
  curated asset, and the diff-line-coverage ratchet.

### Observed population facts -- re-derive every one

Composition measured the following. Treat each as a claim to verify, not as input.

- 85 files that are neither `.py` nor `.md` exceed 500 effective lines.
- Of those, roughly 47 are under `docs/plans/` and 22 under `audits/`.
- 5 `.tf` files exceed 500, the largest being `terraform/iceberg_tables.tf`.
- 3 files under `config/` exceed 500, the largest being
  `config/agent/verification_registry/registry.yaml`.
- 2 files under `.github/workflows/` exceed 500.
- 2 files under `docs/contracts/` exceed 500.
- No `.sh` file exceeds 500.
- Median bytes per effective line, with 10th and 90th percentiles: Python about 53 (44 to 63),
  YAML about 72 (55 to 109), Terraform about 58 (34 to 126), shell about 81 (46 to 152), markdown
  about 106 (71 to 239).
- `docs/plans/reports/OVERSEER-terraform-deploy-redesign.yaml` measures roughly 326 effective
  lines, 255,039 bytes, longest line roughly 8,211 characters.
- `config/sloc_budgets.yaml` currently holds far fewer entries than the 24 its header comment
  describes.

## EMPIRICAL PASS

Bounded sampling. Do NOT exceed these caps.

1. **Class population census** -- measure every tracked file once. This is a full pass but a cheap
   one; it is the factual basis for Q1 and Q6.
2. **At most 12 oversized files**, chosen to span classes, read closely enough to judge whether a
   lower-tier model editing them would struggle, and whether a relief valve exists. Tag findings
   from this pass `evidence_kind: observed`.
3. **At most 8 files that pass a line gate but are extreme on another unit**, or the converse.
   Feeds DD-A.
4. **At most 6 workflow-output files**, plus the workflow definitions that produce and consume
   them, to settle DD-D.
5. **At most 10 commits** touching any budget registry, IF and ONLY IF the clone is not shallow.
   If it is shallow, skip this entirely and mark every history-dependent claim HYPOTHESIS.

Counterfactual test, applied to every proposed gate: **would this gate still fire if the file's
content were reformatted to satisfy it without any reduction in what an agent must comprehend?**
If yes, the gate is measuring load. If no, it is measuring formatting, and that is a VD3 finding.

Observed findings outrank static ones at equal severity.

## METHOD

- **P1 Read.** The four size gates, both raise-guards, the two sibling ratchets, the registry
  tiers, the classification surfaces, and every governing decision above.
- **P2 Census.** Measure the whole tree per class, per unit. Produce the population table.
- **P3 Trace.** For each class: who authors it, who edits it, who consumes it, and what a
  lower-tier model actually does with it. NS-A applies only where an agent edits.
- **P4 Deep-dives.** DD-A through DD-D.
- **P5 Empirical.** The bounded sampling above.
- **P6 Rate.** Fill the rubric. Use `n/a` freely and honestly.
- **P7 Dedup.** Per DEDUP DISCIPLINE, before any finding is written.
- **P8 Synthesize.** Answer Q1 through Q8. Then draft the Decision text. Then compute maturity.
  Synthesis and maturity are LAST.

## DEDUP DISCIPLINE

Before filing ANY finding, search all three ownership surfaces:

- `docs/ROADMAP-PLATFORM.yaml` -- `tier_items[]` and `candidate_decisions[]`
- `docs/DECISIONS.md` -- `^## Decision` headers
- `logs/.recommendations-log.jsonl` -- open and in-progress entries

Record on each finding: `dedup_search_terms` (the terms you actually used) and `dedup_hit_count`.
A hit means the finding becomes a sufficiency assessment of the existing item, or a
`rejected_candidate` -- never a fresh discovery. **A finding with no recorded negative search is
`confidence: HYPOTHESIS`, not CONFIRMED.**

Composition found no `tier_item` owning this territory. Verify that. These open recommendations sit
nearby and are likely dedup hits for narrow findings: rec-2414, rec-2435, rec-2596, rec-2693,
rec-2711, rec-2712, rec-2713, rec-2773, rec-2896, rec-431. CD.29 and CD.30 are adjacent candidate
decisions.

### Deliberate constraints -- DO NOT FLAG

Each of these is a decided position, not an oversight. Flagging one as a defect is a false
positive.

- **Decision 114** -- the 10,000-line roadmap ceiling and the rejection of splitting
  `ROADMAP-PLATFORM.yaml`. This is FIXED and not reopenable. However, you MUST state the
  principled boundary that allows it to stand while other files in the same class are capped, so
  the resulting rule is coherent rather than arbitrary. The requester's position, which you should
  record and may build on: this file is an exception granted to how the roadmap currently exists,
  and explicitly NOT a precedent for how future roadmaps are built.
- **Decision 130 clause 2** -- the one-time `tests/` grandfather was deliberate and bounded.
- **Decision 128 clause 3** -- raise markers are not required to persist after merge.
- **Decision 127** -- the prose taxonomy.
- **Decision 84** -- warehouse and portal invariants.
- **Decision 67** -- the executor is frozen. Do not propose executor-consumed work.
- **Decisions 60 and 73** -- the two-tier presubmit structure.
- Commits from this harness land unsigned. Expected, not a defect.

## OUTPUT

Write exactly two files.

`audits/size-governance-expansion-<sha>.yaml`:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1,
         scope_surfaces: [<the classes you assessed>],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: <enum>, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: <enum>, basis: [], prose: ""}
    - {q: Q3, verdict: <enum>, basis: [], prose: ""}
    - {q: Q4, verdict: <enum>, basis: [], prose: ""}
    - {q: Q5, verdict: <enum>, basis: [], prose: ""}
    - {q: Q6, verdict: <enum>, basis: [], prose: ""}
    - {q: Q7, verdict: <enum>, basis: [], prose: "",
       external_checklist: [{property: "", rating: met|partial|missed, evidence: ""}]}
    - {q: Q8, answers: [{question: "", answer: "", basis: []}]}
  class_verdicts:
    <class name>: {verdict: extend-uniform|extend-calibrated|exempt-with-reason|defer,
                   unit: "", limit: "", relief_valve: "", rationale: "",
                   population_over_limit: 0, confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: <class>, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: <class>, dimension: VD1..VD8, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  draft_decision:
    number: "NNN -- allocate at merge time, do not guess"
    title: ""
    status: Proposed
    problem: ""
    decision: ""
    reversal_conditions: ""
    rationale: ""
    related: ""
  findings:
    - {id: SGE-01, surface: <class|shared>, question: Q1..Q8, dimension: VD1..VD8,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "",
       severity: critical|high|medium|low, severity_rationale: "",
       confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [], highest_leverage_change: <id>,
            maturity_overall: <value>}
```

`audits/size-governance-expansion-<sha>.md` -- prose companion, at most 1500 words, the executive
layer a human reads first. Lead with the eight verdicts and the recommended design in one
paragraph. Do not restate the YAML.

### Invariants

- **COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list.
  `total_findings = len(findings) = novel_count + planned_insufficient_count +
  planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates[]`, NOT in
  findings. `rubric_ratings`, `question_answers`, `class_verdicts` and `draft_decision` are
  systems of record referenced FROM findings, never re-counted. `top_improvements` and
  `highest_leverage_change` MUST be finding ids.
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal. Name the property the control exercises, cite where it operates, and state why the
  control would FAIL if the defect were real.
- `CONFIRMED` requires the behavior traced to a file:line or to an observed sampled artifact.
  Anything less is `HYPOTHESIS`.
- Every class in the SCOPE table must appear in `class_verdicts`, including those you exempt.
- `draft_decision.number` is a placeholder. Do not guess a number; the human allocates it.

## SEVERITY AND MATURITY

Assign severity AFTER judgment, by defect class. Never inherit it from this prompt's framing.

- **critical** -- the proposed or existing governance would produce a wrong-but-trusted outcome:
  a gate that reports compliance while comprehension load is unbounded, or an expansion that
  would wedge the repository with no path to a passing state.
- **high** -- a weakness that materially reduces the guarantee AND whose compensating controls you
  judged insufficient.
- **medium** -- redundancy, ambiguity, or inconsistency with a clear fix.
- **low** -- clarity or wording.

A compensating control lowers severity only if it PROPERTY-MATCHES: it must exercise the same
property AND fail if the defect were real. Apply the counterfactual to the control itself. A
control that cannot catch the break neither lowers severity nor justifies dismissal.

Maturity is computed LAST, per class plus one overall, top-down, first match wins:

- **frontier** -- 0 open critical and 0 open high findings for that class, AND every property in
  Q7's `external_checklist` rated `met` or `partial`, never `missed`.
- **strong** -- 0 critical and at most 1 high.
- **solid** -- at most 1 critical.
- **nascent** -- otherwise.

The top rating remains reachable if you argued a property-matched compensating control. This
framing does not foreclose it.

## COMMIT AND PR MECHANICS

1. Derive the base ONCE: `git fetch origin main`, then `git rev-parse --short origin/main`. That
   sha IS the audited tree. Use it in both filenames, the branch name, and `meta.audited_commit`.
2. `git switch -c audit/size-governance-expansion-<sha> origin/main` so the PR diff contains only
   the two deliverables. This is a deliberate, documented exception to the repository's
   `claude/*` session-branch rule: this session needs a clean two-file diff off the audited base.
3. Repository-wide validation is advisory outside CI here. A clean YAML parse of both deliverables
   is the real pre-push gate:
   `bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/size-governance-expansion-<sha>.yaml`.
   An unrelated `validate --pre` failure is recorded in `meta.contract_notes`, never fixed.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, and `--no-gpg-sign` if
   signing is unavailable.
5. `git push -u origin HEAD`.
6. Open the PR via `mcp__github__create_pull_request`, base `main`, ready for review, title
   `audit: structural-size governance expansion beyond Python (terraform, yaml, workflows, shell, generated)`,
   body = a 2 to 3 sentence lede plus the `summary` block in a yaml fence.
7. **END THE TURN.** Do not poll. Do not merge. Do not subscribe. Do not self-approve.

## GUARDRAILS

The write boundary is a closed list. You create or modify exactly:

- `audits/size-governance-expansion-<sha>.yaml`
- `audits/size-governance-expansion-<sha>.md`

Nothing else. Not a config file, not a check module, not a decision entry, not a fix for an
unrelated failing gate. If you believe something needs changing, that belief belongs in a finding.

Honesty clauses:

- **Fewer than roughly 8 surviving findings is a valid result. State it plainly. Do not pad.**
- Precision over volume. One traced, CONFIRMED finding is worth more than five plausible ones.
- `n/a` in a rubric cell and an empty `rejected_candidates` list are both legitimate outcomes.
- If a class genuinely should NOT be governed, say so. The requester's instinct is that everything
  non-prose should be covered; an argued exemption that survives your own scrutiny is more useful
  than a rubber-stamped extension.
- If you cannot answer a question with the evidence available, say which evidence was missing
  rather than answering it thinly.
