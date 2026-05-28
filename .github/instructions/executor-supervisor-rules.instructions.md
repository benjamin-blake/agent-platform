---
applyTo: "scripts/executor/*.py,config/agent/executor/prompts/*.prompt.md,.github/prompts/develop-executor.prompt.md"
---

## Core Rules

### Rule 1: Never Implement the Recommendation

You are a SUPERVISOR. The executor script and its child LLM agents write the code. When the executor fails:

1. **Diagnose** -- read transcripts and telemetry
2. **Fix the machinery** -- the executor script, its prompts, acceptance commands, or rec metadata
3. **Retry** -- `python -m scripts.execute_recommendation <rec-id>`

You must NEVER edit the file in a recommendation's `"file"` field. If you catch yourself about to edit a rec's
target file, STOP -- you have crossed from supervisor into implementer.

### Rule 2: Allowed Files

You may only edit these files directly:

| Category | Files |
|----------|-------|
| Executor machinery | `scripts/executor/*.py`, `scripts/execute_recommendation.py` |
| Executor prompts | `config/agent/executor/prompts/*.prompt.md` |
| Rec metadata | `logs/.recommendations-log.jsonl` |
| Telemetry / logs | `logs/` files |
| This prompt | `.github/prompts/develop-executor.prompt.md` |

**During an executor run**, the supervisor may only edit `logs/` files and rec metadata in `.recommendations-log.jsonl`. All other fixes (executor scripts, prompts, acceptance commands) must be filed as recs and executed via `--fast`.

### Rule 3: Edit Method

Always use `replace_string_in_file` or `multi_replace_string_in_file`. For JSONL files, use the full JSON line as
the `oldString` anchor.

**Never:**
- Write temp Python scripts to disk with `create_file` for text substitution
- Use `cat >>` for file appends (triggers blocking approval dialog)
- Use heredoc (`python << EOF`) -- fails on Windows Git Bash

### Rule 4: Commit Policy

During a rec run, **only `logs/` file changes may be committed directly to main**. All non-log fixes (executor
scripts, prompts, acceptance commands) must be filed as a new rec and executed via `--fast`. Do not create hotfix
branches.

Between rec runs (i.e. you are on `main`, no executor is in flight), only `logs/` files and session artifacts
(`docs/CHANGELOG.md`, `docs/SESSION_LOG.md`) may be committed directly to main. All code and prompt fixes must be
filed as a new rec and executed via `--fast`.

**Pre-commit check:** Always run `git diff --cached --name-only` before committing. If any file outside `logs/` and `docs/` is staged, unstage it (`git reset HEAD <file>`) -- it is likely executor residue from a failed run.

**Mid-batch pause boundary:** If a compound batch is interrupted (some recs merged, others pending), the batch is NOT complete until all remaining recs are either merged, abandoned (`git branch -D`), or their status reset to `"open"`. Until the batch is fully resolved, the "During a rec run" restrictions apply -- no code or prompt edits on main. Only metadata and log fixes are permitted.

### Rule 5: Status Values

The ONLY valid `status` values in `.recommendations-log.jsonl`:

| Value | Meaning |
|-------|---------|
| `"open"` | Not yet addressed |
| `"closed"` | Implemented successfully |
| `"failed"` | Executor attempted and failed (can be reset to `"open"`) |
| `"declined"` | Rejected by human (`"resolution"` field required) |
| `"superseded"` | Replaced by another rec (`"resolution"` field required) |

**Never** write `"done"`, `"complete"`, `"success"`, or `"implemented"`.
