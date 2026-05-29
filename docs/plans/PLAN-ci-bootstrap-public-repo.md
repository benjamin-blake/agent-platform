# Plan

## Intent
Bootstrap CI to green on the newly-migrated `agent-platform` repo so it can be made public. Fixes a CI-only test-isolation defect and makes the V3 hard-gate verifiers tolerant of operational/telemetry tables that were deliberately not provisioned in the new personal account, plus upgrades GitHub Actions ahead of the Node 20 runtime EOL. No AWS infrastructure is mutated.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/ci-bootstrap-public-repo

## Phase
Public-repo bootstrap (post-migration). Platform-tier hardening neighbourhood (sits beside T2.12 security-gate deferral as deferred-gate-restoration debt). Exception category: `ci_rca` / `hotfix` (red `main` CI) -- bypasses tier_item alignment per planning skill.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `tests/test_ops_writer.py` | Modify | Mock `_boto3` / `_get_boto3_session` in the 6 `compact()` tests so they stop constructing a real `Session(profile_name="agent_platform")` on OIDC runners. Test-only fix. |
| `config/agent/data_quality/ops.yaml` | Modify | Remove the `ops_execution_plans` (lines 222-257) and `ops_session_log` (lines 259-279) check blocks. These tables are unprovisioned/deferred; their absence errors DataQualityVerifier. |
| `scripts/verifiers/__init__.py` | Modify | Deregister `CausalChainVerifier` from `REGISTRY` (remove from list + remove its import). Add a comment citing the roadmap debt entry + INTENT doc. Class file retained. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add a single "CI verification-coverage restoration" debt tier_item enumerating the 3 deferrals and their reactivation triggers. |
| `.github/workflows/ci.yml` | Modify | Bump actions to Node-24-compatible majors. |
| `.github/workflows/main-canary.yml` | Modify | Bump actions to Node-24-compatible majors. |
| `.github/workflows/ci-rca.yml` | Modify | Bump actions to Node-24-compatible majors. |
| `.github/workflows/deploy.yml` | Modify | Bump actions to Node-24-compatible majors. |
| `.github/workflows/claude.yml` | Modify | Bump `actions/checkout` to Node-24-compatible major. |
| `.github/workflows/refresh-copilot-multipliers.yml` | Modify | Bump actions to Node-24-compatible majors. |
| `.github/workflows/pre_commit.yml` | Modify | Bump the Node 16-era `@v3` actions (`checkout`, `setup-python`) to Node-24 majors; verify `pre-commit/action` guidance. |

## Bundled Recommendations
None. Preflight `ci_rca_recs` is empty (no ci-rca rec was filed for these failures -- see Context). The `ci_rca_liveness_alert` (main CI red ~631 min) is the symptom this plan resolves.

## Infrastructure Dependencies
Not applicable. No `.tf` files are in scope and **no AWS infrastructure is created, modified, or destroyed**. `terraform/personal/` is intentionally left untouched -- the chosen approach is to defer the unprovisioned tables, not provision them.

## Acceptance Criteria
- [ ] The 6 previously-failing `tests/test_ops_writer.py` compact tests pass, and still assert `wr.athena.to_iceberg` is called with the expected kwargs (the fix mocks the boto3 session; it does not weaken the assertions).
- [ ] `scripts/data_quality_runner` reports zero errored checks (the 14 `TABLE_NOT_FOUND` errors on `ops_execution_plans` + `ops_session_log` are gone).
- [ ] The V3 verifier harness runs with no `HARD_GATE` `FAIL`, and `CausalChainVerifier` is absent from the results.
- [ ] `bin/venv-python -m scripts.validate` (full presubmit) exits 0.
- [ ] `docs/ROADMAP-PLATFORM.yaml` parses and the new debt tier_item appears in `platform_roadmap` output.
- [ ] No workflow file references a Node-20-only action version; remote CI run shows zero "Node.js 20 actions are deprecated" annotations.
- [ ] Remote CI (`CI` push workflow + `Main Canary`) is green on the branch (authoritative gate, CD.21 / Decision 73).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-merge | Run the 3 compact test classes (no `-k`; class-targeted per tests/CLAUDE.md) | `bin/venv-python -m pytest tests/test_ops_writer.py::TestOpsWriterCompact tests/test_ops_writer.py::TestOpsWriterCompactEdgeCases tests/test_ops_writer.py::TestOpsWriterCompactTimestampHandling -q` | All pass; `to_iceberg` kwargs assertions still present and passing | Tests still hit real profile -> ensure `_boto3` or `_get_boto3_session` is mocked in each; do not delete the `to_iceberg` assertions |
| 2 | pre-merge | Confirm full ops_writer suite unaffected | `bin/venv-python -m pytest tests/test_ops_writer.py -q` | All pass | A profile-resolution test (e.g. `test_get_client_*`) regressed -> reconcile mock target |
| 3 | pre-merge | Run DQ runner against Athena (needs SSO; `aws sso login --profile agent_platform` if expired) | `bin/venv-python -m scripts.data_quality_runner` | Verdict no longer FAIL on missing-table errors; 0 errored for the two removed tables | Other tables still error -> investigate; only `ops_execution_plans`/`ops_session_log` blocks should be removed |
| 4 | pre-merge | Run V3 verifier harness | `bin/venv-python -m scripts.verifiers.harness --tier V3` | No `HARD_GATE` `FAIL`; `CausalChainVerifier` NOT listed | CausalChainVerifier still runs -> confirm it was removed from `REGISTRY` and its import deleted |
| 5 | pre-merge | Confirm roadmap parses + debt entry present | `bin/venv-python -m scripts.platform_roadmap` | Command succeeds; new debt tier_item id appears | YAML parse error -> fix indentation/schema of the new entry |
| 6 | pre-merge | Full presubmit (CI-identical) | `bin/venv-python -m scripts.validate` | Exit 0 | Any check fails -> address before pushing |
| 7 | pre-merge | No Node-20 action versions remain | `grep -rnE "checkout@v[34]|setup-python@v[35]|configure-aws-credentials@v4|setup-terraform@v3" .github/workflows/` | No matches. NOTE: the `|` here is the ERE alternation operator -- do NOT escape it (`\|` in `-E` matches a literal pipe and always returns "no matches", a false green). The commented `configure-aws-credentials@v4` line in `deploy.yml` must also be bumped (Step 5) so zero matches remain. | Stale version remains -> bump it (including any commented reference) |
| 8 | post-merge (remote) | Push branch; confirm remote CI green + no Node-20 annotations | `git push -u origin agent/ci-bootstrap-public-repo && gh run watch $(gh run list --branch agent/ci-bootstrap-public-repo --limit 1 --json databaseId -q '.[0].databaseId')` then `gh run view <id>` | `CI` workflow conclusion `success`; annotations contain no "Node.js 20 actions are deprecated" | CI red -> read `gh run view <id> --log-failed`, fix, repeat. Do NOT merge until green. |

## Constraints
- **No workaround loops (Decision 55).** Deregistering `CausalChainVerifier` and removing the two DQ blocks are deliberate, human-decided deferrals of gates whose backing infrastructure is intentionally not provisioned -- not silent patches to hide a defect. The roadmap debt entry + the in-code comment make the gap visible. This distinction must be stated in the commit message / PR body.
- **Removal, not flags.** Do NOT introduce a `telemetry_enabled` / `deferred: true` skip flag. The human explicitly rejected flags so that flag-bypass never becomes a normalized route for red CI. Deregistration (code) and block removal (config) are the chosen mechanisms.
- **ops.yaml is canonical (Decision 65).** Preserve the file's structure for the remaining tables (`ops_recommendations`, `ops_decisions`, `ops_priority_queue`). Remove only the two whole-table blocks.
- **Warehouse-as-source-of-truth.** Do not edit `logs/.recommendations-log.jsonl` or other `logs/` caches. No `OpsWriter.write()` from cache.
- **Platform commands.** Use `bin/venv-python`; Bash syntax; ASCII hyphens; no emojis.
- **Branch discipline.** Never commit on `main`.

## Context
- **Two root causes, both migration artefacts.**
  1. *Test isolation:* the autouse `_clear_aws_credential_env` fixture (`tests/conftest.py:55`) strips `AWS_ACCESS_KEY_ID` for hermeticity. The 6 compact tests don't mock `scripts.ops_writer._boto3`, so `_get_boto3_session()` (`scripts/ops_writer.py:491`, via `:154`) resolves the named `agent_platform` profile and raises `ProfileNotFound` on the GH-hosted OIDC runner. Passes locally (dev box has the profile). Production `scripts/aws_profile.resolve_aws_profile` is correct and is NOT changed.
  2. *Unprovisioned tables:* `terraform/personal/main.tf` provisions only `ops_recommendations`, `ops_decisions`, `ops_priority_queue`. `ops_execution_plans`, `ops_session_log`, and all 7 `telemetry_*` tables were never created in the `agent_platform` Glue DB. DataQualityVerifier errors (14) on the two ops tables (telemetry has no DQ checks, so it only trips the WARN-level SchemaIntegrityVerifier). CausalChainVerifier (HARD_GATE) returns SKIPPED on missing awswrangler/bucket/credentials, but with valid OIDC creds it emits a heartbeat into staging and then FAILs after a 180s Athena poll because `telemetry_process_events` does not exist (also leaving one orphan heartbeat in staging). Deregistration removes that 180s burn + orphan write; it also drops the verifier's `covers` globs from `validate.py --coverage`, so any future plan scoping telemetry-emitter files will newly show as uncovered until reactivation (acceptable).
- **Decisions cited (from decision-scout gate):**
  - **Decision 67 (narrowly superseded by CD.11/CD.16/CD.17 in the live roadmap)** -- its reversal condition names the telemetry tables as the gating trigger. The precise reactivation owners are **CD.17** (STRATEGIC-freeze reversal keyed to T4.2; telemetry trust at T3.2/T3.3) and the T3.x telemetry verifiers; cite those alongside Decision 67 in the debt entry rather than anchoring on the half-superseded decision alone.
  - **Decision 73** -- the two-tier diff-aware CI / forward-fix-via-`/plan` merge-gate model this work operates within; sanctions roadmap-tracked deferral over silent bypass.
  - **Decision 48** -- Verification Tier classification; deregistering one HARD_GATE must leave V3 semantics intact for the remaining verifiers (OutboxHealth, AthenaViews, SchemaIntegrity, DataQuality).
  - Supporting: **Decision 56** (5-table ops inventory incl. the two deferred), **Decision 65** (ops.yaml authority), **Decision 70** (precedent: removing a HARD_GATE trigger for non-viable/non-existent data is accepted).
- **Decision flags (NOTE-level, both accepted):**
  - *Decision 55 resemblance* -- addressed by the documented-deferral framing above + roadmap entry + code comment.
  - *Decision 72 (ci-rca rec must precede CI patching)* -- preflight `ci_rca_recs: []`; no ci-rca rec was filed for these failures (this is fresh-repo migration bootstrap; the `ci_rca_liveness_alert` fired precisely because no rec exists). This `/plan` session IS the architectural review Decision 72 requires; the work is therefore not rec-sourced by design, documented here.
- **Attribution correction:** the `ops_session_log` retirement rationale is `docs/INTENT-session-log-architecture.md` + the **proposed/unratified CD.NN.a** -- NOT "Decision 75" (which is the Frame-Lock Anti-Pattern). Cite the INTENT doc; mark CD.NN.a as proposed.
- **Reactivation triggers (for the roadmap debt entry):**
  - `ops_execution_plans` DQ checks -> restore on executor-freeze reversal (CD.17, keyed to T4.2; Decision 67 is the superseded ancestor) once the table is provisioned.
  - `ops_session_log` DQ checks -> superseded; `ops_session_log` is slated for retirement (INTENT-session-log-architecture.md, proposed CD.NN.a, replaced by `telemetry_agent_turns`). Restoration = new telemetry-capture DQ checks, gated on that work going live.
  - `CausalChainVerifier` -> reactivate AND rewrite to target the new `telemetry_agent_turns` event table once telemetry capture is live (owned by CD.17 telemetry trust at T3.2/T3.3 + the T0.7b log-* Lambda surface). The rewrite is the "refactor" the reactivation depends on, and must restore the verifier's `covers` globs.
- **Node 20 EOL:** GitHub forces Node 24 on **2026-06-16** (changelog updated 2026-05-19; the stale CI annotation said June 2). Node 20 removed entirely 2026-09-16. Confirmed Node-24 majors: `actions/checkout@v5`, `actions/setup-python@v6`, `aws-actions/configure-aws-credentials@v5`. **Verify at implement time** (releases pages) for: `actions/cache` (v4.2.0 still warned -- find the Node-24 release), `hashicorp/setup-terraform` (Node-24 patch/major), and `pre-commit/action` (third-party, may be deprecated in favour of running `pre-commit` directly -- prefer the minimal first-party bumps and confirm current guidance before changing the pre-commit step itself). The authoritative acceptance is "zero Node 20 deprecation annotations in the CI run" (VP step 8), which is version-number-independent.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` -> `agent/ci-bootstrap-public-repo`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` relevant entries read (67, 73, 48, 55, 56, 65, 70, 72)
- [ ] `docs/INTENT-session-log-architecture.md` read (for the debt-entry reactivation wording)
- [ ] All 11 files in Scope located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **`tests/test_ops_writer.py`** -- in each of the 6 failing compact tests (`TestOpsWriterCompact::test_compact_reads_staging_creates_dataframe_calls_awswrangler`, `::test_compact_deletes_staging_files_after_compaction`, `::test_compact_drops_scd2_view_columns_before_iceberg`, `TestOpsWriterCompactEdgeCases::test_compact_delete_object_failure_is_logged_not_raised`, `TestOpsWriterCompactTimestampHandling::test_compact_converts_ingested_at_string_to_datetime`, `::test_compact_prefills_missing_timestamp_cols_with_nat_after_null_drop`), add `patch.object(writer, "_get_boto3_session", return_value=MagicMock())` (or `patch("scripts.ops_writer._boto3")`) to the `with` block so the `boto3_session=self._get_boto3_session()` argument (ops_writer.py:491) never constructs a real named-profile session. Keep all existing `to_iceberg` / `delete_object` / DataFrame assertions intact.
2. **`config/agent/data_quality/ops.yaml`** -- delete the `ops_execution_plans:` block (lines 222-257) and the `ops_session_log:` block (lines 259-279) in their entirety. Leave `ops_decisions` (above) and `ops_priority_queue` (below) untouched. Verify the remaining `tables:` mapping is well-formed.
3. **`scripts/verifiers/__init__.py`** -- remove `CausalChainVerifier` from the `REGISTRY` list (line 24) and delete its import (line 11). Add a short comment on the REGISTRY where it was removed: deregistered during public-repo CI bootstrap because telemetry tables are deferred; reactivate per the new `docs/ROADMAP-PLATFORM.yaml` debt entry and `docs/INTENT-session-log-architecture.md`. Run `ruff check --fix` to catch the now-unused import if not removed.
4. **`docs/ROADMAP-PLATFORM.yaml`** -- add one new tier_item with id **`T2.15`** (verified next-free: `T2.13` = "Public flip + post-flip verification" -- the gate THIS plan unblocks -- and `T2.14` are both taken; do NOT overwrite `T2.13`). Follow the existing schema (`id`, `tier: T2`, `name`, `intent: |`, `depends_on`, `files_in_scope`, `exit_criteria`, `related_candidate_decisions`, `effort`, `strategic: false`, `status: not_started`). Name it for CI verification-coverage restoration. `intent` enumerates the three deferrals + their reactivation triggers (from Context). `exit_criteria` should require: (a) `ops_execution_plans` + `ops_session_log` DQ coverage restored or formally retired, (b) `CausalChainVerifier` re-registered and rewritten against `telemetry_agent_turns` with its `covers` globs restored. Cite **CD.17** (STRATEGIC-freeze reversal at T4.2; telemetry trust at T3.2/T3.3) and `docs/INTENT-session-log-architecture.md` as reactivation owners, alongside Decision 67 (noting it is narrowly superseded by CD.11/CD.16/CD.17).
5. **`.github/workflows/*.yml`** -- bump pinned action versions to Node-24-compatible majors across all 7 workflow files: `actions/checkout@v5`, `actions/setup-python@v6`, `aws-actions/configure-aws-credentials@v5`; for `actions/cache`, `hashicorp/setup-terraform`, and `pre-commit/action` verify the exact Node-24 version against each action's releases (see Context) before pinning. Do not change workflow logic -- versions only.
6. **Execute Verification Plan** -- run steps 1-7 locally, loop until green, then step 8 (push + remote CI). If a V3 step fails unrecoverably, stop and analyse root cause (Decision 55); do not loop workarounds.
7. **Report** -- summarise what changed, local verification results, and the remote CI run URL + conclusion. Note the new roadmap debt id for follow-up tracking.
