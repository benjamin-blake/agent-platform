# Plan

## Intent
Produce the design-of-record and platform-roadmap decomposition for an agent-native Terraform CI/CD
architecture, closing the three gaps the T2.16b migration exposed (non-sticky apply failures, no speculative
plan, the CI self-grant bootstrap). Serves NS.3 (a self-improving platform that can iterate its own
infrastructure autonomously, with a clean human gate only at the irreversible/privilege-escalating boundary).

## Plan Type
REPORT-ONLY

## Verification Tier
V1 (the deliverable is a design document plus roadmap YAML; verified by internal coherence, the multi-perspective
critique gate, and `platform_roadmap` schema validation. The architecture it specifies is downstream V3 work,
gated into the tier_items -- NOT executed in this session.)

## Plan Path
docs/plans/PLAN-terraform-cicd-agent-native.md

## Phase
Net-new platform-roadmap authoring (candidate decision **CD.NN**). Sits after the T2.16b RDS->Neon migration
(merged, #82) and is the deep-dive realisation of the T2.16b retrospective's "CI self-grant redesign" follow-on
(cross-referenced; not double-authored).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-terraform-cicd-agent-native.md` | Create | The design-of-record: 3 gaps, current state, principles, the target architecture + per-component designs, the routine/gated autonomy boundary, build-vs-buy, the roadmap decomposition (Section 8), instruction-surface synchronization, decision-logging, risks, and decision-alignment scoping guards. **This is the substantive deliverable the Step-10 zero-context reviews critique.** |
| `docs/ROADMAP-PLATFORM.yaml` | Modify (AFTER the Step-10 reviews) | Transcribe Section 8 into platform tier_items (Waves 1-5 + cross-cutting) with `depends_on`/effort/exit_criteria, and add the **CD.NN** candidate-decision entry. Done only once the design is vetted, so the roadmap reflects the reviewed design. |

## Bundled Recommendations
- **rec-2079** (consolidate `IAMRoleReconcile` + `IAMPlatformRolesRead` in `github_ci_apply`) -- not implemented
  here; **absorbed by the Wave 4 (bootstrap-root) design** so it is resolved coherently rather than as a spot
  patch. Recorded in the INTENT doc Section 5.8.
- No recs are implemented in this REPORT-ONLY session.

## Infrastructure Dependencies
None in this session -- no `.tf`, `.py`, `.github/`, or instruction file is edited. The design **describes**
downstream V3 infrastructure (read-only plan role, GitHub Environment + OIDC-scoped privileged role, S3
convergence record, `terraform/bootstrap/` root, drift cron), each gated into a tier_item that becomes its own
IMPLEMENTATION plan. The design references the **post-Phase-2 `github_ci_apply` baseline now on main** (#82) as
the bootstrap-tier starting point.

## Acceptance Criteria
- [ ] `docs/INTENT-terraform-cicd-agent-native.md` exists and is internally consistent: the 3 gaps map to the
      component designs (Section 5), which map to the roadmap waves (Section 8), which name the instruction
      files (Section 9).
- [ ] The design correctly reflects live state: `main-protection` is `enforcement = "active"` requiring
      `pr-validate` + `terraform-validate`; native S3 `use_lockfile`; no Environment / convergence-check / drift
      job yet.
- [ ] The two decision-scout NOTE items are addressed in the doc: single-account Environment scope (Decision 77
      clause 5, not Decision 24 multi-account), and each wave authored as IMPLEMENTATION not STRATEGIC
      (Decision 67).
- [ ] The deliverable passes the Step-10 multi-perspective critique (>=2 zero-context reviewers) to PROCEED, or
      the human accepts current state with deferrals logged in Known Gaps.
- [ ] After the reviews: Section 8 is transcribed into `ROADMAP-PLATFORM.yaml` tier_items + a CD.NN entry, and
      `bin/venv-python -m scripts.platform_roadmap` validates.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [report] | Deliverable exists and is non-empty | `test -s docs/INTENT-terraform-cicd-agent-native.md && echo OK` | `OK` | doc missing/empty |
| 2 | [report] | Live-state claims are accurate (ruleset active + required checks) | `grep -nE 'enforcement *= *"active"\|context *= *"pr-validate"\|context *= *"terraform-validate"' terraform/github/repo.tf` | all three present (the doc's Section 2 premise holds) | if absent, the design's "CD.20 is live" premise is wrong -> revise Section 2 + Wave 1 |
| 3 | [report] | Decision-alignment scoping guards present | `grep -nE 'Decision 67\|Decision 24\|single-account\|IMPLEMENTATION not STRATEGIC' docs/INTENT-terraform-cicd-agent-native.md` | both NOTE items addressed (Section 12) | add the missing scoping guard |
| 4 | [report] | Multi-perspective critique gate (Step 10) | (Agent tool) >=2 zero-context reviewers: senior infra/CICD architect + adversarial risk reviewer, against `docs/INTENT-terraform-cicd-agent-native.md` | both PROCEED, or human-accepted deferrals logged in Known Gaps | iterate on findings; re-critique |
| 5 | [post-review] | Roadmap transcription validates | `bin/venv-python -m scripts.platform_roadmap` | `PASS` (new tier_items + CD.NN resolve; `depends_on` edges valid) | fix schema/referential error in the transcribed entries |

## Constraints
- **REPORT-ONLY discipline:** no source/infra/instruction edits this session. The deliverable is the design +
  (post-review) the roadmap transcription. Downstream waves are separate IMPLEMENTATION plans.
- **Roadmap edits AFTER the reviews** (per the human's scoping): transcribe Section 8 only once the zero-context
  reviews have vetted the design, so the roadmap reflects the reviewed architecture.
- **No `DECISIONS.md` edit:** CD.NN is logged as a roadmap candidate-decision now; ratified as a numbered
  Decision when Wave 1 ships (CD.31->D78 / CD.33->D81 precedent).
- **Decision-scout NO_FLAGS** with two NOTE items (single-account Environment; waves are IMPLEMENTATION) -- both
  baked into the doc (Section 12). Cites Decisions 77, 35, 76, 72/CD.20, 55, 73, 44, 79; frame-challenge per 75.
- No emojis; ASCII hyphens; `bin/venv-python` for Python; Bash-only. No rescue agents or workaround loops
  (Decision 55).

## Context
- Authored from an extended design discussion. Decisions settled with the human: **build** (DIY in Actions, not
  TFC/Atlantis/Spacelift); **GitHub Environments** for the gated path; **apply-saved-plan** (not re-plan); the
  **CD.20 native-control substrate is the first wave**; scope also includes **instruction-artifact
  synchronization** and a **candidate Decision (CD.NN)**.
- **Live-state correction:** the human recalled `main-protection` already applied -- confirmed
  (`terraform/github/repo.tf:55`, `enforcement = "active"`). The apply-workflow's "branch protection not
  available" comment is stale. The net-new controls are the convergence required-check and the Environment.
- **Phase 2 merged (#82):** RDS retired + transitional IAM pruned; the post-prune `github_ci_apply` baseline is
  on main, so the Wave-4 bootstrap design can reference final state.
- **Preflight clean:** no open ci-rca recs (no hard block), tree clean, main fresh.
- This is the deep-dive for the T2.16b retrospective's CI follow-on. The retrospective stays the lightweight
  failure-mode record; this owns the architecture. Cross-referenced to avoid double-authoring.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` consulted via the decision-scout gate (NO_FLAGS; CITE list recorded)
- [ ] Live-state claims spot-checked against `terraform/github/repo.tf`, `terraform/personal/main.tf`,
      `terraform-apply-sandbox.yml`
- [ ] Acceptance Criteria understood

## Ordered Execution Steps
1. **[done] Write the design-of-record** `docs/INTENT-terraform-cicd-agent-native.md` (Sections 1-12).
2. **Step-9 plan-critique** of THIS plan artefact (fresh-context subagent).
3. **Step-10 multi-perspective critique** of the INTENT deliverable: >=2 zero-context reviewers (senior
   infra/CI-CD architect for design correctness + dependency cleanliness; adversarial risk reviewer to probe
   live-state divergence, the convergence-check bootstrap deadlock, OIDC trust-scoping, and the bootstrap-root
   chicken-and-egg). Synthesize consensus vs unique findings; present to the human; iterate per direction;
   re-critique until both PROCEED or the human accepts deferrals (logged in Known Gaps).
4. **Transcribe Section 8** into `docs/ROADMAP-PLATFORM.yaml`: Waves 1-5 + cross-cutting as tier_items
   (`depends_on`/effort/exit_criteria/V3) + the **CD.NN** candidate-decision entry. Run VP-5
   (`platform_roadmap`).
5. **Execute the Verification Plan** -- run each step; loop until green.
6. **Merge** the deliverable to main (Decision 76 web MCP flow). REPORT-ONLY: no `/implement` -- the deliverable
   is the output; each wave is a future IMPLEMENTATION `/plan`.

## Known Gaps
(Populated from Step-10 deferrals.) Carry-ins from the INTENT doc Section 11: convergence-check write-authority
proof, speculative-plan exposure scope (`terraform/github/**`?), the `terraform-converged` seed-green to avoid a
PR deadlock, gated-apply throughput, and the one-time bootstrap-root provisioning -- each to be resolved in its
wave's IMPLEMENTATION plan.
