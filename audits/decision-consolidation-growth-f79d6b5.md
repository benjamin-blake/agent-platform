# Decision-log consolidation, growth direction, and semantic-intent capture -- executive report

Audited commit: `f79d6b5` (origin/main, 2026-07-21). Contract: `audits/decision-consolidation-growth-f79d6b5.yaml`. Model: claude-fable-5.

## Verdict

The decision corpus is healthier than the consolidation hypothesis assumed and in more acute danger than the growth hypothesis assumed. Across 52 of 103 live entries read in full, no same-rule redundancy exists -- subject-sharing entries are rule-distinct, title-annotated amendment/supersession chains, so merge machinery is not warranted (Q1: partial -- 4 of 5 seed clusters adjudicate keep-separate). What is warranted, immediately, is the narrower lifecycle both relief valves already name and nobody has built: the live file sits 1,562 bytes (0.4%) from its 400,000-byte pre-merge ceiling, having consumed 62 KB of the 64 KB headroom in the five days after Decision 134 ratified it, while archival (DPI-04, un-dispositioned) and compact-to-stub (named, unowned) remain unbuilt -- the next ordinary decision entry wedges the authoring path (DCG-01, high). Growth direction is insufficient (Q2): inflow is structurally amplified (Decision 86 routes all durable rationale in; the Decision-105 lane mints a full immutable record per CD state-flip -- 20 of the 39 entries authored 2026-07-02..07-20), there is no significance gate, and the only counterpressure is a total-size wall that cannot see composition (DCG-05, high). Semantic intent earns a scoped adoption (Q3): the parser probe shows the de-facto intent carrier is structurally absent on some entries (Decision 84 parses `context=""`), so an optional `Intent:` marker + nullable column (DCG-06) -- versioned for free by the existing content-hash SCD2 -- plus a quotability-gated scout SPIRIT bucket (DCG-07) close the spirit-alignment gap without authoring tax. Everything recommended is authorable now as IMPLEMENTATION work; nothing waits on T1.5 or CD.17.

## Q1 -- cluster map

| Cluster | Members | Verdict | Basis (one line) |
|---|---|---|---|
| telemetry-standards | 95, 96, 97 | keep-separate | Disjoint axes (model / temporal / identity), pointer-linked, never restated -- deliberate calibration confirmed |
| ducklake-ops-store | 78, 81, 84, 88, 99, 107, 124 | keep-separate | Layered lineage (adopt -> runtime -> sole-backend -> budget); 107's one-line restatement of 88 defers by citation; 78's victims correctly archived |
| size-structural-governance | 43, 102, 114, 128, 130, 134 | keep-separate | The 43->102->128->130 chain shares a subject but no clause is restated; hand-merging without parity tooling is the wrong-but-trusted hazard; 114/134 are deliberate per-artifact siblings |
| workflow-architecture-lineage | 42, 90, 38, 57, 58, 59 | compact-to-stub | 42's 64-line body is fully dead under 90 (which preserved it "intact"); 38/57/58/59 are DPI-02/04 lifecycle territory, not overlap |
| ci-validation-tiering | 60, 73, 135 | keep-separate | Annotated re-commitments; 73 explicitly retains 60 as "the originating ratification" -- a conscious ruling not re-litigated |
| superseded-live-bodies (ext.) | 42, 44, 49 | compact-to-stub | Fully superseded (by 90/117/116), full bodies in the hot path; the counterfactual returns empty -- nothing live dies |
| prose-governance (ext.) | 86, 127 | keep-separate | Rule-distinct expansion, title-annotated |

**Mechanism (Q1: partial).** A standing lifecycle is warranted only in the number-preserving form: eligibility criterion (whole body superseded/inert; superseders never move -- the archived-52-supersedes-live-37/40 inversion shows what criterion-free archival produces), a stub grammar keeping number/header/required markers/exact `Superseded by:` spelling, and terminal-SCD2 semantics (DCG-02). **Citation integrity decides the form:** 12,103 inbound `Decision N` citations across 865 files plus 998 `dec-NNN` citations have no mechanical guard, and the backfill has no tombstone path -- a removed header leaves the warehouse current-row orphaned-live forever (traced at `ops_portal/decisions.py:220`; DCG-03). Stubs keep every citation valid and the parser emitting, so the warehouse records a terminal Superseded version while SCD2 history retains every full pre-stub body -- **the warehouse is the provenance archive**; the hot file need not be. Destructive merges stay out of the vocabulary.

## Q2 -- external checklist scorecard (verdict: insufficient)

| # | Property | Rating | One-line evidence |
|---|---|---|---|
| 1 | immutability-supersession | partial | Immutable-by-convention + exact marker grammar, exercised; no enforced status lifecycle; victim annotation inconsistent (DPI-01) |
| 2 | one-decision-granularity | partial | Substantive entries exemplary (95/96/97); 25/103 ratify entries sit below decision grain (D136: `gates: []`) |
| 3 | significance-gate | missed | No articulated bar; D86 cl.2 routes all rationale IN -- an amplifier, not a gate |
| 4 | generated-index | missed | None; `logs/.decisions-index.jsonl` is a full-record cache no triage consumer reads |
| 5 | decision-drivers | partial | Problem/Rationale optional in the contract, near-universal in practice |
| 6 | machine-readable-frontmatter | partial | No front-matter, but shared parser + typed columns make id/status/supersedes addressable; `amends` is title-prose only |
| 7 | superseded-compaction | missed | Both valves named-unbuilt; 42/44/49 live with full bodies |
| 8 | revisit-cadence | partial | Built stanza monitor surfaces in every preflight; coverage = 1 carrier (D133), predicate registry empty |
| 9 | relationship-graph | partial | Related/superseded_by typed to warehouse; amends edges untyped; no traversal surface |

0 met / 6 partial / 3 missed. The byte guard is a symptom wall, not a direction mechanism: it counts totals and cannot see rate, shape, or composition. Direction = significance clause (DCG-05) + compaction/archival outflow (DCG-01/02) + batch-wave ratification (DCG-04: pure gate-clears land as one entry with per-CD clauses -- the many-CDs-to-one-decision shape is already exercised, CD.16/CD.24 -> dec-079) + generated index (DCG-08, the DAF-safe channel for properties 4/6/9).

## Q3 -- semantic intent disposition

- **Q3a (record): adopt-scoped.** The NULL hypothesis fails narrowly: Rationale carries intent content on most entries but is unaddressable (mixed concerns, no fixed spelling, no column) and absent on some -- observed: Decision 84 parses `context=""`, so zero typed why-content reaches the warehouse. Add `Intent:` as an **optional** fixed-spelling marker + nullable column across `DecisionPayload`, `jsonl_store.Decision` (plain, non-Dq, the raw_block pattern), and the DQ manifest (DCG-06). Never required -- no authoring tax, no retro-enforcement.
- **Q3b (SCD2): adopt.** Rides Decision 134 cl.4 by construction -- `content_hash` covers `raw_block`, so an Intent edit already produces a new version; the typed column makes intent revisions diffable. Grain unchanged. An intent-drift signal is a read-time query over consecutive versions, not stored machinery (Q4).
- **Q3c (scout): adopt-scoped.** Workable now without the deferred read redesign: the whole-file read already exists, so a second judgment axis adds zero read cost. A SPIRIT bucket fires only with a verbatim quote (Intent marker, or Problem/Rationale for the historical band), WARN/NOTE severity only, capped at 3, inside the existing 1,200-word budget (DCG-07). Soft-depends on Q3a for the cheap anchor.

## Maturity

**DECISIONS.md-corpus: solid** (2 open highs -- DCG-01, DCG-05 -- and three checklist misses; its strengths are real: rule-level non-redundancy, disciplined chain annotation, an exercised archive). All five other surfaces compute **frontier** under the pinned thresholds (0 critical / 0 high each): decision-entry.yaml, decisions_md.py+DecisionPayload, validate_decisions_size.py, decision-scout, and the Decision-105 lane carry only medium findings (DCG-06/02, DCG-03, DCG-01-adjacent, DCG-07, DCG-04 respectively) -- the per-surface notes carry the weak/absent rubric texture behind those mediums, which is where the improvement agenda lives.

**Highest-leverage change: DCG-02** (the compaction lifecycle) -- it durably relieves DCG-01, closes checklist property 7, is constrained correctly by DCG-03's ETL trace, and gives DPI-04's dispositions a sanctioned form. Top improvements: DCG-01, DCG-05, DCG-02, DCG-06, DCG-04.

## Dedup posture

`degraded_dedup: false` -- preflight caches generated successfully (787 open recs searched). Every finding carries recorded `dedup_search_terms`; all eight searched negative against open recs, `docs/ROADMAP-PLATFORM.yaml` tier_items/candidate_decisions, and both prior audit YAMLs. DCG-01 is `planned-unbuilt` against DPI-04 (whose own dedup note concurs nothing owns archival); the other seven are `novel`. Referenced-not-refiled: DPI-01 (victim annotations), DPI-02 (dead premises), DPI-04 (archival policy), DAF-01/02 (ETL parity, ceiling). TRAP boundaries held: Decision 43 treated as precedent-in-name only; format/premise/context-window axes untouched; the scout read-cost overlap is named in `meta.contract_notes` and deferred to the concurrent agent-context-governance audit.

**COUNTING INVARIANT (verbatim):** `findings[]` is the SOLE enumerated list; `total_findings = len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`; fully-covered candidates live in `rejected_candidates`, NOT findings; `rubric_ratings`, `question_answers`, and `consolidation_clusters` are systems-of-record referenced FROM findings, never re-counted; `top_improvements` and `highest_leverage_change` MUST be finding ids. Here: 8 = 7 novel + 0 planned-insufficient + 1 planned-unbuilt.
