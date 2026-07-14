# Plan

## Intent
Split the monolithic ARCHITECTURE.md (1907 lines, ~14K tokens) into two focused documents -- one for the trading system design and one for the development workflow -- reflecting 4 months of architectural changes and reducing agent context loading by letting each consumer load only the relevant document.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Branch
agent/platform-architecture-split

## Phase
Phase Platform (Wave 5: Repo Consolidation)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/ARCHITECTURE.md | Modify | Rewrite as trading-system-only architecture with TOC in first 80 lines |
| docs/ARCHITECTURE-WORKFLOW.md | Create | New workflow/development architecture doc with TOC, telemetry, executor, OpsWriter, LLM providers |
| .github/copilot-instructions.md | Modify | Split File Router "Architecture / data flow" into two rows |
| .github/agents/code-review.agent.md | Modify | Add ARCHITECTURE-WORKFLOW.md to the "read all documentation" list |
| .github/agents/retrospective.agent.md | Modify | Update references to point to correct document per context |
| .github/prompts/documentation_update.prompt.md | Modify | Update ARCHITECTURE.md references and add ARCHITECTURE-WORKFLOW.md |
| .github/prompts/scheduled/doc-freshness.prompt.md | Modify | Add ARCHITECTURE-WORKFLOW.md mapping |
| .github/prompts/strategic_review.prompt.md | Modify | Update architecture drift section to reference both docs |
| docs/AGENT_WORKFLOW.md | Modify | Update reference to include both docs |
| docs/GETTING_STARTED.md | Modify | Update 3 references to describe both docs |
| docs/ROADMAP.md | Modify | Update ARCHITECTURE.md reference in Phase 3 deliverable |
| README.md | Modify | Update 2 references in tree diagram and links section |
| .agents/skills/code-review/SKILL.md | Modify | Add ARCHITECTURE-WORKFLOW.md to "Read all documentation" list |
| .antigravity/workflows/documentation_update.md | Modify | Update ARCHITECTURE.md references and add ARCHITECTURE-WORKFLOW.md |

## Bundled Recommendations
- **rec-229**: "ARCHITECTURE.md streaming note conflicts with weekly encoder retraining" -- fix the Future Enhancements streaming entry to note inference-only mode requirement.

## Acceptance Criteria
- [ ] `docs/ARCHITECTURE.md` contains only trading system content (no workflow/CI/telemetry/executor sections)
- [ ] `docs/ARCHITECTURE-WORKFLOW.md` exists and covers: workflow loop, CI/CD, telemetry star schema, executor package, OpsWriter, LLM providers, repo patterns
- [ ] Both documents have a table of contents index within the first 80 lines
- [ ] Zero references to deleted files: `session_close.prompt.md`, `pre-commit-sanity.agent.md`, `cron_review.prompt.md`, `run_retro_lite.py`, `friction_analysis.py`, `metrics_analysis.py`
- [ ] Zero references to `.retro-lite-log.jsonl` as an active feedback mechanism (may be referenced as historical/deprecated)
- [ ] Telemetry section describes the 7-table Iceberg star schema (not the legacy JSONL approach)
- [ ] Executor section documents the 12-submodule package structure
- [ ] LLM provider section documents current state: Gemini CLI (executor), Copilot SDK (Lambda scheduled agents), Bedrock (dormant)
- [ ] OpsWriter/outbox pattern documented
- [ ] rec-229 resolved: streaming enhancement entry includes inference-only mode note
- [ ] All 12 Scope files updated -- no stale references to single ARCHITECTURE.md where context requires the workflow doc
- [ ] `grep -r "ARCHITECTURE" .github/ docs/ .agents/ .antigravity/ README.md GEMINI.md --include="*.md" | grep -v ARCHIVE | grep -v plans/ | grep -v CHANGELOG` returns only correct references
- [ ] `python -m scripts.validate` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Verify ARCHITECTURE.md has no workflow/CI sections | `python -c "t=open('docs/ARCHITECTURE.md').read(); assert 'CI/CD Strategy' not in t; assert 'Workflow Loop' not in t; assert 'session_close.prompt' not in t; assert 'pre-commit-sanity' not in t; assert 'retro-lite-log' not in t; print('PASS: no workflow content in trading doc')"` | Prints "PASS" | Trading doc still contains workflow sections -- move them to workflow doc |
| 2 | pre-deploy | Verify ARCHITECTURE-WORKFLOW.md has telemetry star schema | `python -c "t=open('docs/ARCHITECTURE-WORKFLOW.md').read(); assert 'telemetry_sessions' in t; assert 'telemetry_phases' in t; assert 'telemetry_model_calls' in t; assert 'OpsWriter' in t; assert 'Gemini CLI' in t; print('PASS: workflow doc has required sections')"` | Prints "PASS" | Missing sections -- add telemetry/executor/LLM content |
| 3 | pre-deploy | Verify no dead file references in either doc | `python -c "import re; dead=['session_close.prompt','pre-commit-sanity.agent','cron_review.prompt','run_retro_lite','friction_analysis.py','metrics_analysis.py']; errs=[]; [errs.extend([(d,f) for d in dead if d in open(f).read()]) for f in ['docs/ARCHITECTURE.md','docs/ARCHITECTURE-WORKFLOW.md']]; assert not errs, f'Dead refs: {errs}'; print('PASS: no dead references')"` | Prints "PASS" | Dead references remain -- remove them |
| 4 | pre-deploy | Verify both docs have TOC in first 80 lines | `python -c "for f in ['docs/ARCHITECTURE.md','docs/ARCHITECTURE-WORKFLOW.md']: lines=open(f).readlines()[:80]; toc=''.join(lines); assert '##' in toc and toc.count('[') >= 5, f'{f} missing TOC'; print(f'PASS: {f} has TOC')"` | Both print "PASS" | Add table of contents section |
| 5 | pre-deploy | Verify all downstream references are updated | `python -c "import subprocess; r=subprocess.run(['grep','-r','ARCHITECTURE','.github/','docs/','.agents/','.antigravity/','README.md','--include=*.md'],capture_output=True,text=True); lines=[l for l in r.stdout.splitlines() if 'ARCHIVE' not in l and 'plans/' not in l and 'CHANGELOG' not in l]; print(f'{len(lines)} references found'); [print(l) for l in lines]"` | All references point to correct document | Fix stale references |
| 6 | pre-deploy | Verify rec-229 streaming fix | `grep -A10 'Streaming' docs/ARCHITECTURE.md \| grep -q 'inference-only'` | Exit 0 | Add inference-only mode note to streaming enhancement |
| 7 | pre-deploy | Full validation passes | `python -m scripts.validate` | Exit 0 | Fix any validation errors |

## Constraints
- No implementation code changes -- documentation only
- Shell commands must be Windows-compatible (Python scripts, no PowerShell)
- copilot-instructions.md File Router is a critical reference used by all agents -- changes must preserve table format
- Both documents must be comprehensive standalone documents (no "see the other doc for X" circular references -- each can reference the other but must be self-contained for its domain)
- INTENT-telemetry-system.md remains the authoritative telemetry spec; ARCHITECTURE-WORKFLOW.md provides a summary with pointer to the INTENT doc

## Context
- Strategic review (April 30, 2026) identified ARCHITECTURE.md as severely drifted with 5+ major undocumented systems
- The document still describes: legacy retro-lite friction system, deleted prompt files, old workflow model
- Missing from current doc: telemetry star schema (7 Iceberg tables), executor package (12 submodules), OpsWriter/outbox pattern, Gemini CLI + Copilot SDK provider split, Bedrock dormancy
- Decisions 52 (Bedrock DeepSeek), 53 (Gemini CLI executor), 54 (Copilot SDK Lambda) are referenced in copilot-instructions.md but not in DECISIONS.md -- document current state in the architecture docs but do not create decision entries (separate task)
- Decision 55 (RCA-first) replaces rescue agent architecture -- workflow doc must reflect this
- The user is migrating from VS Code to Antigravity and from GitHub Copilot CLI to Google ecosystem -- the workflow doc should describe current state accurately without overcommitting to any specific tooling brand
- INTENT-telemetry-system.md (757 lines) is the authoritative telemetry spec; the workflow architecture doc summarises it
- rec-229 (streaming note) is bundled -- XS effort fix in Future Enhancements section

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Read all source material
Read the following files to build a complete mental model before writing:
- `docs/ARCHITECTURE.md` (current, 1907 lines -- will be rewritten)
- `docs/INTENT-telemetry-system.md` (telemetry star schema, 757 lines)
- `docs/INTENT-recommendation-executor.md` (executor architecture)
- `scripts/executor/` directory listing and module docstrings (12 submodules)
- `scripts/ops_writer.py` first 50 lines (OpsWriter interface)
- `scripts/llm_client.py` first 50 lines (LLM provider routing)
- `scripts/model_registry.py` first 50 lines (model resolution)
- `docs/DECISIONS.md` (current, 808 lines -- for Decision 51, 55 references)

### Step 2: Write docs/ARCHITECTURE.md (Trading System)
Rewrite the file using the rename-create-delete pattern (rename to `ARCHITECTURE-old.md`, create new `ARCHITECTURE.md`, delete old).

**Structure (must follow this order):**
1. Title + 1-paragraph purpose statement
2. **Table of Contents** -- linked section index (must fit within first 80 lines)
3. High-Level Architecture -- the dual-environment ASCII diagram (keep, it's accurate)
4. AWS Lakehouse -- S3 multi-bucket, Glue Catalog, Athena, Iceberg tables (keep, update if needed)
5. Market Data Pipeline -- Step Functions diagram, Lambda stack, features list (keep)
6. Formula Lifecycle Management -- state machine, transitions (keep)
7. Lab Module -- PySR formula discovery (keep)
8. Formula Integration -- personal env, pgvector, FormulaRATModel (keep)
9. Live Module -- RAT Ensemble (keep)
10. Execution Module -- async engine, latency penalties (keep)
11. A/B Testing framework (keep)
12. Circuit Breakers (keep)
13. Meta-Learner with Auto-Weighting (keep)
14. Feature Architecture -- three-layer pipeline from Phase 2+ (keep)
15. Sync Service (keep)
16. Data Flow Examples (keep)
17. Deployment Options (keep)
18. Performance Characteristics (keep)
19. Cost Optimization (keep)
20. Authentication & Credentials -- AWS SSO (keep)
21. Security Considerations (keep)
22. Error Handling Patterns (keep)
23. Resilience Patterns (keep)
24. Configuration Management (keep)
25. Monitoring & Observability (keep)
26. Future Enhancements -- **fix rec-229**: add note to Streaming entry: "Streaming integration requires inference-only mode with cached encoder weights, or mini-batch retraining triggered by data drift detection (see Decision 41)."

**Remove from this file** (moved to workflow doc):
- "Workflow Loop: Multi-Model Feedback Gates" section
- "Parallel Workflow Architecture: Branch-Specific Plans" section
- "CI/CD Strategy: Agent-Terminal-First" section
- "Quantitative Session Monitoring" section
- "Infrastructure as Code: Idempotent Terraform Patterns" section
- "Optional Dependencies: Import-Time Guards" section
- "Repository Restructuring and Path Migration Patterns" section

**Add to this file:**
- A "Related Documents" section at the end: pointer to `ARCHITECTURE-WORKFLOW.md` for development workflow, CI/CD, telemetry, and executor infrastructure.

### Step 3: Write docs/ARCHITECTURE-WORKFLOW.md (Development Workflow)
Create a new file.

**Structure (must follow this order):**
1. Title + 1-paragraph purpose statement
2. **Table of Contents** -- linked section index (must fit within first 80 lines)
3. Workflow Loop -- the 2-chat model (rewrite from current ARCHITECTURE.md but update to reflect: retro-lite deprecated, telemetry star schema replaces friction logs, implement prompt now includes session close, Haiku for retrospective in merged context). Remove references to `session_close.prompt.md` and `pre-commit-sanity.agent.md`.
4. Parallel Workflow Architecture -- branch-specific plans, plan file discovery canonical algorithm (move from current doc, keep as-is since it's accurate)
5. CI/CD Strategy -- inner/outer loop, validate.py as single source of truth (move from current doc, keep accurate)
6. Quantitative Session Monitoring -- plan_audit.py, session_metrics.py, north_star_tracker.py (move, keep accurate)
7. **Telemetry System (NEW)** -- summarise the 7-table star schema from INTENT-telemetry-system.md. Include: relationship diagram, table names with 1-line descriptions, write path (outbox -> S3 staging -> Iceberg compaction), pointer to INTENT doc for full column schemas. Do NOT copy the full column definitions -- summarise the grain and key columns for each table.
8. **Executor Architecture (NEW)** -- document the executor package: `scripts/executor/` with its 12 submodules. List each module with 1-line purpose. Describe the execution flow: plan -> critique -> refine -> step_runner -> postflight. Reference Decision 55 (RCA-first, no rescue agents). Reference Decision 43 (500 SLOC limit). Note `execute_recommendation.py` is the orchestrator that delegates to the package.
9. **Ops Data Pipeline (NEW)** -- OpsWriter, outbox pattern (Decision 51), bidirectional sync, ops_recommendations/ops_decisions Iceberg tables, ops_data_portal.py as the write portal. Reference the "Single Portal Invariant" from copilot-instructions.md.
10. **LLM Provider Architecture (NEW)** -- current state: Gemini CLI for executor (Decision 53), Copilot SDK for Lambda scheduled agents (Decision 49), Bedrock dormant (Decision 52). `llm_client.py` as the routing layer, `model_registry.py` for resolution. Note: provider landscape is evolving due to company Copilot cancellation and migration to Google ecosystem.
11. Infrastructure as Code -- Terraform patterns, try() with fallback (move from current doc)
12. Optional Dependencies -- import-time guards with sentinel types (move from current doc)
13. Repository Restructuring Patterns (move from current doc, still relevant as reference)
14. **Related Documents** section: pointer to `ARCHITECTURE.md` for trading system design, `INTENT-telemetry-system.md` for full telemetry schema, `INTENT-recommendation-executor.md` for executor lifecycle.

### Step 4: Update downstream references
Update all files that reference ARCHITECTURE.md to point to the correct document:

**copilot-instructions.md** (line 68): Split single File Router row into two:
```
| Trading system design / data flow | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) |
| Development workflow / CI / telemetry | [docs/ARCHITECTURE-WORKFLOW.md](../docs/ARCHITECTURE-WORKFLOW.md) |
```

**code-review.agent.md** (line 41): Add `docs/ARCHITECTURE-WORKFLOW.md` to the "Read all documentation first" list.

**retrospective.agent.md** (line 148): Change `docs/ARCHITECTURE.md` to `docs/ARCHITECTURE-WORKFLOW.md` (the retrospective updates workflow patterns, not trading system design). Line 232: keep `ARCHITECTURE.md` reference since it's about not putting implementation details in CHANGELOG.

**documentation_update.prompt.md** (line 47, 284): Add `ARCHITECTURE-WORKFLOW.md` alongside existing reference. Line 284: add workflow doc to the "Other docs" list.

**doc-freshness.prompt.md** (line 17): Add mapping for `ARCHITECTURE-WORKFLOW.md` -> `scripts/`, `.github/`. Keep existing `ARCHITECTURE.md` -> `src/`, `terraform/`.

**strategic_review.prompt.md** (line 28, 70, 77): Update references to check both documents.

**AGENT_WORKFLOW.md** (line 162): Add ARCHITECTURE-WORKFLOW.md reference alongside existing.

**GETTING_STARTED.md** (lines 623, 931, 950): Update to describe both docs with distinct descriptions.

**ROADMAP.md** (line 366): Keep ARCHITECTURE.md reference (it's about trading strategy documentation).

**README.md** (lines 304, 360): Update tree diagram and links section to include both docs.

**.agents/skills/code-review/SKILL.md** (line 41): Add `docs/ARCHITECTURE-WORKFLOW.md` to the "Read all documentation first" list (mirrors code-review.agent.md change).

**.antigravity/workflows/documentation_update.md** (lines 47, 284): Update ARCHITECTURE.md references and add ARCHITECTURE-WORKFLOW.md (mirrors documentation_update.prompt.md changes).

### Step 5: Run tests and validation
```bash
python -m scripts.validate
```
Must exit 0. Fix any issues found.

### Step 6: Execute Verification Plan
Run each step from the Verification Plan table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

### Step 7: Report
Report: what was implemented, verification results (actual outcomes), bugs found and fixed.
