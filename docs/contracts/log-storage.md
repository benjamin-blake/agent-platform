# Boundary Contract: Log Storage Patterns

## Overview

All JSONL log files in this repository follow one of three storage
patterns. Each pattern defines who produces the data, where it lands,
and how other components read it.

## Pattern 1 -- Cloud-Produced

Lambda functions write JSONL objects directly to S3 under the
`agent-platform-agent-logs` bucket. Local readers retrieve them
via `s3_log_store.read_jsonl()`.

**Flow:** Lambda handler --> S3 --> `s3_log_store.read_jsonl(key)`

**Examples:** scheduled-agent findings, curator findings.

## Pattern 2 -- Locally-Produced

Local scripts write JSONL to the `logs/` directory on disk. When S3
sync is needed, `s3_log_store.append_jsonl(key, entry)` pushes the
entry to S3 on demand. The local file remains the source of truth for
git-tracked artefacts.

**Flow:** script --> `logs/<file>.jsonl` --> `s3_log_store.append_jsonl(key, entry)` --> S3

**Examples:** `.recommendations-log.jsonl`, `.retro-lite-log.jsonl`,
`.session-telemetry.jsonl`, `.execution-step-telemetry.jsonl`,
`.friction-analysis-log.jsonl`, `.north-star-log.jsonl`.

## Pattern 3 -- Shared-Mutable (Planned)

A dedicated `log_writer.py` module will provide atomic read-modify-write
semantics for JSONL files that multiple agents update concurrently.
This pattern is tracked by rec-386 and is not yet implemented.

**Flow (planned):** caller --> `log_writer.write(key, entry)` --> local file + S3

## Priority Queue

### Canonical Path

```
priority-queue/.priority-queue.jsonl
```

The canonical S3 key is `priority-queue/.priority-queue.jsonl` (Decision 45).
The local path is `logs/priority-queue/.priority-queue.jsonl`.

The path `logs/.priority-queue.jsonl` (root of logs/) is the **old path** and
must not be used.

### Status Tags

| Tag | Canonical? | Meaning |
|-----|------------|---------|
| `"queued"` | Yes | Entry is waiting to be picked up by the executor |
| `"executing"` | Yes | Entry is currently being processed |
| `"done"` | Yes | Entry has been completed |
| `"active"` | **No** | Legacy path -- must not be used in new code |

Canonical values: `"queued"`, `"executing"`, `"done"`.

### Canonical Producer (Phase 1+)

Scheduled agents produce `type: "priority-queue-entry"` findings and pass
them to `enqueue_findings()` in `scripts/ops_data_portal.py`, which files
each via `file_rec` (writer-allocated, loud-fail -- Decision 84; no local
buffering). The Decision-70 current-state semantics (all entries of the
latest `queue_run_id`) live INSIDE the reader's `priority_queue_current`
named verb -- the canonical read source for all consumers.

> Legacy producer note: the dormant rec-curator Lambda flow still stages
> queue rows via `scripts/s3_log_store.py` -> OpsWriter/Iceberg; it MUST be
> repointed to the boundary before re-enable (T2.26; see the AGENTS.md
> re-enable runbook caveat).

- **Consumer:** `session_preflight.py` reads the `priority_queue_current`
  verb via the DuckLake reader. Hard-exits on verb failure with creds ok --
  no silent fallback (Decision 57/60); creds-down degrades to the local
  cache with a staleness warning.
- **Local JSONL (`logs/priority-queue/.priority-queue.jsonl`):** read cache
  only (degraded-mode fallback). Never a write source.

### Legacy Producer (deprecated, active until Phase 5)

- **Producer:** `rec-curator.prompt.md` (`.github/prompts/scheduled/`)
  emits `type: "priority-queue-entry"` findings in the Step 6 JSON array
  (stdout). The `findings_processor_handler.py` Lambda detects these and
  writes them to S3 via `overwrite_jsonl("priority-queue/.priority-queue.jsonl", ...)`.
- **Write function:** `s3_log_store.overwrite_jsonl(key, entries)` provides
  full-replace semantics (put_object). Use this for priority queue -- not
  `append_jsonl`.

## Date Last Verified

2026-05-06

## Verified

This contract reflects the storage patterns implemented in
`scripts/s3_log_store.py` (`read_jsonl`, `append_jsonl`, `overwrite_jsonl`,
`get_backend`) and the queue pipeline defined in
`.github/prompts/scheduled/rec-curator.prompt.md` (Step 5/6) and
`src/data/handlers/findings_processor_handler.py` (priority-queue-entry routing).
