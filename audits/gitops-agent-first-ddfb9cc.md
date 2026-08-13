# Git-ops for an agent-first repository -- audit at ddfb9cc

Companion to `audits/gitops-agent-first-ddfb9cc.yaml`. 7 findings (5 novel, 1
planned-insufficient, 1 planned-unbuilt), 4 rejected candidates, all 18 candidates adjudicated.

## Q1: keep squash-merge (CONFIRMED)

The requester's hypothesis -- that squash-merge is a human convenience taxing agent log recovery
-- does not survive the two-sided trace. The evidence supports the opposite framing: squash is
the shape the machine consumers are built to, and the thing actually taxing log recovery is the
shallow clone (Q3a below).

Cost of changing (DD-A): the squash shape is load-bearing in the diff base
(`push_context_base()`'s `HEAD~1` fallback under `fetch-depth: 2`, pinned by a guard in
`verify_ci_workflow.py` whose failure message names Decision 159), in `rec-autoclose`'s
single-commit trailer read, in the trailer-inheritance path for single-commit PRs, and in the
`session_start_sync_main.sh` rationale. Rebase-merge would introduce two silent failure classes
-- multi-commit diff under-selection and trailer loss (no new commit message is ever composed at
a rebase-merge) -- to buy intra-PR granularity that no consumer reads. Merge-commit is forbidden
by `required_linear_history`; unwinding that is a reviewed, CODEOWNERS-gated Terraform change
whose only concrete payoff is fixing a dormant executor-era branch predicate (GITOPS-04), far
cheaper to fix in code. A hybrid puts two history shapes on one `main` so every consumer meets
both, permanently.

Cost of keeping (DD-D, traced with equal weight): sampled pre-merge sequences run 1-4 commits
per PR, dominated by CI fixups whose narrative already lands in PR disclosures. The full
sequences survive server-side -- 894 `refs/pull/*/head` refs, verified fetchable (six fetched,
shallow boundary re-checked unmoved) -- and nothing in-repo fetches or bisects today. I tested
that "nothing" against the absence-of-need vs absence-of-capability distinction: with rationale
provenance dense in plans, decisions, recs, and PR bodies, and with every `main` commit a
CI-green reviewed unit (a *better* bisect/revert substrate than individually-untested
intermediate commits), I judge it mostly absence of need.

One practice deserves naming because it decided several questions: **squash commit bodies here
are hand-composed at merge time**. The body of `84f9209` (#887) is a 23-line condensed summary
that is neither the PR body nor the branch commits; `aa20689` (#888) carries a `Resolves:`
trailer that exists in no branch commit. The merging agent writes an explicit `commit_message`.
That makes `main` a sequence of PR-grain condensed records -- a genuinely agent-first structure
-- and it is documented nowhere, while `implement/SKILL.md:547` actively misdescribes the
mechanism as PR-body inheritance (empirically false; the rec-2679/rec-2733 incidents were
exactly agents following that instruction literally).

## Q3 premises

**Q3a: shallow-clone-dominant.** The container window is 50 commits spanning nine days. Beyond
it, local history queries return confident wrong answers: reproduced live -- `git log --
docs/SESSION_LOG.md` locally attributes the file to boundary commit `5bd32ea` with a 666-line
insertion, while PR #844's real file list (API) is six files, none of them that one.
`count_unapplied_tf_commits` silently returns 0; rec greps false-negative anything older than
the window. Squash costs intra-PR grain; the shallow clone costs *everything* past nine days.
The remedy is cheap and has an obvious home: the session-start hooks already fetch `origin
main` every session, and `ci_rca_lifecycle.py` already deepens on demand -- a bounded
`--deepen` hook retires the whole class. Filed as **GITOPS-03 (high; the
highest-leverage change in this audit)**.

**Q3b: agents-primary-humans-secondary.** A human disposes of every PR, and the repository is
public with an explicit market-the-engineering intent (Decision 101). This constrained Q6: no
convention was discarded merely for being human-legible, because the human reader is real.

## Q6 thesis

Keep the trunk-linear-squash substrate and PR-as-record; enforce the commit grammar machines
already parse; deepen the dev clone; adopt auto-merge; skip notes, SLSA, merge queues;
formalize composed squash bodies and wake-comment IPC as validated contracts.

The full 15-practice checklist plus three named novel structures is in the YAML. The pattern it
shows: this repository has already *invented* the interesting agent-first structures --
merge-time-composed commit bodies, and PR comments as a wake-IPC channel with HTML idempotency
markers -- and its residual weakness is uniform: conventions that load-bearing code parses but
nothing validates (the grammar, the trailer, the merge method itself).

## Findings that matter

- **GITOPS-03 (high, novel)** -- shallow clone yields wrong-but-trusted local history; add a
  session-start bounded deepen. Observed evidence; independent of the merge-strategy verdict.
- **GITOPS-01 (medium, planned-insufficient)** -- the trailer's real delivery path (explicit
  `commit_message` at merge) is folklore; SKILL.md documents the lossy path; rec-2679/rec-2733's
  remedies are right and unbuilt, while the workflow-review audit's CE-11 proposes reconciling
  the drift *toward* the wording this audit falsified. DD-B's re-assessment: keep both recs,
  redirect CE-11, add post-merge trailer validation for bundled-rec plans.
- **GITOPS-06 (medium, novel)** -- the merge method every consumer depends on is UI-mutable
  with zero Terraform diff (`allow_*` in `ignore_changes`; the ruleset still permits
  rebase-merge). Declare it in `terraform/github/repo.tf`. Q8.5 answers: yes, it belongs in IaC.
- **GITOPS-05 (medium, novel)** -- a PR conflicted at creation gets no wake (no trigger), and a
  lost wake is invisible (the script's `exit 1` is masked by `continue-on-error`; 249 runs all
  conclude success). Bounded in practice by push cadence -- the latest run correctly
  idempotent-skipped live-conflicted PR #781 -- but the stranded corner terminates only in a
  human nudge. Extend triggers to `pull_request [opened, reopened]`; surface the failure count.
- **GITOPS-02 (medium, novel)** -- the subject grammar (`feat({slug})` etc.) is parsed by VP
  replay and graduation gates yet nothing enforces it, and the registered table omits live
  prefixes (`fix(`, `docs(`). C4 re-derived: still exactly one bare subject in the window.
- **GITOPS-07 (medium, planned-unbuilt)** -- `SESSION_LOG.md` has had no writer since
  2026-07-01 (the writer path is not invoked by any live command) while preflight still feeds
  its six-week-stale entries to every planning session. T-1.9 already designed the retirement;
  the reader-rewire slice is the unbuilt half. Q7 verdict: neither the markdown log nor
  `ops_session_log` is suitable -- replace both, per T-1.9's own design, with warehouse
  turn-events; git alone cannot substitute because no-commit sessions (the 2026-07-01
  remediation entry is one) leave no trace in any commit body.
- **GITOPS-04 (low, novel)** -- `branch_lifecycle`'s merged-branch predicate
  (`merge-base --is-ancestor`) is structurally false under squash; dormant while the executor
  is frozen; fix or excise before any T4.2 thaw. Only a merge-commit policy would satisfy the
  predicate as written -- not a reason to change the policy.

## Q5: wake machinery -- unreliable-bounded

Both signals were traced end to end. The losses are real but bounded: every push-covered loss
self-heals on the next push to main (~5.5/day observed), the conflict script's
duplicate-cheap/missed-wake-expensive bias is correctly chosen, and the empirical window shows
the machinery working. The unbounded corners are GITOPS-05's two. C11 (signal-green omits
codeql) was **rejected**: the comment claims only that *required* checks passed, which is true
by the ruleset's deliberate minimality; rec-2022 tracks the enhancement. No Q1 outcome changes
the wake design; GitHub-native auto-merge (decided, unblocked, unbuilt) retires the green wake
but can never subsume the conflict wake.

## Sequencing

All seven findings are safe to queue now. Suggested order: GITOPS-03 (one hook, retires a
failure class), GITOPS-06 (one Terraform declaration via the module's human-gated runbook),
GITOPS-01 (doc unification + validation), GITOPS-05, GITOPS-02, GITOPS-07, GITOPS-04.

Maturity: S2/S3 frontier; S1/S4/S5/S6/S7 strong (notes in the YAML explain each cap). Nothing
in scope is nascent; the git-ops layer is in good shape, and its defects cluster on one theme
-- enforce what you rely on.
