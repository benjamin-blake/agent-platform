# AUDIT: git-ops procedures for an agent-first repository

## TASK

Audit this repository's git-ops procedures for fitness in an agent-first repository, and answer
one decisive question: should `main` remain squash-merged? The requester's working hypothesis is
that squash-merge is a human convenience that may be a barrier to efficient log recovery for
agents; treat that as a hypothesis to test, not a conclusion to confirm. Six surfaces are in
scope: the merge-strategy and branch-protection policy, the commit-message contract, the
mechanisms that consume git history, clone and checkout depth, the parallel provenance stores,
and the PR wake-signal machinery. Answer Q1..Q8 below, rate every surface against VD1..VD6,
and file findings. Deliverables: exactly two files, `audits/gitops-agent-first-<sha>.yaml` and
`audits/gitops-agent-first-<sha>.md`, where `<sha>` is the short SHA of `origin/main` derived in
COMMIT / PR MECHANICS. The ONLY files you create or modify in the repository tree are those two
deliverables; regenerating gitignored local caches per SETUP is expected and does not breach this
(never commit them). You draft; the human disposes. Do not implement any change you recommend.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts. Every candidate
in CANDIDATE OBSERVATIONS is a neutral observation that may turn out to be a defect, a deliberate
trade-off, or a non-issue.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.**

Adjudicate each candidate to exactly one outcome:

- **CONFIRMED defect**, not owned by any existing roadmap item, decision, or open recommendation
  -> `findings[]`, `roadmap_crossref.classification: novel`.
- **Owned by an existing item, but that item's remedy is insufficient for the defect as you
  traced it** -> `findings[]`, classification `planned-insufficient`.
- **Owned by an existing item whose remedy is adequate but unbuilt** -> `findings[]`,
  classification `planned-unbuilt`.
- **Owned and fully covered**, or **not a defect** -> `rejected_candidates[]`, naming the
  compensating control or owning item id.

**A run that merely confirms the candidates below has failed.** The candidates are a starting
set, deliberately including observations that are probably fine. Your value is in the
adjudication and in what you find that is not listed.

## READ FIRST: disambiguation traps

1. **"Squashed history" names two different things in this repository, and conflating them
   destroys the audit.** (a) The squash-merge POLICY: one commit on `main` per merged PR.
   (b) The SHALLOW CLONE: the Claude-Code-on-the-web container clones with limited depth
   (`.git/shallow` is present). `docs/ROADMAP-PLATFORM.yaml:474` and
   `audits/legacy/wave-1-outputs/A1.yaml:5` both say "squashed clone" where the referent is the
   shallow clone, not the merge policy. Q3 exists specifically to separate these two causes.
   Verify which one you are reasoning about at every step.
2. **`AGENTS.md` has two sections that look like the same thing.** `## Git-ops procedure`
   (`AGENTS.md:169`) is the canonical authority. `## Merge protocol` (`AGENTS.md:242`) opens by
   pointing at it. Audit the former; treat the latter as a pointer surface whose only defect
   class is drift.
3. **`merge=union` in `.gitattributes` is not a merge-method.** It is a conflict-resolution
   strategy for `*.jsonl` files. It has no bearing on Q1.
4. **One unit of work is two PRs, not one.** The flow produces a `plan({slug})` commit and then
   a separate `feat({slug})` commit on `main`. Any reasoning of the form "one commit per unit of
   work" is wrong; it is one commit per PR, two PRs per unit of work.
5. **Squash-merge and GitHub-native auto-merge are orthogonal axes.** Auto-merge concerns who
   presses merge; the merge method concerns what lands. Do not let one answer the other.
6. **`required_linear_history = true`** (`terraform/github/repo.tf:110`) means merge commits are
   currently forbidden by the ruleset. A merge-commit recommendation therefore carries a
   Terraform ruleset change as a cost; a rebase-merge recommendation does not.
7. **A green `pr-conflict-signal` run does not mean a wake was delivered.** The poll step carries
   `continue-on-error: true`. Reason about the step's internal failure counter, not the run
   conclusion.
8. **In a shallow clone, the oldest present commit reports every file it touches as newly added.**
   `git show --stat <boundary-commit> -- <path>` returns a full-file insertion count regardless of
   the file's real history, because the parent is grafted away. Verify the boundary
   (`cat .git/shallow`, `git log --reverse`) before drawing any conclusion from a `--stat`,
   `git log -- <path>`, or "when was this last changed" query. This trap will actively mislead you
   on S5 file-history questions if you do not guard against it.

## SCOPE

Six surfaces, all BUILT unless marked otherwise. Obtain every file, line, and count by reading
the file yourself -- **trust no number quoted in this prompt; re-derive from the repository** and
record any anchor that does not resolve in `meta.stale_anchors`.

- **S1 merge-strategy-and-protection** -- `AGENTS.md:169-241`, `terraform/github/repo.tf`,
  Decision 76 (`docs/DECISIONS.md:4861`), Decision 89 (`docs/DECISIONS.md:5269`), Decision 83.
- **S2 commit-message-contract** -- the subject-prefix table (`AGENTS.md:190-198`), the
  `Resolves:` trailer rule (`AGENTS.md:235-241`), `scripts/rec_trailer.py`.
- **S3 history-shape-consumers** -- `scripts/checks/_common.py` `push_context_base()`,
  `.github/workflows/rec-autoclose.yml`,
  `scripts/checks/verification/validate_vp_replay.py`,
  `scripts/checks/verification/validate_graduation_completeness.py`,
  `scripts/roadmap/plan_audit.py` `_verify_rec_in_git()`,
  `scripts/convergence_health/record.py` `count_unapplied_tf_commits()`,
  `scripts/ops_portal/ci_rca_lifecycle.py` `_ensure_ancestry_history()` / `classify_closed_head()`.
- **S4 clone-and-checkout-depth** -- the container clone's shallow state; `fetch-depth` settings
  across `.github/workflows/`.
- **S5 parallel-provenance-stores** -- `docs/plans/PLAN-*.yaml`, `docs/DECISIONS.md`,
  `ops_recommendations` (DuckLake, SCD2), `docs/SESSION_LOG.md`, `audits/`, telemetry tables.
  Assess as a provenance SUBSTRATE relative to git history; do not audit their internal schemas.
- **S6 wake-signal-machinery** -- `ci.yml`'s `signal-green` job,
  `.github/workflows/pr-conflict-signal.yml`, `scripts/ci/pr_conflict_signal.sh`,
  `scripts/checks/ci_guards/validate_pr_conflict_signal.py`.

**Out of scope, one line each.** Terraform apply model and deploy channels (own contracts).
The recommendation/decision portal's internal write semantics. The executor freeze (Decision 67).
Repository secrets policy. CI check content beyond the git-shape coupling. Anything requiring an
AWS write.

**Vocabulary.** *Log recovery* = an agent reconstructing what changed, why, and in what order,
from repository-local state. *Wake signal* = a comment posted to a PR to resume a session that
ended its turn. *History shape* = the commit topology and per-commit granularity of `main`.
*Parallel provenance store* = any durable record of change rationale that is not git history.
*Human-ergonomic residue* = a convention whose justification is human reading habit rather than
machine consumption.

## SETUP

Run these, in order, before anything else:

```
git fetch origin main
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`, both of which
DEDUP DISCIPLINE depends on. Both are gitignored caches; never commit them.

**Degraded paths -- never abort, never improvise:**

- IF cache-gen fails (creds or egress down): do NOT abort -- set `meta.degraded_dedup=true`, mark
  every `roadmap_crossref` `confidence=HYPOTHESIS` and `dedup_hit_count=null`, proceed.
- IF `git fetch origin main` fails: set `meta.contract_notes` to record it, use local `origin/main`
  as-is, and note in `meta.stale_anchors` that base derivation is unverified.
- IF an anchor quoted in this prompt does not resolve: record it in `meta.stale_anchors`, locate
  the referenced construct by name (grep for the function/section/setting), and proceed. A stale
  line number is never a reason to skip a surface.
- IF a repo-wide validation command fails for reasons unrelated to your deliverables: record it in
  `meta.contract_notes` and proceed. **Never fix it** -- that breaches the write boundary.
- IF the GitHub API is unavailable for the EMPIRICAL PASS: set `meta.contract_notes` accordingly,
  mark affected findings `evidence_kind: static`, proceed.

## NORTH STAR

The bar to judge each surface against. These are principles you ARGUE with, not rules you
pattern-match; a surface may justifiably depart from one.

- **NS1 Agent-first artefacts.** Every artefact is optimised for agent loading efficiency, not
  human readability. Machine-parseable beats narrative. Where two designs are equally valid and
  one is more machine-parseable, the machine-parseable one wins.
- **NS2 Durable operational data is the source of truth.** Provenance belongs in a queryable,
  durable store. A record that exists in two stores has a drift surface.
- **NS3 Traceability end to end.** Work selection -> authority -> agent action -> independent
  verification -> deployment -> observed outcome -> next improvement should be reconstructible.
- **NS4 Fail loud, never silent.** A mechanism that degrades to a wrong-but-plausible answer is
  worse than one that fails visibly.
- **NS5 Enforce what you rely on.** A machine-readable shape that load-bearing code parses should
  be validated, not left to convention.
- **NS6 Bounded cost.** Recovery that requires an unbounded scan, a network round-trip per item,
  or a full-history fetch is a cost an agent pays on every session.

## THE QUESTIONS

**Q1 -- Should `main` remain squash-merged?**
Assess squash-merge, rebase-merge, merge-commit, and any hybrid keyed on PR class, judged on
agent recoverability and the NORTH STAR, not on human convenience or convention. Populate the
`merge_strategy_decision` block with one entry per candidate strategy. Verdict enum for the
question: `keep-squash` | `switch-to-rebase-merge` | `switch-to-merge-commit` |
`hybrid-by-pr-class`.

**Q2 -- What must git history carry that the parallel provenance stores cannot carry better?**
S5 already holds plans, decisions, recommendations (with SCD2 history), session logs, audits, and
telemetry. Determine what an agent genuinely needs from git history itself, given those stores
exist. Verdict enum: `git-log-load-bearing` | `partially-load-bearing` | `git-log-redundant`.

**Q3 -- Premise tests.** Two premises underlie the request. Test both; report each explicitly.
- **Q3a**: is the SHALLOW CLONE, rather than the merge strategy, the binding constraint on agent
  log recovery? Verdict enum: `shallow-clone-dominant` | `squash-dominant` | `both-material` |
  `neither-material`.
- **Q3b**: are agents in fact the sole consumer of this repository's git log? Consider the human
  who disposes of every PR, and that the repository is PUBLIC with an explicit "market the
  engineering" posture (Decision 101). Verdict enum: `agents-sole-consumer` |
  `agents-primary-humans-secondary` | `genuinely-dual-consumer`. This verdict CONSTRAINS Q6: an
  agent-first-only optimisation is only free where the human-reader claim on that surface is
  weak, so state the dependency in your Q6 prose rather than assuming it away.

**Q4 -- Is the coupling to history shape essential or accidental, and is the commit-message
contract enforced?**
For each S3 mechanism, determine whether it needs the current history shape or merely assumes it,
and what it does when the assumption breaks. Separately assess whether the S2 contract is
adequately enforced for something load-bearing code parses. Verdict enum for the question:
`sufficient` | `partial` | `insufficient`. Record per-mechanism coupling as findings or in the
rubric.

**Q5 -- Is the wake-signal machinery reliable, and does the Q1 answer change its design?**
The requester reports `pr-conflict-signal` as unreliable in practice. Trace the delivery path
end to end for both signals and determine where a wake can be lost, whether a loss is observable,
and whether any Q1 outcome changes what these signals must do. Verdict enum: `reliable` |
`reliable-but-unobservable` | `unreliable-bounded` | `unreliable-unbounded`.

**Q6 -- What should an agent-first repository take FROM industry practice, and what should it
deliberately discard or invent?** *(headline question)*
This is NOT "what is industry best practice?" Many viable git-ops practices exist, and most
carry design pressure from human readers -- review ergonomics, `git log` scanability, bisect
workflows performed by a person. The question is: given the Q3b answer, which industry
conventions are substrate-level requirements that survive any consumer, which are
human-ergonomic residue an agent-first repository should discard, and which structures become
available that would be unnatural for humans but efficient for agents?

Assess EVERY practice in the checklist below, one entry each, in the
`industry_adaptation` field of this question's `question_answers` entry. Pinned per-practice
enum: `adopt-as-is` | `adapt-for-agents` | `discard-human-ergonomic` | `already-in-place` |
`n/a`. Each entry states the practice, the enum value, what specifically it would look like in
an agent-first form, and its evidence. This field is the SOLE source the maturity top tier reads.

**Checklist**: trunk-based development; linear history; Conventional Commits; commit trailers as
structured key-value metadata; `git notes` as detachable machine-readable annotation; PR-as-record
vs commit-as-record; bisectability; revertability; SLSA-style provenance and build attestation;
branch hygiene and post-merge branch deletion; CI checkout-depth strategy (shallow vs full vs
on-demand deepening); merge queues; auto-merge; signed commits; monorepo change-scoping
conventions.

Beyond the checklist, name any structure the checklist does not cover that becomes available once
the primary reader is a machine -- for example, machine-readable commit bodies, structured
trailers carrying plan/rec/decision ids, or annotation stores decoupled from commit messages.
Argue the cost as well as the benefit; a structure that is efficient for agents but unrecoverable
after a history rewrite is not free.

**Q7 -- Is git log history a suitable substitute for a traditionally human-oriented session log?**
`docs/SESSION_LOG.md` is a narrative, human-oriented "lab notebook for inter-session continuity".
Determine what a session log carries that a commit log structurally cannot (and vice versa),
whether the gap is inherent to git or an artefact of current commit-body conventions, and whether
an agent-first repository should retire the narrative log in favour of git plus the other S5
stores, keep both with a clear division, or replace both with something else. Consider: what a
session log records that never becomes a commit (abandoned approaches, RCA reasoning, failed
attempts, human decisions taken in chat); the write-cost and drift-cost of a hand-maintained
narrative; and whether the `ops_session_log` table changes the answer. Note the interaction with
Q6 -- if commit bodies can carry structured machine-readable content, the substitutability
question changes shape. Verdict enum: `git-log-sufficient-substitute` |
`git-log-sufficient-if-commit-contract-changes` | `complementary-keep-both` |
`neither-suitable-replace-both`.

**Q8 -- Questions the requester did not think to ask.**
Answer AND extend these seeds:
- Does the two-PR flow (`plan(` then `feat(`) belong in git at all, or is it an artefact of using
  PRs as the handoff mechanism?
- What happens to reconstructability if a merged PR's branch is deleted and GitHub's PR record
  becomes the only holder of the pre-merge commits?
- Does the `(#NNN)` PR-number suffix constitute adequate provenance indirection, given resolving
  it costs a network round-trip (NS6)?
- Is there a git-ops failure mode that only manifests when multiple agent sessions run
  concurrently against `main`?
- Should the merge method be declared in infrastructure-as-code at all?

## RUBRIC

Rate every surface S1..S6 on every dimension. Pinned enum: `strong` | `adequate` | `weak` |
`absent` | `n/a`. **`n/a` is correct and costless where a dimension does not structurally apply
-- never manufacture a rating or a finding to fill a cell.**

- **VD1 Machine-recoverability** (NS1, NS6) -- can an agent reconstruct what changed and why from
  repository-local state, without a network round-trip per item?
- **VD2 Contract enforcement** (NS5) -- is the machine-readable shape this surface relies on
  validated by a gate, or left to convention?
- **VD3 Coupling essentiality** (NS1) -- does this surface depend on the current history shape by
  necessity, or by unexamined assumption?
- **VD4 Degradation behaviour** (NS4) -- under a shallow clone, a missing commit, or a masked
  failure, does the surface fail loudly or return a plausible wrong answer?
- **VD5 Provenance source-of-truth hygiene** (NS2, NS3) -- is the record stored once in the right
  store, or split and duplicated across stores that can drift?
- **VD6 Human-ergonomic residue** (NS1) -- is this surface's shape justified by agent consumption,
  or inherited from human convention with no agent-facing justification? `strong` = no
  unjustified residue.

## DEEP-DIVES

**DD-A -- End-to-end trace of the four history-shape dependencies.** *(feeds Q1, Q4)*
For each of `push_context_base()` (`HEAD~1` plus `fetch-depth: 2`), `rec-autoclose`'s
`git log -1 --format=%B HEAD`, the `feat({slug})` subject resolution in `validate_vp_replay` and
`validate_graduation_completeness`, and `plan_audit._verify_rec_in_git`'s
`git log origin/main --grep=`: state what breaks under each Q1 candidate strategy, whether the
break is loud or silent, and whether a cheap decoupling exists. This trace is the blast-radius
evidence for Q1 -- do not answer Q1 without it.

**DD-B -- The `Resolves:` trailer delivery path.** *(feeds Q1, Q4)*
`AGENTS.md:236` places the trailer in the squash-merge COMMIT body. `.claude/skills/implement/SKILL.md:547`
places it in the PR body "which the squash-merge commit body inherits". Two open recommendations
(rec-2679, rec-2733) describe a loss mode for single-commit PRs. Determine the actual GitHub
behaviour, whether the two instructions are equivalent in all cases, whether the existing
recommendations' remedies are the right fix, and whether a merge-strategy change would obviate,
worsen, or leave them unchanged. **Explicitly re-assess those two recommendations rather than
dismissing them as owned territory** -- the requester wants to know whether their proposed
remedies still make sense with the merge-strategy question open. Record the re-assessment
outcome in `rejected_candidates` or as a `planned-insufficient` finding, as your trace warrants.

**DD-C -- Wake-signal delivery paths.** *(feeds Q5)*
Trace both signals from trigger to delivered comment. For `signal-green`: which checks gate it
(`ci.yml:303`), which PR-triggered checks exist that are not in that list, and what a watching
session concludes from a comment that arrives before an omitted check finishes. For
`pr-conflict-signal`: enumerate every point where a wake can be lost, and determine whether a
loss is observable given the step's `continue-on-error: true` and the script's internal failure
counter and exit code. Include the case of a PR that is already conflicted at creation time,
when no subsequent push to `main` occurs.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. **Verify each anchor before relying on
it**; anchors rot, and a stale line number goes in `meta.stale_anchors`, not into a finding.
Facts below are stated neutrally and carry no verdict.

**S1 merge-strategy-and-protection**
- `AGENTS.md:169` `## Git-ops procedure` is declared canonical authority; `AGENTS.md:242`
  `## Merge protocol` opens by deferring to it.
- `AGENTS.md:230` step 5 specifies `merge_pull_request(..., merge_method="squash")`.
- Decision 76 (`docs/DECISIONS.md:4861`) records the squash-merge policy as preserved from
  Decision 89 with the transport changed to the GitHub MCP; it also lists GitHub-native
  auto-merge as a deferred follow-up.
- Decision 89 (`docs/DECISIONS.md:5269`) clause 4 states all merges must be squash merges.
- `terraform/github/repo.tf:110` sets `required_linear_history = true`.
- `terraform/github/repo.tf:39-44` lists `allow_merge_commit`, `allow_squash_merge`,
  `allow_rebase_merge`, `allow_auto_merge`, and `delete_branch_on_merge` inside the
  `lifecycle.ignore_changes` block.
- `terraform/github/repo.tf:105-107` sets `strict_required_status_checks_policy = false` with an
  inline comment citing the Decision 76 squash-merge flow.
- The `main_protection` ruleset requires two checks: `pr-validate` and `terraform-validate`.

**S2 commit-message-contract**
- `AGENTS.md:190-198` defines subject prefixes: `feat({slug})`, `plan({slug})`, `roadmap({ids})`,
  `scope({slug})`, `audit({slug})`.
- `AGENTS.md:235-241` defines the `Resolves: rec-NNNN[, rec-MMMM]` trailer and states it triggers
  `rec-autoclose.yml`.
- `scripts/rec_trailer.py` `parse_resolves_trailer()` is a pure regex parser, case-insensitive on
  keyword and token, matching `rec-<digits>`.
- `.claude/skills/implement/SKILL.md:547` instructs placing the trailer in the PR body.
- A repository-wide search for a commit-message conformance check in `scripts/checks/` returned no
  such check. Re-derive this; a negative result is itself a fact to verify.

**S3 history-shape-consumers**
- `scripts/checks/_common.py:40` `push_context_base()` prefers `GITHUB_EVENT_BEFORE`, else
  `HEAD~1`; returns `None` with a warning when `HEAD~1` does not resolve.
- `fetch-depth: 2` appears at `.github/workflows/ci.yml:96`,
  `.github/workflows/main-canary.yml:22`, and `.github/workflows/rec-autoclose.yml:23`.
- Decision 159 (`docs/DECISIONS.md:608`) clause 1 attributes `fetch-depth: 2` to the "squash
  convention, Decision 76"; clause 5 records as an accepted residual that "a multi-commit direct
  push under-selects with `HEAD~1` (Decision 76 squash assumption)".
- `.github/workflows/rec-autoclose.yml` runs `git log -1 --format=%B HEAD` on push to `main` and
  passes the result to `parse_resolves_trailer`.
- `scripts/checks/verification/validate_vp_replay.py:10-17` resolves plan slugs from `feat({slug})`
  commit subjects on `git log origin/main..HEAD`;
  `scripts/checks/verification/validate_graduation_completeness.py:21` uses the same resolution.
- `scripts/roadmap/plan_audit.py:126` `_verify_rec_in_git()` runs
  `git log --oneline origin/main --grep=<rec-id>`.
- `scripts/convergence_health/record.py:105` `count_unapplied_tf_commits()` carries the docstring
  "Returns 0 on any error (record SHA may predate the current clone depth)" and returns 0 inside a
  bare `except`.
- `scripts/ops_portal/ci_rca_lifecycle.py:151` `_ensure_ancestry_history()` runs a best-effort
  `git fetch --unshallow origin`; its docstring states that an unresolvable `merge-base
  --is-ancestor` causes `classify_closed_head` to misfile a stale-code rerun as a regression, and
  that the function is never a hard dependency.
- `.github/workflows/ci-rca.yml:77-83` uses `fetch-depth: 0` with a comment describing it as
  belt-and-suspenders alongside that code-level guard-fetch.

**S4 clone-and-checkout-depth**
- The Claude-Code-on-the-web container clone has `.git/shallow` present; at the time of recon
  `git rev-list --count origin/main` returned 50. Re-derive both.
- All 50 commits carried a `(#NNN)` suffix, spanning PRs #841 to #891 -- one commit per merged PR
  across the whole window.
- Subject-prefix distribution in that window: 25 `feat(`, 21 `plan(`, 1 each `fix(`, `docs(`,
  `audit(`.
- `fetch-depth` settings across workflows range from `1` (`claude.yml`) through `2` to `0`
  (`ci.yml` PR job, `ci-rca.yml`, `convergence-health.yml`).
- `docs/ROADMAP-PLATFORM.yaml:474` records an artefact whose "provenance [is] unrecoverable from
  the squashed clone".
- `cat .git/shallow` returns the grafted boundary; the oldest commit PRESENT is its child. At
  recon, `git show --stat <oldest-present-commit> -- docs/SESSION_LOG.md` reported 666 insertions
  for a file that predates the clone window. This is the trap in READ FIRST item 8; it is also a
  concrete instance to weigh under VD4 for S4.

**S5 parallel-provenance-stores**
- `docs/plans/PLAN-{slug}.yaml` documents are merged to `main` by their own PR before the
  implementing PR.
- `ops_recommendations` is DuckLake-backed with SCD2 history and named-verb reads; `ops_decisions`
  rebuilds from `docs/DECISIONS.md`.
- `rec-autoclose.yml` also stamps `fixed_by_sha` onto closed `ci_rca` recommendations, creating a
  git-SHA reference held in the warehouse.
- `audits/` and the telemetry tables are additional durable records.
- AGENTS.md's warehouse invariant states local files are never upstream of the warehouse.
- `docs/SESSION_LOG.md` was 666 lines at recon; `docs/SESSION_LOG_ARCHIVE.md` was 1565. Its header
  describes it as a "Lab notebook for inter-session continuity", states entries "are written by
  `session_close` at the end of each session", that "`task_start` reads the last 5 entries", and
  that "`strategic_review` archives entries when the log exceeds 20 entries".
- At recon, `.github/prompts/` contained only a `scheduled/` subdirectory; no `session_close`,
  `task_start`, or `strategic_review` prompt file was found in the tree. AGENTS.md's
  `## Instruction architecture` section records that "the legacy top-level
  `.github/prompts/*.prompt.md` and `.github/agents/*.agent.md` files were deleted at T-1.13".
  Re-derive both facts; determine for yourself what currently writes this file, if anything.
- The newest `## [date]` entry heading in `docs/SESSION_LOG.md` was `2026-07-01` at recon. Compare
  against the date range of the commits present on `main` and draw your own conclusion.
- Roadmap item T-1.9 "Session-log architecture audit + redesign" has status `complete`. AGENTS.md's
  warehouse-invariant section lists `ops_session_log` as an Athena-backed table "pending T2.26
  disposition" and notes "session_log may retire per T-1.9". T2.26 status is `in_progress`.
- Sampled squash-commit bodies on `main` carry multi-paragraph, multi-bullet narrative content
  (see for example the body of the oldest commit present in a shallow clone). Read several before
  forming a view on what a commit body can and does carry here.

**S6 wake-signal-machinery**
- `ci.yml:293-322` `signal-green` posts a "CI green" comment; `ci.yml:303` gates it on
  `needs: [pr-validate, terraform-validate]`; it is scoped to `claude/*` head refs and carries
  `continue-on-error: true` with a 3-attempt retry loop.
- An inline comment at `ci.yml:294-297` states the invariant that any future `pull_request`-
  triggered check must be added to that `needs` list, and that cross-workflow needs are
  unsupported.
- `pr-conflict-signal.yml` triggers on push to `main` and `workflow_dispatch`; its single poll
  step carries `continue-on-error: true` and delegates to `scripts/ci/pr_conflict_signal.sh`.
- That script sets `set -uo pipefail; set +e`, uses `_gh_bounded_retry` with 5 mergeable-poll
  attempts and 3 retry attempts elsewhere, increments `_FAILURE_COUNT` via `_signal_failure`
  (which also writes to `GITHUB_STEP_SUMMARY`), and ends with `exit 1` when `_FAILURE_COUNT > 0`.
- On a comments-read failure the script posts the wake anyway, with the stated rationale that a
  duplicate wake is cheap and a missed wake strands a session.
- `scripts/checks/ci_guards/validate_pr_conflict_signal.py` enforces structural invariants on the
  workflow, including anchored delegation and per-call-site exit-status capture.
- At recon, `pr-conflict-signal.yml` had 246 total runs and the 15 most recent all reported
  `conclusion: success`.

**Governing decisions and contracts**: Decision 76 (CC-web workflow, squash policy), Decision 83
(branch protection live), Decision 89 (CI as merge gate), Decision 101 (public boundary),
Decision 159 (push-context diff base), Decision 162 (delegate-script call-site discipline),
Decision 55/72/129 (forward-fix), `docs/contracts/instruction-architecture.yaml`.

## EMPIRICAL PASS

Sample real artefacts; observed findings outrank static ones at equal severity. **Hard bounds --
do NOT exceed:**

- **<= 40** most recent `origin/main` commits: check subject-prefix conformance, `(#NNN)` presence,
  and `Resolves:` trailer presence and well-formedness. Tag `evidence_kind: observed`.
- **<= 15** most recent `pr-conflict-signal.yml` runs and **<= 15** most recent `ci.yml` runs, via
  the GitHub API. For the conflict signal, determine whether any run's step summary or log carries
  a `[PR-CONFLICT-SIGNAL] FAILURE` marker while the run conclusion is `success`.
- **<= 10** merged PRs: check whether the PR body's `Resolves:` trailer reached the `main` commit
  body, and record the PR's commit count (this is the discriminator for the DD-B loss mode).
- **<= 8** `docs/plans/PLAN-*.yaml` with non-empty `bundled_recommendations`: check whether the
  named recommendations are closed.

**Counterfactual test, applied per sample**: for any mechanism you judge to be working, ask
"would this sample still look identical if the mechanism were deleted or silently no-opping?"
If yes, the sample is not evidence that it works. Apply this specifically to `rec-autoclose`
(a recommendation may be closed by a manual portal call rather than the trailer) and to
`pr-conflict-signal` (a green run with no conflicted PRs in the window is not evidence of
delivery).

## METHOD

- **P1 Read.** Every S1..S6 surface. Verify anchors; record stale ones.
- **P2 Trace.** DD-A and DD-B. Establish the blast radius before forming any Q1 opinion.
- **P3 Trace.** DD-C.
- **P4 Premise test.** Q3a and Q3b. Both premises must be settled before Q6, because Q3b
  constrains what Q6 may recommend.
- **P5 Empirical.** The sampling above, within bounds.
- **P6 Rate.** VD1..VD6 across S1..S6.
- **P7 Dedup.** Per DEDUP DISCIPLINE, before any finding is filed.
- **P8 Synthesize.** Answer Q1..Q8, populate `merge_strategy_decision`, then compute maturity
  LAST.

## DEDUP DISCIPLINE

Before filing ANY finding, search the ownership surfaces and record the result on the finding:

- `docs/ROADMAP-PLATFORM.yaml` -- `tier_items[]` and `candidate_decisions[]`.
- `docs/DECISIONS.md` -- `^## Decision` headers.
- `logs/.recommendations-log.jsonl` -- open recommendations.

Record `dedup_search_terms` and `dedup_hit_count` on every finding. **A hit means
sufficiency-assessment or `rejected_candidates`, never a fresh discovery.** A finding with no
recorded negative search is `confidence: HYPOTHESIS`.

**Known nearby owners** (verify status; do not assume):
`rec-2679` (open) trailer-in-PR-body does not survive squash-merge for single-commit branches;
`rec-2733` (open) squash-merge of single-commit PRs drops the trailer, no-opping rec-autoclose;
`rec-2022` (open) signal-green wake gate omits the codeql analyze check;
`rec-3046` (open) extend signal-green to `agent/` branches;
`rec-3067`/`rec-3068`/`rec-3069`/`rec-3070`/`rec-3071` (open) call-site guard, duplicate wake
comment, brittle capture regex, literal-argv coverage, inherited-errexit roster;
`rec-2019`/`rec-2020`/`rec-2021` (open, Low) signal-green documentation and env-binding;
`rec-2735` (closed) the exit-status defect that produced the current script;
`rec-940` (closed) PR auto-merge; `rec-2827` (open) no-auto-merge-protected-path contract;
`audits/workflow-review-d107b4a.yaml:560` records the AGENTS.md/SKILL.md trailer-placement drift.
Note that rec-2679 and rec-2733 are explicitly re-opened for re-assessment by DD-B -- their
existence is NOT a reason to skip that trace.

**Deliberate constraints -- DO NOT FLAG as defects:**

- Squash-merge policy, event-driven CI wake, and the no-polling rule (Decision 76). You may
  RECOMMEND changing the merge method under Q1 -- that is the audit's purpose -- but do not file
  the policy's existence as a defect in itself.
- The `main-protection` ruleset's deliberate minimality: admin `bypass_mode = "always"`,
  `strict_required_status_checks_policy = false`, `required_approving_review_count = 0`, and the
  explicit absence of `required_signatures` (Decision 83; the code comment states "do not add").
- Forward-fix, never auto-revert (Decision 55/72/129).
- The harness-assigned `claude/*` session branch model -- not repository-changeable.
- The `send_later` / trigger backstop retirement (AGENTS.md) and the CC-web permission gotcha.
- The executor freeze and IMPLEMENTATION-only planning (Decision 67).
- The public-repository content boundary (Decision 101).
- `continue-on-error: true` on wake-signal steps as a design intent (a wake must never red a
  build). Its OBSERVABILITY consequences are in scope; its existence is not a defect.

## OUTPUT

Write exactly two files.

`audits/gitops-agent-first-<sha>.yaml`:

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: keep-squash|switch-to-rebase-merge|switch-to-merge-commit|hybrid-by-pr-class,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: git-log-load-bearing|partially-load-bearing|git-log-redundant,
       basis: [], prose: ""}
    - {q: Q3a, verdict: shallow-clone-dominant|squash-dominant|both-material|neither-material,
       basis: [], prose: ""}
    - {q: Q3b, verdict: agents-sole-consumer|agents-primary-humans-secondary|genuinely-dual-consumer,
       basis: [], prose: ""}
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q5, verdict: reliable|reliable-but-unobservable|unreliable-bounded|unreliable-unbounded,
       basis: [], prose: ""}
    - {q: Q6, verdict: <one-line thesis>, basis: [], prose: "",
       industry_adaptation:
         - {practice: <checklist entry or newly named structure>,
            rating: adopt-as-is|adapt-for-agents|discard-human-ergonomic|already-in-place|n/a,
            agent_first_form: "", evidence: ""}}
    - {q: Q7, verdict: git-log-sufficient-substitute|git-log-sufficient-if-commit-contract-changes|complementary-keep-both|neither-suitable-replace-both,
       basis: [], prose: ""}
    - {q: Q8, answers: [{question: "", answer: "", basis: []}]}
  merge_strategy_decision:
    squash: {verdict: recommended|viable|rejected, mechanism: "", what_changes: "", cost: "",
             rationale: "", confidence: CONFIRMED|HYPOTHESIS}
    rebase_merge: {verdict: ..., mechanism: "", what_changes: "", cost: "", rationale: "",
                   confidence: ...}
    merge_commit: {verdict: ..., mechanism: "", what_changes: "", cost: "", rationale: "",
                   confidence: ...}
    hybrid: {verdict: ..., mechanism: "", what_changes: "", cost: "", rationale: "",
             confidence: ...}
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: GITOPS-01, surface: S1..S6|shared, question: Q1..Q8, dimension: VD1..VD6,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "",
       severity: critical|high|medium|low, severity_rationale: "",
       confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [], highest_leverage_change: <id>,
            maturity_S1: <value>, maturity_S2: <value>, maturity_S3: <value>,
            maturity_S4: <value>, maturity_S5: <value>, maturity_S6: <value>}
```

`audits/gitops-agent-first-<sha>.md`: prose companion, **<= 1500 words**, the executive layer a
human reads first. Lead with the Q1 answer and its reasoning, then Q6's thesis, then the findings
that matter. Do not restate the YAML.

**COUNTING INVARIANT**: `findings[]` is the SOLE enumerated list.
`total_findings = len(findings) = novel_count + planned_insufficient_count +
planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates`, NOT findings.
`rubric_ratings`, `question_answers`, and `merge_strategy_decision` are systems-of-record
referenced FROM findings, never re-counted. `top_improvements` and `highest_leverage_change`
MUST be finding ids.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates (mechanism or `file:line`), and
state why the control would FAIL if the defect were real.

`CONFIRMED` requires the behaviour traced to a `file:line` or an observed sampled artefact.
Anything less is `HYPOTHESIS`.

## SEVERITY AND MATURITY

Assign severity AFTER judgment, by defect class. Never inherit severity from this prompt's
framing or from a candidate's position in the list.

- **critical** = an agent can reach a wrong-but-trusted conclusion about repository history or
  work state, or an irreversible act (merge, close, deploy) proceeds on an unsound signal.
- **high** = a weakness that materially reduces recoverability or signal reliability AND whose
  compensating controls you judged insufficient.
- **medium** = redundancy, ambiguity, drift, or inconsistency with a clear fix.
- **low** = clarity or wording.

**Property-match rule for compensating controls**: a control lowers severity or justifies
dismissal only if it exercises the SAME property AND would FAIL if the defect were real. Apply
the counterfactual to the control itself. A control that cannot catch the break neither lowers
severity nor justifies dismissal.

**Maturity**, computed LAST, per surface, top-down, first match wins:

- **frontier** = 0 open critical AND 0 open high findings on that surface, AND every entry in
  Q6's `industry_adaptation` field that bears on that surface is rated `adopt-as-is`,
  `adapt-for-agents`, `already-in-place`, or `n/a` -- never left unassessed.
- **strong** = 0 critical AND <= 1 high.
- **solid** = <= 1 critical.
- **nascent** = otherwise.

`frontier` remains reachable where you argued a property-matched compensating control. A
`discard-human-ergonomic` rating is NOT a maturity penalty -- it is a recommendation, and a
surface can be frontier while carrying one.

## COMMIT / PR MECHANICS

1. Derive the base ONCE:
   ```
   git fetch origin main
   git rev-parse --short origin/main
   ```
   This base IS the audited tree. Use that sha in both deliverable filenames, the branch name,
   and `meta.audited_commit`.
2. `git switch -c audit/gitops-agent-first-<sha> origin/main` so the PR diff contains only the
   two deliverables. This is a deliberate, documented exception to the `claude/*` session-branch
   rule: the audit needs a clean two-file diff off the audited base.
3. Repository-wide validation is advisory outside CI here. The real pre-push gate is a clean YAML
   parse of your two deliverables:
   ```
   bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/gitops-agent-first-<sha>.yaml
   ```
   An unrelated `validate --pre` failure is recorded in `meta.contract_notes`, never fixed.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`. Then
   `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, NOT a
   draft), title:
   `audit: git-ops procedures for an agent-first repo (merge strategy, commit contract, history consumers, clone depth, provenance stores, wake signals)`
   Body: a 2-3 sentence lede plus the `summary` block in a yaml fence.
6. **END THE TURN.** Do not poll, do not merge, do not subscribe, do not self-approve. The human
   disposes of the PR.

## GUARDRAILS

- **Write boundary, closed list**: `audits/gitops-agent-first-<sha>.yaml` and
  `audits/gitops-agent-first-<sha>.md`. Nothing else in the repository tree. Do not fix a defect
  you find. Do not update AGENTS.md, a workflow, a check, or a recommendation. Do not file a
  recommendation through the ops portal.
- **Precision over volume.** Fewer than ~8 surviving findings is a valid result -- state it
  plainly and do not pad. A thin findings list with a well-argued Q1 and Q6 is a better outcome
  than a padded one.
- **Do not confirm the frame.** The requester believes squash-merge may be harming agents. If the
  evidence does not support that, say so directly and explain what the evidence does support.
  A well-evidenced `keep-squash` verdict is a full success.
- Every rating and verdict must trace to evidence you read in this session. Where you could not
  verify, say `HYPOTHESIS` and explain what would settle it.
- No emojis. Plain ASCII, ASCII hyphens only.
