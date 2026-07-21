# AUDIT: Agent Context Governance (L1-L4 instruction surfaces + JIT primitives)

## TASK

You are auditing the AGENT-CONTEXT-LOADING INFRASTRUCTURE of this public agent-first
repository: the mechanisms -- or their absence -- that govern HOW MUCH agent-facing prose
enters an agent's context window, and WHEN. The repo governs Python growth with per-file SLOC
budgets and a CI-enforced raise gate; it governs its two largest data files (the decision log,
the platform roadmap) with per-consumer size ceilings. The open question this audit adjudicates:
the interactive agent-instruction prose -- always-on and on-invocation -- has no equivalent
growth governance, and the just-in-time loading primitives that exist may or may not be wired to
a live consumer. The repository's stated goal is recursive self-improvement, in which these prose
files are not documentation but load-bearing infrastructure.

Audited surfaces (first-class): S1 the root ambient instruction file, S2 the per-directory
instruction files, S3 the slash commands, S4 the skills, S5 the just-in-time loading primitives,
S6 the size-governance pattern and the instruction-architecture contract, and S7 the
designed-but-unbuilt roadmap end-state. Assess every surface across TWO horizons -- what is
buildable now inside the Anthropic Claude Code harness, and the repo's own AWS-native end-state
(typed Lambda verbs, an agent SDK shim) -- and tag every finding with the horizon it targets.

Answer Q1-Q6 (below). Rate each surface against rubric dimensions VD1-VD7. Produce a per-surface
governance verdict from a pinned option set. Deliverables: exactly two files --
`audits/agent-context-governance-<sha>.yaml` and `audits/agent-context-governance-<sha>.md`. The
ONLY files you create or modify in the repository tree are those two; regenerating gitignored
local caches per SETUP is expected and does not breach this. You draft the assessment; the human
disposes of it. You do not implement anything, file recommendations, or edit any audited surface.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you NO verdicts. Every candidate in
this prompt is a hypothesis to be adjudicated by tracing it to the repository, not a defect to be
confirmed. ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the
candidates below has failed.

Per-candidate adjudication enum, with its mapping to the output contract:

- CONFIRMED-defect (traced to file:line, compensating controls judged insufficient) -> `findings`,
  `roadmap_crossref.classification: novel`.
- PLANNED but the owning roadmap item's remedy is insufficient or unbuilt for THIS surface ->
  `findings`, classification `planned-insufficient` or `planned-unbuilt`.
- PLANNED and fully covered by the owning item -> `rejected_candidates` (name the item).
- NOT-a-defect (a compensating control genuinely covers it) -> `rejected_candidates` (name the
  control and why it property-matches).

Severity is never inherited from this prompt's framing; you assign it after judgment (see SEVERITY
+ MATURITY). A candidate phrased here neutrally ("no size ceiling covers X") is not a claim that a
ceiling SHOULD exist -- that is precisely the judgment you owe.

THE CANDIDATES. This is the delimited candidate set that "a run that merely confirms the candidates
has failed" is measured against. Adjudicate EACH to a verdict (findings / rejected_candidates) per
the enum above; a candidate you dismiss must appear in `rejected_candidates`. This list is not
exhaustive of what you may find -- surface new candidates in your own pass and adjudicate them too.
Every candidate below is absence-shaped by construction ("no ceiling", "no validator", "assigns no
responsibility"); an absence is a FACT, not a defect -- expect several to resolve to a `no_change`
verdict or to `rejected_candidates`, and actively weigh the steelman in Q6(iv) before convicting.

- C1 AGENTS.md loads ambient (~8.3K tok) via the `@AGENTS.md` pointer; no registered size ceiling
  covers `.md` instruction prose (the SLOC/decisions/roadmap ceilings do not). (surface S1)
- C2 `required-context` frontmatter is declared in the skills; the only consumer that parses it is
  `scripts/agent_development/run_skill.py`; establish whether the interactive Skill path reads it.
  (S5, S4)
- C3 Harness hooks perform setup + guarding; none injects context; no `UserPromptSubmit` hook is
  wired. (S5)
- C4 T3.14 ("context-budget metric") is scoped to reachable Python SLOC / import-surface / orphan
  count and does not enumerate agent-prose token cost; `status: deferred_post_mvp`. (S7)
- C5 Decision/CD citations appear inline across the prose surfaces; decision-scout externalises the
  full decision log inside `/plan` only. (S1-S4, S5)
- C6 Per-consumer size ceilings exist for the two largest data files (Decision 134, Decision 114);
  no equivalent per-consumer ceiling covers the L1 ambient or the L3/L4 on-invocation prose
  surfaces -- the precedent is not generalised. (S6, S1-S4)
- C7 Per-directory CLAUDE.md files load ambient on directory touch; the largest is ~7.5K tok; the
  set is unbudgeted. (S2)
- C8 `docs/contracts/instruction-architecture.yaml` mandates the `required-context` declaration and
  lists its absence as an anti-pattern, but no validator enforces its presence;
  `validate_instruction_architecture_layers` checks only that content_locations resolve. (S6, S5)
- C9 `planning` (~14K tok) and `implement` (~12K tok) are the largest L4 surfaces; they carry
  workflow methodology alongside embedded project/decision context. (S4)
- C10 The aws-native end-state (T0.8 SDK shim, CD.10 typed verbs, Decision 91) names typed verbs but
  no JIT-context-retrieval verb and assigns no context-budget accounting responsibility. (S7)

## READ FIRST -- DISAMBIGUATION TRAPS

Recon surfaced terms that name two different things and plausible-but-wrong audit targets. Resolve
each before it misdirects you:

- "CONTEXT BUDGET" names two distinct things. Roadmap item T3.14 ("Context-budget as a tracked
  metric") is about reachable-vs-total Python SLOC, import-surface size, and orphan count -- a CODE
  metric. THIS audit is about PROSE token cost -- how many tokens of instruction files load into an
  agent's window. T3.14 does NOT cover the prose surface; do not treat it as already covering it.
  Adjudicating whether it SHOULD is Q5's job.
- The SLOC governance (per-file caps, the raise gate) is the MODEL this audit asks whether to
  mirror -- it is NOT an audit target. Do not file findings against the SLOC checks themselves;
  they work as designed. Assess whether their PATTERN generalizes to prose.
- "required-context" names a declared YAML frontmatter schema, NOT necessarily a live loader.
  Establish empirically which consumers read it before reasoning about it.
- Two roadmaps exist. `docs/ROADMAP-PLATFORM.yaml` is in scope (platform/governance). `ROADMAP-
  PRODUCT.*` (trading phases) is out of scope.
- "hooks" names two things: Claude Code HARNESS hooks (`.claude/hooks/` wired in
  `.claude/settings.json`) and the git pre-commit hook. The just-in-time-loading question (Q2) is
  about HARNESS hooks.
- "decision-scout" is a scoped offload that runs inside the `/plan` workflow only. It is NOT a
  general just-in-time context loader. Do not treat it as already solving the general case.
- L1 "ambient" is not uniform: the root instruction file is always-on every session; per-directory
  instruction files load only when that directory is touched (conditional-ambient). Different load
  triggers, different cost profiles.
- The root `CLAUDE.md` is a POINTER (its entire content is `@AGENTS.md`), not instruction content.
  The L1 content lives in `AGENTS.md`. A finding proposing to inline content into root `CLAUDE.md`
  breaks a hard invariant (see do-not-flag).

## SCOPE

Every size, path, and anchor in this prompt is a lead. Obtain every file/line/size by reading the
file yourself -- trust no number quoted here; re-derive from the repo and record any non-resolving
anchor in `meta.stale_anchors`.

Audited surfaces, with state:

- S1 AGENTS.md (BUILT) -- root universal-rules file (Layer 1), loaded ambient every session via the
  `@AGENTS.md` pointer in root `CLAUDE.md`.
- S2 Per-directory CLAUDE.md files (BUILT) -- `**/CLAUDE.md` (Layer 1), loaded ambient when their
  directory is touched. In-tree set only; `.venv/` copies are third-party, out of scope. (The
  "loaded when the directory is touched" load-trigger is a Claude Code harness behaviour, not a repo
  artefact -- you can re-derive the file set and sizes from disk, but take the trigger itself as
  stated; if a finding leans on it, record the assumption in `meta.contract_notes`.)
- S3 Slash commands (BUILT) -- `.claude/commands/*.md` (Layer 3), loaded when the user invokes the
  command. Thin orchestration referencing skills.
- S4 Skills (BUILT) -- `.claude/skills/*/SKILL.md` (Layer 4), loaded when the agent invokes the
  Skill tool. Deep methodology.
- S5 JIT primitives (BUILT, partial) -- the `required-context` frontmatter, the decision-scout
  subagent pattern, the harness hooks (`.claude/settings.json` + `.claude/hooks/`), and
  `scripts/agent_development/run_skill.py`.
- S6 Governance pattern + contract (BUILT) -- `docs/contracts/instruction-architecture.yaml`; the
  size-governance checks (`validate_sloc_limits`, `validate_sloc_budget_raises`,
  `validate_decisions_size`, `validate_platform_roadmap`); and the prose-classification checks
  (`validate_prose_allowlist`, `validate_intent_doc_freeze`, `validate_placement`,
  `validate_instruction_architecture_layers`, `validate_prompt_compliance`).
- S7 Roadmap end-state (DESIGNED-UNBUILT) -- the destination described in
  `docs/PROJECT_CONTEXT.md` section 8 and the relevant `docs/ROADMAP-PLATFORM.yaml` tier items:
  T3.14 (context-budget metric, deferred), T0.8 (agent SDK shim), CD.10 / Decision 91 (typed
  Lambda verbs), Decision 86 (no standing prose-architecture docs).

Vocabulary. LAYERS L1-L5 are defined in `docs/contracts/instruction-architecture.yaml`. AMBIENT =
loaded without an explicit invocation. ON-INVOCATION = loaded when a command or skill is called.
JIT (just-in-time) = loaded at the moment of need for the task at hand, then discarded. OFFLOAD =
moving bulky context into a fresh subagent that returns only a structured summary (decision-scout
is the exemplar). HORIZON = `present` (buildable inside the Anthropic harness today) or
`aws-native` (the repo's typed-verb / SDK-shim end-state).

Context-only surfaces (assess as CONSUMED context and as the governance PRECEDENT to reason from,
but do NOT re-audit and do NOT file findings against them): `docs/DECISIONS.md`,
`docs/ROADMAP-PLATFORM.yaml`, `docs/SESSION_LOG.md`. Their existing size ceilings (Decision 134,
Decision 114) and the decision-scout offload are the model Q1/Q3 ask whether to generalize.

Out of scope (one line each): L5 executor role prompts (`config/agent/executor/prompts/`) and the
scheduled-agent prompt surface (`.github/prompts/scheduled/`) -- non-interactive agents, not this
audit; the SLOC CODE-governance itself -- mirror it, do not critique it; `ROADMAP-PRODUCT.*` --
product axis; any trading-strategy content -- confidential and irrelevant.

## SETUP

Work from the audited base: derive it and check it out per COMMIT / PR MECHANICS steps 1-2 BEFORE
reading anything (METHOD P0), so every read and size re-derivation is against the audited tree. Read
every in-scope surface directly. Permitted setup commands:

- `bin/venv-python -m scripts.session.preflight --roadmap-detail full` -- populates
  `logs/.preflight-report.json` and refreshes `logs/.recommendations-log.jsonl`. These caches feed
  DEDUP DISCIPLINE. IF this fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`,
  set every finding's `confidence=HYPOTHESIS` and every `roadmap_crossref.dedup_hit_count=null`
  (`null` is the sentinel for "dedup not run"; the schema default `dedup_hit_count: 0` means a
  negative search WAS run and returned zero), and proceed with static dedup against
  `docs/ROADMAP-PLATFORM.yaml` and `docs/DECISIONS.md` on disk.
- Read-only shell for size re-derivation (`wc -c`, `wc -l`, `grep -c`) is permitted and expected.
- Regenerating gitignored local caches is expected and does not breach the write boundary; never
  commit them.

DEDUP DISCIPLINE (see its own section) is mandatory and depends on these caches. If a cache is
absent and cannot be regenerated, follow the degraded path above rather than skipping dedup.

## NORTH STAR

The bar each surface is judged against. These are principles you argue each surface against, not
absolutes to pattern-match.

- NS-1 THE REPO IS FOR AGENTS. Every artefact is optimised for agent loading efficiency, not human
  readability (`docs/PROJECT_CONTEXT.md`, the Agent-First sections). Judge each surface by what it
  costs an agent to load it, and whether that cost is paid only when the content is needed.
- NS-2 PROSE IS INFRASTRUCTURE. In a repo pursuing recursive self-improvement, instruction files
  are load-bearing infrastructure, not documentation. Infrastructure that can grow without bound
  and without measurement is ungoverned infrastructure. Judge whether the governance applied to
  code and data extends to prose -- and whether it SHOULD, per surface.
- NS-3 RIGHT CONTENT, RIGHT LAYER, RIGHT TIME. The 5-layer model exists to load the minimum
  necessary context at each moment. Judge whether content sits in the layer whose load-trigger
  matches its need, and whether always-on surfaces carry only what every session genuinely needs.
- NS-4 DIRECTED GROWTH, NOT PROHIBITION. The repo's governance stance (Decision 43, Decision 128)
  is decompose-by-default with loud, decision-cited exceptions -- not a ban on growth. Any
  governance you assess or propose is judged against this stance: does it direct growth, or merely
  forbid it?
- NS-5 FRONTIER OVER POINT-FIX. The requester wants an infrastructure-grade answer that accounts
  for the unbuilt end-state (typed verbs, SDK shim), not a patch for today's file sizes. Judge each
  surface's readiness for that end-state, and whether the end-state as designed closes the gap.

## THE QUESTIONS

Each question gets its own first-class answer slot in the output. Per-question verdict enum is
pinned below; default where none is pinned is `sufficient` / `partial` / `insufficient`.

- Q1 -- Should the agent-prose surfaces (S1-S4) carry an enforced SIZE/CONTEXT BUDGET analogous to
  the per-file SLOC caps? If so, per surface: what UNIT (bytes / tokens / lines / reachable-set),
  what GRANULARITY (per-file / per-layer / per-always-on-set), and what MECHANISM (a `validate.py`
  check plus a budget registry with a raise-marker, mirroring `config/sloc_budgets.yaml`; a
  measurement-only metric; or none)? Address the TRANSFER HAZARD explicitly: SLOC caps a REACHABLE
  set, but skills and CLAUDE.md files load WHOLE-file, so a naive per-file byte/token cap can be
  gamed by splitting one surface into sub-files that all load together (false governance, and a
  direct tension with the repo's own decompose-by-default posture) -- state whether the unit and
  granularity you propose per surface is robust to this, or whether a per-load-set budget is
  required. Verdict enum: this question's per-surface answer is the `governance_verdict` decision
  block; the `question_answers` entry for Q1 summarises and points at that block. The prompt pins NO
  gate-vs-advisory prior -- argue each surface.
- Q2 -- Given the Anthropic harness, what is the sound mechanism for JUST-IN-TIME context loading,
  and what belongs ambient vs JIT? Assess the available harness levers concretely: SessionStart
  `additionalContext` injection, a `UserPromptSubmit` hook, PreToolUse context injection, subagent
  offload, and the AWS-native verb layer. Which of these is load-bearing, which is a dead end under
  the harness's constraints, and where does the constraint push the solution to the aws-native
  horizon? Verdict: `sufficient` / `partial` / `insufficient` (of the CURRENT mechanism set).
- Q3 -- Should inline Decision/CD citations be stripped from agent prose and served via a
  decision-scout-style JIT lookup, or is inline citation too LOAD-BEARING to remove? Where is the
  boundary between a citation that must stay inline (an agent cannot act correctly without it) and
  one that can be fetched on demand? Verdict: `sufficient` / `partial` / `insufficient` (of the
  current inline-citation posture).
- Q4 -- Is `required-context` the right JIT foundation, and should it be ENFORCED (presence gated)
  and WIRED into the live interactive path? Establish which consumers read it today. If it is
  read by a non-interactive consumer only, is it a latent primitive to activate, a vestigial one to
  retire, or correctly scoped as-is? Verdict: `sufficient` / `partial` / `insufficient`.
- Q5 -- Does the DESIGNED-UNBUILT end-state adequately provision for prose-as-infrastructure
  context governance, or is there a structural gap needing a new tier item or decision? This
  question rates the design against industry context-engineering practice: assess each property in
  the EXTERNAL CHECKLIST below, property-by-property, in this question's `external_checklist` field.
  Verdict: `sufficient` / `partial` / `insufficient`.
  - EXTERNAL CHECKLIST (assess each `met` / `partial` / `missed`, with evidence):
    (a) context-cost OBSERVABILITY/METERING; (b) BUDGET/QUOTA enforcement; (c) JIT RETRIEVAL vs
    preloading; (d) LAYERED/TIERED context with promotion/demotion rules; (e) EXTERNALIZED/OFFLOADED
    memory (subagent or retrieval); (f) DECOMPOSITION-under-a-cap; (g) REACHABILITY/PROVENANCE
    (detecting context that is loaded but unused); (h) PROGRESSIVE DISCLOSURE / summarization.
    A `partial` requires an argued, property-matched compensating control in its evidence.
- Q6 -- Questions the requester did not think to ask. Seeded candidates you must answer AND extend:
  (i) Does the two-tier presubmit even RUN in the interactive session, or is prose governance only
  felt at PR CI -- and does that timing matter for a self-improving loop? (ii) Is there a
  measurement DATA GAP -- does anything record per-session or per-surface token cost over time, the
  way telemetry records execution outcomes? (iii) If an agent EDITS its own instruction files
  (recursive self-improvement), what stops uncontrolled growth in the same edit that adds a rule?
  (iv) The STEELMAN AGAINST governing prose: could a token/size cap induce terser, less-correct
  methodology, or could decompose-by-default fragment load-bearing context that must be read
  together to be correct? Argue whether that harm is real and where it bounds any remedy you
  propose. (v) Does PROMPT-CACHING change the cost calculus -- is the real per-session cost of
  stably-cached always-on prose (AGENTS.md, per-directory CLAUDE.md) low enough that a raw
  token/byte budget over-weights it, and should any budget or metric be cache-aware? Add any others
  recon in your own pass surfaces.

## RUBRIC

Rate each audited surface (S1-S7) on each dimension. Pinned enum: `strong` / `adequate` / `weak` /
`absent` / `n/a`. `n/a` is correct and costless where a dimension does not structurally apply to a
surface -- never manufacture a rating or a finding to fill a cell.

- VD1 CONTEXT-COST OBSERVABILITY -- is this surface's load cost measured, and trendable over time?
- VD2 GROWTH GOVERNANCE -- is there a structural guardrail against unbounded growth (a budget, a
  decompose-by-default trigger), analogous to SLOC?
- VD3 RIGHT-TIME LOADING -- does the surface load only when its content is needed (ambient
  minimised, JIT/offload used where the content is conditional)?
- VD4 LAYER DISCIPLINE -- does content sit in the layer whose load-trigger matches its need; is
  there cross-layer bleed (project context in L1, project context in L4)?
- VD5 PRIMITIVE LIVENESS -- are declared JIT primitives (e.g. `required-context`) wired to a live
  consumer, or latent/vestigial?
- VD6 OFFLOAD LEVERAGE -- is bulky-but-load-bearing context externalised via subagent/verb rather
  than inlined into the surface?
- VD7 FRONTIER-READINESS -- is the surface positioned for the aws-native end-state, and does the
  end-state as designed close its governance gap?

Every question is served by at least one dimension; every dimension is referenced by at least one
question or deep-dive. Q1<->VD2/VD1; Q2<->VD3/VD4; Q3<->VD6; Q4<->VD5; Q5<->VD7/VD1; Q6 ranges.

## DEEP-DIVES

Threads that need end-to-end tracing beyond a rubric cell.

- DD-A (feeds Q4, VD5): `required-context` liveness. Enumerate every file that DECLARES it (grep
  the skills). Enumerate every consumer that READS it (grep the codebase for the parse). Determine
  whether any INTERACTIVE path (the Skill tool invocation) consumes it, or only a programmatic
  harness. The Skill tool's internal loading is closed harness behaviour; establish it by
  absence-of-consumer reasoning over the repo (which files parse the frontmatter), and if you cannot
  determine it conclusively, record the residual assumption in `meta.contract_notes` rather than
  guessing. State the counterfactual: if the frontmatter were deleted from every skill, what
  interactive behaviour would change? The answer determines whether it is latent, vestigial, or
  live.
- DD-B (feeds Q3, VD6): decision-citation load-bearingness. Sample the highest-citation surfaces.
  For a representative set of inline Decision/CD citations, classify each: (1) ACTIONABLE-inline (an
  agent would act incorrectly without the cited rule present in-context), vs (2) PROVENANCE-only (a
  traceability pointer an agent could fetch on demand). Estimate the split. This is the evidence for
  whether offload is safe or lossy, and where the boundary sits.
- DD-C (feeds Q2, Q5, VD3, VD7): the JIT mechanism trace. For each harness lever named in Q2,
  establish from the repo and the instruction-architecture contract whether it is USED, UNUSED, or
  STRUCTURALLY UNAVAILABLE. Then trace the aws-native end-state: does any tier item or decision
  assign a JIT-context-retrieval responsibility to the typed-verb layer or the SDK shim, or is
  context-loading absent from the end-state's verb surface? This is the core of the frontier answer.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Every fact was observed on disk at compose
time; re-derive each before relying on it, and record any that no longer resolves in
`meta.stale_anchors`. Facts are stated neutrally and carry no verdict.

Sizes (bytes / lines, approximate; re-derive with `wc`):
- `AGENTS.md` -- ~33,176 b / 311 L. Root `CLAUDE.md` -- 11 b, content `@AGENTS.md`.
- Per-directory CLAUDE.md (in-tree): `terraform/` ~29,851 b / 339 L; `tests/` ~8,696 b;
  `terraform/github/` ~5,266 b; `terraform/bootstrap/` ~5,151 b; `src/data/handlers/` ~4,307 b;
  `docs/` ~3,813 b; `scripts/` ~2,984 b; `config/` ~1,820 b; `src/lambdas/` ~1,249 b.
- Skills (`.claude/skills/*/SKILL.md`): `planning` ~55,812 b; `implement` ~47,677 b; `audit-prompt`
  ~25,846 b; `orient` ~23,676 b; `plan-critique` ~17,156 b; `overseer` ~12,814 b; `code-review`
  ~12,677 b; `decision-scout` ~8,230 b; `executor-rca` ~1,965 b. (~4 chars/token is a usable rough
  conversion; re-derive if you need precision.)
- Slash commands (`.claude/commands/*.md`): 6 files, ~37,790 b total.
- Context-only: `docs/DECISIONS.md` ~398,438 b, 103 live `## Decision` headers;
  `docs/ROADMAP-PLATFORM.yaml` ~745,247 b / 9,598 L; `docs/SESSION_LOG.md` ~68,031 b.

Governance mechanisms (read each to confirm what it enforces):
- `config/sloc_budgets.yaml` -- per-file Python SLOC budgets; raises require an inline
  `# raise-approved: dec-NNN <reason>` marker. Enforced by
  `scripts/checks/sloc/sloc_limits.py` + `scripts/checks/sloc/validate_sloc_budget_raises.py`.
- `scripts/checks/decisions/validate_decisions_size.py` -- byte + `## Decision` header + combined
  ceilings on `docs/DECISIONS.md` (`_DECISIONS_LIVE_MAX_BYTES=400_000`, `_DECISIONS_LIVE_MAX_H2=120`,
  `_DECISIONS_COMBINED_MAX_BYTES=700_000`), sized explicitly to the decision-scout subagent's
  whole-file read (Decision 134).
- `scripts/checks/roadmap/validate_platform_roadmap.py` -- `_ROADMAP_MAX_LINES=10_000` line ceiling
  (Decision 114).
- `scripts/checks/registry.py` -- tier ordering. `validate_decisions_size` runs in BOTH `--pre`
  (~line 100) and full (~line 172); `validate_sloc_limits` both; `validate_platform_roadmap` full;
  `validate_prose_allowlist` / `validate_intent_doc_freeze` both;
  `validate_instruction_architecture_layers` / `validate_prompt_compliance` full.
- `scripts/checks/contracts/validate_instruction_architecture_layers.py` -- checks only that each
  layer's `content_locations` resolve to at least one file (via `check_layer_compliance` in
  `scripts/prompt_compliance.py`). No size logic, no `required-context` presence check.
- `scripts/checks/contracts/validate_claude_md_pointer_invariant.py` -- root `CLAUDE.md` must equal
  exactly `@AGENTS.md\n`.
- `scripts/checks/hygiene/validate_prose_allowlist.py` -- every tracked `.md` must classify as a
  sanctioned prose class in `docs/contracts/file-router.yaml` (existence/classification; not size).

JIT primitives:
- `required-context` frontmatter -- declared in the skills (grep `.claude/skills/*/SKILL.md`).
  Parsed by `scripts/agent_development/run_skill.py` (`parse_required_context`, ~line 16; used ~line
  84) -- a programmatic fresh-context LLM harness for critiques/evals. Establish independently
  whether any other consumer reads it.
- `docs/contracts/instruction-architecture.yaml` -- line ~61 states skills "must declare
  required-context frontmatter"; lines ~100-102 list "Missing required-context in SKILL.md" as an
  anti-pattern. Confirm whether any validator enforces this presence.
- `.claude/settings.json` -- hooks block: `SessionStart` (4 setup hooks: aws, github-mcp,
  sync-deps, precommit) and `PreToolUse` (3 guards: `never_on_main.py`, `edit_scope_guard.py`,
  `scheduled_agent_log_only.py`). No `UserPromptSubmit` entry present at compose time. Confirm.
- `.claude/skills/decision-scout/SKILL.md` -- the offload exemplar: reads the whole
  `docs/DECISIONS.md` inside a fresh subagent every `/plan`, returns a structured summary, keeping
  the file out of the parent planning agent's context.

Roadmap / end-state (context-only, for Q5/DD-C):
- `docs/ROADMAP-PLATFORM.yaml` T3.14 (grep `id: T3.14`) -- "Context-budget as a tracked metric";
  scoped to reachable/total Python SLOC, import-surface, orphan count; `status:
  deferred_post_mvp`; `scripts/context_budget.py` does not exist. T3.13 / T3.12 are its code-graph
  dependencies (dead-code detection, dependency graph).
- `docs/PROJECT_CONTEXT.md` section 8 ("Agent / instruction architecture end-state") and section 2
  (typed Lambda verbs, agent SDK shim T0.8, CD.10, Decision 91). Decision 86 forbids new standing
  prose-architecture docs.

Coupling counts (re-derive with exactly `grep -oE 'Decision [0-9]+|CD\.[0-9]+'`; a broader pattern
that also counts tier ids `T[0-9]+\.[0-9]+` or the bare word "decision" yields higher numbers --
use the pinned pattern): `AGENTS.md` ~50 refs / ~28 unique; `implement` ~39; `planning` ~40;
`orient` ~26; `plan-critique` ~22; `overseer` ~11; `decision-scout` ~5; `code-review` ~2;
`audit-prompt` ~0.

Load-cost note (neutral, for Q1/Q5/VD1): raw file size is not identical to marginal per-session
token cost. Always-on ambient prose (S1, S2) is subject to the harness's prompt-caching -- a
stably-unchanged ambient file's marginal cost across a session is lower than its byte count implies,
while a file that changes every session is not cached across sessions. Whether this changes the cost
model a budget or metric should use is a judgment you owe (Q1, Q6), not a settled fact; do not assume
raw bytes are the cost, and do not assume caching makes size free.

## EMPIRICAL PASS

Bounded, and observed findings outrank static ones at equal severity. Tag every finding's
`evidence_kind` as `static` or `observed`.

- Re-derive the full size table above (deterministic; `wc`). This is `observed` grounding for VD1
  and Q1.
- Inspect the TWO largest skills only (`planning`, `implement`) for cross-layer bleed (VD4, DD
  context): sample their section headers and look for content that the instruction-architecture
  contract assigns to Layer 2 (project knowledge) or Layer 1 (universal rules) rather than Layer 4
  (methodology). Do NOT exceed these two for deep bleed-inspection; a header-level scan of the
  others is enough to rate VD4.
- For DD-B, sample AT MOST 20 inline Decision/CD citations across the highest-citation surfaces --
  do NOT exceed 20. Classify each actionable-inline vs provenance-only. Report the split as
  `observed` evidence; extrapolating a repo-wide ratio from the sample is a HYPOTHESIS, mark it so.
- Telemetry token-cost sampling: IF `logs/.preflight-report.json` or a reachable telemetry read
  surfaces per-session token cost, you may cite up to 5 recent data points as `observed`. If no
  such data is reachable (the likely case), that absence is itself evidence for Q6(ii) -- record it,
  do not manufacture numbers.

Counterfactual test, applied per candidate: "Would this candidate still be a problem if the
surface's content were half its size / loaded lazily / cited by pointer?" A candidate that
dissolves under the counterfactual is weaker than one that survives it.

## METHOD

- P0 BASE. Derive the audited base sha and check out the audit branch off `origin/main` (MECHANICS
  steps 1-2) BEFORE any read, so every read and every size re-derivation in P1 is against the tree
  recorded in `meta.audited_commit`.
- P1 READ. Read every S1-S6 surface and the S7 end-state anchors. Re-derive the size table.
- P2 TRACE. Adjudicate each candidate to a verdict by tracing it to file:line. Run DD-A, DD-B, DD-C.
- P3 EMPIRICAL. Execute the bounded EMPIRICAL PASS.
- P4 RATE. Fill the rubric (S x VD). Assign `n/a` where a dimension does not structurally apply.
- P5 DECIDE. Produce the per-surface `governance_verdict` for Q1.
- P6 DEDUP. For every surviving finding, run DEDUP DISCIPLINE before it is filed.
- P7 SYNTHESISE. Answer Q1-Q6. Compute severity, then maturity, LAST.

Synthesis and maturity computation always come last.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding:

- `docs/ROADMAP-PLATFORM.yaml` (tier items -- especially T3.12/T3.13/T3.14, T0.8, and any
  instruction-architecture item), `docs/DECISIONS.md` (`## Decision` headers -- especially 43, 86,
  102, 114, 128, 130, 134), and `logs/.recommendations-log.jsonl` (open recs).
- Record `roadmap_crossref.dedup_search_terms` and `dedup_hit_count` on every finding. A hit means
  the finding is a sufficiency-assessment of the owning item (`planned-insufficient` /
  `planned-unbuilt`) or belongs in `rejected_candidates` -- NOT a fresh `novel` discovery. A finding
  filed without a recorded negative search is a HYPOTHESIS; mark its `confidence` accordingly.
- If `meta.degraded_dedup=true`, dedup against the on-disk roadmap/decisions only and set every
  `roadmap_crossref.dedup_hit_count=null` and every finding's `confidence=HYPOTHESIS`.

DELIBERATE CONSTRAINTS -- DO NOT FLAG (each with its decision id):

- The autonomous executor is FROZEN and STRATEGIC plans are suspended (Decision 67). Do not propose
  a mechanism that depends on the executor as consumer, nor a STRATEGIC-plan-typed remedy.
- No new standing prose-architecture docs (Decision 86). Any governance you propose must be
  machine-parseable and collocated with its enforcement -- never a new narrative doc.
- The root `CLAUDE.md` pointer invariant is load-bearing. Do not propose inlining content into it.
- The `send_later` / trigger tools are harness-gated and cannot be fixed via the settings allowlist
  (see AGENTS.md). Do not propose allowlisting them.
- T3.14's `deferred_post_mvp` status is a valid MVP-triage decision (Decision 93). Do not flag the
  deferral itself as a defect; assess whether its SCOPE (code-only) covers prose.
- The SLOC 500-cap decompose-by-default posture (Decision 128) is the MODEL to mirror. Do not
  critique it.
- Auto-memory is disabled by policy; CLAUDE.md is canonical persistence. Do not propose the
  auto-memory system as a JIT store.
- `validate.py` is the single source of truth for CI gates; a new check must be added there, not
  CI-YAML-only. Any enforcement proposal must respect this.

## OUTPUT

Write exactly two files. `audits/agent-context-governance-<sha>.yaml` (the structured audit) and
`audits/agent-context-governance-<sha>.md` (a prose companion, <= ~1500 words, the executive layer
a human reads first). `<sha>` is the audited base short sha (see MECHANICS). The YAML conforms to:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>, methodology_version: 1,
         scope_surfaces: [S1,S2,S3,S4,S5,S6,S7], degraded_dedup: false,
         contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: see-governance_verdict, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q3, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       external_checklist: [{property: a|b|c|d|e|f|g|h, rating: met|partial|missed, evidence: ""}]}
    - {q: Q6, answers: [{question, answer, basis: [<finding ids>]}]}
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
    # one per surface S1-S7
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
    # one row per (surface x dimension) you rate; n/a rows may be omitted or listed explicitly
  governance_verdict:
    # Q1's per-surface actionable verdict. One entry per prose surface S1-S4 (S5-S7 optional).
    # Each surface carries a per-horizon sub-verdict, because a surface's sound answer can differ by
    # horizon (e.g. present: measure_only_metric; aws-native: token_budget_gate). Set a horizon's
    # verdict to no_change if that horizon needs nothing; if the answer is identical across horizons,
    # state the same verdict in both.
    S1:
      present:    {verdict: token_budget_gate|measure_only_metric|jit_offload|layer_relocate|decompose|no_change,
                   mechanism: "", what_changes: "", cost: "", backing_finding: <finding id|null>}
      aws_native: {verdict: token_budget_gate|measure_only_metric|jit_offload|layer_relocate|decompose|no_change,
                   mechanism: "", what_changes: "", cost: "", backing_finding: <finding id|null>}
      unit: ""
      granularity: ""
      rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
  findings:
    - {id: ACG-01, surface: S1..S7|shared, question: Q1..Q6, dimension: VD1..VD7,
       horizon: present|aws-native, title, evidence: "file:line|item-id",
       evidence_kind: static|observed, current_behavior, ideal_behavior, gap,
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt, item_ids: [],
                          dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [ids], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match, decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>,
            maturity_S1: <v>, maturity_S2: <v>, maturity_S3: <v>, maturity_S4: <v>,
            maturity_S5: <v>, maturity_S6: <v>, maturity_S7: <v>}
```

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered candidates live in
`rejected_candidates`, NOT `findings`. `rubric_ratings`, `question_answers`, and `governance_verdict`
are systems-of-record referenced FROM findings, never re-counted. `top_improvements` and
`highest_leverage_change` MUST be finding ids; if `findings` is empty, set `top_improvements: []`
and `highest_leverage_change: null`. Each per-horizon sub-verdict (`present` / `aws_native`) whose
`verdict` is anything other than `no_change` MUST name a `backing_finding` id -- the finding
documenting the gap it acts on; a `no_change` sub-verdict sets `backing_finding: null`.
`per_surface_assessment[].maturity` is the system-of-record for each surface's maturity;
`summary.maturity_<surface>` MUST equal it. A finding's `question` and `dimension` are
single-valued: tag the PRIMARY one it serves and reference any others in the finding's prose
(`gap` / `proposed_change`); a finding whose primary owner is the open-ended question tags
`question: Q6`.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why it would FAIL if the
defect were real. CONFIRMED requires the behaviour traced to file:line or an observed artifact;
anything less is HYPOTHESIS.

## SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherited from this prompt's framing. A
compensating control lowers severity only if it PROPERTY-MATCHES: it exercises the same property AND
would fail if the defect were real (apply the counterfactual to the control). A control that cannot
catch the break neither lowers severity nor justifies dismissal.

- critical = an agent routinely loads so much wrong-layer or unbudgeted context that a correctness-
  or cost-bearing failure is the expected outcome, with no guardrail in the path.
- high = a governance gap that materially degrades the agent-loading guarantee AND whose
  compensating controls you judge insufficient.
- medium = redundancy / ambiguity / cross-layer bleed with a clear fix.
- low = clarity / wording.

MATURITY -- compute LAST, per surface, top-down, first match wins. A finding counts toward a
surface's maturity if its `surface` IS that surface, OR it is tagged `surface: shared` and its
`evidence` materially implicates that surface (a `shared` finding implicating all prose surfaces
S1-S4 counts toward each of them). Pin these thresholds:
- frontier = 0 critical AND 0 high findings for the surface AND -- for S7 only, the surface Q5 rates
  via its EXTERNAL CHECKLIST -- every checklist property `met` or `partial`, never `missed`. For
  S1-S6, which the checklist does not rate, the top tier gates on finding counts alone.
- strong = 0 critical AND <= 1 high.
- solid = <= 1 critical.
- nascent = otherwise.

The top rating remains reachable if you argued a property-matched compensating control -- the
framing here must not foreclose it.

## COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This sha
   IS the audited tree; use it in both deliverable filenames, the branch name, and
   `meta.audited_commit`. IF `git fetch` fails (offline / egress down): do NOT abort and do NOT fall
   back to the session-branch `HEAD` -- use the existing local `origin/main` ref, and record in
   `meta.contract_notes` that the base may be stale relative to the true remote tip.
2. `git switch -c audit/agent-context-governance-<sha> origin/main` so the PR diff is exactly the
   two deliverable files. This is a deliberate, documented exception to the `claude/*` session-branch
   rule -- the audit session needs a clean two-file diff off the audited base; the CI signal-green
   comment fires only on `claude/*` PRs and is irrelevant here because you end your turn without
   merging. If a PreToolUse hook blocks the switch, stay on the current session branch, still write
   the two deliverables against the audited base, and note the deviation in `meta.contract_notes` --
   the clean two-file diff is what matters, not the branch name.
3. Repo-wide `validate --pre` is advisory outside CI. Your real pre-push gate is that both
   deliverables are well-formed (the YAML parses) AND the YAML satisfies the OUTPUT schema's COUNTING
   INVARIANT. Do NOT fix any unrelated `validate` failure -- record it in `meta.contract_notes` and
   move on (write boundary).
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing is
   unavailable. `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title
   `audit: agent context governance (L1-L4 instruction surfaces + JIT primitives)`, body = the
   `summary` block in a yaml fence plus a 2-3 sentence lede). Then END THE TURN -- do not poll, do
   not merge, do not subscribe.

## GUARDRAILS

- Write boundary, restated as a closed list: the ONLY files you create or modify in the tree are
  `audits/agent-context-governance-<sha>.yaml` and `audits/agent-context-governance-<sha>.md`
  (creating the `audits/` directory if it does not yet exist is part of writing them, not a breach).
  Regenerating gitignored caches per SETUP is not a breach; committing them is. Touch no audited
  surface, file no recommendation, edit no roadmap or decision.
- Precision over volume. Fewer than ~6 surviving findings is a valid and honest result -- state it;
  do not pad. A run that merely restates the candidates has failed.
- Every finding tags its `horizon`. A present-horizon finding must be buildable inside the harness
  as described; an aws-native finding must name the tier item or verb it attaches to.
- You are the judge of every candidate. This prompt owes you facts; it owes you no conclusions.
