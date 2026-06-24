#!/usr/bin/env bash
# Bounded transient-5xx retry wrapper for `claude -p`.
# Usage: claude_p_retry.sh <output_file> -- <claude args...>
#
# Retries up to MAX_ATTEMPTS=3 on transient Claude API errors.
# Never retries on substantive verdicts -- caller owns verdict semantics (Decision 55).
# Backoff: CLAUDE_P_RETRY_BACKOFF_BASE (default 4) * 2^attempt seconds.
# Parity with _TRANSIENT_CLAUDE_SIGNATURES in scripts/validate.py (Decision 73, Decision 92).
#
# Distinct from the terraform-registry retry loop (_TRANSIENT_INIT_SIGNATURES): Claude API
# transient signatures differ from registry 5xx patterns and are defined separately here.
set -euo pipefail

MAX_ATTEMPTS=3
BACKOFF_BASE="${CLAUDE_P_RETRY_BACKOFF_BASE:-4}"

if [ $# -lt 2 ]; then
    echo "Usage: claude_p_retry.sh <output_file> -- <claude args...>" >&2
    exit 1
fi

OUTPUT_FILE="$1"
shift

if [ "$1" != "--" ]; then
    echo "claude_p_retry.sh: expected '--' separator after output_file; got: $1" >&2
    exit 1
fi
shift

# Read stdin once; replayed on each attempt to support both piped-prompt and positional-arg callers.
STDIN_CONTENT=$(cat)

_is_transient() {
    local content="$1"
    if [[ "$content" == *"500"* ]] || \
       [[ "$content" == *"502"* ]] || \
       [[ "$content" == *"503"* ]] || \
       [[ "$content" == *"API Error: 5"* ]] || \
       [[ "$content" == *"Internal server error"* ]] || \
       [[ "$content" == *"overloaded"* ]]; then
        return 0
    fi
    return 1
}

LAST_EXIT=0
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    LAST_EXIT=0
    printf '%s' "$STDIN_CONTENT" | claude -p "$@" > "$OUTPUT_FILE" 2>&1 || LAST_EXIT=$?
    if [ "$LAST_EXIT" -eq 0 ]; then
        exit 0
    fi
    OUTPUT_CONTENT=$(cat "$OUTPUT_FILE")
    if _is_transient "$OUTPUT_CONTENT" && [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
        DELAY=$(( BACKOFF_BASE * (2 ** attempt) ))
        echo "claude_p_retry: transient error on attempt ${attempt}/${MAX_ATTEMPTS}; retrying in ${DELAY}s..." >&2
        sleep "$DELAY"
    else
        break
    fi
done

exit "$LAST_EXIT"
