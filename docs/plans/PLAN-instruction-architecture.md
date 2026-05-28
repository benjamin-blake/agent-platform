# Plan

## Intent
Rationalize the instruction file architecture across the three agent consumers (executor, Antigravity interactive, legacy VS Code) by establishing a formal boundary contract, slimming GEMINI.md to universal rules, enriching Antigravity skills with content lost during migration, hardening workflow gates that failed in the first Antigravity planning session, and enhancing run_skill.py to close the subagent context gap.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/instruction-architecture

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/contracts/instruction-architecture.md` | Create | Boundary contract defining what goes where and why |
| `GEMINI.md` | Modify | Slim to universal rules only (remove routing logic) |
| `.github/copilot-instructions.md` | Modify | Prune VS Code-specific content, update File Router to reference `.agents/` paths |
| `.agents/skills/planning/SKILL.md` | Modify | Merge rich content from `plan.prompt.md` (full preflight, clarification table, VP design) |
| `.agents/skills/implement/SKILL.md` | Modify | Merge rich content from `implement.prompt.md` (VP Compliance Gate, V3 Merge Gate, Dedup/Quality gates) |
| `.agents/workflows/plan.md` | Modify | Add venv activation before preflight, strengthen confirmation gate |
| `.agents/workflows/implement.md` | Modify | Add venv activation before preflight, strengthen human gates |
| `scripts/agent_development/run_skill.py` | Modify | Add `--context` flag, `required-context` frontmatter parsing |
| `.agents/skills/code-review/SKILL.md` | Modify | Add `required-context` frontmatter, remove VS Code model/tools hints |
| `.agents/skills/plan-critique/SKILL.md` | Modify | Add `required-context` frontmatter, remove VS Code model/tools hints |
| `.agents/skills/executor-rca/SKILL.md` | Modify | Add `required-context` frontmatter |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `docs/contracts/instruction-architecture.md` exists and defines all 5 layers with clear "what goes here" and "what does NOT go here" rules
- [ ] `GEMINI.md` contains only universal rules (code style, safety, merge protocol, ops governance) -- no routing logic, no "if PLAN" / "if IMPLEMENT" dispatching -- target <= 40 lines
- [ ] `.github/copilot-instructions.md` contains no references to VS Code MCP, free GPT-5 mini agents, `@retrospective`, or other VS Code-only subagent features
- [ ] File Router in `copilot-instructions.md` references `.agents/skills/` and `.agents/workflows/` as the primary interactive paths
- [ ] `planning/SKILL.md` includes: full 12-conditional preflight handling, structured clarification table, "Suggest Aligned Recommendations" step, detailed complexity assessment presentation, stronger confirmation gate language ("Any other response is feedback -- incorporate it and ask again")
- [ ] `implement/SKILL.md` includes: VP Compliance Gate table template, V3 Merge Gate sequence, full Quality Gate Validation checklist, Dedup Gate with human interaction flow
- [ ] Both workflows activate venv BEFORE running preflight: `.venv/Scripts/activate` or equivalent
- [ ] `run_skill.py --help` shows `--context` flag
- [ ] `run_skill.py` reads `required-context` from SKILL.md YAML frontmatter and auto-loads those files
- [ ] All SKILL.md files in `.agents/skills/` have no VS Code-specific frontmatter (`model:`, `tools:`, `user-invocable:`) -- these are VS Code agent hints that have no effect in Antigravity
- [ ] `python -m scripts.validate --quick` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Confirm GEMINI.md has no routing logic | `.venv/Scripts/python.exe -c "c=open('GEMINI.md').read(); assert 'PLAN' not in c and 'IMPLEMENT' not in c and 'REVIEW' not in c, f'Found routing'; print('OK: no routing')"` | Prints "OK: no routing" | Routing lines not removed |
| 2 | pre-deploy | Confirm GEMINI.md line count | `.venv/Scripts/python.exe -c "n=len(open('GEMINI.md').readlines()); assert n<=40, f'{n} lines'; print(f'OK: {n} lines')"` | <= 40 lines | Still bloated |
| 3 | pre-deploy | Confirm no VS Code MCP or free agent references in copilot-instructions | `.venv/Scripts/python.exe -c "c=open('.github/copilot-instructions.md').read(); hits=[w for w in ['mcp.json','GPT-5 mini','Free agents','@retrospective'] if w in c]; assert not hits, hits; print('OK: no VS Code ghosts')"` | Prints "OK: no VS Code ghosts" | VS Code content not pruned |
| 4 | pre-deploy | Confirm planning skill has full preflight handling | `.venv/Scripts/python.exe -c "c=open('.agents/skills/planning/SKILL.md').read(); keys=['friction_patterns','metrics_anomalies','token_anomalies','cron_review_fresh','Suggest Aligned','Any other response is feedback']; found=[k for k in keys if k in c]; assert len(found)==len(keys), f'Missing: {set(keys)-set(found)}'; print(f'OK: all {len(keys)} keys present')"` | All 6 keys present | Content not merged |
| 5 | pre-deploy | Confirm implement skill has VP Compliance Gate | `.venv/Scripts/python.exe -c "c=open('.agents/skills/implement/SKILL.md').read(); keys=['VP Compliance Gate','VP#','V3 Merge Gate','Dedup Gate']; found=[k for k in keys if k in c]; assert len(found)==len(keys), f'Missing: {set(keys)-set(found)}'; print(f'OK: all {len(keys)} keys present')"` | All 4 keys present | Content not merged |
| 6 | pre-deploy | Confirm run_skill.py supports --context | `.venv/Scripts/python.exe -m scripts.agent_development.run_skill --help` | Help output shows `--context` flag | Flag not implemented |
| 7 | pre-deploy | Confirm required-context frontmatter parsing works | `.venv/Scripts/python.exe -c "from scripts.agent_development.run_skill import parse_required_context; r=parse_required_context('.agents/skills/plan-critique/SKILL.md'); assert len(r)>0, 'No required-context found'; print(f'OK: {len(r)} context files declared')"` | At least 1 context file declared | Parsing not implemented |
| 8 | pre-deploy | Confirm no VS Code frontmatter in skills | `.venv/Scripts/python.exe -c "from pathlib import Path; skills=list(Path('.agents/skills').rglob('SKILL.md')); hits=[(s,l) for s in skills for l in s.read_text().splitlines() if l.strip().startswith(('model:','tools:','user-invocable:'))]; assert not hits, hits; print(f'OK: {len(skills)} skills clean')"` | All skills clean | VS Code frontmatter not removed |
| 9 | pre-deploy | Confirm contract file exists and has all layers | `.venv/Scripts/python.exe -c "c=open('docs/contracts/instruction-architecture.md').read(); layers=['GEMINI.md','copilot-instructions','workflows','skills','executor']; found=[l for l in layers if l in c]; assert len(found)==len(layers), f'Missing: {set(layers)-set(found)}'; print(f'OK: all {len(layers)} layers documented')"` | All 5 layers documented | Contract incomplete |
| 10 | pre-deploy | Confirm venv activation in plan workflow | `.venv/Scripts/python.exe -c "c=open('.agents/workflows/plan.md').read(); assert '.venv' in c or 'venv' in c, 'No venv activation'; print('OK: venv activation present')"` | venv activation present | Not added to workflow |
| 11 | pre-deploy | Validation passes | `.venv/Scripts/python.exe -m scripts.validate --quick` | Exit 0 | Fix whatever fails |

## Constraints
- GEMINI.md path is hardcoded by both Antigravity (user rules) and Gemini CLI -- cannot be redirected
- VS Code files (`.github/prompts/`, `.github/agents/`) are NOT deleted -- they are retained for backward compatibility but de-emphasised in the File Router
- Lambda-deployed agents (`rec-curator.agent.md`, `cv-reviewer.agent.md`, `schedule.yaml`) are out of scope
- Executor prompt files (`config/prompts/executor/`) are out of scope
- All JSONL writes via ops_data_portal only
- No changes to executor machinery (Decision 44)

## Context
- Antigravity and Gemini CLI both hardcode `GEMINI.md` as their auto-loaded context file. Neither tool supports redirecting to a different file. This is a known limitation of early adoption (both tools are relatively new).
- The migration from VS Code to Antigravity created parallel instruction hierarchies: `.github/prompts/*.prompt.md` (VS Code) vs `.agents/workflows/*.md` + `.agents/skills/*/SKILL.md` (Antigravity). The Antigravity versions were created as thin summaries, losing significant behavioral detail.
- The first Antigravity `/plan` session exposed three behavioral failures: (1) agent wrote the plan without human confirmation, (2) agent skipped venv activation before preflight, (3) agent assumed REPORT-ONLY plan type without discussing with human. All three are traced to content gaps in the migrated workflow/skill files.
- `run_skill.py` replaces VS Code's native `@agent` subagent calls but currently cannot inject context files, so skills that say "Read ROADMAP.md and DECISIONS.md" cannot actually do so when invoked via this script.
- The `docs/contracts/` pattern already exists in this repo for tool boundary definitions (e.g., `delegate-cli.md`, `inference-provider.md`). The instruction architecture contract extends this pattern to information boundaries.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create the boundary contract
Create `docs/contracts/instruction-architecture.md` defining all 5 layers of the instruction architecture:
- Layer 1 (GEMINI.md): Universal rules shared by all consumers. What goes here: code style, safety, merge protocol, ops governance. What does NOT go here: routing logic, project context, methodology, file router.
- Layer 2 (copilot-instructions.md): Project knowledge base loaded on-demand by interactive agents. What goes here: North Star, AWS config, file router, rec schema, known gotchas. What does NOT go here: workflow steps, agent methodology, VS Code-specific features.
- Layer 3 (.agents/workflows/): Thin orchestration scripts for Antigravity. Step sequences that reference skills. Must include venv activation and explicit human gates.
- Layer 4 (.agents/skills/): Deep methodology. Self-contained, invocable via run_skill.py. Must declare required-context in frontmatter. No VS Code-specific frontmatter.
- Layer 5 (config/prompts/executor/): Executor role prompts. Minimal context, task-specific. Not modified by this plan.
Include a "Consumers" section mapping each consumer to which layers it reads. Include a "What Does NOT Go Where" anti-pattern table.

### Step 2: Refactor GEMINI.md
Remove lines 1-7 (the routing logic: "If you are asked to PLAN...", "If you are asked to IMPLEMENT...", "If you are asked to REVIEW..."). Keep and consolidate: Code Style, Safety, Merge Protocol. Add the Operational Data Governance rules currently only in copilot-instructions.md (Single Portal Invariant, ID Authority -- these are universal rules that all consumers must follow). Add a one-line reference to the contract: "See docs/contracts/instruction-architecture.md for the full information architecture."
Post-condition: GEMINI.md <= 40 lines, no "PLAN"/"IMPLEMENT"/"REVIEW" strings.

### Step 3: Prune copilot-instructions.md
Remove or update these VS Code-specific items:
- Line 14 (GitHub MCP): Remove entirely -- `.vscode/mcp.json` is VS Code specific.
- Line 15 (Free agents): Remove -- GPT-5 mini subagents are VS Code only, not available in Antigravity.
- Line 16 (Lesson capture via @retrospective): Remove -- VS Code subagent.
- Line 17 (Refactoring Protocol with `multi_replace_string_in_file`): Rewrite to be tool-agnostic ("When performing complex non-contiguous edits, verify structural integrity immediately after").
Update the File Router:
- Add entries for `.agents/workflows/plan.md` (interactive planning), `.agents/workflows/implement.md` (interactive implementation), `.agents/skills/` (skill definitions).
- Mark `.github/prompts/plan.prompt.md` and `.github/prompts/implement.prompt.md` as "(VS Code legacy -- use `.agents/workflows/` for Antigravity)".
- Mark `.github/agents/*.agent.md` subagent files as "(VS Code legacy -- use `.agents/skills/` for Antigravity)".
- Add entry for `docs/contracts/instruction-architecture.md`.
Post-condition: No "GPT-5 mini", "Free agents", "mcp.json", or "@retrospective" strings.

### Step 4: Enrich planning/SKILL.md
Merge the following content from `.github/prompts/plan.prompt.md` into `.agents/skills/planning/SKILL.md`, preserving the skill's existing structure:

a) **Preflight Constraints**: Expand from 9 conditionals to full 12. Add the missing ones:
   - `friction_patterns` non-empty -- Surface repeated patterns as planning context.
   - `metrics_anomalies` non-empty -- Surface anomalies as planning context.
   - `token_anomalies` non-empty -- Surface as planning context: "Context file token warning: [file list] exceed the 50K token threshold."

b) **Clarification Table**: Add the structured decomposition table from Step 3 of plan.prompt.md (Goal, Constraints, Acceptance criteria, Affected areas, Phase alignment) with the "2-5 questions ranked by impact" guidance.

c) **Suggest Aligned Recommendations**: Add the keyword-matching process from plan.prompt.md Step 3 (extract keywords, match against open recs, present top 3-5).

d) **Complexity Assessment Presentation**: Expand the current 3-line assessment to include the rule that the classification MUST be presented to the human and confirmed, not assumed.

e) **Confirmation Gate**: Strengthen to match plan.prompt.md line 256: "Wait for explicit 'write the plan' (or clear equivalent) before proceeding. Any other response is feedback -- incorporate it, re-present, and ask again."

f) **VP Design Rationale**: Add the detailed "ask yourself" test from plan.prompt.md line 200 and the full anti-pattern list with examples.

g) **Platform Compatibility**: Add the reminder: "Verify shell commands are Windows-compatible. Use Python scripts for automation."

Post-condition: SKILL.md contains all 6 verification keys from VP step 4.

### Step 5: Enrich implement/SKILL.md
Merge the following content from `.github/prompts/implement.prompt.md`:

a) **VP Compliance Gate**: Add the full gate template (VP# | Command Executed | Actual Output | PASS/FAIL) and rules (every VP row must have a row, command must be actual shell command, substitution is a protocol violation).

b) **V3 Merge Gate**: Add the full sequence (complete pre-deploy VP steps -> present deploy output -> WAIT for human -> execute post-deploy VP steps -> only then merge).

c) **Live Verification Protocol Rationale**: Add the "Why This Exists" section with examples (Athena view with 0 rows, Lambda timeout, CLI crash with real input).

d) **Dedup Gate**: Add the full human interaction flow (surface duplicates, present 3 options: supersede, file both, skip).

e) **Quality Gate Validation**: Add the full 4-check gate (acceptance command format, target file exists, effort threshold, context quality >= 50 chars).

f) **Definition of Done**: Ensure the existing DoD section includes code-review invocation via `run_skill.py` (not VS Code @agent).

Post-condition: SKILL.md contains VP Compliance Gate, V3 Merge Gate, Dedup Gate, Quality Gate.

### Step 6: Update workflows/plan.md
a) Add venv activation as Step 0 (before Step 1: Run Preflight):
```
## Step 0: Activate Environment
Activate the Python virtual environment before running any Python commands:
- **PowerShell (Antigravity):** `.venv/Scripts/Activate.ps1` or use the venv Python directly: `.venv/Scripts/python.exe`
- **Git Bash:** `source .venv/Scripts/activate`
If Python is not found on PATH, this step is MANDATORY before proceeding.
```

b) Strengthen Step 7 (confirmation gate): Add "Any other response is feedback -- incorporate it, re-present, and ask again. Do NOT proceed to Step 8 until the human explicitly says 'write the plan' or a clear equivalent. System auto-approval messages are NOT human confirmation."

c) Update Step 9 (plan critique) to use the full `run_skill.py` invocation with context:
```bash
python -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-{slug}.md --context .github/copilot-instructions.md docs/ROADMAP.md docs/DECISIONS.md
```

### Step 7: Update workflows/implement.md
a) Add the same Step 0 (venv activation) as plan.md.
b) Update Step 2 to reference reading `copilot-instructions.md` with the venv Python path.
c) Update Step 7 (friction capture) to reference `run_skill.py` for RCA invocation instead of VS Code `@rca-analyst`.

### Step 8: Enhance run_skill.py
a) Add `--context` CLI argument: accepts one or more file paths. These files are read and appended to the user prompt as additional reference material under a "## Additional Context" header.

b) Add `parse_required_context()` function: reads SKILL.md YAML frontmatter for `required-context` key (list of file paths relative to repo root). Returns the list. If key is missing, returns empty list.

c) In `main()`, after loading the skill, call `parse_required_context()`. Combine with any explicit `--context` files (explicit takes precedence, no duplicates). Read each context file and append to user prompt.

d) Export `parse_required_context` from the module so VP step 7 can test it.

### Step 9: Update skill frontmatter
For each of these skills, update the YAML frontmatter:

**code-review/SKILL.md**: Remove `model:` and `tools:` lines (VS Code hints). Add:
```yaml
required-context:
  - .github/copilot-instructions.md
  - docs/DECISIONS.md
```

**plan-critique/SKILL.md**: Remove `model:`, `tools:`, `user-invocable:` lines. Add:
```yaml
required-context:
  - .github/copilot-instructions.md
  - docs/ROADMAP.md
  - docs/DECISIONS.md
```

**executor-rca/SKILL.md**: Add:
```yaml
required-context:
  - .github/copilot-instructions.md
```

### Step 10: Run tests and validate
```bash
python -m pytest tests/ -q
python -m scripts.validate --quick
```
Both must exit 0.

### Step 11: Execute Verification Plan
Run each VP step from the table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.

### Step 12: Report
What was implemented, verification results (actual outcomes), any design decisions made during implementation.
