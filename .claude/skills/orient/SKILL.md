---
name: orient
description: Read-only orientation session. Surfaces in-progress/eligible work, CI-RCA triage, ranked what-to-work-on, and up to N disjoint /plan prompts with an overlap matrix and keystone-first sequencing. Chat reply only; writes nothing.
---

# Orient Methodology

You are using this skill to augment the `/orient` workflow. This skill is **strictly read-only**: it produces a chat reply only. No files, roadmap edits, recommendation writes, or decision writes.

Decisions cited: 90 (Four-Tier Workflow Architecture), 59 (prefer deterministic signals), 72 (RCA-as-Plan-Source), 76 (.claude/ canonical), 84 (closed boundary), 86 (no new prose-architecture docs), 88 (egress budget).

## Read-Only Contract

The `/orient` workflow produces **one deliverable: a chat reply**. It:
- Writes no files
- Makes no roadmap status edits
- Files no recommendations or decisions (Single Portal Invariant untouched)
- Issues no git commits or pushes

Status flips remain the verification-earned closing step owned by `/implement` tier-item bookkeeping. Orient reports roadmap state AS AUTHORED -- it never promotes, infers, or corrects status.

## Inputs

| Input | Source | Load method |
|---|---|---|
| CI-RCA recs | `logs/.preflight-report.json` (`ci_rca_unresolved_recs`, `ci_rca_likely_resolved_recs`, alerts) | Read preflight cache |
| Eligible / in_progress items | `logs/.preflight-report.json` (`platform_roadmap.next_eligible`, `in_progress`, `strategic_pending`) | Read preflight cache |
| Blocked-on-CD annotations | `logs/.preflight-report.json` (`platform_roadmap.blocked_on_cd`) | Read preflight cache |
| Gate evaluations | `logs/.preflight-report.json` (`platform_roadmap.gate_evaluations`) | Read preflight cache |
| Roadmap detail | `docs/ROADMAP-PLATFORM.yaml` | Read file |
| Recent main activity | `git log --oneline -10 origin/main` | Bash |

**Read-from-preflight-cache constraint (Decision 88 egress budget; Decision 84 closed boundary):** `/orient` reads the preflight cache -- it must NOT trigger a fresh warehouse reader fan-out. Do not call `bin/venv-python -m scripts.platform_roadmap` or any DuckLake reader verb during orient. The preflight script is the only path that may refresh `logs/.preflight-report.json`.

**Full-projection requirement:** `/orient` requires the full preflight projection (`--roadmap-detail full`). If `platform_roadmap.gate_evaluations` is absent from the cached report, re-run preflight with `--roadmap-detail full` before proceeding (the orient command handles this check in Step 1).

## Status-Trusted-Never-Inferred Rule

Read roadmap `status` exactly as authored in `docs/ROADMAP-PLATFORM.yaml`. Never infer, promote, or correct status from commit activity, PR history, or file existence.

- **Activity-vs-label** (e.g., "a recent commit touched T-X.Y's scope but the label is still `not_started`"): surface as **neutral dispatch context** only -- useful for the operator's prioritization but never a correctness verdict.
- **Trust the label**: the T2.20 lesson is that a merged-but-unverified item is correctly `not_started`. Activity-inference leads to silently skipping the verification step that earns the status flip.
- Status flips require `/implement`'s tier-item bookkeeping gate. Orient has no authority to flip status.

## Tier Item Freshness Gate -- Reference

The single authoritative definition of the Tier Item Freshness Gate lives in the **planning skill** (`.claude/skills/planning/SKILL.md`, section "Tier Item Freshness Gate"). Orient uses the eligible candidates from the preflight cache as its input list. Freshness adjudication (the four checks: silent-completion, stale-reference, supersession, gating-decision) fires per-item inside `/plan` at commitment time, not during orientation.

Do not re-author the four checks here -- that would be drift by design. `/orient` references the planning skill's section; it does not duplicate it.

## Deliverable Shape

The orient deliverable is a structured chat reply with four sections, in order:

### 1. Status Digest

Compact table of tier_items currently `in_progress` or eligible (`not_started` with all depends_on satisfied). Source: `platform_roadmap.next_eligible` and `platform_roadmap.in_progress` from preflight cache.

```
| Tier Item | Status | Phase | Notes |
|---|---|---|---|
| T-X.Y: <name> | in_progress | <phase> | |
| T-X.Y: <name> | eligible | <phase> | gated by CD.NN (related) [if in blocked_on_cd] |
```

**Blocked-on-CD annotation**: for each item in `platform_roadmap.blocked_on_cd`, add a "gated by CD.NN" note in the Notes column including the relationship type (`gates`, `related`, or `decision_required_before`) and whether the item carries `bootstrap_completion_exempt: true` (in which case it may start/complete despite the pending CD). An item can be eligible-to-start while still annotated as gated-by-CD; the annotation informs planning, it is not a hard block on eligibility.

Omit items with status `complete`, `reserved`, or blocked (depends_on not satisfied).

**Gate-evaluation summary** (below the status table): one line per cross-tier gate from `platform_roadmap.gate_evaluations`:
```
Cross-tier gates: G.1 pass | G.8 fail | G.9 fail | G.10 fail
  G.8 deferred reason: <reason> [only shown when verdict is deferred]
```
Deferred gates include the reason string so the operator understands which runtime field is unresolved.

### 2. CI-RCA Triage

Source: `ci_rca_unresolved_recs`, `ci_rca_likely_resolved_recs`, `ci_rca_liveness_alert`, `forward_fix_recursion_alert` from preflight cache. Decision 72 surfacing obligation: all open ci-rca recs are visible here so the operator knows the state before opening `/plan`.

| Preflight signal | Classification | Operator action |
|---|---|---|
| `ci_rca_unresolved_recs` non-empty | **HARD BLOCK** | List each rec (id, priority, title). The next `/plan` enforces the block; orient surfaces it. |
| `ci_rca_likely_resolved_recs` non-empty | **SOFT PROMPT** | "LIKELY RESOLVED -- verify and close." Provide the close command per rec: `bin/venv-python -m scripts.ops_data_portal --update-rec <id> --status closed --resolution 'Fixed by ...'`. |
| `ci_rca_liveness_alert` non-null | **HARD ALERT** | Main CI red >30 min with no rec. Triage immediately. |
| `forward_fix_recursion_alert` non-null | **HARD ALERT** | 3+ ci-rca recs targeting same file in 24h. Triage immediately. |

If HARD BLOCK recs exist, note them prominently at the top of this section. The next `/plan` session will enforce the block; orient provides the full visibility layer.

### 3. Ranked What-to-Work-On

Prioritized work list from the Status Digest:

1. **CI-RCA first**: HARD BLOCK recs appear as item 0 -- they block other work. For each, suggest a `/plan` prompt to resolve it.
2. **In_progress before eligible**: items already in progress have momentum and are typically lower activation cost.
3. **Keystone-first within eligible**: items that unblock the largest downstream depends_on fan-out appear before items with fewer downstream dependents. Compute the downstream fan-out from `depends_on` chains in `docs/ROADMAP-PLATFORM.yaml`; a keystone is an item whose completion enables the largest set of currently blocked items.
4. **Strategic pending**: list separately at the bottom, noted "blocked by executor freeze (CD.17 reversal required)".

Format: numbered list with a one-line rationale per item citing the keystone/momentum/block reasoning.

### 4. /plan Prompts with Overlap Matrix

Up to 5 ready-to-paste `/plan` prompts (one per eligible non-blocked item), ordered keystone-first.

**Overlap matrix** -- before finalizing prompts, compute pairwise overlap between items. Two items overlap if they share at least one `files_in_scope` path, share a `related_candidate_decisions` cd_id, or one is in the other's `depends_on` chain. Non-overlap on all three dimensions = safe to parallelize.

Present the matrix:
```
Overlap matrix:
  T-X.Y vs T-A.B: [file1.py, file2.py]   <- cannot parallelize
  T-X.Y vs T-C.D: none                    <- safe to parallelize
```

**Keystone-first sequencing**: order prompts so items that unblock the most downstream work appear first. Note explicitly which pairs are safe to run in parallel sessions.

If a HARD BLOCK ci-rca rec exists, prepend a zero-th prompt:
```
/plan ci-rca: resolve rec-NNNN (<brief title>)
```

Then one prompt per eligible item:
```
/plan <item-id>: <item-name>
```

## Scope

v1: platform roadmap only. Product-roadmap orientation is deferred.
