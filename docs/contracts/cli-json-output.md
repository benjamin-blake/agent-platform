# Contract: Copilot CLI JSON Output Schema

**DEPRECATED** -- replaced by Bedrock converse() API response parsing in `scripts/bedrock_client.py`. Retained for reference. See Decision 52.

**Version**: 1.0
**Source**: `--output-format=json` flag (GitHub Copilot CLI)
**Parser**: `scripts/copilot_wrapper.parse_jsonl_output()`
**Reference**: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference

---

## Overview

When invoked with `--output-format=json`, the Copilot CLI writes one JSON object
per line (JSONL format) to stdout, instead of human-readable text.  Each line
is a self-contained event object.  The schema was derived empirically from live
CLI invocations in this repository (planning session tests, April 2026).

---

## Event Types

### `session.*`

Session lifecycle events.  Not currently used by `parse_jsonl_output()`.

```json
{"type": "session.start", "sessionId": "..."}
{"type": "session.end",   "sessionId": "..."}
```

---

### `user.message`

The user's input prompt (echoed back).  Not currently used by
`parse_jsonl_output()`.

```json
{"type": "user.message", "data": {"content": "<prompt text>"}}
```

---

### `assistant.turn_start` / `assistant.turn_end`

Marks the boundary of a complete assistant turn.  Not used directly; content
is extracted from `assistant.message` events.

```json
{"type": "assistant.turn_start"}
{"type": "assistant.turn_end"}
```

---

### `assistant.message`

**Primary content event.**  One or more `assistant.message` events carry the
model's text response.  In streaming mode, a single turn may emit multiple
chunks; each chunk has its own `assistant.message` event.

```json
{
  "type": "assistant.message",
  "data": {
    "content":      "<text chunk>",
    "messageId":    "<uuid>",
    "outputTokens": 42,
    "toolRequests": []
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `data.content` | string | Text content of this chunk. Concatenate all chunks to reconstruct the full response. |
| `data.messageId` | string | Unique identifier for this message. |
| `data.outputTokens` | int | Output tokens consumed by this chunk. |
| `data.toolRequests` | array | Tool calls requested by the model (empty for text-only turns). |

**Extraction guidance**: join all `data.content` values from all
`assistant.message` events to reconstruct the model's full response text.

---

### `tool.execution_start` / `tool.execution_complete`

Tool call lifecycle events.  Not used by `parse_jsonl_output()`; included here
for completeness.

```json
{"type": "tool.execution_start",    "tool": "<name>", "callId": "<id>"}
{"type": "tool.execution_complete", "tool": "<name>", "callId": "<id>", "exitCode": 0}
```

---

### `result`

**Session metadata event.**  Always the last line of a successful JSON output
stream.  Contains billing usage and the session exit code.

```json
{
  "type":      "result",
  "sessionId": "<uuid>",
  "exitCode":  0,
  "usage": {
    "premiumRequests":    2.0,
    "totalApiDurationMs": 1234
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `sessionId` | string | CLI session UUID.  Used for `--resume` in subsequent calls. |
| `exitCode` | int | CLI exit code (0 = success). |
| `usage.premiumRequests` | float | Premium request units consumed.  This is the authoritative billing metric for GitHub Copilot — use instead of the `requests_for_model()` heuristic. |
| `usage.totalApiDurationMs` | int | Total API duration in milliseconds. |

---

## Parser Contract (`parse_jsonl_output`)

`scripts/copilot_wrapper.parse_jsonl_output(raw: str) -> dict`

**Input**: Raw stdout string from a `--output-format=json` CLI invocation.

**Output**:

```python
{
    "content":          str,    # Concatenated text from all assistant.message events
    "session_id":       str,    # From result.sessionId (empty string if absent)
    "exit_code":        int,    # From result.exitCode (0 if absent)
    "premium_requests": float,  # From result.usage.premiumRequests (0.0 if absent)
}
```

**Error behaviour**: Raises `CopilotResponseError` if any non-empty line fails
`json.loads()`.  Empty lines are silently skipped.

**No fallback**: The parser has no text-mode fallback.  If JSON parsing fails
the error is surfaced immediately so the root cause is fixed rather than masked.

---

## Usage Example

```python
from scripts.copilot_wrapper import copilot_call, parse_jsonl_output

# JSON output is the default; no extra arguments required
result = copilot_call("Write a docstring for this function.")
# result.stdout  -> extracted text content
# result.premium_requests -> billing units from result event
```

---

## Known Gotchas

- `data.content` may be an empty string in intermediate tool-calling turns.
  Filter these out with `filter(None, content_parts)` before joining.
- `result.exitCode` in the JSON payload is the CLI's logical exit code, which
  may differ from the subprocess return code in error edge cases.  Always check
  the subprocess return code first; use the JSON exit code only for logging.
- `usage.premiumRequests` is a float, not an integer.  Some models return
  fractional values (e.g. `0.5`).
