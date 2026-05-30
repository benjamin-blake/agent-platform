# Plan

## Intent
Sweep factually-wrong, present-tense references to retired legacy systems (company AWS account, private repo, local/Windows/Antigravity dev) out of the live, actively-loaded knowledge base so every downstream agent operates on correct ambient context. Accurate context is a precondition for the self-improving loop (North Star): an agent that reads "you are on a Windows host, use `aws sso login`" makes wrong moves.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2 (Decision 48: scope modifies pure-Python `scripts/` source -- `setup.py`, `scripts/session_postflight.py` -- with no external integration, so unit tests must exercise the real changed code paths and the 100%-coverage gate applies; the docs/config portions are V1. No V3 trigger: no file is Lambda-packaged, no `.tf`, no cross-service contract.)

## Branch
`claude/cool-volta-I7b2X`

> Deviation note: this session's harness directive pins all work to `claude/cool-volta-I7b2X`, so the plan is authored here rather than on a generated `agent/{slug}` branch. If `/implement`'s `find_plan.py` cannot auto-locate the plan from the branch name, pass the path explicitly: `docs/plans/PLAN-legacy-reference-sweep.md`.

## Phase
Platform -- post-migration hygiene. No exact `tier_item` (soft-warn: `user_explicit_out_of_scope`); nearest eligible item is T0.2 (Claude Code on the web env definition). This is **Plan 1 of a 2-plan split**; the deferred Plan 2 (legacy agent-surface retirement) maps to tier item **T5.3**.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/PROJECT_CONTEXT.md` | Modify | Lines 5 (Windows host -> Linux container/bash/`bin/venv-python`), 15 (drop "no Docker on company VM"), 37 (SSO -> static-key assume-role), 238 (pyenv 3.11.9 / `.venv/Scripts` / `C:/Users` -> Python 3.12+ / `bin/venv-python`). **DO NOT touch File Router rows 147-173** (they reference paths Plan 2 deletes). |
| `docs/GETTING_STARTED.md` | Modify | VS Code/PowerShell venv activation, `aws sso login`, `formulas-*` buckets, "company VM", Windows `netstat` -> Linux/static-key/`agent-platform-data-lake`. Replace with current procedure (present tense). |
| `docs/ARCHITECTURE.md` | Modify | Credential section `aws sso login --profile company-aws-profile` -> static-key/`agent_platform`; `formulas-*` diagram + prose -> `agent-platform-data-lake`. |
| `docs/ARCHITECTURE-WORKFLOW.md` | Modify | `company-aws-profile` in the SSO check (~138) and portal-drain snippet (~357) -> `agent_platform`. Leave the `schedule.yaml` provider-routing line (~417) -- deferred/Plan 2. |
| `README.md` | Modify | Public-facing quickstart: `aws sso login` + `formulas-*` -> static-key + `agent-platform-data-lake`. |
| `.claude/skills/planning/SKILL.md` | Modify | Line 9: drop non-existent `GEMINI.md` from the never-modify list. Line 262: "Verify shell commands are Windows-compatible" -> Linux/bash + `bin/venv-python`. |
| `src/data/handlers/CLAUDE.md` | Modify | Lines 9-11: `.venv/Scripts/python.exe` (x3) -> `bin/venv-python` (live instruction bug). |
| `tests/CLAUDE.md` | Modify | Line 24: "Windows Git Bash compatibility" rationale -> "shell-quoting fragility" (the rule banning `python -c` one-liners is unchanged). |
| `docs/DECISIONS.md` | Modify | Append a dated past-tense migration-update pointer to **Dec 60, Dec 68, Dec 71, Dec 72 (Branch-Protection, ~line 470 -- NOT the same-numbered RCA record at ~line 159), Dec 24, Dec 62**. Convert present-tense retired-infra statements (self-hosted EC2 runner, `aws sso login`, `company-aws-profile`) to past tense + pointer to CD.21 / Dec 73 / static-key model. **Preserve historical rationale verbatim.** Markdown source only -- do NOT edit `logs/.decisions-index.jsonl`. |
| `docs/INTENT-ci-cd-architecture.md` | Modify | Present-tense **operational** statements only: substrate section (self-hosted EC2 runner as current/proposed substrate), credential-fallback tiers (~140-144), profile table (~379-381) -> past tense + CD.21 pointer. Leave design narrative. |
| `docs/INTENT-validation-architecture.md` | Modify | Substrate section (~80-89, self-hosted EC2 runner) -> past tense + CD.21 pointer. Leave the validation-tier design. |
| `docs/INTENT-telemetry-system.md` | Modify | Line ~717 "the system runs on a Windows host" present-tense constraint -> Linux container (the UTC requirement and `pathlib.Path` rationale stay). |
| `setup.py` | Modify | **Surgical.** Add a deprecation header pointing to `bin/setup-cloud-env.sh` as the canonical CC-web/Linux setup; correct user-facing `company-aws-profile` / `aws sso login` strings -> `agent_platform` / static-key. **LEAVE `check_gemini_cli()` and its "Decision 53" citation byte-for-byte (Dec 67/CD.17 freeze carve-out). LEAVE `fix_venv_activate_for_git_bash()` present (Dec 27, soft-deprecated via header).** |
| `tests/test_setup.py` | Modify | Update coverage for the changed `setup.py` strings/header (test_coverage_checker requires 100% for modified source). |
| `scripts/session_postflight.py` | Modify | The credential-failure fallback (~line 670) that invokes `aws sso login` (hangs/fails under static-key) -> emit a static-key refresh error message instead. |
| `tests/test_session_postflight.py` | Modify | Add/adjust a test asserting the credential-failure path does NOT spawn `aws sso login` and emits the static-key guidance. (Opportunistically addresses rec-657's missing `check_sso` mock if trivial.) |
| `config/config.personal.yaml` | Modify | Remove the "Company S3 Access" section and `formulas-production` / `formulas-staging` keys (scout verified: no live reader). If a live reader is found at implement time, repoint to `agent-platform-data-lake` instead of removing. |

## Bundled Recommendations
None formally bundled. Adjacent (same file, optional): **rec-566** (document `PLAN_TOKEN_BUDGET` in `PROJECT_CONTEXT.md`) -- address only if trivially in the same edit; otherwise leave for its own pass. **rec-657** (postflight test mocks) is partially touched by the `tests/test_session_postflight.py` change.

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda-packaged file in scope (`config/config.personal.yaml` is NOT `config/config.yaml`), so no `build_lambda --deploy` / smoke-test step is required (Dec 67/CD.17).

## Acceptance Criteria
- [ ] Operational/ambient docs (`PROJECT_CONTEXT.md`, `GETTING_STARTED.md`, `ARCHITECTURE.md`, `ARCHITECTURE-WORKFLOW.md`, `README.md`) contain no `company-aws-profile`, no `formulas-{discovery,staging,production}`, no `.venv/Scripts`, no `C:/Users`, and no `pyenv ... 3.11` as current instructions.
- [ ] `PROJECT_CONTEXT.md` states the current dev surface ("Linux container", `bin/venv-python`) and static-key credential model.
- [ ] `.claude/skills/planning/SKILL.md` no longer references `GEMINI.md` and has no "Windows-compatible" instruction.
- [ ] `src/data/handlers/CLAUDE.md` uses `bin/venv-python` (no `.venv/Scripts/python.exe`).
- [ ] DECISIONS 60/68/71/72(branch)/24/62 each carry a dated 2026-05 migration-update pointer; retired-infra present-tense statements are past-tensed; historical rationale is unchanged (no net rationale deletion).
- [ ] INTENT docs (`ci-cd-architecture`, `validation-architecture`, `telemetry-system`) no longer assert retired infra / Windows-host in present tense; design narrative preserved.
- [ ] `setup.py`: deprecation header present and points to `bin/setup-cloud-env.sh`; `company-aws-profile`/SSO strings corrected; `check_gemini_cli()` and the "Decision 53" citation are byte-for-byte unchanged; `fix_venv_activate_for_git_bash()` still defined.
- [ ] `scripts/session_postflight.py` invokes no `aws sso login`; the credential-failure path emits static-key refresh guidance.
- [ ] `config/config.personal.yaml` has no `formulas-*` / "Company S3 Access" section and still parses.
- [ ] Deferred/Plan-2 surfaces untouched: `.agents/`, `.github/{prompts,agents,instructions,copilot-instructions.md}`, `scripts/{validate,prompt_compliance,list_customizations,session_preflight}.py`, executor machinery, and Gemini/Copilot/Bedrock/Lambda references are unchanged.
- [ ] `bin/venv-python -m scripts.validate` passes (full presubmit: lint, format, unit tests, coverage, prompt-compliance).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-merge | Unambiguous legacy tokens gone from operational docs | `! git grep -nE "company-aws-profile\|formulas-(discovery\|staging\|production)\|\.venv/Scripts\|C:/Users\|pyenv[^\n]*3\.11" -- docs/PROJECT_CONTEXT.md docs/GETTING_STARTED.md docs/ARCHITECTURE.md docs/ARCHITECTURE-WORKFLOW.md README.md` | Exit 0 (no matches printed) | A match means a stale current-instruction token survives in that file -> replace with current truth |
| 2 | pre-merge | Operational docs assert current truth | `git grep -q "Linux container" -- docs/PROJECT_CONTEXT.md && git grep -q "bin/venv-python" -- docs/PROJECT_CONTEXT.md && git grep -q "agent_platform" -- docs/GETTING_STARTED.md` | Exit 0 | Missing current-state statement -> add it |
| 3 | pre-merge | Planning skill cleaned | `! git grep -nE "GEMINI\.md\|Windows-compatible" -- .claude/skills/planning/SKILL.md` | Exit 0 (no matches) | Residual `GEMINI.md` / Windows note -> remove/replace |
| 4 | pre-merge | Handler instruction venv fixed | `! git grep -nE "\.venv/Scripts" -- src/data/handlers/CLAUDE.md && git grep -q "bin/venv-python" -- src/data/handlers/CLAUDE.md` | Exit 0 | `.venv/Scripts` remains -> replace with `bin/venv-python` |
| 5 | pre-merge | Decision addenda present (all 6) | `test "$(grep -cE "2026-05 migration update" docs/DECISIONS.md)" -ge 6` | Exit 0 (>=6 dated pointers) | Fewer than 6 -> a target decision is missing its past-tense migration pointer |
| 6 | pre-merge | INTENT present-tense Windows claim gone | `! git grep -q "runs on a Windows host" -- docs/INTENT-telemetry-system.md && git grep -qiE "retired\|CD\.21\|GitHub-hosted" -- docs/INTENT-ci-cd-architecture.md docs/INTENT-validation-architecture.md` | Exit 0 | Present-tense Windows claim remains, or substrate sections lack a retirement pointer |
| 7 | pre-merge | setup.py surgical: freeze carve-out intact + deprecation added | `git grep -q "Decision 53" -- setup.py && git grep -q "check_gemini_cli" -- setup.py && git grep -q "fix_venv_activate_for_git_bash" -- setup.py && git grep -qi "deprecat" -- setup.py && git grep -q "bin/setup-cloud-env.sh" -- setup.py && ! git grep -q "company-aws-profile" -- setup.py` | Exit 0 | Carve-out removed, or deprecation/redirect missing, or `company-aws-profile` string remains |
| 8 | pre-merge | setup.py behaviour | `bin/venv-python -m pytest tests/test_setup.py -q` | Pass | Failing test -> fix logic/strings or test expectations |
| 9 | pre-merge | postflight no SSO login + static-key path | `! git grep -nE "\"sso\", *\"login\"\|sso login" -- scripts/session_postflight.py && bin/venv-python -m pytest tests/test_session_postflight.py -q` | Exit 0 + pass | `aws sso login` remains, or the credential-failure test is missing/failing |
| 10 | pre-merge | config.personal.yaml cleaned + parses | `! git grep -nE "formulas-(production\|staging\|discovery)\|Company S3 Access" -- config/config.personal.yaml && bin/venv-python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('config/config.personal.yaml').read_text())"` | Exit 0 (no matches, parses) | Section remains or YAML breaks |
| 11 | pre-merge | Deferred/Plan-2 surfaces untouched | `! git diff --name-only "$(git merge-base origin/main HEAD)" HEAD \| grep -E "^(\.agents/\|\.github/(prompts\|agents\|copilot-instructions)\|scripts/(validate\|prompt_compliance\|list_customizations\|session_preflight)\.py\|scripts/executor/\|config/lambda/)"` | Exit 0 (no matches) | A deferred/Plan-2 file was modified -> revert it; out of Plan 1 scope |
| 12 | pre-merge | Full presubmit (authoritative local gate) | `bin/venv-python -m scripts.validate` | Exit 0 | Any failure -> fix and re-run; loop until green (remote CI is the final authority per Merge Protocol) |

> VP note: Step 10's `python -c` is a one-shot YAML-parse probe inside a plan VP (not a rec acceptance command, where `python -c` is banned); if the project exposes a config-loader module or test, prefer it. All other steps are `git grep`/`pytest`/`validate` and are bash/Linux-native.

## Constraints
- **Past-tense / pointer-fix only for historical records.** In `DECISIONS.md` and `INTENT-*.md`, convert present-tense descriptions of retired infra to past tense + a dated pointer to the superseding decision (CD.21 / Dec 73 / static-key). NEVER rewrite the historical rationale ("why we decided"). User directive + the repo's supersede-don't-rewrite convention.
- **setup.py edits are surgical.** Leave `check_gemini_cli()` and its "Decision 53" citation byte-for-byte (Dec 67/CD.17 executor freeze). Leave `fix_venv_activate_for_git_bash()` defined (Dec 27); only the deprecation header marks it dormant. Do not refactor logic beyond correcting the migration-factual strings.
- **Do NOT touch deferred surfaces** (Plan 2 / freeze): `.agents/`; `.github/{prompts,agents,instructions,copilot-instructions.md}`; `scripts/{validate,prompt_compliance,list_customizations,session_preflight}.py`; executor machinery; and any Gemini/Copilot/Bedrock/Lambda inference references. Verified by VP step 11.
- **`.agents/skills/planning/SKILL.md` mirror is deliberately left stale** (Dec 58 / Dec 75 cross-harness mirror rule). It is corrected or retired in Plan 2; do not mirror edits into a tree slated for deletion.
- **DECISIONS.md write path:** edit the markdown source directly -- it is the legitimate non-warehouse ETL source of truth (`DECISIONS.md -> ops_decisions`, CLAUDE.md "Warehouse-as-source-of-truth"; Dec 56). Do NOT edit `logs/.decisions-index.jsonl` (Single-Portal invariant binds the JSONL caches, not the markdown). Appending dated addenda allocates no new decision IDs, so no `ops_data_portal` call is required; the ETL propagates on next `sync_ops`.
- **`config/config.personal.yaml`:** re-verify no live reader of the removed keys (`git grep -nE "s3_(production\|staging)_bucket\|formulas-"` across `src/`, `scripts/`, `config/`) before deleting; if a reader exists, repoint to `agent-platform-data-lake` rather than removing.
- **Decision 72 disambiguation:** two records share the number 72 (RCA-as-Plan-Source ~line 159; Branch-Protection-Unavailable ~line 470). The repo-visibility addendum targets the **Branch-Protection** record. Verify by content, not number.
- Code style: ruff format, line length 127; type hints; no emojis; ASCII hyphens only; always invoke `bin/venv-python`. Per the "Batch file modification + ruff cascade" gotcha, modify 1-2 files then run `ruff check --fix` before proceeding.
- No rescue agents or workaround loops (Decision 55). If `validate.py` surfaces a pre-existing unrelated failure, do not patch around it -- report it.

## Context
- **Migrations completed:** company/work AWS -> personal account (profile `agent_platform`, static-key assume-role chain, region eu-west-2, bucket `agent-platform-data-lake`, GitHub-hosted OIDC CI per **CD.21**); private -> public repo (`benjamin-blake/agent-platform`); local Windows/Git-Bash/VS-Code/Antigravity dev -> **Claude Code on the web** (Linux Ubuntu 24.04, bash, `bin/venv-python`, Python 3.12+).
- **Two-plan split (human decision).** This is Plan 1 (low-risk factual sweep). **Plan 2 (deferred, maps to T5.3):** delete `.agents/` + `.github/{prompts,agents,instructions,copilot-instructions.md}` (keep only `.github/workflows/`); retire/repoint their code consumers -- `validate.py` (~5 checks: `validate_cli_tools_in_prompts`, prompt-compliance glob, `validate_no_underscore_instructions`, prompt-density metrics, `schedule.yaml` source-registry check), `prompt_compliance.py`, `list_customizations.py`, `session_preflight.sync_copilot_instructions()` -- plus their 4 test files; update `PROJECT_CONTEXT.md` File Router rows, `AGENTS.md` path refs, `docs/contracts/instruction-architecture.md`; supersede **Decision 58**. (CI-safety pre-checked: all consumers are guarded -- `if dir.exists()` / empty-glob no-ops / warn-and-skip -- so deletion will not hard-fail CI, but the dead checks must be retired.)
- **Decision Scout verdict:** FLAGS_FOUND (3 NOTE flags, all resolved here: `.agents/` mirror deferral; surgical `setup.py` carve-out; freeze confirmed no-Lambda-step). **CITE:** Dec 72 (Branch-Protection), Dec 68, Dec 60, Dec 73 / CD.21 (forward pointer), Dec 48 (V2 tier), Dec 58 / 75 (mirror deferral), Dec 27 (setup.py soft-deprecation), Dec 67 / CD.17 (freeze carve-out).
- **Known gotcha:** `test_coverage_checker` requires a test file at 100% coverage for every modified source file -> `tests/test_setup.py` and `tests/test_session_postflight.py` must be updated alongside their sources.
- **Incidental finding (not fixed here):** duplicate "Decision 72" numbering in `DECISIONS.md` is a data-quality issue worth a future rec.
- Branch divergence at planning time: 0 commits behind `origin/main` (preflight 2026-05-30); no Scope-file overlap with main changes.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `claude/cool-volta-I7b2X`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (locate the SIX target records and the correct Decision 72)
- [ ] All files in the Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] `bin/setup-cloud-env.sh` confirmed to exist (the redirect target for `setup.py`)

## Ordered Execution Steps
1. Confirm branch is `claude/cool-volta-I7b2X` (not `main`).
2. **Operational/ambient docs (present-tense, replace with current truth).** Edit `docs/PROJECT_CONTEXT.md` (lines 5, 15, 37, 238 only -- NOT File Router rows 147-173), then `docs/GETTING_STARTED.md`, `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-WORKFLOW.md`, `README.md`. Substitutions: `company-aws-profile`->`agent_platform`; `aws sso login`->`aws sts get-caller-identity --profile agent_platform` (static-key); `formulas-{discovery,staging,production}`->`agent-platform-data-lake`; Windows/Git-Bash/PowerShell/`.venv/Scripts`/pyenv-3.11.9->Linux/bash/`bin/venv-python`/3.12.
3. **Agent-instruction files.** `.claude/skills/planning/SKILL.md` (line 9 drop `GEMINI.md`; line 262 Windows->Linux/bash); `src/data/handlers/CLAUDE.md` (lines 9-11 `.venv/Scripts/python.exe`->`bin/venv-python`); `tests/CLAUDE.md` (line 24 rationale).
4. **Decision records (past-tense + dated pointer, preserve rationale).** In `docs/DECISIONS.md`, append to each of Dec 60, 68, 71, 72(Branch-Protection ~L470), 24, 62 a line of the form: `> **2026-05 migration update:** <past-tense correction>; see CD.21 / Decision 73 / static-key model.` Convert in-prose present-tense retired-infra statements to past tense. Edit markdown only; leave `logs/.decisions-index.jsonl` alone.
5. **INTENT docs (operational/substrate present-tense -> past tense).** `docs/INTENT-ci-cd-architecture.md` (substrate, credential tiers, profile table), `docs/INTENT-validation-architecture.md` (substrate section), `docs/INTENT-telemetry-system.md` (Windows-host line). Preserve design narrative.
6. **Code/config leaks.**
   a. `setup.py`: add deprecation header redirecting to `bin/setup-cloud-env.sh`; correct `company-aws-profile`/`aws sso login` user-facing strings to `agent_platform`/static-key. LEAVE `check_gemini_cli()` + "Decision 53" + `fix_venv_activate_for_git_bash()` intact. Update `tests/test_setup.py`.
   b. `scripts/session_postflight.py`: replace the `aws sso login` credential-failure fallback (~L670) with a static-key refresh error message. Update `tests/test_session_postflight.py` with a test asserting no `aws sso login` spawn + the static-key message on credential failure.
   c. `config/config.personal.yaml`: re-verify no live reader of `formulas-*`/`s3_*_bucket` keys; remove the "Company S3 Access" section (or repoint to `agent-platform-data-lake` if a reader exists).
7. Run `ruff check --fix` and `ruff format` after each 1-2 file batch (gotcha: avoid batch-modify-then-lint cascades).
8. **Execute Verification Plan** -- run each step in order. Loop until all pass. Do not patch around pre-existing unrelated `validate.py` failures (Decision 55) -- report them instead.
9. Report: files changed, decisions/INTENT records past-tensed, VP results, and an explicit confirmation that deferred/Plan-2 surfaces were left untouched (VP step 11).
