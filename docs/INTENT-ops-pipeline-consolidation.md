# INTENT: Consolidate the ops_recommendations write/sync pipeline behind a single agent-facing API

Status: NOT_STARTED  -- planning context for a future session
Author: incident analysis on branch agent/dq-wave2-capabilities-write-validation, 2026-05-09
Audience: planner agent for the next plan that touches `scripts/ops_data_portal.py`,
`scripts/ops_writer.py`, `scripts/sync_ops.py`

## TL;DR for the planner

Today an agent attempting to verify wave-2 DQ acceptance had to run six different commands
(`update_rec`, `sync_ops drain`, `sync_ops pull`, `ops_writer --compact`, `ops_writer
--refresh-views`, `data_quality_runner`) in the right order, with the right env vars, with
the right knowledge of which command silently fails. It didn't. The agent corrupted the
Iceberg `ops_recommendations` table with ~13 partial records (turning DQ verdict from FAIL
to HARD_GATE) by following the documented happy path. **The current architecture leaks the
internal pipeline layers to the agent through five separate CLIs, and at least one of the
mutation primitives (`update_rec`) reads its "existing record" from a cache that another
command (`sync_ops pull`) can silently corrupt.** This must be fixed at the API boundary,
not just by adding more documentation or a wrapper script.

## The incident

### What was attempted

Branch: `agent/dq-wave2-capabilities-write-validation`. Wave 2 of the DQ enforcement arc
ships `compute_automatable()`, write-time structural validators, and 12 prose acceptance
conversions. Acceptance criterion: `validate --integration` passes, which requires
`data_quality_runner` to show zero violations on the wave-2 `ops_recommendations` checks
(`file`/`context`/`acceptance` not-null, context >= 80 chars).

The DQ runner reported 21 violations on `ops_recommendations`:
- 1 file null, 1 context null, 1 acceptance null
- 18 context-length violations (< 80 chars)

The agent's plan: extend the 7 actively-thin contexts to >= 80 chars (the user judged them
too low-value to write fully meaningful contexts), close them, then verify.

### What happened, in order

1. Agent ran `update_rec` 14 times (7 close + 7 context extensions). Local JSONL appended
   each new record. DynamoDB updated. S3 staging files written.

2. Agent ran `sync_ops pull` to refresh the local cache against Athena.
   **`sync_ops pull` overwrote the local JSONL with the stale Athena view's content** -- which
   did NOT yet have the writes from step 1. The local JSONL now reflected the pre-update
   state. The agent's writes were silently invisible locally even though they were committed
   to DynamoDB.

3. Agent ran the DQ runner. Identical violation counts. Diagnosis (correct in part): "the
   Athena view hasn't been compacted yet."

4. Agent triggered `ops_writer --compact ops_recommendations` with `AWS_DEFAULT_REGION=eu-west-2`
   set. The OpsWriter's `_get_client()` correctly reads the `_SSO_PROFILE` constant, but
   the call to `awswrangler.athena.to_iceberg()` further down the function creates its OWN
   boto3 session that does NOT inherit that profile. With only the region env var set,
   awswrangler raised `Unable to locate credentials`. This was caught by a broad `except
   Exception` block, logged as a warning, and the function returned 0.
   **The CLI exit code was 0. Stdout: "Compacted 0 rows for ops_recommendations". Nothing
   surfaced the credential failure to the agent.**

5. Agent re-ran `update_rec` for all 14 recs (correct response to apparent silent failure).
   At line 298 of `ops_data_portal.update_rec`: `existing = _sanitize_athena_record(load_recommendation(rec_id) or {})`.
   `load_recommendation` reads from local JSONL. After step 2's `sync_ops pull`, JSONL has
   only the stale Athena view's records, some of which were already missing fields (the
   pre-existing wave-2 violations).
   **For ~13 of the records, `existing` was a partial dict missing some required fields.**
   `merged = {**existing, **updates}` produced a partial record. `Recommendation.model_validate`
   passed because Pydantic validates field types, not field presence at this depth. OpsWriter
   staged the partial records.

6. Agent re-ran compaction with the correct env vars (`AWS_PROFILE=company-aws-profile
   AWS_DEFAULT_REGION=eu-west-2`). Compacted 39 rows into Iceberg, including the ~13
   partial records.

7. Agent ran the DQ runner. Verdict went from FAIL (64 failures) to **HARD_GATE** (72
   failures). New NULL violations on `id`, `title`, `source`, `effort`, `priority`, `status`,
   `automatable`, `risk` -- all required fields. Existing violations on `file`/`context`/`acceptance`
   *increased* by 5-6 each. The 7 context-length fixes that did land (where `existing` was
   not corrupted) showed up as the only positive delta: 18 -> 11 context-length violations.

### Recovery posture

DynamoDB is intact (it never reads from the JSONL). The Iceberg table is APPEND-only, so the
partial rows are present as the latest snapshot but earlier snapshots have the correct rows.
The fix on the data side is to time-travel-rollback the `ops_recommendations` Iceberg table
to the snapshot prior to today's compaction, OR to re-source the affected ~13 records from
DynamoDB and write them through cleanly.

## What this incident reveals about the architecture

### Five user-facing CLIs, one logical operation

To "make my recommendation update visible to DQ", the agent must run, in order:

| # | Command                                              | Purpose                              | Fails silently? |
|---|------------------------------------------------------|--------------------------------------|-----------------|
| 1 | `python -m scripts.ops_data_portal --update-rec ...` | DynamoDB + S3 staging + JSONL append | No              |
| 2 | `python -m scripts.sync_ops drain`                   | Drain outbox if portal couldn't write directly | Returns `{}` ambiguously |
| 3 | `python -m scripts.ops_writer --compact <table>`     | S3 staging -> Iceberg                | **Yes -- credential errors caught** |
| 4 | `python -m scripts.ops_writer --refresh-views`       | Iceberg -> `_current` views          | No              |
| 5 | `python -m scripts.data_quality_runner`              | Verify the result                    | No              |

Only step 1 is documented in CLAUDE.md as the agent's surface ("Single Portal Invariant").
Steps 2-5 are referenced piecemeal across docs but never as a coherent pipeline. There is
no runbook that says "after a write, do X to make it visible." Agents discover the missing
steps by running into stale data, then trial-and-erroring through the layers.

### `sync_ops pull` is not a sync; it's a destructive reset

Despite the name, `pull` does not merge -- it overwrites the local JSONL with whatever
Athena returns. If the agent has uncommitted changes that haven't propagated through
compaction yet, those changes silently disappear from the local cache. The cache then
becomes the source of "truth" for any subsequent `update_rec`, which propagates the
corruption.

This is a footgun named `pull` that behaves like `git reset --hard`.

### `update_rec` reads "existing" from a cache, not the source of truth

`scripts/ops_data_portal.py:298`:

```python
existing = _sanitize_athena_record(load_recommendation(rec_id) or {})
merged = {**existing, **updates}
```

`load_recommendation` reads from `logs/.recommendations-log.jsonl` -- which is a
gitignored, agent-mutable, sync_ops-overwritable cache. The single most fundamental rule of
mutation primitives ("read-modify-write must read from the source of truth") is violated.
DynamoDB is the source of truth and is reachable; the lookup should go there.

### `OpsWriter.compact()` swallows credential errors

`scripts/ops_writer.py:491-493`:

```python
except Exception as exc:  # noqa: BLE001
    logger.warning("ops_writer.compact: compaction failed for %s: %s", table, exc)
    return 0
```

A bare `except Exception` catches credential errors, network errors, schema errors, and
disk-full errors equally. The function returns 0 (which is also the "no staging files"
success value). The CLI prints `Compacted 0 rows` and exits 0. There is no way for an
agent to distinguish "nothing to do" from "permanent failure" from a single CLI invocation.

### `awswrangler` doesn't inherit OpsWriter's profile

`OpsWriter._get_client()` creates a `boto3.Session(profile_name=_SSO_PROFILE)`. Twenty
lines later, `wr.athena.to_iceberg(...)` is called. awswrangler creates its own boto3
session from process-level env vars (`AWS_PROFILE`, `AWS_DEFAULT_REGION`) and does not
accept a `boto3_session` parameter at this entrypoint. So the OpsWriter's profile choice
is ignored at the actual write boundary. The agent has to know to set both env vars at the
process level. This is not documented.

### Multiple silent-failure modes compose multiplicatively

Each individual silent-failure (caught credential error, sync_ops pull as overwrite,
update_rec reading from cache, awswrangler ignoring session) is benign in isolation. They
*compose* into the incident: silent compaction failure -> agent re-runs update_rec ->
update_rec reads polluted cache -> partial records get staged -> next compaction succeeds
and writes the partial records -> DQ verdict drops one tier.

The architecture has zero seams where the failure could have surfaced before damage.

## The user's instinct, sharpened

The user's read: "agents currently need to run each step of the ops_recommendations
pipeline in order, this is fundamentally incorrect ... the solution should be to make a
single function that agents call that syncs the entire rec log for them."

This is correct in direction. **A single agent-facing API is necessary but not sufficient.**
A wrapper that just chains the five existing commands would have produced exactly the same
incident today, because the underlying primitives (`update_rec` reading from cache,
`compact` swallowing credential errors, `pull` overwriting) would still be load-bearing.
The fix has to be at the primitives layer too.

My recommendation: **rebuild the agent-facing API around three operations, and fix the
underlying primitives so the pipeline can't be skewed by a missed step.**

## Recommended architecture

### Three operations, owned by `ops_data_portal`

1. **`file_rec(fields) -> rec_id`** -- atomic create. Writes to DynamoDB; schedules
   compaction. Returns only after the write is durable in DynamoDB. No JSONL involvement.

2. **`update_rec(rec_id, updates) -> bool`** -- atomic update. Reads existing record from
   DynamoDB (NOT JSONL). Merges. Writes to DynamoDB. Schedules compaction. Returns only
   after the write is durable in DynamoDB.

3. **`sync() -> SyncReport`** -- flush pending compactions and refresh views.
   Idempotent. Returns a structured report listing tables compacted, rows compacted,
   views refreshed, and any errors. Errors are surfaced as exceptions, not warnings.

That's the entire agent-facing surface. Everything else (`drain`, `pull`, raw `compact`,
raw `refresh-views`, direct JSONL access) becomes internal-only -- removed from CLAUDE.md,
documented as "operator-only", and ideally moved out of `scripts/` into a
`scripts/internal/` directory that the linter checks no agent-loaded prompt references.

### Primitive fixes (must land alongside the new API)

a. **`update_rec` reads existing from DynamoDB.** Not from JSONL. JSONL becomes
   write-only-from-portal (last-wins append) and read-only for diagnostics. If DynamoDB is
   unreachable, fail loud rather than silently fall back to JSONL.

b. **`OpsWriter.compact` raises on infrastructure errors.** Distinguish:
   - "no staging files for this date" (returns 0, normal)
   - "infrastructure error: credentials, network, schema mismatch" (raises)
   The current bare `except Exception` is the bug.

c. **`OpsWriter` passes its session to awswrangler.** `wr.athena.to_iceberg` accepts a
   `boto3_session` parameter. Use it. Stop relying on process env vars.

d. **`sync_ops pull` is renamed and constrained.** Rename to `rebuild_local_cache` with
   a big "DESTRUCTIVE" warning. Refuse to run if there are pending writes detected (e.g.,
   any S3 staging files for today not yet compacted). This single guard would have prevented
   today's incident.

e. **JSONL is rebuilt from DynamoDB on demand**, not from Athena. DynamoDB is the source
   of truth; the cache should be derived from it directly. Going through Athena adds a
   compaction lag for no benefit.

f. **Compaction is auto-triggered.** Either:
   - on every write (sync but possibly slow -- acceptable for low-frequency writes), or
   - by a single background process running on the host that watches for staging files.
   Either way, the agent should not have to know the word "compaction" exists.

### Single-Portal Invariant, properly enforced

CLAUDE.md already says "All recommendation and decision writes go through `python -m
scripts.ops_data_portal`." The presence of `scripts/ops_writer.py` and `scripts/sync_ops.py`
as separately-invocable CLIs creates a parallel write surface. Either:
- those files become library-only (no `__main__` block, no CLI), or
- they get a `--internal-only` flag that fails unless an env var is set, or
- they're moved to `scripts/internal/` and the validate.py rec-write-paths check is
  extended to forbid prompt files referencing them.

If the rule is "agents only touch ops_data_portal," the build system must enforce it.

## Out of scope for this consolidation

- The DQ runner, validate.py, and verifier harness are independent of this pipeline and
  should not be modified.
- The Iceberg schema, Athena workgroup, and DynamoDB table structure are stable -- the
  fix is at the Python API boundary, not the storage layer.
- The local outbox pattern (for SSO-unavailable resilience, Decision 57) stays. It's a
  separate concern from the pipeline-step proliferation.

## Decisions the planner will need to make

1. **Compaction trigger model.** Synchronous on every write, periodic background
   process, or hybrid? Synchronous is simplest and aligns with "agent doesn't see the
   pipeline" but adds ~1-2s latency to every write. Background process needs a host to run
   on (the EC2 self-hosted runner is now available -- this becomes feasible).

2. **DynamoDB as canonical read source.** Every `update_rec` becoming a DynamoDB GET adds
   a network round-trip. Acceptable? (DynamoDB GET is ~10ms; trivial vs. a compaction.)

3. **Migration of existing internal CLIs.** Hard-remove or soft-deprecate? Hard-removal
   forces alignment but breaks any operator runbooks. Soft-deprecation lets old runbooks
   continue but lets the parallel-write-surface drift back.

4. **Cache rebuild strategy.** Rebuild from DynamoDB scan (slow but exact) or from Athena
   query (fast but eventually-consistent)? If the cache is purely diagnostic, eventually-consistent
   is fine. If the cache is consulted by any code path other than diagnostics, exact is
   required. The end-state should be: nothing in `scripts/` reads from the JSONL except a
   single dump utility.

5. **Recovery for today's incident.** Iceberg time-travel-rollback to the snapshot prior
   to today's `ops_writer --compact` run, then re-write the affected recs from DynamoDB
   through the (fixed) primitives. This is the smallest-blast-radius fix. The alternative
   (live with the partial records and overwrite each one) leaks complexity into the cleanup
   plan.

## My honest opinion

The user is right that the current shape is wrong. The fix is bigger than they framed it,
but smaller than a rewrite. Three changes do most of the work:

1. `update_rec` reads from DynamoDB (one function, ~5 lines)
2. `OpsWriter.compact` raises on infrastructure errors (one function, ~10 lines)
3. A single `ops_data_portal.sync()` entrypoint replaces drain+compact+refresh (one new
   function, ~30 lines, mostly orchestration)

Those three changes, plus removing the `--compact` / `--drain` / `--refresh-views` /
`pull` CLIs from the agent's allowed surface, make the incident impossible to reproduce.
The "single function for agents" the user wants emerges naturally from this -- it's the
new `ops_data_portal.sync()` plus the existing `file_rec` and `update_rec`.

The deeper architectural lesson: **silent failures compose**. Every `except Exception:
return 0`, every "did this command actually do anything" ambiguity, every CLI that does
two things depending on context, is a contribution to a future incident. The wave-2 work
(write-time validators) was the right move on the WRITE path; this consolidation is the
equivalent move on the SYNC path.
