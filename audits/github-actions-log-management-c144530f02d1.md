# GitHub Actions Log Management Audit

## Direct answers

- **Q1 - Partial.** The repository provides native annotations, step summaries, typed artifacts, stable diagnostic codes, and JUnit-first RCA evidence. CI-RCA can nevertheless widen from `--log-failed` to an uncapped whole-run log, so bounded machine retrieval is not guaranteed.
- **Q2 - Partial.** Apply, reconcile, deployment, and convergence paths often fail closed with actionable diagnostics. This strength is not governed consistently across every agent-consumed path, and the unbounded fallback weakens economical progressive disclosure.
- **Q3 - Complete statically, runtime-degraded.** All 19 workflows and seven composite actions have a reachable trigger/caller and a current purpose or conservative retained-state rationale. No retirement candidate meets the required four-negative trace. Recent execution could not be verified because this harness has no `gh` CLI.
- **Q4 - Partial; adopt a risk-based convention.** Case variation is harmless. The material gap is that governed or agent-consumed failures are not required to expose an explicit job/step identity, stable diagnostic code, and bounded decisive surface. Full cosmetic uniformity is unwarranted.
- **Q5 - Partial.** The design is strong on anti-false-green controls, native annotations, machine-readable artifacts, confidential-data handling, and local reproducibility. It misses bounded raw-log discipline and a coherent evidence-retention policy.
- **Q6.** Diagnostic surfaces are only partly a stable agent API; truncation may bias diagnosis; artifact expiry may prevent delayed RCA/dedup; fork diagnostics are designed to degrade safely but were not observed; cancellation states lack a shared envelope; log growth has no measurable ingestion budget; and one authority citation is stale.

## Highest-leverage findings

1. **GAL-01 (high): Bound CI-RCA fallback retrieval.** Preserve the failed-job/step identity, cap returned bytes or lines, emit an explicit truncation envelope, and retain a link or artifact for raw recovery. This directly reduces agent ingestion cost without hiding evidence.
2. **GAL-02 (medium): Enforce a risk-based diagnostic contract.** Apply it only to governed and agent-consumed paths. Require stable identifiers and at least one bounded decisive surface; do not mandate cosmetic naming uniformity.
3. **GAL-04 (medium): Govern evidence retention by purpose.** Map ephemeral handoffs, ordinary CI evidence, governed deployment evidence, and security evidence to explicit retention classes.
4. **GAL-03 (low): Correct the CI-RCA Decision 143 citation.** The runtime guard remains fail-closed, but its claimed authority is unrelated.

## Strengths

The best paths demonstrate layered diagnostics: concise native annotations, summaries for degraded/no-op states, downloadable JUnit and selection artifacts, content-addressed plan handoffs, and explicit false-green guards after best-effort credential steps. Composite actions consolidate high-risk logic and all seven have direct callers plus manifest validation. CI-RCA correctly distinguishes fetch stderr from retrieved log content and fails loudly on empty evidence.

## Lifecycle exceptions

`tf-gated-apply-prototype.yml` and `terraform-provider-mirror-seed.yml` are conservatively **retained**, not called orphaned: manual-only execution and low frequency are insufficient removal evidence. `reconcile.yml` is an active manual recovery channel. Runtime evidence for every workflow is a declared gap, not negative lifecycle evidence.

## Sequencing

Implement GAL-01 first. Define GAL-02's risk set next and align its evidence envelope with GAL-01. Then establish GAL-04 retention classes so bounded summaries and raw recovery evidence expire deliberately. GAL-03 is independent and safe to correct at any time. The human should disposition findings; this audit makes no workflow changes.
