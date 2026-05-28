Refine this plan based on the critique. Address every violation listed.

## Original Plan
{plan_text}

## Critique Feedback
{critique_text}

## Recommendation Context
- **ID**: {rec_id}
- **Title**: {title}
- **Context**: {context}
- **Target File**: {file}
- **Acceptance Criteria**: {acceptance}
- **Dependencies**: {dependencies}
- **Effort Estimate**: {effort}

## Scope Files
{scope_files}

Before generating the revised plan, re-scan ALL acceptance commands against the BANNED Patterns
checklist from the planning prompt. Verify no banned patterns are present.

Return the complete revised plan using this exact format for each step:

### Step N: [Brief title]
**File**: path/to/file.py
**Action**: create|modify|delete
**Description**: What this step does
**Acceptance**: `runnable shell command that exits 0 on success`
