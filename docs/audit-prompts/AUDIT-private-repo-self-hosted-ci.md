# AUDIT: private-repo migration with self-hosted CI

## TASK

Assess a proposed migration of the repository `benjamin-blake/agent-platform` from its current
state (PUBLIC, Apache-2.0, CI on GitHub-hosted `ubuntu-latest` runners) to a PRIVATE repository
with CI executing on a self-hosted runner on owned hardware. Two decisions are coupled by GitHub's
policy on self-hosted runners and repository visibility -- verify that policy's current wording
yourself rather than assuming the coupling.

You will assess seven surfaces (S-VIS, S-RUNNER, S-CI, S-WAKE, S-GOV, S-SEC, S-CRED -- defined in
SCOPE), answer twelve questions (Q1..Q12), rate a rubric (VD1..VD7) per surface, run an internal
adversarial review to convergence, and produce two deliverables:

- `audits/private-repo-self-hosted-ci-<sha>.yaml` -- the structured audit record
- `audits/private-repo-self-hosted-ci-<sha>.md` -- a companion prose report, <= ~1500 words

The ONLY files you create or modify in the repository tree are those two deliverables. Regenerating
gitignored local caches per SETUP is expected and does not breach this boundary (never commit them).

You draft; the human disposes. Open a pull request and end your turn. Do not merge, do not poll,
do not implement any recommendation you make.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts. Every candidate
below is a hypothesis to adjudicate, not a defect to confirm.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.**

**A run that merely confirms the candidates below has failed.**

Adjudicate each candidate to exactly one outcome:

| Outcome | Where it goes |
|---|---|
| CONFIRMED defect, not owned by any existing roadmap item or decision | `findings[]`, classification `novel` |
| Owned by an existing item/decision whose remedy you judge insufficient | `findings[]`, classification `planned-insufficient` |
| Owned by an existing item/decision whose remedy is sound but unbuilt | `findings[]`, classification `planned-unbuilt` |
| Owned and fully covered by the owning item | `rejected_candidates[]` |
| Not a defect | `rejected_candidates[]`, naming the compensating control |

Severity is assigned by YOU after judgment (see SEVERITY + MATURITY). Nothing in this prompt's
ordering, emphasis, or phrasing carries severity information.

### Symmetry requirement (read before you begin)

A `findings[]` list structurally records only PROBLEMS. That shape can silently bias an audit
toward a no-go, because evidence that the migration IMPROVES something has nowhere to live.
This prompt corrects for that with a separate `migration_benefits[]` block, which you MUST
populate or explicitly declare empty with reasoning.

Actively seek evidence FOR the migration with the same rigor you apply against it. The candidate
list below is deliberately split: C1-C12 lean against the proposal, C13-C16 lean for it. That
split reflects what compose-time recon happened to surface -- it is NOT a weighting, NOT a
prior, and NOT a verdict. Weight both sets equally, and add your own candidates in either
direction.

Two failure modes are equally bad, and you are accountable for both:

- Concluding go because the requester wants to go.
- Concluding no-go because this prompt enumerated more risks than benefits.

## READ FIRST -- disambiguation traps

Seven hazards where a term names two different things, or where a plausible audit target is the
wrong one. Each invites a specific misread.

1. **"Full tier" is NOT the pull-request gate.** `ci.yml` has four jobs. `pr-validate`
   (`ci.yml:16-17`, `if: github.event_name == 'pull_request'`) runs `python -m scripts.validate --pre`
   -- the FAST tier -- and is the PR gate. `main-validate` (`ci.yml:85-86`,
   `if: github.event_name == 'push'`) runs the full tier and fires ONLY on push to main, i.e.
   post-merge. Any latency argument that treats the ~24-minute full tier as blocking the PR edit
   loop is wrong. Establish which loop each cost belongs to before reasoning about it.

2. **FOUR Terraform roots, different apply models.** `terraform/` (legacy, NOT applied -- retained
   as an architectural artefact per CD.21), `terraform/personal/` (live; auto-applies behind a
   deterministic guard), `terraform/github/` (manages the repository settings themselves; applied
   by hand, locally, every time -- FORBIDDEN from any auto-apply workflow per
   `terraform/github/CLAUDE.md`), and `terraform/bootstrap/` (admin-only, out of scope). The
   repository-visibility flip is a `terraform/github/` change.

3. **This repository already HAD a self-hosted runner and deliberately left it.** An EC2 self-hosted
   runner was retired on 2026-05-28 per CD.21; `terraform/ec2_runner.tf` is still on disk as a
   retained artefact, not live infrastructure. It is NOT the proposed box. Do not audit
   `ec2_runner.tf` as though it were the proposal, and do not treat its existence as evidence the
   proposal is already partly built. Its historical cost IS a relevant datum (see F39).

4. **`agent/*` versus `claude/*` branch prefixes.** The OIDC branch role's trust condition lists
   `repo:<owner>/<repo>:ref:refs/heads/agent/*` (`terraform/personal/oidc.tf`, near line 406), while
   `ci.yml`'s `signal-green` job keys on `startsWith(github.head_ref, 'claude/')` (`ci.yml:304`) and
   `AGENTS.md` states sessions work on harness-assigned `claude/...` branches. These are different
   prefixes in different mechanisms. Determine which is live before drawing any conclusion.

5. **"GHAS is always-on for public repos" is not "this repository owns GitHub Advanced Security."**
   `terraform/github/repo.tf:15-17` records that the `advanced_security` attribute is omitted
   because setting it errors on public repositories. Whether the underlying controls survive a
   visibility flip, and on what plan, is a question -- not something this comment answers.

6. **Two distinct meanings of "environment".** `tf-gated-apply` is a *GitHub Actions Environment*
   (`terraform/github/environments.tf`) used as a human-approval gate. Separately,
   `docs/contracts/environment-taxonomy.md` defines a sandbox/SIT/PROD *deployment environment*
   taxonomy. They are unrelated. Q5 concerns the former.

7. **"Billable" minutes versus "used" minutes.** These are not the same number here, and the
   difference is central to the economics. Establish the current billed amount empirically (see
   EMPIRICAL PASS) before accepting any cost baseline.

Additionally: the `audits/` directory already contains outputs of PRIOR, unrelated audits (e.g.
`audits/unclosed-loops-44ef5c6.yaml`). Those are context, not your deliverables and not your subject.

## SCOPE

### Surfaces (all BUILT and live unless stated)

| ID | Surface | Role |
|---|---|---|
| S-VIS | Repository visibility and the IP boundary | `terraform/github/repo.tf:11` sets `visibility = "public"`; `AGENTS.md` "PUBLIC repository / confidential-data boundary" |
| S-RUNNER | The proposed self-hosted runner host | DESIGNED-UNBUILT. No runner configuration exists in the repository today |
| S-CI | CI pipeline and the `scripts/validate.py` substrate | 19 workflow files; `scripts/validate.py`; `scripts/checks/` |
| S-WAKE | The agent wake substrate | `ci.yml` `signal-green` job; `.github/workflows/pr-conflict-signal.yml`; the `subscribe_pr_activity` harness subscription |
| S-GOV | Plan-tier governance controls | `terraform/github/repo.tf` `main_protection` ruleset; `terraform/github/environments.tf`; `.github/CODEOWNERS` |
| S-SEC | Code-security controls | `.github/workflows/codeql.yml`; `.github/workflows/ghas-probe.yml`; secret scanning + push protection in `repo.tf:18-23`; `.github/dependabot.yml` |
| S-CRED | OIDC credential path | `terraform/personal/oidc.tf`; the 16 workflow files declaring `id-token: write` |

### Vocabulary

- **Fast tier / `--pre`**: `python -m scripts.validate --pre`. Diff-aware lint, format, mypy,
  affected-set pytest selection, prompt checks. The PR gate.
- **Full tier**: `python -m scripts.validate` with no flags. Runs on push to main and on the
  `main-canary` schedule.
- **Guard**: `scripts/terraform_apply_guard.py`. Classifies a Terraform plan; exit 2 routes to the
  `tf-gated-apply` Environment.
- **Wake substrate**: the mechanisms that return control to a watching agent session when CI
  finishes or a PR becomes conflicted. See `AGENTS.md` "Push -> PR -> CI -> merge flow", step 4.
- **Convergence record**: `s3://.../convergence/personal/sandbox.json`; a red record hard-blocks apply.

### Out of scope -- do not audit, do not opine

- The DuckLake/Neon + S3 warehouse and its migration status. Stays in AWS. Out of scope.
- Trading strategy, alpha, or any hosted-product domain logic.
- The Decision 67 executor freeze and the STRATEGIC-plan suspension. Ambient constraints.
- Whether `validate.py`'s individual checks are correct. Its role as a portability boundary IS in
  scope (Q10); the correctness of its checks is not.
- `terraform/bootstrap/` and admin-tier credential recovery procedures.

### Trust-nothing clause

Obtain every file, line number, size, and count by reading the repository yourself. **Trust no
number quoted in this prompt.** Re-derive each from the tree at your audited base commit. Record
any anchor that does not resolve in `meta.stale_anchors` and proceed -- a stale anchor is a note,
never a blocker.

## PROPOSED HARDWARE AND WORKLOAD

The target host is a specific, already-purchased machine. Full component specification, from the
purchase record (April 2025):

| Component | Specification |
|---|---|
| CPU | AMD Ryzen 9 9950X, AM5, 16 cores / 32 threads |
| Motherboard | ASRock B850 LiveMixer WiFi (AM5) |
| RAM | Kingston FURY Beast 32 GB as a **single 1x32GB DDR5-5600 module** |
| Storage | 4 TB Kingston FURY Renegade M.2-2280 NVMe SSD |
| GPU | Gigabyte GeForce RTX 3050 6 GB OC, low-profile |
| CPU cooler | Arctic Liquid Freezer III 240 mm AIO |
| PSU | 700 W, 80 Plus Bronze |
| Case | Mid tower |
| OS | Ubuntu |
| Capital cost | ~GBP 1,390 including VAT, April 2025 |
| Ownership | Owned outright; personal hardware |

Three properties of this specification are load-bearing and easy to miss:

- **The memory is single-channel.** One 32 GB module populates one channel on a board that supports
  two. Memory bandwidth is roughly half what a matched 2x16GB pair would deliver on the same board,
  and a 32-thread CPU saturating a single channel is a plausible bottleneck for parallel workloads.
  Free DIMM slots exist, so this is remediable for the price of RAM -- factor that into any
  recommendation rather than treating it as fixed.
- **32 GB total across up to 32 concurrent workers** is roughly 1 GB per worker before accounting
  for the OS, the container runtime, and any co-resident workload.
- **The GPU is a low-profile RTX 3050 (6 GB)** -- adequate for display output, not a compute asset.
  Do not assume GPU acceleration is available for anything.

### Dual-purpose intent (requester-supplied)

This is the SAME machine intended to run the trading product's symbolic-regression / formula-discovery
workload (PySR). `AGENTS.md` states "PySR runs on a separate compute node"; the requester confirms
that node and this proposed runner are one physical machine.

**Theorise briefly whether one CPU can carry both responsibilities** -- CI runner and formula
discovery. One or two paragraphs in Q2's prose, informed by the memory-channel and per-worker-RAM
facts above and by the duty-cycle question. Consider whether the two workloads can be temporally
separated (scheduling, niceness, cgroup limits, pausing one for the other), whether that separation
is compatible with the availability requirements Q4 establishes, and whether contention is
symmetric or falls mainly on one side.

**This is explicitly a BOUNDED theorisation.** Do not benchmark PySR, do not research symbolic
regression performance characteristics in depth, and do not fetch external sources for it. Reason
from the hardware facts and stated workload shapes, mark the conclusion as a hypothesis, and move
on. It informs Q2's verdict; it is not a separate question.

### Still unstated -- do not invent

Not stated, and not derivable from the repository: network bandwidth and whether the host is on a
residential connection, physical location and security, UPS or power redundancy, expected uptime or
duty cycle, whether the machine sleeps or is powered off when unattended, electricity tariff, and
PySR's actual CPU/memory profile and duty cycle.

**Rule for unstated inputs:** where a calculation requires one, state the assumption explicitly in
the finding or answer, give the figure as a RANGE across a plausible span rather than a point
estimate, and record it in `meta.assumed_inputs` as `{input, assumed_value, why, sensitivity}`. Do
NOT silently pick a number, and do NOT refuse to answer. If a conclusion flips across the plausible
span of an assumed input, that sensitivity is itself a finding.

## REQUESTER CONTEXT (stated intent -- treat as claims to test, not as findings)

The requester supplied the following motivation. It is the requester's stated belief. It is NOT
established fact, and several parts are empirically checkable against the repository and against
GitHub's current published documentation. Test it; do not adopt it.

- The requester is concerned that this work could be taken by others and monetised.
- The requester assesses the current moat as small, and locates the valuable asset in the DuckLake
  operational data rather than in the code.
- The requester notes that this data is already being consumed to improve the platform itself.
- The requester states the original reason for going public was an assumption that a private
  repository would be unaffordable, and believes self-hosting CI may remove that constraint.

Two threads in that statement are load-bearing and you must address both explicitly in Q1:

(a) The causal chain "private was unaffordable -> self-hosting makes private affordable -> therefore
    go private" has three links, each independently checkable. Check each.
(b) If operational data value flows continuously into the platform's code, prompts, contracts, and
    configuration, then the code progressively ENCODES the asset the requester is trying to protect.
    Argue whether this raises or lowers the value of a visibility flip, and say which.

### Unverified premises carried into the questions

These entered via the requester's brief and have NO corroborating repository artifact. Each is
flagged where it appears. Verify each against primary sources before building an argument on it;
if a premise proves false, say so and re-frame the affected question rather than answering the
false version.

- **P1** (feeds Q10): that GitHub announced a per-minute platform charge for self-hosted runners
  effective 2026-03-01, and that it was postponed rather than cancelled. No repository artifact
  records this. If you cannot corroborate it, treat Q10 as the general question "how portable is
  this CI if self-hosted execution stops being free or stops being available", which does not
  depend on P1.
- **P2** (feeds TASK, Q1): that GitHub requires or restricts self-hosted runners to private
  repositories. GitHub's published guidance on this has historically been a RECOMMENDATION about
  fork-PR risk rather than an enforced restriction. Establish the current, actual wording; the
  strength of the coupling between the two decisions depends on it, and if the coupling is weaker
  than assumed, the two decisions can be evaluated independently.

## NORTH STAR

The bar you judge each surface against. These are principles, not absolutes -- argue each case; do
not pattern-match. Derived from `docs/PROJECT_CONTEXT.md` and `AGENTS.md`.

- **NS1 Governed autonomy.** Agents act under bounded authority, with independent verification
  between intent and irreversible effect.
- **NS2 Verification is the admission mechanism.** Independent CI verdicts are the safety envelope,
  not a formality. A control that cannot render a verdict is not a control.
- **NS3 Evidence over assertion.** A signal is not proof. A control asserted to be live but not
  live-verified is a claim, not a control. (This is the ULF-01 lesson: see `AGENTS.md` T2.12 note.)
- **NS4 Portability.** Models, compute providers, and hosts are replaceable implementation choices,
  not product identity. Exit cost is a first-class design property.
- **NS5 Non-wedging governance.** Controls must not deadlock the loop they govern. Several existing
  controls are deliberately advisory for exactly this reason (Decision 83).
- **NS6 Public-content boundary.** Market the engineering, not the alpha. Credentials, account ids,
  ExternalIds, and alpha never reach the repository -- independent of visibility.
- **NS7 Durable state is authoritative.** Local files are caches, never write sources.

## THE QUESTIONS

Answer all twelve. Each gets exactly ONE entry in `question_answers[]`. Q1, Q3, Q9, and Q12 use
special entry shapes defined in OUTPUT; Q2, Q4, Q5, Q6, Q7, Q8, Q10, Q11 use the generic shape.

### Q1 -- Does going private plausibly protect anything worth protecting?

Enumerate the protections a visibility flip would plausibly confer **on future commits**. Rank them
by how load-bearing each is. State honestly which are speculative.

**Build an explicit adversary model first** -- the same rigor VD1 demands and Q7 requires for the
runner. Name the adversaries (who would take this work, and to do what), the assets (what
specifically has value, and to whom), and the acquisition channels. Then assess which channels a
visibility flip actually closes.

Channels you must consider, at minimum:
- Direct repository read while public.
- Republication or mirroring by third parties.
- **Transmission to third-party model providers.** This repository's contents are continuously sent
  to external model APIs by design (see the roadmap cost model's inference line items, F40). A
  visibility flip does not touch this channel. Assess what it means for the protection claim.
- Anything the platform publishes or exposes that remains legible after the flip.

Treat the residual-leak floor as a BOUNDED INPUT, not the verdict, and reason about it analytically
-- **do not attempt to actually perform a reconstruction**. Assume the public history is effectively
redactable (0 forks; 1 star, which is the owner's own). Reason about what must stay legible after
migration and whether that floor erodes the forward protections you enumerated.

Address (a) and (b) from REQUESTER CONTEXT explicitly.

**Because the answer depends on intent the repository cannot reveal, rate Q1 under EACH of four
pinned intent scenarios**, then give one headline recommendation under the scenario you judge most
probable from repository evidence -- marking that judgment as an inference and naming the evidence.

| Intent id | Scenario |
|---|---|
| I-A | Solo instrument. The platform remains a personal tool; no commercial intent. |
| I-B | Commercial product. The platform or a derivative is licensed or sold later. |
| I-C | Portfolio and credibility. The public engineering surface is itself the asset. |
| I-D | Open-core. Platform public; hosted product and data private. |

Verdict enum (per intent scenario AND for the headline):
`recommend-private | recommend-public | recommend-conditional`
(`recommend-conditional` REQUIRES naming the preconditions.)

### Q2 -- What does the full tier actually cost on 16C/32T versus 2 cores?

Establish whether the suite is already parallelised, and at what width it runs today. Then model
the speedup on the proposed hardware. Show the model's assumptions.

**The box is SHARED with the PySR workload.** Treat CPU and memory contention as a first-class
constraint: model the speedup both contended and uncontended, and state which figure a migration
decision should use. PySR's duty cycle is UNSTATED -- follow the unstated-input rule.

Consider explicitly whether the bottleneck is CPU-parallel at all: identify what fraction of the
full tier is parallelisable work versus serial setup (dependency installation, tool startup,
Terraform init, network-bound steps), and bound the achievable speedup accordingly. Note that 32 GB
across many concurrent pytest workers is itself a constraint worth checking.

Verdict enum: `material-speedup | marginal-speedup | no-speedup | regression`

### Q3 -- Runner design

Specify the runner architecture: ephemeral versus persistent, containerised jobs for
`ubuntu-latest` parity, how many concurrent runners one box should host given PySR contention, and
the registration, upgrade, and monitoring story.

You are AUTHORING this design -- no runner configuration exists in the repository. Then you rate
the design you authored against the checklist below. This self-referential structure is deliberate
and is assigned to you: propose the strongest design you can, then rate it honestly. A design you
rate `met` on all ten while having hand-waved the hard parts is a failed answer; the adversarial
review phase will be looking for exactly that.

**EXTERNAL CHECKLIST.** Assess property-by-property, rating each `met | partial | missed` with
evidence. `partial` requires an argued, property-matched compensating control. This field is the
SOLE source the maturity top tier reads for S-RUNNER.

| # | External practice |
|---|---|
| 1 | Ephemeral (single-job) runners rather than persistent, per GitHub's hardened-runner guidance |
| 2 | Just-in-time / short-lived registration tokens rather than a long-lived registration secret |
| 3 | Job-level container isolation to approximate `ubuntu-latest` image parity |
| 4 | Runner process executes as a non-root, least-privilege service account |
| 5 | Restricted outbound network egress from the runner host |
| 6 | Defined runner-version upgrade and pinning policy |
| 7 | Host-level liveness monitoring and alerting on runner availability |
| 8 | Separation of untrusted (fork PR) workloads from privileged workloads, by runner group or label |
| 9 | Secrets never persisted to the runner filesystem across jobs |
| 10 | Workspace and build-cache cleanup between jobs (no state bleed) |

Verdict enum: `sufficient | partial | insufficient`

### Q4 -- Availability

Jobs targeting a self-hosted runner queue, and GitHub cancels them after a documented timeout
(verify the current value). Determine what breaks when the box is off, asleep, saturated by PySR,
or otherwise unavailable.

Cover the wake substrate specifically. All three mechanisms assume CI answers in minutes:
`subscribe_pr_activity` (harness-side), `ci.yml`'s `signal-green` comment (`ci.yml:293-322`), and
`pr-conflict-signal.yml`. `AGENTS.md` retired the `send_later` backstop on the explicit reasoning
that no dropped-signal gap remained. Determine whether an offline runner reopens such a gap, and if
so what replaces the backstop.

Extend beyond human-driven PRs: assess whether runner unavailability affects the scheduled
workflows (`main-canary` 3-hourly, `codeql` and `ghas-probe` weekly, `terraform-drift` hourly) and
the `workflow_run`-chained `ci-rca` pipeline. Consider also whether a HYBRID assignment (some jobs
hosted, some self-hosted) changes the answer.

Verdict enum: `closed | partially-closed | reopened-gap`

### Q5 -- Plan tier

Establish, against GitHub's CURRENT published plan documentation, what a private repository on
GitHub Free loses relative to a public repository -- specifically regarding Actions Environments
with required reviewers, branch protection or rulesets, required status checks, and required
reviewers. Then determine what in THIS repository depends on each.

**This repository has already lived through exactly this failure mode, and recorded it.**
`docs/DECISIONS.md:5269` (Decision 89) declared GitHub branch protection "permanently unavailable"
for this repository under the free plan, citing the private-repo restriction on
`required_status_checks`. Decision 83 (`docs/DECISIONS.md:4487`) reversed that premise on the
grounds that the repository was made public on 2026-05-30, "removing that restriction". Read both.
A visibility flip appears to re-impose the exact constraint Decision 89 described -- determine
whether that is so under GitHub's CURRENT plan terms (which may have changed since Decision 89 was
written), and what it costs.

Named dependencies to trace: the `tf-gated-apply` Environment (declared as a job-level
`environment:` in three workflow files), the `main_protection` ruleset in
`terraform/github/repo.tf:62-119` (its `required_status_checks` on `pr-validate` and
`terraform-validate`, `require_code_owner_review`, `required_linear_history`), `.github/CODEOWNERS`,
and the server-side half of the never-commit-on-main rule (the client-side half is the
`.claude/hooks/never_on_main.py` PreToolUse hook).

Price the alternatives against GitHub Pro. Cost is weighted CO-EQUAL with IP protection in this
audit -- do not dismiss a price difference as immaterial without argument, and do not inflate one.

Verdict enum: `no-loss | loss-mitigable | loss-blocking`

### Q6 -- Security regression

Determine what happens on a private repository without paid add-ons, against current GitHub
documentation, to each of: CodeQL / code scanning, secret scanning, push protection, **the
dependency graph, and Dependabot alerts and security updates** (`.github/dependabot.yml` declares
pip and github-actions ecosystems, weekly). For each control, state what replaces it, or state that
nothing does.

Then determine the fate of Decision 83 / audit finding ULF-01 and its standing `ghas-probe` monitor
(`.github/workflows/ghas-probe.yml`, weekly cron at line 39). That monitor exists specifically to
prove -- against the live API, not against Terraform configuration -- that these controls are
enabled. `AGENTS.md` asserts these controls are live, citing dated evidence. Assess what must change
in that assertion, in the monitor, and in the decision record, and whether the migration creates a
period in which the assertion outlives the reality it describes (the exact defect class ULF-01
named).

Note the interaction with Q7: Dependabot updates dependencies that would then execute on the
privileged host. Losing Dependabot alerts and gaining a privileged execution host are related
changes, not independent ones.

Verdict enum: `replaced | partially-replaced | unreplaced`

### Q7 -- Threat-model the runner as a privileged host

The runner would execute `terraform apply` against live AWS infrastructure, hold AWS authority via
OIDC-federated roles, persist state between jobs if persistent, and install dependencies -- including
automated Dependabot updates -- on personally-owned hardware that also runs another workload.

Produce an actual threat model: assets, adversaries, entry points, and the trust boundary the host
sits on. Assess at minimum: compromise of the runner yielding AWS authority; persistence and state
bleed between jobs; malicious or compromised dependencies executing on the host; blast radius
reaching the co-resident PySR workload and any other data on that machine; and physical and network
exposure of a host on a personal network.

Compare against the property the current GitHub-hosted arrangement provides: a fresh, disposable VM
per job. State clearly which properties are LOST, not merely which are changed. Where a proposed
control from Q3 mitigates a threat, say so and apply the property-match rule to it.

Verdict enum: `acceptable | acceptable-with-controls | unacceptable`
(`acceptable-with-controls` REQUIRES enumerating the controls.)

### Q8 -- Does OIDC survive?

Confirm whether OIDC federation survives (a) the repository-visibility change and (b) self-hosted
execution, for the workflows declaring `id-token: write`. Inspect the trust conditions in
`terraform/personal/oidc.tf` and determine whether any condition derives from repository visibility.

Note the branch-prefix trap (READ FIRST item 4) when assessing whether trust conditions match the
branches actually in use.

Then the forward-looking half: if CI ever leaves GitHub Actions entirely (Q10), the
`token.actions.githubusercontent.com` issuer disappears. What is the on-prem credential story?
Assess the options against NS1 (bounded authority) and Q7's threat model -- a long-lived static
credential on the runner host is one option; say what it costs.

Verdict enum: `survives | survives-with-changes | breaks`

### Q9 -- Published history and licensing

The requester assesses the already-published history as effectively redactable given 0 forks and 1
self-star. Test that assessment briefly against what is actually recoverable from third-party
mirrors, archives, caches, and any published artifact -- then state whether retraction is worth
doing, and at what effort. The repository has been public since 2026-05-30 (F11).

Separately, recommend a license posture for future commits. The repository is currently Apache-2.0
(`LICENSE`). A permissive license already granted on published commits cannot be revoked for those
commits. Consider the requester's monetisation concern and make an actual recommendation.

Verdict enum: `worth-doing | not-worth-doing | moot`
Plus a license recommendation: `keep-apache-2.0 | change-to-<named-license> | dual-license`

### Q10 -- Escape hatch

**Premise P1 applies here and is uncorroborated -- verify it first** (see REQUESTER CONTEXT). If P1
does not hold, answer the premise-independent form: how portable is this CI if self-hosted execution
stops being free, stops being available, or must be abandoned for any reason?

Assess `scripts/validate.py` as the claimed single entrypoint. Establish empirically how many of the
19 workflow files actually route through it, and cost the migration of those that do not.
Specifically cost `terraform-apply-sandbox.yml`, `reconcile.yml`, the two deploy workflows, and
`ci-rca.yml`'s `workflow_run` chaining (`ci-rca.yml:6-31`) -- naming for each the GitHub-Actions-native
feature it depends on (Environments, OIDC, `workflow_run` events, `gh` CLI, artifact storage,
concurrency groups) and what replacing that feature would require.

Verdict enum: `portable | portable-with-cost | locked-in`

### Q11 -- Sequence and rollback

Produce a sequenced migration plan. For each step state: what it changes, whether it is reversible
and at what cost, what must be proven working before it, and the abort criterion.

State explicitly what must be proven working BEFORE the repository flips to private -- the flip has
the sharpest asymmetry, since some controls cannot be tested on a private repository without first
being on one.

Identify any ordering constraint that, if violated, produces a lockout: a state in which neither
the human nor an agent can merge, apply, or recover. `terraform/github/CLAUDE.md` documents an
existing "Lockout recovery" procedure for the ruleset; assess whether it survives this migration.

If your Q1 headline is `recommend-public`, still produce the plan -- conditioned on the requester
overriding that recommendation. The plan's existence is not an endorsement.

Verdict enum: `sequenced-plan-with-rollback | plan-with-unresolved-blockers | no-viable-sequence`

### Q12 -- What did the requester not think to ask?

Seeded candidates below. Answer each AND extend the list from your own analysis.

1. The proposal reverses two ratified decisions and invalidates a completed tier item's exit
   criteria (see DEDUP DISCIPLINE). What is the process obligation for reversing a ratified decision
   in this repository, and does this audit satisfy it?
2. `AGENTS.md` and `docs/PROJECT_CONTEXT.md` state the platform end-state is "a public, agent-first
   automation platform". Does going private contradict a stated end-state, and if so, which artifacts
   must change?
3. What happens to the `claude.yml` workflow and the Claude Code OAuth token path on a private repo?
4. Does a single-owner private repository change the meaning of the sole-developer compensating
   controls (`prevent_self_review = false`, `required_approving_review_count = 0`, admin bypass)?
5. Is there a middle option neither the requester nor this prompt named -- private repo with
   GitHub-hosted runners on a paid plan; a hybrid runner assignment; a split-repository topology per
   CD.32 -- and does it dominate the proposed plan on any axis?
6. What is the maintenance burden, in recurring human hours, of operating a self-hosted runner, and
   who absorbs it in a solo-developer project?
7. What does the repository LOSE by going private that is not a security control -- Codespaces
   quota, the CD.20 "curated portal" public-surface intent, T2.11a's one-click evaluator boot, any
   portfolio or credibility value?

## RUBRIC

Rate every dimension for every surface. Pinned enum: `strong | adequate | weak | absent | n/a`.

`n/a` is a CORRECT and COSTLESS rating where a dimension does not structurally apply. Never
manufacture a rating or a finding to fill a cell.

Rate the POST-MIGRATION state as proposed -- this is a forward-looking assessment, not a review of
the status quo. Where the current state is materially better or worse on a dimension, say so in the
`note` field.

| ID | Dimension | Asks |
|---|---|---|
| VD1 | Threat-model fit | Does the control address a named adversary and a named asset, or is it a control in search of a threat? |
| VD2 | Verification liveness | Is the control's live state provable, or merely configured and asserted? (NS3) |
| VD3 | Availability and non-wedging | Does the surface preserve the loop when degraded, or can it deadlock it? (NS5) |
| VD4 | Portability and exit cost | How tightly coupled to one vendor or host, and what does leaving cost? (NS4) |
| VD5 | Blast radius and least privilege | What authority is held, and what contains it? (NS1) |
| VD6 | Economic honesty | Are costs and savings stated against an empirically verified baseline? |
| VD7 | Reversibility | Can the change be undone, and at what cost? |

## DEEP-DIVES

Each deep-dive produces analysis. Whether any part of it becomes a finding is YOUR adjudication
under the CANDIDATE OBSERVATIONS contract -- these blocks name threads to trace, not verdicts to
reach.

### DD-A -- The cost baseline (feeds Q1, Q2, Q5, Q10; VD6)

Establish the true current cost of CI, then the true post-migration cost. Derive every figure.

**Start from the repository's own cost model** -- `docs/ROADMAP-PLATFORM.yaml`, the `cost_model`
block (near lines 279-300). It carries a headline `total_per_month_usd`, an enumerated `breakdown`,
a `headline_basis` with an explicit unenumerated add-on, and a `line_items_not_enumerated` list.
Two entries are directly on point: `ec2_runner_24_7` records the retired self-hosted runner's
historical cost, and `line_items_not_enumerated` explicitly folds "GH-hosted runner minutes" into
the add-on. This is a LIVE system of record. A cost finding filed as `novel` without searching it
is a dedup failure.

Trace end to end: what the repository is billed today; what changes at the moment of the visibility
flip; the applicable free allowance on each candidate plan; actual monthly usage; and the residual
bill under each option (stay public / private + hosted runners / private + self-hosted / hybrid).
Include the self-hosted option's non-Actions costs: electricity, hardware amortisation, and human
maintenance time. Several of these inputs are UNSTATED -- follow the unstated-input rule and give
ranges.

Counterfactual: **if the self-hosted runner were removed from the plan and the repository simply
went private on a paid GitHub plan, what would actually change?** Answer in money and in
engineering hours.

### DD-B -- Wake-substrate liveness under an unavailable runner (feeds Q4; VD2, VD3)

Trace each wake mechanism end to end and determine its behaviour when a queued job never starts.

For each of `signal-green`, `pr-conflict-signal`, and `subscribe_pr_activity`: what event fires it,
what happens when the job it depends on is queued rather than completed, and whether the watching
session receives anything at all. Then determine the observable state of a watching agent session
at T+1h, T+6h, and past the queue-cancellation timeout.

Counterfactual: **if the runner never comes online, does any mechanism in the current design
eventually tell the agent so?** Determine the answer, then adjudicate whether it constitutes a
defect under the CANDIDATE OBSERVATIONS contract and assign severity by the SEVERITY rules -- not by
the sharpness of this question's framing.

### DD-C -- The ratified-decision reversal (feeds Q1, Q12; VD1, VD7)

The proposal reverses CD.20 (ratified as dec-111, the public flip) and CD.21 (ratified as dec-112,
the move to GitHub-hosted runners), and invalidates exit criteria of tier item T2.10 (status
`complete`), which include "no remaining workflow references the self-hosted runner label". CD.21
additionally `narrowly_supersedes` a clause of Decision 68; reversing CD.21 therefore has a
second-order effect on Decision 68's status.

**Decision 68 lives in `docs/DECISIONS_ARCHIVE.md` (near line 1546), NOT in `docs/DECISIONS.md`** --
titled "Self-Hosted EC2 Runner as Canonical CI Execution Environment (Superseded by Decision 112)".
Grepping only `DECISIONS.md` for it returns nothing.

Read the reasoning recorded for each and determine: what conditions were assumed at ratification,
whether those conditions have actually changed, and whether the proposal's rationale engages with
the original reasoning or merely postdates it. A reversal justified by new information is
legitimate; whether this one is, is your adjudication.

## GROUNDING MAP

This map exists to spend your cognition on judgment rather than on grep. **Verify every anchor
before relying on it** -- re-read the file, confirm the line, and record any non-resolving anchor in
`meta.stale_anchors`. Facts are stated neutrally and carry no verdict.

### Workflow inventory

- F1. `.github/workflows/` contains 19 `.yml` files.
- F2. Across those files, `runs-on: ubuntu-latest` appears 33 times; no other `runs-on` value appears.
- F3. 16 of the 19 files contain `id-token: write`.
- F4. 3 files reference `scripts.validate` (`ci.yml`, `main-canary.yml`, `ci-rca.yml`); 16 do not.
- F5. `environment: tf-gated-apply` appears as a job key in `reconcile.yml:647`,
  `terraform-apply-sandbox.yml:750`, and `tf-gated-apply-prototype.yml:35`.

### CI structure and timing

- F6. `ci.yml:16-17`: job `pr-validate`, `if: github.event_name == 'pull_request'`. `ci.yml:67` runs
  `python -m scripts.validate --pre`. `timeout-minutes: 30` (`ci.yml:19`).
- F7. `ci.yml:85-86`: job `main-validate`, `if: github.event_name == 'push'`. `ci.yml:136` runs
  `python -m scripts.validate`. `timeout-minutes: 60` (`ci.yml:88`).
- F8. `ci.yml:293-304`: job `signal-green`, `needs: [pr-validate, terraform-validate]`, gated on
  `success() && github.event_name == 'pull_request' && startsWith(github.head_ref, 'claude/')`,
  `continue-on-error: true`, retried up to 3 times (`ci.yml:318-322`).
- F9. Across the 30 most recent `ci.yml` runs on push-to-main, wall-clock duration had median 23.8
  minutes, p10 22.1, p90 27.7, max 30.6.
- F10. A `get_workflow_run_usage` call against `ci.yml` push-to-main run id `31685689143` returned
  `billable.UBUNTU.total_ms = 0` across 4 jobs, with `run_duration_ms = 1325000`.
- F11. Repository-wide, the Actions API reported `total_count = 10442` workflow runs all-time. **The
  repository became public on 2026-05-30** (`terraform/github/repo.tf:16-17`; `docs/DECISIONS.md:3185`).
  Note that 2026-05-28 is a DIFFERENT date -- the repository's GitHub `created_at` and the EC2-runner
  retirement date. Use 2026-05-30 for any public-window calculation.
- F12. `main-canary.yml:5`: `cron: '0 */3 * * *'`. One observed run had a wall-clock duration of 27.6
  minutes.
- F13. `codeql.yml:9`: `cron: "0 6 * * 1"`. `ghas-probe.yml:39`: `cron: '0 7 * * 1'`.
  `terraform-drift.yml:42`: `cron: '17 * * * *'`.
- F14. `ci-rca.yml:6-31`: triggered `on: workflow_run:` with a `workflows:` list naming `CI`,
  `Main Canary`, `terraform-apply-sandbox`, `rec-autoclose`, `deploy-ducklake-lambdas`,
  `deploy-prod-lambdas`; `types: [completed]`.

### Test suite and parallelism

- F15. `scripts/checks/_scaffolding.py`, function `_build_unit_test_cmd` (definition at line 121),
  returns a pytest command whose argument list includes `"-n", "auto"` (lines 147-148),
  `--timeout 120`, `--timeout-method=thread`, a fixed `--randomly-seed`, and `-m "not integration"`.
- F16. `pyproject.toml:7-15` sets `addopts` including `--randomly-seed=last`, `--disable-socket`, and
  `--allow-hosts=127.0.0.1,::1`.
- F17. `pytest-xdist>=3.6.1` appears in `requirements-dev.txt:11` and `requirements-fast.txt:12`.
- F18. `find tests -name "test_*.py"` returns 501 files.
- F19. `scripts/validate.py` is 428 lines and defines the flags `--pre` and `--terraform-only` among
  others; with no flags it runs the full check suite.

### Repository settings (Terraform-managed)

- F20. `terraform/github/repo.tf:11`: `visibility = "public"`.
- F21. `terraform/github/repo.tf:13-24`: a `security_and_analysis` block enabling `secret_scanning`
  and `secret_scanning_push_protection`. The comment at lines 15-17 states `advanced_security` is
  omitted because GHAS "is always-on for PUBLIC repos" and setting it via the API errors.
- F22. `terraform/github/repo.tf:62-119`: `github_repository_ruleset` named `main-protection`,
  `enforcement = "active"`, with `bypass_actors` at repository-admin role and `bypass_mode = "always"`.
- F23. Within that ruleset: `require_code_owner_review = true` (line 87),
  `required_approving_review_count = 0` (line 89), required checks `pr-validate` (line 97) and
  `terraform-validate` (line 101), `strict_required_status_checks_policy = false` (line 107),
  `required_linear_history = true` (line 110). Lines 112-117 record that `required_signatures` is
  deliberately absent.
- F24. `terraform/github/environments.tf`: `github_repository_environment` named `tf-gated-apply`,
  with `prevent_self_review = false`, a `reviewers` block sourced from
  `var.gated_apply_reviewer_user_ids`, and `deployment_branch_policy` with
  `protected_branches = true`, `custom_branch_policies = false`.
- F25. `terraform/github/repo.tf:123-139`: `allowed_actions = "all"`,
  `default_workflow_permissions = "read"`, `can_approve_pull_request_reviews = false`.
- F26. `.github/CODEOWNERS` exists and scopes paths including `/.github/workflows/terraform-*.yml`
  and `/terraform/bootstrap/`.
- F27. `.github/dependabot.yml` declares two ecosystems, `pip` and `github-actions`, both weekly.

### Credentials and OIDC

- F28. `terraform/personal/oidc.tf` defines trust conditions using
  `token.actions.githubusercontent.com:aud` (StringEquals `sts.amazonaws.com`) and
  `token.actions.githubusercontent.com:sub` (StringLike). Observed sub patterns include
  `repo:<owner>/<repo>:ref:refs/heads/main`, `repo:<owner>/<repo>:ref:refs/heads/agent/*`,
  `repo:<owner>/<repo>:pull_request`, and `repo:<owner>/<repo>:ref:refs/pull/*` (near lines 404-406,
  602-604, 790, 813-815).
- F29. `ghas-probe.yml` header records two credentials by name and expiry only: `GHAS_PROBE_TOKEN`
  (fine-grained PAT, repo-scoped, expires 2027-05-31) and `CLAUDE_CODE_OAUTH_TOKEN` (expires
  2027-05-31).

### Governing decisions and roadmap items

- F30. `docs/ROADMAP-PLATFORM.yaml`, `candidate_decisions`: CD.20 "Repository public-flip after T2.3;
  public surface is curated portal, not export of operational data", `state: ratified`,
  `ratified_as: dec-111`.
- F31. CD.21 "CI migrates from self-hosted EC2 runner to GitHub-hosted runners + OIDC federation on
  public-flip", `state: ratified`, `ratified_as: dec-112`, with a `narrowly_supersedes` block naming
  Decision 68's self-hosted-EC2-runner-as-primary-CI-surface clause.
- F32. CD.32 "Multi-product platform topology (unified project_id data plane + IP-boundary-only repo
  axis)", `state: pending`, whose `discipline_points` state that the data/identity axis and the
  code/repo axis (monorepo versus separate private repos) are orthogonal and must not be conflated.
- F33. CD.38 "Executor delegates verification execution to GitHub Actions; AWS waits on verdicts",
  `state: pending`, whose discipline points include "GitHub Actions is the sole verifier/validation
  runner; AWS never runs validate.py or verifiers in-cloud."
- F34. `docs/DECISIONS.md`: `## Decision 83: Branch Protection Now Active -- Amends Decision 89
  Premise (Decided)` at line 4487; `## Decision 77` at 4786; `## Decision 73` at 4982;
  `## Decision 89: GitHub Branch Protection Not Available -- CI Enforcement as the Only Merge Gate
  (Decided)` at line 5269.
- F35. `AGENTS.md`, "Temporary Operational Constraints", asserts GHAS secret-scanning, push
  protection, and Actions permissions "were live-verified 2026-08-11 by `ghas-probe` run
  31536138747", and that CodeQL is verified separately via green `codeql.yml` runs.
- F36. `AGENTS.md`, "Push -> PR -> CI -> merge flow" step 4, states the `send_later`/trigger backstop
  is retired, on the reasoning that both events `subscribe_pr_activity` cannot deliver natively are
  now covered by event-driven comments and no dropped-signal gap remains.
- F37. `LICENSE` is the Apache License, Version 2.0.
- F38. `terraform/CLAUDE.md` and `terraform/github/CLAUDE.md` state that `terraform/github/**` is
  excluded from `terraform-apply-sandbox.yml`'s path filter and must never be added to any auto-apply
  workflow; `terraform/github/CLAUDE.md` documents a "Lockout recovery" procedure.
- F39. `docs/ROADMAP-PLATFORM.yaml` `cost_model.current_scale` records
  `total_per_month_usd: "22-59"`, a `breakdown` whose `ec2_runner_24_7` entry reads
  `"$0 (retired 2026-05-28 per CD.21; ~$35/mo historical, line retained as baseline)"`, a
  `headline_basis` with `add_on_usd: "10-30"`, and a `line_items_not_enumerated` list that includes
  "GH-hosted runner minutes".
- F40. The same `cost_model` breakdown includes `deepseek_executor_inference` and
  `anthropic_escape_hatch_spillover` line items, describing recurring inference spend through
  external model-provider APIs.
- F41. `docs/ROADMAP-PLATFORM.yaml` tier item T2.10, "GitHub OIDC federation + hosted-runner
  migration; mark self-hosted runner deprecated", has `status: complete`,
  `completed_at: "2026-05-28"`, `related_candidate_decisions: [CD.21]`, and exit criteria including
  "no remaining workflow references the self-hosted runner label" and "terraform/ec2_runner.tf has a
  deprecation header referencing CD.21".
- F42. `docs/DECISIONS_ARCHIVE.md` near line 1546 contains `## Decision 68: Self-Hosted EC2 Runner as
  Canonical CI Execution Environment (Superseded by Decision 112)`.

## CANDIDATE OBSERVATIONS

Hypotheses to adjudicate. Not defects. Several may be wrong, already owned, or fully compensated.
C1-C12 lean against the proposal; C13-C16 lean for it. Weight them equally (see the Symmetry
requirement).

- C1. The proposal reverses two ratified decisions (CD.20/dec-111, CD.21/dec-112), invalidates
  completed tier item T2.10's exit criteria, and has a second-order effect on Decision 68.
- C2. The stated cost premise ("private was unaffordable") may invert once F10 is established: the
  current billed amount and the post-flip billed amount may not stand in the assumed relation.
- C3. The wake substrate's three mechanisms may all be push-triggered on job COMPLETION, leaving a
  queued-but-never-started job with no notifying mechanism.
- C4. CD.38 designates GitHub Actions as the sole verifier for the future executor; runner
  availability may therefore be load-bearing for the autonomous loop, not only for human PRs.
- C5. Controls named in `AGENTS.md` as live (F35) may lapse at the visibility flip while the assertion
  persists -- the defect class ULF-01 named.
- C6. The `tf-gated-apply` Environment is the authorization boundary for IAM/trust/destroy applies; if
  Environments with required reviewers are unavailable on the target plan, that boundary may have no
  equivalent. Decision 89 (F34) may describe the precedent.
- C7. A shared PySR box may not deliver the modelled speedup, and CI may degrade the PySR workload
  reciprocally.
- C8. `validate.py` may be a narrower portability boundary than "single entrypoint" implies (F4).
- C9. The OIDC trust conditions reference `refs/heads/agent/*` while live sessions use `claude/*`
  (F28, READ FIRST item 4); the relationship between these is undetermined.
- C10. A persistent runner holding AWS authority and executing Dependabot-updated dependencies may
  lose the per-job disposability property the hosted arrangement provides.
- C11. If operational data value flows into code, prompts, and contracts, the code may increasingly
  encode the asset -- which may cut either way on the visibility decision.
- C12. `main-canary` at 3-hour cadence (F12) may represent a large share of total CI usage that the
  stated baseline did not separate out.
- C13. Repository contents already reach external model providers by design (F40); the visibility
  flip may therefore close a smaller share of the exposure surface than assumed -- OR the remaining
  share it does close may still be the one that matters. Adjudicate which.
- C14. Going private may REDUCE ongoing engineering burden: the public-content boundary currently
  imposes a standing cost (the `never-commit` pre-commit hook, the account-id scrubbing in the
  speculative-plan job, Decision 101 review load on every artifact). That burden may shrink.
- C15. A self-hosted runner may unlock capabilities the hosted tier cannot offer at any price:
  no per-job time limit, large persistent caches, more memory, faster full-tier feedback, and the
  ability to run the currently-excluded `integration`-marked tests.
- C16. The ~$35/mo historical figure for the retired EC2 runner (F39) is for CLOUD-hosted hardware
  billed 24/7; owned hardware has a different cost structure, and the comparison may favour the
  proposal more than the retirement of the EC2 runner suggests.

## EMPIRICAL PASS

Ground the economics and timing claims in observation, within hard bounds.

**Sampling caps -- do NOT exceed:**
- At most 3 calls to list workflow runs, at most 30 runs each.
- At most 5 calls to `get_workflow_run_usage`.
- At most 2 calls to any repository-settings or billing endpoint.
- At most 8 external documentation fetches total (see EXTERNAL EVIDENCE).
- Do not download workflow logs.

Tag every finding `evidence_kind`: `static` (file inspection), `observed` (sampled artifact), or
`external` (published third-party documentation). **At equal severity, `observed` outranks `static`.**

Counterfactual per sample: **does this observation survive if my assumption about it is wrong?** For
the billing observation specifically: a zero value may mean not-billed, or may mean not-reported by
that endpoint. Distinguish these before building an argument on it.

Degraded paths: if the Actions API is unavailable, set `meta.degraded_empirical = true`, downgrade
affected findings to `HYPOTHESIS`, proceed. If a billing or settings endpoint returns 403 or is
otherwise unauthorized for the audit credential, that is NOT an audit failure -- record it in
`meta.access_limitations`, derive what you can from the run-usage endpoint and static sources, and
proceed. Never abort.

## EXTERNAL EVIDENCE

Q5, Q6, Q10, and DD-A depend on GitHub's CURRENT published documentation -- plan feature matrices,
Actions pricing and included-minutes allowances, GHAS availability on private repositories,
self-hosted-runner guidance, and any pricing announcement relevant to premise P1. None of this is in
the repository, and all of it changes over time.

**Use `WebFetch` and/or `WebSearch`** to consult primary sources -- prefer `docs.github.com` and
official GitHub changelog/blog posts over third-party summaries. Cap: 8 fetches total.

Record every external claim as a finding or answer with `evidence_kind: external` and an
`evidence` value of the form `<publisher> | <page title or doc path> | <URL> | retrieved <date>`.

**Degraded path -- if web access is unavailable or a fetch fails:** do NOT abort and do NOT answer
from training knowledge as though it were verified. Set `meta.degraded_external = true`, mark every
affected finding and question verdict `confidence: HYPOTHESIS`, state explicitly in the affected
`prose` field which claims could not be verified and what the answer would be under each plausible
version of the facts, and proceed. A question answered on unverified plan-tier facts must SAY so.

## METHOD

Execute in order. Synthesis and maturity are always LAST.

- **P1 Read.** Read `AGENTS.md` in full first -- it is the architecture. Then `docs/PROJECT_CONTEXT.md`,
  the seven surfaces, and every anchor in the GROUNDING MAP. Record non-resolving anchors.
- **P2 Trace.** For each candidate C1..C16, trace the behaviour to file:line, a sampled artifact, or
  an external source. Discard, confirm, or reclassify each.
- **P3 Deep-dive.** Execute DD-A, DD-B, DD-C.
- **P4 Empirical + external.** Run the EMPIRICAL PASS and EXTERNAL EVIDENCE within their caps.
- **P5 Rate.** Fill the rubric, every dimension for every surface. Populate `migration_benefits[]`.
- **P6 Dedup.** Apply DEDUP DISCIPLINE to every candidate finding before it is filed.
- **P7 Adversarial review to convergence.** See below. Mandatory.
- **P8 Synthesize.** Answer Q1..Q12, compute severity, then compute maturity last.

## ADVERSARIAL REVIEW (MANDATORY -- P7)

Before finalising, subject your own findings to adversarial review and iterate until convergence.
You are structurally the wrong judge of your own reasoning; this phase corrects for that.

**Dispatch.** Spawn a subagent as an adversarial reviewer, with repository read access. Give it the
finding set (id, title, evidence, severity, confidence, reasoning), the `migration_benefits[]`
entries, the question verdicts, and this instruction -- and NOTHING about which items you are
confident in or worried about, as that biases the read:

> You are an adversarial reviewer. Your job is to REFUTE, not to confirm. For each item below --
> findings, claimed migration benefits, and question verdicts alike -- attempt to demonstrate it is
> wrong, overstated, already compensated by a control the author missed, or dependent on a premise
> that does not hold. Verify claims against the repository yourself. Default to "refuted" where you
> are uncertain.
>
> Then check for bias in BOTH directions, and report whichever you find:
> (a) Is any conclusion driven by the requester's stated preference for going private, rather than
>     by evidence?
> (b) Is any conclusion driven by the audit brief having enumerated more risks than benefits --
>     i.e. a no-go reached by counting problems rather than by weighing them? Is the benefit side
>     argued as rigorously as the risk side, or is it thin?
>
> Output, per item: id, verdict `stands | overstated | refuted`, one line of reasoning, and the
> evidence you checked. Then a short bias section covering (a) and (b) separately.

**Iterate.** Apply the results: move refuted items to `rejected_candidates[]` (recording the
refutation), downgrade overstated ones in severity or confidence, and revise any question verdict
whose basis changed. Then re-dispatch a FRESH adversarial reviewer against the revised set -- a
revision that fixes one item can introduce another, and a reviewer that has already seen your
reasoning is no longer adversarial.

**Convergence criterion.** Converged when a round returns zero `refuted` and zero `overstated`
verdicts AND raises no bias finding. **Round cap: 3.** If not converged after 3 rounds, stop, keep
the surviving items, mark each unconverged item `confidence: HYPOTHESIS` and
`adversarial_verdict: unconverged`, and record the unresolved disagreement in
`meta.unconverged_items` with one line each.

**Record.** Set `meta.adversarial_rounds` to the number of rounds actually dispatched, and
`meta.adversarial_refuted_count` to the total refuted across all rounds.

**If dispatch fails:** retry once. If it fails again, set `meta.adversarial_rounds: 0`,
`meta.adversarial_status: "dispatch-failed"`, mark every finding `adversarial_verdict: not-reviewed`,
downgrade every `CONFIRMED` finding to `HYPOTHESIS`, and note it in `meta.contract_notes`. This is a
DEGRADED but shippable run -- the `.md` report must say so in its opening paragraph. Do not silently
skip the phase and do not abort.

**Anti-pattern.** Do not tell the reviewer which items you consider strong. Do not reuse a
reviewer's context across rounds. Do not treat silence as agreement.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces. A finding without a recorded negative
search is a `HYPOTHESIS`, not a `CONFIRMED` defect.

**Ownership surfaces to search -- all five:**
1. `docs/ROADMAP-PLATFORM.yaml` -- `tier_items[]` and `candidate_decisions[]`. Use a
   `bin/venv-python -c` `yaml.safe_load` projection; do NOT read the file whole.
2. `docs/ROADMAP-PLATFORM.yaml` -- the `cost_model` block, for any cost finding (see DD-A).
3. `docs/DECISIONS.md` -- grep `^## Decision` headers, then read only matching entries.
4. **`docs/DECISIONS_ARCHIVE.md`** -- same grep. Superseded decisions live ONLY here; Decision 68 is
   one of them (F42). Omitting this surface produces false negatives.
5. `logs/.recommendations-log.jsonl` -- grep. Records use the key `id` (not `rec_id`), with `title`,
   `status`, and `context`.

Record on every finding: `dedup_search_terms` (terms actually searched), `dedup_hit_count`, and
`item_ids` for any owning item. A hit means you assess SUFFICIENCY of the existing remedy, or reject
the candidate -- never that you file a fresh discovery.

**Known prior coverage you must engage with, not rediscover:** CD.20/dec-111, CD.21/dec-112, CD.32,
CD.38, tier item T2.10, Decision 68 (archive), Decision 83, Decision 89, and audit finding ULF-01.

### Deliberate constraints -- DO NOT FLAG

Each is a decided position. Flag one only if the MIGRATION specifically breaks it, and say so.

- The executor freeze and STRATEGIC-plan suspension (Decision 67).
- `signal-green` and `terraform-converged` being advisory rather than required checks (Decision 83 --
  a required check would wedge autonomous fix-merges).
- `prevent_self_review = false`, `required_approving_review_count = 0`, and admin `bypass_mode =
  "always"` (Decision 83 / sole-developer repository).
- `strict_required_status_checks_policy = false` (Decision 76 squash-merge flow).
- `terraform/github/**` never being auto-applied (Decision 77).
- The absence of `required_signatures` (Decision 83's minimal-ruleset posture; rationale recorded at
  `terraform/github/repo.tf:112-117`).
- `terraform/ec2_runner.tf` being retained on disk (CD.21 / T2.10 exit criteria).
- The retirement of the `send_later` backstop (`AGENTS.md` "Push -> PR -> CI -> merge flow" step 4,
  resting on Decision 76/83's event-driven wake design). Q4 explicitly REOPENS this as a question, so
  assessing it there is in scope; flagging its original retirement is not.

## OUTPUT

Write exactly two files. `<sha>` is the short SHA of the audited base commit, identical in both
filenames and in `meta.audited_commit`.

### `audits/private-repo-self-hosted-ci-<sha>.yaml`

```yaml
audit:
  meta:
    audited_commit: <origin/main short sha>
    base_branch: main
    model: <your self-reported model name, free text>
    methodology_version: 1
    scope_surfaces: [S-VIS, S-RUNNER, S-CI, S-WAKE, S-GOV, S-SEC, S-CRED]
    degraded_dedup: false
    degraded_empirical: false
    degraded_external: false
    access_limitations: []          # endpoints that refused or were unauthorized
    assumed_inputs:                 # every unstated input you had to assume
      - {input: "", assumed_value: "", why: "", sensitivity: ""}
    adversarial_rounds: 0
    adversarial_status: completed|converged|round-capped|dispatch-failed
    adversarial_refuted_count: 0
    unconverged_items: []
    premises_tested:                # P1, P2 from REQUESTER CONTEXT
      - {id: P1, holds: true|false|unverified, evidence: "", effect_on_answers: ""}
    contract_notes: ""              # read by the human reviewing the PR; also surfaced in the .md
    stale_anchors: []
  question_answers:
    # GENERIC shape -- Q2, Q4, Q5, Q6, Q7, Q8, Q10, Q11:
    - {q: Q2, verdict: <that question's pinned enum>, basis: [<finding ids>], prose: ""}
    # Q1 shape (per-intent ratings plus a headline):
    - q: Q1
      per_intent:
        - {intent: I-A, verdict: recommend-private|recommend-public|recommend-conditional,
           preconditions: [], rationale: ""}
        # exactly four entries, I-A..I-D
      headline: {verdict: recommend-private|recommend-public|recommend-conditional,
                 assumed_intent: I-A|I-B|I-C|I-D, intent_inference_evidence: "", preconditions: []}
      adversary_model: {adversaries: [], assets: [], channels: [],
                        channels_closed_by_flip: [], channels_not_closed: []}
      basis: [<finding ids>]
      prose: ""
    # Q3 shape (verdict PLUS the external checklist):
    - q: Q3
      verdict: sufficient|partial|insufficient
      external_checklist:
        - {property: "<one of the 10 named practices>", rating: met|partial|missed, evidence: ""}
        # exactly ten entries
      basis: [<finding ids>]
      prose: ""
    # Q9 shape (verdict PLUS a license recommendation):
    - {q: Q9, verdict: worth-doing|not-worth-doing|moot,
       license_recommendation: keep-apache-2.0|change-to-<named>|dual-license,
       license_rationale: "", basis: [], prose: ""}
    # Q12 shape (answers list, NO verdict):
    - {q: Q12, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
  intent_dependencies:
    - {question: Q1..Q12, flips_on: [I-A, I-B, I-C, I-D], conclusion_under_each: "",
       what_the_requester_must_decide: ""}
  migration_benefits:
    # REQUIRED block. Evidence the migration IMPROVES something. Same rigor as findings.
    # If genuinely empty, write [] and say why in summary.benefits_note -- do not omit the key.
    - id: BEN-01
      surface: <surface|shared>
      title: ""
      claim: ""
      evidence: "file:line|item-id|external-citation"
      evidence_kind: static|observed|external
      magnitude: "<what it is worth, in money, time, or capability>"
      confidence: CONFIRMED|HYPOTHESIS
      adversarial_verdict: stands|overstated-and-revised|unconverged|not-reviewed
  per_surface_assessment:
    - {surface: S-VIS, maturity: frontier|strong|solid|nascent, strengths: "",
       top_gaps: [<finding ids>], top_benefits: [<benefit ids>]}
    # This is the SOLE system of record for maturity. summary.maturity_* MUST equal these values.
  rubric_ratings:
    - {surface: S-VIS, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id|external-citation", note: ""}
  migration_plan:
    - {step: 1, action: "", changes: "", reversible: true|false, rollback: "",
       preconditions: [], abort_criterion: "", lockout_risk: ""}
  findings:
    - id: PRIV-01                   # PRIV-NN, zero-padded, assigned in filing order,
                                    # contiguous in the FINAL set (renumber after adversarial
                                    # review so there are no gaps from refuted items)
      surface: S-VIS|S-RUNNER|S-CI|S-WAKE|S-GOV|S-SEC|S-CRED|shared
      question: Q1..Q12             # the PRIMARY question this serves
      also_serves: []               # any additional question ids
      dimension: VD1..VD7
      title: ""
      evidence: "file:line|item-id|external-citation"
      evidence_kind: static|observed|external
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref:
        classification: novel|planned-insufficient|planned-unbuilt
        item_ids: []
        dedup_search_terms: []
        dedup_hit_count: 0
        note: ""
      effort: XS|S|M|L
      depends_on: []
      sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}
      adversarial_verdict: stands|overstated-and-revised|unconverged|not-reviewed
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    total_benefits: 0
    benefits_note: ""
    top_improvements: []            # finding ids; [] is legal when findings is empty
    highest_leverage_change: ""     # a finding id, or "" when findings is empty
    go_no_go: recommend-private|recommend-public|recommend-conditional
                                    # MUST equal question_answers Q1 headline.verdict
    maturity_S_VIS: ""              # MUST equal per_surface_assessment
    maturity_S_RUNNER: ""
    maturity_S_CI: ""
    maturity_S_WAKE: ""
    maturity_S_GOV: ""
    maturity_S_SEC: ""
    maturity_S_CRED: ""
```

**Enum definitions** (so you need not invent them):

- `effort` -- estimated implementation work for one competent engineer: `XS` under 1 hour;
  `S` 1 hour to 1 day; `M` 1 to 3 days; `L` more than 3 days.
- `change_type` -- `add` (new control/mechanism where none exists); `rescope` (change what an
  existing mechanism covers); `enforce` (make an advisory mechanism binding); `unify` (collapse
  duplicate mechanisms); `persist` (durably record something currently ephemeral); `clarify`
  (documentation or wording only, no behaviour change); `retune_gate` (adjust an existing gate's
  threshold or routing without changing its scope).

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list of PROBLEMS.
`total_findings = len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`.
`migration_benefits[]` is separately counted as `total_benefits` and is NEVER added to
`total_findings`. Fully-covered or refuted candidates live in `rejected_candidates[]`.
`rubric_ratings`, `question_answers`, `migration_plan`, `intent_dependencies`, and
`per_surface_assessment` are systems-of-record referenced FROM findings, never re-counted.
`top_improvements` and `highest_leverage_change` MUST be finding ids when findings exist.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why the control would
FAIL if the defect were real.

`CONFIRMED` requires the behaviour traced to file:line, an observed sampled artifact, or a cited
external source. Anything less is `HYPOTHESIS`.

### `audits/private-repo-self-hosted-ci-<sha>.md`

Prose companion, <= ~1500 words. Lead with the Q1 go/no-go and the intent dependency. Then the
ranked findings with severity and effort, the benefits, the cost picture from DD-A, and the
migration sequence. If any `meta` degraded flag is set or `adversarial_status` is not `converged`,
say so in the opening paragraph. Reference finding ids; no YAML dump.

## SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class. Never inherit it from this prompt's framing or
from the order in which candidates were listed.

- **critical** -- the migration as proposed can produce an irreversible or trust-destroying outcome:
  a lockout with no recovery path, a silent lapse of a control the platform asserts is live, or an
  unbounded expansion of authority on an untrusted host.
- **high** -- a weakness that materially reduces a guarantee the platform depends on, AND whose
  compensating controls you judged insufficient.
- **medium** -- redundancy, ambiguity, or inconsistency with a clear fix.
- **low** -- clarity or wording.

**Compensating-control property-match rule.** A control lowers severity or justifies dismissal ONLY
if it exercises the SAME property AND would FAIL if the defect were real. Apply the counterfactual
to the control itself. A control that cannot catch the break neither lowers severity nor justifies
dismissal -- say so explicitly rather than silently discounting it.

**Maturity.** Compute LAST, per surface, top-down, first match wins. "Open" means present in the
final `findings[]` for that surface; items in `rejected_candidates[]` do not count. A
`HYPOTHESIS`-confidence finding DOES count toward its severity tier -- uncertainty is not an
exemption; if that drives a rating you consider unfair, say so in the `note`.

- **frontier** -- 0 open critical and 0 open high findings on that surface, AND (S-RUNNER only)
  every property in Q3's `external_checklist` rated `met` or `partial`, never `missed`.
- **strong** -- 0 critical and <= 1 high.
- **solid** -- <= 1 critical.
- **nascent** -- otherwise.

The top rating remains reachable where you argued a property-matched compensating control. Nothing
in this prompt's framing forecloses it.

## SETUP

Permitted setup, run once at the start:

```bash
git fetch origin main
git rev-parse --short origin/main          # this IS your audited base
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

The preflight populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`, which
DEDUP DISCIPLINE depends on. These are gitignored caches; never commit them.

**Degraded paths -- never abort, never improvise:**

- IF cache-gen fails (credentials or egress down): set `meta.degraded_dedup = true`, mark every
  `roadmap_crossref` `confidence: HYPOTHESIS` and `dedup_hit_count: null`, proceed.
  `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`, and `docs/DECISIONS_ARCHIVE.md` are on disk and
  remain searchable regardless.
- IF the GitHub Actions API is unavailable: `meta.degraded_empirical = true`, downgrade affected
  findings to `HYPOTHESIS`, proceed on static evidence.
- IF a billing or settings endpoint is unauthorized: record in `meta.access_limitations`, derive what
  you can from other sources, proceed. Not an audit failure.
- IF web access is unavailable or a fetch fails: `meta.degraded_external = true`; see EXTERNAL
  EVIDENCE for the full degraded contract. Do not answer plan-tier questions from training knowledge
  as though verified.
- IF an anchor in the GROUNDING MAP does not resolve: record in `meta.stale_anchors`, re-derive the
  fact yourself, proceed.
- IF an unstated input is required: follow the unstated-input rule in PROPOSED HARDWARE AND WORKLOAD
  and record it in `meta.assumed_inputs`.
- IF adversarial dispatch fails: see ADVERSARIAL REVIEW's dispatch-failure contract.
- IF `bin/venv-python -m scripts.validate --pre` fails for a reason unrelated to your two deliverables:
  record it in `meta.contract_notes` and proceed. Do NOT fix it -- that breaches the write boundary.
  Repo-wide validation is advisory outside CI here; a clean YAML parse of your two deliverables is
  the real pre-push gate.

## COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main`, then `git rev-parse --short origin/main`. That
   commit IS the audited tree. Use its short SHA in both deliverable filenames, in the branch name,
   and in `meta.audited_commit`.
2. `git switch -c audit/private-repo-self-hosted-ci-<sha> origin/main` so the PR diff contains only
   your two deliverable files. This is a deliberate, documented exception to the `AGENTS.md`
   `claude/*` session-branch rule: the audit needs a clean two-file diff off the audited base.
3. Verify both deliverables parse (YAML-load the `.yaml`) before pushing.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, and commit message:
   `audit(private-repo-self-hosted-ci): audit findings`
5. `git push -u origin HEAD`.
6. Open the PR via `mcp__github__create_pull_request`: `base=main`, ready for review (not draft),
   title `audit: private-repo migration with self-hosted CI (visibility, runner, CI, wake, governance, security, credentials)`,
   body = a 2-3 sentence lede plus the `summary` block in a yaml fence.
7. **END YOUR TURN.** Do not poll. Do not merge. Do not self-approve. **Do not call
   `subscribe_pr_activity`** -- this is a deliberate exception to the `AGENTS.md` PR flow, which
   normally mandates it. The audit session's job ends at PR creation; the human disposes.

## GUARDRAILS

**Write boundary -- a closed list.** The only files you create or modify in the repository tree are:

1. `audits/private-repo-self-hosted-ci-<sha>.yaml`
2. `audits/private-repo-self-hosted-ci-<sha>.md`

Regenerating gitignored caches under `logs/` per SETUP is expected and is not a breach; never commit
them. Do not fix a failing check. Do not edit a workflow, a Terraform file, `AGENTS.md`, a decision,
or the roadmap. Do not file recommendations through the ops portal. Do not implement any change you
recommend.

**Honesty clauses.**

- **Fewer than ~8 surviving findings is a valid result. State it plainly and do not pad.** A short,
  correct audit is worth more than a long one padded to look thorough.
- **Precision over volume.** One traced, adversarially-survived finding outranks five plausible ones.
- **A run that merely confirms this prompt's candidates has failed.** The candidate list is a
  starting set, and several entries may be wrong.
- **Argue both directions with equal rigor.** The requester has expressed a clear wish to go private;
  that wish is context, not evidence. This prompt enumerates more risks than benefits; that asymmetry
  is an artifact of compose-time recon, not a prior. If the evidence supports the migration, say so
  as directly as you would say the opposite. Your adversarial reviewer is instructed to look for
  BOTH preference-driven reasoning and problem-counting reasoning -- do not give it either.
- **Where a conclusion depends on intent you cannot determine, branch -- do not guess and do not
  stall.** Record it in `intent_dependencies` with the conclusion under each intent scenario, and
  say plainly what the requester must decide. You cannot ask; the session ends with a PR.
