# Plan

## Intent
Establish the root README.md as the sole permanently-human-facing portal for this repo, replacing its outdated product-era content with an accurate end-state view of the platform control plane, so that any human landing on this repo instantly understands what it is and what it is not.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-readme-platform-portal.md

## Phase
Partial advance on T2.11b (Public-portal artefact authoring). Architecture diagram component of T2.11b is deferred; this plan does NOT claim T2.11b completion.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `README.md` | Modify (full rewrite) | Replace product-era "Hybrid Lakehouse Trading System" content with an accurate, end-state platform portal that is a curated projection of ROADMAP-PLATFORM.yaml and CLAUDE.md per CD.23 |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] README.md opens with a projection disclaimer per CD.23 exit criterion ("this is a projection of [canonical source]")
- [ ] All five North Star principles (NS.1-NS.5) are present verbatim or near-verbatim
- [ ] Platform / product boundary is explicit: "platform repo, not a product repo"; ROADMAP-PRODUCT named as sibling
- [ ] Brief hosted-products section names trading as product #1 and the `project_id` multi-tenancy model; prospective tenants named as prospective only
- [ ] Each platform subsystem carries a `[live]`, `[partial]`, or `[planned]` status tag
- [ ] Documentation model section describes what stays markdown, what migrates, what becomes schema-validated YAML -- using roadmap tier-item IDs (T5.4, T1.11) rather than internal table names, per CD.20
- [ ] All hyperlinks point only to durable targets: `CLAUDE.md`, `AGENTS.md`, `docs/ROADMAP-PLATFORM.yaml`, `docs/ROADMAP-PRODUCT.yaml`, `SECURITY.md`, `src/`, `scripts/`; no links into migration-bound docs (INTENT-*.md, contracts/*.md, DECISIONS.md, SESSION_LOG.md)
- [ ] Autonomous Executor is marked `[partial]` and notes the executor freeze pending CD.17 / T4.2
- [ ] Scheduled Agents is marked `[partial]` and notes the May 2026 Lambda-to-CC-agent migration
- [ ] No internal Athena/DuckLake table names appear in the README (ops_decisions, ops_recommendations, ops_session_log, etc.) per CD.20
- [ ] `bin/venv-python -m scripts.validate --pre` passes

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | static | Projection disclaimer present at top of README | `grep -c "projection" README.md` | Output >= 1 | Add projection disclaimer as first substantive sentence |
| 2 | static | No internal ops table names in README | `grep -E "ops_decisions\|ops_recommendations\|ops_session_log\|ops_priority_queue\|telemetry_" README.md` | No output (exit 1 = pass) | Replace table names with tier-item references (T5.4, etc.) |
| 3 | static | All links point to durable targets only | `grep -oE "\[([^\]]+)\]\(([^)]+)\)" README.md \| grep -vE "(CLAUDE\.md\|AGENTS\.md\|ROADMAP-PLATFORM\.yaml\|ROADMAP-PRODUCT\.yaml\|SECURITY\.md\|src/\|scripts/\|^#\|http)"` | No output (no non-durable links) | Replace offending links with durable targets or remove |
| 4 | static | All five NS principles present | `grep -c "NS\." README.md` | Output >= 5 | Add missing principles from ROADMAP-PLATFORM.yaml:136-152 |
| 5 | static | Platform / product boundary explicit | `grep -qi "platform repo" README.md && grep -qi "ROADMAP-PRODUCT" README.md && echo PASS` | PASS | Add platform/product boundary section |
| 6 | static | Validate passes (markdown, prompt-compliance, format) | `bin/venv-python -m scripts.validate --pre` | Exit 0 | Fix any reported lint/format issues |

## Constraints
- No inline em dashes; use plain ASCII hyphens (AGENTS.md style rule)
- No emojis (AGENTS.md)
- README declares itself a projection, never a source of truth (CD.23)
- No internal table names in portal files (CD.20)
- Executor freeze is active -- executor subsystem must be marked accordingly (AGENTS.md Temporary Operational Constraints)
- Scheduled agents disabled May 2026 (AGENTS.md Operational Runbooks)
- T2.11b architecture diagram is deferred; acceptance criteria must not claim T2.11b completion

## Context
- CD.23: The human portal is a curated projection of agent-first canonical content, not a parallel source of truth. Each portal file must state "this is a projection of [canonical source]" at the top.
- CD.20: Public surface is README.md, AGENTS.md, EVALUATION-PROMPTS.yaml, SECURITY.md. No references to internal ops/telemetry table names.
- CD.13: ROADMAP-PLATFORM.yaml is the agent-first documentation exemplar; narrative markdown is the legacy pattern being retired. README is a scoped exception.
- KG.1: Platform roadmap is product-agnostic; platform / product boundary is the KG.1 load-bearing gap; Decision 78 uses this boundary to separate DuckLake (platform ops) from Iceberg (product/market-data).
- T2.11b: Partial advance only -- architecture diagram exit criterion deferred.
- T5.4: DECISIONS.md retirement to governed lakehouse is roadmap-future-state (depends on T1.5); documentation model section describes it as such.
- T1.11: PLAN-*.md to PLAN-*.yaml migration. CD.22 scope explicitly exempts README.md, CLAUDE.md, AGENTS.md -- these stay markdown.
- Decision 76: Claude Code on the web harness branch model; /plan and /implement entry points are .claude/commands/ canonical.
- Decision 77: Two-axis environment taxonomy (platform sandbox/SIT/PROD vs product phases).
- Decision 78: DuckLake for ops/telemetry; Iceberg for product/market-data. Platform/product data-format split.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] AGENTS.md read (executor freeze state, scheduled agent status, style rules)
- [ ] ROADMAP-PLATFORM.yaml NS.1-NS.5 block (lines 136-152) located and readable
- [ ] CD.23 (lines 646-664) located for projection disclaimer exact wording
- [ ] CD.20 (lines ~646) no-internal-table constraint confirmed
- [ ] T2.11b exit criteria located (partial advance scope confirmed)
- [ ] All files in Scope table located and readable

## Ordered Execution Steps

1. **Read pre-implementation context** -- Read AGENTS.md (executor freeze status, scheduled-agent runbook, style rules). Read ROADMAP-PLATFORM.yaml lines 136-152 (NS.1-NS.5), lines 646-664 (CD.23 projection disclaimer exact wording), and T2.11b exit criteria. Read docs/PROJECT_CONTEXT.md (North Star statement, platform subsystem inventory).

2. **Rewrite README.md** in this exact section order:
   a. **Title + projection disclaimer** (2-3 lines) -- "agent-platform" as repo name; declaration that this file is a curated projection of `ROADMAP-PLATFORM.yaml` and `CLAUDE.md`, which are the canonical sources.
   b. **North Star** -- five principles NS.1-NS.5 verbatim, rendered as a table or short bullet list.
   c. **What this repo is** -- platform substrate and control plane. NOT the trading product. Sibling to `docs/ROADMAP-PRODUCT.yaml`, not parent. One short paragraph.
   d. **Hosted products** -- trading system as product #1; `project_id` multi-tenancy model (one operational data plane, products distinguished by column not by separate stores); prospective tenants (reaper-tools, dbt-daywork) explicitly marked prospective + unbuilt; IP-separation axis (cross-employer code stays in external repo). Short section (~6 sentences).
   e. **Platform subsystems** -- two-column table (Subsystem | Status + one-line description). Status tags: `[live]`, `[partial]`, `[planned]`. Subsystems to include (minimum):
      - Recommendation + Decision Governance [live]
      - CI / OIDC [live]
      - Instruction Architecture (5-layer) [live]
      - Environment Taxonomy [live]
      - Autonomous Executor [partial] -- note executor freeze pending CD.17 / T4.2
      - Scheduled Agents [partial] -- note Lambda disabled May 2026, migrating to CC scheduled-agent model
      - Lambda Tooling Platform [planned -- T0.7+]
      - DuckLake Lakehouse [planned -- T2.12+]
      - Verification / Validation Kernel [planned -- T3.1+]
   f. **Documentation model** -- three-column table (Content type | Current form | End-state). Use roadmap tier-item IDs (T5.4, T1.11, T5.5), NOT internal table names. Cover: agent-instruction files (CLAUDE.md/AGENTS.md), operational decisions + session logs + recs (migrating to governed lakehouse per T5.4/T1.9), plans (migrating to schema-validated YAML per T1.11), briefing docs / INTENT-* (demoted non-authoritative per T5.5), human portal files (README/AGENTS/SECURITY remain markdown per CD.20/CD.23).
   g. **Repo layout** -- condensed directory table (top-level dirs + one-line purpose; omit transient build/log dirs).
   h. **Agent workflow entry points** -- two short bullets: `/plan` (.claude/commands/plan.md, Opus, harness branch) and `/implement` (.claude/commands/implement.md, executes PLAN-*.md on harness branch). Note: slash commands are the canonical interactive entry points; all other workflows load from skills on demand.
   i. **Links** -- "Canonical sources" section with links only to: CLAUDE.md, AGENTS.md, docs/ROADMAP-PLATFORM.yaml, docs/ROADMAP-PRODUCT.yaml, SECURITY.md. No other external links except ROADMAP files and these five.

3. **Run Verification Plan steps 1-5** (static grep checks). Fix any failures inline.

4. **Run Verification Plan step 6** (`bin/venv-python -m scripts.validate --pre`). Fix any failures.

5. **Execute Verification Plan** -- run each step. Loop until all pass. If any step is unrecoverable, stop and analyze root cause (Decision 55).

6. Report: what was implemented, verification results.
