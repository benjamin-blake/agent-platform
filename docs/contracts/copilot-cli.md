# Boundary Contract: GitHub Copilot CLI

## Tool
GitHub Copilot CLI (`gh copilot suggest`, `copilot`)

## Input Semantics

| Argument | Semantics | Correct Use |
|----------|-----------|-------------|
| `-p "instruction"` | User message: the model treats this as an instruction to act on | Always include a plain instruction string |
| `@filepath` | Document context: the model sees the file content but does not treat it as an instruction | Use for supplementary context only |

## What We Send
A short instruction string as the `-p` argument, with file content injected via `@filepath` as supplementary context. Example:
```bash
copilot -p "Generate a step-by-step plan for the attached spec. Do not write any code." @spec.txt
```

## Why This Delivery Mechanism Is Correct
Agentic models receiving only `@filepath` context ask "what should I do with this?" and implement the spec instead of reasoning about it. The instruction verb (`-p "..."`) tells the model what to do with the context; the file provides the content to operate on.

## What Would Go Wrong If Semantics Differ
If only `-p @filepath` is passed (no instruction string), agentic models in planning or critique contexts will begin *implementing* the spec instead of reviewing it. This is the root cause of planning-phase agentic loops (see rec-119).

## Date Last Verified
2026-04-08

## Related Gotcha
See "Copilot CLI @file vs user message" in `.github/copilot-instructions.md`.

## Verified
This contract reflects the behavior documented in the [GitHub Copilot CLI docs](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line) and observed during rec-119 investigation.
