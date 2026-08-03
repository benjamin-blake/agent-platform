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

**Where the candidates are.** This prompt does not carry a separate numbered candidate list. The
candidates you must adjudicate are, exactly: (a) the six items under READ FIRST, each of which
asserts a state of the world you must confirm or refute, and (b) every bullet in the GROUNDING MAP
subsection headed "Observed population facts -- re-derive every one". That is the candidate set
wherever this prompt says "the candidates". The Q8 seeds are QUESTIONS, not candidates: they are
answered in `question_answers[Q8].answers[]`, and they enter `findings[]` or
`rejected_candidates[]` only if answering one surfaces a defect. The remaining GROUNDING MAP
entries are anchors handed over to save you grep; verify them, but they are not candidates and a
stale one goes to `meta.stale_anchors`, not to `rejected_candidates[]`.

Adjudicate each candidate to exactly one disposition, and map it to the output contract as
follows:

- CONFIRMED defect, no existing item owns it -> `findings[]`, `roadmap_crossref.classification:
  novel`
- Real, and an existing roadmap item / decision / open recommendation owns the territory but its
  remedy is insufficient -> `findings[]`, classification `planned-insufficient`
- Real, owned by an item whose remedy is adequate but unbuilt -> `findings[]`, classification
  `planned-unbuilt`
- Real, and fully covered by an existing item's built remedy -> `rejected_candidates[]`
- Not a defect -> `rejected_candidates[]`. Name the compensating control and why it
  property-matches WHEN the reason for dismissal is that a control covers it. When the reason is
  simply that the candidate is not a defect at all -- the state of the world is as described and
  nothing is wrong with it -- set `compensating_control` and `control_property_match` to the
  literal `n/a` and put the reasoning in `why_dismissed`. A candidate you confirm as true-and-fine
  belongs here; an empty `rejected_candidates[]` is therefore unlikely but not forbidden.

## READ FIRST -- DISAMBIGUATION TRAPS

Six hazards. Each invites a specific misread that would waste most of a session.

1. **"SLOC" names two things.** It is (a) the concrete Python-specific measure in
   `scripts/checks/sloc/sloc_limits.py` (the counting expression at lines 38 and 91; the limit
   CONSTANT and the file walker live separately in `_shared.py`) -- non-blank, non-`#`-prefixed
   lines -- and (b) the
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

5. **Decision 43's two legacy rows are in DIFFERENT states -- do not treat them alike.** Its
   structural-limits table declares limits "across all repository code, prompts, and agents" and
   carries rows for `.prompt.md` (3000 lines) and `.agent.md` (1500 lines). The `.agent.md` row IS
   a dead letter: zero such files are tracked. The `.prompt.md` row is NOT: 12 such files are
   tracked and live, under `.github/prompts/scheduled/` and
   `config/agent/executor/prompts/` (the latter is Layer 5 of the instruction architecture). Only
   the legacy top-level `.github/prompts/*.prompt.md` set was deleted at T-1.13. Verify both counts
   yourself. This trap exists because `.prompt.md` is OUT of scope as an audit target (it is
   markdown) while its Decision 43 row is live -- so the row is easy to cite as dead coverage when
   it is not. Establish whether any check enforces it (verify against `config/prose_budgets.yaml`
   and against what `scripts/checks/prompts/validate_prompt_files.py` actually asserts), then
   record the result as markdown observation (a) per THE MARKDOWN RULE. If you CONFIRM the row is live and
   unenforced, that is a real defect: file it as a finding with `surface: shared` (not optional --
   `shared` is the legal home for a defect belonging to no class, and filing is what keeps this
   candidate adjudicable). If you REFUTE it, it goes to `rejected_candidates[]`. Either way the Q8
   observation also records it. This is the ONE markdown finding this audit may contain, and it is
   the sense in which the Q8 observation is "the whole of markdown's presence": no markdown
   `class_verdicts` entry, no markdown census, no second markdown finding.

6. **Ratchet direction is per-registry, not universal.** `config/coverage_baseline.yaml` ratchets
   UP (a minimum that may only rise). `config/sloc_budgets.yaml`, `config/prose_budgets.yaml` and
   `config/mypy_baseline.yaml` ratchet DOWN (a ceiling that may only fall). A generalized engine
   that assumes one direction is wrong for the other.

## SCOPE

### In scope -- file classes to reach a verdict on

Every class below is BUILT and present on disk. Enumerate the current population of each yourself.

All globs are repo-root-relative. **Classification is FIRST MATCH WINS, in the table order given
below.** Note that row 1 (generated) deliberately precedes every hand-authored row, so a generated
file living inside a hand-authored directory is classified by its provenance, not its location --
`terraform/personal/.terraform.lock.hcl` is Generated (row 1), never Terraform (row 2), and
`config/mypy_baseline.yaml` is Generated (row 1), never Config (row 3). A genuine cross-row case
lower down: `docs/decisions-index.json` would match row 11's `**/*.json` but is caught by row 1
first. This ordering is a compose-time convenience so your census is reproducible; whether
provenance SHOULD outrank location is exactly Q8 seed 1 and DD-C, and you may recommend otherwise.

The `slug` column is the PINNED identifier. Use it verbatim as the key in `class_verdicts` and as
the `surface` value in `rubric_ratings`, `per_surface_assessment` and `findings`, so those four
blocks cross-reference mechanically. Do not invent or prettify these strings. `findings[].surface`
additionally accepts the literal `shared` for a defect belonging to no single class; `shared` is
NOT a slug and never appears in `class_verdicts`, `rubric_ratings` or `per_surface_assessment`.

| # | slug | Locations (repo-root-relative) | Role |
|---|---|---|---|
| 1 | `generated` | any file meeting the provenance test below, wherever it lives | projections of a source of truth |
| 2 | `terraform` | `terraform/**/*.tf`, `terraform/**/*.hcl`, `*.hcl` | hand-authored infrastructure |
| 3 | `config` | `config/**/*.yaml`, `config/**/*.yml` | machine-consumed configuration and registries |
| 4 | `contracts` | `docs/contracts/**/*.yaml` | agent-consumed field/procedure semantics |
| 5 | `ci_workflows` | `.github/**/*.yml`, `.github/**/*.yaml` | CI/CD definitions (note `.github/agents/schedule.yaml` lands here by glob though its role is agent scheduling -- flag the mismatch if it matters to your verdict) |
| 6 | `shell` | `**/*.sh`, plus extensionless files under `bin/` whose first line is a shell shebang | setup, hooks, wrappers |
| 7 | `lambda_manifests` | `src/lambdas/*/manifest.yaml` | packaging descriptors |
| 8 | `roadmaps` | `docs/ROADMAP-*.yaml` (there are THREE, not two -- enumerate them) | monotonically growing work-lists |
| 9 | `workflow_outputs` | `docs/plans/**/*.yaml`, `audits/**/*.yaml` | one file per workflow run |
| 10 | `test_fixtures` | `tests/fixtures/**/*.yaml`, `tests/fixtures/**/*.yml`, `tests/fixtures/**/*.json` | inputs asserted against by tests |
| 11 | `data_query` | `**/*.sql`, `**/*.json`, `**/*.toml`, `**/*.jsonl` | miscellaneous structured |
| 12 | `residual` | every tracked, non-excluded file matching no row above | see the residual rule |

**Generated provenance test (row 1).** A file is generated if ANY holds: it carries a do-not-edit
or generated-by banner in its first 10 lines; a checked-in command or check regenerates it (search
the path in `scripts/` and `.github/workflows/` -- there is no Makefile in this repository); or it
is a documented projection of a named source of truth. Known members you should expect the test to
catch, and should verify rather than assume: `docs/decisions-index.json`, both
`.terraform.lock.hcl` files, and `config/mypy_baseline.yaml` (which documents `--seed` and
`--update` commands in its own header). Note the baseline family is NOT uniform, and this is a real
test of the provenance key rather than a trivium: `config/coverage_baseline.yaml` and
`config/composite_action_body_baseline.yaml` mirror the same registry shape but document NO
regeneration command, so under the test as written they are hand-authored `config`, not
`generated`. Verify all three and decide whether a key that splits sibling registries across two
classes is the right key -- that is DD-C and Q8 seed 1. Note the interesting
edge: `config/sloc_budgets.yaml` is BOTH machine-regenerated (by `--update-sloc-budgets`) AND
hand-edited (to add raise markers), so its provenance is genuinely hybrid. `config/prose_budgets.yaml`
has NO regeneration command at all despite mirroring the same registry shape -- verify that
asymmetry and decide what it means for Q3. For the census, first-match-wins settles both
mechanically: `config/sloc_budgets.yaml` satisfies the provenance test and is `generated`;
`config/prose_budgets.yaml` does not and is `config`. You do not get to re-file either. The
judgment asked of you is what that MEANS -- whether a key that puts a hand-edited registry in the
generated class, and splits two mirror-shaped registries across two classes, is the right key --
and that belongs in DD-C and Q8 seed 1, not in a reclassification.
If provenance is genuinely undeterminable for a file, classify it by extension and record the
ambiguity as a DD-C observation.

**Residual class (row 12) -- MANDATORY.** `git ls-files` tracks files that match no row above.
Composition observed these unmatched extensions: `.txt` (12, including requirements files), `.log`
(3), `.gitignore` (2), `.example` (2), `.gitkeep` (2), `.lock`, `.tfrc`, `.importlinter`,
`.gitattributes`, `.python-version`, `.baseline` (1 each), and 3 extensionless files
(`bin/venv-python` is a fourth extensionless file but carries a bash shebang, so row 6 `shell`
claims it before residual can). It also
observed unmatched `.yaml` files, which matter more because YAML is where the oversized population
lives: at least `.pre-commit-config.yaml`, `EVALUATION-PROMPTS.yaml`, and
`docs/intent-migration/MANIFEST.yaml` (which exceeds 500 effective lines). Enumerate the real set
yourself; do not trust this list.

`class_verdicts` MUST carry a `residual` entry giving the DEFAULT verdict for any file matching no
named class -- because the deliverable is draft Decision text, and a rule built from a
closed-but-partial table ships a gap on day one. Its `verdict` uses the SAME pinned Q1 enum as every other
class -- map your intent onto it so no coercion is needed: govern-by-default -> `extend-uniform`
(or `extend-calibrated` if the default limit differs); leave-ungoverned -> `exempt-with-reason`;
block-the-PR-until-classified -> `defer`, naming the missing precondition as "a classification
decision for the new file class". Then say in `rationale.actual_purpose` what happens when a NEW
file class appears after the Decision lands. Leaving future classes ungoverned by default and
blocking on an unclassified file are both defensible; pick one and own it.

**THE MARKDOWN RULE -- markdown is entirely OUT OF SCOPE.** Be precise about why, because the
obvious reason is false and you should not repeat it: markdown is NOT already fully governed.
`validate_prose_limits` covers only four surface classes (root ambient set, per-directory
`CLAUDE.md`, `**/SKILL.md`, `PROJECT_CONTEXT.md`) and `validate_decisions_size` covers the decision
corpus; roughly 28 tracked `.md` files exceed 500 effective lines and many are governed by neither.

Markdown is excluded because the requester scoped it out, on evidence you should record but not
re-litigate: every agent-instruction markdown surface is ALREADY compliant (`.claude/commands/**`
max 119 effective lines, `**/*.prompt.md` max 155, `**/*.instructions.md` max 127,
`docs/contracts/**/*.md` max 193, `audits/**/*.md` max 141 -- zero over 500 in any of them), and
the one markdown class with real violations, `docs/audit-prompts/**` (13 of 23 over 500, largest
3368), is executed only by frontier-tier models. Governing markdown would mean 8+ carve-outs for a
population with almost no real violations, layered on top of an existing byte-based regime.

**QUARANTINE -- read this before you reuse the reasoning above.** The frontier-consumed argument is
the requester's SCOPING INPUT for excluding markdown. It is NOT a rationale available to you for any
in-scope class verdict, and NS-A forbids it: "exempt because only a frontier model reads it" is
precisely the tier-keyed answer the fixed-floor constraint rules out. This matters because
`workflow_outputs` (`audits/**/*.yaml`, `docs/plans/**/*.yaml`) is also frontier-consumed and is
81 percent of the affected population -- if DD-D concludes that class should be exempt, the reason
must be that no agent surgically EDITS those files, never that a capable model reads them.

Do NOT census markdown, do not classify it, and do not issue class verdicts on it. Record exactly one
observation carrying these two facts, so a future decision can pick them up. "Observation" has a
concrete home: an entry in `question_answers[Q8].answers[]`, with `question` naming the topic and
`answer` carrying the facts. The same applies anywhere this prompt says "record as a DD-C
observation" -- there is no separate observations block; it folds into the relevant Q8 answer.
  (a) Decision 43's `.prompt.md` row (3000 lines) is LIVE and governs 12 tracked files, and no
      check appears to enforce it -- verify that claim before recording it.
  (b) `docs/ROADMAP-PRODUCT.yaml` carries a header stating it SUPERSEDES
      `docs/ROADMAP-PRODUCT.md`, with the markdown "retained for one transition cycle as a recovery
      artefact". So this is a superseded transitional artifact, not a live peer -- verify the header
      before recording it. The observation worth keeping is narrower than a format-twin
      inconsistency: a retiring duplicate is governed differently from its successor purely by
      extension, which is a question about how governance handles transition windows.
That observation is the whole of markdown's presence in this audit. Do not expand it.

**Exclusion outranks classification.** The exclusion list below is applied FIRST, before
first-match-wins runs. A generated `.py` file is excluded (Python is out of scope), not row 1
`generated`. Exclusion wins every tie.

**Excluded from all classes** (do not census, do not verdict):
- anything under `.git/`, `.venv/`, `node_modules/`, `pip/`, `lambda-packages/`, `docker/`,
  `personal_scripts/`, and any path not tracked by `git ls-files`;
- **`**/*.py`** -- Python is already governed and is context-only for this audit (see "Context-only"
  below). It is NOT a residual member; do not census it and do not issue a class verdict for it;
- **`**/*.md`, without exception** -- see THE MARKDOWN RULE above. This is an extension-level
  exclusion applied before classification, so no markdown file reaches `residual`. Note it is
  `.md`-scoped, not path-scoped: NON-markdown files under `docs/plans/reports/` are NOT excluded,
  and one of them (`OVERSEER-terraform-deploy-redesign.yaml`) is class `workflow_outputs` and is
  DD-A's centrepiece.

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

- **effective lines / CENSUS RULE -- pinned, not your judgment.** Effective lines are non-blank
  lines whose first non-whitespace character is not `#` -- what the current Python gate counts.
  Comment syntax differs by language (`.tf` uses `#`, `//` and `/* */`; JSON has no comments), so
  this does not port cleanly, which is itself evidence for Q2. For the P2 census and for every population number
  you report, apply the Python definition of effective lines VERBATIM to every class: non-blank,
  first non-whitespace character not `#`. Do NOT strip `//` or `/* */` in `.tf`, and do not apply
  per-language comment rules. This is deliberate: it makes your census reproducible, it matches
  how the numbers in the GROUNDING MAP were derived so you can compare like with like, and it
  keeps the census independent of the Q2 verdict you have not reached yet.
  Then, SEPARATELY, as part of answering Q2, report how much the population would change for the
  classes where the rule is wrong -- at minimum `.tf` (where `//` and `/* */` comments are
  miscounted as code) and `.json` (which has no comments, so every line counts). If that delta
  changes any Q1 or Q6 verdict, that fact is itself a finding. Never silently substitute a
  different counting rule; if you believe another rule is better, say so in Q2 and show both
  numbers.
- **ratchet**: a registry of per-file budgets plus a gate, where movement in the tolerant
  direction is unrestricted and movement in the permissive direction requires a marker citing a
  real Decision.
- **relief valve**: the sanctioned way to bring an over-budget file into compliance. This
  repository has already used SIX distinct ones, and you must consider all six for every class --
  treating the list as {decompose, raise} would wrongly make several classes look ungovernable:
  1. **Decompose** into a facade package (the Python gate's valve).
  2. **Relocate** content to another surface (the prose gate's valve).
  3. **Defer** detail to an uncapped auxiliary file the surface points at rather than inlines.
  4. **Compact in place** -- strip terminal/dead content while preserving the single file. Used on
     `ROADMAP-PLATFORM.yaml` (Decision 147) and on the decision corpus as a compact-to-stub
     lifecycle (Decision 149).
  5. **Archive** -- move inert entries to a sibling file under a lifecycle rule (Decision 146).
  6. **Take a loud, Decision-cited raise** (Decision 128's marker mechanism).
  A seventh possibility is not a relief valve but a redesign: **change how the file is produced**
  so it never reaches the limit. Q8 asks about this explicitly.
  Which valves are honest for which class is a judgment you must make. Valves 4 and 5 are the ones
  a registry, an append-only roadmap, or a generated projection can typically use when 1 is
  forbidden by anti-fragmentation.
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
  `meta.degraded_dedup: true`, set every FINDING's top-level `confidence` to `HYPOTHESIS` (there is
  no `confidence` key inside `roadmap_crossref`), set every `roadmap_crossref.dedup_hit_count` to
  `null`, and proceed using `docs/ROADMAP-PLATFORM.yaml` and `docs/DECISIONS.md` on disk as the
  dedup surfaces.
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
- IF `git fetch origin main` fails (network or auth): do NOT abort and do NOT skip the sha. Fall
  back to `git rev-parse --short HEAD`, use THAT sha everywhere the base sha is called for, branch
  from `HEAD` instead of `origin/main`, and record
  `meta.contract_notes: "origin unreachable; audited tree is local HEAD <sha>, not origin/main"`.
  The audit is still valid against the tree you actually read.
- IF web access is unavailable when answering Q7, do not abort: answer the external half from model
  knowledge. Keep the two-part `evidence` shape the Q7 section pins -- the repo-side citation is
  still required -- and suffix only the external half with `(model knowledge, unverified)`. Add a
  note to `meta.contract_notes`. Q7 is never a reason to stop.
- IF the PR creation call fails at the end: the deliverables are already committed and pushed,
  which is the substantive result. Report the failure and the branch name in your final message
  and STOP. Do not retry more than twice, and do not fall back to any other publication route.

## NORTH STAR

Six principles. These are bars you judge each class against, not rules you pattern-match. Argue
with them where a class warrants it -- a well-argued departure is a better result than compliance.

- **NS-A Model portability is the point, against a FIXED lowest common denominator.** The limit
  exists so that a lower-tier model can hold an entire file it is EDITING in working comprehension
  and change it without collateral error. It is not an aesthetic preference and not a proxy for
  code quality. Any expansion must trace back to this, or name a different and explicitly stated
  purpose for that class.

  The design target is a fixed floor set at the LOWEST-CAPABILITY TIER the platform routes work to
  -- repo-grounded as the DeepSeek-class executor default (`scripts/llm/utils.py`, the
  `MODEL_PLANNING` / `MODEL_EXECUTION` values) and described in `AGENTS.md` as the
  Sonnet/Gemini/Deepseek tier that "degrade[s] on comprehension". If the system works at that
  floor, it works for anything above it. The requester's forward reference point is a
  next-generation DeepSeek-Flash-class model; treat that as ILLUSTRATIVE of the tier, not as a
  version to resolve against this tree -- deliberately so, because a floor pinned to a named
  version would itself be the kind of roster-dependent input this constraint exists to forbid.
  This is a REQUESTER CONSTRAINT, not your judgment call (see the do-not-flag list). It rules out an entire family of otherwise-plausible answers, so do
  not propose any of them: no limit that varies by which model consumes the file, no per-model or
  per-tier budget, no exemption granted because a surface happens to be read only by a frontier
  model today, and no governance input that has to be revised when the model roster changes. Model
  identities move constantly; a rule keyed to them would need continuous renegotiation, and the
  engineering cost of that is the reason the floor is fixed instead.
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

**Per-class questions and the scalar `verdict` field -- pinned convention.** Q1, Q5 and Q6 are
answered PER CLASS. The per-class answers live in `class_verdicts[<class>]`, which has a field for
each: `verdict` (Q1), `rationale` (Q5), and `migration` (Q6). The scalar `verdict` in each of those
three `question_answers[]` entries is a ROLL-UP, computed by this rule and not by your judgment.
Roll up over the relevant field: Q1 over `class_verdicts[*].verdict`, Q5 over
`class_verdicts[*].rationale.transfer`, Q6 over `class_verdicts[*].migration.mode`. If every class
shares one value for that field, use it; otherwise use the literal string `mixed` and let the
`prose` field summarize the split. `mixed` is a legitimate and expected answer for all three. Do
not invent a different convention, and do not omit a class from `class_verdicts` because its
answer felt obvious.

**Q1 -- Should the rule extend, and to which classes?**
Reach a verdict for EVERY class in the SCOPE table, including `residual`. Verdict enum:
`extend-uniform | extend-calibrated | exempt-with-reason | defer` (roll-up may also be `mixed`).
`extend-uniform` = same limit and same unit as the Python gate. `extend-calibrated` = governed,
but with a class-specific limit or unit you must specify. `exempt-with-reason` = deliberately
ungoverned, with the reason recorded so it is not re-litigated. `defer` = should be governed but
a named precondition is missing.

**Q2 -- What is the right unit of measure?**
Verdict enum: `keep-effective-lines | unify-on-bytes | per-class-unit | tokens | composite`.
The repository currently uses four distinct units across the five size-measuring gates DD-B
enumerates: effective lines, raw lines, bytes,
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
lives, and what happens to the existing gates under your design.

On tier cost specifically -- do not treat "run it in `--pre`" as free. Decision 135 replaced the
`--pre` edited-set tier gate with live, cacheless, strictly-additive affected-set selection, and
`--pre` checks carry a `pre_globs` scoping declaration (visible in `scripts/checks/registry.py`,
e.g. on `validate_tier_floor`). Establish whether a whole-tree size census can be `pre_globs`-scoped
at all, or whether it must walk everything on every PR, and price that under VD4 and NS-F. Note
that the incumbent `validate_sloc_limits` declares no `pre_globs` -- work out what that implies
before recommending N more whole-tree walks.

**Q4 -- Are the previous ratchet successes a sound foundation for a repo-wide rule?**
Verdict enum: `sound-reusable | sound-needs-generalization | unsound-in-this-direction`.
The repository has at least five ratchets: SLOC budgets, prose budgets, mypy error-count baseline,
coverage baseline, and the composite-action shell-body baseline. Identify what is genuinely
load-bearing in the pattern versus incidental to Python. Name any property that worked because
the governed corpus was Python and does not survive the move to declarative, generated, or
write-once files.

**Q5 -- Does the stated rationale transfer to every class?**
Verdict enum:
`transfers-fully | transfers-comprehension-only | needs-distinct-rationale | does-not-transfer`
(roll-up may also be `mixed`). Answered per class, recorded in `class_verdicts[<class>].rationale`.
The owner gives two reasons for the 500-line rule: lower-tier models make fewer mistakes on small
files, and small files make 100 percent test coverage tractable. The second reason has no referent
for `.tf`, `.yaml`, or `.json` -- there is no per-file coverage concept for them. State, for each
class you recommend governing, the ACTUAL purpose the limit serves there. A class governed for a
reason nobody has articulated will be argued away the first time it is inconvenient.

**Q6 -- Migration and grandfathering.**
Verdict enum: `one-time-grandfather | class-exemption | staged-waves | reject` (roll-up may also be
`mixed`). Answered per class, recorded in `class_verdicts[<class>].migration`.
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

**Where Q7's evidence comes from -- this is the one question not answerable from the repository.**
Each checklist property has two halves: does THIS repository have the property (answer from the
repository, cite `file:line` or a mechanism name), and does mainstream practice have it (answer
from outside). For the outside half you MAY use web search if it is available to you, and you MAY
answer from your own model knowledge if it is not. Populate `evidence` as
`"<repo side: file:line or mechanism> || <external side: tool or source name>"` -- a DOUBLE pipe,
so it is not confused with the single-pipe alternation used elsewhere in the schema. Suffix the
external side with `(model knowledge, unverified)` whenever you did not verify it against a live
source. An unverified external claim is acceptable here and must be labelled; a silently
unverified one is not. The `rating` reflects the REPOSITORY's standing on the property, not
mainstream's.

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

`external_checklist` is the SOLE source for the checklist half of the `frontier` maturity gate.
No other field feeds that half. (The finding-count half is defined under SEVERITY AND MATURITY.)

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
- **If Q2 unifies the unit, what happens to the prose regime?** The markdown corpus is governed in
  BYTES by `validate_prose_limits` and is out of scope here. But if your Q2 answer moves the
  in-scope classes to bytes, tokens, or a composite, the two regimes either converge on one unit or
  diverge further. Say which, and say whether a future markdown decision would inherit your unit or
  keep its own. One short paragraph -- do not audit the prose regime.
- **What does the fixed-floor choice cost?** NS-A pins governance to a fixed
  lowest-common-denominator model rather than to which model actually consumes a file. That is
  settled and not yours to overturn -- but name what it costs: which files end up governed more
  tightly than their real consumers require, and whether any class is so exclusively
  frontier-consumed that a uniform floor is measurably wasteful there. Answer in one short
  paragraph; this is a cost disclosure, not a reopening.
- **What is the base rate of the harm?** Every recommendation here traces to NS-A -- lower-tier
  models mis-editing large files. Establish whether that harm has ever been OBSERVED in this
  repository's non-Python classes, or whether it is assumed. Look for evidence in CI-RCA
  recommendations, in `logs/.recommendations-log.jsonl`, and in the Decisions that motivated the
  existing gates (Decision 128's account of `convergence_health.py` is the clearest recorded case,
  and it is Python). If no non-Python instance exists, say so plainly -- recommending gates on an
  assumed harm is a defensible engineering choice, but it should be a stated one, and it bears
  directly on how aggressive Q6's migration should be. This question can lower the severity of
  your own recommendations; let it.

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

**DD-B -- The mechanism, costed.** Feeds Q3, Q4. Read all FIVE existing size-measuring gates --
`validate_sloc_limits`, `validate_prose_limits`, `validate_platform_roadmap`'s
`_roadmap_size_issues`, `validate_decisions_size`, and `validate_composite_action_shell_bodies`
(which measures inline bodies in effective lines) -- plus all four raise-guards (the two
budget-raise guards and the two baseline-edit guards named in the GROUNDING MAP). Establish precisely what is shared, what is duplicated, and what is genuinely
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
- `scripts/checks/sloc/sloc_limits.py:80` -- `validate_sloc_limits`. ANCHOR CONVENTION: where this
  map cites a registered check by name, the line is its `@registry.register(...)` decorator, with
  the `def` on the following line. The same holds for `validate_sloc_budget_raises.py:79` and
  `prose_limits.py:86`. An off-by-one against the `def` line is this convention, not a stale
  anchor. Its effective-line count is
  `[ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]`.
- `scripts/checks/sloc/sloc_limits.py:20` -- `def _update_sloc_budgets`, downward-only, documented
  as never seeding a newly-oversized unregistered file.
- `scripts/checks/sloc/validate_sloc_budget_raises.py:79` -- the raise-guard. Parses raw YAML text
  rather than `yaml.safe_load` so the inline marker survives. SKIPs non-failing when `origin/main`
  is unreachable.
- `config/sloc_budgets.yaml` -- the registry. Its header comment states that 24 `tests/` entries
  below are a one-time grandfather per Decision 130. Count the entries actually present, and count
  how many are `tests/`. Compare with the header.

### The parallel prose gate

- `scripts/checks/prose/prose_limits.py:86` -- `validate_prose_limits`, byte-based, over surface
  classes S1/S2/S4/S8.
- `scripts/checks/prose/prose_limits.py:1-21` -- the module docstring states its relief valves are
  relocate, defer, or take a cited raise, and states at lines 13-15 that fragmenting ambient prose
  does not reduce the load.
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
  `_DECISIONS_COMBINED_MAX_BYTES = 700_000`. Note this is the live+archive COMBINED ceiling and it
  survives; the constant Decision 160 retired was the separate LIVE-byte ceiling
  (`_DECISIONS_LIVE_MAX_BYTES`, Decision 145's 500,000), which is absent from the tree. Two
  different ceilings on one surface -- do not conflate them.
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
- `scripts/checks/registry.py:117-122` -- a contiguous block of SIX checks in the `--pre` tier, in
  this order: `validate_sloc_limits` (117), `validate_prose_limits` (118),
  `validate_sloc_budget_raises` (119), `validate_coverage_baseline_edits` (120),
  `validate_mypy_baseline_edits` (121), `validate_prose_budget_raises` (122). The four
  size-and-prose checks are interleaved with the two sibling-ratchet raise-guards, which is
  directly relevant to Q3 and Q4 -- the raise-guard shape is already applied to four different
  registries side by side in one block.
- `scripts/checks/registry.py:173` -- `full_sequence()`. Handed over so you do not have to
  rediscover it: `validate_coverage_baseline_edits` and `validate_mypy_baseline_edits` DO appear in
  `full_sequence()`, while `validate_sloc_budget_raises` and `validate_prose_budget_raises` do NOT.
  The four raise-guards therefore run in different tier sets. Whether that asymmetry is principled
  (a diff-vs-base check is meaningless post-merge) or accidental is yours to judge, and it bears
  directly on Q3 and Q4.
- `scripts/checks/registry.py:205-206` -- in the full tier: `validate_sloc_limits` and
  `validate_prose_limits`. (Nearby line numbers in this region have drifted before; re-derive the
  exact lines and record any miss in `meta.stale_anchors`.)

### Classification surfaces

- `docs/contracts/file-router.yaml` -- carries `routes`, `docs_root_allowlist`, `prose_allowlist`
  with `allowed_globs` and `grandfathered_globs`, and `scripts_root_allowlist`. Enforced by
  `scripts/checks/hygiene/validate_placement.py`.
- `docs/CLAUDE.md` -- the class-to-home map for `docs/`.

### Governing decisions

Read each in `docs/DECISIONS.md`; do not rely on these one-line characterizations.

- **Decision 43** -- original structural limits; declares scope as "all repository code, prompts,
  and agents". Its `.agent.md` row refers to a deleted surface (0 tracked files); its `.prompt.md`
  row does NOT (12 tracked files). See trap 5.
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

### The post-131 size-governance family -- READ THESE, they carry the counter-evidence

Q4 asks whether the ratchet family is a sound foundation. The decisions below are where that
family was stress-tested, and two of them cut AGAINST simply adding more ceilings. A Q4 answer that
does not engage with Decisions 160, 145 and 147 has not done the work.

- **Decision 134** -- ratified `DECISIONS.md` size governance at Decision-114 parity: a live-header
  ceiling plus a live-byte ceiling.
- **Decision 145** -- raised the `DECISIONS.md` live-byte ceiling 400,000 -> 500,000, describing
  itself as an ARBITRARY STOPGAP, and warned in its own text that a second stopgap raise "is itself
  a signal that the structural fix is overdue."
- **Decision 160** -- **RETIRED that byte ceiling entirely** rather than raise it again, on the
  grounds that the ceiling existed to size one specific consumer behaviour (a whole-file read) and
  that once the consumer was rebuilt to read boundedly, the ceiling had no referent. This is the
  repository's own worked example of a size ceiling being judged WRONG-SHAPED rather than
  wrong-valued. Weigh it against Q1 and Q2 directly.
- **Decision 147** -- Decision 114's reversal trigger FIRED (the roadmap reached 9,996 of 10,000
  lines). The response was Path A, compact in place, explicitly rejecting Path C (per-tier split,
  as the N-files-to-reassemble anti-pattern) and Path D (a bare ceiling raise, as the Decision 128
  silent-trade anti-pattern). Read the full path set; it is the closest precedent for what an
  expanded rule would have to offer each class.
- **Decision 146** -- archival policy for the decision corpus.
- **Decision 149** -- number-preserving compact-to-stub lifecycle, with a stub grammar.
- **Decision 150** -- decision-log growth direction: a significance bar governing what may be
  created at all, rather than a ceiling on what exists. A different governance shape from a
  ratchet; assess whether any in-scope class wants it.
- **Decision 135** -- replaced the `--pre` edited-set tier gate with live, cacheless, strictly
  additive affected-set selection. This determines the CI wall-time cost of any new `--pre` check
  and is directly relevant to VD4 and Q3.
- **Decisions 159, 161, 162** -- three ratchets that landed AFTER the ones named earlier in this
  map: the coverage baseline, the mypy error-count baseline, and the composite-action shell-body
  baseline. Together with SLOC and prose that makes five live ratchets sharing one shape, which is
  the population Q4 asks you to judge.

### Observed population facts -- re-derive every one

Composition measured the following, applying the pinned CENSUS RULE over `git ls-files`. Treat each
as a claim to verify, not as input. Where a number below is qualified with "about", the exact value
is expected to move slightly with tree state; the counts are expected to reproduce exactly.

- 86 files that are neither `.py` nor `.md` exceed 500 effective lines.
- Of those, 48 are under `docs/plans/` and 22 under `audits/` -- roughly 81 percent of the affected
  population is workflow output. This is the single most consequential number in this map; DD-D
  exists because of it.
- The two largest oversized files OUTSIDE `workflow_outputs` are `docs/ROADMAP-PRODUCT.yaml`
  (about 4,707 effective lines, class `roadmaps`) and `docs/decisions-index.json` (about 2,245,
  class `generated`). They are named here because they are where the `roadmaps` and `generated`
  verdicts actually get decided -- `ROADMAP-PLATFORM.yaml` carries a do-not-flag carve-out and
  `ROADMAP-PRODUCT.yaml` does not, and the provenance key stands or falls on files like the second.
- 5 `.tf` files exceed 500, the largest being `terraform/iceberg_tables.tf`.
- 3 files under `config/` exceed 500, the largest being
  `config/agent/verification_registry/registry.yaml`.
- 2 files under `.github/workflows/` exceed 500.
- 2 files under `docs/contracts/` exceed 500.
- No `.sh` file exceeds 500; the largest measures about 106 effective lines (13 files tracked).
- Median bytes per effective line, with 10th and 90th percentiles, over ALL tracked files of each
  extension. Percentile method, stated so you can reproduce it exactly: sort the per-file ratios
  ascending and take the value at nearest-rank index `floor(q*(n-1)+0.5)`. Median is the middle
  value for odd n and the MEAN OF THE TWO MIDDLE VALUES for even n. Files with zero effective
  lines are dropped from the ratio set (the ratio is undefined); this rule applies to every
  ranking in this prompt, including the DD-A outlier selection.
  Python 53.6 (44.3 to 64.3, n=823); `.yaml` 72.4 (55.4 to 113.9, n=422); `.yml` 66.0 (46.5 to
  98.5, n=27); Terraform `.tf` 60.8 (35.8 to 125.6, n=33); shell `.sh` 92.2 (46.4 to 130.5, n=13);
  markdown 105.3 (69.9 to 241.1, n=314). Weigh the within-class spread against the between-class
  spread before concluding anything about unit substitutability. These were measured at a
  specific tree; your base sha may differ by a few files, which is expected and is not a stale
  anchor -- re-derive and use YOUR numbers. Note that the small-n
  classes (`.sh` at 13, `.yml` and `.tf` at 27 and 33) carry wide percentile uncertainty, so do not
  over-read their tails.
- `docs/plans/reports/OVERSEER-terraform-deploy-redesign.yaml` measures 326 effective lines,
  255,039 bytes, longest line 8,211 characters. It falls under `workflow_outputs` (row 9; `docs/plans/**/*.yaml`
  matches it recursively), so it is a workflow output -- which means the most extreme
  unit-divergence case in the repository sits in the class DD-D may conclude should be exempt.
  Reconcile those two conclusions explicitly rather than letting them pass in separate sections.
- `config/sloc_budgets.yaml` currently holds far fewer entries than the 24 its header comment
  describes -- composition counted 3 entries, 1 of them under `tests/`. Count both and compare. The
  drain was performed by the decomposition program the header names; the header text was not
  updated alongside it. Handed over as evidence for Q4: the ratchet-plus-decompose pattern
  demonstrably drained a 24-file grandfather roster.

## EMPIRICAL PASS

Bounded sampling. Do NOT exceed these caps.

1. **Class population census** -- measure every tracked file once. This is a full pass but a cheap
   one; it is the factual basis for Q1 and Q6.
2. **At most 12 oversized files**, chosen to span classes, read closely enough to judge whether a
   lower-tier model editing them would struggle, and whether a relief valve exists. Tag findings
   from this pass `evidence_kind: observed`.
3. **At most 8 unit-divergence outliers, split across BOTH directions.** DD-A needs files where a
   line gate and a byte gate disagree, and disagreement runs both ways, so take up to 5 from the
   high side and up to 3 from the low side:
   - HIGH side (byte-heavy; passes a line gate while carrying large load): ratio >= 2x the class
     median -- the median of the CLASS (the row-N slug population from your own census), not of the
     file extension; the per-extension figures in the GROUNDING MAP are for comparison only. Rank
     descending by ratio; break ties by total bytes, largest first. Take up to 5.
   - LOW side (line-heavy; would fail a line gate while carrying little load per line): ratio
     <= 0.5x the class median. Rank ascending by ratio; break ties by effective lines, largest
     first. Take up to 3.
   If a side has no qualifiers, take fewer and say so -- do not backfill from the other side. If a
   side has more qualifiers than its cap, the ranking decides; do not exceed the cap. Feeds DD-A.
4. **At most 6 workflow-output files**, plus the workflow definitions that produce and consume
   them, to settle DD-D.
   A file may qualify for more than one pass; it counts against each pass's cap independently, and
   you read it once. The caps bound effort per pass, not the number of distinct files.
5. **At most 10 commits** touching any budget registry, IF and ONLY IF the clone is not shallow.
   If it is shallow, skip this entirely and mark every history-dependent claim HYPOTHESIS.

**`evidence_kind`, defined once for all five passes.** `observed` = the finding rests on a
specific artifact you opened and measured during the empirical pass (a named file, a named commit,
a named workflow definition). `static` = the finding rests on reading a gate, a config, or a
Decision and reasoning about what it would do. Passes 1, 2, 3 and 4 yield `observed` (pass 1 is a
measurement of real files, not a reading of a gate); pass 5 yields `observed` only when the clone
is not shallow; reading the GROUNDING MAP or the check modules yields `static`. When a finding rests on both, tag it `observed`.

Counterfactual test, applied to every proposed gate: **would this gate still fire if the file's
content were reformatted to satisfy it without any reduction in what an agent must comprehend?**
If yes, the gate is measuring load. If no, it is measuring formatting, and that is a VD3 finding.

Observed findings outrank static ones at equal severity. Operationally: when ordering
`summary.top_improvements` and when choosing `summary.highest_leverage_change`, an
`evidence_kind: observed` finding is ranked above an `evidence_kind: static` finding of the same
severity. This affects ordering only; it never changes a severity or a confidence.

## METHOD

- **P1 Read.** The five size-measuring gates named in DD-B, all four raise-guards, the registry
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

**Roadmap dedup -- a schema gotcha that will cost you if you repeat it.** `docs/ROADMAP-PLATFORM.yaml`
keys its `tier_items[]` on `name` and `intent`, NOT on `title`/`detail`. A projection that greps
`title` returns nothing and looks like a clean negative search. Grep `name` and `intent`.

Two roadmap surfaces DO own adjacent territory and are handed over so you do not have to find them:

- **T3.14** (`status: deferred_post_mvp`) -- "Context-budget as a tracked metric (extend Decision 43
  from per-file caps to repo-wide reachable SLOC)". It ships MEASUREMENT, not enforcement, and
  explicitly leaves to a ratifying decision whether any threshold becomes a hard gate. This is the
  repository's only precedent for an AGGREGATE rather than per-file budget, which is exactly what Q8
  seed 3 asks about. Any finding about repo-wide or directory-level budgets is
  `planned-unbuilt` or `planned-insufficient` against T3.14, not `novel`. Read it before answering
  Q8 seed 3.
- **KG.11** (`status: resolved`, `resolution_ref: Decision 114`) -- "YAML file-size split policy".
  This is the prior adjudication of split-an-oversized-YAML versus raise-the-ceiling, decided in
  favour of raising. It is the closest existing precedent to a YAML size rule; treat a
  YAML-splitting recommendation as re-opening it, and say so explicitly if you do.

No OTHER tier_item appears to own the per-file expansion itself -- verify that with a `name`/`intent`
grep rather than trusting it. These open recommendations sit nearby and are likely dedup hits for
narrow findings: rec-2414, rec-2435, rec-2596, rec-2693, rec-2711, rec-2712, rec-2713, rec-2773,
rec-2896, rec-431. CD.29 and CD.30 are adjacent candidate decisions.

### Deliberate constraints -- DO NOT FLAG

Each of these is a decided position, not an oversight. Flagging one as a defect is a false
positive.

- **Decision 114, with Decision 147 answering its reversal trigger** (147 RESPONDS to 114; it does
  not amend it -- this repository annotates real amendments with an explicit "amends Decision NNN"
  in the header, and 147 carries none) -- the single-file-preserved treatment of
  `ROADMAP-PLATFORM.yaml` is FIXED: do not recommend splitting it. See the GROUNDING MAP entry for
  the state (the trigger fired; compaction answered it) -- "the ceiling has never been tested"
  would be false. What is fixed is the one-coherent-file outcome, not an untouchable number. You
  MUST state the principled boundary that lets this file stand while other files in its class are
  capped, so the rule reads as coherent rather than arbitrary. The requester's position, which you
  should record and may build on: this file is an exception granted to how the roadmap currently
  exists, and explicitly NOT a precedent for how future roadmaps are built.
- **Decision 130 clause 2** -- the one-time `tests/` grandfather was deliberate and bounded.
- **Decision 128 clause 3** -- raise markers are not required to persist after merge.
- **Decision 127** -- the prose taxonomy.
- **Decision 84** -- warehouse and portal invariants.
- **Decision 67** -- the executor is frozen. Do not propose executor-consumed work.
- **Decisions 60 and 73** -- the two-tier presubmit structure.
- **Model-agnostic design against a fixed floor** (NS-A). The requester has decided that
  consuming-model tier must NOT be a variable in the rule. Do not flag the absence of tier-aware
  governance as a gap, and do not recommend introducing it. You MAY note in Q8 what this costs.
- The stale header comment in `config/sloc_budgets.yaml` (it describes 24 `tests/` entries; far
  fewer remain). Known and trivial -- use it as Q4 evidence, do not file it as a finding.
- Commits from this harness land unsigned. Expected, not a defect.

## OUTPUT

Write exactly two files.

`audits/size-governance-expansion-<sha>.yaml`:

```
audit:
  # meta flag readers, so none of these is write-only:
  #   degraded_dedup     -> read by the human triaging findings: true means every
  #                         roadmap_crossref is HYPOTHESIS and dedup must be redone before
  #                         any finding is queued as work.
  #   stale_anchors      -> read by whoever re-runs or extends this audit: each entry is a
  #                         GROUNDING MAP anchor that must be re-derived before reuse.
  #   contract_notes     -> read by the human disposing of the PR: records every degraded
  #                         path taken, so a caveated result is never mistaken for a clean one.
  #   deliverable_size   -> read by the self-referential check under GUARDRAILS.
  meta: {audited_commit: <base short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         # methodology_version: bumped only if a future audit changes this prompt's method;
         #   read by anyone comparing two runs of this audit. Emit 1.
         # scope_surfaces: the slugs you actually assessed; read as the cross-check that
         #   class_verdicts is complete. Should list all 12.
         methodology_version: 1,
         scope_surfaces: [<the slugs you assessed>],
         degraded_dedup: false,
         # contract_notes: a single string. If several degraded paths fire, concatenate them
         # separated by "; " -- it records EVERY degraded path taken, not just the last.
         contract_notes: "",
         # stale_anchors: list of objects, never bare strings.
         stale_anchors: [{anchor: "file:line as this prompt cited it", expected: "", found: ""}],
         # md_words: measured by `wc -w` on the committed .md, so it is checkable against the cap.
         deliverable_size: {yaml_effective_lines: 0, md_words: 0,
                            breaches_own_recommendation: true|false, note: ""}}
  question_answers:
    # Roll-up rule for Q1/Q5/Q6 is pinned under THE QUESTIONS; do not restate it here.
    # `basis` accepts finding ids AND direct evidence citations ("file:line", a rec id, a Decision
    # id, a census number) -- a well-grounded verdict resting on a Decision rather than on a defect
    # must still be citable, and an empty findings[] is a legitimate outcome.
    - {q: Q1, verdict: extend-uniform|extend-calibrated|exempt-with-reason|defer|mixed,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: keep-effective-lines|unify-on-bytes|per-class-unit|tokens|composite,
       basis: [], prose: ""}
    - {q: Q3, verdict: generalize-engine|replicate-per-domain|hybrid, basis: [], prose: ""}
    - {q: Q4, verdict: sound-reusable|sound-needs-generalization|unsound-in-this-direction,
       basis: [], prose: ""}
    - {q: Q5, verdict: transfers-fully|transfers-comprehension-only|needs-distinct-rationale|
                       does-not-transfer|mixed,
       basis: [], prose: ""}
    - {q: Q6, verdict: one-time-grandfather|class-exemption|staged-waves|reject|mixed,
       basis: [], prose: ""}
    - {q: Q7, verdict: ahead-justified|ahead-unjustified|at-parity|behind, basis: [], prose: "",
       # evidence here is a two-part string using " || " as the separator (double pipe, to avoid
       # colliding with the single-pipe alternation used in other schema fields):
       #   "<repo side: file:line or mechanism> || <external side: tool or source name>"
       # suffix the external side with "(model knowledge, unverified)" when not live-verified
       external_checklist: [{property: "", rating: met|partial|missed, evidence: ""}]}
    # Q8 basis: finding ids where the answer produced one, otherwise evidence citations
    # ("file:line", a rec id, or a Decision id). Mixing the two in one list is fine.
    - {q: Q8, answers: [{question: "", answer: "", basis: []}]}
  # One entry per SCOPE-table slug, rows 1-12, including `residual`. None may be omitted.
  # Key is the pinned slug verbatim (generated, terraform, config, contracts, ci_workflows,
  # shell, lambda_manifests, roadmaps, workflow_outputs, test_fixtures, data_query,
  # residual).
  # `confidence` here follows the same degraded-run rule as findings: if meta.degraded_dedup is
  # true, every class verdict is HYPOTHESIS. This matters more than the findings case, because
  # draft_decision is built from these verdicts.
  # `unit` is a CONCRETE MEASURE NAME, never a Q2 verdict label -- one of: effective-lines,
  # raw-lines, bytes, tokens, entries, a named composite like "effective-lines+max-line-length",
  # or the literal n/a for an exempt-with-reason or defer class (which has no unit yet).
  # `limit` is an integer for extend-uniform / extend-calibrated, and the literal n/a for
  # exempt-with-reason and for defer (a deferred class has no limit yet, by definition).
  # `population_over_limit` is ALWAYS counted in effective lines under the pinned CENSUS RULE,
  # even when your recommended unit is bytes or tokens, so the number stays comparable across
  # classes; if your unit differs, add the count in that unit parenthetically in `relief_valve`.
  # For an exempt-with-reason or defer class there is no recommended limit: set limit: n/a, count
  # population_over_limit against the incumbent 500-effective-line rule, and say so in
  # `relief_valve` so the number is never read as a breach of a rule you did not propose.
  class_verdicts:
    <slug>: {verdict: extend-uniform|extend-calibrated|exempt-with-reason|defer,  # Q1
                   rationale: {transfer: transfers-fully|transfers-comprehension-only|
                                         needs-distinct-rationale|does-not-transfer,    # Q5
                               actual_purpose: ""},
                   migration: {mode: one-time-grandfather|class-exemption|staged-waves|reject,
                               drain_owner: "", sequencing: ""},                        # Q6
                   unit: "", limit: "", relief_valve: "",
                   population_over_limit: 0, confidence: CONFIRMED|HYPOTHESIS}
  # One entry per class slug.
  per_surface_assessment:
    - {surface: <class>, maturity: strong|solid|nascent, strengths: "", top_gaps: [<finding ids>]}
  # Read by: per_surface_assessment (a weak/absent cell should normally have a corresponding
  # finding, whose id goes in that class's top_gaps -- top_gaps holds FINDING IDS, never rubric
  # cells; a weak cell with no finding behind it means either the finding is missing or the rating
  # is too harsh, so reconcile rather than leaving it dangling) and by the
  # human comparing classes on one dimension. 12 slugs x 8 dimensions = 96 cells; `n/a` is
  # expected to be common and is costless.
  rubric_ratings:
    - {surface: <slug>, dimension: VD1..VD8, rating: strong|adequate|weak|absent|n/a,
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
    # `questions` and `dimensions` are LISTS -- a finding may serve several of each.
    # Put the primary one first; ordering carries no other meaning.
    - {id: SGE-01, surface: <class|shared>, questions: [Q1..Q8], dimensions: [VD1..VD8],
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "",
       severity: critical|high|medium|low, severity_rationale: "",
       confidence: CONFIRMED|HYPOTHESIS,
       # dedup_hit_count is an integer normally, and null only when meta.degraded_dedup is true.
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [], highest_leverage_change: <id>,
            maturity_overall: frontier|strong|solid|nascent}
```

`audits/size-governance-expansion-<sha>.md` -- prose companion, at most 1500 words as measured by
`wc -w`, the executive layer a human reads first. Lead with the seven question verdicts (Q1-Q7;
Q8 carries answers rather than a verdict, so summarize it in a sentence) and the recommended
design, in one paragraph. Then the per-class verdict table. Do not restate the YAML.

### Invariants

- **COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list.
  `total_findings = len(findings) = novel_count + planned_insufficient_count +
  planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates[]`, NOT in
  findings. `rubric_ratings`, `question_answers`, `class_verdicts` and `draft_decision` are
  systems of record referenced FROM findings, never re-counted. `top_improvements` and
  `highest_leverage_change` MUST be finding ids.
- `summary.top_improvements` holds 3 to 5 finding ids (fewer only if `findings[]` is smaller),
  ordered by the observed-over-static rule.
- `summary.highest_leverage_change` is a finding id, or `null` if `findings[]` is empty. An empty
  findings list is a legitimate outcome; do not invent a finding to fill this field.
- Two schema fields exist for the human triaging this audit into work, and have no other consumer:
  `findings[].effort` and `findings[].depends_on`. `findings[].sequencing.blocked_behind` serves
  the same reader. Note that `sequencing.safe_to_queue_now` refers to human-led `/plan` work only
  -- the autonomous executor is frozen (Decision 67), so it never means "queue for the executor".
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal. Name the property the control exercises, cite where it operates, and state why the
  control would FAIL if the defect were real.
- `CONFIRMED` requires the behavior traced to a file:line or to an observed sampled artifact.
  Anything less is `HYPOTHESIS`.
- Every SCOPE-table slug, rows 1-12, must appear in `class_verdicts`, including classes you
  exempt and including `residual`. Twelve entries, keyed by the pinned slug, no omissions.
- `findings[].questions` and `findings[].dimensions` are lists; every value must come from the
  pinned Q1..Q8 and VD1..VD8 sets.
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

Maturity is computed LAST, per class plus one overall, top-down, first match wins.

**Finding attribution -- pinned.** A finding with `surface: <class>` counts against THAT class
only. A finding with `surface: shared` counts against the OVERALL rating only, never against any
individual class. This is deliberate: a shared defect should not mark down ten classes at once.

**Per-class maturity** (uses finding counts only -- `external_checklist` is repo-wide and does not
project onto a single class):

- **strong** -- 0 open critical and 0 open high findings attributed to that class.
- **solid** -- 0 critical and at most 1 high.
- **nascent** -- otherwise.

**Overall maturity** (the only rating with a `frontier` tier, because only it can read the
repo-wide checklist):

- **frontier** -- 0 open critical and 0 open high findings anywhere (all classes plus `shared`),
  AND every property in Q7's `external_checklist` rated `met` or `partial`, never `missed`.
- **strong** -- 0 critical AND at most 1 high, anywhere.
- **solid** -- at most 1 critical AND at most 3 high, anywhere.
- **nascent** -- otherwise.

Both ladders are deliberately sensitive to `high` at every rung: a run with no criticals but many
highs must NOT be able to fall through to a favourable rating. If your overall rating reads better
than most of your per-class ratings, re-check the counts before emitting it.

Write per-class values into `per_surface_assessment[].maturity` and the overall value into
`summary.maturity_overall`.

The top rating remains reachable if you argued a property-matched compensating control. This
framing does not foreclose it.

## COMMIT AND PR MECHANICS

1. Derive the base ONCE: `git fetch origin main`, then `git rev-parse --short origin/main`. That
   sha IS the audited tree. Use it in both filenames, the branch name, and `meta.audited_commit`.
2. `git switch -c audit/size-governance-expansion-<sha> origin/main` so the PR diff contains only
   the two deliverables. This is a deliberate, documented exception to the repository's
   `claude/*` session-branch rule: this session needs a clean two-file diff off the audited base.
   Consequence you should NOT try to compensate for: this repository's two automated wake signals
   (the CI-green comment and the merge-conflict poller) only watch `claude/*` PRs, so an `audit/*`
   PR wakes no one. That is correct and intended here, because step 7 ends your turn and the human
   disposes of the PR. Do not rename the branch, do not add a polling loop, and do not schedule a
   self check-in to compensate.
3. Repository-wide validation is advisory outside CI here. A clean YAML parse of both deliverables
   is the real pre-push gate:
   `bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/size-governance-expansion-<sha>.yaml`.
   An unrelated `validate --pre` failure is recorded in `meta.contract_notes`, never fixed.
4. Commit both deliverables in ONE commit with `user.name=Claude`,
   `user.email=noreply@anthropic.com`, and `--no-gpg-sign` if signing is unavailable. Commit
   message subject, verbatim:
   `audit(size-governance-expansion): structural-size governance expansion assessment`
   Body: one line naming the audited sha. Commits land unsigned in this harness; that is expected
   and is not something to fix -- do not amend or reset-author to chase a signature flag.
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

**The self-referential check -- REQUIRED, not optional.** Your own YAML deliverable lands in
`audits/`, which is the in-scope `workflow_outputs` class (SCOPE row 9). Before you push, measure it under the pinned
CENSUS RULE and fill `meta.deliverable_size`. If it breaches the limit YOUR OWN Q1/Q6 verdicts
would impose on `workflow_outputs`, set `breaches_own_recommendation: true` and address it in the
companion report: either the workflow-output class should be exempt (and your verdict should say
so), or your recommended limit is not survivable by the tooling that must live under it, or the
right answer is to change what these workflows emit. Do NOT resolve this by trimming the audit to
fit, and do NOT split the deliverable across more files to dodge it -- either move is exactly the
evasion your own VD3 dimension exists to catch. A recommendation whose first violation is the
document making it is a finding about the recommendation.

Honesty clauses:

- **Fewer than roughly 8 surviving findings is a valid result. State it plainly. Do not pad.**
- Precision over volume. One traced, CONFIRMED finding is worth more than five plausible ones.
- `n/a` in a rubric cell and an empty `rejected_candidates` list are both legitimate outcomes.
- If a class genuinely should NOT be governed, say so. The requester's instinct is that everything
  non-prose should be covered; an argued exemption that survives your own scrutiny is more useful
  than a rubber-stamped extension.
- If you cannot answer a question with the evidence available, say which evidence was missing
  rather than answering it thinly.
