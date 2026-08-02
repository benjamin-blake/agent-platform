#!/usr/bin/env bash
# Body of the subagent-plan-review composite action, extracted from action.yml (rec-2924) so the
# logic is shellcheckable and directly testable. tests/test_subagent_review_wiring.py drives this
# file under the EXACT invocation GitHub uses for a composite `shell: bash` step --
# `bash --noprofile --norc -e -o pipefail <file>` -- because the inherited -e is the whole bug.
#
# Contract with action.yml (all supplied via the step's env: block):
#   CLAUDE_CODE_OAUTH_TOKEN  caller-passed secret (composite actions cannot read secrets.* directly)
#   CONTEXT_DESCRIPTION      plan-under-review context phrase, interpolated into the reviewer prompt
#   WORKSPACE_ROOT           ${{ github.workspace }} -- repo root for scripts/ lookups
#   GITHUB_OUTPUT            step-output file (GitHub-provided)
# cwd is the terraform root module directory containing plan.json (step `working-directory`).
#
# Emits exactly one outcome=proceed|revise|starved, preserving the STARVED-no-latch anti-masking
# (Decision 55) -- never an implicit PROCEED or REVISE on starvation.

set -uo pipefail

# GitHub runs composite `shell: bash` step bodies as
#     bash --noprofile --norc -e -o pipefail {0}
# so errexit is INHERITED here, and the `set -uo pipefail` above does NOT clear it -- `set` only
# touches the options it names. This script is DESIGNED for a no-errexit world: every failure path
# below writes an explicit outcome and exits deliberately, and scripts/ci/review_verdict.py exits
# 0/2/1 BY CONTRACT for PROCEED/REVISE/STARVED (see its main() docstring; proven by
# tests/test_review_verdict.py). Under inherited -e the `VERDICT=$(... review_verdict.py ...)`
# assignment aborts the shell the instant the classifier reports REVISE or STARVED, so the
# same-budget retry and the outcome-writing case block below become dead code, the caller reads an
# EMPTY outputs.outcome, misses its `== 'starved'` anti-masking carve-out, and latches a FALSE RED
# convergence record for a run in which terraform apply never executed (rec-2924). Clear it.
set +e

# The output channel is TOTAL by construction: the fail-closed anti-masking value is written FIRST,
# so an outcome is defined on EVERY exit path -- including an unexpected abort that never reaches
# the case block below. GITHUB_OUTPUT is last-write-wins, so each deliberate write further down
# overrides this pre-write. The property whose absence produced the false red is "an outcome is
# defined on every exit path"; it is encoded structurally here rather than left to control flow
# reaching the right branch.
echo "outcome=starved" >> "$GITHUB_OUTPUT"

# Decision 155 marker shape (mirrors the DCG-03 orphan-guard skip marker): distinct, greppable,
# and mirrored to $GITHUB_STEP_SUMMARY when set, so an accumulating STARVED rate is
# operator-observable rather than buried in a per-run job log. Never changes the outcome or exit
# status this script has already decided -- pure observability.
_starved_marker() {
  local reason="$1"
  local msg="[SUBAGENT-REVIEW] STARVED: ${reason}"
  echo "$msg" >&2
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '\n## Subagent review STARVED\n\n%s\n' "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
}

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN}" ]; then
  _starved_marker "no CLAUDE_CODE_OAUTH_TOKEN available; failing closed before any reviewer invocation."
  echo "outcome=starved" >> "$GITHUB_OUTPUT"
  exit 1
fi
if ! command -v claude &> /dev/null; then
  sudo npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional && sudo npm cache clean --force
fi

if ! python3 "${WORKSPACE_ROOT}/scripts/terraform_apply_guard.py" --digest plan.json > plan_digest.txt; then
  _starved_marker "guard digest build failed (infra failure, not a plan rejection)."
  echo "outcome=starved" >> "$GITHUB_OUTPUT"
  exit 1
fi

MAX_TURNS=5
PROMPT="Review the terraform plan digest below for ${CONTEXT_DESCRIPTION}. It has already passed the deterministic guard (no destroy, no out-of-budget IAM/trust change; may include in-budget IAM inline-policy or attachment UPDATEs on managed boundary-carrying CI roles per T2.25). The full plan is at plan.json (Read tool) if you genuinely need more detail than the digest provides. Confirm the plan is a safe, expected sandbox infrastructure change. Reply with exactly the single token PROCEED on its own line if safe to auto-apply, or REVISE followed by the reason if not."

cat plan_digest.txt | "${WORKSPACE_ROOT}/scripts/ci/claude_p_retry.sh" review.json -- \
  --output-format json --allowedTools "Read" --max-turns "$MAX_TURNS" "$PROMPT" || true
VERDICT=$(python3 "${WORKSPACE_ROOT}/scripts/ci/review_verdict.py" review.json)

if [ "$VERDICT" = "STARVED" ]; then
  echo "Reviewer STARVED on first attempt; retrying once at the SAME turn budget (${MAX_TURNS} -- never larger, T2.39 c2)." >&2
  cat plan_digest.txt | "${WORKSPACE_ROOT}/scripts/ci/claude_p_retry.sh" review_retry.json -- \
    --output-format json --allowedTools "Read" --max-turns "$MAX_TURNS" "$PROMPT" || true
  VERDICT=$(python3 "${WORKSPACE_ROOT}/scripts/ci/review_verdict.py" review_retry.json)
fi

echo "Reviewer verdict: ${VERDICT}"
case "$VERDICT" in
  PROCEED)
    echo "outcome=proceed" >> "$GITHUB_OUTPUT"
    exit 0
    ;;
  REVISE)
    echo "Subagent returned REVISE; failing closed." >&2
    echo "outcome=revise" >> "$GITHUB_OUTPUT"
    exit 1
    ;;
  *)
    echo "Subagent STARVED (max-turns/no-verdict/API-exhausted) after the same-budget retry; blocking apply WITHOUT latching the convergence record red." >&2
    _starved_marker "max-turns/no-verdict/API-exhausted after the same-budget retry (T2.39 c2); apply blocked, convergence record NOT overwritten (Decision 55 anti-masking)."
    echo "outcome=starved" >> "$GITHUB_OUTPUT"
    exit 1
    ;;
esac
