# Intent: Two-Tier Validation Architecture

This document is the architectural anchor for the migration of `scripts/validate.py` from a four-flag world (`--quick`, `--scope`, `--ci`, `--integration`, plus `--verifiers` and `--coverage` advisories) to a two-tier model: presubmit (the default, comprehensive) and edit-loop (`--pre`, the fast inner loop).

It complements `docs/INTENT-verification-system.md`, which defines the three-layer programmatic verification system. This document operates at Layer 1 of that pyramid -- the surface every workflow calls -- and specifies the bounded execution and substrate that make the two-tier model coherent for autonomous agents.

**Status:** Architectural anchor. This document records intent and constraints; the flag refactor and substrate stand-up are sequenced as separate STRATEGIC plans referenced by recommendations filed alongside this doc.

**Builds on:** Decision 48 (Verification Tier Design), Decision 51 (Local-First Outbox + Bidirectional Sync), Decision 55 (RCA-First Executor -- no rescue agents), Decision 57 (Interactive vs Autonomous SSO recovery), and `docs/INTENT-verification-system.md`.

---

## Motivation

The current `validate.py` exposes five execution surfaces -- `--scope auto|all|python|terraform|docs|prompts`, `--integration`, `--ci`, `--quick`, `--verifiers` -- plus a new `--coverage` advisory. Each was added in response to a real local need (fast lint, full sweep, integration mode, CI parity). The aggregate is now strictly worse than its parts:

1. **Agents pick the wrong flag.** Autonomous executors and human/agent implementations have routed through `--quick` (lint only) when they should have run integration checks, and through `--scope all` when `--quick` would have done. Each mismatch wastes minutes and produces a deceptive PASS. (Historical context; resolved by this migration.)

2. **The flags carry no enforcement of bounded execution.** A `--ci` invocation may run for 10+ minutes if Terraform plan or pip-audit hangs. Autonomous agents cannot reason about wall-clock budgets when the surface they call has no commitment to one.

3. **The flag set evolved organically; the boundary between "fast inner loop" and "everything before merge" is implicit.** A new contributor (human or agent) reading `--help` cannot derive the intended call site for each flag.

4. **CI workflow drift.** GitHub Actions calls `validate.py --ci`. The local equivalent is `--scope all` plus optional `--integration`. The two diverge silently when authors add a check to one path and not the other -- exactly the failure mode `validate.py` was created to prevent.

The motivation for two-tier is **agent-first**: autonomous and supervised agents need crisp tier boundaries with explicit time budgets so they can decide *whether to run* the gate rather than *which flag to choose*. Human ergonomics improve as a side-effect.

---

## Two-Tier Model

The end state collapses the surface into exactly two flags:

| Tier | Flag | When to call | What runs | Time budget |
|------|------|--------------|-----------|-------------|
| Presubmit | (default, no flag) | Before merge. Once per branch, by CI or by the developer prior to PR submission. | Lint, format, all unit tests, terraform validate, dependency health, prompt validation, V3 verifiers (when AWS available), DQ runner auto-invoke if stale. | <= 5 minutes total. |
| Edit-loop | `--pre` | Per-step during implementation. Inside the inner author/agent loop. | Lint, format, prompt validation. Nothing that hits AWS, nothing that runs pytest. | <= 30 seconds. |

**Default is presubmit, not edit-loop.** Calling `python -m scripts.validate` with no flags runs the comprehensive gate. This inverts the current scope-auto behaviour, which infers from changed files -- inference is exactly the source of agent confusion.

`--scope`, `--ci`, `--integration`, and `--verifiers` are deleted. `--coverage` is retained as an advisory (it does not gate; it surfaces verifier coverage gaps for humans and the planning skill).

### Behaviour of the default (presubmit) tier

- Runs the full python check suite, terraform checks (when terraform is in PATH), dependency health, and prompt validation unconditionally.
- Invokes the V3 verification harness when AWS credentials are available; when they are not, the harness is skipped with a `verification_skipped` event (Decision 57). Skip is not failure.
- Auto-invokes the data quality runner when `logs/debug/dq-latest.json` is missing or older than the freshness window. Decision 57 governs SSO-unavailable cases: skip with actionable guidance, do not crash.
- Hard-fails on any check whose failure would block merge. Advisory checks (coverage, complexity warnings) print but do not contribute to the failure list.

### Behaviour of the edit-loop tier

- Lint, format, prompt validation, and copilot multipliers validation. Nothing else.
- Designed to fit inside the per-step verification cycle of `/implement` and the autonomous executor's tight loops.
- Never reaches AWS, never runs pytest, never invokes the harness.

---

## Naming Convention

Exactly one named flag exists in the end-state CLI: `--pre`.

**The default has no name.** This is deliberate: the default carries the semantic weight of "I am about to merge", and naming it (e.g., `--presubmit`) creates the temptation to skip it for other named modes.

**Advisory flags are name-suffixed by their output, not by execution mode:**

- `--coverage` reports verifier coverage gaps and exits 0 unconditionally.

Flags from the legacy world that survive only as deprecation aliases for one minor cycle:

- `--ci` -> alias for the default. Removed once CI workflow is updated.
- `--scope all` -> alias for the default. Removed once docs/PROJECT_CONTEXT.md and slash commands are updated.

Removed outright:

- `--integration`, `--verifiers`, `--scope auto|python|terraform|docs|prompts`. Behaviour folded into the default.

---

## Substrate

The two-tier model is structurally weak without a substrate that makes "the default tier always runs in CI" cheap and reliable. GitHub Actions hosted runners are billed and constrained to ~2000 minutes/month; the current repository is approaching that cap. The proposed substrate is a **self-hosted GitHub Actions runner on EC2** with the same SSO and toolchain configuration as the developer machine.

Required substrate properties:

- Same Python interpreter, same `aws sso` configuration via SSM-injected creds, same `terraform`, `gh`, `docker` versions as the dev box. Drift between local and CI is the failure mode `validate.py` exists to prevent; the substrate must not reintroduce it.
- Branch protection on `main` requires the workflow to pass before merge. The workflow calls `python -m scripts.validate` (the default presubmit tier) and nothing else.
- Reversible in 30 seconds: a single binary registered against the repository. If the runner is deregistered, hosted runners pick up jobs again.
- Zero billed minutes for the default presubmit tier. Pip-audit, dependency health, and the V3 harness all run on the self-hosted runner without consuming budget.

The substrate stand-up is filed as a separate STRATEGIC plan (recommendation: "Stand up self-hosted GitHub Actions runner on EC2 with SSO substrate"). It is a prerequisite for the flag-consolidation work; without it, the default tier is too slow to run on every PR.

The alternative -- run all validation locally and have the GitHub status check trust developer-claimed PASS -- is structurally weak (see `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` Future Direction for the architect's three-point assessment: loses determinism, signalling problem, discretion creep). The local-only path is not pursued.

---

## Bounded Execution

Bounded execution is the property that makes the two-tier model usable by autonomous agents. An agent calling `validate.py` must be able to commit to a wall-clock budget *before* it sees the output.

The bounds:

- **Presubmit tier: 5 minutes total.** Inherited from `INTENT-verification-system.md` Constraint 8. Any check whose worst-case wall-clock exceeds this is decomposed (e.g., terraform plan moved to a separate scheduled health check) or capped with a per-check timeout that prefers "report timeout, FAIL closed" over silent extension.
- **Edit-loop tier: 30 seconds.** Hard upper bound on the entire `--pre` invocation. If lint or format takes longer, the file is too large or the toolchain is broken; either way, exceeding the budget surfaces as a FAIL.
- **Per-verifier timeout: 120 seconds.** Inherited from `INTENT-verification-system.md` Constraint 8. Verifiers exceeding this are reported as FAIL with detail "timeout exceeded".
- **DQ runner auto-invoke timeout: 60 seconds.** The runner queries Athena; longer than 60s implies a stuck query or SSO degradation. Timeout means SKIP with an actionable message, not a FAIL (Decision 57).

These bounds are surfaced in the `--help` output of both tiers so agents and humans can reason about them without reading source.

---

## Migration Sequence

The migration from four-flag to two-tier is a multi-step ratchet. Each step is reversible; the deletion event is the moment the convergence is real.

1. **Land this INTENT document and the matching Decision Record.** No flag changes yet. The architectural anchor must exist before any flag-consolidation PR can reference it. (This plan: `PLAN-dq-validate-integration.md`.)

2. **Wire the DQ runner auto-invoke into `--integration`.** Closes Gap 2 from `PLAN-audit-ops-recs-dq-scalability.md`. The current four-flag set continues to function. (This plan.)

3. **Stand up the EC2 self-hosted runner with SSO substrate.** Filed as recommendation alongside this plan. Branch protection switches to require the self-hosted workflow; no flag change yet. (Separate STRATEGIC plan.)

4. **[DONE] Add `--pre` parity tests and freeze its surface.** `--quick` renamed to `--pre`; existing test suite covers the `--pre` behaviour. Surface frozen by this plan (PLAN-validate-two-tier, 2026-05-09).

5. **[DONE] Consolidate flags.** Deleted `--scope`, `--ci`, `--integration`, `--verifiers`. Default is presubmit. `--pre` is the only named flag. `--coverage` remains as advisory. CI workflow updated to call `python -m scripts.validate` with no flags. (Implemented by PLAN-validate-two-tier, 2026-05-09.)

6. **Add scheduled postsubmit health checks.** Wave 4b of `INTENT-verification-system.md`. A nightly job runs the V3 harness against `main` to detect drift introduced after merge. (Filed as recommendation alongside this plan.)

7. **Delete this document's "migration sequence" section.** The convergence is real once steps 1-6 land. The migration sequence is transitional infrastructure; leaving it in place after convergence creates the same ambiguity the migration was meant to eliminate.

Each step files telemetry (`telemetry_process_events`, tier=decision) so the trajectory is queryable.

---

## Relationship to INTENT-verification-system

`INTENT-verification-system.md` defines the three-layer quality pyramid:

- Layer 1: structural checks (validate.py, pytest, ruff) -- this document refines.
- Layer 2: programmatic verifiers (the harness) -- this document delegates to.
- Layer 3: LLM judgment (code review) -- out of scope here.

Specifically, this document operationalises Wave 1 item 4 of `INTENT-verification-system.md`:

> 4. Add `--integration` and `--coverage` flags to `validate.py`

The `--coverage` flag is implemented in this plan; the `--integration` semantics are extended to auto-invoke the DQ runner when its cache is stale. Both will fold into the default presubmit tier per the migration sequence above. The `check_coverage()` function in `scripts/verifiers/__init__.py` is the implementation mechanism.

Where `INTENT-verification-system.md` answers "does the system actually do what it's supposed to do?" via Layer 2 verifiers, this document answers "what is the entrypoint that runs all of that, and what does it cost in time and substrate?". The entrypoint is `python -m scripts.validate` (default tier). The cost is bounded by the time budgets above. The substrate is the self-hosted runner.

The same-PR guard from `INTENT-verification-system.md` (a verifier and its covered code cannot land in the same PR except for initial creation) continues to apply unchanged. This document does not weaken that boundary.

---

## Constraints

1. **Agent-first reasoning.** All naming, time budgets, and exit-code semantics must be derivable by an autonomous agent reading `--help` and this INTENT doc together, without consulting external resources. If an agent has to ask a human "which flag should I use", the design has failed.

2. **No silent fallbacks.** When AWS credentials or the self-hosted runner are unavailable, the gate emits a structured event and skips with explanation. Skip is not failure. Crash is not failure either -- it is a design defect. (Decision 57 governs the SSO-unavailable case specifically.)

3. **No rescue agents.** A failed validate run does not invoke an LLM to retry, repair, or re-interpret. Failed means failed. The only response is RCA at the gate boundary -- file a recommendation, fix the gap permanently. (Decision 55.)

4. **CI workflow is the single source of truth for the presubmit tier.** Once consolidation lands, `.github/workflows/ci.yml` calls `python -m scripts.validate` with no flags. The workflow file does not encode any check that the script does not run. Drift is enforced absent by `validate.py`'s own self-test.

5. **Local-first outbox semantics for telemetry.** The validate run emits `telemetry_process_events` for each tier transition. Decision 51 governs the write path: local outbox first, drained to Iceberg by sync_ops. The validate script never writes directly to Athena.

6. **Windows compatibility.** All subprocess invocations use `sys.executable` (the `PYTHON` constant), pass `encoding="utf-8", errors="replace"` when `text=True`, and use list form -- never shell strings. Bash here-strings only where Bash is available; Git Bash on Windows must be a viable execution environment.

7. **No emojis, no em-dashes.** Plain ASCII. Windows console encoding mangles em-dashes; emoji rendering is inconsistent across terminals and AI agents.

8. **The migration sequence is committed but not load-bearing.** Each step is reversible by design. If self-hosted runner stand-up reveals operational issues that make hosted runners preferable, the migration halts at step 2 and the four-flag world continues. The sequence is not an irreversible commitment; the *direction* (toward two-tier) is.
