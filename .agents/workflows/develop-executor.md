# Workflow: Develop Executor (RCA)

**Purpose**: Execute Root Cause Analysis (RCA) on unrecoverable executor failures, as mandated by Decision 55.
**Trigger**: Slash command `/develop-executor`

## 1. Context Gathering
- Ask the user to specify the failure context if not provided (e.g., a specific `rec-NNN` or transcript path).
- Read the most recent failure transcript in `logs/transcripts/` or the latest exception in `logs/.telemetry-process-events.jsonl` matching the context.

## 2. Execute RCA Skill
- Run the Executor RCA skill in a fresh context to ensure unbiased diagnosis:
  ```bash
  python -m scripts.agent_development.run_skill --skill executor-rca --target <path_to_failure_transcript> --model auto
  ```
- Wait for the skill to output its root cause analysis and the generated recommendation JSON.

## 3. Log Recommendation
- Parse the `.recommendations-log.jsonl` file to find the highest existing `rec-NNN`.
- Replace the placeholder `rec-NNN` in the skill's JSON output with the next incremented ID.
- Append the JSON line to `logs/.recommendations-log.jsonl`.

## 4. Stop Cleanly
- **CRITICAL INVARIANT:** Do not attempt to repair the failure. Do not apply workarounds.
- Terminate the workflow, leaving the fix to be prioritized and implemented via the standard `/plan` -> `/implement` loop.
