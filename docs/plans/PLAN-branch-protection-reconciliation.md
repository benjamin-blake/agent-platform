# Plan

## Intent
Keep the agent-instruction surfaces truthful: `main` branch protection (T2.12 / CD.20) is verified live, but multiple docs still say "apply pending" and still assert branch protection is "permanently unavailable" (Decision 72's now-false premise). Every CI/CD-touching planning session reasons from these surfaces, so the stale premise misleads autonomous work. This plan reconciles the surfaces with reality and logs a numbered Decision amending Decision 72 — reversing the premise while preserving its merge-gate design consequences.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-branch-protection-reconciliation.md

## Phase
Platform roadmap tier T2 — T2.12 (Pre-flight security pass) / CD.20. Bookkeeping reconciliation of an already-applied gate; not new feature work.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `AGENTS.md` | Modify | Rewrite the "T2.12 security gate (CD.20) -- controls-as-code shipped, apply pending" temporary-constraints bullet to state the apply is complete and the controls are live. |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Flip T2.12 `status: in_progress` -> `complete` (+ `completed_at`), refresh its `progress_note` (currently "human-gated terraform apply pending"). Leave the UNRELATED DuckLake pending-apply note (~L3535) untouched. |
| `.github/workflows/terraform-apply-sandbox.yml` | Modify | Fix the stale "Branch protection / required status checks are not available (Decision 72 / CD.20)" header comment (~L8). Comment-only; workflow logic unchanged. |
| `scripts/terraform_apply_guard.py` | Modify | Update the module-docstring framing ("compensating control for the absence of branch protection / required status checks"). The guard remains the fail-closed plan-CONTENT control (CD.35 / Decision 77). Behaviour unchanged — docstring only. |
| `terraform/personal/oidc.tf` | Modify | Fix the stale parenthetical at ~L239-240 ("Decision 72 / CD.20 -- branch protection and required status checks are NOT available"). Comment-only; the two compensating controls listed below it remain valid. |
| `docs/INTENT-ci-cd-architecture.md` | Modify | Update hard-constraint #1 (~L15) and the Decision-72 relationship row (~L461): protection is now AVAILABLE and ACTIVE but deliberately non-wedging, so the forward-fix / convention-plus-tooling design is PRESERVED. |
| `docs/DECISIONS.md` | Modify | Add the new numbered Decision 83 narrative (amending Decision 72); add an "Amended by Decision 83" prose pointer on the Decision 72 (Branch Protection Not Available, ~L769) entry, replacing its stale "branch protection remains deferred" 2026-05 migration note; add a one-line migration note to Decision 60's stale "branch protection ... requires the workflow to pass" substrate text. |
| `scripts/ops_data_portal.py::file_decision` | Invoke (not edit) | Portal call (the mandated Single-Portal write path) to allocate + stage the new decision row into `ops_decisions`. Then `sync`. |

## Bundled Recommendations
None. (Priority queue empty at preflight; Athena reader degraded. The `rec-2079` consolidation surfaced by the decision-scout belongs to CD.35 Wave 4, not this reconciliation.)

## Infrastructure Dependencies
`.tf` (`terraform/personal/oidc.tf`) and a Lambda-adjacent CI script (`scripts/terraform_apply_guard.py`) appear in Scope, but **every edit here is comment/docstring-only — zero resource changes, no `terraform apply` initiated by this plan, no Lambda packaged or deployed.**

| Concern | Timing | Note |
|---------|--------|------|
| `oidc.tf` lives under `terraform/personal/**` | **Post-merge (implement session)** | Merging the implementation PR to `main` triggers `terraform-apply-sandbox.yml` (path filter `terraform/personal/**`). A comment-only `.tf` change yields a **no-op** `terraform plan` (zero `resource_changes`); the guard passes trivially (no findings) and the apply is a no-op. This is expected, not a defect. Confirm via VP step 9. |
| Subagent-review step needs `CLAUDE_CODE_OAUTH_TOKEN` | Post-merge | If the no-op apply's subagent-review step fails on an expired token, that is an apply-pipeline auth issue (refresh per the CLAUDE.md runbook), NOT a plan defect. |
| `terraform_apply_guard.py` is a CI script | n/a | Not Lambda-packaged; no deploy. Docstring edit does not change `evaluate_plan` / exit codes. |

## Acceptance Criteria
- [ ] Live-state probes recorded: `main` `protected: true` confirmed; GHAS secret scanning, CodeQL, Dependabot, Actions-permissions each probed and their verdicts noted (VP 1-4).
- [ ] `AGENTS.md` T2.12 bullet states the controls are applied/live (no "apply pending").
- [ ] `docs/ROADMAP-PLATFORM.yaml` T2.12 is `complete` with `completed_at` **iff all controls probe live**; otherwise marked "apply complete; <control> verification outstanding" with the specific gap named (no overclaim).
- [ ] The stale "branch protection / required status checks not available" / "permanently unavailable" assertions are removed from `terraform-apply-sandbox.yml`, `terraform_apply_guard.py`, `terraform/personal/oidc.tf`, and `docs/INTENT-ci-cd-architecture.md` (historical quotation inside `DECISIONS.md` excepted).
- [ ] A new numbered Decision (heading "Decision 83") amending Decision 72 exists in `docs/DECISIONS.md`; the Decision 72 entry carries an "Amended by Decision 83" pointer; Decision 60's stale substrate line carries a migration note.
- [ ] The decision is filed via `file_decision` (portal) and round-trips into `ops_decisions` after `sync` (or is queued to the outbox if the warehouse is offline — never written to the JSONL cache directly).
- [ ] `bin/venv-python -m scripts.validate --pre` exits 0.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Confirm `main` protection is live | `mcp__github__list_branches(owner="benjamin-blake", repo="agent-platform")` → entry `name=="main"` | `"protected": true` | If `false`, protection is NOT live — **STOP**, do not flip T2.12, re-scope (the premise reversal would be wrong). |
| 2 | [pre-deploy] | Confirm Dependabot active | `mcp__github__list_branches(...)` (look for `dependabot/*`) and/or `mcp__github-full__list_dependabot_alerts(owner, repo)` | ≥1 `dependabot/*` branch OR alerts endpoint returns (not 404-disabled) | If neither, record "Dependabot verification outstanding" in the T2.12 note; do not claim it live. |
| 3 | [pre-deploy] | Confirm GHAS secret scanning enabled | `mcp__github-full__list_secret_scanning_alerts(owner, repo)` | Endpoint returns a list (HTTP 200, possibly empty) — not 404 "secret scanning disabled" | If 404/disabled, record "GHAS secret scanning verification outstanding"; do not claim it live. |
| 4 | [pre-deploy] | Confirm CodeQL code scanning ran | `mcp__github-full__list_code_scanning_alerts(owner, repo)` and/or `mcp__github__actions_list` filtered to `codeql.yml` | Code-scanning endpoint returns (not 404) AND ≥1 CodeQL workflow run exists | If no CodeQL runs, record "CodeQL verification outstanding"; do not claim it live. |
| 5 | [pre-deploy] | No stale premise assertion remains in the scoped instruction/comment surfaces | `grep -rniE "apply pending\|permanently unavailable\|required status checks are not available\|branch protection.{0,30}(unavailable\|not available\|deferred)" AGENTS.md docs/ROADMAP-PLATFORM.yaml docs/INTENT-ci-cd-architecture.md scripts/terraform_apply_guard.py terraform/personal/oidc.tf .github/workflows/terraform-apply-sandbox.yml` | Zero hits | Any hit = an un-reconciled surface; fix it. |
| 6 | [pre-deploy] | Decision 83 round-trips into the warehouse | After filing: `bin/venv-python -m scripts.sync_ops pull` then `grep -c "Decision 83" docs/DECISIONS.md` and inspect `file_decision` return value | `file_decision` returned a `dec-NNN` string; `sync` reports the decisions table pulled; ≥1 "Decision 83" hit | If return is `pending-<uuid>`, warehouse offline — confirm `aws sts get-caller-identity --profile agent_platform`, refresh creds, the outbox drains on next `sync` (do NOT hand-write the JSONL cache). |
| 7 | [pre-deploy] | Decision 72 + 60 carry amendment pointers | `grep -n "Amended by Decision 83" docs/DECISIONS.md` and re-read the Decision 60 substrate line | "Amended by Decision 83" present on the Decision 72 (Branch Protection Not Available) entry; Decision 60 migration note present | If missing, add the prose pointer (narrative-only — do NOT restamp the old warehouse rows). |
| 8 | [pre-deploy] | Prompt-compliance + lint gate passes | `bin/venv-python -m scripts.validate --pre` | Exit 0 | Fix any flagged instruction-surface / format issue. |
| 9 | [post-deploy] | The `oidc.tf` comment edit applies as a no-op | On the merge-commit SHA: `mcp__github__actions_list` → `terraform-apply-sandbox` run; read its `Terraform plan` step log | Plan reports "No changes" / 0 to add-change-destroy; guard OK; apply no-op; run green | If a real diff appears, the edit accidentally changed a resource — investigate. If red on token/auth, refresh `CLAUDE_CODE_OAUTH_TOKEN` (apply-pipeline issue, not a plan defect). |

## Constraints
- **Single-Portal Invariant:** the decision write goes through `scripts.ops_data_portal.file_decision` only. NEVER `Edit`/`Write` `logs/.decisions-index.jsonl` or `logs/.recommendations-log.jsonl`. `DECISIONS.md` is the legitimate non-warehouse ETL source of truth and may be edited directly (per AGENTS.md). (Decisions 69 / 78 / 81.)
- **Do NOT hardcode the warehouse decision id.** `file_decision` allocates `dec-NNN` atomically via DynamoDB and returns it; the human-facing "Decision 83" heading is a separate file-counter (verify next-free = 83 by reading the top of `DECISIONS.md`). The two numbers need not be equal — capture whatever `file_decision` returns.
- **The "Amended by Decision 83" pointer is a narrative edit only** — it does NOT restamp the Decision 72 warehouse row. The amendment linkage lives in the NEW decision's body (mirrors the Decision 67->79 and Decision 72->76 precedents).
- **Comment/docstring edits must not change behaviour.** `terraform_apply_guard.py::evaluate_plan` and its exit codes, and `terraform-apply-sandbox.yml`'s steps, are untouched except for prose. The guard stays fail-closed.
- **Out of scope (do not touch):** the genuinely-pending DuckLake apply note in `ROADMAP-PLATFORM.yaml` (~L3535); all `docs/plans/PLAN-*.md` (committed history, frozen by convention); the CD.35 wave items (T2.20-T2.25) — this plan reconciles the *premise*, not the CD.35 build.
- No rescue agents or workaround loops (Decision 55). If a control probes not-live, mark the gap honestly rather than forcing T2.12 to `complete`.

## Context
- **Verified finding (2026-06-08):** GitHub branch API returns `"protected": true` for `main`; `terraform/github/repo.tf` `main_protection` ruleset has `enforcement = "active"`; `dependabot/pip/*` branches confirm Dependabot is active. The `terraform/github/` (T2.12 / CD.20) apply has landed; the docs lag.
- **Decision-scout gate: NO_FLAGS.** Two NOTE refinements folded in above (no hardcoded `dec-083`; narrative-only pointer). One RELATED drift item folded in: Decision 60's stale "branch protection requires the workflow to pass" substrate line gets a migration note.
- **Decisions this plan must cite** (scout CITE list): Decision 72 (amendment target — note `DECISIONS.md` has two entries numbered 72; this is "GitHub Branch Protection Not Available" at ~L769, cite by title), Decision 76 (already foresaw the reversal: "unblocked now the repo is public ... reversing Decision 72's 'permanently unavailable' premise"), Decision 77 (the guard rationale the comment edits must preserve), Decision 73 (forward-fix model designed around the old premise — the design is preserved, only the premise reverses), Decision 75 (frames this as a sanctioned premise-correction, matching the Decision 82 precedent that "reverses the premise but preserves the design consequences").
- **The amendment's substance:** Decision 72's "permanently unavailable" premise is false (repo public since 2026-05-30 per Decision 73/CD.21; `main_protection` ruleset active). The merge-gate consequences are PRESERVED, not overturned: the ruleset is deliberately configured non-wedging — `bypass_actors` admin `bypass_mode = "always"`, `strict_required_status_checks_policy = false`, required checks = `pr-validate` + `terraform-validate` only, and `terraform-converged` is advisory-not-required (CD.35) — so the forward-fix model, the Decision 76 squash-merge flow, and autonomous merge all still hold.
- **Main divergence:** preflight `main_freshness` = 0 behind / 0 ahead; no Scope file changed on main since branch. No rebase needed.
- **Telemetry:** session opened (`31aa34f2-4b90-4af6-bdd1-883d54a63775`); Athena reader degraded (ACCESS_DENIED on Iceberg metadata HeadObject) — VP step 6's warehouse round-trip may fall back to the outbox; that is acceptable (the rec/decision is durable, drains on next healthy `sync`).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (esp. Decision 72 @ ~L769, Decision 60, Decision 82 as wording template)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Run the live-state probes (VP 1-4)** and record each verdict. If VP 1 (`main` protection) is not `true`, **STOP** — surface to the human; the premise reversal is unsafe.
2. **`AGENTS.md`** — rewrite the T2.12 temporary-constraints bullet: controls applied/live (GHAS secret scanning + push protection, `main-protection` ruleset active with admin bypass actor, CodeQL, Dependabot, Actions permissions), referencing that the apply landed via the `terraform/github/` human-gated local apply. Keep it one tight bullet (agent-first).
3. **`docs/ROADMAP-PLATFORM.yaml`** — set T2.12 `status: complete` + `completed_at: "2026-06-08"` and refresh `progress_note` to record the apply landed and which controls were probe-verified. If any VP 2-4 control was NOT verified live, instead keep `in_progress`/partial and name the outstanding control explicitly. Do not touch the unrelated DuckLake note (~L3535).
4. **`.github/workflows/terraform-apply-sandbox.yml`** — fix the ~L8 header comment: branch protection / required status checks ARE now live (`main-protection`), and the guard + subagent review remain the *content* gate for the auto-apply path (per Decision 77 / CD.35). Logic untouched.
5. **`scripts/terraform_apply_guard.py`** — update the module docstring: the guard is the fail-closed plan-CONTENT control (no destroy/IAM/trust in an auto-apply); drop the "absence of branch protection" framing. Code untouched.
6. **`terraform/personal/oidc.tf`** — fix the ~L239-240 parenthetical: branch protection is live; the apply role's `refs/heads/main`-only trust + the fail-closed guard remain the compensating controls bounding this highest-blast CI role. Comment-only.
7. **`docs/INTENT-ci-cd-architecture.md`** — update the ~L15 hard-constraint #1 and the ~L461 Decision-72 row: protection available + active but deliberately non-wedging (admin bypass always, strict=false, required = pr-validate + terraform-validate, terraform-converged advisory); forward-fix/convention design preserved.
8. **File the amendment via the portal:** `bin/venv-python -c "from scripts.ops_data_portal import file_decision; print(file_decision({'title': 'Branch protection now active -- amends Decision 72 premise', 'status': 'Decided', 'rationale': '<premise-reversal-preserving-consequences>'}))"` (use the full field set per `get_rec_write_guidance`/Decision schema; capture the returned `dec-NNN`).
9. **`docs/DECISIONS.md`** — add the "## Decision 83: ..." narrative (verify next-free heading number by reading the file top; latest is Decision 82) recording the premise reversal + preserved consequences + the cited decisions; add the "Amended by Decision 83" pointer to the Decision 72 (Branch Protection Not Available) entry, replacing its stale "remains deferred" migration note; add a one-line migration note to Decision 60's stale substrate line.
10. **Sync:** `bin/venv-python -m scripts.sync_ops sync` (or `pull`) to propagate the decision (or drain the outbox if offline).
11. **Execute Verification Plan** — run each step. Loop until pass. Do not force T2.12 `complete` if a control probe failed (Decision 55: mark the gap, no workaround).
12. **Report:** surfaces reconciled, probe verdicts, the allocated `dec-NNN` + "Decision 83" heading, VP results, and any control marked outstanding.

## Work Areas (STRATEGIC plans only)
N/A — IMPLEMENTATION.
