# Executor Roadmap Review (T4 design) -- companion report

Audited: the designed-unbuilt T4 autonomous-executor architecture (Step Functions + Lambda
Durable Function personas + deterministic glue; CD.27/CD.17/CD.37/CD.38/CD.10 and T4.1-T4.11)
at commit `7d57a0d`. Structured audit: `audits/executor-roadmap-review-7d57a0d.yaml`.

**Headline on the two driving questions.** (a) The roadmap has gaps, but they are almost all
*placement* gaps, not missing design: every loop transition has an owner, and the two serious
defects are controls that were designed correctly and then parked `deferred_post_mvp` on the
wrong side of the very boundary (Decision 93) that needs them -- merge mechanics (T4.9) and
loop budgets (T4.11). (b) The design is genuinely near-frontier -- **competitive** by the
pinned rubric, one checklist row short (offline persona evaluation), with several elements
(plan-entity RBAC, sole-external-oracle verification, rollback-keyed autonomy gates) at or
beyond common industrial practice. The fixes are cheap: mostly roadmap re-sequencing edits,
not new architecture.

## The five verdicts

**Q1 -- completeness: `partial`.** Walking rec -> plan -> critique -> implement -> review ->
verify -> merge -> deploy -> observe: the middle of the loop (plan through verify) is owned and
well-specified by T4.1/T4.2/T4.5-T4.7 and CD.38. The two ends are weaker. At the head, `pick_rec`
is specified only as "poll priority queue" -- nothing binds it to the T3.8 relevance verdict, the
writer-derived automatable/risk fields, or the Decision 117 self-modification boundary (EXR-04).
At the tail, the state machine's last states are `file_pr -> emit_telemetry`: merge mechanics
exist only in deferred T4.9, and the deploy seam onto the ratified CD.35 apply path is
contradictorily documented (EXR-01, EXR-07). No transition is *absent*, so the verdict stops at
partial rather than insufficient.

**Q2 -- frontier posture: `competitive`.** Eleven of twelve checklist rows are met or partial;
the safety-critical rows (independent verification, sandboxing, idempotency/TOCTOU) are none of
them missed. The single miss is row 12: no offline eval/regression harness for the personas
themselves -- a persona-prompt or model-tier change reaches production with only reactive
detection (EXR-08). The partials (bounded autonomy, sandboxing enforcement, idempotency) all
trace to the same cause: T4.9/T4.10/T4.11 are designed to frontier standard but deferred past
the point their governance is first needed.

**Q3 -- containment sequencing: `unsound`.** Per item: T4.8 (locks) is *correctly* deferred --
concurrency=1 property-matches it exactly, and CD.37 keys reactivation to the same event (T4.4
raising concurrency) that creates the hazard. T4.9 and T4.10 are mis-sequenced (EXR-01, EXR-03).
T4.11 is the verdict-driver: at the MVP boundary the loop runs unattended with no enforced cap
on plan->critique->revise cycling or total LLM calls per rec. Deterministic-only retries bound
transport, concurrency=1 bounds the fleet, and cost alarms detect -- but nothing *stops* a
cycling execution, and the platform's own history (rec-449, cited in Decision 55) shows critique
cycling is a real failure mode. One MVP-critical control deferred with no interim substitute
pins the verdict at unsound (EXR-02, the audit's only critical finding). The remedy is a
re-sequencing edit, not new design.

**Q4 -- substrate risk: `sound`.** The CD.27 bet is hedged risk-by-risk: Durable Functions
(~5 months GA) carries a designated DynamoDB self-checkpoint fallback with a 12-month
re-evaluation trigger, a forced-timeout checkpoint-replay exit criterion, and a health-signal
alarm; the 256 KB state limit is pre-empted by the S3-pointer discipline; Step Functions
Standard is ratified precedent (Decision 39). LiteLLM-only transport with a cold Tier 3 and
single-region are deliberate, owned residuals (KG.7, Decision 77) that stall rather than
corrupt. The one seam: CD.27's escape-hatch example names "terraform apply" as an in-executor
ECS task, contradicting the ratified Decision 92/CD.38 apply authority (EXR-07).

**Q5 -- unasked questions.** The window between T4.2 and T4.4 is governed by construction
(T3.4 -- a T4.2 dependency -- requires A0-A3 live first), though A-gate ownership is split
across two items with no boundary statement (EXR-06). The deploy tail deliberately leans on the
live CD.35 pipeline -- sound reuse, but rec-2523 (observed) shows that path has a guard-BLOCK
red-record deadlock that required an out-of-band human admin apply. No item owns the
adversarial-input/prompt-injection threat model of a loop that reads rec/repo/CI content and
merges its own repository (EXR-05). No item owns the cutover from the frozen single-process
executor, while live item T3.10 still plans work inside the frozen code (EXR-09). Extensions
worth an atomic-plan line: GitHub-side credential scoping for `file_pr`/merge, a named operator
kill-switch, and version skew for in-flight year-long executions.

**Empirical note (KG.2).** Of the 15 newest open executor-matching recs sampled, most matched
incidentally (ThreadPoolExecutor, budget-breach recs); none named a capability absent from the
T4 design except rec-2523's deploy-path deadlock, folded into EXR-07. The sampled backlog does
not evidence missing T4 capabilities.

## Highest-leverage findings

| ID | Sev | Class | One line |
|----|-----|-------|----------|
| EXR-02 | critical | planned-unbuilt | Loop budgets (T4.11) deferred past the boundary where the loop first runs unattended; no interim revision-cycle bound |
| EXR-01 | high | planned-unbuilt | Merge leg owned only by deferred T4.9; state machine ends at `file_pr`; T4.2's exit criterion presupposes the deferred callback protocol |
| EXR-04 | high | planned-insufficient | `pick_rec` admission predicate unbound to relevance / automatable / risk / self-mod boundary |
| EXR-05 | medium | novel | No prompt-injection threat model for persona context |
| EXR-08 | medium | novel | No offline persona-eval harness (sole missed frontier row) |
| EXR-03 | medium | planned-unbuilt | T4.10 "MUST conform / author before T4.2" prose contradicts its deferred status; invisible to the Decision 93 validator |
| EXR-07 | medium | planned-insufficient | CD.27 escape-hatch example contradicts ratified apply authority; observed deploy-path deadlock (rec-2523) |
| EXR-06 | medium | planned-insufficient | A-gate ownership split between T3.4 (A0-A3) and T4.4 (A0-A5 + rollback) |
| EXR-09 | medium | novel | Frozen-executor cutover unowned; T3.10 invests in code the substrate replaces |

Highest-leverage single change: **EXR-01** -- pulling the minimal verdict-callback +
merge-authority + SHA-binding slice of T4.9 ahead of the MVP boundary simultaneously repairs
the Q1 tail gap, the T4.2 exit-criterion inversion (C2), and checklist row 11, and it is the
edit the other re-sequencings (EXR-02/03) naturally ride with.

Four of twelve candidates were dismissed against property-matched compensating controls
(locks-vs-concurrency=1, RCA-as-exception-path, the Durable Functions hedge, single-region),
and two more were partially dismissed (deploy-tail ownership, cost telemetry) -- the candidate
list was a floor, not a script, and three findings (EXR-05/08/09) are novel, outside it.

## Per-surface maturity (design-maturity ratings, not built-state)

orchestration: **strong** | personas: **strong** | verification: **strong** |
autonomy-governance: **solid** | plan-entities: **frontier** | scheduled-agents: **frontier** |
shared: **strong**

The verification surface is the best *design* in the set (sole-external-oracle, SHA-bound
merge, TAP two-tier) held back purely by placement; plan-entities is the most complete surface
end-to-end (RBAC separation of duties, authority-flip timed to the producer, staleness gate
before decoupling). The through-line for the human reader: the T4 design does not need more
architecture -- it needs four `deferred_post_mvp` decisions re-examined against Decision 93's
own boundary definition, three of which this audit finds were parked one boundary too late.
