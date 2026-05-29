---
description: Supervisor workflow for developing the autonomous executor. Runs Root Cause Analysis on unrecoverable executor failures and files a permanent fix as a recommendation, per Decision 55. Does not repair the failure inline.
---

# Workflow: Develop Executor (RCA)

**Purpose**: Execute Root Cause Analysis (RCA) on unrecoverable executor failures, as mandated by Decision 55.
**Trigger**: Slash command `/develop-executor`

## 1. Context Gathering
- Ask the user to specify the failure context if not provided (e.g., a specific `rec-NNN` or transcript path).
- Read the most recent failure transcript in `logs/transcripts/` or the latest exception in `logs/.telemetry-process-events.jsonl` matching the context.

## 2. Execute RCA Skill
- Run the Executor RCA skill in a fresh context to ensure unbiased diagnosis. This is intentionally a headless invocation via `run_skill.py` (not the in-session Skill tool), so the diagnosis is uncontaminated by this session's reasoning:
  ```bash
  bin/venv-python -m scripts.agent_development.run_skill --skill executor-rca --target <path_to_failure_transcript> --model auto
  ```
- Wait for the skill to output its root cause analysis and the generated recommendation JSON.

## 3. File the Recommendation
The RCA skill emits a recommendation JSON. File it via the ops portal (NOT a direct write to the JSONL — Single Portal Invariant). Translate each JSON field into the corresponding `--file-rec` argument:

```bash
bin/venv-python -m scripts.ops_data_portal --file-rec \
    --title "<rca.title>" \
    --file "<rca.file>" \
    --context "<rca.context>" \
    --acceptance "<rca.acceptance>" \
    --effort <XS|S|M|L|XL> \
    --priority <Critical|High|Medium|Low> \
    --source executor-rca \
    --risk <low|medium|high> \
    --verification "<rca.verification>" \
    --verification-tier <V1|V2|V3>
```

- The portal allocates the next `rec-NNN` ID atomically via DynamoDB.
- RCA recommendations derive `automatable=false` automatically -- executor files match the boundary patterns in `config/agent/executor/capabilities.yaml` (Decision 44). The `--automatable` CLI flag has been removed; the portal formula handles it.
- If AWS credentials are missing, the portal queues to `logs/.ops-outbox/`. Drain later with `bin/venv-python -m scripts.ops_data_portal --drain --profile agent_platform`.

## 4. Stop Cleanly
- **CRITICAL INVARIANT:** Do not attempt to repair the failure. Do not apply workarounds.
- Terminate the workflow, leaving the fix to be prioritised and implemented via the standard `/plan` -> `/implement` loop.
