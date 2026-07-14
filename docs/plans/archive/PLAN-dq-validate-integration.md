# Plan

## Intent

Close Gap 2 from `PLAN-audit-ops-recs-dq-scalability.md` (DQ runner integration into `validate.py`) and capture the architectural direction for two-tier validation in a durable INTENT document plus Decision Record. This unblocks the move toward presubmit/postsubmit-only validation surfaces and prepares the runway for the EC2 self-hosted runner work that follows in a separate plan.

## Plan Type

IMPLEMENTATION

## Verification Tier

V3 (auto-invocation of `data_quality_runner` queries Athena; the harness call requires SSO).

## Branch

agent/dq-validate-integration

## Phase

Phase Platform - verification system maturation (parallel to Phase 2 schema backfill).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `scripts/verifiers/__init__.py` | Modify | Add `check_coverage(scope_files)` function per `INTENT-verification-system.md` Wave 1 spec. Iterates REGISTRY, collects `covers` glob patterns, returns scope files not matched by any verifier. |
| `scripts/validate.py` | Modify | Add `--coverage` flag and `run_coverage_check()`. Add `ensure_fresh_dq_results()` and call it from `run_integration_checks()` before the harness, so `--integration` auto-invokes the DQ runner when `dq-latest.json` is missing or >1h stale. |
| `tests/test_validate.py` | Modify | Add tests for `--coverage` flag (covered/uncovered scope) and DQ auto-invoke (missing file, stale file, fresh file). Mock subprocess and file mtime. |
| `tests/test_verifiers.py` | Modify | Add tests for `check_coverage()` (file matched, file unmatched, glob expansion). |
| `docs/INTENT-validation-architecture.md` | Create | Architectural anchor for two-tier validation (presubmit + edit-loop), naming convention, EC2 substrate, bounded-execution constraint, migration sequence. |
| `docs/DECISIONS.md` | Modify | Append new Decision: "Two-tier validation architecture: presubmit (default) + edit-loop (`--quick`)". Mirror entry in `logs/.decisions-index.jsonl` via portal. |
| `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Modify | Append "Future Direction (Validation Architecture)" amendment pointing at the new INTENT doc. |
| `CLAUDE.md` | Modify | Update merge protocol section to reference `--integration` as the comprehensive pre-merge gate, and note the planned migration to two-tier per the new INTENT. |

## Bundled Recommendations

None. The 127 open non-automatable recommendations were reviewed; none touch `validate.py`, `data_quality_runner`, or CI wiring (executor/planning/prompt-engineering domain only). Kept open en bloc.

## Acceptance Criteria

- [ ] `python -m scripts.validate --coverage` reports scope files lacking verifier coverage; advisory only (does not fail the build).
- [ ] `python -m scripts.validate --integration` auto-invokes `python -m scripts.data_quality_runner` if `logs/debug/dq-latest.json` is missing or >1h stale, then proceeds with the harness against fresh data.
- [ ] If SSO is unavailable, the auto-invoke step prints a clear actionable message and skips (does not crash). Decision 57 (Interactive vs Autonomous SSO) is honoured.
- [ ] `docs/INTENT-validation-architecture.md` exists with the eight required `## ` headings (see VP step 4).
- [ ] `docs/DECISIONS.md` contains a new Decision entry referencing "Two-tier validation architecture"; the same Decision is mirrored in `logs/.decisions-index.jsonl` via the portal.
- [ ] `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` contains a "Future Direction (Validation Architecture)" section linking to `INTENT-validation-architecture.md`.
- [ ] `CLAUDE.md` merge protocol section references `--integration`.
- [ ] Three forward-looking recommendations are filed via the portal:
      1. "Stand up self-hosted GitHub Actions runner on EC2 with SSO substrate"
      2. "Consolidate validate.py flags to two-tier model: presubmit (default) + --quick"
      3. "Add scheduled postsubmit health checks (Wave 4b INTENT-verification-system)"
- [ ] Existing `python -m scripts.validate --ci` exits 0 on this branch.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [post-impl][pre-deploy] | `--coverage` flag prints a coverage report and does not crash | `.venv/Scripts/python.exe -m scripts.validate --coverage` | Exit code 0; stdout contains the substring `coverage` and either `All scope files covered` OR a list of uncovered files | Implement or fix `run_coverage_check()` and `check_coverage()` |
| 2 | [post-impl][pre-deploy] | DQ auto-invoke triggers when cache missing | `rm -f logs/debug/dq-latest.json && .venv/Scripts/python.exe -m scripts.validate --integration 2>&1 \| grep -c "data_quality_runner"` | Returns at least `1` (auto-invoke ran). After the command, `logs/debug/dq-latest.json` exists. | Add the auto-invoke step before harness in `run_integration_checks()` |
| 3 | [post-impl][pre-deploy] | DQ auto-invoke skipped when cache fresh | `.venv/Scripts/python.exe -m scripts.data_quality_runner && .venv/Scripts/python.exe -m scripts.validate --integration 2>&1 \| grep -c "DQ cache fresh"` | Returns at least `1` (skip message printed) | Fix freshness branch in `ensure_fresh_dq_results()` |
| 4 | [post-impl][pre-deploy] | INTENT doc structural completeness | `grep -cE "^## (Motivation\|Two-Tier Model\|Naming Convention\|Substrate\|Bounded Execution\|Migration Sequence\|Relationship to INTENT-verification-system\|Constraints)" docs/INTENT-validation-architecture.md` | Returns `8` | Add the missing heading |
| 5 | [post-impl][pre-deploy] | Decision Record present in markdown view | `grep -c "Two-tier validation architecture" docs/DECISIONS.md` | Returns at least `1` | Add the DR entry to DECISIONS.md |
| 6 | [post-impl][post-deploy] | Decision Record present in JSONL store (post portal write) | `grep -c "Two-tier validation architecture" logs/.decisions-index.jsonl` | Returns at least `1` | File via `python -m scripts.ops_data_portal --file-decision ...` |
| 7 | [post-impl][pre-deploy] | Audit plan amendment references new INTENT | `grep -c "INTENT-validation-architecture" docs/plans/PLAN-audit-ops-recs-dq-scalability.md` | Returns at least `1` | Append the Future Direction section |
| 8 | [post-impl][pre-deploy] | CLAUDE.md merge protocol references `--integration` | `grep -cE "validate.*--integration\|--integration.*pre-merge" CLAUDE.md` | Returns at least `1` | Add the bullet to the Merge Protocol section |
| 9 | [post-impl][post-deploy] | Three forward-looking recs filed and synced (post portal writes) | `.venv/Scripts/python.exe -m scripts.sync_ops pull > /dev/null && grep -cE "(Stand up self-hosted GitHub Actions runner on EC2\|Consolidate validate.py flags to two-tier\|Add scheduled postsubmit health checks)" logs/.recommendations-log.jsonl` | Returns at least `3` | File missing rec(s) via `python -m scripts.ops_data_portal --file-rec ...` |
| 10 | [post-impl][pre-deploy] | Coverage check unit test exists and passes | `.venv/Scripts/python.exe -m pytest tests/test_verifiers.py -k check_coverage -v` | Exit 0; at least one test selected | Add the missing test case |
| 11 | [post-impl][pre-deploy] | DQ auto-invoke unit test exists and passes | `.venv/Scripts/python.exe -m pytest tests/test_validate.py -k ensure_fresh_dq -v` | Exit 0; at least one test selected | Add the missing test case |
| 12 | [post-impl][pre-deploy] | Full local CI sweep passes | `.venv/Scripts/python.exe -m scripts.validate --ci` | Exit 0 | Diagnose and fix the failing check at root cause |

## Constraints

- This plan does NOT consolidate the four flags into two. It adds the architectural anchor for that future consolidation. Flag rename / `--ci` deletion / `--verifiers` deletion are explicitly deferred to the rec filed in step 9.
- The DQ runner auto-invoke must respect Decision 57: if SSO is unavailable, print an actionable message and skip rather than crashing. Autonomous executors (Lambda) skip the auto-invoke entirely.
- The INTENT document must follow the existing `INTENT-verification-system.md` style and explicitly reference Wave 1 of that spec (the `--coverage` flag is Wave 1 item 4).
- The Decision Record MUST be filed via `python -m scripts.ops_data_portal --file-decision` (Single Portal Invariant). Direct edits to `logs/.decisions-index.jsonl` will fail `validate.py`.
- All forward-looking recs filed in step 9 must have `automatable: false` (they are STRATEGIC plans waiting to happen, not executor work).
- No emojis in code or docs. ASCII hyphens only (no em-dashes).
- No rescue agents or workaround loops (Decision 55). If V3 verification fails unrecoverably, stop and analyse root cause.
- Windows compatibility: subprocess invocations of `data_quality_runner` use `sys.executable` (or `PYTHON` constant), not the literal string `python`. Pass `encoding="utf-8", errors="replace"`.
- The auto-invoke must not run during `_VALIDATE_DEPTH > 0` (recursion guard already exists in `validate.py`).

## Context

- **Audit report this closes a gap from:** `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (Gap 2: DQ runner not in `validate.py` or any GitHub Actions workflow).
- **Sessions A and B prior work:** PR #285 (gaps 1, 4, 5) and PR #286 (gaps 3, 6) landed substantial Wave 1 verifier infrastructure beyond their original gap scope. The harness, DQ verifier, `--integration` flag, and `--verifiers` flag already exist. This plan completes the Gap 2 closure that the existing infra started.
- **Authoritative architecture:** `docs/INTENT-verification-system.md` defines the three-layer quality pyramid; this plan operates at Layer 1 (the `validate.py` surface) wired to Layer 2 (the DQ runner and harness).
- **Wave alignment:** This plan completes Wave 1 item 4 (`--integration` and `--coverage` flags on `validate.py`) per `INTENT-verification-system.md` and creates the architectural anchor for a future Wave that consolidates flags.
- **Decisions referenced:** 48 (Verification Tier Design: V1=static, V2=unit, V3=integration), 51 (Local-First Outbox + Bidirectional Sync), 55 (No rescue agents), 57 (Interactive vs Autonomous SSO recovery).
- **Single Portal Invariant:** All Decision and Recommendation writes go through `scripts/ops_data_portal.py`. The local JSONL files are read-only caches.
- **Agent-first reframing:** This is an agent-driven project. The two-tier model's primary motivation is bounded-execution determinism for autonomous agents, not human ergonomics. The bounded-execution constraint (5-minute total harness cap, 120-second per-verifier cap) is already present in `INTENT-verification-system.md` constraint 8 and is referenced in the new INTENT.
- **127 open non-automatable recs:** Reviewed during preflight; all in executor/planning/prompt-engineering domain. None align with this scope. Kept open en bloc.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (this plan is on `agent/dq-validate-integration`).
- [x] `docs/PROJECT_CONTEXT.md` read.
- [x] `docs/DECISIONS.md` decisions referenced (48, 51, 55, 57).
- [x] `docs/INTENT-verification-system.md` read; Wave 1 item 4 confirmed as the spec for this work.
- [x] `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` Gap 2 description re-read.
- [x] Current state of `scripts/validate.py`, `scripts/verifiers/__init__.py`, and `scripts/verifiers/data_quality.py` inspected. `check_coverage()` confirmed missing; `--integration` flag confirmed present but DQ-passive.
- [x] Acceptance Criteria understood and verifiable via the Verification Plan commands.

## Ordered Execution Steps

1. **Add `check_coverage()` to `scripts/verifiers/__init__.py`.** Signature: `def check_coverage(scope_files: list[str]) -> list[str]`. Iterate `REGISTRY`, collect each verifier's `covers` glob patterns, return scope files not matched by any pattern. Use `fnmatch.fnmatch` or `pathlib.PurePath.match()` for glob support (the existing `covers` lists use patterns like `"config/data_quality/**"`).
2. **Add unit tests for `check_coverage()`** in `tests/test_verifiers.py`: covered file (matches a verifier's `covers`), uncovered file (no match), glob expansion (e.g., `src/data/foo.py` matches `src/data/**`).
3. **Add `--coverage` flag and `run_coverage_check()` to `scripts/validate.py`.** When the flag is passed, detect changed files on the current branch (re-use existing `get_changed_files` logic in validate.py if present; otherwise add a small helper), call `check_coverage()`, and print the report. Advisory only — do not append to `failed`.
4. **Add `ensure_fresh_dq_results()` to `scripts/validate.py`.** Check `logs/debug/dq-latest.json` mtime. If missing or >1h old, call `invoke_step("Data quality runner", [PYTHON, "-m", "scripts.data_quality_runner"], failed)`. If fresh, print a skip message. Wrap with SSO-availability check: if `aws sts get-caller-identity --profile company-aws-profile` fails, print an actionable message and return without crashing (Decision 57). Hook this into `run_integration_checks()` *before* `validate_verification_harness()`.
5. **Add unit tests for the new validate.py logic** in `tests/test_validate.py`: `--coverage` flag prints expected output; `ensure_fresh_dq_results` handles missing file, stale file, fresh file, SSO-unavailable. Mock `subprocess.run`, `Path.exists()`, `Path.stat()`.
6. **Write `docs/INTENT-validation-architecture.md`** with the eight `## ` sections checked by VP step 4. Capture: the two-tier model (presubmit + edit-loop), why agent-first projects benefit from crisp tier boundaries, the EC2 self-hosted runner as the substrate that makes the model coherent, the bounded-execution constraint (per-verifier and total-harness timeouts), the naming convention (`--quick` is the only named flag; presubmit is the default), and the migration sequence from the current four-flag world to the two-tier model. Reference `INTENT-verification-system.md` Wave 1 explicitly.
7. **File the Decision Record via the portal:** `python -m scripts.ops_data_portal --file-decision --title "Two-tier validation architecture: presubmit (default) + edit-loop (--quick)" --rationale "..." --status open`. Then add a corresponding entry to `docs/DECISIONS.md` markdown that mirrors the JSONL record.
8. **Append "Future Direction (Validation Architecture)" section** to `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` after the existing "Future Direction" section, linking to `docs/INTENT-validation-architecture.md`. State that the validation flag refactor and EC2 runner stand-up are sequenced as separate STRATEGIC plans referenced by the rec IDs filed in step 9.
9. **Update `CLAUDE.md` Merge Protocol section.** Add a bullet referencing `python -m scripts.validate --integration` as the comprehensive pre-merge gate when SSO is available. Note that the flag set will migrate to two-tier per `docs/INTENT-validation-architecture.md`.
10. **File three forward-looking recommendations via the portal**, all with `automatable: false`:
    - Title: "Stand up self-hosted GitHub Actions runner on EC2 with SSO substrate", priority High, effort L, risk medium. Context cites `INTENT-validation-architecture.md` substrate section.
    - Title: "Consolidate validate.py flags to two-tier model: presubmit (default) + --quick", priority Medium, effort M, risk low. Dependencies: the EC2 runner rec (this rec is blocked on the runner landing first).
    - Title: "Add scheduled postsubmit health checks (Wave 4b INTENT-verification-system)", priority Medium, effort M, risk low. Context cites the postsubmit row in the new INTENT.
11. **Run `python -m scripts.sync_ops pull`** to refresh the local cache so VP step 9 sees the newly filed recs.
12. **Execute Verification Plan** — run each VP step. Loop until pass. If V3 step (2 or 3) fails unrecoverably (e.g., Athena rejects the query), stop and analyse root cause per Decision 55; do not paper over with mocks.
13. **Report:** what was implemented, verification results (all 12 VP steps), the three rec IDs allocated by the portal, and the Decision ID allocated.
