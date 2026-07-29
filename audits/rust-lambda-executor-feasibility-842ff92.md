# Rust Lambda and Executor Feasibility Audit

## Q6 - adopt-with-caveats

Adopt Rust for one governed, reversible **regular Lambda** pilot: the new T4.1 `critique_gate`. Do not make Rust the executor default, port existing Python, or use Rust for T4.2 Lambda Durable Function personas today. Step Functions remains managed orchestration and is not being rewritten.

This corrects an overly conservative first recommendation. Rust is worth testing in the AWS machinery precisely because its compiler can give coding agents immediate, structured feedback and its native binary can reduce regular-Lambda initialization and memory. The evidence supports a bounded experiment, not a platform mandate.

## Why not the AI-calling Lambdas?

The cold-start premise combines two different products:

1. **Regular Lambda:** AWS supports Rust through the Rust runtime client on an OS-only runtime. A small native binary can reduce runtime initialization, package overhead, duration, and memory, but it does not eliminate creation of new execution environments or all initialization.
2. **Lambda Durable Functions:** T4.2's LLM-calling personas require AWS checkpoint/replay and suppression of completed tool/LLM operations. AWS currently lists Node.js, Python, Java, and C# Durable runtimes and no official Rust Durable SDK. A Rust custom runtime or container does not supply those semantics. Model/network latency also remains after initialization.

Therefore Rust cannot presently remove cold starts from the T4.2 AI-call path without replacing a supported durability layer with bespoke high-risk machinery. The proposed `critique_gate` does not call an AI API; it tests Rust where AWS support is first-class without conflating regular and Durable Lambda (RLE-01).

## Why `critique_gate`?

T4.1's `critique_gate` aggregates structured critic verdicts and returns a deterministic route. It has no LLM transport, repository checkout, GitHub credential, or DuckDB/native-layer dependency. A fixed Python sibling can serve as a behavioral reference, and Step Functions can invoke an alias-qualified weighted canary with immediate rollback. Success cannot automatically expand Rust to another worker.

The pilot must exercise the packaged Lambda boundary and fail closed for malformed, missing, duplicated, contradictory, reordered, and forward-versioned verdicts. This tests whether Rust's exhaustive enums, `Result` handling, ownership, and type-state diagnostics improve agent attempts-to-green and escaped-defect rates rather than merely proving that a stub compiles (RLE-02/RLE-03).

## Direct answers Q1-Q5

- **Q1 - transformational** for Rust-everywhere because T4.2 lacks first-class Rust Durable support. The one-worker pilot is only an S-to-M incremental experiment.
- **Q2 - mixed.** Compiler feedback and native regular-Lambda characteristics are credible positives. IAM, cloud behavior, schemas, replay placement, idempotency, and business behavior still require tests and runtime controls.
- **Q3 - material-overhead.** The pilot needs a versioned language-neutral manifest and affected-artifact logic; pinned Rust/Cargo; reproducible build and dependency/SBOM checks; Terraform runtime/architecture support; packaged behavioral coverage; governed CD, deploy records, smoke, symbolized logs, and rollback. These are charged to the pilot.
- **Q4 - none.** Refactor no existing Python before MVP. This is a new-function experiment, not a migration.
- **Q5 - bounded-dual-language.** Rust is limited to `critique_gate`; T4.2 remains Python; other T4.x workers require a later evidence-based exception.

## Production entry, graduation, and sunset

Before any Rust production traffic, the T4.1 plan must pre-register:

- a fixed Python reference and matched or seeded contract-change tasks for AI attempts-to-green, compiler/lint catches, and escaped behavioral defects;
- numeric materiality thresholds, minimum sample count, observation window, and time box;
- controlled cold/warm cohorts reporting Lambda `Init Duration`, duration, memory, artifact size and GB-seconds **plus** end-to-end Step Functions latency and dollars per completed recommendation;
- one production architecture, a reproducible artifact, packaged bootstrap smoke, a named Rust/CVE owner, and the existing governed code-deploy channel extended before deployment;
- an alias-qualified weighted canary, retained contract-compatible Python version, alarms, and a performed rollback drill.

The pilot may not delay the Python T4.1/T4.2 critical path. Missing, inconclusive, or failed gates default to Python. Sunset means traffic rollback **and removal** of Rust-only manifest, CI, Terraform, and dependency-maintenance surfaces unless another independently approved Rust artifact uses them. Graduation permits only an architecture-owner review of the next measured deterministic candidate; it never authorizes Rust Durable personas by analogy.

## Unresolved evidence and adversarial-review effect

The repository still lacks comparative invocation, duration, memory, cost, agent-repair, and escaped-defect data. `critique_gate` may be too small for natural observations, so matched or seeded tasks are required; percentage Lambda savings may still be immaterial after Step Functions and engineering cost.

Round 1 rejected a Rust default but preserved a post-MVP experiment. User feedback exposed that this sequencing underweighted compiler feedback for coding agents and a new, isolated regular worker. A second fresh-context round with compiler-safety, Rust-performance, and delivery-operations perspectives accepted the bounded pilot only after adding the Python counterfactual, fail-closed cases, full delivery-path scope, one deployed architecture, weighted alias rollback, pre-registered thresholds, non-blocking time box, ownership, and removal-on-sunset. Those caveats are why the verdict is `adopt-with-caveats`, not `fully-adopt-rust`.
