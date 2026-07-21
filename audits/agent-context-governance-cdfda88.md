# Agent Context Governance Audit (cdfda88)

Companion to `audits/agent-context-governance-cdfda88.yaml` (authoritative on any mismatch).

## Verdict

The instruction-prose surfaces are well-ARCHITECTED and un-GOVERNED: layer discipline, subagent
offload, and right-time loading are genuinely strong, but every live prose surface can grow
unmeasured and unbounded -- and this is a regression, not an oversight. Decision 43 ratified prose
line-budgets and rec-432/rec-433 were filed to enforce them, but both are stranded on the
`.github/` surfaces deleted at T-1.13, and the one prose-cost metric that existed (preflight
`token_anomalies`) was removed with "no replacement" while `planning/SKILL.md:43` still tells
agents to react to it. Six findings survived (1 high, 5 medium); two candidates were dismissed as
correct-by-design.

## Per-surface maturity

| Surface | Maturity | One-line basis |
|---|---|---|
| S1 root AGENTS.md | strong | 1 high (ACG-01, shared) + drift instance (ACG-03); pointer-invariant root and on-demand discipline are real strengths |
| S2 per-dir CLAUDE.md | strong | Same shared high; conditional-ambient trigger is the right shape; terraform/ carries decision-history bleed |
| S3 slash commands | strong | Same shared high only; thinnest, best-disciplined class |
| S4 skills | strong | Shared high + bleed (ACG-03) + latent frontmatter (ACG-02); the offload architecture here is the repo's showpiece |
| S5 JIT primitives | frontier | Count-derived (one medium); note VD5 rates weak -- `required-context` is latent and its sole parser is broken per open rec-568 |
| S6 governance pattern | strong | The pattern (consumer-sized ceilings, raise markers) is proven where applied; coverage, not design, is the gap |
| S7 roadmap end-state | strong | Q5 checklist: 1 met, 5 partial, 2 missed (no prose metering, no unused-context detection); frontier gate fails on the missed properties |
| S8 PROJECT_CONTEXT.md | strong | Shared high + ancestral "Context budget" stanza (ACG-04); its End-State sha-fingerprint check is the repo's one live prose-freshness mechanism |

## Q1 recommendation (both horizons)

Mirror `config/sloc_budgets.yaml` for prose -- one registry, one `validate.py` check (both tiers),
ratchet-down free, raises loud via an inline `# raise-approved: dec-NNN` marker. Units and
granularity are chosen to defeat the transfer hazard (whole-file loading makes naive per-file caps
gameable by splitting into co-loading files):

- **S1 (present + aws-native): byte-budget GATE on the resolved root ambient load-set** -- root
  `CLAUDE.md` plus transitive `@`-imports, i.e. `AGENTS.md` today. The load-set, not the file, is
  the unit; splitting cannot game it.
- **S2 (both): per-file gate** (each per-directory `CLAUDE.md` is its own conditional-ambient
  load-set; resolve imports anyway to stay split-proof).
- **S3 (present): measure only.** Smallest class, strongest discipline; gate only if the trend
  turns. No change needed at the aws-native horizon.
- **S4 (both): per-SKILL.md-entry-file gate.** Robust to the hazard because the sanctioned
  decompose-response genuinely defers cost: move deep/conditional sections to on-demand auxiliary
  files (harness-native progressive disclosure -- used by zero skills today), contracts, or a
  subagent. Aux files stay uncapped so the budget pushes content toward on-demand loading, not
  deletion. The implement skill runs on a sonnet pin -- Decision 128's model-portability rationale
  verbatim.
- **S8 (both): consumer-sized per-file gate**, the Decision 134 pattern exactly: `/plan`,
  `/implement`, `/audit`, and plan-critique full-read it, so the ceiling is sized to that read,
  with relief valves (extract to contracts per Decision 86; retire dead gotchas).

Numeric ceiling values are deliberately not proposed (human disposition); seeding at current sizes
(the Decision 102 precedent) makes the gate a ratchet-plus-loud-raise from day one. Prompt caching
(Q6v) lowers the price of stable ambient prose, not its window occupancy or comprehension load --
and `AGENTS.md` changed 4 times in the 5-day observable history window, so "stable" is weaker than
it looks. Budgets stay byte-denominated; the metric should report stable-vs-churning bytes.

## Highest-leverage change and top findings

**ACG-01 (high, planned-insufficient) is the highest-leverage change**: one registry + one check
generalizes an already-proven mechanism to the only ungoverned infrastructure class, and re-points
or closes the stranded rec-432/rec-433 in the same stroke. It is safe to queue now -- no
dependency on measurement.

- **ACG-05 (medium)**: no prose-context measurement exists anywhere; the metric that existed was
  removed as telemetry-rework collateral. Rescope T3.14's snapshot (explicitly code-only today,
  despite its own "agent context is a first-class resource" driver) to enumerate per-surface prose
  fields, and restore a cheap creds-free preflight advisory now.
- **ACG-03 (medium, observed)**: duplicated project-state drifts -- `AGENTS.md` says the DuckLake
  governed deploy channel is "still PENDING (T2.38)" while `src/lambdas/CLAUDE.md` says it "landed
  at T2.38" and the roadmap marks T2.38 complete; decision-scout hardcodes "currently 67" live
  decision headers vs 103 measured; three surfaces state stale DECISIONS.md sizes. Dedupe state to
  one home with pointers; generalize the End-State fingerprint pattern for facts that must stay
  inline.
- **ACG-02 (medium)**: `required-context` is mandated by the contract, enforced by nothing, parsed
  only by a harness the planning skill itself declares broken (rec-568) while `develop-executor`
  still routes to it -- and its declared payloads (full 745KB roadmap, full 398KB decision log)
  contradict the targeted-read discipline the skill bodies mandate. Retire it or rescope it to
  typed load-directives, then enforce what the contract promises.
- **ACG-04 (medium, observed)**: `PROJECT_CONTEXT.md:18`'s "Context budget" rule references files
  that do not exist and an enforcer (`strategic_review`) that was never more than a lookback flag.
  The repo's one ambient statement of context-budget philosophy has itself rotted.
- **ACG-06 (medium, aws-native)**: the end-state names typed verbs for ops data but no
  JIT-context-retrieval verb and no context-accounting owner; decision-scout's Lambda-migration
  contract ("this skill is the migration's stable interface") points at a query verb no roadmap
  item owns. Attach it to T5.4 (or a sibling) at the next bookkeeping pass.

## What was NOT found / dismissed

- **No critical findings.** No surface routinely loads enough wrong-layer context for a
  correctness- or cost-bearing failure to be the expected outcome. Current sizes are moderate
  (~8.3K tokens always-on; ~14K for the largest skill on invocation).
- **C3 dismissed (absence correct by design)**: the missing `UserPromptSubmit` /
  context-injection hook is the right absence -- per-prompt injection is an ambient tax; the need
  is served by the preflight cache, on-invocation loading, and subagent offload. `SessionStart
  additionalContext` remains a viable channel for the ACG-05 digest.
- **C5 dismissed (compensating control property-matched)**: inline Decision/CD citations should
  NOT be stripped. A 20-citation sample found 18-19 of 20 are cheap provenance tags adjacent to an
  inline operative rule; decision bodies are already fetched JIT (decision-scout, rg-targeted
  reads at `/implement` and plan-critique). Stripping ids would break live machinery to save
  almost nothing. Q3: sufficient.
- **The offload architecture needed no findings**: decision-scout's 398KB-confined subagent read,
  plan-critique's targeted projections, the overseer's read-nothing router, and code-review's
  scoped-diff discipline are frontier-grade patterns as built.
- **T3.14's deferral was not flagged** (valid Decision 93 triage); only its code-only scope is
  assessed (ACG-05). The SLOC governance itself was treated as the model to mirror, per the
  prompt's constraints, and all six findings respect Decision 86 (no new standing prose docs --
  every proposed mechanism is machine-parseable and collocated with enforcement).

All grounding-map anchors resolved on re-derivation (`meta.stale_anchors` is empty); preflight ran
clean, so dedup was performed against live caches (`degraded_dedup: false`).
