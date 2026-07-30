# Rust Lambda and Executor Feasibility Audit

## Q6 - do-not-adopt-rust

Do not adopt Rust as the governed implementation default for the CD.27 executor now. This is an MVP decision, not a permanent ban: use Python for T4.1 deterministic glue, T4.2 Durable personas, and the later Lambda-bearing T4.3, T4.8, T4.9a, and T4.12 work until measured evidence justifies a whole-artifact exception. Step Functions remains managed orchestration and is not a language migration target.

## Decisive evidence

AWS supports ordinary Rust Lambda binaries through the Rust runtime client on an OS-only runtime, but that does not transfer to Lambda Durable Functions. Current AWS documentation lists Node.js, Python, Java, and C# managed Durable runtimes. Container images still require a Durable Execution SDK, and AWS lists no Rust SDK. T4.2 requires forced-timeout checkpoint/replay without repeating completed LLM or tool calls, so a bespoke Rust compatibility layer would own the most failure-sensitive executor property (RLE-01).

The repository has no Rust sources, Cargo metadata, or pinned toolchain. Its manifest schema names `.py` handlers and `pip_packages`; coverage mapping and both governed deploy workflows are Python-specific. A Rust production path therefore requires a versioned language-neutral manifest plus cross-build, provenance, vulnerability, coverage, deployment-record, and behavioral-smoke integration, not merely compilation (RLE-02).

No sampled repository evidence quantifies a Rust advantage. There are no comparative cold/warm latency, duration, memory, package, GB-second, build-time, or language-attributable defect measurements. The bounded recent recommendation sample was dominated by IAM, authority-source, HTTP/service, documentation, and CI-budget issues. Rust types can prevent some local invalid states, ownership errors, and concurrency mistakes, but cannot prove IAM, external schemas, replay determinism, idempotent side effects, callback correlation, or cloud behavior (RLE-03).

## Direct answers Q1-Q5

- **Q1 - transformational.** Direct Lambda runtime work appears in T4.1, T4.2, T4.3, T4.8, T4.9a, and T4.12. T4.9, T4.10, and T4.11 affect contracts, workflows, or managed Step Functions state but do not directly create or modify worker runtime code. The hypothesis midpoint is 104 engineer-days across non-overlapping runtime, Durable compatibility, delivery, and verification outputs. The exact estimate is deliberately low-confidence; the mandatory Durable incompatibility independently makes Rust-default work transformational because it requires a bespoke support layer or reversal of CD.27.
- **Q2 - mixed.** Rust provides meaningful local compiler and native-runtime strengths for regular Lambda, but repository-specific runtime savings and defect reduction are unmeasured. Durable support, native dependency parity, delivery velocity, incident response, and dual supply-chain ownership weigh against adoption now.
- **Q3 - material-overhead.** A single versioned manifest can contain rather than duplicate policy, but two toolchains and artifact formats remain. Rust gates must include behavioral contracts that fail when feature code is deleted or replaced by a compile-only stub. Parallel CI can limit wall-clock impact; its actual effect is unmeasured.
- **Q4 - none.** Migrate no existing Python before MVP. Measure DuckLake workers first, preserve the current executor as frozen replacement context, and prefer retirement over porting for ops-compaction or scheduled/findings surfaces where roadmap disposition removes the artifact.
- **Q5 - python-only-until-post-mvp.** Use Python for T4.1 and T4.2 and for later Lambda-bearing T4.x changes during MVP. The architecture owner may approve a later whole-artifact Rust pilot after the delivery contract is language-neutral and a representative worker crosses a predeclared threshold. This does not prohibit a non-production experiment outside the MVP critical path.

## Pre-MVP recommendation

Implement CD.27 in the language with first-class Durable support and the repository's governed delivery path. Preserve language-neutral JSON/schema boundaries at Step Functions, callback, and persona contracts so later replacement is reversible. Do not port the five DuckLake functions, three prod-class functions, or current executor merely to create uniformity.

## Reopen conditions

Reopen the decision when all three conditions hold:

1. AWS offers a first-class Rust Durable SDK/runtime that passes a forced-timeout, completed-operation suppression, in-flight version, local-test, and observability proof - or the required T4.2 semantics are deliberately redesigned.
2. A contract-identical ordinary Lambda comparison reports cold/warm p50/p99, peak memory, artifact size, billed GB-seconds, build minutes, operator time, and defect-class catches, and clears a predeclared total-cost threshold.
3. A versioned language-neutral manifest supports target architecture, entrypoint, dependency lock, reproducible build, SBOM/advisory response, coverage, deploy records, smoke evidence, alias canary, symbolized incident diagnosis, and whole-artifact rollback.

The cheapest experiment is one low-side-effect T4.1 deterministic worker after its contract stabilizes. Compare Python and Rust behind alias rollback; do not use a sidecar or mixed-language shared library, and do not infer Durable support from ordinary Lambda results.

## Unresolved evidence

The cost ranges lack historical Rust delivery calibration; invocation and duration data are absent; the recent defect sample is too small for population-level prevention rates; two named expected test anchors were absent; and current eu-west-2 Durable capability should be re-probed during T4.2 planning. These uncertainties favor measure-first rather than either language mythology or a permanent prohibition.

## Adversarial-review effect

One stable round completed three fresh-context perspectives. The compiler skeptic narrowed claims about schema and idempotency, the performance advocate preserved ordinary-Lambda optimization optionality, and the delivery reviewer expanded incident, supply-chain, and rollback consequences. Accepted challenges changed wording and uncertainty, not Q1-Q6 verdicts; estimate precision and representative defect evidence remain explicitly deferred. The YAML contains every challenge and reconciliation.
