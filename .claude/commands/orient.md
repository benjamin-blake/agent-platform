---
description: Read-only orientation session. Surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and ready-to-paste /plan prompts. Produces a chat reply only; writes nothing. Run before /plan to choose what to work on next.
model: opus[1m]
---

# Orient Workflow

**Intent**: Consume the preflight cache and platform roadmap to produce a structured orientation deliverable: status digest, CI-RCA triage, ranked work list, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Writes nothing.

*Note: For the full orientation methodology (read-only contract, deliverable shape, overlap matrix spec, keystone sequencing, status-trusted-never-inferred rule), invoke your `orient` skill via the Skill tool.*

## Step 1: Confirm Preflight Cache

Check whether `logs/.preflight-report.json` exists and is recent. If it is missing or older than 2 hours, run preflight to refresh:

```bash
bin/venv-python -m scripts.session_preflight
```

`/orient` reads the preflight cache only -- it does NOT trigger a fresh warehouse reader fan-out (Decision 88 egress budget; Decision 84 closed boundary). The preflight script is the only path that may update `logs/.preflight-report.json`.

Do NOT call `bin/venv-python -m scripts.platform_roadmap` or any DuckLake reader verb during this workflow.

## Step 2: Load Inputs

Read the following from the preflight cache (`logs/.preflight-report.json`):
- `platform_roadmap.next_eligible` -- items eligible to start
- `platform_roadmap.strategic_pending` -- items blocked by the executor freeze
- `ci_rca_unresolved_recs` -- HARD BLOCK recs (if any)
- `ci_rca_likely_resolved_recs` -- SOFT PROMPT recs (if any)
- `ci_rca_liveness_alert` -- HARD ALERT if non-null
- `forward_fix_recursion_alert` -- HARD ALERT if non-null
- `recent_main_commits` -- last 5 main commits (planning context)

Read `docs/ROADMAP-PLATFORM.yaml` directly for:
- All `in_progress` tier_items
- `files_in_scope` lists (for the overlap matrix)
- `depends_on` chains (for keystone computation)

## Step 3: Invoke the Orient Skill and Emit the Deliverable

Apply the `orient` skill methodology to produce the four-section chat deliverable:
1. Status Digest
2. CI-RCA Triage
3. Ranked What-to-Work-On
4. /plan Prompts with Overlap Matrix

Output the deliverable to the chat. This is the sole output of `/orient`.

**Write nothing.** No files created or modified. No recommendations filed. No roadmap edits.

STOP. The orient session is complete.
