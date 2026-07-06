# Audit: docs/DECISIONS.md as an authoring format — prose-monolith vs structured/warehouse-native

**Audited commit:** `d140093` (origin/main, 2026-07-05) | **Scope:** one surface, `docs/DECISIONS.md` as a FORMAT | **Maturity: solid** | **Findings: 4** (2 high, 2 medium; 2 novel, 2 planned-insufficient) | System of record: `audits/decisions-authoring-format-d140093.yaml`

## Verdict in one paragraph

Keep authoring decisions as prose in the one file — but ratify that choice consciously instead of drifting in it. The verdict is **ratify-prose-with-size-governance**. The repo's own precedents already answer the frame: Decision 87 says human-authored, low-frequency, diff-reviewed artifacts are correctly git-authoritative until a machine produces them at frequency (it names the DECISIONS.md ETL as its sanctioned precedent); Decision 114 says a growing canonical file gets a conscious ceiling plus a deterministic guard; CD.23 says human surfaces are projections of canonical state. Measured against those bars, the format's real defects are not "it is prose" — they are a lossy ETL that silently guts entries on their way to the warehouse (DAF-01), growth that doubled the file in 30 days with no ceiling, guard, or even a conscious no-ceiling ruling (DAF-02), a grammar that exists only as folklore imitated across ~120 distinct section markers and four divergent hand-rolled parsers (DAF-03), and a roadmapped end-state that deletes the governance surface where CD.23 says it should be demoted to a generated projection (DAF-04). All four are fixable at S effort inside the prose format, and all four are prerequisite work T1.5 inherits rather than redoes.

## What the empirical pass found (Q2 — the strongest evidence)

The parser (`scripts/decisions_md.py`) extracts 7 concepts keyed on exact bold markers; the corpus uses ~120 distinct markers. Running the real parser over 8 sampled entries (D121, D114, D87 post-85; D84, D77 middle band; D67, D48, D26 pre-77), the captured-field fraction ranged **9%–75%** of each raw block, and **all 8 dropped at least one governing element**:

- **Decision 84** — the entry that defines the warehouse invariants — lands in `ops_decisions` with an **empty `decision_text`**: its body marker reads `**Decision (four invariants):**`, which the exact-match regex never sees. Its 2026-07-03 amendment is invisible, except that the amendment's prose leaks the integer 70 into `related_decisions` three times.
- **Decision 67** — the decision that currently blocks all STRATEGIC plans — captures 194 of 2,172 bytes: `decided_date` is the literal string **"remove when reversal condition is met"** (the date-fallback regex harvesting a clause-status line), and problem/decision/context/related are all empty.
- **All 15 `**Reversal conditions:**` carriers** (the modern band's governing revisit triggers, Decisions 106–121) are dropped; so are all trailing `[Amendment]` blocks, all 7 blockquote migration-updates, `**Consequences:**` (6), and the April band's `**Decision status:**` lines (11 entries lose their dates). Plural cites ("Decisions 69/78") drop relationship edges.
- The backfill counts every such row as **"written"** — there is no fidelity signal anywhere, and the rows are in the table now (the backfill auto-runs on every merge touching the file).

The converse probe keeps this honest: when the canonical markers are used, rich prose survives intact (Decision 104's full multi-clause body lands complete), and the prose form carries things a bare structured row would flatten — dated inline amendments, clause-level statuses, renumbering provenance, qualified citations ("archived context, not a live governing decision"). Today this loss has **zero blast radius**: every content consumer (decision-scout, plan-critique, implement, humans) reads the file, and the table's only read verbs are a portal fetch and a freshness timestamp. The danger is precisely the roadmapped flip: T1.5 ports readers to the table and T5.4 deletes the file, and **no exit criterion anywhere requires content parity first**. Q2 verdict: **lossy-or-inverted** — lossy on fidelity (observed); the upstream-prose direction itself is sound, bounded, and triply ratified.

## Consumption paths (Q1) and governance (Q3)

Twelve paths enumerated; none requires a prose monolith. The scout's whole-file read (~271 KB ≈ 65–70k tokens per `/plan`) is mostly intrinsic content cost, but the container adds dead entries, boilerplate, and — decisively — an ungoverned growth trajectory. Two paths genuinely require a **git-tracked, human-readable** surface, which is not the same as prose authoring: human browse/sign-off, and the R1 ratification guard's referential target, which greps the file's headers *deliberately* because CI PR roles cannot reach the warehouse (Decision 105's hermeticity rationale). Q1: **mixed**.

Governance properties (numbering, sign-off, browse) all function today and all survive a structured format at modest cost — but growth is factually unruled: **130,797 B / 42 headers on 2026-06-05 → 271,398 B / 81 headers on 2026-07-05**. The only size guard in the repo is the roadmap's (`_ROADMAP_MAX_LINES = 10_000`, Decision 114); nothing equivalent references DECISIONS.md, and no decision consciously exempts it. At the observed rate the scout read exceeds a 200k-token window within ~2 months, while the only roadmapped shrink event (T5.4) sits behind T1.5 — STRATEGIC, frozen under CD.17, no ETA. Q3: **preserved-but-ungoverned**.

## Findings (fix-first order)

| ID | Sev | Class | One-liner |
|----|-----|-------|-----------|
| DAF-01 | high | planned-insufficient (T1.5/T5.4/T0.7b) | ETL silently drops/mangles governing content (8/8 sampled; D84 empty body, D67 garbage date); no fidelity tripwire; no parity criterion gates the consumer flip |
| DAF-02 | high | novel | No ceiling, no guard, no conscious ruling while the file doubles monthly and the mandatory /plan gate reads it whole; Decision-114 parity never applied |
| DAF-03 | medium | novel | No authoring grammar: ~120-marker folklore, four divergent parsers (ETL, R1 guard, preflight, dormant `list_customizations` cache-writer that evades the Decision-104 guard's patterns) |
| DAF-04 | medium | planned-insufficient (T5.4/T1.5) | End-state deletes browse + sign-off + the R1 guard's hermetic CI target with no named replacement — contra CD.23's projection principle |

**Highest-leverage change: DAF-01** — it is the one that prevents a wrong-but-trusted governance outcome from ever becoming reachable, and the parser/schema work is inherited intact by T1.5.

All four are safe to queue now. Sequencing note: DAF-01+DAF-03 share the parser file and co-land naturally; DAF-02's ratifying decision is where DAF-03's contract and DPI-04's archival relief valve get documented; DAF-04 is a pure roadmap-text edit that should land *before* CD.18/T1.5 thaw so the future planner inherits the corrected end-state.

## What was deliberately not filed

Six candidates dismissed with property-matched controls (full reasoning in the YAML): flip-authoring-now (fails Decision 87's ratified timing test and duplicates frozen T1.5 work at L–XL cost); the upstream-ETL "inversion" (a ratified, bounded, guard-enumerated carve-out); splitting the monolith (Decision 114/110 one-file principle — with the honest caveat that only its one-LOAD half transfers to prose); scout/critique cost symptoms and stale figures (workflow-review WF-04/05/14/18, largely fixed at HEAD); keyspace/display drift (CAND-01's DPI-03/05/06/07); numbering collisions (CAND-01 Q5 + the ratified writer-allocation direction).

## Questions the requester didn't ask (Q5 highlights)

- **"One file" and "prose" are separable properties.** Decision 114's one-file argument was made for a structured file whose consumers can project slices; a prose monolith gives one load but no projection — the scout's mandatory whole-file read is the direct consequence. A single generated or front-mattered file preserves both halves.
- **The authoring template is specified nowhere** — entry shape is imitation of the previous entry; that is how the unparsed Reversal-conditions convention spread through 15 entries without any parser learning it.
- **The archive rides every format decision** (ETL input #2, R1 referential peer, also deleted by T5.4) and is easy to forget; each proposed change names it explicitly.
- **The backfill rewrites the whole corpus per sync** (~101 upserts per merge touching the file) because prose offers no per-entry change detection — minor, recorded, foldable into DAF-01.

## Disposition mechanics (what the human ratifies)

One numbered Decision, Decision-114-parity: retain prose authoring for the interim (Decision 87 grounds); set a ceiling (suggested ~500 KB combined or ~150 live headers — sized to the scout window; the human picks the number) enforced by a new registry check; adopt the authoring contract + single shared parser; land the ETL parity fields and loud fidelity tripwire; edit T1.5 (parity exit criterion) and T5.4 (delete → generated projection, or name the replacement surfaces). Aggregate effort S. The maturity rating **solid** (2 open highs) reflects concentrated, specified, cheap-to-close gaps in an otherwise well-functioning governance surface — the strengths (single-load browse, PR-diff sign-off, hermetic CI target, continuous auto-backfill, modern-band discipline) are real and worth preserving through exactly the disposition above.
