# Plan

## Intent
Eliminate the root cause of repeated executor failures (rec-241, rec-244, rec-119) by decomposing rec-251 into automatable sub-recs that any executor agent can implement independently.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-decompose-rec-251

## Phase
Infrastructure / Tooling (no phase dependency)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `logs/.recommendations-log.jsonl` | Modify | Append 6 new sub-recs (rec-252 through rec-257), close rec-251, supersede rec-035 |

## Bundled Recommendations
- rec-251 (parent, being decomposed)
- rec-035 (superseded by this decomposition)

## Acceptance Criteria
- [ ] rec-252 through rec-257 exist in `logs/.recommendations-log.jsonl` with status `open` and correct dependency chains
- [ ] rec-251 status is `closed` with `resolution` citing decomposition into rec-252 through rec-257
- [ ] rec-035 status is `superseded` with `resolution` citing rec-252
- [ ] All 8 JSONL entries are valid JSON (verified by `python -c "..."` one-liner)
- [ ] `python scripts/validate.py` exits 0

## Constraints
- JSONL entries must conform to the schema in `.github/copilot-instructions.md` (Recommendations Log Schema section)
- Status values: only `open`, `closed`, `superseded` -- never `done`, `complete`, `implemented`
- Acceptance commands must be single inline backtick commands, no trailing prose
- Dependencies arrays must reference valid rec IDs

## Context
- rec-251 is Critical/non-automatable because it touches the core CLI invocation path across 9 callsites
- Decomposition strategy: one foundation rec (rec-252), three parallel migration recs (rec-253/254/255), one cleanup rec (rec-256), one follow-up rec (rec-257)
- rec-035 (context injection) is naturally solved by rec-252's workspace-file approach
- rec-119 (prior attempt) failed; rec-249 (workaround) already superseded by rec-251
- See `docs/plans/PLAN-infra-decompose-rec-251.md` Context section for full problem statement and solution architecture

### Callsites Reference (for sub-rec context fields)
| # | Callsite | File | Phase |
|---|----------|------|-------|
| 1 | `generate_initial_plan()` | `scripts/executor/plan.py` | Planning |
| 2 | `critique_plan()` | `scripts/executor/plan.py` | Planning |
| 3 | `refine_plan()` | `scripts/executor/plan.py` | Planning |
| 4 | `implement_step()` | `scripts/executor/step_runner.py` | Implementation |
| 5 | `review_code()` | `scripts/executor/postflight.py` | Post-exec |
| 6 | `_fix_ci_failure()` | `scripts/executor/postflight.py` | Post-exec |
| 7 | `_fix_code_review_findings()` | `scripts/executor/postflight.py` | Post-exec |
| 8 | `_agent_merge_recovery()` | `scripts/executor/postflight.py` | Post-exec |
| 9 | `classify_risk()` | `scripts/classify_risk.py` | Standalone |

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Append rec-252 through rec-257 to JSONL
Append exactly 6 new JSONL entries to `logs/.recommendations-log.jsonl`. Each entry must be a single line of valid JSON. Use the rec schema from `copilot-instructions.md`. The entries are:

**rec-252** -- Add workspace-file invocation mode to copilot_call()
```json
{"id": "rec-252", "date": "2026-04-11", "title": "copilot_call: add workspace-file invocation mode (context_file_path + inline_instruction)", "source": "planning", "effort": "S", "priority": "Critical", "status": "open", "automatable": true, "risk": "low", "file": "scripts/copilot_wrapper.py", "context": "Foundation for rec-251 decomposition. Add two new optional params to copilot_call(): context_file_path (str) and inline_instruction (str). When both set: write prompt body to context_file_path (in logs/debug/, already gitignored, no cleanup), pass inline_instruction via -p (no @ prefix). When neither set, fall back to existing @tempfile. Add helper build_context_path(phase, rec_id, step_n=None) -> str returning logs/debug/{phase}-context-{rec_id}[-step{n}].md. Context files persist for debugging. See PLAN-infra-decompose-rec-251.md for full architecture.", "acceptance": "`python -m pytest tests/test_copilot_wrapper.py -k context_file -v`", "dependencies": [], "tags": ["executor", "copilot-wrapper", "cli-invocation"]}
```

**rec-253** -- Migrate planning callsites to workspace-file mode
```json
{"id": "rec-253", "date": "2026-04-11", "title": "plan.py: migrate generate/critique/refine to workspace-file invocation mode", "source": "planning", "effort": "S", "priority": "Critical", "status": "open", "automatable": true, "risk": "low", "file": "scripts/executor/plan.py", "context": "Migrate 3 planning callsites (generate_initial_plan, critique_plan, refine_plan) to use context_file_path + inline_instruction from rec-252. Context file: logs/debug/plan-context-{rec_id}-{gen|critique|refine}.md. Inline instruction directs model to read context file and produce expected output. Session continuity (resume_session_id) unchanged. See PLAN-infra-decompose-rec-251.md Callsites table rows 1-3.", "acceptance": "`python -m pytest tests/test_executor_plan.py -k context_file -v`", "dependencies": ["rec-252"], "tags": ["executor", "planning", "cli-invocation"]}
```

**rec-254** -- Migrate implement_step() to workspace-file mode
```json
{"id": "rec-254", "date": "2026-04-11", "title": "step_runner.py: migrate implement_step to workspace-file invocation mode", "source": "planning", "effort": "S", "priority": "Critical", "status": "open", "automatable": true, "risk": "medium", "file": "scripts/executor/step_runner.py", "context": "Highest-traffic callsite, most affected by 28 KB ceiling. Migrate implement_step() to use context_file_path + inline_instruction from rec-252. Context file: logs/debug/impl-context-{rec_id}-step{n}.md. Inline instruction includes step number and total for sequential context. --continue session flag is independent of prompt delivery and unchanged. See PLAN-infra-decompose-rec-251.md Callsites table row 4.", "acceptance": "`python -m pytest tests/test_executor_step_runner.py -k context_file -v`", "dependencies": ["rec-252"], "tags": ["executor", "step-runner", "cli-invocation"]}
```

**rec-255** -- Migrate postflight callsites to workspace-file mode
```json
{"id": "rec-255", "date": "2026-04-11", "title": "postflight.py: migrate review/ci-fix/review-fix/merge-recovery to workspace-file mode", "source": "planning", "effort": "S", "priority": "Critical", "status": "open", "automatable": true, "risk": "low", "file": "scripts/executor/postflight.py", "context": "Migrate 4 postflight callsites (review_code, _fix_ci_failure, _fix_code_review_findings, _agent_merge_recovery) to workspace-file mode from rec-252. Context files: logs/debug/{review|ci-fix|review-fix|merge-recovery}-context-{rec_id}.md. Lower traffic than step_runner but benefits from debugging persistence. See PLAN-infra-decompose-rec-251.md Callsites table rows 5-8.", "acceptance": "`python -m pytest tests/test_executor_postflight.py -k context_file -v`", "dependencies": ["rec-252"], "tags": ["executor", "postflight", "cli-invocation"]}
```

**rec-256** -- Remove legacy @tempfile path and migrate remaining callsites
```json
{"id": "rec-256", "date": "2026-04-11", "title": "copilot_call: remove legacy @tempfile path, migrate classify_risk and run_agent", "source": "planning", "effort": "S", "priority": "High", "status": "open", "automatable": true, "risk": "low", "file": "scripts/copilot_wrapper.py", "context": "Final cleanup after all callsites migrated. (a) Migrate classify_risk() and run_agent() to workspace-file mode. (b) Remove legacy @tempfile code path from copilot_call() -- prompt param becomes inline instruction only, context_file_path required for multi-line prompts. (c) Update docs/contracts/copilot-cli.md with new invocation pattern. Supersedes rec-128 contract update. See PLAN-infra-decompose-rec-251.md.", "acceptance": "`python -c \"import pathlib; t=pathlib.Path('scripts/copilot_wrapper.py').read_text(); assert 'NamedTemporaryFile' not in t, 'legacy path remains'\" && python -m pytest tests/test_copilot_wrapper.py tests/test_classify_risk.py -v`", "dependencies": ["rec-253", "rec-254", "rec-255"], "tags": ["executor", "copilot-wrapper", "cli-invocation", "cleanup"]}
```

**rec-257** -- Add periodic context file pruning + S3 archival
```json
{"id": "rec-257", "date": "2026-04-11", "title": "Add logs/debug/ context file pruning and S3 archival to session_postflight", "source": "planning", "effort": "S", "priority": "Medium", "status": "open", "automatable": true, "risk": "low", "file": "scripts/session_postflight.py", "context": "Follow-up to workspace-file migration (rec-252 through rec-256). Context files persist in logs/debug/ (gitignored) for debugging. Add prune_context_files(max_age_days=7) that archives files older than threshold to S3 (agent-platform-agent-logs/context-files/) and deletes local copies. Called from session_postflight.py cleanup phase. Prevents unbounded local growth. See PLAN-infra-decompose-rec-251.md.", "acceptance": "`python -m pytest tests/test_session_postflight.py -k prune_context -v`", "dependencies": ["rec-256"], "tags": ["executor", "cleanup", "s3"]}
```

Acceptance: `python -c "import json; entries=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip() and not l.startswith('#')]; ids={e['id'] for e in entries}; assert all(f'rec-{n}' in ids for n in range(252,258)), f'missing: {[f\"rec-{n}\" for n in range(252,258) if f\"rec-{n}\" not in ids]}"`

### Step 2: Update rec-251 status to closed
Find the line in `logs/.recommendations-log.jsonl` containing `"id": "rec-251"` and update it:
- Set `"status": "closed"`
- Add `"resolution": "Decomposed into rec-252 through rec-257. See PLAN-infra-decompose-rec-251.md."`
- Add `"execution_result": "manual"`
- Add `"execution_date": "2026-04-11"`
- Add `"execution_branch": "agent/infra-decompose-rec-251"`

Acceptance: `python -c "import json; r=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip() and not l.startswith('#') and '\"rec-251\"' in l][0]; assert r['status']=='closed' and 'rec-252' in r.get('resolution',''), f'rec-251: {r[\"status\"]}'" `

### Step 3: Update rec-035 status to superseded
Find the line in `logs/.recommendations-log.jsonl` containing `"id": "rec-035"` and update it:
- Set `"status": "superseded"`
- Add `"resolution": "Superseded by rec-252. Workspace-file invocation mode naturally injects target file content into implementation prompts."`

Acceptance: `python -c "import json; r=[json.loads(l) for l in open('logs/.recommendations-log.jsonl') if l.strip() and not l.startswith('#') and '\"rec-035\"' in l][0]; assert r['status']=='superseded' and 'rec-252' in r.get('resolution',''), f'rec-035: {r[\"status\"]}'" `

### Step 4: Validate JSONL integrity
Run: `python -c "import json; lines=[l for l in open('logs/.recommendations-log.jsonl', encoding='utf-8') if l.strip() and not l.startswith('#')]; [json.loads(l) for l in lines]; print(f'All {len(lines)} entries valid')"` -- must print valid count with no exceptions.

Acceptance: `python -c "import json; [json.loads(l) for l in open('logs/.recommendations-log.jsonl', encoding='utf-8') if l.strip() and not l.startswith('#')]"`

### Step 5: Run validation
Run `python scripts/validate.py` -- must exit 0.

Acceptance: `python scripts/validate.py`

### Step 6: Report
Report: (a) 6 new recs filed (rec-252 through rec-257), (b) rec-251 closed, (c) rec-035 superseded, (d) all JSONL valid, (e) validate.py passed.
