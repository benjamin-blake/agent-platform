# AUDIT: git-ops procedures for an agent-first repository

## TASK

Audit this repository's git-ops procedures for fitness in an agent-first repository, and answer
one decisive question: should `main` remain squash-merged? The requester's working hypothesis is
that squash-merge is a human convenience that may be a barrier to efficient log recovery for
agents; treat that as a hypothesis to test, not a conclusion to confirm. Seven surfaces are in
scope: the merge-strategy and branch-protection policy, the commit-message contract, the
mechanisms that consume git history, clone and checkout depth, the parallel provenance stores,
the PR wake-signal machinery, and the session/branch-lifecycle hooks. Answer all ten questions below (Q1, Q2, Q3a, Q3b, Q4, Q5, Q6,
Q6b, Q7, Q8 -- Q3 is split into two, and Q6b sits between Q6 and Q7), rate every surface against
VD1..VD6,
and file findings. Deliverables: exactly two files, `audits/gitops-agent-first-<sha>.yaml` and
`audits/gitops-agent-first-<sha>.md`, where `<sha>` is the short SHA of `origin/main` derived in
COMMIT / PR MECHANICS. The ONLY files you create or modify in the repository tree are those two
deliverables; regenerating gitignored local caches per SETUP is expected and does not breach this
(never commit them). You draft; the human disposes. Do not implement any change you recommend.

## ADJUDICATION CONTRACT: candidates vs verdicts

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts. Every entry in
the CANDIDATE OBSERVATIONS section that follows is a neutral observation that may turn out to be
a defect, a deliberate trade-off, or a non-issue.

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

## CANDIDATE OBSERVATIONS

C1..C18 are the candidate set the adjudication protocol above operates on. Each is a neutral
observation, verified on disk at compose time. **None is a defect until you trace it.** Several
are expected to resolve to `rejected_candidates`. This list is not exhaustive -- findings outside
it are welcome and are the clearest evidence the run added value.

- **C1** (S1, S3) -- `main` carries exactly one commit per merged PR across the sampled window.
  Four mechanisms read that shape: `HEAD~1`, a single `git log -1` commit body, `feat({slug})`
  subject resolution, and a `--grep` over subjects.
- **C2** (S4) -- the development container's clone is shallow. Two consumers handle this
  explicitly (`_ensure_ancestry_history` deepens on demand; `count_unapplied_tf_commits` returns
  0 on error); others do not visibly handle it.
- **C3** (S2) -- the `feat({slug})` / `plan({slug})` subject convention is parsed by load-bearing
  checks, and no check validates conformance to it.
- **C4** (S2) -- at recon exactly one commit subject in the window did not carry a
  `prefix(scope)` form: `audit: decision / contract / change-record content routing and
  prior-intervention erosion (S1-S5) (#864)`, which uses a bare `audit:` with no parenthesised
  slug. Re-derive over the CURRENT window (which will be larger) and count how many
  non-conforming subjects exist now; determine whether this is a violation, an unregistered valid
  form, or immaterial.
- **C5** (S2, S3) -- three surfaces state where the `Resolves:` trailer belongs, in
  non-identical terms (AGENTS.md, `implement/SKILL.md`, `.github/pull_request_template.md`).
- **C6** (S2, S3) -- two open recommendations (rec-2679, rec-2733) describe a trailer loss mode
  for single-commit PRs. DD-B re-assesses them; do not treat their existence as closing the
  question.
- **C7** (S1) -- the merge-method repository settings sit in Terraform's `ignore_changes` list,
  so the live merge method is not declared in infrastructure-as-code.
- **C8** (S1) -- `required_linear_history = true` constrains which merge methods are available
  without a Terraform change; `require_code_owner_review = true` plus `.github/CODEOWNERS`
  scopes `/terraform/github/` behind code-owner review.
- **C9** (S3, and a COST-OF-KEEPING candidate -- see the balance note below) --
  `scripts/executor/branch_lifecycle.py` decides whether a branch is merged via
  `git merge-base --is-ancestor <branch> main`. Squash-merge creates a NEW commit that the branch
  is not an ancestor of. Determine what that predicate therefore returns for an already-merged
  branch TODAY, what the `git branch -d` cleanup behind it does as a result, and what each
  alternative strategy would return. Also determine whether the code path is currently reachable
  given the executor freeze (a dormant path changes severity, not correctness). Cross-check
  against the remote branch count in DD-D's anchors.
- **C10** (S5) -- `docs/SESSION_LOG.md` names `session_close` / `task_start` /
  `strategic_review` as its writer and readers; the newest entry predates the sampled commit
  window. Determine what currently writes it, if anything.
- **C11** (S6) -- `signal-green` gates on two checks; other `pull_request`-triggered checks exist
  in the repository. Determine whether a "CI green" comment can precede an omitted check's
  completion, and what a watching session does with that.
- **C12** (S6) -- the conflict-signal step carries `continue-on-error: true` while its script
  exits non-zero on internal failure. Determine whether a failed wake is observable to anyone.
- **C13** (S6) -- the conflict signal triggers on push to `main`; a PR conflicted at creation
  time with no subsequent push to `main` is a case to trace.
- **C14** (S4, S5) -- in a shallow clone, history queries against files older than the clone
  window return confident, wrong answers (see trap 9). Determine which in-repo consumers are
  exposed to this and whether any of them would notice.
- **C15** (S1, S5) -- the ordered sequence of commits an implementing session made within a PR is
  not present on `main`; `main` carries their squashed result. Determine where, if anywhere, that
  sequence survives, what an agent loses by not having it locally, and whether anything needs it.
- **C16** (S1) -- resolving a `main` commit to its full PR record (all commits, reviews, CI runs)
  requires a GitHub API round-trip. Determine whether that indirection is adequate provenance or
  a per-item cost an agent pays repeatedly (NS6).
- **C17** (S1, S7) -- merged branches may be deleted after merge. Determine whether the pre-merge
  commits remain reachable afterwards, for how long, and whether anything here depends on them.
- **C18** (S3) -- a bisect over `main` localises to one PR, not to a step within it. Determine
  whether anything in this repository bisects, and what resolution any such consumer needs.

The candidate set is deliberately balanced: C1/C2/C7/C8/C14 bear on the cost of CHANGING the
current strategy, C9/C15/C16/C17/C18 on the cost of KEEPING it. Neither group is the answer; both
are evidence. If you find the set still leans one way, say so in your Q1 prose.

## READ FIRST: disambiguation traps

1. **"Squashed history" names two different things in this repository, and conflating them
   destroys the audit.** (a) The squash-merge POLICY: one commit on `main` per merged PR.
   (b) The SHALLOW CLONE: the Claude-Code-on-the-web container clones with limited depth
   (`.git/shallow` is present). `docs/ROADMAP-PLATFORM.yaml:474` and
   `audits/legacy/wave-1-outputs/A1.yaml:5` ("this clone is a single squashed snapshot commit")
   both use squash wording where the referent is the shallow clone, not the merge policy. Q3a exists specifically to separate these two causes.
   Verify which one you are reasoning about at every step.
2. **Decision 89's TITLE is stale; its clause 4 is not.** Decision 89 is titled "GitHub Branch
   Protection Not Available", a premise Decision 83 reversed (the `main-protection` ruleset is
   live). Its clause 4 is nonetheless cited here as squash-policy authority. Do not read the
   stale title as invalidating the clause, and do not file the stale title as a finding of this
   audit -- it is out of scope. Judge the clause on its merits.
3. **`AGENTS.md` has two sections that look like the same thing.** `## Git-ops procedure`
   (`AGENTS.md:169`) is the canonical authority. `## Merge protocol` (`AGENTS.md:242`) opens by
   pointing at it. Audit the former; treat the latter as a pointer surface whose only defect
   class is drift.
4. **`merge=union` in `.gitattributes` is not a merge-method.** It is a conflict-resolution
   strategy for `*.jsonl` files, and is not itself a Q1 option. One narrow exception: a strategy
   that replays commits individually (rebase-merge) applies the union driver once per commit
   rather than once per PR, so union-merge behaviour IS a legitimate cost input to Q1. Weigh it
   there; do not audit the union strategy itself.
5. **One unit of work is two PRs, not one.** The flow produces a `plan({slug})` commit and then
   a separate `feat({slug})` commit on `main`. Any reasoning of the form "one commit per unit of
   work" is wrong; it is one commit per PR, two PRs per unit of work.
6. **Squash-merge and GitHub-native auto-merge are orthogonal axes.** Auto-merge concerns who
   presses merge; the merge method concerns what lands. Do not let one answer the other.
7. **`required_linear_history = true`** (`terraform/github/repo.tf:110`) means merge commits are
   currently forbidden by the ruleset. A merge-commit recommendation therefore carries a
   Terraform ruleset change as a cost; a rebase-merge recommendation does not. Cost that change fully: `require_code_owner_review = true` (`terraform/github/repo.tf:87`) plus
   `.github/CODEOWNERS` places `/terraform/github/` behind code-owner review, so the ruleset edit
   is itself a reviewed, admin-bypass-logged change -- not a free toggle.
8. **A green `pr-conflict-signal` run does not mean a wake was delivered.** The poll step carries
   `continue-on-error: true`. Reason about the step's internal failure counter, not the run
   conclusion.
9. **In a shallow clone, the oldest commit reachable from a ref reports every file it touches as
   newly added.** `.git/shallow` lists commits whose PARENTS have been grafted away. Those commits
   exist as objects, but NOT all of them are reachable from a ref -- at recon `.git/shallow` held
   two entries and only one was reachable from `origin/main`, so `cat .git/shallow` and
   `git log --reverse origin/main` name DIFFERENT commits. The one that matters for any history
   query is the oldest REACHABLE one: what `git log --reverse origin/main | head -1` returns. Running
   `git show --stat <that commit> -- <path>` returns a full-file insertion count regardless of the
   file's real history, because the diff is taken against nothing. Establish the boundary
   (`cat .git/shallow`, `git log --reverse origin/main`, `git cat-file -t <sha>`) before drawing
   any conclusion from a `--stat`, a `git log -- <path>`, or a "when was this last changed" query.
   This trap will actively mislead you on S5 file-history questions if you do not guard against it.

## SCOPE

Seven surfaces, all BUILT unless marked otherwise. Obtain every file, line, and count by reading
the file yourself -- **trust no number quoted in this prompt; re-derive from the repository** and
record any anchor that does not resolve in `meta.stale_anchors`.

- **S1 merge-strategy-and-protection** -- `AGENTS.md:169-241`, `terraform/github/repo.tf`,
  `.github/CODEOWNERS`, Decision 76 (`docs/DECISIONS.md:4861`),
  Decision 89 (`docs/DECISIONS.md:5269`), Decision 83.
- **S2 commit-message-contract** -- the subject-prefix table (`AGENTS.md:190-198`), the
  `Resolves:` trailer rule (`AGENTS.md:235-241`), `scripts/rec_trailer.py`,
  `.claude/skills/implement/SKILL.md` (trailer placement step), and
  `.github/pull_request_template.md` (the template rendered at PR-open time).
- **S3 history-shape-consumers** -- the inventory below is a STARTING SET, not a closed list.
  Sweep for further consumers yourself (`git log`, `git diff`, `git show`, `rev-list`,
  `merge-base`, `HEAD~`, `HEAD^` across `scripts/`, `.github/workflows/`, AND `.claude/hooks/`)
  and add what you find; DD-A's blast radius is only as good as this set.
  - `scripts/checks/_common.py` `push_context_base()`
  - `.github/workflows/rec-autoclose.yml` (`git log -1 --format=%B HEAD`)
  - `scripts/checks/verification/validate_vp_replay.py`
  - `scripts/checks/verification/validate_graduation_completeness.py`
  - `scripts/roadmap/plan_audit.py` `_verify_rec_in_git()`
  - `scripts/convergence_health/record.py` `count_unapplied_tf_commits()`
  - `scripts/ops_portal/ci_rca_lifecycle.py` `_ensure_ancestry_history()` / `classify_closed_head()`
  - `scripts/executor/branch_lifecycle.py` -- `git merge-base --is-ancestor <branch> main` as a
    merged/not-merged predicate (two call sites, approximately lines 140 and 311). **This is the most
    merge-strategy-sensitive construct in the inventory**; determine what it returns under each
    Q1 candidate, and separately whether the code path is currently reachable given the executor
    freeze (a dormant path changes severity, not correctness).
  - `scripts/ci_rca/vacuous_pass.py` -- `git diff --name-only HEAD^ HEAD`, with a stated
    `fetch-depth: 2` dependency and an `"undetermined"` return on failure
  - `scripts/checks/contracts/_shared.py` -- merge-base `git ls-tree` / `git diff` reads
  - `scripts/checks/decisions/validate_decision_entry_conformance.py` and
    `scripts/checks/decisions/_baseline.py` -- `git show origin/main:<path>` baseline reads
  - `scripts/checks/roadmap/validate_fallback_reevaluation.py`,
    `scripts/checks/roadmap/validate_platform_roadmap.py`
  - `scripts/verify_ci_workflow.py` (approximately line 152) -- asserts
    `main-validate` checkout `fetch-depth == 2`, with the failure message citing "Decision 159:
    HEAD~1 must resolve for the push-context diff base, squash-merge convention". This is the
    guard that pins the squash assumption into CI; it is a direct Q1 cost input.
  - `scripts/checks/contracts/validate_contract_drift.py` (merge-base; advisory SKIP when
    `origin/main` is unreachable)
  - `scripts/checks/roadmap/validate_plan_scope_closure.py` and `scripts/roadmap/plan_obligations.py`
    (net-new plan set derived from a git diff)
  - `scripts/checks/verification/validate_handoff_full_tier.py` (documented degrade to
    `git diff HEAD`), `scripts/test_coverage_checker.py`
  - `scripts/session/postflight.py`, `scripts/session/metrics.py`,
    `scripts/preflight/env_git.py`, `scripts/executor/postflight_gates.py`,
    `scripts/executor/acceptance_lint.py`, and the `scripts/executor/step_commit.py` /
    `step_runner.py` / `ci_triage.py` / `run_summary.py` / `batch_compound.py` group
  Note that a `git show origin/main:<path>` CONTENT read and a `git log`/`merge-base` HISTORY
  read have different exposure to both merge strategy and clone depth. Classify each consumer by
  which kind it is before judging its coupling.
- **S4 clone-and-checkout-depth** -- the container clone's shallow state; `fetch-depth` settings
  across `.github/workflows/`.
- **S5 parallel-provenance-stores** -- `docs/plans/PLAN-*.yaml`, `docs/DECISIONS.md`,
  `ops_recommendations` (DuckLake, SCD2), `docs/SESSION_LOG.md`, `audits/`, telemetry tables.
  Assess as a provenance SUBSTRATE relative to git history; do not audit their internal schemas.
- **S6 wake-signal-machinery** -- `ci.yml`'s `signal-green` job,
  `.github/workflows/pr-conflict-signal.yml`, `scripts/ci/pr_conflict_signal.sh`,
  `scripts/checks/ci_guards/validate_pr_conflict_signal.py`.
- **S7 session-and-branch-lifecycle git-ops** -- the agent-side surface that actually MUTATES git
  state: `.claude/hooks/session_start_sync_main.sh` (`git fetch origin main` +
  `git branch -f main origin/main`), `.claude/hooks/fresh_branch_base.py` (side-effecting
  branch-cut guard), `.claude/hooks/never_on_main.py` (block-on-main guard),
  `.claude/hooks/session_start_commit_signing.py`, `.claude/hooks/edit_scope_guard.py`,
  `.claude/hooks/session_start_precommit.sh` plus the `.pre-commit-config.yaml` chain it installs
  (note `no-commit-to-branch --branch main` there against `never_on_main.py` -- two guards over
  one property is a VD5 question, not automatically a defect), and AGENTS.md's rebase-phase distinction
  (`AGENTS.md:210-212`) and its local-main-sync subsection (`AGENTS.md:214-217`). This is the only surface on which a clone-depth remedy could be
  implemented, which is why it is in scope.

**Out of scope, one line each.** Terraform apply model and deploy channels (own contracts).
The recommendation/decision portal's internal write semantics. The executor freeze (Decision 67).
Repository secrets policy. CI check content beyond the git-shape coupling. Anything requiring an
AWS write.

**Vocabulary.** *Log recovery* = an agent reconstructing what changed, why, and in what order,
from repository-local state. *Wake signal* = a comment posted to a PR to resume a session that
ended its turn. *History shape* = the commit topology and per-commit granularity of `main`.
*Parallel provenance store* = any durable record of change rationale that is not git history.
*Human-ergonomic convention* = a convention whose justification is human reading habit rather
than machine consumption. The term is descriptive, NOT pejorative: such a convention may be
correct to keep (a human reads this repository too -- see Q3b), correct to adapt, or correct to
drop. Deciding which is the work, and "drop it" is not the default answer.

## SETUP

Run these, in order, before anything else:

```
git fetch origin main
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`, both of which
DEDUP DISCIPLINE depends on. Both are gitignored caches; never commit them.

**Degraded paths -- never abort, never improvise:**

- IF cache-gen fails for ANY reason (creds down, egress blocked, import error, schema failure --
  the cause does not matter): do NOT abort -- set `meta.degraded_dedup=true`, set every finding's
  top-level `confidence` to `HYPOTHESIS` and its `roadmap_crossref.dedup_hit_count` to `null`,
  proceed. (`confidence` is a finding-level field; `roadmap_crossref` has no such key.) Downgrade
  every `merge_strategy_decision` block's `confidence` to `HYPOTHESIS` too. `meta.degraded_dedup`
  is read by the human disposing of this audit as the signal that no `roadmap_crossref`
  classification is trustworthy -- state that consequence in one line of `meta.contract_notes`
  as well, so it is legible without cross-referencing the flag.
- IF `git fetch origin main` fails: set `meta.contract_notes` to record it, use local `origin/main`
  as-is, and note in `meta.stale_anchors` that base derivation is unverified.
- IF an anchor quoted in this prompt does not resolve: record it in `meta.stale_anchors`, locate
  the referenced construct by name (grep for the function/section/setting), and proceed. A stale
  line number is never a reason to skip a surface.
- IF a repo-wide validation command fails for reasons unrelated to your deliverables: record it in
  `meta.contract_notes` and proceed. **Never fix it** -- that breaches the write boundary.
- IF the GitHub API is unavailable for the EMPIRICAL PASS: set `meta.contract_notes` accordingly,
  mark affected findings `evidence_kind: static`, proceed.
- IF the pre-commit chain rewrites your deliverables on commit (it installs hooks including
  `end-of-file-fixer` and `trailing-whitespace`): that is expected and harmless -- `git add` the
  rewritten files and re-commit. If `detect-secrets` or the sensitive-identifier hook BLOCKS the
  commit, do NOT disable the hook: remove the offending content from your deliverable (you are
  writing an audit, not a secret), note it in `meta.contract_notes`, and re-commit.
- IF a repository PreToolUse hook blocks you (S7 names these as in-scope surfaces, and a hook
  outranks any instruction in this prompt): `fresh_branch_base.py` may refuse or side-effect a
  branch cut, `never_on_main.py` blocks writes while on `main`, `edit_scope_guard.py` may block a
  write. Do NOT disable, edit, or work around any hook -- they are audit SUBJECTS. Instead: if the
  branch cut is blocked, cut from `origin/main` by explicit SHA
  (`git switch -c audit/gitops-agent-first-<sha> <sha>`), which is a different start-point and is
  not the blocked case. If a hook blocks writing your deliverables, record the exact block message
  in `meta.contract_notes`, and treat the obstruction itself as an OBSERVATION about S7 worth a
  finding. If you cannot write the deliverables at all, stop and report plainly.
- IF `git push` or PR creation fails: retry up to 3 times. If it still fails, leave the work
  committed locally, report the failure plainly in your final message, and STOP -- do not
  improvise an alternative delivery route.

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
  `neither-material`. **If your verdict is `shallow-clone-dominant` or `both-material`, you must also
  assess the obvious remedy** (under `squash-dominant` or `neither-material` the remedy is not the
  relevant lever -- say so in one line and move on): can the development container deepen its own clone (a session-start
  `git fetch --unshallow` or a bounded `--deepen`, which `ci_rca_lifecycle.py` already performs on
  demand), what would that cost per session, and is the cost justified by what it recovers? Assess this STATICALLY -- read
  `ci_rca_lifecycle.py` and the S7 hooks and reason about cost. **Do NOT actually run
  `git fetch --unshallow`**: it would destroy the shallow-boundary evidence trap 9 depends on and
  can move your base mid-run. State the assessment in the Q3a prose; file it as a finding if you
  judge it a gap. A `shallow-clone-dominant` verdict with no remedy assessed is incomplete.
- **Q3b**: are agents in fact the sole consumer of this repository's git log? Consider the human
  who disposes of every PR, and that the repository is PUBLIC, with a public-content boundary
  clause in Decision 101 and the phrase "market the engineering, not the alpha" stated at
  `AGENTS.md:9`. Verdict enum: `agents-sole-consumer` |
  `agents-primary-humans-secondary` | `genuinely-dual-consumer`. This verdict CONSTRAINS Q6: an
  agent-first-only optimisation is only free where the human-reader claim on that surface is
  weak, so state the dependency in your Q6 prose rather than assuming it away.

**Q4 -- Is the coupling to history shape essential or accidental, and is the commit-message
contract enforced?**
For each S3 mechanism, determine whether it needs the current history shape or merely assumes it,
and what it does when the assumption breaks. Separately assess whether the S2 contract is
adequately enforced for something load-bearing code parses. **This question carries TWO verdicts**
-- record both in its `question_answers` entry: `verdict_coupling`:
`mostly-essential` | `mixed` | `mostly-accidental`, rating the S3 set as a whole; and
`verdict_enforcement`: `sufficient` | `partial` | `insufficient`, rating the S2 contract. The
per-mechanism detail lives in the prose per the deep-dive routing in DEEP-DIVES below; a mechanism you judge
defective is also a finding.

**Q5 -- Is the wake-signal machinery reliable, and does the Q1 answer change its design?**
The requester reports `pr-conflict-signal` as unreliable in practice. Trace the delivery path
end to end for both signals and determine where a wake can be lost, whether a loss is observable,
and whether any Q1 outcome changes what these signals must do. Verdict enum: `reliable` |
`reliable-but-unobservable` | `unreliable-bounded` | `unreliable-unbounded`.

**Q6 -- What should an agent-first repository take FROM industry practice, and what should it
deliberately discard or invent?** *(headline question)*
This is NOT "what is industry best practice?" Many viable git-ops practices exist, and most
carry design pressure from human readers -- review ergonomics, `git log` scanability, bisect
workflows. Whether any given one of those pressures is in fact human-ONLY is for you to determine
rather than assume: an agent bisects too. The question is: given the Q3b answer, which industry
conventions are substrate-level requirements that survive any consumer, which are human-ergonomic
conventions an agent-first repository should drop or keep deliberately, and which structures
become available that would be unnatural for humans but efficient for agents?

Assess EVERY practice in the checklist below, one entry each, in the
`industry_adaptation` field of this question's `question_answers` entry. Pinned per-practice
enum: `adopt-as-is` | `adapt-for-agents` | `retain-for-human-reader` | `discard-human-ergonomic`
| `invent-novel-structure` | `already-in-place` | `n/a`. Use `invent-novel-structure` for the
requester's explicitly-requested third category: a structure that is NOT an industry practice at
all, which becomes available only because the reader is a machine. Do not mislabel an invention
as an adapted practice. `retain-for-human-reader` exists because dropping a practice is not
automatically the agent-first answer -- keep the option live. Each entry states the practice, the
enum value, the `surfaces` list it bears on (this is what the maturity rule reads; an entry
bearing on no surface takes `surfaces: []` AND must justify that in its `evidence` field -- an
empty list is a claim about the repository, not a default), what it would look like in an agent-first form, and
its evidence. This field is the SOLE source the maturity top tier reads.
This question's `verdict` is NOT an enum: it is a one-sentence thesis (<= 40 words) stating what
an agent-first repository should take, adapt, keep, drop, and invent.

**Checklist**: trunk-based development; linear history; Conventional Commits; commit trailers as
structured key-value metadata; `git notes` as detachable machine-readable annotation; PR-as-record
vs commit-as-record; bisectability; revertability; SLSA-style provenance and build attestation;
branch hygiene and post-merge branch deletion; CI checkout-depth strategy (shallow vs full vs
on-demand deepening); merge queues; auto-merge; signed commits; monorepo change-scoping
conventions.

Beyond the checklist, name between 0 and 4 structures (no more) that the checklist does not cover that becomes available once
the primary reader is a machine -- for example, machine-readable commit bodies, structured
trailers carrying plan/rec/decision ids, or annotation stores decoupled from commit messages.
Argue the cost as well as the benefit; a structure that is efficient for agents but unrecoverable
after a history rewrite is not free.

**Q6b -- If the strategy changes, what does the TRANSITION look like?**
Answer this whenever Q1's verdict is anything other than `keep-squash`; answer it as
`n/a-keep-squash` otherwise. A verdict the requester can act on needs its migration shape:
is the change retroactive (rewriting existing `main` history) or go-forward-only? If
go-forward-only, `main` then carries TWO history shapes, and every S3 consumer keyed on `HEAD~1`,
`--grep` over subjects, or `merge-base --is-ancestor` meets both -- trace what each does at the
boundary. Name the ordering of changes (Terraform ruleset, repository setting, AGENTS.md, the
`fetch-depth` guard in `verify_ci_workflow.py`, consumer fixes) and which must land together to
avoid a broken intermediate state. Verdict enum: `n/a-keep-squash` | `go-forward-only` |
`retroactive-rewrite` | `go-forward-with-consumer-migration`.

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
Answer all five seeds below, then add between 2 and 5 of your own -- no more. Prefer the ones a
reader would act on. **Any defect a Q8 answer surfaces is filed as a finding like any other** --
an answer slot is not a substitute for `findings[]`, and a defect that stops at Q8 escapes
severity, dedup, and the counting invariant:
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

Rate every surface S1..S7 on every dimension. Pinned enum: `strong` | `adequate` | `weak` |
`absent` | `n/a`. **`n/a` is correct and costless where a dimension does not structurally apply
-- never manufacture a rating or a finding to fill a cell.**

Polarity, pinned for every dimension: `strong` always means the surface is in GOOD shape on that
dimension, `weak` means poor shape, `absent` means the property is entirely missing where it
should exist, `n/a` means the dimension does not structurally apply. Never read a dimension's
phrasing as inverting this -- a surface with NO coupling to history shape rates `strong` on VD3,
not `absent`.

- **VD1 Machine-recoverability** (NS1, NS6) -- can an agent reconstruct what changed and why from
  repository-local state, without a network round-trip per item? `strong` = yes, locally and
  cheaply.
- **VD2 Contract enforcement** (NS5) -- is the machine-readable shape this surface relies on
  validated by a gate, or left to convention? `strong` = a gate enforces it; `absent` = the
  surface relies on a shape nothing checks.
- **VD3 Coupling essentiality** (NS1) -- does this surface depend on the current history shape by
  necessity, or by unexamined assumption? `strong` = no coupling, or coupling that is necessary
  and documented; `weak` = coupling by unexamined assumption; `absent` = coupling that is both
  unnecessary and undocumented.
- **VD4 Degradation behaviour** (NS4) -- under a shallow clone, a missing commit, or a masked
  failure, does the surface fail loudly or return a plausible wrong answer? `strong` = fails
  loudly and visibly; `absent` = degrades silently to a wrong-but-trusted result.
- **VD5 Provenance source-of-truth hygiene** (NS2, NS3) -- is the record stored once in the right
  store, or split and duplicated across stores that can drift? `strong` = one authoritative
  store; `weak` = duplicated with a live drift surface.
- **VD6 Consumer fit** (NS1, and constrained by the Q3b verdict) -- is this surface's shape
  justified by its ACTUAL consumers? `strong` = the shape is deliberate and matches who reads it,
  whether that is agents, humans, or both. `weak` = the shape is inherited convention that serves
  no current consumer. A surface deliberately shaped for a human reader rates `strong` where a
  human reader genuinely exists; this dimension does not reward machine-optimisation for its own
  sake.

## DEEP-DIVES

**Where deep-dive output goes**: DD-A's per-mechanism breakage matrix is recorded in the Q4
`question_answers` entry's `prose`, AND its bottom line -- what changing the strategy would cost
-- is summarised in the Q1 prose beside DD-D's. Q1's answer must narrate BOTH sides of the
ledger; a Q1 prose that carries DD-D's cost-of-keeping without DD-A's cost-of-changing (or the
reverse) is a one-sided answer. Any mechanism you judge defective is ALSO filed as a finding. DD-B's outcome is recorded per the instruction in its own text. DD-C's trace is
recorded in the Q5 `question_answers` entry's `prose`, with defects filed as findings. DD-D's
status-quo cost trace is recorded in the Q1 `question_answers` entry's `prose` (alongside DD-B's
drift summary), with any loss you judge material filed as a finding. Where DD-D bears on what the
parallel provenance stores must carry, carry that into the Q2 prose; where it bears on the
session-log substitution, carry it into Q7. Those are pointers, not duplication -- one sentence
each naming the DD-D result the answer depends on. A
deep-dive that produces no finding still produces prose -- never leave one silent.

**DD-A -- End-to-end trace of the history-shape dependencies.** *(feeds Q1, Q4)*
For each of `push_context_base()` (`HEAD~1` plus `fetch-depth: 2`), `rec-autoclose`'s
`git log -1 --format=%B HEAD`, the `feat({slug})` subject resolution in `validate_vp_replay` and
`validate_graduation_completeness`, and `plan_audit._verify_rec_in_git`'s
`git log origin/main --grep=`: state what breaks under each Q1 candidate strategy, whether the
break is loud or silent, and whether a cheap decoupling exists. This trace is the blast-radius
evidence for Q1 -- do not answer Q1 without it.

**DD-B -- The `Resolves:` trailer delivery path.** *(feeds Q1, Q4)*
THREE surfaces state where the trailer belongs, in non-identical terms. `AGENTS.md:236` places it
in the squash-merge COMMIT body. `.claude/skills/implement/SKILL.md:547` places it in the PR body
"which the squash-merge commit body inherits". `.github/pull_request_template.md` -- the surface
actually rendered to the author at PR-open time -- places it in the commit body and explicitly
warns "not just the PR description". Read all three verbatim before analysing; an analysis built
on two of them is incomplete. Two open recommendations (rec-2679, rec-2733) describe a loss mode
for single-commit PRs. Determine the actual GitHub
behaviour, whether the two instructions are equivalent in all cases, whether the existing
recommendations' remedies are the right fix, and whether a merge-strategy change would obviate,
worsen, or leave them unchanged. **Explicitly re-assess those two recommendations rather than
dismissing them as owned territory** -- the requester wants to know whether their proposed
remedies still make sense with the merge-strategy question open. Record the re-assessment outcome using the full
adjudication contract -- `rejected_candidates`, or a finding classified `novel`,
`planned-insufficient`, or `planned-unbuilt`, whichever your trace warrants (a trailer defect the
two recommendations do not own at all IS `novel`) -- and summarise the three-surface drift analysis
in the Q1 `question_answers` prose.

**DD-C -- Wake-signal delivery paths.** *(feeds Q5)*
Trace both signals from trigger to delivered comment. For `signal-green`: which checks gate it
(`ci.yml:303`), which PR-triggered checks exist that are not in that list, and what a watching
session concludes from a comment that arrives before an omitted check finishes. For
`pr-conflict-signal`: enumerate every point where a wake can be lost, and determine whether a
loss is observable given the step's `continue-on-error: true` and the script's internal failure
counter and exit code. Include the case of a PR that is already conflicted at creation time,
when no subsequent push to `main` occurs.

Scope ruling for this deep-dive: enumerating PR-triggered checks may surface workflows belonging
to the deploy/apply model, which SCOPE excludes. You MAY name such a workflow as evidence that
`signal-green`'s gate list is incomplete -- that is a wake-signal finding. You may NOT assess or
recommend changes to the deploy/apply model itself. If the only available remedy would change
that model, file the finding against S6 and say so in `sequencing.note`.

**DD-D -- The cost of the STATUS QUO.** *(feeds Q1, Q2, Q7 -- mandatory, same standing as DD-A)*
Starting anchors, handed over so this trace begins on the same footing as DD-A's consumer
inventory -- verify each, and extend:
  - **Fetch guard, read first:** fetching a PR ref IS permitted (Q3a's prohibition is on
    `--unshallow` specifically, not on this). But a `git fetch origin refs/pull/<N>/head` into a
    shallow clone can add `.git/shallow` entries and, for a PR whose base predates the boundary,
    can change what `git log --reverse origin/main | head -1` returns -- the exact evidence trap 9
    and the S5 `--stat` example rest on. So: record the boundary FIRST
    (`git log --reverse origin/main --format=%h | head -1` and `cat .git/shallow`), fetch, then
    re-check it. If it moved, say so in `meta.contract_notes` and treat the S4 `--stat` example as
    recon-time evidence rather than something you reproduced. If a `merge-base..head` count will
    not resolve for a given PR, skip that PR, note it, and sample another -- never `--unshallow`
    to force it.
  - `git ls-remote origin 'refs/pull/*/head' | wc -l` returned 893 at recon: the PRE-MERGE commit
    sequence of merged PRs is retained on the remote and is fetchable via
    `git fetch origin refs/pull/<N>/head`. Confirm this, and establish what it costs (network? per
    PR?) and whether anything in the repository actually does it.
  - Pre-merge commit counts, sampled at recon by fetching `refs/pull/<N>/head` and counting
    `merge-base..head`: PR #887 = 1, #891 = 1, #889 = 2, #888 = 2, #883 = 4. Re-derive over your
    own sample (see EMPIRICAL PASS) -- if agent PRs typically carry ONE commit, squash collapses
    nothing and the granularity argument is moot; if they carry several, it collapses a real
    sequence. This ratio is the single most decisive number in DD-D; do not assume it.
  - `git ls-remote --heads origin | wc -l` returned 25 at recon. Determine whether
    `delete_branch_on_merge` is live (recall from C7 that it is unmanaged in Terraform) and what
    that implies for C17.
  - `.github/workflows/` retention: whether CI logs and run records for a merged PR outlive the
    branch, and for how long.
DD-A traces what would BREAK if the merge strategy changed. This deep-dive traces the opposite
and is equally required: what is unrecoverable TODAY, for an agent, precisely BECAUSE `main`
carries one squashed commit per PR? Trace at least: intra-PR commit granularity (the ordered
steps an implementing session actually took, and where they now live, if anywhere); bisect
resolution (what a bisect over `main` can and cannot localise at one-commit-per-PR granularity,
and whether anything in this repository bisects); per-step attribution and review-fix history;
and whether the `(#NNN)` indirection to the PR record is a sufficient substitute given it costs a
network round-trip (NS6) and depends on GitHub retaining refs for deleted branches. Answering Q1
without BOTH DD-A and DD-D is answering it on one-sided evidence.

**Interpreting a negative answer -- read this before you trace.** Several DD-D questions are
existence questions ("does anything here bisect?", "does anything fetch a PR ref?") whose answer
may well be "nothing". A bare "nothing" is NOT evidence of no cost. Distinguish two cases every
time, and say which you concluded: (a) ABSENCE OF NEED -- the capability is available and nothing
needs it, which genuinely is no cost; (b) ABSENCE OF CAPABILITY -- the capability was never
practically available under the current strategy, so nothing was ever built to use it, and its
absence is evidence about the constraint rather than about the need. Note the structural
asymmetry you are working against: DD-A traces an inventory of ~25 existing consumers and will
naturally yield a concrete breakage list, while DD-D asks what does not exist and will naturally
yield silence. Do not mistake that asymmetry of EVIDENCE SHAPE for an asymmetry of COST.

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
- `terraform/github/repo.tf:39-44` lists SIX settings inside the `lifecycle.ignore_changes`
  block: `allow_merge_commit`, `allow_squash_merge`, `allow_rebase_merge`, `allow_auto_merge`,
  `allow_update_branch`, and `delete_branch_on_merge`. All six are merge-adjacent; none is
  declared in Terraform.
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
- `scripts/convergence_health/record.py:101` `count_unapplied_tf_commits()` carries the docstring line (at :107)
  "Returns 0 on any error (record SHA may predate the current clone depth)"; the enclosing
  `try` returns 0 from an `except Exception:  # noqa: BLE001` handler at approximately line 137.
- `scripts/ops_portal/ci_rca_lifecycle.py:151` `_ensure_ancestry_history()` runs a best-effort
  `git fetch --unshallow origin`; its docstring states that an unresolvable `merge-base
  --is-ancestor` causes `classify_closed_head` to misfile a stale-code rerun as a regression, and
  that the function is never a hard dependency.
- `.github/workflows/ci-rca.yml:77-83` uses `fetch-depth: 0` with a comment describing it as
  belt-and-suspenders alongside that code-level guard-fetch.

**S4 clone-and-checkout-depth**
- The Claude-Code-on-the-web container clone has `.git/shallow` present. **The window GROWS: at
  recon `git rev-list --count origin/main` returned 50 spanning PRs #841-#891, and `main` advances
  continuously, so by the time you run this the count and range WILL be larger. Every number in
  this S4 block is a shape claim, not a value claim -- re-derive all of them and use your own
  figures throughout; do not record the drift in `meta.stale_anchors` (it is expected, not stale).**
- Every commit in the window carried a `(#NNN)` suffix -- one commit on `main` per merged PR,
  with no exceptions across the whole window. That SHAPE is the load-bearing claim; confirm it
  still holds rather than checking the count.
- Subject-prefix distribution at recon: all but ONE subject matched a `prefix(scope)` form
  (roughly half `feat(`, roughly half `plan(`, with single `fix(`, `docs(`, and `audit(` entries).
  Exactly one did not (see C4). Re-derive the distribution yourself; the load-bearing claim is
  "all but a small number conform", and your job includes checking whether that still holds.
- `fetch-depth` settings across workflows range from `1` (`claude.yml`) through `2` to `0`
  (`ci.yml` PR job, `ci-rca.yml`, `convergence-health.yml`).
- `docs/ROADMAP-PLATFORM.yaml:474` records an artefact whose "provenance [is] unrecoverable from
  the squashed clone".
- The `.git/shallow` entries ARE the oldest present commits (their PARENTS are grafted away), so
  `<oldest-present>^` does not resolve. At recon,
  `git show --stat <oldest-present-commit> -- docs/SESSION_LOG.md` reported 666 insertions for a
  file that long predates the clone window. This is the trap in READ FIRST item 9; it is also a
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
- The workflow has a substantial run history. Derive the run count and recent conclusions
  yourself in the EMPIRICAL PASS; if the GitHub API is unavailable, follow the SETUP degraded
  path and reason from the workflow and script sources alone, which suffice for C12.

**Governing decisions and contracts**: Decision 76 (CC-web workflow, squash policy), Decision 83
(branch protection live), Decision 89 (CI as merge gate), Decision 101 (public boundary),
Decision 159 (push-context diff base), Decision 162 (delegate-script call-site discipline),
Decision 55/72/129 (forward-fix), `docs/contracts/instruction-architecture.yaml`.

## EMPIRICAL PASS

Sample real artefacts; observed findings outrank static ones at equal severity. **Hard bounds --
do NOT exceed:**

- **The ENTIRE shallow-clone window** (`git rev-list --count origin/main`; ~50 at recon and
  growing), capped at **80** to bound effort. The whole window is required because C4's
  conformance question cannot be adjudicated over a subset -- and because the OLDEST commit in the
  window is the one trap 9 and the S5 `--stat` example both depend on, so a cap that trims the
  tail would silently remove your own evidence. Check subject-prefix conformance, `(#NNN)`
  presence, and `Resolves:` trailer presence and well-formedness. Tag `evidence_kind: observed`.
  If the window somehow exceeds 80, take the 80 most recent PLUS the oldest reachable commit, and
  say so in `meta.contract_notes`.
- **<= 15** most recent `pr-conflict-signal.yml` runs and **<= 15** most recent `ci.yml` runs, via
  the GitHub API. For the conflict signal, determine whether any run's step summary or log carries
  a `[PR-CONFLICT-SIGNAL] FAILURE` marker while the run conclusion is `success`.
- **<= 10** merged PRs: check whether the PR body's `Resolves:` trailer reached the `main` commit
  body, and record the PR's commit count (this is the discriminator for the DD-B loss mode).
- **<= 8** `docs/plans/PLAN-*.yaml` with non-empty `bundled_recommendations`: check whether the
  named recommendations are closed. This is the efficacy sample for the `Resolves:` trailer path
  -- it feeds DD-B and the Q4 `verdict_enforcement`. An unclosed rec is NOT automatically a defect:
  distinguish trailer-never-emitted, trailer-emitted-but-unparsed, closed-by-manual-portal-call,
  and plan-not-yet-implemented before concluding anything. Record the breakdown in the Q4 prose.

"Outrank" is operational: where an observed finding and a static finding of equal severity
compete for a slot in `top_improvements` or for `highest_leverage_change`, the observed one wins.
It does not alter severity.

**Counterfactual test, applied per sample**: for any mechanism you judge to be working, ask
"would this sample still look identical if the mechanism were deleted or silently no-opping?"
If yes, the sample is not evidence that it works. Apply this specifically to `rec-autoclose`
(a recommendation may be closed by a manual portal call rather than the trailer) and to
`pr-conflict-signal` (a green run with no conflicted PRs in the window is not evidence of
delivery).

## METHOD

- **P0 Base.** Perform SETUP, then immediately derive the base sha and create the branch per
  COMMIT / PR MECHANICS steps 1-2, BEFORE any analysis. Fixing the base first guarantees the
  filename sha, `meta.audited_commit`, and the tree you actually read are the same commit even if
  `main` advances mid-run.
- **P1 Read.** Every S1..S7 surface. Verify anchors; record stale ones.
- **P2 Trace.** DD-A, DD-B, and DD-D -- DD-A gives the cost of changing, DD-D the cost of keeping. Establish BOTH before forming any Q1 opinion.
- **P3 Trace.** DD-C.
- **P4 Premise test.** Q3a and Q3b. Both premises must be settled before Q6, because Q3b
  constrains what Q6 may recommend.
- **P5 Empirical.** The sampling above, within bounds.
- **P6 Rate.** VD1..VD6 across S1..S7.
- **P7 Dedup.** Per DEDUP DISCIPLINE, before any finding is filed.
- **P8 Synthesize.** Answer all ten questions (Q1..Q8, with Q3 split into Q3a/Q3b, plus Q6b), populate `merge_strategy_decision`, then compute maturity
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
- The harness-assigned `claude/*` session branch model (Decision 76 clause 2) -- not
  repository-changeable from within this repository.
- The `send_later` / trigger backstop retirement and the CC-web permission gotcha, both recorded
  in AGENTS.md `## Git-ops procedure` step 4 under Decision 76/83. These carry no separate
  decision id; AGENTS.md is the authority.
- The executor freeze and IMPLEMENTATION-only planning (Decision 67).
- The public-repository content boundary (Decision 101).
- `continue-on-error: true` on wake-signal steps as a design intent (a wake must never red a
  build) -- stated as an invariant in `pr-conflict-signal.yml`'s header comment under Decision
  55/76/83. Its OBSERVABILITY consequences are squarely in scope (see C12); its existence is not
  a defect.

## OUTPUT

Write exactly two files.

`audits/gitops-agent-first-<sha>.yaml`:

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: "<your self-reported model name; free text, quoted>",
         methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6, S7],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  # contract_notes: a single string; when several degraded paths fire, join their notes with
  #   "; " in the order they occurred. Never drop one to make room for another.
  # stale_anchors: a list of objects, {anchor: "<as cited in the prompt>", found: "<what is
  #   actually there, or 'absent'>"}. Anchors only -- non-anchor notes go in contract_notes.
  question_answers:
    - {q: Q1, verdict: keep-squash|switch-to-rebase-merge|switch-to-merge-commit|hybrid-by-pr-class,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: git-log-load-bearing|partially-load-bearing|git-log-redundant,
       basis: [], prose: ""}
    - {q: Q3a, verdict: shallow-clone-dominant|squash-dominant|both-material|neither-material,
       basis: [], prose: ""}
    - {q: Q3b, verdict: agents-sole-consumer|agents-primary-humans-secondary|genuinely-dual-consumer,
       basis: [], prose: ""}
    - {q: Q4, verdict_coupling: mostly-essential|mixed|mostly-accidental,
       verdict_enforcement: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q5, verdict: reliable|reliable-but-unobservable|unreliable-bounded|unreliable-unbounded,
       basis: [], prose: ""}
    - q: Q6                      # NOTE: block style is REQUIRED here -- a flow mapping cannot
      verdict: ""                #       contain a block sequence, and industry_adaptation is one.
      basis: []                  #       verdict: a one-sentence thesis, <= 40 words, not an enum.
      prose: ""
      industry_adaptation:
        - practice: <checklist entry or newly named structure>
          rating: adopt-as-is|adapt-for-agents|retain-for-human-reader|discard-human-ergonomic|invent-novel-structure|already-in-place|n/a
          surfaces: [S1, S3]     # surfaces this practice bears on; [] requires justification
          agent_first_form: ""
          evidence: ""
    - {q: Q6b, verdict: n/a-keep-squash|go-forward-only|retroactive-rewrite|go-forward-with-consumer-migration,
       basis: [], prose: ""}
    - {q: Q7, verdict: git-log-sufficient-substitute|git-log-sufficient-if-commit-contract-changes|complementary-keep-both|neither-suitable-replace-both,
       basis: [], prose: ""}
    - q: Q8                      # block style for the same reason
      answers:
        - {question: "", answer: "", basis: []}
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
    - {surface: S1, maturity: <derived>, maturity_note: "", strengths: "",
       top_gaps: [<finding ids>]}   # top_gaps: up to 3 finding ids, most severe first
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - id: GITOPS-01              # block style; the list-valued fields below need it
      candidate_ids: [C1]        # LIST of C1..C18, or [] if you discovered this yourself
      surface: [S2, S3]          # LIST. one or more of S1..S7, or exactly [shared]
      question: [Q1, Q4]         # LIST. from Q1,Q2,Q3a,Q3b,Q4,Q5,Q6,Q6b,Q7,Q8 -- never bare Q3
      dimension: [VD2]           # LIST. one or more of VD1..VD6
      title: ""
      evidence: ""               # "file:line", an item-id, or for evidence_kind: observed a
                                 # commit sha / workflow run id / PR number -- any of these
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate|switch_mechanism
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                         item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""}
      effort: XS|S|M|L           # XS <1h, S <halfday, M <2d, L >2d -- of the FIX, not the audit
      sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}
                                 # safe_to_queue_now: false iff this fix must wait on another
                                 # finding or roadmap item named in blocked_behind
  rejected_candidates:
    - {candidate_ids: [C2], candidate: "", why_dismissed: "",
       compensating_control: "", control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, rejected_count: 0, candidates_unadjudicated: [],
            top_improvements: [], highest_leverage_change: <id or null>,
            maturity_S1: <value>, maturity_S2: <value>, maturity_S3: <value>,
            maturity_S4: <value>, maturity_S5: <value>, maturity_S6: <value>,
            maturity_S7: <value>}
```

`audits/gitops-agent-first-<sha>.md`: prose companion, **<= 1500 words**, the executive layer a
human reads first. Lead with the Q1 answer and its reasoning, then Q6's thesis, then the findings
that matter. Do not restate the YAML.

**COUNTING INVARIANT**: `findings[]` is the SOLE enumerated list.
`total_findings = len(findings) = novel_count + planned_insufficient_count +
planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates`, NOT findings.
`rubric_ratings`, `question_answers`, and `merge_strategy_decision` are systems-of-record
referenced FROM findings, never re-counted. `top_improvements` holds 3 to 5 finding ids (fewer only if `findings[]` is
smaller). `top_improvements` and `highest_leverage_change` MUST be finding ids;
`highest_leverage_change` is `null` when `findings[]` is empty.
`rejected_count` MUST equal `len(rejected_candidates)` and is deliberately NOT part of the
`total_findings` sum -- it is a separate cross-check that the candidate set was fully adjudicated.

Cardinality, pinned: `rubric_ratings` carries one row per (surface, dimension) pair -- 7 surfaces
x 6 dimensions = 42 rows, `n/a` included. `per_surface_assessment` carries exactly 7 rows. The
single rows shown in the skeleton are format examples, not counts. On an `n/a` row set
`evidence: ""` and put the one-line reason the dimension does not structurally apply in `note`.

Q1 / `merge_strategy_decision` consistency, pinned: exactly ONE block is `recommended`, and it
must be the one Q1's verdict names (`hybrid-by-pr-class` -> the `hybrid` block). Every other
block is `viable` or `rejected`.

`change_type: switch_mechanism` is the value for replacing one mechanism with a different one --
use it for any merge-strategy change recommendation; no other value fits that class.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates (mechanism or `file:line`), and
state why the control would FAIL if the defect were real.

`CONFIRMED` requires the behaviour traced to a `file:line` or an observed sampled artefact.
Anything less is `HYPOTHESIS`.

Field shapes, pinned: `surface`, `question`, and `dimension` on a finding are LISTS -- a finding
may legitimately span several (C5 spans S2 and S3; DD-B feeds Q1 and Q4). A finding that bears on several surfaces lists
them all (`surface: [S2, S3]`) and counts toward EACH listed surface's maturity tally. Reserve
the literal `[shared]` for a finding that genuinely belongs to no single surface; a `[shared]`
finding counts toward no surface's maturity and appears in no `top_gaps` list, so do not use it
as a shortcut for a multi-surface finding. If a `[shared]` finding is severe, name it in
`summary.top_improvements` -- that is its only route to visibility. Legal `question` values are
`Q1, Q2, Q3a, Q3b, Q4, Q5, Q6, Q6b, Q7, Q8` -- note `Q3a`/`Q3b`, never a bare `Q3`.
`candidate_ids` is a LIST naming the CANDIDATE OBSERVATIONS entries a finding or rejection
adjudicates, or `[]` for anything you discovered yourself. One finding MAY cover several
candidates -- C15/C16/C17/C18 are four facets of one cost-of-keeping argument and a single
well-argued finding covering all four is BETTER than four padded ones. One candidate MAY also
split across several entries where your trace genuinely separates them (C6 bundles rec-2679 and
rec-2733, which DD-B re-assesses individually).

Coverage rule (this is the real cross-check): every one of C1..C18 MUST appear AT LEAST ONCE
across `findings[].candidate_ids` and `rejected_candidates[].candidate_ids`. None may be silently
dropped. `summary.candidates_unadjudicated` lists any you could not resolve, as objects
`{candidate_id: "C7", reason: "<one line>"}`; an empty list is the expected result.

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

**Maturity**, computed LAST, per surface, top-down, first match wins.

Counting rule, pinned: "critical" and "high" mean findings YOU filed in `findings[]` carrying
that severity and naming that surface -- regardless of `roadmap_crossref.classification`. A
`planned-unbuilt` or `planned-insufficient` high counts exactly like a novel high; the gap is
open either way. `rejected_candidates` never count.

Assessment rule, pinned: an `industry_adaptation` entry "bears on" a surface iff that surface
appears in the entry's `surfaces` list. Any of the six non-`n/a` ratings counts as ASSESSED --
including `discard-human-ergonomic` and `retain-for-human-reader`. Only an entry you left out of
the field entirely, or one bearing on the surface with no rating, is unassessed.

- **frontier** = 0 critical AND 0 high findings on that surface, AND every
  `industry_adaptation` entry bearing on that surface is assessed per the rule above, AND that
  surface appears in the `surfaces` list of at least THREE `industry_adaptation` entries. The
  three-entry floor exists because you author the `surfaces` lists yourself: without it, a surface
  reaches the top tier by being assigned to nothing. If a surface genuinely bears on fewer than
  three practices, it cannot be `frontier` -- cap it at `strong` and say why in
  `per_surface_assessment[].maturity_note`.
- **strong** = 0 critical AND <= 1 high.
- **solid** = <= 1 critical AND <= 3 high.
- **nascent** = otherwise.

`frontier` remains reachable where you argued a property-matched compensating control. Neither a
`discard-human-ergonomic` nor a `retain-for-human-reader` rating is a maturity penalty -- both
are recommendations, and a surface can be frontier while carrying either.

Precedence, pinned: `summary.maturity_S1..S7` and `per_surface_assessment[].maturity` MUST agree.
Compute once, write twice; if they disagree the deliverable is invalid.

## COMMIT / PR MECHANICS

1. Derive the base ONCE, at P0, immediately after SETUP:
   ```
   git rev-parse --short origin/main
   ```
   (SETUP already ran `git fetch origin main`; do not fetch again -- a second fetch can move the
   base mid-run and desynchronise the filename sha from the tree you read.) This base IS the
   audited tree. Use that sha in both deliverable filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/gitops-agent-first-<sha> origin/main` so the PR diff contains only the
   two deliverables. This is a deliberate, documented exception to the `claude/*` session-branch
   rule: the audit needs a clean two-file diff off the audited base.
3. Repository-wide validation is advisory outside CI here. The real pre-push gate is a clean YAML
   parse of your two deliverables:
   ```
   bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/gitops-agent-first-<sha>.yaml
   ```
   An unrelated `validate --pre` failure is recorded in `meta.contract_notes`, never fixed.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, using this subject
   verbatim (it follows the repository's `prefix(scope):` convention -- the same convention C4
   asks you to adjudicate, so do not author a bare `audit:` subject here):
   ```
   audit(gitops-agent-first): git-ops agent-first audit deliverables
   ```
   Then `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` with `owner` and `repo` taken from the
   `origin` remote (`git remote get-url origin`), `base: main`, `head`: your branch, ready for
   review, NOT a draft. Title:
   `audit(gitops-agent-first): git-ops procedures for an agent-first repo`
   Body: a 2-3 sentence lede plus the `summary` block in a yaml fence.
6. **END THE TURN.** Do not poll, do not merge, do not subscribe, do not self-approve. The human
   disposes of the PR.

**Precedence.** This section OVERRIDES the repository's ambient git-ops instructions wherever the
two differ -- specifically the `claude/*` session-branch rule and the subscribe-then-wait-for-CI
flow. Those exist for change PRs that must merge; this is a read-only audit deliverable the human
disposes of. Follow this section, not the ambient one, and do not treat the difference as a
finding.

## GUARDRAILS

- **Write boundary, closed list**: `audits/gitops-agent-first-<sha>.yaml` and
  `audits/gitops-agent-first-<sha>.md`. Nothing else in the repository tree. Do not fix a defect
  you find. Do not update AGENTS.md, a workflow, a check, or a recommendation. Do not file a
  recommendation through the ops portal.
- **Precision over volume.** Fewer than ~8 surviving findings is a valid result -- state it
  plainly and do not pad. A thin findings list with a well-argued Q1 and Q6 is a better outcome
  than a padded one.
- **Do not confirm the frame, and do not over-correct against it.** The requester believes
  squash-merge may be harming agents. If the evidence does not support that, say so directly and
  explain what the evidence does support. A well-evidenced `keep-squash` verdict is a full
  success; so is a well-evidenced `switch-to-rebase-merge`, `switch-to-merge-commit`, or
  `hybrid-by-pr-class` verdict. What is NOT a success is a verdict that follows the weight of the
  candidate list rather than the weight of the evidence you gathered in DD-A and DD-D.
- Every rating and verdict must trace to evidence you read in this session. `basis` holds finding
ids only, so a verdict resting on evidence that produced NO finding takes `basis: []` and carries
its evidence in `prose` -- that is expected, not a gap (a well-evidenced verdict with few findings
is a valid result). Where you could not
  verify, say `HYPOTHESIS` and explain what would settle it.
- No emojis. Plain ASCII, ASCII hyphens only.
