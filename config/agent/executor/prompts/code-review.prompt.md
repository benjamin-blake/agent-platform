Review the changed files below against the acceptance criteria.

## Recommendation
- **ID**: {rec_id}
- **Title**: {title}
- **Acceptance Criteria**: {acceptance}

## Implementation Steps That Were Executed
{plan_steps}

## Changed Files
{changed_files}

## File Contents
{files_block}

## Response Format

Each finding MUST start with `CRITICAL:`, `HIGH:`, `MEDIUM:`, or `LOW:` followed by a space, file path, colon, description.

If no CRITICAL or HIGH findings, end with:
`GATE: PASSED — no blocking issues found`

If CRITICAL or HIGH findings exist, end with:
`GATE: FAILED — N blocking issue(s) require resolution before merge`
