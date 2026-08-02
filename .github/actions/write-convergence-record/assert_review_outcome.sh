#!/usr/bin/env bash
# Strict consumer for the review-outcome / review-step-outcome pair (rec-2923; Decision 162 R1
# instance). Enforces the two-sided contract BEFORE write-convergence-record/action.yml performs
# any S3 write: an undefined or unrecognised review outcome must fail loudly, never fall through
# to the green/red write as if it were a routine "review did not starve" case.
#
# rec-2923 had TWO independent failures: the producer (review.sh) died silently under inherited
# errexit AND this consumer accepted the resulting empty outcome as if it meant "not starved,
# proceed to the write". A strict consumer ranks above every producer-side control -- a consumer
# that switch-cases on a value and treats "anything unrecognised, including empty" as a legitimate
# branch is a latent bug regardless of how the producer fails.
#
# Contract, driven from two env vars set by the caller (action.yml):
#   REVIEW_STEP_OUTCOME  the calling job's `steps.review.outcome` (GitHub's own per-step
#                        conclusion) -- "" when the caller passes no review-step-outcome input
#                        (the guard-routed and gated-apply call sites, which run no review step).
#   REVIEW_OUTCOME       the calling job's review verdict output (proceed|revise|starved|"").
#
# When REVIEW_STEP_OUTCOME is "success" or "failure" (the review step RAN), REVIEW_OUTCOME must be
# exactly one of proceed|revise|starved -- empty or unrecognised is a contract violation (the
# rec-2923 shape: the reviewer step ran, but its outcome output was never populated).
#
# Otherwise (REVIEW_STEP_OUTCOME is "skipped", "cancelled", or absent/"" -- no review step ran at
# all) REVIEW_OUTCOME must be EMPTY; a non-empty value there is equally a contract violation (a
# review verdict with no review step to have produced it).
#
# Deliberately does NOT rely on inherited errexit -- clears it explicitly and encodes every branch
# with its own exit, since inherited-errexit dependence on a silently-non-running control path is
# the defect class this script exists to close (see review.sh's header for the sibling incident
# this script is the downstream fix for).
set -uo pipefail
set +e

REVIEW_STEP_OUTCOME="${REVIEW_STEP_OUTCOME:-}"
REVIEW_OUTCOME="${REVIEW_OUTCOME:-}"

case "$REVIEW_STEP_OUTCOME" in
  success | failure)
    case "$REVIEW_OUTCOME" in
      proceed | revise | starved)
        exit 0
        ;;
      *)
        echo "::error::assert_review_outcome: review step ran (REVIEW_STEP_OUTCOME='${REVIEW_STEP_OUTCOME}') but REVIEW_OUTCOME='${REVIEW_OUTCOME}' is not one of proceed|revise|starved -- refusing to write the convergence record (Decision 162 R1; the rec-2923 shape)." >&2
        exit 1
        ;;
    esac
    ;;
  *)
    if [ -n "$REVIEW_OUTCOME" ]; then
      echo "::error::assert_review_outcome: no review step ran (REVIEW_STEP_OUTCOME='${REVIEW_STEP_OUTCOME}') but REVIEW_OUTCOME='${REVIEW_OUTCOME}' is non-empty -- refusing to write the convergence record (Decision 162 R1)." >&2
      exit 1
    fi
    exit 0
    ;;
esac
