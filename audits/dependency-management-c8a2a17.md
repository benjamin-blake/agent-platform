# Dependency management audit - c8a2a17

## Executive verdicts

| Question | Verdict | Basis |
|---|---|---|
| Q1 declaration completeness | **Partial** | Root Python declarations are clear, but Lambda list literals, workflow-local installs, native binaries, extensions, and ownership metadata are not one accountable inventory. |
| Q2 Dependabot visibility | **Incomplete** | Only root pip and repository-wide GitHub Actions entries exist; Terraform, pre-commit, Lambda-only lists, native inputs, and extensions lack an equal closed updater loop. |
| Q3 integrity and reproducibility | **Weak** | `requirements.lock` is subset-checked but not installed; Lambda ranges resolve afresh; native and extension bytes have no verified digest. |
| Q4 update lifecycle | **Orphan-prone** | Protected checks gate merge, but no mechanism disposes or escalates an ignored green dependency PR. No remote was available to execute the required five-PR sample. |
| Q5 automation policy | **Insufficient** | Grouping reduces noise, but there is no risk classifier, safe auto-merge eligibility, stale policy, or complete artifact-refresh closure. |
| Q6 industry comparison | **Lagging** | CI/protection and least privilege are sound; reproducibility, inventory, integrity, risk policy, and observability miss several checklist properties. External ratings are hypotheses because official browsing returned HTTP 401. |
| Q7 unasked questions | **Material gaps** | The lock is checked rather than consumed; mapping of lazy imports is manual; native ownership lacks provenance; Actions are mostly mutable tags; Terraform/pre-commit are uncovered; no SBOM/license/EOL policy exists; deployment triggers miss dependency inputs; and ownership does not survive 30 days of human absence. |

## Recommended automation policy

| Class | Target | Required gates and closure |
|---|---|---|
| Patch, dev/test, pre-commit | Auto-merge | GitHub-native auto-merge, immutable input, reproducible lock, required checks, supersession and stale escalation. |
| Minor, security | Queued auto-merge | Trusted Dependabot metadata, dependency review, protected CI, affected artifact build/smoke, forward-fix escalation. Security remains a distinct expedited lane. |
| Major, runtime, Actions, Terraform, Lambda-only, extensions | Human review | Code-owner/risk owner review, immutable references, full affected tests, governed deploy and smoke evidence. |
| Native binaries | Prohibited auto-merge | Verified digest/signature and provenance, explicit human approval, layer rebuild/deploy/smoke. |

GitHub-native auto-merge is preferable to direct workflow merge because it preserves branch protection without granting a custom merge identity broad write access. A merge queue is premature at current concurrency; scheduled maintenance is useful for review-only classes but is not lifecycle closure by itself. Renovate becomes attractive only if Dependabot plus generated manifests cannot cover nonstandard inputs. Manual review remains necessary for high-blast-radius changes, but must be paired with escalation.

## Strengths

- Root runtime, fast, and dev roles are explicitly separated, and a full transitive runtime lock exists.
- DuckDB uses a machine-readable version source and a lockstep validation path.
- Lambda manifests identify function consumers and explicitly document custom and managed layers.
- Pull requests targeting `main` run protected `pr-validate` and `terraform-validate` checks.
- Default workflow permissions are read-only and Actions cannot approve reviews.
- Governed Lambda channels use scoped deployment identities, deployment records, and post-deploy smoke gates.
- Dependabot groups minor/patch root updates and caps open PR volume.

## Surviving findings

1. **DEPEND-01 - High: native and extension byte integrity.** The layer builder accepts pgclient objects from S3 and DuckDB extensions from S3/CDN without checking a committed digest or signature. HTTPS, private storage, deterministic ZIPs, and smoke tests do not authenticate provenance. Add a machine-readable digest inventory and fail before packaging on any mismatch.
2. **DEPEND-02 - High: the transitive Python lock is not consumed.** The sync check proves only that each root name appears as an exact pin. CI and builds install range manifests, so reviewed, tested, and later deployed resolution can differ. Generate and consume platform-appropriate hashed locks and compare regenerated content.
3. **DEPEND-03 - Medium: updater coverage is incomplete.** `rec-2864` adequately owns moving `DUCKLAKE_DEPS` into a watched manifest, but not Terraform roots, pre-commit hooks, workflow install inputs, `PROD_DEPS`, native tools, extensions, or managed layers. Add a generated authority-to-updater coverage gate.
4. **DEPEND-04 - Medium: dependency PRs lack deterministic disposition.** Required checks prevent unsafe merges, but a green update ignored for 30 days remains open. Add metadata-driven eligibility, native auto-merge for low risk, human review for high risk, and noise-bounded stale/supersession escalation.
5. **DEPEND-05 - Medium: merge-to-deployment closure is incomplete.** Lambda deployment filters omit several dependency authorities, and DuckLake function deployment explicitly does not publish and attach dependency layers. Derive affected artifacts and triggers from the authoritative inventory.
6. **DEPEND-06 - Medium: no complete inventory/SBOM policy.** Existing checks cover import contracts, package existence, and lock presence, not consumer/owner, vulnerability, license, EOL, provenance, and exposure age. Generate one multi-ecosystem inventory with expiring exceptions.
7. **DEPEND-07 - Low: mutable Action tags.** Most third-party `uses:` references use major tags, while a few monitoring workflows demonstrate immutable SHA pins. Enforce SHA pins with readable version comments and automated updates.

Seven findings is intentional: candidates with nearby but non-property-matched controls were consolidated rather than padded.

## 90-day target sequence

1. **Days 0-30:** Land DEPEND-01 and DEPEND-07 integrity gates. Specify production/dev/Lambda resolution closures and implement DEPEND-02 lock consumption.
2. **Days 31-60:** Implement `rec-2864` and DEPEND-03's complete authority/updater map. Generate DEPEND-06 inventory fields and measure update age, remediation latency, recurring failures, and EOL exposure; set SLOs only after this baseline.
3. **Days 61-90:** Implement DEPEND-05 affected-artifact deployment closure, then DEPEND-04 risk-classified GitHub-native auto-merge and stale/supersession policy. Rehearse tampered bytes, stale green PR, failed update, and dependency-only Lambda bump counterfactuals.

## Rejected intuitions and compensating controls

The fast PR tier's omission of heavyweight runtime wheels is deliberate and partly compensated by full main validation; it is not itself a defect. `strict=false` does not remove required status checks. Empty Lambda `pip_packages` lists are often intentional because custom or managed layers own the closure. Read-only workflow permissions should remain: increasing privileges is not a remedy for missing lifecycle design. Root grouped updates and the five-PR cap control noise, but do not dispose stale PRs. The DuckDB version SSOT prevents version drift, but it does not verify downloaded extension bytes or synchronize every Lambda dependency.

## Degraded-mode notes and external sources

The repository had no `origin` remote and no `origin/main`; the audit therefore used local `HEAD` `c8a2a17`, and remote-freshness and PR-frequency claims are hypotheses. Preflight refreshed 1,706 recommendation rows on 2026-07-26 with `recs_read_status=ok`. GitHub web research returned HTTP 401, so official-product comparisons are hypotheses and the audit does not award `leading`. Intended official references, accessed unsuccessfully on 2026-07-26: [Dependabot configuration options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference), [supported ecosystems](https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories), [automatic dependency updates](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/automating-dependabot-with-github-actions), [auto-merge](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests), and [dependency review](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-dependency-review).
