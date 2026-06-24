---
description: Read-only orientation session. Surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and ready-to-paste /plan prompts. Produces a chat reply only; writes nothing. Run before /plan to choose what to work on next.
model: opus[1m]
---

# Orient Workflow

**Intent**: Consume the preflight cache and platform roadmap to produce a structured orientation deliverable: status digest, CI-RCA triage, ranked work list, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Writes nothing.

*Note: For the full orientation methodology (read-only contract, deliverable shape, overlap matrix spec, keystone sequencing, status-trusted-never-inferred rule), invoke your `orient` skill via the Skill tool.*

## Step 1: Confirm Preflight Cache

Check whether `logs/.preflight-report.json` exists, is recent (< 2 hours old), and contains
a `platform_roadmap.gate_evaluations` key. If any condition fails, run preflight with the
full projection to refresh:

```bash
bin/venv-python -m scripts.session_preflight --roadmap-detail full
```

`/orient` reads the preflight cache only -- it does NOT trigger a fresh warehouse reader fan-out
(Decision 88 egress budget; Decision 84 closed boundary). The preflight script is the only path
that may update `logs/.preflight-report.json`.

Do NOT call `bin/venv-python -m scripts.platform_roadmap` or any DuckLake reader verb during this workflow.

## Step 2: Load Inputs

Read the following from the preflight cache (`logs/.preflight-report.json`):
- `platform_roadmap.next_eligible` -- items eligible to start (each carries `user_action_required`)
- `platform_roadmap.strategic_pending` -- items blocked by the executor freeze
- `platform_roadmap.in_progress` -- items currently in progress; Phase B each entry also carries:
  - `open_criteria_count` -- count of criteria with status=open in the structured ledger
  - `all_plans_actioned` -- true if no PLAN-*.yaml has closes_criteria pointing at still-open criteria
  - `needs_followon_plan` -- true iff open_criteria_count > 0 AND all_plans_actioned is true (follow-on /plan is the next action)
- `platform_roadmap.blocked_on_cd` -- eligible items with a related pending candidate_decision
- `platform_roadmap.gate_evaluations` -- cross-tier gate verdicts (pass|fail|deferred)
- `ci_rca_unresolved_recs` -- HARD BLOCK recs (if any)
- `ci_rca_likely_resolved_recs` -- SOFT PROMPT recs (if any)
- `ci_rca_liveness_alert` -- HARD ALERT if non-null
- `forward_fix_recursion_alert` -- HARD ALERT if non-null
- `recent_main_commits` -- last 5 main commits (planning context)

Read `docs/ROADMAP-PLATFORM.yaml` directly for:
- `files_in_scope` lists (for the overlap matrix)
- `depends_on` chains (for keystone computation)

## Step 3: Invoke the Orient Skill and Emit the Deliverable

Apply the `orient` skill methodology to produce the four-section chat deliverable:
1. Status Digest -- includes an Open Criteria column for in_progress items (ranked fewest-open-criteria-first); Phase A infers from exit_criteria + progress_note prose, Phase B reads open_criteria_count from the preflight cache.
2. CI-RCA Triage
3. Ranked What-to-Work-On -- in_progress items emit follow-on /plan prompts (fewest-open-criteria-first); /implement is suggested only for genuinely mid-implementing (un-actioned) plans. Phase B reads needs_followon_plan from the preflight cache.
4. /plan Prompts with Overlap Matrix -- follow-on /plan prompts for in_progress items precede eligible-item prompts.

Output the deliverable to the chat. This is the sole output of `/orient`.

**Write nothing.** No files created or modified. No recommendations filed. No roadmap edits.

STOP. The orient session is complete.
