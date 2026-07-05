# Audit-target discovery -- companion report (audited commit f48bd85)

The top recommendation is an audit no existing surface can produce: examine the
**platform-first sequencing frame** itself (CAND-03) -- the directive that keeps the entire
trading product dormant until the autonomous loop closes appears in DECISIONS.md only as a
given inside Decision 93, was never ratified or weighed against an interleaving alternative,
and its conditions have visibly moved (executor frozen since May, zero telemetry captured,
product plane scaffold-frozen, MVP months out per today's triage). The headline across the
slate: this platform's governance names almost everything -- every finding is
*partially-owned* -- but nothing adjudicates **premises**. Mechanics are tended; the "because
X" layer underneath binding CDs and Decided decisions is where the audit-worthy material
lives. Structured slate: `audits/audit-scope-discovery-f48bd85.yaml` (system of record).

## The slate

| Rank | Cat | Target | One-line scope | Priority |
|---|---|---|---|---|
| 1 | CAT-D | Platform-first sequencing directive | Examine the never-ratified platform-before-product frame against an interleaved minimal-product-loop alternative | critical |
| 2 | CAT-B | 23 pending candidate_decisions | Premise-validity pass over the binding pending-CD set: superseded-unmarked text (CD.7/CD.10/CD.11), decayed inputs (CD.18 stash), empty ratification-lane feed | high |
| 3 | CAT-C | docs/DECISIONS.md live set | Premise-integrity sweep of 81 live entries; dead-premise Decided entries (26, 35, 37, 40 observed) plus a supersession-annotation control | high |
| 4 | CAT-D | DECISIONS.md authoring format | Examine the prose-monolith frame (271KB, ETL source, numbering authority) against structured/warehouse-native alternatives | high |
| 5 | CAT-A | code-review rec producer | Calibration of a producer filing recs ~4x faster than anything retires them (685 open, 400 code-review, 585 non-automatable) | medium |
| 6 | CAT-B | CD.4 + KG.9 | Re-test the "AGENTS.md is the portability hedge" premise against accumulated CC-web-specific machinery; disposition KG.9 | medium |

Recommended subset (Q6 seed d): run 1 -> 2 -> 3. CAND-03's verdict can rescope everything
below it; CAND-02 is small and feeds the two-day-old ratification lane real input (and can
unblock T1.5 via the CD.18 disposition); CAND-04 should wait for CAND-01's content pruning
(`depends_on`) and for T0.7b's fate.

## Highest-leverage audit

CAND-03 is both rank 1 and the highest-leverage candidate (Q6 seed c). Every active tier item
is built inside the platform-first frame, so if interleaved product iteration dominates strict
sequencing, the marginal value of a large share of in-flight work drops or re-orders -- and
the telemetry chain would fill with real trading data instead of waiting for synthetic loop
traffic. Critically, the existing audit portfolio cannot catch this: mvp-triage and the
executor review both operate *inside* the frame (their four "platform-first" mentions are
citations-as-premise, not examinations), and plan-critique's Frame Challenge fires only on new
plans, never on standing allocations. The audit can also "fail" productively: if the frame
survives, the deliverable is the ratifying Decision with reversal conditions that Decision 75
says a conscious frame choice requires -- today the directive is not even written down as a
decision. It is deliberately fenced: it does not re-open the immunized top-lines (DuckLake,
taxonomy, public repo) or the trigger-gated executor freeze.

## What we are NOT recommending

Everything recently covered stays covered: the T4 executor design, active-tier MVP triage, the
verification system, and the workflow layer (all four audits at HEAD), plus the trading-product
`src/` code itself -- already characterized to file:line precision by the wave-1 code-surface
audit embedded in ROADMAP-PRODUCT.yaml's `current_state`, and dormant by design (its leverage
relocates to CAND-03). We also decline the DD-B "missing framelock detector" framing: the
detector exists (plan-critique Phase 2b, mandatory, at `.claude/skills/plan-critique/SKILL.md:69`);
the residual standing-choice gap is best exercised by CAND-03/CAND-04, not audited as an
absence. Ratification-lane mechanics are owned (Decision 105 + ULF-02); OQ.3/5/6/14 and
KG.13/KG.14 are low-leverage or trigger-gated; Decision 114 already consciously decided the
roadmap-file-size question. Decision 48's stale V3 trigger list was absorbed into
verification-review's existing findings rather than double-counted.

## Category health

- **CAT-A (repo areas): well-tended** -- 0 critical/high; five recent audits plus the wave-1
  sweep own most area territory; one medium producer-calibration candidate survives.
- **CAT-B (roadmap constructs): tended** -- one high; transition mechanics owned, but the
  pending-CD set is binding-while-stale (three different treatments of superseded pending CDs
  coexist, and `ratifiable_cds()` is structurally empty because no pending CD carries
  `realization_evidence`).
- **CAT-C (decision premises): tended** -- one high, densely evidenced: 4 of 15 sampled
  entries (27%) failed the premise counterfactual with no annotation, and in-file Warehouse-ID
  metadata (dec-1083..1091; Decision 75's colliding "dec-081") drifted past Decision 105's
  CD-side-only reconciliation.
- **CAT-D (framelocks): thin** -- one critical and one high; the two named frames
  (platform-first sequencing; prose-monolith decision authoring) have no control that would
  ever re-examine them.

This report drafts; the human disposes. Nothing here executes an audit -- each finding's
`what_a_deep_audit_would_examine` seeds a future `/audit` invocation.
