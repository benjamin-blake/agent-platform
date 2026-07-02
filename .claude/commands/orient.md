---
description: Read-only orientation session. Surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and ready-to-paste /plan prompts. Produces a chat reply only; writes nothing. Run before /plan to choose what to work on next.
model: opus[1m]
---

# Orient Workflow

**Intent**: Consume the preflight cache and platform roadmap to produce a structured orientation deliverable: status digest, CI-RCA triage, ranked work list, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Writes nothing.

*Note: For the full orientation methodology (read-only contract, deliverable shape, overlap matrix spec, keystone sequencing, status-trusted-never-inferred rule), invoke your `orient` skill via the Skill tool.*

## Step 1: Confirm Preflight Cache

Check whether `logs/.preflight-report.json` exists, is recent (< 2 hours old), and contains a
`platform_roadmap.gate_evaluations` key. If any condition fails, refresh with the full projection:
`bin/venv-python -m scripts.session_preflight --roadmap-detail full`.

Full cache-only constraint, input-field semantics, and the in_progress field contract live in the
`orient` skill (Inputs section) -- invoke it via the Skill tool rather than re-deriving them here.

## Step 2: Load Inputs

Read from the preflight cache (`logs/.preflight-report.json`): `platform_roadmap.next_eligible`,
`strategic_pending`, `in_progress` (field semantics in the skill's Inputs > In_progress entry
fields), `blocked_on_cd`, `gate_evaluations`, `ratifiable_cds`; `ci_rca_unresolved_recs`,
`ci_rca_likely_resolved_recs`, `ci_rca_liveness_alert`, `forward_fix_recursion_alert`,
`recent_main_commits`; and the Best-Practices signals `convergence_health`, `telemetry_health`,
`data_quality`, `non_automatable_softcap_breached`, `terraform_pending`.

For `files_in_scope` (overlap matrix) and `depends_on` (keystone computation), use the typed-loader
projection -- pure-local, no warehouse I/O, distinct from the banned `-m scripts.platform_roadmap`
module entrypoint (frame-lock note: this imports `scripts.platform_roadmap.load()` only, never the
module entrypoint itself). Fall back to a full-file Read of `docs/ROADMAP-PLATFORM.yaml` on error:
```bash
bin/venv-python -c "import json; from scripts.platform_roadmap import load; ids={i['id'] for k in ('next_eligible','in_progress','blocked_on_cd') for i in json.load(open('logs/.preflight-report.json')).get('platform_roadmap',{}).get(k,[])}; proj=[t.model_dump(include={'id','files_in_scope','depends_on','related_candidate_decisions'}) for t in load('docs/ROADMAP-PLATFORM.yaml').tier_items if t.id in ids]; print(json.dumps(proj))"
```

## Step 3: Invoke the Orient Skill and Emit the Deliverable

Apply the `orient` skill methodology to produce the six-section chat deliverable:
1. Status Digest
2. CI-RCA Triage
3. Momentum & Direction
4. Best-Practices Health Check
5. Ranked What-to-Work-On
6. /plan Prompts with Overlap Matrix

See the skill's Deliverable Shape section for the full spec of each.

Output the deliverable to the chat. This is the sole output of `/orient`.

**Write nothing.** No files created or modified. No recommendations filed. No roadmap edits.

STOP. The orient session is complete.
