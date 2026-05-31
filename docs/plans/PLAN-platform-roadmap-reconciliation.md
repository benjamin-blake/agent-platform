# Plan

## Intent
Reconcile `docs/ROADMAP-PLATFORM.yaml` with the repository's actual post-migration state (off the company AWS account onto a personal account; primary dev surface = Claude Code on the web; repo now public) so the roadmap's harness-consumed eligibility computation reflects reality instead of stale bookkeeping. This advances NS.4 (the repo is for agents): the roadmap is the canonical machine-readable source the planning surface reads every session, and a roadmap that lies about its own state misdirects every downstream `/plan`.

## Plan Type
IMPLEMENTATION

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-platform-roadmap-reconciliation.md

## Phase
Platform roadmap meta-governance: T-1 / T0 / T2 tier reconciliation. This is not a single tier_item; it updates the roadmap's own status bookkeeping after the "public-migration" PR series (#1-#17) landed work through ad-hoc plans rather than through the tier_items. (Product roadmap is a sibling document and out of scope.)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/ROADMAP-PLATFORM.yaml | Modify | Flip migration-realized tier_items to complete; append `[Realized ...]` amendment lines to now-real candidate decisions; add post-flip-debt progress_notes; land bundled rec corrections |

No source code, schema, or other documents change. `CandidateDecision`/`TierItem` Pydantic models in `scripts/platform_roadmap.py` are read-only references for this plan (see Constraints).

## Bundled Recommendations
- **rec-817** (XS, Low) — Reconcile Windows-path replacement count discrepancy in T0.14 notes vs session log. Target file is `docs/ROADMAP-PLATFORM.yaml`; corrected as part of the T0.14 audit.
- **rec-1950** (XS, Low) — T2.15 `depends_on` should reference T2.13 as a semantic upstream gate. Landed as part of the T2.13 reconciliation.

## Acceptance Criteria
- [ ] The six clear-cut migration-realized items (**T0.2, T0.3, T2.1, T2.3, T2.10, T2.13**) are `status: complete`, each with a real `completed_at` PR-merge date, `bootstrap_completion_exempt: true`, and a `note` citing the evidence (PR / artefact path).
- [ ] **T2.13** additionally carries a note that the public flip landed ahead of CD.20's planned security/portal sequence.
- [ ] **T0.5** is resolved per the judgment rule in Step 4 (default: `complete` with a supersession note; fallback: `not_started` with a retire/rescope note) - never left silently stale.
- [ ] **T0.14** and **T2.2** are resolved per the evidence rule in Step 5 (flip only on positive evidence; otherwise keep current status with a corrected note). rec-817's count discrepancy is reconciled in T0.14's note regardless.
- [ ] **T2.11a, T2.11b, T2.12** remain `not_started`, each with a `progress_note` documenting outstanding post-flip portal/security debt. T2.12's note reflects the Decision 72 nuance (repo-visibility blocker resolved; gate deferred per CD.20).
- [ ] Candidate decisions **CD.2, CD.6, CD.20, CD.21, CD.26** keep `state: pending` and each `detail` gains a `[Realized 2026-05-DD: ...]` amendment line. No new keys are added to any CandidateDecision (model is `extra="forbid"`).
- [ ] **T2.15.depends_on** includes **T2.13** (rec-1950).
- [ ] `document.status` stays `draft` and `document.filed_via` stays `pending_log_decision_lambda` (the roadmap's own ratification vehicle, T0.7b, has not landed).
- [ ] Tiers **T1, T3, T4, T5** are confirmed unchanged (all `not_started` except the existing `T1.8: reserved`); the reconciliation introduced no edits there.
- [ ] `RoadmapDocument` Pydantic schema validates and full `validate.py` passes (CI parity).
- [ ] `session_preflight` recomputes `platform_roadmap.next_eligible` to reflect the flips (T0.2 no longer eligible; newly-unblocked items surface).
- [ ] rec-817 and rec-1950 are closed via the ops portal (`update_rec`, `execution_result=success`).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-deploy | Roadmap parses + schema-validates | `bin/venv-python -m scripts.platform_roadmap` | Exit 0; emits eligibility state; no `ValidationError`/`ValueError` | Schema/grammar error -> fix the offending field; confirm no new CandidateDecision key was added (extra="forbid") |
| 2 | pre-deploy | Flipped items are complete + exempt + dated | `bin/venv-python - <<'PY'`<br>`import yaml; d=yaml.safe_load(open("docs/ROADMAP-PLATFORM.yaml"));`<br>`m={i["id"]:i for i in d["tier_items"]};`<br>`ids=["T0.2","T0.3","T2.1","T2.3","T2.10","T2.13"];`<br>`assert all(m[i]["status"]=="complete" and m[i].get("completed_at") and m[i].get("bootstrap_completion_exempt") and m[i].get("note") for i in ids), [(i,m[i]["status"]) for i in ids];`<br>`print("ok")`<br>`PY` | Prints `ok` | A flip is missing status/completed_at/exempt/note -> complete the field set for that item |
| 3 | pre-deploy | Deferred gates stay not_started with progress_note | `bin/venv-python - <<'PY'`<br>`import yaml; d=yaml.safe_load(open("docs/ROADMAP-PLATFORM.yaml"));`<br>`m={i["id"]:i for i in d["tier_items"]};`<br>`ids=["T2.11a","T2.11b","T2.12"];`<br>`assert all(m[i]["status"]=="not_started" and m[i].get("progress_note") for i in ids), [(i,m[i]["status"]) for i in ids];`<br>`print("ok")`<br>`PY` | Prints `ok` | Missing progress_note or wrong status -> add the post-flip-debt note |
| 4 | pre-deploy | CDs unchanged-state but carry realized amendment | `bin/venv-python - <<'PY'`<br>`import yaml; d=yaml.safe_load(open("docs/ROADMAP-PLATFORM.yaml"));`<br>`c={x["id"]:x for x in d["candidate_decisions"]};`<br>`ids=["CD.2","CD.6","CD.20","CD.21","CD.26"];`<br>`assert all(c[i]["state"]=="pending" and "Realized" in c[i]["detail"] for i in ids), [(i,c[i]["state"]) for i in ids];`<br>`print("ok")`<br>`PY` | Prints `ok` | State changed or amendment missing -> keep state=pending; append `[Realized ...]` to detail |
| 5 | pre-deploy | rec-1950 + document-level invariants | `bin/venv-python - <<'PY'`<br>`import yaml; d=yaml.safe_load(open("docs/ROADMAP-PLATFORM.yaml"));`<br>`m={i["id"]:i for i in d["tier_items"]};`<br>`assert "T2.13" in m["T2.15"]["depends_on"], m["T2.15"]["depends_on"];`<br>`assert d["document"]["status"]=="draft";`<br>`print("ok")`<br>`PY` | Prints `ok` | Missing dep or status drift -> add T2.13 to T2.15.depends_on; restore document.status=draft |
| 6 | pre-deploy | Eligibility recomputed; T0.2 no longer eligible | `bin/venv-python -m scripts.session_preflight && bin/venv-python - <<'PY'`<br>`import json; r=json.load(open("logs/.preflight-report.json"));`<br>`elig=[i["id"] for i in r["platform_roadmap"]["next_eligible"]];`<br>`assert "T0.2" not in elig, elig;`<br>`print("next_eligible:", elig)`<br>`PY` | Prints a next_eligible set without T0.2 | T0.2 still eligible -> its status flip did not take; re-check Step 2 |
| 7 | pre-deploy | Full CI-parity validation (authoritative) | `bin/venv-python -m scripts.validate` | Exit 0; all checks pass | Any failure -> fix the reported check; do NOT bypass |

## Constraints
- Only `docs/ROADMAP-PLATFORM.yaml` is in scope. Do not edit `scripts/platform_roadmap.py`, `CLAUDE.md`, `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, or any source file. (PROJECT_CONTEXT.md already describes the personal account / OIDC / static-key reality; AGENTS.md already carries the T2.12-deferred note. Updating dependent surfaces is a separate follow-up if desired.)
- `CandidateDecision` is `extra="forbid"` with no `realized`/`note` field. Realized annotations MUST go inside the existing `detail` string as a `[Realized 2026-05-DD: ...]` line (the convention already used by CD.7/CD.11/CD.17). Adding a new key fails the Pydantic check.
- `TierItem.status` is `Literal["not_started","in_progress","complete","reserved"]` - there is no "deferred"/"superseded" status. Out-of-sequence and superseded reality is recorded in the `note` / `progress_note` string fields, not a new status value.
- The graph validator checks id-uniqueness, depends_on resolution, and cycles - it does NOT enforce that a complete item's deps are complete. Out-of-order completes pass CI but MUST be justified in `note` so the divergence is auditable.
- **No post-update work in this plan** (human directive): T2.12 security hardening, T2.11a/b portal authoring, T0.6/T0.7 Lambda tooling, and product L1.alpha work are follow-up plans, captured only as advisory pointers in Context.
- This is an IMPLEMENTATION plan, not STRATEGIC (Decision 67 freeze; confirmed by decision-scout). No Lambda-packaged files are touched, so no Lambda build/deploy/DEFERRED steps apply.
- Rec status closure goes through `python -m scripts.ops_data_portal` (`update_rec`), never by editing `logs/.recommendations-log.jsonl` (Single Portal Invariant).
- No rescue agents or workaround loops (Decision 55). If `validate.py` fails for a reason outside this edit, stop and diagnose - do not paper over.

## Context

### Decision-scout outcome
Gate verdict was **FLAGS_FOUND** (one WARN). The WARN is resolved in this plan and recorded below; it is not deferred.

**Resolved WARN - completion-while-CD-pending.** The roadmap's `agent_instructions` state a CD must be ratified before its gated tier_items can be marked complete, with the sole carve-out being the per-item `bootstrap_completion_exempt` flag. The migration-realized items (T0.2, T0.3, T0.5, T2.1, T2.3, T2.10, T2.13) are NOT in the enumerated legacy/CD.25 exempt sets, yet their gating CDs (CD.2[T0], CD.6[T2], CD.21[T2.10], CD.20[T2.13], CD.26[T0.3]) stay pending because the ratification vehicle (T0.7b log-decision Lambda) is not built. **Resolution (human-accepted): add `bootstrap_completion_exempt: true` to each flipped item, with a `note` explaining it is in the same circular bind as the 29 items already carrying the flag** (CD cannot ratify until T0.7b lands). This is the only schema-consistent way to honor both human decisions (keep CDs pending AND mark realized items complete); leaving the items in_progress would defeat the reconciliation's purpose.

### Decisions to cite (in the relevant item notes / CD amendments)
- **Decision 76** (Claude-Code-on-the-Web workflow migration) - the ratified anchor for "the migration happened"; cite in T0.2 and T2.13 notes and the CD.2 amendment.
- **Decision 77** (two-axis environment/phase taxonomy + sandbox auto-apply) - governs the `terraform/personal/` partial-backend reality; cite in the T2.1 note and CD.6 amendment.
- **Decision 73** (two-tier diff-aware CI + CI-RCA) - the OIDC/hosted-runner migration and the V1 `validate.py` verification both sit inside this CI model; cite in the T2.10 note and CD.21 amendment.
- **Decision 67** (Lambda + STRATEGIC plan freeze) - confirms plan-type is correctly IMPLEMENTATION.
- Related (awareness only, no citation obligation): **Decision 24** (company-aws-profile retirement, neighbour to T2.3), **Decision 48** (V1 tier classification confirmed), **Decision 72** (branch-protection - visibility blocker now resolved, gate still deferred per CD.20; word T2.12's progress_note accordingly).

### T0.5 judgment note
T0.5 ("session-start hook with device-code SSO bootstrap") had its mechanism superseded: SSO was abandoned for the personal account per CD.26, and `.claude/hooks/session_start_aws.sh` now performs static-key chain verification at session start. The session-start auth-bootstrap *intent* is met by a different mechanism. Default representation is `complete` + supersession note. If the implement agent finds the hook does not actually satisfy the intent, fall back to `not_started` + a note that T0.5 is superseded by CD.26 and a candidate for retirement/rescope.

### What to develop next (advisory - OUT of scope for this plan, for follow-up `/plan` sessions)
Derived from the *reconciled* roadmap, in recommended order:
1. **T2.12 - security-harden the public repo (S, do first).** Repo is public without GHAS secret scanning, push protection, branch protection, CodeQL, Dependabot, or fork-PR policy. Highest-priority follow-up. Aligns with rec-028 (minimum-permissions model) and unblocks rec-940 (PR auto-merge after public-flip).
2. **T2.11a + T2.11b - finish the public surface (XS + S):** `.devcontainer`, `SECURITY.md`, `EVALUATION-PROMPTS.yaml`. Completes CD.20's curated portal.
3. **T0.6 -> T0.7b - Lambda agent-tooling spine (M):** T0.7b (log-decision Lambda) is the ratification vehicle - building it unblocks the entire pending-CD backlog (CD.10's defining capability). Becomes eligible once T0.3 flips complete in this plan.
4. **Product unlock: L1.alpha.1 (alpha() Protocol + Signal contract, S)** - with the platform foundation reconciled, this is where actual trading-system development begins (product roadmap).

### Known gotchas
- **KG.11 (file-size):** this edit adds note/progress_note strings. The file is already large (~3340 lines). Keep notes terse (one or two sentences). If the file crosses ~2500 lines / 50K tokens, file a rec to split per-tier (do not split in this plan).
- **KG.12 (VP refresh):** the VP above asserts against item ids and fields, not line numbers, so it survives YAML growth.
- Idempotency: the status-flip rules are idempotent on resume (an item already `complete` with the right fields is a no-op).

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current`)
- [ ] docs/PROJECT_CONTEXT.md read (personal-account / OIDC / static-key reality)
- [ ] DECISIONS.md entries 76, 77, 73, 67 read for citation wording
- [ ] docs/ROADMAP-PLATFORM.yaml read in full; `scripts/platform_roadmap.py` `TierItem` + `CandidateDecision` models read (field set + `extra="forbid"`)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Read `docs/ROADMAP-PLATFORM.yaml` in full and `scripts/platform_roadmap.py` lines 118-296 (`TierItem`, `CandidateDecision`, `_validate_graph`). Confirm the allowed field set and `extra="forbid"` on both models before editing.
2. **Audit pass.** For each tier_item gather repo evidence: `git log --date=short --oneline` for the public-migration PR series (#1-#17), `terraform/personal/` contents, file existence (`.devcontainer`, `SECURITY.md`, `EVALUATION-PROMPTS.yaml`, `bin/setup-cloud-env.sh`, `terraform/personal/oidc.tf`, `platform_roles.tf`, `.claude/hooks/session_start_aws.sh`), and CLAUDE.md / PROJECT_CONTEXT.md descriptions. Deep verification on T-1 / T0 / T2; confirmation pass that T1 / T3 / T4 / T5 remain `not_started` (except `T1.8: reserved`).
3. **Flip the six clear-cut items** to `status: complete` with `completed_at` (real PR-merge date), `bootstrap_completion_exempt: true`, and an evidence `note`:
   - T0.2 -> complete (`bin/setup-cloud-env.sh` + web-harness migration PR #10; cite Decision 76). completed_at 2026-05-30.
   - T0.3 -> complete (`terraform/personal/platform_roles.tf`, static-key creds PR #4/#5; cite CD.26). completed_at 2026-05-29.
   - T2.1 -> complete (personal-account Terraform Phase B applied+verified, PR #1; cite Decision 77). completed_at 2026-05-28.
   - T2.3 -> complete (`agent-platform` rename PR #1 + legacy-reference sweep PR #11; cite Decision 24). completed_at 2026-05-30.
   - T2.10 -> complete (`terraform/personal/oidc.tf`, EC2 runner retired per CD.21; cite Decision 73). completed_at 2026-05-28.
   - T2.13 -> complete + a note that the public flip (PR #1 merge) landed ahead of CD.20's security/portal sequence (T2.11a/b + T2.12 outstanding). completed_at 2026-05-28.
4. **Resolve T0.5** per the judgment rule: verify `.claude/hooks/session_start_aws.sh` performs session-start auth bootstrap. If yes -> `complete` + `completed_at` 2026-05-29 + `bootstrap_completion_exempt: true` + note "intent met via static-key verification hook per CD.26; original device-code SSO mechanism not built (SSO abandoned for personal account)". If no -> keep `not_started` + note "superseded by CD.26 static-key auth; candidate for retirement/rescope".
5. **Resolve the evidence-dependent items** (flip only on positive evidence):
   - T0.14: reconcile the rec-817 Windows-path count discrepancy in its note. Flip to `complete` only if the Windows-assumption sweep is demonstrably finished; otherwise keep `in_progress` with the corrected note. (T0.14 is already in the enumerated exempt set - no new flag needed.)
   - T2.2: flip to `complete` only if ops + decisions data is demonstrably present in personal-account Athena (preflight `recommendation_sync` pulled 721 recs + 38 decisions - strong evidence) with a note to confirm the CD.19 timestamp policy; add `bootstrap_completion_exempt: true`. Otherwise keep `not_started`.
   - Do NOT flip T2.4 / T2.5 / T2.7 / T2.8 / T2.9 / T2.14 or any T1/T3/T4/T5 item - no evidence of completion; they stay `not_started`.
6. **Deferred gates:** keep T2.11a, T2.11b, T2.12 `not_started`; add a `progress_note` to each documenting post-flip debt. T2.11b's note records that README landed but `SECURITY.md` + `EVALUATION-PROMPTS.yaml` are outstanding. T2.12's note flags urgent security debt (repo public without GHAS/branch protection), worded per the Decision 72 nuance (visibility blocker resolved; gate deferred per CD.20).
7. **CD amendments:** append a `[Realized 2026-05-DD: ...]` line to the `detail` of CD.2, CD.6, CD.20, CD.21, CD.26. Keep every `state: pending`. CD.20's line records partial realization (public flip done; T2.11a/b + T2.12 deferred). Add no new keys.
8. **Bundled rec corrections:** add `T2.13` to `T2.15.depends_on` (rec-1950); ensure the T0.14 note count is reconciled (rec-817, done in Step 5).
9. **Invariant confirm:** `document.status` stays `draft`; `document.filed_via` stays `pending_log_decision_lambda`; T1/T3/T4/T5 untouched.
10. **Execute Verification Plan** - run each step in order. Loop until all pass. Step 7 (`validate.py`) is the authoritative CI-parity gate.
11. **Close bundled recs** via `bin/venv-python -m scripts.ops_data_portal` `update_rec` for rec-817 and rec-1950 (`execution_result=success`, with a one-line resolution referencing this plan).
12. **Report:** list every item whose status/notes changed (with evidence), the CD amendments, the recomputed `next_eligible` set from VP Step 6, and restate the out-of-scope what-next advisory (T2.12 first) for the follow-up planning session.
