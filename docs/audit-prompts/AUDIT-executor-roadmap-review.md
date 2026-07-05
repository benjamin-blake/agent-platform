# AUDIT: Autonomous Executor Roadmap Review (T4 design)

You are a frontier-capability model executing a self-contained, read-only design review in a
fresh session. You cannot ask clarifying questions -- everything you need is in this file and in
the repository at HEAD. Execute it exactly as written.

## 1. TASK

Perform a read-only design review of the PLANNED autonomous executor on the platform roadmap --
the designed-unbuilt "T4" architecture: AWS Step Functions orchestration + Lambda Durable
Function agent-personas + deterministic-glue Lambdas, which is intended to pick recommendations
off a priority queue and drive them autonomously through plan -> critique -> implement -> review
-> verify -> merge -> deploy -> observe. The target is the DESIGN as expressed in the roadmap
tier_items and candidate_decisions, NOT any existing executor code (see the traps in section 3).

Answer five questions (Q1..Q5, section 7), rate the design on eight dimensions per surface
(VD1..VD8, section 8), and produce findings for the gaps you confirm. The requester's two
driving questions are: (a) does the roadmap have gaps -- is any capability the closed autonomous
loop needs missing, under-specified, or mis-sequenced; and (b) is the design aiming at a
frontier, industry-leading architecture.

Deliverables: exactly two files -- `audits/executor-roadmap-review-<sha>.yaml` (the structured
audit) and `audits/executor-roadmap-review-<sha>.md` (a <=1500-word companion report a human
reads first). You DRAFT; the human DISPOSES -- you open a PR and stop; you do not merge, and you
file no recommendations or decisions. The ONLY files you create or modify in the repository tree
are those two deliverables. Regenerating gitignored local caches per section 5 is expected and
does not breach this boundary (never commit them).

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you NO verdicts. Every candidate in
the section 10.1 CANDIDATE OBSERVATIONS list is a neutrally-phrased hypothesis you must trace to
the repository and adjudicate -- never a defect you may assume. ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run
that merely confirms the candidates below has failed.

Per-candidate adjudication -- map each to exactly one outcome:
- CONFIRMED defect the roadmap does not own anywhere -> `findings[]`, `roadmap_crossref.classification: novel`.
- A real weakness whose owning tier_item / CD exists but whose remedy is insufficient as
  specified -> `findings[]`, classification `planned-insufficient`.
- A real weakness whose owning item exists but is not yet built AND whose exit criteria, once
  built, would close it -> `findings[]`, classification `planned-unbuilt` (file this ONLY when
  the deferral/sequencing itself is the defect, e.g. a safety control needed at MVP is parked
  post-MVP; do NOT file "item X is not built yet" when the design is sound and merely pending).
- Fully covered by its owning item, or not-a-defect -> `rejected_candidates[]`, naming the
  compensating control or decision that dismisses it.

You are expected to find candidates that are NOT defects. A candidate dismissed with a
property-matched compensating control is a successful adjudication, not a failure. Equally, you
are expected to surface defects NOT in the candidate list -- the candidate set is a floor on
your attention, not a ceiling.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

These hazards will misdirect you if you do not internalise them before reading anything else.

- TRAP-1 (two executors, one name). A BUILT executor exists on disk: `scripts/execute_recommendation.py`
  (~130 KB), the `scripts/executor/*.py` submodules, and `config/agent/executor/prompts/*.prompt.md`.
  This is a single-process, local Python CLI executor and is FROZEN (Decision 67). It is NOT the
  audit target and you must NOT audit it for bugs, code quality, or completeness. The audit target
  is the PLANNED redesign onto a different substrate (Step Functions + Lambda Durable Functions),
  ratified-in-candidate-form by CD.27, which narrowly supersedes the earlier Fargate-executor
  clause. Treat the existing code as context that tells you what concepts carry forward, never as
  the design under review. Auditing `execute_recommendation.py` is the single most likely way to
  waste this session.
- TRAP-2 (CD.NN vs Decision NN). `CD.27`, `CD.17`, `CD.37`, `CD.38`, `CD.10` are
  candidate_decisions inside `docs/ROADMAP-PLATFORM.yaml` (each carries `state: pending`,
  `filed_via: pending_log_decision_lambda`) -- they are the ADOPTED-BUT-NOT-YET-FORMALLY-RATIFIED
  design intent. `Decision 55`, `67`, `87`, `90`, `93` are ratified entries in `docs/DECISIONS.md`.
  When a candidate turns on ratification status, cite which register you read. That CD.27 is still
  `pending` is a stated fact; it is NOT itself a defect to flag (the platform's whole design layer
  lives as candidate_decisions).
- TRAP-3 (two roadmaps). `docs/ROADMAP-PLATFORM.yaml` (tier_items, infra, the T4 executor) is the
  target axis. `docs/ROADMAP-PRODUCT.yaml` (trading phases 1-7) is OUT OF SCOPE. "Phase" is a
  product word; "tier_item" / "T4" is a platform word.
- TRAP-4 (verifier harness is a dependency, not a target). The T3 verifier harness (typed checks,
  graduation registry, causal-chain verifier T3.2) is the SUBSTRATE the executor's verification
  leg (CD.38) delegates to, and T3.2 is a hard gate (G.8) and a stated dependency of T4.1/T4.2.
  Assess only whether the EXECUTOR DESIGN'S RELIANCE on T3 is sound (is the delegation specified,
  sequenced, and correlated correctly). Do NOT audit T3's internal correctness -- that is a
  different surface with its own prior audit (`audits/verification-system-review-*`).
- TRAP-5 (persona vs skill). `decision_scout` is a planned executor PERSONA (T4.2); `decision-scout`
  is an existing interactive `.claude/skills/` methodology. The persona reuses the concept; the
  skill is context, not the design.
- TRAP-6 (deferred is a decision, not a hole). `deferred_post_mvp` (Decision 93) is a conscious
  lifecycle status, not an oversight. You MAY flag a deferred item IF you argue its capability is
  required to reach the MVP boundary (loop closes with no human in the critical path); you may NOT
  flag "item X is deferred" as itself a defect.

## 4. SCOPE

IN SCOPE -- all designed-unbuilt unless noted; obtain every file/line/size by reading the file --
trust no number quoted here; re-derive from the repo and record any non-resolving anchor in
`meta.stale_anchors`:

- The T4 tier_items in `docs/ROADMAP-PLATFORM.yaml`: T4.1 (Step Functions state machine +
  glue-Lambda scaffolding + IAM), T4.2 (agent-persona Durable Functions + LiteLLM transport,
  XL/STRATEGIC), T4.3 (scheduled-agent loop re-enabled), T4.4 (autonomy maturity gates A0-A5),
  T4.5 (plan/critique/revision warehouse entities), T4.6 (autonomous plan->critique->revision loop
  + authority-flip), T4.7 (plan-staleness story), T4.8 (semantic locks + rec leases,
  deferred_post_mvp), T4.9 (executor<->GitHub-Actions handshake contract, deferred_post_mvp),
  T4.10 (durable persona contract registry, deferred_post_mvp), T4.11 (executor loop-budget +
  retry policy, deferred_post_mvp).
- The governing candidate_decisions: CD.27 (substrate), CD.17 (freeze-reversal trigger), CD.37
  (semantic locks), CD.38 (verification delegated to GitHub Actions), CD.10 (agent tooling =
  Lambda-per-verb).
- The ratified decisions the T4 design implements: Decision 55 (RCA-first executor), 67 (freeze),
  87 (plans as warehouse entities), 90 (four-tier workflow), 93 (Platform-MVP boundary +
  deferred_post_mvp).
- The dependency / gate structure that binds them: `cross_tier_gates` (G.8, G.9), the
  `depends_on` edges of T4.*, and `open_questions` / `known_gaps` entries that touch the executor
  (KG.2, KG.3, KG.13).

SHARED VOCABULARY (define once, use throughout):
- "the loop" / "the autonomous loop" = one MVP iteration per Decision 93: rec filed -> implemented
  -> validated -> merged -> deployed -> next observable state, no human in the critical path.
- "persona" = one agent role run as a Lambda Durable Function (plan_agent, plan_critic,
  decision_scout, implement_agent, code_reviewer; plus rca + bookkeeping in T4.10).
- "glue Lambda" = a deterministic (non-LLM) Lambda (pick_rec, prepare_workspace, critique_gate
  aggregator, file_pr, emit_telemetry).
- "the freeze" = the Decision 67 STRATEGIC-plan clause, reversed by CD.17 when its named tier-item
  gates land; it blocks STRATEGIC-plan filing and executor re-enablement, NOT the design work.
- "MVP boundary" = the point at which the loop above closes end-to-end (Decision 93); everything
  consciously placed after it is `deferred_post_mvp`.
- "checkpoint-replay" = Lambda Durable Function semantics: on timeout, the next invocation resumes
  from the last completed tool call without re-issuing completed LLM calls.

OUT OF SCOPE (one line each):
- The existing frozen executor code -- context only (TRAP-1).
- Internal correctness of the T3 verifier harness, the DuckLake/ops data backbone, and the
  Terraform CI/CD apply path -- assess only the executor design's RELIANCE on them.
- The trading product roadmap and any trading alpha/strategy content (TRAP-3).
- Re-litigating ratified decisions 55/67/87/90/93 -- assess whether T4 correctly implements them
  and whether gaps remain around them; do not re-decide them.

## 5. SETUP

Run these read-only setup commands. If any fails, DO NOT abort -- take the named degraded path and
set the named meta flag exactly as the relevant step below specifies, then proceed. Never
improvise or abort.

1. `git fetch origin main && git rev-parse --short origin/main` -> this short sha is `<sha>`: use
   it in both deliverable filenames, the branch name, and `meta.audited_commit`. If `git fetch`
   fails (egress down), use `git rev-parse --short HEAD`, and set `meta.contract_notes` to note
   the base was HEAD not fetched-origin/main.
2. Cache generation for DEDUP DISCIPLINE (section 13):
   `bin/venv-python -m scripts.session_preflight --roadmap-detail full`
   (populates `logs/.preflight-report.json` and refreshes `logs/.recommendations-log.jsonl`).
   IF cache-gen fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`, and on
   EVERY finding set the finding-level `confidence: HYPOTHESIS` and
   `roadmap_crossref.dedup_hit_count: null`, then proceed using the on-disk
   `logs/.recommendations-log.jsonl` as-is (it is a committed read cache).
3. All roadmap/decision reads are plain file reads and need no credentials; they never justify
   aborting.

## 6. NORTH STAR

The bar you judge each surface against. These are principles to argue with, not checkboxes to
match -- for each, decide whether the T4 design meets it and say why.

- NS-A (loop actually closes). The design's telos (Decision 93) is one iteration with NO human in
  the CRITICAL path. A design where a human is structurally reintroduced into the critical path
  (as opposed to the exception/RCA path) does not meet this bar. This is a bar you judge each
  surface against.
- NS-B (contained autonomy). A self-improving system that can plan, edit, and merge its own
  repository must be bounded: it cannot revise indefinitely, cannot exceed budget, cannot
  self-certify its own verification, cannot modify its own machinery, and cannot act on an unsound
  verdict. Judge whether the design's containment is sufficient for the authority it grants.
- NS-C (verification the actor does not control). The thing that says "this change is correct"
  must be independent of the agent that produced the change (Google-TAP-style: CI is the oracle,
  the author is not). Judge whether the executor can ever mark its own work green.
- NS-D (durable and observable). State survives process death (checkpoint-replay, Step Functions
  durable execution); every turn is traced (tokens, cost, latency, tool calls) so regressions and
  cost runaways are visible. Judge whether the design is observable enough to be operated safely.
- NS-E (progressive, reversible autonomy). Autonomy is earned in stages keyed to measured
  success, and every forward step has an automatic rollback when a regression metric breaches
  threshold. Judge whether the escalation-and-rollback story is complete and correctly sequenced.
- NS-F (frontier posture). Measured against how the best autonomous/agentic software-engineering
  systems are built (section 7, Q2 checklist), the design should be at or near the industry
  frontier, with deliberate, argued exceptions rather than silent omissions.

## 7. THE QUESTIONS

Answer each in `question_answers[]`. Q1..Q4 carry a pinned verdict enum; Q5 uses the answers
shape. Each answer's `basis` lists the finding ids that support it (empty is allowed only if the
verdict is the strongest option).

- Q1 -- ROADMAP COMPLETENESS / GAPS. Verdict enum: `complete | partial | insufficient`. Walk the
  loop (rec -> plan -> critique -> implement -> review -> verify -> merge -> deploy -> observe ->
  next). For EACH transition, name the tier_item(s)/CD(s) that own it and judge whether the
  capability is: owned-and-sufficiently-specified, owned-but-under-specified, owned-but-mis-
  sequenced, or absent (no item/CD/KG owns it). `partial` = at least one under-specified or
  mis-sequenced transition; `insufficient` = at least one absent capability on the critical path.
- Q2 -- FRONTIER / INDUSTRY-LEADING. Verdict enum: `frontier | competitive | lagging`. Assess the
  design property-by-property against this EXTERNAL CHECKLIST, recording each in the answer's
  `external_checklist` field as `{property, rating: met|partial|missed, evidence}`. `partial`
  requires you to name an argued, property-matched compensating control in `evidence`. The
  checklist (assess every row):
    1. Durable workflow orchestration with checkpoint-replay (vs fragile single-process runs).
    2. Planner / critic / actor separation with an INDEPENDENT critic (not the actor grading
       itself).
    3. Bounded autonomy: hard caps on plan revisions, implement revisions, review rounds,
       verification attempts, and total LLM calls per unit of work.
    4. Verification the actor cannot control or self-certify (independent CI oracle; hermetic /
       differential / fail-on-revert testing).
    5. Least-privilege sandboxing: per-persona tool allow/deny lists, scoped IAM, and a hard
       self-modification boundary.
    6. Progressive autonomy with human-ratified escalation gates AND automatic rollback keyed to
       measured regression metrics.
    7. Concurrency control for parallel work via semantic/lock conflict avoidance (not file
       overlap alone).
    8. Full-fidelity per-turn observability: tokens in/out, cached-token read/write, est cost,
       latency, model id -- for eval, cost control, and regression detection.
    9. RCA-on-failure with permanent forward-fix (no silent workaround / no automated
       retry-on-bad-LLM-output).
    10. Provider-agnostic inference transport + model-tier routing (no single-vendor lock-in at
        the inference layer).
    11. Idempotency / exactly-once under retries: task-token + correlation-id binding, stale/
        duplicate-callback rejection, and verdict-to-head-SHA (TOCTOU) binding at merge.
    12. Offline evaluation / regression harness for the agent PERSONAS THEMSELVES (does a change
        to a persona prompt regress plan or implementation quality?).
  The maturity computation (section 15) reads this `external_checklist` field as its SOLE source
  for the frontier tier.
- Q3 -- SAFETY & CONTAINMENT SEQUENCING. Verdict enum: `sound | partial | unsound`. The four
  containment items T4.8 (semantic locks/leases), T4.9 (verdict handshake + SHA binding), T4.10
  (persona contracts: allowed/forbidden tools, max_llm_calls, max_revisions), and T4.11 (loop-
  budget caps) are all `deferred_post_mvp`. Judge, per item, whether its capability is required
  for the loop to close SAFELY at the MVP boundary. If a control is needed at MVP but parked
  post-MVP, that placement is the defect (classification `planned-unbuilt`). `unsound` = at least
  one MVP-critical containment control is deferred with no interim substitute.
- Q4 -- SUBSTRATE & TECHNOLOGY RISK. Verdict enum: `sound | partial | unsound`. Assess the CD.27
  bet: Step Functions Standard Workflows for the per-rec lifecycle; Lambda Durable Functions
  (noted ~5 months in GA at CD.27) for persona loops with a DynamoDB self-checkpoint fallback as
  an INTENT open question; ECS Run Task as the >15-min escape hatch; the 256 KB Step Functions
  state limit handled via S3-pointer pattern; LiteLLM as sole transport; single region
  (eu-west-2). Judge whether each risk is hedged, and whether any is a frontier-fragility.
- Q5 -- QUESTIONS THE REQUESTER DID NOT THINK TO ASK. Use the `answers` shape. Seeds you MUST
  answer AND extend: (a) What governs autonomy in the window between T4.2 (loop first runs) and
  T4.4 (A-gates live)? (b) Does any T4 item own the "deploy -> observe" tail of the loop, or does
  it lean on the CD.35/CD.16 apply path, and is that seam specified? (c) Is there a rec-quality /
  eligibility gate before a rec is executed autonomously, beyond freshness (T3.8)? (d) Is there a
  per-rec cost cap / cost-runaway alarm before the loop runs unattended? Add every further
  question a requester who wants a frontier autonomous executor would wish had been asked.

## 8. RUBRIC

Rate each in-scope surface on each dimension in `rubric_ratings[]`. Enum: `strong | adequate |
weak | absent | n/a`. `n/a` is correct and costless where a dimension does not structurally apply
to a surface -- never manufacture a rating or a finding to fill a cell. Surfaces to rate:
`orchestration` (T4.1/CD.27 workflow layer), `personas` (T4.2/T4.10), `verification`
(T4.9/CD.38), `autonomy-governance` (T4.4/T4.11/T4.8), `plan-entities` (T4.5/T4.6/T4.7),
`scheduled-agents` (T4.3), and `shared` (cross-cutting).

- VD1 loop-closure completeness (serves Q1) -- does the surface fully own its slice of the loop?
- VD2 containment & safety (serves Q3, NS-B) -- budgets, locks, boundary, rollback, RCA-first.
- VD3 verification integrity (serves Q1/Q3, NS-C) -- independent oracle, TOCTOU/SHA binding,
  no self-certification.
- VD4 substrate soundness & durability (serves Q4, NS-D) -- engine fit, checkpoint-replay,
  escape hatch, state-size, region/DR.
- VD5 observability, telemetry & cost (serves Q4, NS-D) -- per-turn tracing, cost caps, gate
  metrics.
- VD6 sequencing & dependency integrity (serves Q1/Q3) -- `depends_on` edges, gates, MVP-boundary
  placement, deferred-vs-live consistency.
- VD7 frontier alignment (serves Q2, NS-F) -- surface's standing against the section-7 checklist.
- VD8 agent-first governance fit (serves Q1, NS-B) -- persona contracts, verb-RBAC, plan
  authority-flip/staleness, self-describing surface.

Every question is served by at least one dimension; every dimension serves at least one question
or deep-dive.

## 9. DEEP-DIVES

- DD-A (loop-closure trace; feeds Q1, Q5). Trace the full MVP loop transition-by-transition
  against the tier_items. For each transition produce: owning item(s), the exit criterion that
  guarantees the property (quote it), and a gap classification. Pay specific attention to the two
  ends the tier_items under-emphasise: rec SELECTION/eligibility at the head (what picks the rec,
  what makes it safe to auto-run) and DEPLOY->OBSERVE at the tail (what applies the merged change
  and confirms the next observable state).
- DD-B (deferred-containment sequencing; feeds Q3). For each of T4.8/T4.9/T4.10/T4.11, establish:
  what the control does, why it is deferred (read the item's forward-intent note), what -- if
  anything -- substitutes for it before MVP (e.g. T4.1's concurrency=1 substitutes for T4.8's
  locks; is that substitution complete and self-consistent?), and whether the loop can reach
  MVP-closed without it. T4.10 states "T4.2 persona implementations MUST conform to these
  contracts" while T4.10 is deferred and T4.2 is not: trace whether this is a live-depends-on-
  deferred inversion versus the Decision 93 rule that "no live platform item may depend_on a
  deferred_post_mvp item," and whether the model_validator that enforces that rule sees this
  prose-level coupling.
- DD-C (verification leg; feeds Q1/Q3/Q4). Trace CD.38 + T4.9: the executor never runs validate.py
  or verifiers in-cloud; Step Functions dispatches and WAITS on GitHub Actions verdict callbacks;
  merge is permitted only when the callback's verified head SHA equals the PR head at merge time.
  Cross-check against T4.2's own exit criterion that already requires `file_pr -> PR opens and
  validates green`. Judge whether the T4.2 exit criterion depends on a protocol (T4.9) that is
  deferred, and whether that is a sequencing inversion or a benign smoke-vs-production distinction.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every anchor was read from disk during
composition, but anchors rot and origin/main may have advanced -- VERIFY each before you rely on
it, and record any non-resolving anchor in `meta.stale_anchors`. Facts are stated neutrally; the
verdict is yours to reach.

Roadmap (`docs/ROADMAP-PLATFORM.yaml`; line numbers approximate):
- CD.27 (~line 1011): names the executor substrate as Step Functions (one execution per rec) +
  Lambda Durable Functions (personas) + deterministic Lambdas (glue); `state: pending`;
  narrowly_supersedes CD.11's Fargate-as-executor clause; `discipline_points` include
  "Step Functions retry policies are deterministic-only" and a Durable-Functions-maturity note
  ("~5 months in GA ... if API semantics regress within the first 12 months, fall back to
  self-checkpointed Lambda with state in DynamoDB").
- CD.17 (~line 647): the freeze-reversal trigger -- `T4.2.status == complete AND
  grace_period_elapsed(T4.2,14) AND item_field_eq(T3.2,"latest_run.verdict","PASS") AND
  T3.3.status == complete AND grace_period_elapsed(T3.3,7)`; `state: pending`.
- CD.37 (~line 1805): semantic locks (not file locks alone) for parallel rec execution; "inert
  under the freeze and the T4.1 concurrency=1 ceiling until the autonomy gates (T4.4) raise
  concurrency above 1"; gates T4.8.
- CD.38 (~line 1827): executor delegates verification to GitHub Actions; AWS waits on verdicts;
  "GitHub Actions is the sole verifier/validation runner; AWS never runs validate.py or verifiers
  in-cloud"; merge only when callback head SHA == PR head; gates T4.9.
- T4.1 (~line 7311): `status: not_started`, effort L, `depends_on: [T2.1, T3.2]`. State-machine
  glue Lambdas pick_rec/prepare_workspace/critique_gate/file_pr/emit_telemetry; "Concurrency cap
  = 1 on the state machine initially per Decision 55 RCA-first; raise as autonomy gates A2+ pass";
  every waitForTaskToken/verdict-wait state carries HeartbeatSeconds/TimeoutSeconds routing
  timeouts to ci-rca.
- T4.2 (~line 7373): `status: not_started`, effort XL, `depends_on: [T4.1, T3.4, T1.6]`. Personas
  plan_agent/plan_critic/decision_scout/implement_agent/code_reviewer as Durable Functions;
  LiteLLM sole transport; an exit criterion requires the end-to-end smoke "rec -> plan_agent ->
  Parallel(plan_critic, decision_scout) -> critique_gate PASS -> implement_agent -> code_reviewer
  -> file_pr -> PR opens and validates green"; another exit criterion is the CD.17 stability
  precondition (grace_period_elapsed(T4.2,14) AND zero unrecovered failures).
- T4.3 (~line 7444): `not_started`; re-enable six scheduled agents on the persona substrate;
  substrate choice (Step Functions scheduled execution vs GitHub-hosted Actions schedule) left to
  the atomic plan.
- T4.4 (~line 7505): `not_started`, effort XL, `depends_on: [T4.2, T3.4]`. Autonomy gates A0-A5,
  each with entry/exit AND a rollback criterion; rollback file-rec is automatic, formal gate
  change is human-ratified.
- T4.5/T4.6/T4.7 (~lines 7527/7573/7611): `not_started`. Plan/critique/revision warehouse
  entities; authority-flip from git to warehouse; plan-staleness (base_commit_sha pinning +
  divergence check) as the precondition for planning/implementation decoupling.
- T4.8 (~line 7634): `deferred_post_mvp`, `depends_on: [T3.8, T0.12.5, T1.12]`. Deterministic
  semantic locks + lease protocol; "inert under the freeze and the T4.1 concurrency=1 ceiling
  until the autonomy gates (T4.4) raise concurrency above 1."
- T4.9 (~line 7666): `deferred_post_mvp`, `depends_on: [T4.1, T2.20]`. Executor<->GitHub-Actions
  callback + correlation protocol; correlation ids incl. head SHA; "Merge is permitted only when
  the callback's verified head SHA equals the PR head at merge time."
- T4.10 (~line 7709): `deferred_post_mvp`, `depends_on: [T4.1, T1.12]`. Persona contract registry
  (input/output schema, allowed/forbidden tools, max_llm_calls, max_revisions, failure_outputs);
  adds rca + bookkeeping personas; states "T4.2 persona implementations MUST conform to these
  contracts."
- T4.11 (~line 7745): `deferred_post_mvp`, `depends_on: [T4.1, T4.10]`. Loop-budget caps enforced
  by Step Functions state (not persona prompt discipline); transport-retry separated from
  judgement-revision budget; exhausted budgets route to RCA.
- T3.2 (~line 6551): `not_started` causal-chain verifier; its latest-run PASS is gate G.8 and a
  CD.17 precondition. T3.4 (~line 6581): `not_started` control-plane loop closure (STRATEGIC).
  T3.20 (~line 7239): `not_started` agent-turn telemetry capture, `depends_on: [T2.36, T1.10, T3.2]`.
- known_gaps: KG.2 (~line 8224, ~250-rec backlog not mapped to tier items; ~35 executor recs
  aligned with T4.2 at snapshot), KG.3 (provider-agnostic executor INTENT "not deeply consumed";
  T4.2 to re-read at decomposition), KG.13 (~line 8331, Test Impact Analysis + result caching
  deferred to executor scale).

Decisions (`docs/DECISIONS.md`):
- Decision 55 (~line 2274): RCA-first -- on unrecoverable failure, stop cleanly, invoke RCA, file
  a permanent-fix rec; NO rescue/workaround automation; deterministic recovery (git retry, ruff
  auto-fix, timeout retry) remains valid.
- Decision 67 (~line 2503): the surviving STRATEGIC-plan-freeze clause; reversed by CD.17.
- Decision 87 (~line 1546): plans/critiques/revisions become warehouse entities; git remains
  authoritative until the autonomous producer (T4.x) exists; cl.6 gates plan/implement decoupling
  on a plan-staleness story.
- Decision 90 (~line 1490): four-tier workflow `/orient -> /plan -> /implement ->
  /develop-executor`; current operational state is the first three, executor frozen.
- Decision 93 (~line 1286): Platform-MVP boundary = "the autonomous loop closes end-to-end with no
  human in the critical path of one iteration (rec -> implement -> validate -> merge -> deploy ->
  observe -> next rec)"; introduces `deferred_post_mvp`; line ~1308: "No live platform item
  (status == not_started or in_progress) may depend_on a deferred_post_mvp item. The
  platform_roadmap.py model_validator enforces this at load time."

Context-only anchors (do NOT audit; confirm existence if a candidate turns on them):
- `scripts/execute_recommendation.py`, `scripts/executor/*.py`,
  `config/agent/executor/prompts/*.prompt.md` -- the frozen existing executor (TRAP-1).
- `config/agent/executor/capabilities.yaml` -- `boundary_patterns` + `maturity_ceiling: 1.0`, the
  self-modification boundary SSOT (Decision 117).

### 10.1 CANDIDATE OBSERVATIONS (the "candidate list"; adjudicate EACH per section 2)

Each is a neutrally-phrased hypothesis drawn from the facts above, NOT a verdict. Adjudicate every
one to a finding or a `rejected_candidate` (section 2). This list is a FLOOR on your attention, not
a ceiling -- surface defects not listed here, and do not assume any listed item is real. The list
is deliberately mixed: some are expected to resolve to `rejected_candidates`.

- C1. T4.8 (semantic locks/leases), T4.9 (verdict handshake + SHA binding), T4.10 (persona
  contracts), and T4.11 (loop-budget caps) are all `deferred_post_mvp`, while the MVP boundary
  (Decision 93) is "the loop closes end-to-end with no human in the critical path." Hypothesis:
  one or more of these controls is required to close the loop SAFELY at MVP.
- C2. T4.2's exit criterion requires `file_pr -> PR opens and validates green`, while the
  verdict-callback/correlation protocol that governs the merge decision (T4.9 / CD.38) is
  `deferred_post_mvp`. Hypothesis: T4.2's exit depends on a deferred protocol (sequencing
  inversion), versus a benign smoke-vs-production distinction.
- C3. T4.10 states "T4.2 persona implementations MUST conform to these [persona] contracts," yet
  T4.10 is deferred and T4.2 is live (`depends_on: [T4.1, T3.4, T1.6]` -- no edge to T4.10).
  Hypothesis: a prose-level live-depends-on-deferred coupling the Decision 93 model_validator does
  not see, versus a benign forward-reference.
- C4. Concurrency is fixed at 1 (T4.1) and raised only by the A-gates (T4.4, XL), while the
  concurrency-safety mechanism (T4.8 semantic locks) is deferred. Hypothesis: single-concurrency
  is the effective MVP steady-state throughput and a frontier economics gap.
- C5. No T4 tier_item appears to own an offline evaluation / regression harness for the agent
  personas themselves (does changing `plan_agent.prompt.md` regress plan quality?); T3.7
  meta-validates `validate.py`, not persona output quality. Hypothesis: persona-eval is an absent
  capability.
- C6. RCA-first (Decision 55) routes every LLM-judgment failure to a filed rec + human review;
  combined with concurrency=1 and no-LLM-retry, hypothesis: a human is structurally reintroduced
  such that "no human in the critical path" (NS-A) is not achievable in practice -- versus the RCA
  path being the exception path, not the critical path.
- C7. Lambda Durable Functions is noted ~5 months in GA at CD.27, hedged by an INTENT-level
  DynamoDB-self-checkpoint fallback. Hypothesis: substrate-maturity risk is inadequately hedged
  for a frontier bet.
- C8. Per-turn cost telemetry and any per-rec cost cap / runaway alarm depend on T3.20
  (`not_started`, deep dependency chain) and are not named in a T4 exit criterion. Hypothesis:
  cost-runaway observability is missing before the loop runs unattended.
- C9. The autonomy gates A0-A5 land in T4.4 (depends_on T4.2), while the loop first runs at T4.2.
  Hypothesis: there is no governed autonomy story in the T4.2->T4.4 window.
- C10. The MVP loop names "deploy -> observe." Hypothesis: no T4 item owns the autonomous
  deploy-and-observe tail; it leans on the CD.35/CD.16 apply path and that seam is unspecified.
- C11. Rec freshness/relevance is gated (T3.8, complete) and reconciled (T3.9). Hypothesis: a
  rec-quality / well-formedness eligibility gate BEFORE autonomous execution (is this rec safe to
  auto-run?) is absent, distinct from freshness.
- C12. The entire executor is single-region (eu-west-2). Hypothesis: single-region is a frontier
  resilience gap -- versus a deliberate cost/complexity tradeoff consistent with the North Star.

## 11. EMPIRICAL PASS

This is a design/roadmap audit; the primary evidence is the roadmap and decision text, which is
static. One bounded empirical sample is permitted and useful:

- Sample <= 15 OPEN recommendations whose title or context matches the executor
  (`executor|persona|step function|durable|autonom|T4\.|plan_agent`) from
  `logs/.recommendations-log.jsonl` -- do NOT exceed 15; order by each rec's `date` field
  (YYYY-MM-DD) descending and take the newest 15 matches. Use them ONLY to
  test the KG.2 hypothesis (is a real executor-rec backlog unmapped to T4 items, and does any rec
  in it name a capability absent from the T4 tier_items?). Tag any finding this produces
  `evidence_kind: observed`; an observed gap (a real filed rec naming a missing capability)
  outranks a purely static "the roadmap doesn't mention X" finding at equal severity. All other
  findings are `evidence_kind: static`. The counterfactual per sample: "would this rec still be
  necessary if the T4 design as written were fully built?" -- if yes, the capability it names is a
  candidate gap; if no, it is already owned.

## 12. METHOD

- P1 READ: sections 3-10; read every in-scope tier_item, CD, and decision named in section 10 from
  disk; confirm the trap boundaries.
- P2 TRACE: run DD-A (loop-closure), DD-B (deferred-containment), DD-C (verification leg).
- P3 EMPIRICAL: the single bounded rec sample (section 11), only to test KG.2.
- P4 RATE: fill `rubric_ratings[]` per surface x dimension.
- P5 DEDUP: section 13, before any finding is written.
- P6 ADJUDICATE: each candidate (the section 10.1 list, C1..C12) + each surfaced defect -> finding
  or rejected_candidate.
- P7 SYNTHESISE: question_answers, per_surface_assessment, summary; compute maturity LAST
  (section 15).

## 13. DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding's
`roadmap_crossref`:
- grep `docs/ROADMAP-PLATFORM.yaml` for the capability (tier_items AND candidate_decisions AND
  known_gaps AND open_questions).
- grep `^## Decision` headers and bodies in `docs/DECISIONS.md`.
- grep `logs/.recommendations-log.jsonl` for an open rec already naming it.
Record `dedup_search_terms` (the terms you searched) and `dedup_hit_count` (matches found). A hit
means the territory is already owned: the finding is `planned-insufficient` (owned, remedy weak)
or `planned-unbuilt` (owned, deferral/sequencing is the defect), or it moves to
`rejected_candidates` (fully covered) -- never `novel`. A finding filed `novel` without a recorded
negative search is a HYPOTHESIS, not a confirmed finding; mark it so.

DELIBERATE-CONSTRAINT DO-NOT-FLAG LIST (each with its authority -- do not file these as defects):
- The executor being unbuilt/frozen -- Decision 67 / CD.17 (deliberate).
- `deferred_post_mvp` as a status per se -- Decision 93 (you MAY flag only that a SPECIFIC deferred
  control is MVP-critical, never the status itself).
- STRATEGIC plans blocked / XL items decomposed into atomic IMPLEMENTATION plans -- Decision 67.
- Single-account, SIT/PROD as future -- Decision 77.
- Git-authoritative plans until the T4.6 authority-flip -- Decision 87.
- Bedrock retired / LiteLLM-only transport -- CD.28.
- Concurrency = 1 as the initial ceiling -- T4.1 / Decision 55 (raised by A-gates).
- KG.3 (provider-agnostic INTENT not yet deeply consumed) is a known, owned gap -- not novel.

## 14. OUTPUT

Write both deliverables. Pin every enum inline. YAML shape:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported name, free text>, methodology_version: 1,
         scope_surfaces: [orchestration, personas, verification, autonomy-governance,
                          plan-entities, scheduled-agents, shared],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: complete|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: frontier|competitive|lagging, basis: [<finding ids>], prose: "",
       external_checklist: [{property: "", rating: met|partial|missed, evidence: ""}]}  # 12 rows
    - {q: Q3, verdict: sound|partial|unsound, basis: [<finding ids>], prose: ""}
    - {q: Q4, verdict: sound|partial|unsound, basis: [<finding ids>], prose: ""}
    - {q: Q5, answers: [{question: "", answer: "", basis: [<finding ids>]}]}  # seeds a-d + extensions
  per_surface_assessment:
    - {surface: <one of scope_surfaces>, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: <>, dimension: VD1..VD8, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: EXR-01, surface: <scope surface|shared>, question: Q1..Q5, dimension: VD1..VD8,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|resequence,
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
            maturity_orchestration: "", maturity_personas: "", maturity_verification: "",
            maturity_autonomy_governance: "", maturity_plan_entities: "",
            maturity_scheduled_agents: "", maturity_shared: ""}
```

INVARIANTS (state and honour these):
- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) =
  novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered candidates live
  in `rejected_candidates`, NOT findings. `rubric_ratings` / `question_answers` /
  `external_checklist` are systems-of-record referenced FROM findings, never re-counted.
  `top_improvements` and `highest_leverage_change` MUST be finding ids.
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal: name the property the control exercises, cite where it operates (item-id or
  file:line), and state why the control would FAIL if the defect were real.
- CONFIRMED requires the behaviour traced to a specific tier_item/CD/decision line or an observed
  sampled rec; anything less is HYPOTHESIS.

The companion `.md` (<=1500 words): lede (what was audited and the headline verdict on the two
driving questions), the five question verdicts with one paragraph each, a short table of the
highest-leverage findings, and the per-surface maturity line. Prose for humans; no YAML dump.

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherit it from this prompt's framing:
- critical = the autonomous loop could take an irreversible action (merge, deploy) on an unsound
  or unverified basis, or a self-improving loop could run unbounded (no budget/lock/rollback) at
  the point it is first live.
- high = a capability the closed loop materially needs is absent or under-specified AND its
  compensating controls are insufficient (property-match applied).
- medium = redundancy / ambiguity / sequencing inconsistency with a clear fix.
- low = clarity / wording / cross-reference.

COMPENSATING-CONTROL PROPERTY-MATCH: a control lowers severity or dismisses a candidate ONLY if it
exercises the SAME property AND would FAIL if the defect were real. Example: "concurrency = 1"
property-matches "no semantic locks yet" ONLY while concurrency is genuinely 1; it does NOT
property-match any risk that survives at concurrency 1.

MATURITY -- compute LAST, per surface, top-down, first match wins. The `per_surface_assessment.maturity`
and every `summary.maturity_<surface>` field take this enum: `frontier | strong | solid | nascent`
(distinct from the rubric enum). Pin these thresholds:
- `frontier` = 0 open critical AND 0 open high findings on that surface AND every Q2
  `external_checklist` row RELEVANT to that surface (mapping below) is rated met or partial
  (never missed).
- `strong` = 0 critical AND <= 1 high on that surface.
- `solid` = <= 1 critical on that surface.
- `nascent` = otherwise.

Checklist-row-to-surface relevance (pinned; a row may be relevant to more than one surface; the
`shared` surface is relevant to ALL 12 rows; if you judge a row ambiguous for a surface, COUNT it
as relevant -- the conservative direction):
- `orchestration`: rows 1 (durable orchestration), 5 (sandboxing/IAM), 9 (RCA-on-failure),
  11 (idempotency/TOCTOU).
- `personas`: rows 1 (checkpoint-replay), 2 (planner/critic/actor), 5 (per-persona tool scoping),
  8 (per-turn observability), 10 (provider-agnostic transport), 12 (persona eval harness).
- `verification`: rows 4 (independent oracle), 11 (idempotency/TOCTOU/SHA binding).
- `autonomy-governance`: rows 3 (bounded autonomy), 6 (progressive autonomy + rollback),
  7 (semantic-lock concurrency).
- `plan-entities`: rows 8 (observability of plan/revision state); otherwise mostly `n/a`-by-mapping
  -- a row not listed for a surface does not gate that surface's frontier rating.
- `scheduled-agents`: rows 8 (observability), 9 (RCA-on-failure), 10 (provider-agnostic transport).
The top rating remains reachable where you argued a property-matched compensating control -- the
framing here must not foreclose it. A surface that is deliberately unbuilt-but-well-designed can
still rate `frontier` on design terms; state in `per_surface_assessment.strengths` that the rating
is a design-maturity rating, not a built-state rating.

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE (section 5 step 1): `git fetch origin main` then
   `git rev-parse --short origin/main` -> `<sha>`. This base IS the audited tree; use `<sha>` in
   both filenames, the branch name, and `meta.audited_commit`.
2. `git switch -c audit/executor-roadmap-review-<sha> origin/main`. This clean two-file branch off
   the audited base is a deliberate, documented exception to the AGENTS.md `claude/*`
   session-branch rule (the CI signal-green comment wake fires only on `claude/*` PRs and is
   irrelevant here -- you end your turn without merging; the human disposes).
3. Repo-wide `validate.py` is advisory outside CI in this repo: a clean YAML parse of the two
   deliverables (`bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"
   audits/executor-roadmap-review-<sha>.yaml`) is the real pre-push gate. An unrelated
   `validate --pre` failure is recorded in `meta.contract_notes`, never fixed (write boundary).
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing
   is unavailable. Commit message: `audit: autonomous executor roadmap review (T4 design)`.
   `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title
   `audit: autonomous executor roadmap review (T4 design)`, body = the `summary` block in a
   ```yaml fence + a 2-3 sentence lede naming the two driving verdicts). Then END THE TURN -- do
   not poll, do not subscribe, do not merge.

## 17. GUARDRAILS

- WRITE BOUNDARY (closed list): the ONLY files you create or modify in the repository tree are
  `audits/executor-roadmap-review-<sha>.yaml` and `audits/executor-roadmap-review-<sha>.md`.
  Regenerating gitignored local caches per section 5 is expected and is not a breach; never commit
  them. You file NO recommendations and NO decisions -- the human disposes of your findings.
- Public repo: no AWS account IDs, ARNs, IAM ExternalIds, credentials, internal hostnames, or
  trading alpha in either deliverable.
- Precision over volume. Fewer than ~8 surviving findings is a valid, good result -- state it; do
  NOT pad. A run that merely restates the candidate list, or that files "the executor isn't built
  yet" as a finding, has failed. Every finding must survive its dedup search and its
  property-matched compensating-control test.
- You have no human to ask. Where this prompt assigns a judgment to you, make it and record your
  reasoning; where it pins a rule, follow it; if an anchor does not resolve, record it in
  `meta.stale_anchors` and re-derive from the repo rather than guessing.
