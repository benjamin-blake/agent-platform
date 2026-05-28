# Plan

## Intent
Produce `docs/INTENT-aws-migration-platform-evolution.md` -- a single deliberation document that uses the pending AWS migration (company-aws-profile work account -> personal account) as the architectural inflection point to (a) ratify an AWS resource naming convention separating `platform-*` shared resources from `{project_id}-*` project resources, (b) commit to the monorepo-plus-`project_id` multi-project model and explicitly defer the split-repo extraction described in `PLAN-platform-extraction-strategy.md`, (c) validate and extend the existing T0/T1 Lambda dependency ordering for `project_id` awareness, and (d) propose the candidate decisions and tier_items needed in `docs/ROADMAP-PLATFORM.yaml` to land the work in follow-on IMPLEMENTATION plans. Feeds the North Star by keeping the self-improvement loop portable across future projects while collapsing the work-account legacy naming into a clean substrate.

## Plan Type
REPORT-ONLY

The substantive output is `docs/INTENT-aws-migration-platform-evolution.md`. This plan file is the planning artefact that points at it. Per planning skill REPORT-ONLY rules, both files land in the same initial commit, the deliverable goes through the multi-perspective Step 10 critique, and no `/implement` follow-on is required from this plan. Implementation of the proposed CDs and tier_items happens in follow-on IMPLEMENTATION plans that edit `docs/ROADMAP-PLATFORM.yaml`.

## Verification Tier
V1

The deliverable is a markdown document. No runtime code, no infrastructure, no Lambda-packaged files. Verification is structural conformance and grep-based reference correctness against the canonical artefacts the INTENT cites.

## Branch
claude/plan-aws-migration-d2kc5

(Per the session-level instruction: develop on the harness-assigned branch, not a new `agent/{slug}` branch.)

## Phase
T2 (Full state migration to personal account) -- this INTENT is upstream of T2.1 (full Terraform re-deploy) and T2.3 (company-aws-profile profile-reference sweep). It also amends the T-1 governance ratification path by proposing new candidate decisions and tier_items.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-aws-migration-platform-evolution.md` | Create | The substantive deliverable -- ratification document for the three migration threads |
| `docs/plans/PLAN-aws-migration-platform-evolution.md` | Create | This planning artefact |

Read-only context the deliverable consumes (NOT in scope for edits in this plan):

- `docs/ROADMAP-PLATFORM.yaml` -- canonical platform sequencing; INTENT proposes CDs/tier_items to add in a follow-on plan
- `docs/ROADMAP-PRODUCT.md` -- product roadmap; cross-references for `Phase Infra-Env`
- `docs/PROJECT_CONTEXT.md` -- AWS profile, account, bucket conventions
- `docs/DECISIONS.md` -- existing decisions context
- `docs/plans/PLAN-platform-extraction-strategy.md` -- prior REPORT-ONLY on platform extraction; INTENT decides its fate (supersede vs defer)
- `terraform/*.tf` -- current AWS resource naming patterns; INTENT inventories them
- `CLAUDE.md`, `AGENTS.md` -- platform vs product instruction split

## Bundled Recommendations
None. The 271 open recs and 190 non-automatable recs surfaced at preflight are not direct dependencies of this strategic deliberation; any rec that becomes relevant (e.g. rec-725 Terraform state reconciliation) is cited as context inside the INTENT rather than bundled into this plan.

## Acceptance Criteria
- [ ] `docs/INTENT-aws-migration-platform-evolution.md` exists and is internally consistent
- [ ] The INTENT covers all four threads: naming convention, multi-project model commitment, repo rename, Lambda ordering validation
- [ ] At least four candidate decisions (CD.25-CD.28 numbering) are drafted with explicit `gates` lists naming the tier_items they govern
- [ ] At least four new or amended tier_items are proposed with explicit `depends_on` lists; existing tier_item amendments cite the original tier_item id
- [ ] All resource-name mappings (current -> proposed) cite the current resource by name and location (terraform file:line or AWS resource type)
- [ ] Repo rename section lists at least three candidate names with stated tradeoffs and a recommendation
- [ ] Open questions section explicitly enumerates what is deferred for resolution during the Step 10 critique
- [ ] The INTENT explicitly resolves the fate of `docs/plans/PLAN-platform-extraction-strategy.md` (superseded with rationale, OR deferred-option with conditions for revisit)
- [ ] Multi-perspective Step 10 critique gate runs and converges (both agents PROCEED on a fresh round, OR explicit human acceptance with deferral list documented)

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | static | Confirm INTENT deliverable exists and is readable | `test -f docs/INTENT-aws-migration-platform-evolution.md && wc -l docs/INTENT-aws-migration-platform-evolution.md` | File exists with substantive line count (>200 lines) | File missing or stub-only |
| 2 | static | Confirm INTENT references all canonical context files | `grep -E "ROADMAP-PLATFORM\.yaml\|ROADMAP-PRODUCT\.md\|DECISIONS\.md\|PROJECT_CONTEXT\.md\|PLAN-platform-extraction-strategy" docs/INTENT-aws-migration-platform-evolution.md \| wc -l` | At least 5 references (each canonical doc cited at least once) | Missing references; INTENT not grounded |
| 3 | static | Confirm at least four candidate decisions are drafted | `grep -E "^### CD\.(2[5-9]\|3[0-9])" docs/INTENT-aws-migration-platform-evolution.md \| wc -l` | At least 4 CD headings | Fewer than 4 CDs drafted -- under-specified |
| 4 | static | Confirm at least four new/amended tier_items proposed | `grep -E "^#### T(-1\|0\|1\|2)\." docs/INTENT-aws-migration-platform-evolution.md \| wc -l` | At least 4 tier_item references | Fewer than 4 tier_items -- under-specified |
| 5 | static | Confirm naming-convention mapping table present | `grep -c "^\|" docs/INTENT-aws-migration-platform-evolution.md` | Substantive table content (>40 pipe characters indicating multi-row tables) | No mapping table -- naming convention is hand-wavy |
| 6 | static | Confirm repo rename candidates enumerated | `grep -iE "agentic-platform\|bblake-platform\|self-improving" docs/INTENT-aws-migration-platform-evolution.md` | At least three named candidates appear in the doc | Fewer than three candidates -- choice not deliberated |
| 7 | static | Confirm plan-critique gate has run on the PLAN artefact | (manual: Step 9 of the workflow) | `Recommendation: PROCEED` returned | REVISE loop until PROCEED |
| 8 | static | Confirm multi-perspective report critique has run on the INTENT | (manual: Step 10 of the workflow) | Both critic agents PROCEED on a fresh round, OR explicit human acceptance with documented deferrals | Convergence rule not met |

## Constraints

- **No STRATEGIC plans (CLAUDE.md):** This plan is REPORT-ONLY, which is allowed. The INTENT proposes follow-on work as IMPLEMENTATION plans, not as a Work Areas decomposition.
- **No Lambda deployment touches:** This plan modifies no Lambda-packaged files. The CLAUDE.md `Lambda deployment deferred` DEFERRED step is not applicable.
- **Decision 67 (STRATEGIC-plan freeze):** Even when proposing new tier_items, the INTENT must classify each as a single atomic IMPLEMENTATION-shaped item or call out where decomposition is needed in a future planning round. Do not introduce work that would require a STRATEGIC plan to action.
- **Single Portal Invariant:** Do not write to recs/decisions logs from this plan. CDs are proposed in the INTENT document; ratification happens later via the `log-decision` Lambda once T0.7b lands (long timeline).
- **Warehouse-as-source-of-truth:** No data writes; this is documentation only.
- **No rescue agents or workaround loops (Decision 55).**

## Context

- **Why now:** The user is starting the AWS migration to their personal account. T2.1 (full Terraform re-deploy) is the natural moment to land a new naming convention -- doing it after T2.1 would mean a second pass of resource renames. Doing it before T2.1 lets the new account come up clean from day one.
- **Why a single INTENT rather than three:** The three threads (naming, separation, Lambda ordering) are causally linked. The naming convention depends on whether platform vs product is meaningful (separation), and `project_id` on Lambda schemas depends on the multi-project commitment. Splitting into three documents would force forward references between them.
- **Why monorepo + project_id (user decision):** PLAN-platform-extraction-strategy.md proposed a split-repo + submodule architecture. The user chose monorepo + project_id during Step 6, citing lower upfront cost and the absence of a second consuming project today. The INTENT must explicitly handle the fate of the prior REPORT-ONLY (supersede vs defer).
- **Why repo rename now:** Aligns with the AWS rename moment. The repo currently named `agent-platform` is neither machine-learning (formula discovery is symbolic regression) nor a sandbox (it's a production platform). Renaming during the migration window minimises link rot -- GitHub provides automatic redirects but external references to `bblake-platform-*` bucket names also reset to the new convention.
- **Lambda ordering is already mapped:** ROADMAP-PLATFORM.yaml T-1.x / T0.x / T1.x already encode the dependency graph for CD.10's six Lambdas. The INTENT validates this and proposes additive `project_id` work; it does NOT propose to re-sequence the existing depends_on graph.
- **T0.12 schemas already merged (2026-05-19):** RecPayload and DecisionPayload landed without a `project_id` field. The INTENT must propose either an amendment via a new tier_item that adds the field, or absorb into the T2.2 import-mode work.
- **Decision 67 freeze still in effect:** Per CLAUDE.md temporary operational constraints, no STRATEGIC plans can be filed. The follow-on plans this INTENT proposes will all be IMPLEMENTATION-shaped.
- **Preflight context:** SSO required device-code auth (succeeded). `sync_ops.pull` failed with "unstaged writes detected for ops_recommendations -- call sync() first". This is a pre-existing DynamoDB-side outbox condition unrelated to this plan; not blocking. 271 open recs, 0 CI-RCA recs, no friction patterns, no aging recs, no budget bypass alerts. `roadmap_phase` reads as `Phase 1: Core Infrastructure ... COMPLETE` -- preflight has not yet absorbed the platform_roadmap structured state (T-1.4 not yet shipped).

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (`claude/plan-aws-migration-d2kc5`)
- [x] `docs/PROJECT_CONTEXT.md` read
- [x] `docs/ROADMAP-PLATFORM.yaml` read (~1500 lines covering T-1, T0, T1, T2 tier items)
- [x] `docs/ROADMAP-PRODUCT.md` read
- [x] `docs/plans/PLAN-platform-extraction-strategy.md` read in full
- [x] Acceptance Criteria verifiable via the Verification Plan above

## Ordered Execution Steps

This plan's "execution" is the authoring of the INTENT deliverable. The steps below are written for any future agent that picks this plan up after the planning agent's mission completes.

1. Read the canonical context files listed under Scope.
2. Inventory current AWS resource names (grep `terraform/*.tf` for `name` attributes and bucket / Lambda / table / workgroup definitions). Produce a current-state table inside the INTENT.
3. Draft the naming convention as a CD with explicit `platform-*` vs `{project_id}-*` rules. Include the rationale (`platform-*` resources are project-agnostic and survive any one project's lifecycle; `{project_id}-*` resources are scoped and disposable).
4. Draft the monorepo + `project_id` commitment as a CD that explicitly supersedes (or defers, with conditions) the architecture in `PLAN-platform-extraction-strategy.md`.
5. Draft the repo rename CD with 3-4 named candidates and a recommendation.
6. Draft the `project_id` schema extension CD that amends the T0.12 work (since T0.12 is already merged).
7. Propose tier_items: at minimum, (a) a T-1.x or T0.x item adding `project_id` to RecPayload/DecisionPayload Pydantic models, (b) a T2.x item applying the naming convention during the personal-account Terraform re-deploy (gates T2.1), (c) a T2.x item handling the repo rename and reference sweep, (d) amendments to T2.2 (data import with project_id default) and T2.3 (broaden the profile-reference sweep to include legacy resource names).
8. Validate the existing Lambda dependency order (T0.6 -> T0.7a/b/c -> T0.8 -> T1.1 -> T1.2/T1.3 -> T1.9; T1.4 parallel) against the proposed `project_id` work. Surface any items where the new `project_id` field changes the dependency story (e.g. T0.6 IAM role policies that may need a `project_id` claim).
9. Enumerate open questions for the human to resolve during Step 10 critique (final repo name, final SSO profile name, `project_id` as SCD2 partition key, PLAN-platform-extraction-strategy.md fate).
10. **Execute Verification Plan** -- run each step. Loop until pass. If V3 fails unrecoverably, stop and analyze root cause (Decision 55). (Not applicable here -- V1 only.)
11. Report: the INTENT deliverable is the report. The plan critique (Step 9 of the workflow) and the multi-perspective report critique (Step 10 of the workflow) are the verification surface.

## Known Gaps

- The CD numbering proposed in the INTENT (CD.25-CD.28) is provisional. If ROADMAP-PLATFORM.yaml gains additional CDs between this INTENT's authoring and the follow-on IMPLEMENTATION plan, the numbering may shift -- the implementing plan must allocate the next available CD ids at write time.
- This INTENT does not attempt to design the cross-project recommendation query schema (a `rec_project_dim` star-schema dimension or a `project_id` partition key). That is deferred to a follow-on planning round once a second project actually exists.
- This INTENT does not address methodology DNA leakage (the V1/V2/V3 verification tier framing baked into prompts; the AWS-Athena-pytest assumptions baked into skills). PLAN-platform-extraction-strategy.md notes 5 and 6 surface this; it remains deferred.
