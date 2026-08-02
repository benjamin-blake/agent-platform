#!/usr/bin/env bash
# Best-effort archival of review.json / review_retry.json (whichever exist in the working
# directory) to s3://<bucket>/ci-rca-evidence/review-transcripts/<run_id>/, so a later
# investigation can see WHY the reviewer stalled (rec-2923 preventive action).
#
# TOTAL by construction -- always exits 0 regardless of outcome, so this step can never change
# the subagent-plan-review action's verdict (outputs.outcome, set entirely by review.sh) and does
# NOT depend on `continue-on-error` in composite steps (a documented GitHub grey area -- see
# action.yml). Its own failure path prints a distinct marker (never a bare `|| true`): the one
# time a transcript is actually needed is by definition a moment when something already went
# wrong, so a silent swallow here would lose the evidence quietly at the worst possible time.
#
# Contract (env, set by action.yml):
#   RUN_ID            github.run_id -- the S3 key's run-scoped prefix.
#   ARCHIVE_BUCKET     S3 bucket for the archive (default agent-platform-data-lake).
# cwd is the terraform root module directory (same working-directory as the review step) --
# composite steps do NOT inherit the previous step's working-directory, so action.yml sets this
# step's working-directory explicitly to the same value.
set -uo pipefail
set +e

RUN_ID="${RUN_ID:-unknown}"
BUCKET="${ARCHIVE_BUCKET:-agent-platform-data-lake}"
PREFIX="ci-rca-evidence/review-transcripts/${RUN_ID}"

_archive_marker() {
  local msg="[SUBAGENT-REVIEW] transcript archival FAILED: $1 (best-effort; review outcome unaffected)"
  echo "$msg" >&2
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n## Subagent review transcript archival failed\n\n%s\n' "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
}

if ! command -v aws &> /dev/null; then
  _archive_marker "aws CLI not found"
  exit 0
fi

archived=0
for f in review.json review_retry.json; do
  if [ -f "$f" ]; then
    if aws s3 cp "$f" "s3://${BUCKET}/${PREFIX}/${f}" --content-type application/json > /dev/null 2>&1; then
      archived=$((archived + 1))
    else
      _archive_marker "aws s3 cp failed for ${f}"
    fi
  fi
done

if [ "$archived" -eq 0 ]; then
  echo "[SUBAGENT-REVIEW] transcript archival: no review.json/review_retry.json found -- nothing to archive."
fi

exit 0
