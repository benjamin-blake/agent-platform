# AUDIT REPORT: DECISIONS.md premise integrity + supersession/keyspace sweep

**Audited commit:** `8fb581e` (origin/main, 2026-07-05) | **Surface:** `docs/DECISIONS.md` (81 live entries, 271KB) | **Maturity: solid** | **Findings: 7** (0 critical, 2 high, 4 medium, 1 low) | Contract: `audits/decision-log-premise-integrity-8fb581e.yaml`

Why-now context (observed facts): decision-scout loads this file in full as binding plan context; its Phase-1 text quotes a live-header count of 67 against an actual 81 (it re-derives at run time, so this is staleness evidence, not a defect). The file is the sole ETL source for `ops_decisions` (Decision 84).

## Verdicts

| Q | Topic | Verdict |
|---|---|---|
| Q1 | Premise integrity | **localized-drift** -- 64 live / 6 dead-annotated / 11 dead-unannotated / 0 indeterminate; every unannotated corpse is pre-Decision-77 |
| Q2 | Supersession-annotation control | **insufficient** -- practice is ad hoc (11 victims annotated, 11 not); no check exists; invariant specified in DPI-01 |
| Q3 | Warehouse-ID keyspace | **cosmetic-drift** -- ETL provably immune (keys on header numbers); 7 retired 4-digit ids + 1 collision are display drift with one agent-mediated hazard |
| Q4 | Lifecycle/status hygiene | **insufficient** -- stated archival policy has no enforcer and contradicts practice; 1 perpetual "pending review"; 8 archive-eligible entries |
| Q5 | Convention conformance | **insufficient** -- 2 properties missed (stable-unique-identifiers, supersession-bidirectionality), 3 partial |

## Q1 classified enumeration (number | premise class | archive-eligible)

**premise-live, none archive-eligible (64):** 121, 120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 88, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 77, 76, 75, 73, 72, 70, 67, 66, 65, 64, 63, 61, 60, 59, 57, 55, 48, 41, 39, 27, 25. (Clause-level unannotated amendments noted on 78 cl.3 and 80 pt.3 -- see Q6.)

**dead-but-annotated (6):** 71 (t), 89 (t), 68 (t), 62 (f), 42 (t), 24 (t) -- all carry migration-update blockquotes, amendment notes, or status-line supersession markers; (t) = archive-eligible.

**dead-unannotated (11):** 74 (f), 58 (f), 49 (t), 44 (f), 43 (f, SLOC row), 40 (f), 38 (f), 37 (f), 35 (f), 26 (t), 23 (t).

Counts: premise-live 64, dead-but-annotated 6, dead-unannotated 11, indeterminate 0; archive-eligible 8 (23, 24, 26, 42, 49, 68, 71, 89). Population verified: no `## Decision` inside a code fence; 26 is the only duplicate number across live+archive.

**Seed adjudication (DD-A).** All four seeds survive, none at the prompt's implied severity alone: **D26** -- artifacts (`plan.prompt.md`, `session_close.prompt.md`) deleted at T-1.13, architecture two supersessions stale (42->90), status "pending review" perpetual since March, and its number collides with a divergent archived Decided copy (DPI-05). **D35** -- unconditional "no auto-apply" inverted for sandbox by D77 cl.3 with no victim marker; stakes moderated: AGENTS.md:138 and terraform/CLAUDE.md co-cite it *with* D77, and D77 names and scopes it in-file. **D37** -- GitHub-Models dispatch superseded by D116's routing; dispatcher disabled; no victim marker (rec-2057 owns only its no-IAM-users facet). **D40** -- Copilot SDK retired (49->116), Bedrock retired (CD.28), triggers moot and unmonitored, yet ROADMAP-PRODUCT.md:755 still cites those triggers as a live activation condition, and the drafted supersession (INTENT-provider-agnostic-executor.md:3) was never filed. Beyond the seeds, the sweep added D23, D38, D43 (SLOC row inverted by D102), D44 (superseded by D117 yet cited as the authority by live enforcement code), D49, D58 (cited as canonical by ROADMAP-PLATFORM.yaml:7819), and D74 (the only retired-runner decision that never got the migration blockquote its five peers got).

## Keyspace map (DD-B)

43 in-file `**Warehouse ID:**` lines. Canonical rule (re-derived from dec-086..121 line text + Decision 105): `dec-NNN` = own decision number, 3-digit.

| Band | Entries | In-file value | Canonical? |
|---|---|---|---|
| 86-121 | 35 lines (dec-086..dec-121) | number-keyed | yes (dec-089 absent -- rec-2278) |
| 77-85 | 77:dec-1083, 78:dec-1085, 79:dec-1086, 80:dec-1088, 81:dec-1089, 83:dec-1090, 85:dec-1091 | retired writer-era 4-digit | **no** -- D105 itself maps CD.31->dec-078, CD.16/24->dec-079, CD.33->dec-081, CD.22->dec-085 |
| 75 | **dec-081** | collides with Decision 81's canonical id | **no** |
| no line (38) | everything <=76 except 75, plus **82, 84** (the keying-defining decision itself), 89 | -- | -- |

The ETL is immune: `parse_decisions_md` keys on `int(header number)` (scripts/decisions_md.py:90) and `file_decision` forms `dec-{n:03d}` from an integer -- the lines are never parsed. The residual hazard is `update_decision("dec-081")` by an agent trusting D75's line: the referential check passes against Decision 81's real row and silently corrupts it (DPI-03). ETL duplicate handling is silent first-parsed-wins (decisions_md.py:91-92) and the backfill is upsert-only with no reconcile -- so keyspace defects are invisible downstream and deleted/renumbered headers strand orphan rows (mechanism confirmed; current orphan existence untestable from the repo) (DPI-06). The archive additionally holds Decisions 52/53/54 as h3 headers the ETL sees but the R1 guard's h2-only regex does not (DPI-07).

## Annotation practice (DD-C)

Three shapes observed, all machine-detectable (each embeds the superseder's number in the victim's block): status-line suffix (D42 "(Superseded by Decision 90)"), migration/amendment blockquote (D68, D71, D60, D62, D24), inline bracketed correction (D92 "[CORRECTED by Decision 94...]", D67 restatement, the D84/D87/D103 mis-cite trio). Distribution: ~11 victims annotated, 11 not -- including the 2026-07-03 D116/D117 supersessions, whose victims (D49, D44) got nothing. The practice is ad hoc human memory; no check in `scripts/checks/**` touches supersession (confirmed absent). Verdict: uncontrolled; DPI-01 specifies the invariant (parse supersedes/amends edges; fail unless the victim block names the superseder; waiver file for human-ruled non-binding clause edges).

## Findings (severity-ordered)

- **DPI-01 (high, novel):** No mechanical supersession-annotation invariant; spec provided (check, inputs, acceptance). Highest-leverage change -- it stops the corpse pile from regrowing and the point-fix treadmill (rec-2057/2058/2059/917/918) from being the only remedy.
- **DPI-02 (high, planned-insufficient):** The 11-victim annotation backfill, with per-entry killing events; includes fixing the two out-of-file stale citations (ROADMAP-PLATFORM.yaml:7819 -> D58, ROADMAP-PRODUCT.md:755 -> D40).
- **DPI-03 (medium, planned-insufficient):** Rewrite the 8 non-canonical Warehouse ID lines, add the missing modern-band lines (bundle rec-2278).
- **DPI-05 (medium, novel):** Adjudicate duplicate Decision 26 (live pending-review vs archived Decided); rec-1964's duplicate-72 no longer reproduces and should be reviewed for closure.
- **DPI-04 (medium, novel):** Reconcile the archival policy (PROJECT_CONTEXT.md:18 + the stale "# Open Decisions" H1) with Decision-84-era practice; 8 recommended archive moves; resolve D26/D40/D49/D55/D70 statuses.
- **DPI-06 (medium, novel):** Duplicate-number detection + backfill reconcile-report spec.
- **DPI-07 (low, novel):** Normalize the archive's h3 Decision 52/53/54 headers (or align the two parsers' grammars).

## Maturity: solid

0 critical, 2 high -> not *strong* (needs <=1 high); the two Q5 `missed` properties independently foreclose *frontier*. The gap to *strong* is exactly DPI-01+DPI-02: land the invariant and the backfill and the surface re-rates. What keeps this file *solid* rather than *nascent* is real: the post-75 band is disciplined (number-keyed warehouse identity, superseders naming targets, dated inline corrections, written renumbering provenance), immutability is respected everywhere, and the ETL's number-keying makes the scariest-looking drift (the dec-081 double-claim) display-layer rather than data-layer.

## Dedup posture

All eight prompt-named point-fix recs confirmed open in the cache; none re-filed as novel. DPI-02/DPI-03 are classified planned-insufficient against them (the audit's contribution is the sweep + the control, not the instances). Deliberate constraints honored: no opinion on the DuckLake backend, the CD-side pointers (Decision 105), the file's prose format, pending-CD validity, sequencing, or decision-scout.
