# Platform roadmap MVP-triage -- executive report (audited commit 7d57a0d)

Companion to `audits/platform-roadmap-mvp-triage-7d57a0d.yaml`. All 48 active tier_items
triaged; the YAML is the system of record.

## The two verdicts

**MVP reachability (Q1): `reachable_with_resequencing`.** The Decision 93 boundary -- one
autonomous loop iteration with no human in the critical path -- is reachable, and the
Decision 67 / CD.17 freeze is not what would stop it. The freeze constrains plan *type* and
executor *operation*, not construction: CD.17's own text names decomposition into atomic
IMPLEMENTATION plans as "the current operating mode ... NOT a blocker for roadmap progress."
Every freeze-gated strategic item on the critical path (T1.5, T3.3, T3.4, T4.1, T4.2, T4.4)
is buildable today under that mode. The freeze holds structurally on its earliest-unmet
reversal gate -- T4.2 complete (+14d), still `not_started` -- with T3.3 (+7d) also unmet and
T3.2's runtime PASS treated as not-yet-PASS (no positive evidence exists). The diagnostic
critical path runs: T2.18 -> T2.19 -> T2.26 -> T2.36 -> T3.2 -> T3.3 -> T3.4 (with T1.13's
tail), in parallel the verb chain T0.7x -> T0.8 -> T1.1 -> T1.5 -> T1.6, then T4.1 -> T4.2.
Three resequencing corrections are needed: **(1)** T3.2 has no dependency edge to T2.36, but a
verifier proving PRODUCE->PERSIST->QUERY needs live DuckLake telemetry tables to assert
against -- plan it after T2.36 regardless of the DAG. **(2)** The ops_priority_queue is empty
*today* and its producer (rec-curator) is disabled and mispointed at a retired store
(Decision 84 caveat); nothing on the critical path owns restoring the loop's "next rec" feed
before the executor's pick_rec lands -- T4.3's producer slice must be pulled forward or the
feed question settled explicitly at T4.1 decomposition. **(3)** T1.5 -- on the only path to
T1.6, which T4.2 requires -- cannot start until CD.18 is ratified, a pending zero-cost human
act. Relatedly, CD.28 ratification is the only thing between T0.4 and complete. Both
ratifications should be explicit next actions.

**Telemetry (Q4): `binding_but_underscoped`.** Telemetry is genuinely the binding constraint
on recursive improvement, on two independent grounds. First, **zero telemetry is captured or
stored today**: the write path has been dead since the 2026-05-28 migration and open rec-2173
records the preflight blind spot -- there is no data for any improvement loop to read, so the
system currently iterates blind. Second, the chain is a *prerequisite* of the executor
unfreeze (CD.17 requires T3.2 PASS and T3.3 complete +7d), so the frozen executor cannot be
the upstream bottleneck -- and T3.3's anomaly recs have a live consumer before any executor
exists: the /orient -> /plan surface. The chain is fully itemized (capture T3.20, storage
T2.36, verification T3.2, analysis T3.3; contracts for all four tables ratified at T0.12.6),
so nothing is missing in scope -- the "underscoped" is placement: capture (T3.20), the
requester's stated priority, is sequenced *last* (behind T2.36 + T1.10 + T3.2), so no data
accumulates until nearly the whole chain is built; T3.2 lacks its storage edge; and T3.3's
false-positive threshold is undefined until decomposition. The June candidate framing
("capture ahead of a freeze-kept reader") is inverted: nothing is ahead of anything -- all
four links are not_started. If faster iteration is the goal, the storage substrate tail
(T2.26 -> T2.36) is the highest-value work on the board, followed by pulling capture as early
as its true dependencies allow.

## Counts

Of 48 active items: **20 keep_active_mvp** (no change -- the residual MVP by construction,
never enumerated as a committed set), **15 defer_post_mvp**, **4 mark_complete**, **1
remove**, **8 rescope**. 28 findings total; every deferral was verified against the
Decision 93 no-live-dep-on-deferred rule (the two coupled sets -- T2.30/T2.31/T2.32 and
T4.5/T4.6/T4.7 -- defer as closed units). Deferrals: T-1.19, T1.7, T1.9, T2.15, T2.30,
T2.31, T2.32, T3.5, T3.7, T3.14, T4.5, T4.6, T4.7, T5.1, T5.5. Completes (each proven
against read artifacts): T-1.14, T0.4 (pending only CD.28 ratification), T2.25, T3.17.
Remove: T5.4 (tombstone; duplicates T1.5's own first exit criterion). T5.2 is deliberately
*not* deferred -- Decision 93 excluded the billing-stopper from parking and its grace has
elapsed.

## Top five highest-leverage changes

1. **RMAP-06 -- consolidate the verb-surface closeout (T0.7a/b/c, T1.1, T1.2, T1.3).** Six
   items whose verbs already run in production every session, held open by residuals
   (obsolete import_mode criteria -- their consumer T2.2 is complete; pagination; describe;
   status-DAG check). One consolidated closeout item and one plan replace six of each.
2. **RMAP-01 -- mark T2.25 complete.** Decision 92 point 5 literally records "IMPLEMENTED by
   T2.25 / 2026-06-29"; guard, budget table, and SoT doc all verified. An M-effort phantom
   on the active surface.
3. **RMAP-07 -- split T4.3 and pull the queue-producer slice forward.** The loop's rec feed
   is empty and unowned on the critical path; deciding this now avoids discovering it at
   executor smoke-test time.
4. **RMAP-14 -- defer the priority string->int migration (T2.30).** L effort plus two V3
   Lambda cycles; the queue orders correctly on strings today.
5. **RMAP-15 -- defer the effort string->int migration (T2.31).** Same class, with its
   design precursor (the LOC weights) not even defined yet.

**The single highest-leverage change is RMAP-06**: it removes the largest block of
eligibility noise on the surface (six standing items on the loop's own write path) and
converts six prospective per-item closeout plans into one, while explicitly retiring the
obsolete import_mode criteria rather than letting them masquerade as unbuilt work.

## What was *not* changed, deliberately

Most of the roadmap survives contact: 20 of 48 items stand as-is, including the whole
executor cluster core (T4.1/T4.2/T4.4), the telemetry chain (T2.36, T3.2, T3.3, T3.20), the
DuckLake spine (T2.18/T2.19/T2.26), and the operator's recent explicit scoping calls (T3.9
MVP per 2026-06-24 note; T3.10 reactivated 2026-07-03) -- those were respected, not
relitigated. No mark_complete was granted where a criterion failed its artifact check
(T0.7c's pagination gap alone blocked an otherwise-done item from complete). No existing
deferred item is un-deferred; no committed MVP list is produced -- the Q1 sequence is a
diagnostic trace, and the defer-by-exception frame stands.

Per-tier maturity: T4 is `lean`; every other tier is `mostly-lean` (one redundant or
lagged item each; T1's rating reflects its silent-completion family rather than redundancy).
Nothing rated `noisy` or `overgrown`, and no deferral strands a dependent.

This report drafts; the human disposes -- nothing recommended here takes effect until a
human executes it via `/plan`.
