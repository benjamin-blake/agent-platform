# Plan

## Intent

Close the verification gap that allows features to ship with passing acceptance criteria but broken end-to-end behaviour -- directly serving the North Star by making the self-improving feedback loop trustworthy: testing enforcement means the system can only improve, never silently regress.

## Plan Type

IMPLEMENTATION

## Verification Tier

V1 (Static) -- all scope files are docs, prompts, configs, or JSONL; no runtime Python changes.

## Branch

agent/platform-verification-tiers

## Phase

Phase Platform (automation infrastructure)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| logs/.recommendations-log.jsonl | Modify | Close rec-461, rec-462, rec-401, rec-426 as already_implemented |
| docs/DECISIONS.md | Modify | Add Decision 48: Verification Tier Classification |
| .github/prompts/plan.prompt.md | Modify | Add Verification Tier field to plan template + classification rules (new Step 5e) |
| .github/prompts/implement.prompt.md | Modify | Add V3 iterative deploy-test-fix loop guidance |
| config/prompts/executor/planning.prompt.md | Modify | Add Verification Tier classification rule for executor plans |
| config/prompts/executor/critique.prompt.md | Modify | Add hard-fail rule: V3 plans without invocation step are NEEDS_REVISION |

## Bundled Recommendations

| Rec | Effort | Priority | Current Status | Action |
|-----|--------|----------|---------------|--------|
| rec-461 | S | High | open (already implemented PR #228) | Close as already_implemented |
| rec-462 | XS | High | open (already implemented PR #228) | Close as already_implemented |
| rec-401 | XS | High | open (already implemented PR #228) | Close as already_implemented |
| rec-426 | S | High | open (already implemented) | Close as already_implemented |

## Acceptance Criteria

- [ ] rec-461, rec-462, rec-401, rec-426 all have status "closed" and execution_result "already_implemented" in JSONL
- [ ] docs/DECISIONS.md contains "Decision 48" with Verification Tier Classification
- [ ] .github/prompts/plan.prompt.md contains "Verification Tier" section (Step 5e) with V1/V2/V3 classification rules
- [ ] .github/prompts/implement.prompt.md contains V3 iterative deploy-test-fix loop guidance
- [ ] config/prompts/executor/planning.prompt.md contains Verification Tier classification rule
- [ ] config/prompts/executor/critique.prompt.md contains hard-fail rule for V3 without invocation step
- [ ] python scripts/validate.py exits 0

## Constraints

- Executor boundary files (config/prompts/executor/planning.prompt.md, config/prompts/executor/critique.prompt.md) must go through /plan -> /implement, not the executor (Decision 44)
- No new Python scripts in this plan -- enforcement is through workflow rules and Decision documentation; automated tier detection is a future enhancement
- Verification Tier classification must be deterministic based on scope files, not LLM judgment
- config/prompts/executor/ files are Lambda-packaged via copytree (build_lambda.py L58) but not read by any Lambda handler. Lambda deploy step is omitted intentionally.

## Context

### Why the rec-curator was not tested

The rec-curator pipeline (rec-448, rec-450, rec-451) was built across sessions 25-27. Every rec in the chain had **structural acceptance** -- grep checks that verified file contents existed, not that the system worked. The test_coverage_checker.py enforced 100% unit test coverage for Python files, but:

1. **rec-448** (prompt rewrite): Acceptance was `grep -qE "decay_date|north_star_impact" .github/prompts/scheduled/rec-curator.prompt.md`. This verifies the prompt file contains the right keywords, not that the Lambda can parse and execute it.

2. **rec-451** (session_preflight.py queue display): Acceptance was `python -m pytest tests/test_session_preflight.py -x -q`. Unit tests pass with mocked S3 reads, but the actual S3 key path was wrong (`active` vs `queued` status, missing subdirectory prefix). The unit tests verified the code logic in isolation, not the contract between services.

3. **rec-450** (EventBridge rule): Acceptance was `grep -qE "rec.curator|rec_curator" terraform/scheduled_agents.tf`. Terraform syntax, not invocation.

When the rec-curator was first triggered live (session 28), 7 bugs surfaced:
- Model hallucinated bash tool calls (prompt assumed shell access)
- S3 data not injected into prompt (handler missing preload logic)
- max_tokens=4096 too small for output
- Model ID requires Marketplace subscription (SCP blocked)
- Cross-region profile hits SCP-blocked region (eu-north-1)
- boto3 read timeout (60s default, call takes ~5 minutes)
- AWS CLI read timeout (60s default, Lambda takes ~10 minutes)

**None of these bugs were catchable by the existing verification framework.** The framework enforces unit test coverage (V2) but has no mechanism to require integration/deployment testing (V3) for features that interact with external systems.

### Root cause: Missing Verification Pyramid

The codebase has three verification levels, but only the first two are enforced:

| Level | Name | Enforced? | Mechanism |
|-------|------|-----------|-----------|
| V1 | Static | Yes | ruff, validate.py, grep acceptance |
| V2 | Unit | Yes | test_coverage_checker.py (100% coverage gate) |
| V3 | Integration | **No** | Nothing -- Lambda deploy, API contracts, cross-service behaviour |

The Verification Tier System formalizes this by requiring plans to declare which tier applies and enforcing tier-appropriate verification in the Ordered Execution Steps.

### Related Decisions
- Decision 43 (Directed Growth Governance): Established file-level quality gates; this extends to verification-level gates
- Decision 44 (Executor Self-Modification Boundary): executor planning/critique prompts are boundary files
- Decision 47 (Bedrock as Single Lambda Inference Provider): The Lambda Deployment Assessment (Step 5d) is a V3 rule already; this generalizes it

### Already-implemented recs evidence
- rec-461/462/401: Implemented in commit 7bacde1 (PR #228, 2026-04-18)
- rec-426: TestCheckAcceptanceOnMain class exists with 8 test cases, all passing
- All four acceptance commands pass on current main

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions -- confirmed: Decision 43, 44, 47 all aligned)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Close already-implemented recs in JSONL

**File:** logs/.recommendations-log.jsonl

**Pre-condition:** rec-461, rec-462, rec-401, rec-426 all have status "open" in the JSONL. Their acceptance commands all pass on current main (verified during planning).

**Changes:** Append closure entries for all four recs to the JSONL. Each entry must have:
- `status`: `"closed"`
- `execution_result`: `"already_implemented"`
- `execution_date`: current ISO-8601 timestamp
- `execution_branch`: `"agent/platform-verification-tiers"`
- `execution_premium_requests`: `0.0`
- `execution_steps`: `0`

Use Python to append (last-wins JSONL semantics means appending a new entry with updated fields is the correct pattern). Copy all original fields from the existing entry, then override the status/execution fields.

**Post-condition:** `load_recommendation("rec-461")` returns status "closed" with execution_result "already_implemented". Same for rec-462, rec-401, rec-426.

### Step 2: Add Decision 48 to docs/DECISIONS.md

**File:** docs/DECISIONS.md

**Pre-condition:** File exists, contains Decisions 45-47. No existing Decision addresses verification tier classification.

**Changes:** Add a new section at the top of the file (after the heading, before Decision 47), following the existing Decision format:

```
## Decision 48: Verification Tier Classification (Decided)

**Decision:** Every implementation plan must declare a Verification Tier (V1, V2, or V3) based on the files in scope. The tier determines the minimum verification standard the plan's Ordered Execution Steps must meet.

**Problem:**
The rec-curator pipeline (rec-448 through rec-451) shipped with passing acceptance criteria and 100% unit test coverage, but failed on first live invocation with 7 integration bugs. Root cause: acceptance commands verified file contents (V1/structural) or ran unit tests with mocked dependencies (V2), but no step required deploying and invoking the actual Lambda to verify end-to-end behaviour (V3). The existing Lambda Deployment Assessment (Step 5d, Decision 47) addresses Lambda-specific cases but does not generalise to other integration boundaries (e.g., cross-service contracts, S3 key agreements, API schemas).

**Tier Definitions:**

| Tier | Name | Scope Trigger | Minimum Verification |
|------|------|--------------|---------------------|
| V1 | Static | Files with no runtime effect: docs, prompts, configs, .md, .yaml (non-handler) | grep/file-existence acceptance; no pytest required |
| V2 | Unit | Pure Python logic: scripts/, src/ files with no external integration | pytest with 100% coverage (existing test_coverage_checker.py gate) |
| V3 | Integration | Files that interact with external systems: Lambda handlers (src/data/handlers/), schedule.yaml, Terraform, API contracts, cross-service data flows | Deploy + invoke + verify output. Iterative: if invocation reveals bugs, fix and re-invoke in the same session. Acceptance must be behavioural (invoke and check output), never structural (grep exists). |

**Classification Rules (deterministic):**
1. If ANY file in scope matches V3 triggers, the plan is V3 (highest tier wins)
2. If no V3 triggers but any file matches V2 triggers, the plan is V2
3. Otherwise V1

**V3 Scope Triggers (exhaustive list):**
- Files under src/data/handlers/
- .github/agents/schedule.yaml (deployed to Lambda)
- .github/prompts/scheduled/ (deployed to Lambda)
- terraform/*.tf files that create/modify resources with runtime effects
- Any file listed in _LAMBDA_SCRIPTS in scripts/build_lambda.py
- Any change that modifies a cross-service contract (S3 key paths, JSONL schemas consumed by another service, API response formats)

**V3 Ordered Execution Step Requirements:**
1. Deploy step: build and deploy the artifact (e.g., python -m scripts.build_lambda --deploy)
2. Invoke step: trigger the deployed artifact and capture output (e.g., --trigger-lambda NAME, aws lambda invoke)
3. Verify step: check the output matches expectations (e.g., parse S3 output, verify status code)
4. Fix-and-retry: if invocation reveals bugs, fix the code, redeploy, and re-invoke in the same session until the output is correct
5. Acceptance command must be behavioural: it must invoke the system and verify output, not just grep for file contents

**What this does NOT include:**
- Automated tier detection script (future enhancement -- deterministic based on file paths, suitable for a Python script in scripts/)
- Changes to test_coverage_checker.py (V2 enforcement is already working; V3 is a different layer)

**Related:** Decision 43 (Directed Growth Governance), Decision 44 (Executor Boundary), Decision 47 (Lambda Deployment Assessment -- V3 subset)

**Limitation:** Verification tier classification is documentation-enforced only. No automated detection currently exists. A future rec should add a deterministic tier classifier to validate.py based on scope file paths, closing the enforcement gap that motivated this decision.

**Decision status:** Decided -- April 2026
```

**Post-condition:** docs/DECISIONS.md contains "Decision 48" with Verification Tier definitions.

### Step 3: Add Verification Tier section to plan.prompt.md

**File:** .github/prompts/plan.prompt.md

**Pre-condition:** File contains Step 5d (Lambda Deployment Assessment). No existing Verification Tier section.

**Changes:** Add a new section `## Step 5e: Verification Tier Classification` immediately AFTER `## Step 5d: Lambda Deployment Assessment` and BEFORE `## Step 6: Create Branch`.

Content (add as-is):

```
## Step 5e: Verification Tier Classification

Every plan must declare a `## Verification Tier` field in the plan template (after `## Plan Type`). Classification is deterministic based on scope files:

**V1 (Static):** Scope contains only docs, prompts, configs, markdown, or YAML files with no runtime effect.
- Minimum verification: grep/file-existence acceptance commands
- Example: prompt rewrites, Decision entries, config YAML creation

**V2 (Unit):** Scope contains Python source files (scripts/, src/) with no external integration.
- Minimum verification: pytest with 100% coverage (enforced by test_coverage_checker.py)
- Example: refactoring a function, adding a validation gate to validate.py

**V3 (Integration):** Scope contains files that interact with external systems.
- Triggers: src/data/handlers/, .github/agents/schedule.yaml, .github/prompts/scheduled/, terraform/*.tf with runtime resources, files in _LAMBDA_SCRIPTS in build_lambda.py, or any change to a cross-service contract (S3 key paths, JSONL schemas consumed by another service)
- Minimum verification: deploy + invoke + verify output. Acceptance must be behavioural (invoke the system), never structural (grep for contents).
- V3 plans MUST include an iterative deploy-test-fix loop in Ordered Execution Steps:
  1. Deploy the artifact
  2. Invoke and capture output
  3. If output is wrong, fix the code, redeploy, and re-invoke
  4. Repeat until output is correct
  5. Only then write acceptance as passing

**Highest tier wins:** If any file in scope triggers V3, the entire plan is V3.

**The plan template's `## Verification Tier` field must be one of: V1, V2, V3.**

Reference: Decision 48 (docs/DECISIONS.md)
```

Also add the `## Verification Tier` field to the plan template in Step 7 (the template markdown block). Add it as a new line immediately after `## Plan Type`:

```
## Verification Tier
V1 / V2 / V3

(Determined by Step 5e classification. V3 if any scope file triggers integration verification.)
```

**Post-condition:** plan.prompt.md contains Step 5e with Verification Tier rules, and the plan template includes the Verification Tier field.

### Step 4: Add V3 iterative deploy-test-fix guidance to implement.prompt.md

**File:** .github/prompts/implement.prompt.md

**Pre-condition:** File exists and contains quality gate validation rules. No existing Verification Tier guidance.

**Changes:** Add a new section between Step 4 (File Recs to Log, ending ~L152) and Step 5 (Validate, Commit, and Merge, beginning ~L154), as a new heading `## V3 Integration Verification`:

```
## V3 Integration Verification (Plans with Verification Tier: V3)

When implementing a V3 plan, the Ordered Execution Steps will include deploy + invoke + verify steps. The implementing agent must follow this iterative protocol:

1. **Complete all code changes** per the plan steps
2. **Deploy** the artifact (e.g., `python -m scripts.build_lambda --deploy`)
3. **Invoke** the deployed system and capture output (e.g., `--trigger-lambda NAME`, `aws lambda invoke`)
4. **Inspect output** for correctness:
   - If output is correct: proceed to acceptance verification
   - If output reveals a bug: diagnose, fix the code, redeploy, and re-invoke
   - Continue the fix-deploy-invoke loop until output is correct
5. **Do not close the rec** until the invocation produces correct output
6. **Document** any bugs found and fixed during the loop in the implementation summary

This protocol exists because V3 features cannot be verified by unit tests alone. Mocked dependencies hide integration bugs (wrong S3 keys, timeout configurations, IAM permissions, cross-service schema mismatches). The only reliable verification is invoking the real system.

The plan's acceptance command for V3 features should verify the deployment artefact's output, not just file contents:
- **Good V3 acceptance:** `python -m scripts.run_scheduled_agent --trigger-lambda rec-curator` (behavioural)
- **Bad V3 acceptance:** `grep -q "priority-queue-entry" .github/prompts/scheduled/rec-curator.prompt.md` (structural)

Reference: Decision 48 (docs/DECISIONS.md), Step 5e of plan.prompt.md
```

**Post-condition:** implement.prompt.md contains V3 Integration Verification section.

### Step 5: Add Verification Tier rule to executor planning.prompt.md

**File:** config/prompts/executor/planning.prompt.md

**Pre-condition:** File contains Lambda Deployment Assessment section. No existing Verification Tier rule.

**Changes:** Add a new section after the existing "Lambda Deployment Assessment -- CRITICAL" section:

```
## Verification Tier Classification -- CRITICAL

Every executor plan must classify its Verification Tier based on the recommendation's target files:

- **V1 (Static):** Target file is docs, prompts, configs, markdown, or YAML with no runtime effect. Acceptance can be grep-based.
- **V2 (Unit):** Target file is Python source (scripts/, src/) with no external integration. Acceptance must use pytest.
- **V3 (Integration):** Target file interacts with external systems (src/data/handlers/, schedule.yaml, .github/prompts/scheduled/, terraform/*.tf, files in _LAMBDA_SCRIPTS). Acceptance must be behavioural -- invoke the deployed system and verify output. The plan MUST include deploy + invoke steps.

Highest tier wins. If the recommendation's `file` field or acceptance command touches V3 triggers, classify as V3.

V3 plans that use structural acceptance (grep for file contents) instead of behavioural acceptance (invoke and verify output) are invalid. The critique will reject them.

Reference: Decision 48 (docs/DECISIONS.md)
```

**Post-condition:** config/prompts/executor/planning.prompt.md contains Verification Tier Classification section.

### Step 6: Add Verification Tier hard-fail rule to executor critique.prompt.md

**File:** config/prompts/executor/critique.prompt.md

**Pre-condition:** File contains Hard-Fail Rules section with Lambda deployment rule.

**Changes:** Add to the Hard-Fail Rules section, as a new paragraph after the existing Lambda deployment rule:

```
Plans classified as V3 (integration verification) that use structural acceptance commands (grep, test -f, file-existence checks) instead of behavioural acceptance commands (invoke the deployed system and verify output) are NEEDS_REVISION. V3 plans must include: (a) a deploy step, (b) an invoke step that triggers the real system, (c) a verify step that checks the output. Structural acceptance for V3 features hides integration bugs that only surface on first live invocation. Reference: Decision 48.
```

**Post-condition:** config/prompts/executor/critique.prompt.md contains V3 verification hard-fail rule.

### Step 7: Run validation

Run `python scripts/validate.py` -- must exit 0. This confirms all file edits are syntactically valid and no rules are broken.

### Step 8: Report implementation summary

Report what was implemented and any design decisions made during implementation. List any issues encountered and how they were resolved.
