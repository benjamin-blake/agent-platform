# Plan

## Intent
Land T0.9 (vendor-portable AGENTS.md sidecar via Anthropic's thin-pointer import pattern) plus Phase 1 of T0.14 (Windows-assumption sweep across the slash-command and skill instruction layer). Two effects: (a) AGENTS.md becomes a canonical, single-source-of-truth file readable by Claude Code, Cursor, Copilot, Aider, VS Code, Zed, and Warp without duplication; (b) every slash command and skill body stops prescribing `\.venv/Scripts/python.exe` invocations that fail in Linux container sessions. Both contribute to the user's Phase 2 goal of moving primary development to Claude Code on the web (ephemeral Linux containers) while keeping the Windows compute node usable for PySR.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/agents-md-and-instruction-sweep

## Phase
T0 Bootstrap (T0.9 complete; T0.14 partial — instruction layer only; scripts/ and remaining surfaces deferred to follow-on plans)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `AGENTS.md` | Create | Canonical content. Full port of current root `CLAUDE.md` with the "Shell invocations on Windows" section reframed to "Shell invocations" (OS-agnostic, Windows-host gotchas stripped per user direction). "Role and environment" reframed to reflect Linux-container-primary surface with Windows compute node as PySR compute node. |
| `CLAUDE.md` | Rewrite | Replace with exactly `@AGENTS.md\n` (one line). Anthropic's official import pattern: Claude Code reads CLAUDE.md, follows the import, loads AGENTS.md transitively. Single source of truth = AGENTS.md. |
| `scripts/validate.py` | Modify | Add `check_claude_md_pointer_invariant()` to the standard check suite. Fails (non-zero rc) if root `CLAUDE.md` is anything other than exactly `@AGENTS.md\n`. Registered with the same plumbing as the other validate.py checks (Decision 60 two-tier architecture; this is a presubmit check, not `--pre`). |
| `tests/test_validate.py` | Modify | Add `TestClaudeMdPointerInvariant` class: 1 happy-path test (`@AGENTS.md\n` passes) + 3 failure tests (extra content, wrong target like `@OTHER.md`, empty file). If file does not exist, create it and seed with the test class. |
| `.claude/commands/plan.md` | Modify | Sweep `\.venv/Scripts/python.exe -m ...` → `bin/venv-python -m ...` (4 occurrences). No semantic change; the wrapper resolves to the correct binary per OS. |
| `.claude/commands/implement.md` | Modify | Same sweep (11 occurrences). |
| `.claude/commands/develop-executor.md` | Modify | Same sweep (3 occurrences). |
| `.claude/skills/planning/SKILL.md` | Modify | Same sweep (7 occurrences). |
| `.claude/skills/implement/SKILL.md` | Modify | Same sweep (5 occurrences). |
| `.claude/skills/code-review/SKILL.md` | Modify | Same sweep (4 occurrences). |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Bookkeeping: flip T0.9 `status: not_started` → `complete` with `completed_at: "2026-05-19"`. Add a `notes:` field on T0.14 recording that the instruction layer (commands + skills, 34 occurrences) is swept; remaining surfaces (scripts/, .agents/, src/data/handlers/CLAUDE.md, setup.py) deferred to follow-on plans. |
| `docs/SESSION_LOG.md` | Modify | Bookkeeping: append a session entry summarising the work (T0.9 mechanism chosen = thin-pointer import; instruction-layer sweep complete; PR link). Per the existing session-log convention. |

## Bundled Recommendations
None. The three peripherally-related open recs (rec-405, rec-440, rec-436) either target deep-frozen files or sit at a different layer; bundling would dilute the sweep's atomicity.

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda-packaged files in scope (per Decision 67 deferral). No AWS account state changes.

## Acceptance Criteria
- [ ] `AGENTS.md` exists at repo root with ported content (line count ≥ 80, all sections from current `CLAUDE.md` preserved except Windows-host gotchas)
- [ ] `AGENTS.md` "Shell invocations" section is OS-agnostic; leads with `bin/venv-python` as the canonical Python invocation; contains no Windows-only prescriptions
- [ ] `AGENTS.md` "Role and environment" reframed: dev surface = Claude Code on the web (Linux container); compute node = PySR compute node; explicit removal of "Host is Windows; PowerShell is primary"
- [ ] `CLAUDE.md` content is exactly the bytes `@AGENTS.md\n` (one line, single trailing newline, no whitespace)
- [ ] `scripts/validate.py` includes `check_claude_md_pointer_invariant()` wired into the standard check suite
- [ ] `bin/venv-python -m pytest tests/test_validate.py -k claude_md_pointer -v` reports 4 tests passing
- [ ] `bin/venv-python -m scripts.validate` (standard run, no flags) exits 0
- [ ] `grep -rn '\.venv/Scripts\|python\.exe' .claude/commands/ .claude/skills/` returns zero hits
- [ ] `grep -rn 'bin/venv-python' .claude/commands/ .claude/skills/` returns at least 30 hits (sum of replacements per file counts)
- [ ] `docs/ROADMAP-PLATFORM.yaml` records T0.9 as `status: complete` with `completed_at: "2026-05-19"`; T0.14 has a `notes:` field describing partial progress
- [ ] `docs/SESSION_LOG.md` has a new session entry for `agents-md-and-instruction-sweep` per existing log convention

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | static | AGENTS.md exists with substantive content | `test -f AGENTS.md && wc -l AGENTS.md` | exit 0; line count ≥ 80 | re-port content from CLAUDE.md backup; check git history if accidentally truncated |
| 2 | static | CLAUDE.md is exactly the import pointer | `wc -c CLAUDE.md && cat CLAUDE.md` | byte count = 12 (`@AGENTS.md` = 10 chars + `\n` = 1; some editors add final `\n` = total 11; allow 11 or 12); content prints `@AGENTS.md` | rewrite CLAUDE.md to the exact bytes |
| 3 | static | No Windows venv paths in instruction layer | `grep -rn '\.venv/Scripts\|python\.exe' .claude/commands/ .claude/skills/ \|\| echo CLEAN` | prints `CLEAN` | re-sweep the file that still contains a hit |
| 4 | static | Replacement count meets expected lower bound | `grep -rn 'bin/venv-python' .claude/commands/ .claude/skills/ \| wc -l` | ≥ 30 | re-check each file; a missed occurrence will make the previous step's expected behaviour off |
| 5 | unit | Pointer invariant unit tests pass | `bin/venv-python -m pytest tests/test_validate.py -k claude_md_pointer -v` | 4 passed (1 happy + 3 failure scenarios) | inspect failures; the check must correctly distinguish exact pointer from drift |
| 6 | unit | Pointer invariant catches drift on a synthetic file | `printf '@AGENTS.md\nstray content\n' > /tmp/drifted_claude.md && bin/venv-python -c "from scripts.validate import check_claude_md_pointer_invariant; import sys; sys.exit(0 if not check_claude_md_pointer_invariant('/tmp/drifted_claude.md') else 1)"` | exit 0 (check correctly returns False on drift) | the check is too lax; tighten the byte-equality assertion |
| 7 | unit | Pointer invariant catches wrong import target | `printf '@OTHER.md\n' > /tmp/wrong_target.md && bin/venv-python -c "from scripts.validate import check_claude_md_pointer_invariant; import sys; sys.exit(0 if not check_claude_md_pointer_invariant('/tmp/wrong_target.md') else 1)"` | exit 0 (check correctly returns False) | tighten target match |
| 8 | integration | Full validate.py standard run passes | `bin/venv-python -m scripts.validate` | exit 0; all checks PASS including the new invariant | fix whichever check is failing; the new invariant is the most likely culprit if regressed |
| 9 | integration | bin/venv-python wrapper resolves on current host | `bin/venv-python -m scripts.session_preflight --help 2>&1 \| head -5` | preflight CLI help text prints (any non-empty output that mentions session_preflight or argparse) | venv broken — re-create .venv; or wrapper logic broken — inspect bin/venv-python |
| 10 | integration | Roadmap flip recorded | `grep -B1 -A2 "id: T0.9" docs/ROADMAP-PLATFORM.yaml \| grep -E "status: complete\|completed_at"` | both `status: complete` and `completed_at: "2026-05-19"` print | edit docs/ROADMAP-PLATFORM.yaml under the T0.9 entry |
| 11 | integration | Session log entry appended | `grep -E "^## \[2026-05-19\].*agents-md-and-instruction-sweep" docs/SESSION_LOG.md` | at least one match | append the session entry per existing log convention |
| 12 | integration | New Claude Code session would load CLAUDE.md → AGENTS.md transitively | (manual on next session start) ensure the session-start system reminder shows AGENTS.md content under the claudeMd context block | content visible | this is a property of Claude Code's import resolution; if absent, the `@AGENTS.md` syntax is malformed (check exact bytes) |

## Constraints
- IMPLEMENTATION only (Decision 67 — no STRATEGIC plans until reversal)
- Never edit on `main` (PreToolUse hook `never_on_main.py` enforces; branch is `agent/agents-md-and-instruction-sweep`)
- No `OpsWriter.write()` from local cache (Warehouse-as-source-of-truth invariant)
- No direct edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` (Single Portal Invariant)
- All rec writes (if any during implement) go through `bin/venv-python -m scripts.ops_data_portal --file-rec`
- No rescue agents or workaround loops (Decision 55) — if a check fails unrecoverably, file an RCA rec and stop, do not patch around
- Authoritative pre-merge gate is remote CI (Decision 68); local `validate.py --pre` is advisory only
- No new emojis or em dashes in any edited file (CLAUDE.md/AGENTS.md code style rule)

## Context
- **Why now**: The user is moving primary dev surface to Claude Code on the web. Without this sweep, every fresh Linux container session would see slash-command bodies and skill prose telling it to run `\.venv/Scripts/python.exe`, which does not exist on Linux. PR #339 fixed the 4 hardcoded paths in `.claude/settings.json` and `scripts/session_preflight.py` (T0.1, T0.11), but the instruction layer (44 references across 8 files) was out of scope for that PR.
- **AGENTS.md mechanism decision**: User chose Anthropic's official thin-pointer import pattern over duplicate-with-CI-parity or git-symlink. CLAUDE.md becomes a one-line `@AGENTS.md` pointer; AGENTS.md holds the content. Drift is structurally impossible at the root level because CLAUDE.md has no editable content. Per-directory CLAUDE.md files (e.g. `src/data/handlers/CLAUDE.md`) remain canonical for their subdirectory because Claude Code's per-directory loader does NOT recognise per-directory `AGENTS.md` (per official memory docs). Resolves T0.9 open question OQ.5.
- **"Shell invocations on Windows" reframe**: User chose to strip Windows-host gotchas entirely (heredoc-fails-on-Git-Bash, `subprocess.run(timeout=N)` non-cascading, Microsoft Store shim) rather than preserve as conditional sub-bullets. Rationale: the compute node is a PySR compute node, not an interactive dev surface — those gotchas matter less in the new topology. If a future session on the compute node needs the guidance, it can be reintroduced via a follow-on plan.
- **"Role and environment" reframe**: Currently asserts "Host is Windows; PowerShell is primary". This becomes "Primary dev surface: Claude Code on the web (Linux container, Ubuntu 24.04). compute node is the PySR compute node, reached via REDACTED-VPN + SSH when needed." Aligned with the originating session's strategic-context point 1 in `docs/plans/briefings/BRIEFING-linux-container-migration.md`.
- **What this plan does NOT do**: Sweep `scripts/` (11 occurrences across 6 files), `.agents/` mirrors, `src/data/handlers/CLAUDE.md`, `setup.py`, or `tests/test_setup.py`. Those become Phase 2-4 of T0.14 in follow-on plans. The `.github/prompts/` and `.github/agents/` legacy fallbacks are deep-frozen per CLAUDE.md and stay untouched.
- **Why exceeds advisory 5-file threshold**: User explicitly confirmed the 5-file limit is advisory, and these 12 files are tightly coupled (the AGENTS.md sidecar mechanism is structurally required for any sweep that mentions `@AGENTS.md`, and the instruction-layer sweep is mechanically uniform across `.claude/commands/` and `.claude/skills/`). Splitting into multiple plans would introduce ordering churn and force two separate code-reviews of identical sweep logic.
- **Decision 67 (Lambda deferral)**: No Lambda-packaged files in scope. The `config/`, `scripts/llm_client.py`, `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/` paths are NOT touched. No `DEFERRED: build_lambda.py --deploy` step needed.
- **Decision 55 (no rescue loops)**: If verification step 5 (pytest) fails because the check logic is wrong, fix the check; do not write a wrapper that swallows the failure. If step 8 (validate.py full run) fails on an unrelated check, stop and triage rather than patching around — the failure may indicate pre-existing repo state that warrants its own rec.
- **Friction patterns from preflight**: 5 `CausalChainVerifier heartbeat` patterns surfaced (informational only; this plan does not touch the verifier).
- **Open recs**: 259 open, 186 non-automatable, 0 ci-rca. No hard block.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` returns `agent/agents-md-and-instruction-sweep`)
- [ ] `docs/PROJECT_CONTEXT.md` read for AWS config, file router, recommendation schema, gotchas
- [ ] `docs/DECISIONS.md` read for Decision 55, 57, 60, 67, 68, 73 (the constraints cited above)
- [ ] `docs/plans/briefings/BRIEFING-linux-container-migration.md` read for the strategic context behind T0.9 and T0.14
- [ ] `docs/ROADMAP-PLATFORM.yaml` T0.9 and T0.14 entries read in full
- [ ] All 12 files in Scope table located and readable
- [ ] Current `CLAUDE.md` backed up mentally / via git history before rewrite (the canonical content moves to AGENTS.md, so verbatim port is critical)
- [ ] Acceptance Criteria understood and verifiable
- [ ] Existing `tests/test_validate.py` (if any) read to match its test-class style

## Ordered Execution Steps

1. **Read source state.** Read current `CLAUDE.md` in full (the canonical content to be ported). Read `scripts/validate.py` to find the existing check-registration pattern (how `check_*` functions are wired into the standard run). Read existing `tests/test_validate.py` (if any) to match its style; if absent, plan to create one.

2. **Author AGENTS.md.** Create `AGENTS.md` at repo root. Port full content of current `CLAUDE.md` verbatim with two surgical edits: (a) rename section "Shell invocations on Windows" → "Shell invocations" and rewrite its body as OS-agnostic prose leading with `bin/venv-python` (no Windows-host bullets); (b) rewrite "Role and environment" section so it asserts Linux-container-primary surface with compute node as PySR compute node. Preserve every other section byte-for-byte: "Code style", "Safety", "Branching", "Temporary Operational Constraints", "Memory policy", "Agent-First Repository", "Skills and slash commands", "Operational data governance", "Warehouse-as-source-of-truth invariant", "Merge protocol", "Instruction architecture", "Operational runbooks". No new emojis, no em dashes.

3. **Rewrite CLAUDE.md.** Overwrite `CLAUDE.md` with exactly the two bytes `@AGENTS.md` followed by `\n`. Verify byte count: `wc -c CLAUDE.md` should report 11 (10 chars + LF).

4. **Add the pointer invariant check.** In `scripts/validate.py`, add `check_claude_md_pointer_invariant(path: str = "CLAUDE.md") -> bool` that reads the file and returns True iff its content is exactly `@AGENTS.md\n`. Wire it into the standard check registry (whatever the existing pattern is — e.g. add a row to a CHECKS list, or append to a registered-checks decorator chain). Surface its name in the failure summary if it fails. The check is presubmit-tier, not `--pre`.

5. **Add unit tests.** In `tests/test_validate.py` (extend if exists, create if absent), add a `TestClaudeMdPointerInvariant` class with 4 methods: `test_happy_path` (write `@AGENTS.md\n` to tmp, expect True), `test_extra_content` (write `@AGENTS.md\nstray\n`, expect False), `test_wrong_target` (write `@OTHER.md\n`, expect False), `test_empty_file` (write empty string, expect False). Use `tmp_path` fixture per pytest convention.

6. **Sweep `.claude/commands/`.** In each of `plan.md`, `implement.md`, `develop-executor.md`, replace every occurrence of `\.venv/Scripts/python.exe -m` with `bin/venv-python -m`. Replace any bare `\.venv/Scripts/python.exe` (no `-m`) with `bin/venv-python`. Do NOT introduce any new mentions of `python.exe`. Verify per-file counts match expected: plan.md (4), implement.md (11), develop-executor.md (3).

7. **Sweep `.claude/skills/`.** Same mechanical sweep in `planning/SKILL.md` (7), `implement/SKILL.md` (5), `code-review/SKILL.md` (4). Note: `planning/SKILL.md` is the skill body already loaded into this very session; re-read after editing to confirm no markdown structure was inadvertently damaged.

8. **Run the sweep-completeness greps.** `grep -rn '\.venv/Scripts\|python\.exe' .claude/commands/ .claude/skills/` must return zero hits. `grep -rn 'bin/venv-python' .claude/commands/ .claude/skills/` must return ≥ 30. If either fails, return to step 6 or 7 for the offending file.

9. **Run the Verification Plan.** Execute every numbered step in the VP. Loop on any failure: fix the underlying cause (per Decision 55, do not work around). If V2 step 5 or 6 fails unrecoverably, stop and analyse root cause — this is more likely an issue with the new check than a wider problem.

10. **Invoke the code-review skill.** `bin/venv-python -m scripts.agent_development.run_skill --skill code-review --session-id <UUID>` per the implement workflow. Address any HIGH-severity findings; file MEDIUM/LOW as recs via `bin/venv-python -m scripts.ops_data_portal --file-rec`.

11. **(In parallel with code-review running) Bookkeeping step 1 — update the platform roadmap.** Edit `docs/ROADMAP-PLATFORM.yaml`: under the `T0.9` entry, flip `status: not_started` → `status: complete` and add `completed_at: "2026-05-19"`. Under the `T0.14` entry, add a `notes:` field recording that the instruction layer (44 Windows-path references across 8 files in `.claude/commands/` and `.claude/skills/`) is swept; Phase 2 (scripts/, ~11 occurrences across 6 files) and Phase 3 (.agents/, src/data/handlers/CLAUDE.md, setup.py) deferred to follow-on plans. T0.14 status stays `not_started` since full completion requires the deferred phases.

12. **(In parallel with code-review running) Bookkeeping step 2 — update the session log.** Append an entry to `docs/SESSION_LOG.md` following the existing convention (date heading, slug, summary, PR link placeholder). Summary should note: T0.9 mechanism = thin-pointer import per Anthropic memory docs; T0.14 Phase 1 (instruction layer) complete; 44 Windows-path references swept; follow-on phases enumerated.

13. **Final report.** Summarise: what was implemented, verification results, any HIGH-severity code-review findings addressed, any MEDIUM/LOW filed as recs. Confirm `git status` is clean and the branch is push-ready.
