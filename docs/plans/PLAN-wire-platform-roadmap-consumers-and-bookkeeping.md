# Plan

## Intent
Close the loop on T-1.4 (preflight platform_roadmap state, merged in cb87c2a) by wiring its two consumers (T-1.2 planning skill, T-1.3 /plan command), declaring a new T-1.9 tier_item that captures the session-log architecture audit that emerged from this planning discussion, and adding an in-implement bookkeeping rule so future /implement sessions update tier_item status + progress_note automatically. This makes platform_roadmap state observable to every future planning session and eliminates the manual ratification lag currently producing the preflight stale_cache_note.

## Plan Type
IMPLEMENTATION

(Per AGENTS.md Temporary Operational Constraints: STRATEGIC plan-artefact authoring is suspended; this work is decomposed as a single atomic IMPLEMENTATION plan despite touching multiple files. Complexity heuristic of >5 files / >8 steps is informational only during the freeze.)

## Verification Tier
V2

Python source (`scripts/platform_roadmap.py`) plus skill/command markdown (`.claude/skills/planning/SKILL.md`, `.claude/commands/plan.md`, `.claude/skills/implement/SKILL.md`) plus declarative YAML (`docs/ROADMAP-PLATFORM.yaml`). No external systems, no Lambda-packaged files (none of the files in scope appear in any Lambda manifest), no Terraform. Verification exercises real schema validation, the actual preflight JSON, and the actual skill/command load paths.

## Branch
agent/wire-platform-roadmap-consumers-and-bookkeeping

## Phase
T-1 (Governance / integration tier — wires the consumers of T-1.4's just-merged preflight computation and adds the bookkeeping discipline that closes the ratification-lag feedback loop).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | (a) Flip T-1.4 status `not_started` -> `complete` with `completed_at: "2026-05-19"`. (b) Add new tier_item **T-1.9 "Session-log architecture audit + redesign"** with REPORT-ONLY shape, S effort, intent capturing the two-write-surface concern (`docs/SESSION_LOG.md` deprecated per NS.4; `ops_session_log` Athena schema unverified for accuracy/semantics; log-* Lambda surface in T0.7b changes the eventual target). |
| `scripts/platform_roadmap.py` | Modify | Add optional `progress_note: str \| None = None` field to TierItem. Field is consumed by the implement-skill bookkeeping rule (Scope item 5 below) to record partial-completion narrative when a session advances a tier_item without satisfying all exit_criteria. Existing `status: Literal[..., "in_progress", ...]` enum already supports the partial state — no enum change needed. |
| `.claude/skills/planning/SKILL.md` | Modify | T-1.2: planning skill Step 2 reads `preflight.platform_roadmap` and surfaces `next_eligible[]` and `strategic_pending[]` to the planning agent. Add documented exception categories for soft-warning behaviour when an intent names work outside tier_items (`ci_rca`, `hotfix`, `security_advisory`, `ad_hoc_rec`, `user_explicit_out_of_scope`). |
| `.claude/commands/plan.md` | Modify | T-1.3: /plan Step 2 (Read Context) section adds a one-line instruction to print `preflight.platform_roadmap.next_eligible` and `preflight.platform_roadmap.strategic_pending` so the human sees the eligibility surface without me having to manually grep the YAML. |
| `.claude/skills/implement/SKILL.md` | Modify | In-implement bookkeeping rule (NEW). After the implement skill's existing verification-pass gate fires, walk `tier_item.exit_criteria[]` for each tier_item named in the executed plan's Scope. If all exit_criteria pass: stage a `status: complete` flip + `completed_at` timestamp. If a strict subset pass: stage `status: in_progress` + a structured `progress_note` describing what shipped this session. Stage these edits to the YAML during the code-review window (which runs in the cloud and does not block the local agent); commit them after code-review returns PROCEED; discard them if code-review returns REVISE. State-machine semantics specified in Ordered Execution Step 4. |

Additionally, a SECOND new tier_item (**T-1.10 "In-implement tier_item bookkeeping rule"**) is declared in the same YAML edit pass alongside T-1.9. T-1.10 documents this very plan's bookkeeping work as canonical T-1 governance (per plan-critique finding: no work should silently fall outside tier_item discipline that this plan is itself designed to close). T-1.10 has `depends_on: [T-1.4]`, exit_criteria listing the four bookkeeping-rule components (trigger, walk, parallel timing, status-flip rules), and is flipped to `status: complete` by this same plan's commit 4 (since the implement-skill rule IS T-1.10).

## Bundled Recommendations
None. The 279 open recommendations and 198 non-automatable recs surfaced at preflight are not direct dependencies of this governance-loop closeout. The closest aligned rec (rec-027 "Test nested subagents") concerns the implement skill's subagent invocation surface but is not load-bearing for this plan's bookkeeping rule, which uses the implement skill's existing verification gate as the trigger.

## Infrastructure Dependencies
N/A. No `.tf` files in scope.

## Acceptance Criteria
- [ ] `docs/ROADMAP-PLATFORM.yaml` T-1.4 entry has `status: complete` and `completed_at: "2026-05-19"`
- [ ] `docs/ROADMAP-PLATFORM.yaml` contains new tier_item with `id: T-1.9`, `tier: T-1`, `effort: S`, `strategic: false`, `status: not_started`, intent text covering all four discussion points (two write surfaces, NS.4 markdown deprecation, Athena schema unverified, Lambda migration target), exit_criteria naming the REPORT-ONLY INTENT deliverable shape, and `depends_on: []`
- [ ] `docs/ROADMAP-PLATFORM.yaml` contains new tier_item with `id: T-1.10`, `tier: T-1`, `effort: S`, `strategic: false`, `depends_on: [T-1.4]`, exit_criteria listing the four bookkeeping-rule components (trigger, criteria walk, parallel-with-code-review timing, status-flip rules); `status: complete` only AFTER commit 4 of this plan lands (the implement-skill rule IS T-1.10's deliverable, so its bookkeeping-rule self-application is the proof of completion)
- [ ] `bin/venv-python -m scripts.validate --pre` passes (advisory edit-loop tier: lint/format/diff-aware checks on touched files only — `validate_platform_roadmap()` does NOT run in `--pre` per its docstring at `scripts/validate.py:1603`)
- [ ] `bin/venv-python -m scripts.validate` (full CI-equivalent, no `--pre`) passes — this is the authoritative gate that calls `validate_platform_roadmap()` via `run_python_checks()` at `scripts/validate.py:1899`, and is what CI on the self-hosted runner enforces per Decision 68
- [ ] `scripts/platform_roadmap.py` TierItem class has `progress_note: str | None = None`; existing tests still pass
- [ ] `bin/venv-python -m scripts.session_preflight` produces a `logs/.preflight-report.json` where `platform_roadmap.next_eligible[]` no longer contains T-1.4 (because it's now complete) and the existing `next_eligible` items remain (T-1.7, T0.2, T0.3, T0.13, T0.14)
- [ ] `.claude/skills/planning/SKILL.md` Step 2 instructs the agent to consume `preflight.platform_roadmap.next_eligible` and `preflight.platform_roadmap.strategic_pending`; the five soft-warn exception categories are enumerated
- [ ] `.claude/commands/plan.md` Step 2 instructs the planning agent to print the eligibility summary to the user
- [ ] `.claude/skills/implement/SKILL.md` contains a documented bookkeeping section that names: (a) the trigger (verification-pass gate fires), (b) the criteria walk (exit_criteria executable checks), (c) the parallel-with-code-review timing (stage during review, commit after PROCEED, discard on REVISE), (d) the status-flip rules (all-criteria -> complete; subset -> in_progress + progress_note; zero -> no change)
- [ ] T-1.9 declaration commits separately from the implementation commits so the roadmap diff is reviewable on its own
- [ ] Plan-critique gate (Step 9) returns PROCEED

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | static | Confirm YAML loads through the RoadmapDocument Pydantic schema after T-1.4 status flip + T-1.9 + T-1.10 additions + `progress_note` field | `bin/venv-python -c "from scripts.platform_roadmap import load; load('docs/ROADMAP-PLATFORM.yaml'); print('ok')"` | Prints `ok` | Schema rejects the YAML; check id-uniqueness, depends_on resolution, and field types |
| 2 | static | Confirm T-1.4 marked complete | `bin/venv-python -c "from scripts.platform_roadmap import load; doc = load('docs/ROADMAP-PLATFORM.yaml'); item = next(i for i in doc.tier_items if i.id == 'T-1.4'); assert item.status == 'complete', item.status; print('ok')"` | Prints `ok` | T-1.4 not flipped or status field missed |
| 3 | static | Confirm T-1.9 exists and round-trips through Pydantic | `bin/venv-python -c "from scripts.platform_roadmap import load; doc = load('docs/ROADMAP-PLATFORM.yaml'); item = next(i for i in doc.tier_items if i.id == 'T-1.9'); assert item.tier == 'T-1' and item.effort == 'S' and item.depends_on == [] and item.status == 'not_started'; print('ok')"` | Prints `ok` | T-1.9 missing or fields wrong |
| 4 | static | Confirm T-1.10 exists with correct dependency on T-1.4 | `bin/venv-python -c "from scripts.platform_roadmap import load; doc = load('docs/ROADMAP-PLATFORM.yaml'); item = next(i for i in doc.tier_items if i.id == 'T-1.10'); assert item.tier == 'T-1' and item.effort == 'S' and 'T-1.4' in item.depends_on; print('ok')"` | Prints `ok` | T-1.10 missing or dependency wrong |
| 5 | static | Confirm `progress_note` field exists on TierItem and accepts a string | `bin/venv-python -c "from scripts.platform_roadmap import TierItem; t = TierItem(id='X', tier='T0', name='n', progress_note='shipped phase 1'); assert t.progress_note == 'shipped phase 1'; print('ok')"` | Prints `ok` | Field not added or wrong type |
| 6 | static | Confirm preflight no longer lists T-1.4 in next_eligible | `bin/venv-python -m scripts.session_preflight 2>/dev/null && bin/venv-python -c "import json; r = json.load(open('logs/.preflight-report.json')); ids = [i['id'] for i in r['platform_roadmap']['next_eligible']]; assert 'T-1.4' not in ids, ids; print('ok')"` | Prints `ok` | T-1.4 still listed (status flip didn't take) |
| 7 | static | Confirm planning skill Step 2 references `preflight.platform_roadmap` | `grep -n 'platform_roadmap' .claude/skills/planning/SKILL.md` | Returns at least one hit referencing next_eligible / strategic_pending consumption | Skill not wired; add the reference |
| 8 | static | Confirm planning skill enumerates the five soft-warn exception categories | `bin/venv-python -c "import pathlib; t = pathlib.Path('.claude/skills/planning/SKILL.md').read_text(); cats = ['ci_rca', 'hotfix', 'security_advisory', 'ad_hoc_rec', 'user_explicit_out_of_scope']; missing = [c for c in cats if c not in t]; assert not missing, f'missing: {missing}'; print('ok')"` | Prints `ok` | Categories missing — add the ones flagged |
| 9 | static | Confirm /plan command Step 2 surfaces eligibility | `grep -nE 'next_eligible\|strategic_pending\|platform_roadmap' .claude/commands/plan.md` | At least one hit in Step 2 area | Command not wired |
| 10 | static | Confirm implement skill bookkeeping section has required components | `bin/venv-python -c "import pathlib; t = pathlib.Path('.claude/skills/implement/SKILL.md').read_text(); needed = ['exit_criteria', 'progress_note', 'code-review', 'PROCEED', 'REVISE']; missing = [k for k in needed if k not in t]; assert not missing, f'missing: {missing}'; print('ok')"` | Prints `ok` | Section missing required components — add the ones flagged |
| 11 | dynamic | Bookkeeping rule dry-run, EXECUTABLE-CRITERIA PATH ONLY: prepend a temporary T0.99 tier_item to YAML in-memory, walk its single trivially-passing criterion (`test -f CLAUDE.md`), assert the rule's subprocess-exec logic identifies it as passing; YAML on disk untouched. **Coverage gap:** this step exercises the executable-criteria subprocess path only. The state-machine semantics (idempotency-on-resume, abandonment detection, staged-edit-loss detection) live as prose in `.claude/skills/implement/SKILL.md` and are not unit-testable in their current form; they are validated by (a) prose review during the plan-critique gate and (b) the bookkeeping rule's first real-world self-application against T-1.10 (the self-application invariant). | `bin/venv-python -c "import yaml, subprocess; d = yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml')); d['tier_items'].append({'id':'T0.99','tier':'T0','name':'dry-run','intent':'test','depends_on':[],'files_in_scope':[],'exit_criteria':['test -f CLAUDE.md'],'related_candidate_decisions':[],'effort':'XS','strategic':False,'status':'not_started'}); item = d['tier_items'][-1]; results = [subprocess.run(c, shell=True).returncode == 0 for c in item['exit_criteria']]; assert all(results), results; print('ok')"` | Prints `ok` (the criterion executes via subprocess and passes; the rule logic is exercised in-process; YAML on disk untouched) | Subprocess fails (CLAUDE.md missing) or yaml shape rejected |
| 12 | dynamic | Bookkeeping rule prose-judgement-path limitation: document explicitly in the implement-skill section that prose exit_criteria fall through to agent judgement and that the default action for ambiguous prose is to NOT stage a status flip (conservative bias), and confirm the section says so | `bin/venv-python -c "import pathlib; t = pathlib.Path('.claude/skills/implement/SKILL.md').read_text(); assert 'prose' in t.lower() and 'conservative' in t.lower(), 'missing prose/conservative-bias guidance'; print('ok')"` | Prints `ok` | Section does not document the prose-path limitation — add the explicit conservative-bias rule |
| 13 | static | Commit graph assertion: branch has exactly four named commits in expected order (roadmap, T-1.2, T-1.3, T-1.4-bookkeeping) | `git log main..HEAD --oneline \| awk -F' ' '{print $2}'` (read the commit-subject prefixes; expected to start with `roadmap`, `feat(t-1-2)`, `feat(t-1-3)`, `feat(implement-bookkeeping)`) | Four commits, prefixes match the expected sequence | Commit graph diverges — squash or reorder as needed; if intentional drift, document in plan |
| 14 | static | Fast-tier presubmit (advisory edit-loop only) green | `bin/venv-python -m scripts.validate --pre` | Exit 0, no regressions in lint/format on touched files | Address the specific failure; do not skip checks. NB: this tier does NOT call `validate_platform_roadmap()` — VP step 15 is the authoritative roadmap-schema gate |
| 15 | static | Full CI-equivalent locally (not just --pre) | `bin/venv-python -m scripts.validate` | Exit 0, no regressions | Address the failure; CI is authoritative gate per Decision 68 |
| 16 | static | Pytest green on platform_roadmap module (schema change shouldn't break existing tests) | `bin/venv-python -m pytest tests/test_platform_roadmap.py -v` | All tests pass | Adjust test fixtures only if they're shape-asserting the TierItem field list; never weaken schema invariants |

## Constraints
- AGENTS.md: STRATEGIC plans suspended (this is IMPLEMENTATION, conforms)
- AGENTS.md: Lambda deployment deferred (no Lambda-packaged files in scope, N/A)
- AGENTS.md: never edit on `main` (branch already created, hook enforces)
- CLAUDE.md: ASCII only, no emojis in code/docs/scripts
- CLAUDE.md: Single Portal Invariant (this plan does not write to recs/decisions logs; only YAML + skill markdown)
- CLAUDE.md: Warehouse-as-source-of-truth (this plan does not touch any logs/ files or Athena writers)
- Decision 55: No rescue agents or workaround loops
- Decision 67: STRATEGIC-plan freeze applies (this plan is IMPLEMENTATION; conforms)
- Decision 68: CI (validate.py on self-hosted runner) is the authoritative pre-merge gate; local `--pre` is advisory

## Context

- **Why now:** T-1.4 shipped in PR #349 (cb87c2a) and produces a 35-key `platform_roadmap` payload in every preflight JSON, but the two consumers (planning skill, /plan command) do not read it. Without them, the just-shipped feature is invisible to the planning workflow it was built for. Today's planning session had to manually grep the YAML to surface eligible work — that's the friction this plan eliminates.
- **Why bookkeeping in the same plan:** The bookkeeping rule's value depends on the consumers existing (skill/command read the platform_roadmap, the bookkeeping rule writes to it). Shipping consumers without the writer leaves stale_cache_note alive; shipping the writer without consumers leaves the writes invisible. Pairing them in one plan closes the loop atomically.
- **Why T-1.9 in the same branch:** Recs are atomic units for the (currently-paused) executor, not deliberation work. The session-log architecture question is REPORT-ONLY-shaped (audit + INTENT + CD proposal), which is the tier_item pattern (cf. INTENT-aws-migration-platform-evolution which is T2-tier REPORT-ONLY work). The T-1.5 RoadmapDocument Pydantic schema validates structural conformance, so adding tier_items is a low-risk YAML edit.
- **Stale-cache loop:** The preflight currently surfaces `stale_cache_note: "roadmap edits awaiting ratification: YAML mtime ... newer than latest decision ..."`. Marking T-1.4 complete and adding the bookkeeping rule reduces (does not eliminate) this loop because ratification via the log-decision Lambda (T0.7b) is still months out; until then the bootstrap clause exempts T-1 items from CD ratification before status flips.
- **Parallel-with-code-review rationale:** The code-review skill runs against the cloud (multi-minute wall-clock); the local agent is idle in that window. Staging YAML edits during that idle window is genuine concurrency, not busywork. The commit-after-PROCEED / discard-on-REVISE pattern keeps the bookkeeping bound to the verification verdict so a REVISE doesn't leave bogus status flips in the worktree.
- **Existing schema gotcha:** `scripts/platform_roadmap.py:129` already defines a `note: str | None = None` field on TierItem, but YAML entries use `notes:` (plural) — so the existing field is unused (silently ignored by `extra="ignore"`). This is a pre-existing inconsistency NOT in scope for this plan. We add a new `progress_note` field with distinct semantics ("what's been done so far" vs "static commentary on the item"); the unused `note` field stays untouched.
- **Session-log architecture defer rationale:** Today's discussion converged on dropping session-log writes from this plan because (a) markdown surface is deprecated per NS.4, writing to it is dead work; (b) Athena ops_session_log writer is unverified for accuracy/semantics, more writes would entrench unaudited behaviour; (c) the eventual log-* Lambda surface in T0.7b changes the target, so building bookkeeping logic against the current surface generates migration debt. T-1.9 captures this deliberation as a REPORT-ONLY tier_item for a future planning session.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (verify with `git branch --show-current`)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] CLAUDE.md + AGENTS.md read for invariants
- [ ] docs/ROADMAP-PLATFORM.yaml read, specifically T-1.4 (line ~756), T-1.8 (line ~843), T0.14 (line ~1180) for tier_item shape reference, and the agent_instructions block (lines 23-79) for bootstrap clause context
- [ ] scripts/platform_roadmap.py read, specifically the TierItem class (lines 115-130) and the existing tests at tests/test_platform_roadmap.py
- [ ] Confirmed that `validate_platform_roadmap()` is a function inside `scripts/validate.py` (defined at line 1598, called from line 1899 via `run_python_checks()`), NOT a standalone module. Per its docstring at line 1603, it runs in FULL presubmit only — `bin/venv-python -m scripts.validate` — and NOT in `--pre` edit-loop mode. For local roadmap-schema verification during the edit loop, use the direct loader call: `bin/venv-python -c "from scripts.platform_roadmap import load; load('docs/ROADMAP-PLATFORM.yaml')"`
- [ ] Confirmed the loader function is `load(path)` (line 273), not `load_roadmap()`
- [ ] .claude/skills/planning/SKILL.md read end-to-end (especially Step 2 / Suggest Aligned Recommendations)
- [ ] .claude/commands/plan.md read end-to-end (especially Step 2: Read Context)
- [ ] .claude/skills/implement/SKILL.md read end-to-end (especially the verification-pass gate and the code-review invocation)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and each is independently verifiable

## Ordered Execution Steps

1. **Roadmap commit (declarative-only, lands first):**
   a. Edit `docs/ROADMAP-PLATFORM.yaml`: flip T-1.4 `status: not_started` -> `status: complete`, add `completed_at: "2026-05-19"` (matching cb87c2a PR #349 merge date).
   b. Edit `docs/ROADMAP-PLATFORM.yaml`: append new tier_item T-1.9 after T-1.8, with:
      - `id: T-1.9`
      - `tier: T-1`
      - `name: Session-log architecture audit + redesign`
      - `intent:` multi-line block capturing the two-write-surface concern, NS.4 markdown deprecation, Athena schema unverified, T0.7b Lambda migration target shift, and that this is REPORT-ONLY shape
      - `depends_on: []`
      - `files_in_scope: []` (REPORT-ONLY)
      - `exit_criteria:` listing the REPORT-ONLY INTENT deliverable shape (audit both surfaces, propose CD(s) for the surface decision, propose follow-on IMPLEMENTATION plans for the migration)
      - `related_candidate_decisions: []` (CDs to be drafted inside the eventual INTENT)
      - `effort: S`
      - `strategic: false`
      - `status: not_started`
   c. Edit `docs/ROADMAP-PLATFORM.yaml`: append new tier_item T-1.10 after T-1.9, with:
      - `id: T-1.10`
      - `tier: T-1`
      - `name: In-implement tier_item bookkeeping rule`
      - `intent:` describing the bookkeeping rule that this very plan introduces (post-verification, walks exit_criteria, stages YAML edits parallel to code-review, commits on PROCEED). Note explicitly that this tier_item's deliverable IS the implement-skill rule shipped by commit 4 of this plan, so completion is self-applied by the rule on its own first run.
      - `depends_on: [T-1.4]` (the rule consumes the same YAML state T-1.4 produces)
      - `files_in_scope: ['.claude/skills/implement/SKILL.md']`
      - `exit_criteria:` listing the four bookkeeping-rule components: (1) trigger fires after verification-pass gate, (2) walk traverses tier_item exit_criteria with executable + prose-judgement handling, (3) parallel-with-code-review timing with explicit commit-on-PROCEED / discard-on-REVISE / abandonment-detection state machine, (4) status-flip rules (all-criteria -> complete; subset -> in_progress + progress_note; zero -> no change; idempotent on resume)
      - `related_candidate_decisions: []`
      - `effort: S`
      - `strategic: false`
      - `status: not_started` (flipped to `complete` only by commit 4's self-application)
   d. Edit `scripts/platform_roadmap.py`: add `progress_note: str | None = None` to TierItem (line ~129, after the `note` field).
   e. Verify locally: `bin/venv-python -c "from scripts.platform_roadmap import load; load('docs/ROADMAP-PLATFORM.yaml'); print('ok')"`. If it fails, fix the YAML or the schema before committing.
   f. Commit: `git add docs/ROADMAP-PLATFORM.yaml scripts/platform_roadmap.py && git commit -m "roadmap(t-1-4,t-1-9,t-1-10): mark T-1.4 complete; declare T-1.9 session-log audit + T-1.10 bookkeeping rule; add progress_note field"`.

2. **T-1.2 planning skill wiring (feat commit):**
   - Edit `.claude/skills/planning/SKILL.md` to add to Step 2: "Read `preflight.platform_roadmap` (already in the JSON from Step 1) and surface `next_eligible[]` (eligible work items) and `strategic_pending[]` (queued strategic items) to the agent so the planning session is grounded in canonical roadmap state."
   - Add a documented exception-categories paragraph: "Soft-warn (do not reject) when an intent names work outside `tier_items[]` if it falls into one of these documented categories: `ci_rca`, `hotfix`, `security_advisory`, `ad_hoc_rec`, `user_explicit_out_of_scope`. Reject only when the intent claims tier_item alignment that does not resolve to a known id."
   - Commit: `git commit -m "feat(t-1-2): planning skill reads preflight.platform_roadmap and surfaces eligibility"`.

3. **T-1.3 /plan command wiring (feat commit):**
   - Edit `.claude/commands/plan.md` Step 2 to add a one-line instruction: "Also surface `preflight.platform_roadmap.next_eligible` and `preflight.platform_roadmap.strategic_pending` to the human so the eligibility surface is visible without me grepping the YAML."
   - Commit: `git commit -m "feat(t-1-3): /plan Step 2 surfaces platform_roadmap eligibility to human"`.

4. **In-implement bookkeeping rule (feat commit) — T-1.10 deliverable:**
   - Edit `.claude/skills/implement/SKILL.md` to add a new section "Tier_item bookkeeping (post-verification, pre-merge)". Section must contain:
     - **Trigger:** verification-pass gate fires (the existing implement-skill gate at the end of the Verification Plan execution loop).
     - **Walk:** for each tier_item id named in the plan's `Phase` field or Context section, OR named via a `roadmap-touched:` directive in the plan, walk `tier_item.exit_criteria[]` and evaluate each criterion. Executable criteria (greppable / file-exists / pytest-runnable / `bin/venv-python -c "..."` one-liners) run via subprocess; the pass/fail signal is the exit code. Prose criteria fall through to agent judgement WITH A CONSERVATIVE BIAS: when in doubt about whether a prose criterion is satisfied, do NOT count it as passing. This bias produces under-counting (false in-progress) rather than over-counting (false complete), which matches the safer failure mode for the stale_cache_note loop this work is closing.
     - **Outcome rules:** all-criteria pass -> stage `status: complete` + `completed_at: "<today ISO>"`. Strict subset pass (>=1 but not all) -> stage `status: in_progress` + `progress_note: "<one-line description of what shipped this session>"` (preserve any existing `progress_note` by appending a dated bullet rather than overwriting). Zero pass -> no YAML change.
     - **Parallel-with-code-review state machine** (explicit per plan-critique finding):
       1. Implement skill invokes code-review (which runs in the cloud / via subagent and does NOT block the local agent's wall-clock).
       2. WHILE code-review is running, the implement-skill agent performs the criteria walk and stages the YAML edit locally to the worktree (uncommitted, `git status` shows it modified).
       3. **Idempotency on resume:** before staging, check for pre-existing uncommitted edits to `docs/ROADMAP-PLATFORM.yaml`. If present and they match what the bookkeeping rule would produce, no-op. If present and they conflict, surface the conflict to the user and skip auto-bookkeeping for this session — do NOT silently overwrite.
       4. **Code-review verdict handling:**
          - PROCEED -> commit the staged edit as a follow-up commit on the branch: `git commit docs/ROADMAP-PLATFORM.yaml -m "roadmap(<tier-ids>): bookkeeping after <slug>"`. Push.
          - REVISE -> discard the staged edit: `git checkout -- docs/ROADMAP-PLATFORM.yaml`. Address the code-review findings. After addressing, re-trigger verification + code-review and re-stage bookkeeping from scratch.
       5. **Abandonment / timeout semantics:** if code-review does not return within the implement-skill's existing wait window (or is interrupted), the staged YAML edit is discarded automatically on next session entry (the idempotency check on resume detects the orphaned stage and reports it to the user for explicit accept/reject rather than silently committing). The implement skill does not auto-commit bookkeeping that lacks a verdict-attested verification pass.
       6. **Staged-edit-loss detection:** if any intermediate command (manual `git checkout`, `git stash`, `git reset`) clobbers the staged edit between dispatch and verdict, the next bookkeeping attempt detects this by re-running the criteria walk and comparing against the YAML's current state. Loss is observable, not silent.
     - **Self-application invariant:** T-1.10's own exit_criteria are satisfied by the existence of this section. The first /implement run that uses this skill SHOULD therefore stage `T-1.10 -> status: complete` as part of this same commit's bookkeeping pass — but DO NOT flip T-1.10 manually in this commit; the rule's first real-world invocation (this very session, if /implement is run against this plan) is the proof. If the rule works, T-1.10 self-flips; if it does not, T-1.10 stays `not_started` and the bug is observable.
     - **Recovery clause for failed self-flip:** if T-1.10 remains `status: not_started` after this branch merges (because the bookkeeping pass aborted, code-review returned REVISE indefinitely, or the rule failed silently), the next planning session must address it explicitly — either as a manual YAML flip in a small follow-up plan, or as a follow-on tier_item that re-implements the bookkeeping rule under different assumptions. Do not let T-1.10 sit `not_started` indefinitely while its implementation is live; that contradicts the very stale-cache loop this plan exists to close.
   - Commit: `git commit .claude/skills/implement/SKILL.md -m "feat(t-1-10): in-implement tier_item bookkeeping rule, parallel with code-review"`.

5. **Execute Verification Plan** — run each VP step in order. Loop until pass. For step 10 (synthetic dry-run), revert any test tier_items added so the YAML lands clean.

6. **Report:** summarise what was implemented, the verification results, and the four commits landed on the branch. Open a PR via `gh pr create` per the merge protocol.

## Work Areas
N/A (IMPLEMENTATION plan).
