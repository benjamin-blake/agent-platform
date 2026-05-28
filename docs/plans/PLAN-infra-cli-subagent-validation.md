# Plan

## Intent

Validate subagent-to-CLI invocation pattern (rec-027), archive resolved recommendations (rec-021), and complete transcript storage infrastructure (rec-029). These are independent, low-risk improvements that collectively advance the CLI migration roadmap.

## Plan Type

DEFINED_SCOPE

## Branch

agent/infra-cli-subagent-validation

## Phase

Infra (workflow infrastructure)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/DECISIONS.md` | Modify | Document rec-027 experimental findings |
| `docs/RECOMMENDATIONS.md` | Modify | Remove strikethrough rows (moved to archive) |
| `docs/RECOMMENDATIONS_ARCHIVE.md` | Create | Storage for resolved recommendations |
| `logs/transcripts/README.md` | Modify | Add archival policy and index format spec |
| `logs/.transcript-index.jsonl` | Create | Machine-readable transcript index |
| `scripts/transcript_index.py` | Create | Script to regenerate index from transcripts/ |
| `tests/test_transcript_index.py` | Create | Unit tests for transcript_index.py |
| `logs/.recommendations-log.jsonl` | Modify | Update rec-021, rec-027, rec-029 status to closed |

## Acceptance Criteria

### rec-027: Subagent CLI Invocation
- [ ] Experiment executed: subagent invokes `copilot --version` via shell tool
- [ ] Experiment executed: subagent invokes `copilot -p "echo test" -s --no-ask-user` (non-interactive)
- [ ] Results documented in DECISIONS.md with success/failure, error messages if any
- [ ] Pattern characterized: context inheritance, permission inheritance, failure modes

### rec-021: Archive Resolved Recommendations
- [ ] `RECOMMENDATIONS_ARCHIVE.md` created with all resolved rows from `RECOMMENDATIONS.md`
- [ ] `RECOMMENDATIONS.md` contains only open items (removes ~80% of content)
- [ ] Archive has same table format as original for consistency

### rec-029: Transcript Storage Infrastructure
- [ ] `logs/transcripts/README.md` includes archival policy (90 days local, then archive)
- [ ] `logs/.transcript-index.jsonl` schema defined and empty file created
- [ ] `scripts/transcript_index.py` can scan `logs/transcripts/` and rebuild index
- [ ] 5+ unit tests for transcript_index.py

## Constraints

- No production code changes (infra/docs only)
- rec-027 experiments must not break any existing functionality
- Haiku-appropriate: straightforward file operations and documentation

## Ordered Execution Steps

### Step 1: rec-027 Experiment Setup
**Files:** None (shell commands only)
**Action:** Run diagnostic commands to establish baseline CLI availability from agent context.
```bash
which copilot
copilot --version
```
**Acceptance:** Commands execute and return expected output.

### Step 2: rec-027 Subagent CLI Test
**Files:** None (shell commands only)
**Action:** Invoke the Explore subagent with a prompt that requires it to run `copilot --version` via shell tool. Capture whether the subagent can invoke CLI commands.
**Acceptance:** Document whether subagent successfully invokes CLI, or fails with permission/tool error.

### Step 3: rec-027 Document Findings
**Files:** `docs/DECISIONS.md`
**Action:** Add Decision 31 documenting:
- Experiment methodology
- Success/failure results
- Implications for Phase B (rec-002, rec-028)
- Recommended patterns for subagent CLI invocation
**Acceptance:** Decision 31 exists with complete findings.

### Step 4: rec-021 Create Archive File
**Files:** `docs/RECOMMENDATIONS_ARCHIVE.md`
**Action:** Create archive file with header and table structure matching RECOMMENDATIONS.md.
**Acceptance:** File exists with proper markdown table headers.

### Step 5: rec-021 Move Resolved Rows
**Files:** `docs/RECOMMENDATIONS.md`, `docs/RECOMMENDATIONS_ARCHIVE.md`
**Action:** Move all strikethrough (resolved) rows from RECOMMENDATIONS.md to RECOMMENDATIONS_ARCHIVE.md.
**Acceptance:** RECOMMENDATIONS.md contains only open items; archive contains all resolved items.

### Step 6: rec-029 Update Transcript README
**Files:** `logs/transcripts/README.md`
**Action:** Add archival policy section:
- Local retention: 90 days
- Archive destination: `logs/transcripts/archive/` (future: S3/LFS)
- Index file: `.transcript-index.jsonl`
**Acceptance:** README includes archival policy with specific retention period.

### Step 7: rec-029 Create Transcript Index Schema
**Files:** `logs/.transcript-index.jsonl`
**Action:** Create empty JSONL file with schema comment:
```
# Schema: {"path": "...", "session_id": "...", "branch": "...", "timestamp": "...", "size_bytes": N}
```
**Acceptance:** File exists with schema comment.

### Step 8: rec-029 Create transcript_index.py
**Files:** `scripts/transcript_index.py`
**Action:** Create script with functions:
- `scan_transcripts(dir: Path) -> list[dict]` — scan directory for .md files
- `build_index(transcripts: list[dict]) -> None` — write to JSONL
- `main()` — CLI entry point with `--rebuild` flag
**Acceptance:** Script runs without errors; `python scripts/transcript_index.py --rebuild` produces valid JSONL.

### Step 9: rec-029 Create Tests
**Files:** `tests/test_transcript_index.py`
**Action:** Create 5+ unit tests:
- `test_scan_empty_directory`
- `test_scan_with_transcripts`
- `test_build_index_creates_jsonl`
- `test_index_schema_valid`
- `test_cli_rebuild_flag`
**Acceptance:** All tests pass; coverage for transcript_index.py ≥ 80%.

### Step 10: Update Recommendation Status
**Files:** `logs/.recommendations-log.jsonl`
**Action:** Set status to "closed" for rec-021, rec-027, rec-029.
**Acceptance:** grep confirms all three have `"status": "closed"`.

### Step 11: Validate and Commit
**Files:** All modified files
**Action:** Run `python scripts/validate.py` and commit if passing.
**Acceptance:** validate.py exit 0; commit succeeds.

## Dependencies

- rec-006 (--share transcripts): CLOSED — prerequisite for rec-029
- No other blocking dependencies

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Subagent cannot invoke shell tool | Document limitation; proceed with agent-level CLI calls only |
| Copilot CLI not available in subagent context | Expected possible outcome; document and adjust Phase B plans |
| RECOMMENDATIONS.md format varies | Manual review of moved rows |

## Estimated Effort

- rec-027: S (1-2 experiments + documentation)
- rec-021: XS (mechanical file move)
- rec-029: S (script + tests)
- **Combined: M** (3-4 hours)
