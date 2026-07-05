# AUDIT: CI-RCA Subsystem (diagnosis agent + evidence pipeline + enforcement spine + roadmap)

TASK: Read-only, frontier-grade architectural audit of the CI-RCA (CI Root-Cause-Analysis)
subsystem of this repository. FOUR surfaces, evaluated as ONE system: (S1) the `ci-rca`
diagnosis agent -- its GitHub Actions workflow and agent prompt; (S2) the deterministic evidence
pipeline -- seven `scripts/ci_rca_*.py` modules plus `config/ci_rca_taxonomy.yaml`; (S3) the
portal enforcement spine -- the `CiRcaContext` schema and the `file_rec` / `_run_ci_rca_cross_check`
gate in `scripts/ops_data_portal.py`, with its tests; (S4) the live observability gauges in
`scripts/session_preflight.py` and the governing roadmap/contract (`docs/ROADMAP-PLATFORM.yaml`
T1.13, `docs/INTENT-ci-rca-methodology.md`). The subsystem is ALREADY BUILT and running: judge the
built-and-running reality together with the NARROW remaining planned surface (the
`CI_RCA_STRICT_MODE` strict-flip, telemetry Phase 4, residual tightenings). Deliverables: exactly two
files, `audits/ci-rca-system-<sha>.yaml` and `audits/ci-rca-system-<sha>.md`. The ONLY files you
create or modify in the tree are those two; regenerating gitignored local caches per SETUP is
expected and is not a tree edit (never commit them). You draft judgment; the human disposes.

Your output is expensive. Lead with verdicts, be dense, cut filler. The reader built this system and
is a sophisticated architect: skip basics, skip flattery, go to the frontier margin. Every sentence
earns its token cost.

---

## 1. CANDIDATE OBSERVATIONS vs VERDICTS (the epistemic contract)

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you NO verdicts. Every candidate in
Section 8 is a hypothesis to ADJUDICATE, not a finding to confirm. ASSUME NO CANDIDATE IS A REAL
DEFECT UNTIL YOU TRACE IT. A run that merely confirms the candidates below has FAILED.

Per-candidate adjudication, and its mapping to the output contract (Section 14):
- Traced to a CONFIRMED defect not owned by any roadmap item -> `findings[]`, classification `novel`.
- Owned by a roadmap/contract item whose remedy you judge insufficient or unbuilt -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt`.
- Owned AND fully covered by that item's remedy -> `rejected_candidates[]` (name the item).
- Not a defect (a compensating control makes it safe) -> `rejected_candidates[]` (name the control
  AND its property match per Section 15).

Severity is NEVER inherited from this prompt's framing. You assign it AFTER judgment (Section 15).

---

## 2. READ FIRST -- disambiguation traps

These are two-things-one-name hazards discovered at recon. Internalise them before reading code;
each invites a wrong finding.

1. **`scripts/ci_rca_evidence.py` is NOT the whole evidence pipeline.** It is the bundle
   assembler/uploader (S3 + local fallback). Gate/tier analysis lives in `scripts/ci_rca_tier_map.py`
   (AST walk of `validate.py`, runtime probe, `compute_earliest_viable_gate`); failure
   classification in `scripts/ci_rca_taxonomy.py`; gate-escape/vacuous-pass detection in
   `scripts/ci_rca_vacuous_pass.py`. Auditing only the file the INTENT doc names by itself is a
   miss.
2. **The INTENT contract's Athena/Iceberg prose is RETIRED, not current.** `docs/INTENT-ci-rca-methodology.md`
   Sections 1, 3, 7 were written against a pre-Decision-84 Iceberg/Athena backend; `ops_*` moved to
   DuckLake-on-Neon (Decision 84/81). The doc marks these passages `[STALE]` inline. Audit the
   IMPLEMENTATION. Do NOT file "the system uses Athena / Iceberg" findings -- it does not. (Whether
   the un-updated prose harms the contract's source-of-truth role IS in scope: that is Q4, a
   different claim.)
3. **Bare `source=ci_rca` vs the sibling sources.** The cross-check spine applies ONLY to
   `source=ci_rca`. Sibling sources are deliberately carved out and validated differently:
   `ci_rca_evidence_dispute`, `ci_rca_probe_health`, `ci_rca_warn_period_audit`,
   `ci_rca_terminus_override`, `ci_rca_taxonomy_extension`, `ci_rca_strict_mode_demotion`. Do not
   assert "sibling source X bypasses the cross-check" as a defect -- the carve-out is by design
   (verify the design intent before judging).
4. **Two things named "gate".** The CI MERGE gate is a tier ladder (`pre` -> `presubmit` -> `CI`).
   The PORTAL enforcement gate is the set of checks inside `file_rec` / `_run_ci_rca_cross_check`.
   Keep them distinct in every finding.
5. **CI-RCA is NOT the executor-RCA.** This subsystem diagnoses CI failures (Decision 72). A
   SEPARATE system (Decision 55, the `executor-rca` skill) diagnoses autonomous-executor failures.
   Do not conflate; do not audit the executor path.
6. **Decision 72 was formerly duplicated.** DECISIONS.md once had two "Decision 72" entries; the
   branch-protection one was renumbered to Decision 89. "Decision 72" throughout this audit means
   "RCA-as-Plan-Source for CI Merge Gate Failures".

---

## 3. SCOPE

Surfaces (all BUILT unless marked). Trust NO number, path, or line quoted in this prompt: obtain
every file/line/size by reading the file yourself, and record any non-resolving anchor in
`meta.stale_anchors`. The GROUNDING MAP (Section 10) exists to spend your cognition on judgment,
not grep -- but verify before relying.

- **S1 -- diagnosis agent** (BUILT): `.github/workflows/ci-rca.yml`, `.claude/agents/scheduled/ci-rca.md`.
- **S2 -- evidence pipeline** (BUILT): `scripts/ci_rca_evidence.py`, `ci_rca_taxonomy.py`,
  `ci_rca_tier_map.py`, `ci_rca_vacuous_pass.py`, `ci_rca_filing.py`, `ci_rca_probe_health.py`,
  `ci_rca_back_validation.py`; `config/ci_rca_taxonomy.yaml`; guards
  `scripts/checks/ci_guards/validate_ci_rca_taxonomy.py`, `validate_ci_rca_trigger.py`.
- **S3 -- enforcement spine** (BUILT, running in WARN mode): `scripts/ops_data_portal.py`
  (`CiRcaContext`, `file_rec`, `_run_ci_rca_cross_check`, `back_validate_ci_rca`);
  `tests/test_ops_data_portal.py` (ci_rca test classes).
- **S4 -- observability + governance** (BUILT gauges; the strict-flip + telemetry Phase 4 are
  DESIGNED-UNBUILT): `scripts/session_preflight.py` ci_rca gauges; `docs/ROADMAP-PLATFORM.yaml`
  T1.13 (remaining exit criterion c2 -- strict-flip, gated on Phase-4 back-validation AND c7
  probe-abstention fail-loud -- and the c12 sub-criteria), T3.4; `docs/INTENT-ci-rca-methodology.md`.

Out of scope (one line each): the executor-RCA path (Decision 55); the DuckLake reader/writer
internals (treat the portal boundary as a black box); Decision 43 the SLOC policy itself (only its
tier-PLACEMENT is in scope); general `validate.py` correctness beyond CI-RCA's use of it; any
non-`ci_rca` recommendation source.

Vocabulary: **tier** = one of `pre` (`validate --pre`, edit-loop), `presubmit` (`validate`, local
pre-push), `CI` (remote merge gate). **warn/strict** = `CI_RCA_STRICT_MODE` values; warn logs +
stamps a marker and accepts, strict raises before write. **bundle** = `evidence_bundle.json`
(deterministic facts). **bundle-wins** = on agent/bundle disagreement the bundle is authoritative.
**recurrence_class** = `novel | instance_of_known_pattern | regression`. **context_v2_json** = the
structured `CiRcaContext` blob carried on a `ci_rca` rec.

---

## 4. SETUP (run once, at start; expected and permitted)

1. Generate the operational caches (DEDUP, Section 13, and the empirical pass, Section 11, depend on
   them):
   ```bash
   bin/venv-python -m scripts.session_preflight --roadmap-detail full
   ```
   This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl` (the
   recommendations read cache) and computes the live CI-RCA telemetry gauges. These are gitignored;
   regenerating them is not a tree edit.
2. Confirm the branch and derive the base per Section 16.

DEGRADED PATHS (never abort; set a flag, downgrade confidence, proceed):
- IF cache-gen fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`, mark every
  finding's `confidence` `HYPOTHESIS` and every `roadmap_crossref.dedup_hit_count` null. For any
  finding that would have relied on a live gauge from `logs/.preflight-report.json`, set that finding's
  `confidence: HYPOTHESIS` and write `gauge unverified (degraded)` into its `severity_rationale` --
  there is no separate `unverified` field; `confidence: HYPOTHESIS` plus the note is its home.
  Proceed with static analysis of the code surfaces (which need no creds).
- IF an anchor in Section 10 does not resolve: record it in `meta.stale_anchors` and re-derive the
  fact from the file; do not treat the prompt's line number as ground truth.

---

## 5. NORTH STAR (the bar the rubric references; each is a bar you JUDGE against, not a slogan to
pattern-match)

- **NS1 -- Deterministic beats model on disputable facts.** When a fact can be computed from repo
  state, the computed value must win over the LLM's assertion (bundle-wins). Judge whether the
  division of labour actually places the disputable facts on the deterministic side.
- **NS2 -- A guarantee is real only if enforced.** A check that exists but runs in warn (logs,
  accepts) is a *signal*, not a *guarantee*. Judge each advertised guarantee against whether it is
  actually in force in the deployed configuration.
- **NS3 -- The self-improving loop must CLOSE.** A filed RCA whose preventive action does not
  measurably reduce recurrence is an open loop. Judge whether a fix provably reduces the failure
  mode or whether the same failure re-files.
- **NS4 -- The contract is the source of truth.** Divergence between the contract text and the
  implementation is a first-class defect if it can mislead a reader relying on the contract. Judge
  whether a coherence mechanism exists and holds.
- **NS5 -- Depth must be measurable.** Without observability that distinguishes rescue-style
  filings from real RCA at scale, the methodology is write-only. Judge whether the live gauges
  actually measure the guarantee, or only proxies of it.
- **NS6 -- Structural floors are signals, not guarantees, and the system must say so.** A
  keyword+citation terminus check raises the cost of shallow output but cannot verify causal
  antecedence. Judge whether the system acknowledges its semantic ceiling AND actually routes the
  residual to a human/critique surface that runs.

---

## 6. THE QUESTIONS

Answer each as a first-class output entry (Section 14 `question_answers`). Pinned verdict enum per
question is given. Cite finding ids as basis.

- **Q1 -- Is the guarantee in force?** `CI_RCA_STRICT_MODE=warn` and the live warn-mode reject rate
  is ~0.44 (re-derive from `logs/.preflight-report.json` `ci_rca_telemetry.warn_mode_reject_rate`).
  So the coded enforcement accepts writes it is designed to reject. Assess: does the contract
  advertise a depth/anti-rescue guarantee it does not currently enforce? Is the warn->strict flip
  (T1.13 c2) REACHABLE given that flipping today would reject ~44% of real `ci_rca` writes, or is
  warn a stable equilibrium the design cannot escape? Verdict enum: `in_force | partially_in_force |
  not_in_force`.
- **Q2 -- Does the loop close?** Re-derive the recurrence concentration (Section 11). Assess whether
  `file_rec` for `source=ci_rca` has any WRITE-TIME dedup/recurrence guard, or whether dedup is
  entirely post-hoc (advisory preflight surfacing + back-validation). Does a filed preventive_action
  provably reduce the failure mode, or does the same root cause re-file? Verdict enum: `closes |
  partial | does_not_close`.
- **Q3 -- Is the deterministic/model division sound?** Trace the bundle-wins cross-check
  (`_run_ci_rca_cross_check`). Assess whether the deterministic bundle actually constrains the depth
  the contract claims, or whether the enforced floor (why_chain length + terminus keyword + file:line
  regex) is a structural signal the model can satisfy vacuously (the contract admits this in Section
  5 -- test whether that admission is adequately compensated). Verdict enum: `sound | adequate |
  weak`.
- **Q4 -- Contract<->implementation coherence.** The INTENT doc is STALE-annotated throughout
  (Athena/Iceberg -> DuckLake). Assess whether the drift undermines the doc's source-of-truth role
  for a reader who relies on it, and whether any mechanism keeps contract and code coherent (a
  validator, a test, a review gate). Verdict enum: `coherent | drifting | incoherent`.
- **Q5 -- Frontier benchmark (EXTERNAL CHECKLIST).** Rate the subsystem property-by-property against
  NAMED external practice. This question's `external_checklist` field is the SOLE source the maturity
  top tier reads. Assess each: (a) blameless-postmortem discipline (blame-free, systemic focus);
  (b) five-whys / genuine causal-antecedence (not restated symptoms); (c) error-budget / SLO-style
  gating of the loop; (d) shift-left gate placement (earliest-viable-gate computation); (e)
  flake/quarantine management for recurring failures; (f) deterministic-over-LLM adjudication of
  disputable facts. For each: `met | partial | missed` with one evidence anchor. `partial` REQUIRES
  an argued property-matched compensating control in the evidence string (which may run longer than a
  bare `file:line` when rating `partial` -- append the control argument after the anchor). Q5's
  overall rollup verdict enum is `strong | adequate | weak`: predominantly `met` -> strong; a mix
  with no `missed` -> adequate; any `missed` -> weak.
- **Q6 -- Questions the requester did not think to ask.** Seeds (answer AND extend with your own):
  (i) does the 20-minute workflow timeout + `--max-turns 30` bound the agent enough that it cannot
  itself run away the way a naive RCA prompt would? (ii) is there a failure mode where the agent
  files a rec the cross-check accepts in warn but strict would reject, and that thin rec then shapes
  a `/plan` architecture decision before anyone notices? (iii) what happens to the ~44% would-reject
  recs when strict flips -- is there a migration/backfill path, or do those CI failures become
  unfilable? (iv) is the abstention path (`rca_confidence=undetermined`) a silent depth-bypass at
  scale? (v) the diagnosis agent reads the untrusted failed-CI log (`/tmp/ci-rca-failed.log`) as
  input -- is that a prompt-injection surface by which a crafted failing run could steer the agent's
  `file_rec` / `context_v2_json` output, and what compensates (the head-repo==base-repo +
  default-branch job gate, the restricted `--allowedTools` set)? Assess against VD6. (vi)
  `.github/workflows/ci-rca.yml` has NO top-level `concurrency:` block (grounding map). Can two
  failing workflows -- or a retried run -- dispatch concurrent `ci-rca` runs that double-file recs on
  the same root cause? Is ANY of the observed duplicate-storm (Section 11) a cross-run DISPATCH race
  rather than only a recurrence-class/dedup gap? What compensates (the per-category commit-status
  "Dedup guard" step in the workflow, the `workflow_dispatch force_rca` bypass), and does it
  property-match a cross-run double-file?

---

## 7. RUBRIC (rate each dimension per surface S1-S4; enum `strong | adequate | weak | absent | n/a`)

`n/a` is correct and costless where a dimension does not structurally apply to a surface -- never
manufacture a rating or finding to fill a cell.

- **VD1 -- guarantee-in-force** (does the enforcement actually run in the deployed config, or only
  exist in code). Served by Q1.
- **VD2 -- evidence determinism / reproducibility** (bundle computation, SHA-256 anchoring, AST
  walker stability, hash canonicalisation). Served by Q3, Q5(f).
- **VD3 -- loop-closure / anti-recurrence** (write-time dedup, back-validation efficacy, does a fix
  reduce recurrence). Served by Q2, Q5(e).
- **VD4 -- contract<->implementation coherence** (staleness, SoT integrity, coherence mechanism).
  Served by Q4.
- **VD5 -- observability / measurability** (do gauges measure the guarantee or a proxy; is the
  strict-rejection blind spot covered). Served by Q1, Q5(c).
- **VD6 -- adversarial-agent resistance** (terminus token-sprinkling, dispute-as-bypass, override
  abuse, self-attested confidence). Served by Q3, Q6.

---

## 8. CANDIDATE OBSERVATIONS (neutral facts + hypotheses to adjudicate -- NOT findings)

Each is stated neutrally. Trace before you convict; a candidate may resolve to a finding, a
rejected_candidate, or a reframe.

- **C1.** `config/feature_flags.yaml` sets `CI_RCA_STRICT_MODE: warn`; the live
  `ci_rca_telemetry.warn_mode_reject_rate` is ~0.44 with a "may need tuning" note at the 0.25 alert
  threshold; the Phase-4 strict-flip promotion gate is a SEPARATE, tighter bar (<=0.05 -- re-derive
  both from `scripts/session_preflight.py`). Hypothesis to test: the enforcement spine's central
  guarantee is coded but not in force, and the ~0.44 rate sits ~9x above its own <=0.05 activation
  gate.
- **C2.** `file_rec` (`scripts/ops_data_portal.py`) has a source-file gate and a schema/cross-check
  path for `source=ci_rca`, but no observed WRITE-TIME dedup against existing open recs on the same
  file/root-cause. `scripts/session_preflight.py` `_derive_forward_fix_recursion` surfaces files with
  >=3 `ci_rca` recs advisorily. Hypothesis: recurrence is detected only post-hoc, not prevented.
- **C3.** A cluster of `ci_rca` recs targets one test file with the same root cause and continues
  after a preventive guard for that class landed (PR #478, `test-count-coupling-guard`). Hypothesis:
  the preventive_action did not hold, OR the guard does not cover the recurring case; the
  back-validation match key is file-only (INTENT Section 7.2, a known weaker heuristic). Adjudicate
  which.
- **C4.** `docs/INTENT-ci-rca-methodology.md` Sections 1/3/7 carry `[STALE]` annotations pointing to
  a retired Athena/Iceberg backend. Hypothesis: contract drift; assess whether any test/validator/
  review gate keeps the contract coherent with the DuckLake implementation, or whether the doc can
  mislead a future reader.
- **C5.** The enforced `why_chain` terminus check is (a) a systemic-keyword set and (b) a
  `file:line` citation regex (`CiRcaContext` validators). Section 5 of the contract states this is a
  depth SIGNAL, not a GUARANTEE, and routes causal-antecedence review to `/plan-critique` + human PR
  review. Hypothesis: the residual is adequately routed -- OR `/plan-critique` does not actually run
  on every `ci_rca` rec before it shapes a plan. Trace whether the routing is real.
- **C6.** Override (`why_chain_terminus_override`) and dispute (`ci_rca_evidence_dispute`) paths are
  typed and rate-limited but self-attested; the only backpressure is a rate limit + `/plan` review.
  Hypothesis: an adversarial or lazy agent could route around the floor via these paths at a rate the
  gauges do not yet alert on (the strict-mode-rejection and dispute-throttle gauges are deferred to
  telemetry Phase 4 / T2.36).
- **C7.** The bundle-absent and S3-missing paths in `_run_ci_rca_cross_check` fail-loud in strict but
  accept-with-marker in warn; the abstention path (`rca_confidence=undetermined`) routes to
  "mandatory human review" via preflight. Hypothesis: in the current warn deployment, a bundle-absent
  or abstaining rec is accepted with only a log/marker -- assess whether "mandatory human review"
  is actually mandatory (blocking) or merely surfaced.
- **C8 (POSITIVE CONTROL -- framed to test your skepticism, not to be confirmed).** C1-C7 all lean
  toward "something is insufficient"; C8 deliberately does not. The multi-failure filing path is
  "sequential, not transactional" (INTENT Section 3.3 / Section 4 check 9): N failed checks in one
  run produce N separate recs via N `file_rec` calls with no cross-rec atomicity, so a partial batch
  (first rec files, second fails) is possible. This LOOKS like a correctness hole. Hypothesis to
  adjudicate BOTH ways: is it a real defect, or a deliberate, adequately-compensated design (the
  contract addresses partial state; `/plan` reviews it; a per-run atomic transaction may be
  unwarranted)? Adjudicate C8 on its evidence like any other candidate -- do NOT force it into
  `findings` to keep the candidate set "productive", and do NOT wave it into `rejected_candidates` to
  satisfy the "positive control" label. Let the trace decide.

---

## 9. DEEP-DIVES

- **DD-A (feeds Q1, Q6-iii, VD1/VD5).** Trace the warn->strict path end to end: `get_ci_rca_strict_mode`
  -> the warn branches in `file_rec` and `_run_ci_rca_cross_check` that call `_stamp_warn_mode_reject`
  -> the T1.13 c2 exit criterion text in `docs/ROADMAP-PLATFORM.yaml` -> the Phase 4 back-validation
  path (`back_validate_ci_rca`, `--back-validate` CLI). Produce: is the flip mechanically gated on a
  metric that the current corpus cannot satisfy, and what would have to change for c2 to be met.
- **DD-B (feeds Q2, Q3, VD2/VD3).** Trace one bundle from generation to enforcement:
  `ci_rca_taxonomy.classify_failures` -> `ci_rca_tier_map.build_tier_membership` +
  `compute_earliest_viable_gate` -> `ci_rca_evidence.generate_bundles` (SHA-256) ->
  `_run_ci_rca_cross_check` checks 1-4. Produce: at which step could a wrong-but-trusted value enter,
  and does bundle-wins actually catch an agent that mirrors the bundle's own (possibly wrong)
  `earliest_viable_gate` without independent judgment.

---

## 10. GROUNDING MAP (verified anchors -- this map spends your cognition on judgment, not grep;
verify each before relying, and record misses in `meta.stale_anchors`)

Line numbers are as of the drafting commit and may drift; the file and identifier are the durable
anchors.

**S1 -- diagnosis agent**
- `.github/workflows/ci-rca.yml` (~340 lines): `on: workflow_run` for `[CI, Main Canary,
  terraform-apply-sandbox]` completed + `workflow_dispatch`; job `if:` gates on
  `conclusion==failure` AND head-repo==base-repo AND head-branch==default-branch (~line 34);
  `timeout-minutes: 20` (~36), NO top-level `concurrency:` block; installs
  `@anthropic-ai/claude-code@2.1.148`; runs `claude -p ... --max-turns 30` with a restricted
  `--allowedTools` set (~285-288); evidence step `continue-on-error: true` (~170,178) invokes
  `scripts.ci_rca_evidence --emit-dir` (~184-189) and computes `bundle_absent` (~209-218); filing
  detected via `scripts.ci_rca_filing` `FILED:` marker (~294), fails loud if none (~295-298).
- `.claude/agents/scheduled/ci-rca.md` (~191 lines): 6-step methodology (read failed log -> read
  bundle -> load guidance -> compose `context_v2_json` CiRcaContext v2 -> `file_rec --source ci_rca
  --priority Critical` -> report with terminal `FILED: <rec_id>` marker); read-only tools; no
  autonomous fix (Decision 72).

**S2 -- evidence pipeline**
- `scripts/ci_rca_evidence.py` (~317): `generate_bundles` (~180), `upload_and_persist` (~85),
  `_canonical_json` (~59), `main` (~266).
- `scripts/ci_rca_taxonomy.py` (~173): `classify_failure` (~52), `classify_failures` (~107),
  `resolve_workflow_tier` (~146).
- `scripts/ci_rca_tier_map.py` (~284): `build_tier_membership` (~107), `probe_runtime` (~180, N=5
  drop-extremes), `compute_earliest_viable_gate` (~239); `AST_WALKER_VERSION=1`.
- `scripts/ci_rca_vacuous_pass.py` (~161): `compute_escape_mode` (~130), `parse_vacuous_pass` (~31).
- `scripts/ci_rca_filing.py` (~75): `extract_filed_rec_id` (~21, matches only `FILED: rec-NNN`).
- `scripts/ci_rca_probe_health.py` (~256): `compute_abstention_rate` (~85), `escalate` (~182).
- `scripts/ci_rca_back_validation.py` (~143): `find_preventive_regressions` (~76, file-only match).
- `config/ci_rca_taxonomy.yaml` (~98): keys `failure_categories`, `agent_only_categories`,
  `function_to_category`, `step_name_to_category`, `log_pattern_to_category`, `workflow_to_tier`.
- Guards: `scripts/checks/ci_guards/validate_ci_rca_taxonomy.py` (`validate_ci_rca_taxonomy`, ~line
  9; runs in `--pre` AND full per `scripts/checks/registry.py`), `validate_ci_rca_trigger.py`
  (`validate_ci_rca_trigger`, ~line 12; full tier).

**S3 -- enforcement spine (`scripts/ops_data_portal.py`)**
- `file_rec` (~999): ci_rca source-file gate (~1045); `ci_rca_evidence_dispute` carve-out (~1054,
  runs before and short-circuits the ci_rca block); `source=ci_rca` context_v2 warn-validation
  (~1076-1109: strict raises ~1080, warn stamps ~1085); cross-check gate (~1112, only when
  `context_v2_json is not None and not _migration_mode`).
- `_run_ci_rca_cross_check` (~367-504): bundle-absent fail-loud (~391; `undetermined` returns ~399,
  strict raises ~402, warn stamps `bundle_absent` ~404); S3 existence (~408-430:
  `missing`/`degraded`/`fail_open`); SHA-256 load+verify (~432-439, mismatch always raises); four
  bundle-wins checks (~441-494: check-1 undetermined-mirror ~450, check-2 evg-mismatch ~458, check-3
  escape_mode ~468, check-4 vacuous_pass author-discipline ~477); disposition (~496: strict raises
  ~500, warn stamps `cross_check_check_N` ~503).
- Helpers: `get_ci_rca_strict_mode` (~121, default `warn`), `_validate_ci_rca_context_v2` (~225),
  `_stamp_warn_mode_reject` (~352), `back_validate_ci_rca` (~507, `--back-validate` CLI ~1761),
  daily cap `_CI_RCA_BACK_VALIDATE_DAILY_CAP=20` (~102).
- Models: `CiRcaContext` (~168-222; `schema_version` 1..2, `why_chain` len 3-7 each 40-250 chars,
  terminus validator ~207, `recurrence_class` enum ~181, portal-only `warn_mode_reject` field ~195);
  `_DetectionGap` (~151-165; `earliest_viable_gate` {pre,presubmit,CI,undetermined},
  `actual_gate_that_caught_it` {pre,presubmit,CI}, `gap_explanation` 120-600 + file:line,
  `escape_mode` enum); `CiRcaEvidenceDispute` (~236-247; `disputed_field`
  {earliest_viable_gate,actual_gate_that_caught_it,failure_category}); `_WHY_CHAIN_SYSTEMIC_KEYWORDS`
  (~103-117), `_WHY_CHAIN_CITATION_RE` (~118).
- Tests (`tests/test_ops_data_portal.py`): `TestCiRcaSourceFileGate` (~881),
  `TestCiRcaSchemaEnforcement` (~1533), `TestCiRcaEvidenceDispute` (~1893),
  `TestCiRcaCrossCheckSpine` (~2002), `TestBundleAbsentFailLoud` (~2269), `TestEvidenceS3Existence`
  (~2326), `TestWarnModeRejectMarker` (~2427). Note: `test_flag_default_is_warn` (~1541) pins the
  warn default; no exact-count `len(X)==N` assertion against ci_rca collections was found (three
  membership-over-fixed-literal-list asserts exist: schema 6-field ~1576, dispute 5-field ~1990,
  disputed_field 3-value ~1932).

**S4 -- observability + governance**
- `scripts/session_preflight.py`: `_derive_ci_rca_open` (~435), `_derive_ci_rca_undetermined_open`
  (~466) -> `print_ci_rca_undetermined_recs` ("CI-RCA Mandatory Human Review" ~497),
  `_compute_ci_rca_abstention` (~513), `_compute_ci_rca_telemetry` (~575, warn-mode-reject-rate +
  thresholds ~571), `_derive_forward_fix_recursion` (~740, files with >=3 ci_rca recs).
  `scripts/executor/rec_write_guidance.py` (~110) returns the CiRcaContext schema for `--guidance`.
- `docs/ROADMAP-PLATFORM.yaml` T1.13: c1 `met` (all six follow-on plans + more landed); c2 =
  strict-flip after Phase-4 back-validation AND c7 probe-abstention fail-loud (c12(i) is the
  abstention-rate gauge); c12(ii)
  bundle-absent fail-loud (implemented), c12(iii) preventive-action back-validation (implemented,
  file-only). T3.4 = STRATEGIC control-plane loop closure, `not_started`, depends on T1.13.
- `docs/INTENT-ci-rca-methodology.md` (~582 lines): the contract; Sections 1/3/7 `[STALE]`
  (Athena/Iceberg -> DuckLake, Decision 84/81); Section 5 "What this contract DOES NOT do" (semantic
  ceiling admission); Section 6 phased warn->strict rollout; Section 7 observability (re-grounded to
  warm-cache gauges).

**Governing decisions** (grep the header, do NOT full-read DECISIONS.md): Decision 55 (RCA-first,
forward-fix never workaround), 60 (two-tier validation), 66 (Precision Context Injection), 72
(RCA-as-Plan-Source, no autonomous fix, consumed by `/plan`), 73 (two-tier diff-aware CI,
forward-fix), 84/81 (DuckLake retarget), 88 (Neon catalog egress budget; the ci_rca gauges cite it
for zero-egress warm-cache reads).

**Live gauges to RE-DERIVE from `logs/.preflight-report.json`** (do not trust these prompt values;
read the JSON): `ci_rca_telemetry.warn_mode_reject_rate`, `.recurrence_class_distribution`,
`.warn_mode_reject_count`/`.ci_rca_total`; `ci_rca_abstention_gauge`; `ci_rca_back_validation` (the
preventive-regression pairings); `ci_rca_recs` (open critical ci_rca recs).

---

## 11. EMPIRICAL PASS (hard bounds -- do NOT exceed)

The `logs/.recommendations-log.jsonl` cache holds ~125 `source=ci_rca` recs. Do NOT read them all.
Run these EXACT commands ONCE each, then reason from the output. Do NOT invent open-ended greps or
re-run these.

```bash
# 1. Recurrence concentration: ci_rca recs per file (top offenders)
bin/venv-python -c "import json,collections; c=collections.Counter(json.loads(l).get('file','?') for l in open('logs/.recommendations-log.jsonl') if json.loads(l).get('source')=='ci_rca'); print(c.most_common(8))"

# 2. Status split of the TOP-recurring file's recs (open vs closed = is the loop closing?).
#    Derives the file from the same corpus as command 1 -- do NOT hardcode a filename.
bin/venv-python -c "import json,collections; rows=[json.loads(l) for l in open('logs/.recommendations-log.jsonl')]; ci=[r for r in rows if r.get('source')=='ci_rca']; f=collections.Counter(r.get('file','?') for r in ci).most_common(1)[0][0]; c=collections.Counter(r.get('status') for r in ci if r.get('file')==f); print(f, dict(c))"

# 3. Live telemetry gauges (already computed by preflight)
bin/venv-python -c "import json; d=json.load(open('logs/.preflight-report.json')); print({k:d[k] for k in d if 'ci_rca' in k.lower()})"
```

Counterfactual test applied to each empirical claim: "would this signal still be true if the
enforcement spine were deleted?" -- if yes, the spine is not the thing producing the signal. Tag each
finding `evidence_kind: static` (from reading code) or `observed` (from the rec corpus / live
gauges). An `observed` finding OUTRANKS a `static` one at equal severity. Sample at most the 25
most-recent `ci_rca` recs if you need individual context beyond the aggregates above; do NOT exceed
25.

---

## 12. METHOD (phases; synthesis and maturity LAST)

- **P1 Read** the four surfaces via the GROUNDING MAP (verify anchors; do not re-discover what is
  handed to you).
- **P2 Trace** DD-A and DD-B end to end.
- **P3 Empirical** pass (Section 11), bounded.
- **P4 Adjudicate** each candidate C1-C8 to a finding / rejected_candidate / reframe (C8 is a
  positive control -- adjudicate it genuinely both ways on the evidence; do not assume its
  disposition).
- **P5 Rate** the rubric (Section 7) per surface.
- **P6 Dedup** every prospective finding (Section 13) before it enters `findings[]`.
- **P7 Synthesise**: answer Q1-Q6, fill the decision block, compute maturity LAST (Section 15).

You are handed the discovery. Do NOT spend the session re-grepping the tree. If you find yourself
running more than a handful of exploratory commands beyond Section 4 and Section 11, STOP and
synthesise -- the map is the discovery.

---

## 13. DEDUP DISCIPLINE (before filing ANY finding)

Grep the ownership surfaces and record the negative search on the finding
(`roadmap_crossref.dedup_search_terms`, `.dedup_hit_count`). A finding without a recorded search is a
HYPOTHESIS, not CONFIRMED.

```bash
# roadmap + decisions ownership
grep -n "ci_rca\|CI_RCA\|strict_mode\|back_valid\|recurrence" docs/ROADMAP-PLATFORM.yaml | head -40
grep -niE "ci.?rca|strict.?mode" docs/DECISIONS.md | head -20
# open recs already owning nearby territory (the cache is the read surface)
grep -o '"title": "[^"]*"' logs/.recommendations-log.jsonl | grep -i "ci_rca\|strict\|recurrence\|dedup\|count" | head -20
```

A hit means the territory is OWNED: classify the finding `planned-insufficient` / `planned-unbuilt`
(sufficiency assessment against the owning item), NOT a fresh `novel` discovery. If
`meta.degraded_dedup=true`, mark hit counts null and confidence HYPOTHESIS.

**Deliberate constraints -- DO NOT FLAG (each with its owner):**
- Warn-default and the phased warn->strict rollout are deliberate (INTENT Section 6). Do not flag
  "flag defaults to warn" as a bug per se. (Q1's question of whether the flip is REACHABLE is fair
  game.)
- The executor is frozen (Decision 67); `ci_rca` recs are consumed by `/plan`, not an executor. Do
  not flag "no executor consumer".
- Athena/Iceberg staleness in the INTENT doc is known and migration-tracked (Decision 84/81). Do not
  file a fresh "system uses Athena" finding. (Q4's SoT-integrity question is fair game.)
- Causal-antecedence is deliberately unenforceable deterministically and routed to `/plan-critique`
  + human review (INTENT Section 5). Do not flag "why_chain doesn't verify causality" as novel; DO
  test whether the routing actually runs (C5).
- File-only back-validation match key is a KNOWN weaker heuristic (INTENT Section 7.2, deferred). Do
  not flag as novel; assess sufficiency.
- Strict-mode-rejection and dispute-throttle gauges are deferred to telemetry Phase 4 / T2.36. Do
  not flag their absence as novel; assess whether the deferral leaves a live blind spot.
- Lambda scheduled agents are disabled; `ci_rca_probe_health` substitutes via preflight. Known.
- T3.4 is STRATEGIC / `not_started` (Decision 67 suspends STRATEGIC work). Do not flag as
  pejoratively unstarted.

---

## 14. OUTPUT (the pinned contract -- emit BOTH deliverables)

Write `audits/ci-rca-system-<sha>.yaml` (the structured audit) and `audits/ci-rca-system-<sha>.md`
(a prose companion, <= ~1500 words, the executive layer a human reads first: lead with the Q1-Q6
verdicts, the single highest-leverage change, and the strict-flip decision). `<sha>` is the base
short sha from Section 16, identical across both filenames and `meta.audited_commit`.

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported name>, methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4],
         degraded_dedup: false, contract_notes: "", stale_anchors: [],
         dossier_fact_check: []}   # any prompt-quoted number your re-derivation contradicts: {claim, prompt_value, your_value}
  question_answers:
    - {q: Q1, verdict: <in_force|partially_in_force|not_in_force>, basis: [<ids>], prose: ""}
    - {q: Q2, verdict: <closes|partial|does_not_close>, basis: [], prose: ""}
    - {q: Q3, verdict: <sound|adequate|weak>, basis: [], prose: ""}
    - {q: Q4, verdict: <coherent|drifting|incoherent>, basis: [], prose: ""}
    - {q: Q5, verdict: <strong|adequate|weak>, basis: [], prose: "",
       external_checklist: [{property: <a..f>, rating: met|partial|missed, evidence: "file:line|gauge"}]}
    - {q: Q6, answers: [{question: "", answer: "", basis: []}]}   # answer seeds i-vi AND extend
  strict_flip_readiness:        # the decision block (Q1 prose points here)
    spine: {verdict: <keep_warn|flip_strict_now|flip_strict_after_fix|redesign>,
            mechanism: "", what_changes: "", cost: "", rationale: "",
            confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<ids>]}
    # ... S2, S3, S4
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|gauge", note: ""}
    # ... every applicable (surface, dimension) cell; n/a where structurally inapplicable
  findings:
    - {id: CIRCA-01, surface: <S1|S2|S3|S4|shared>, question: <Q1..Q6>, dimension: <VD1..VD6>,
       title: "", evidence: "file:line|rec-id|gauge", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "", compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale: "", confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0, planned_unbuilt_count: 0,
            top_improvements: [<ids>], highest_leverage_change: <id>,
            maturity_S1: <>, maturity_S2: <>, maturity_S3: <>, maturity_S4: <>, maturity_overall: <>}
```

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered candidates live in
`rejected_candidates`, NOT findings. `rubric_ratings` / `question_answers` / `strict_flip_readiness`
are systems-of-record referenced FROM findings, never re-counted. `top_improvements` and
`highest_leverage_change` MUST be finding ids -- EXCEPT when `total_findings == 0`, in which case
`top_improvements` is `[]` and `highest_leverage_change` is null (a zero-finding audit is a valid
result per Section 17; do not invent a finding to populate these).

---

## 15. SEVERITY + MATURITY (assign AFTER judgment; maturity LAST)

Severity by DEFECT CLASS (not inherited from this prompt's framing):
- **critical** = the subsystem can produce a wrong-but-trusted RCA signal that misdirects the
  self-improving loop, OR an enforcement the contract claims to provide is not actually in force in a
  way that materially misleads a consumer.
- **high** = a weakness that materially caps RCA quality or loop-closure AND whose compensating
  controls you judged insufficient.
- **medium** = a real gap with a clear fix and bounded blast radius.
- **low** = clarity / wording / polish.

Compensating-control rule (PROPERTY MATCH, required whenever a control is the reason for dismissal or
severity reduction): name the property the control exercises, cite where it operates (mechanism or
file:line), and state why the control would FAIL if the defect were real. A control that cannot catch
the break neither lowers severity nor justifies dismissal. (E.g. "back-validation surfaces it in
preflight" only compensates for recurrence if it actually BLOCKS or DEDUPS the write -- surfacing
alone does not property-match a write-time-prevention claim.)

Maturity per surface, computed LAST, top-down, FIRST MATCH WINS. Pinned thresholds:
- **frontier** = 0 open critical AND 0 open high findings on that surface. (Per-surface frontier
  gates on finding counts ONLY; the subsystem-wide Q5 `external_checklist` does NOT gate any
  individual surface -- it gates `maturity_overall` only, below.)
- **strong** = 0 critical AND <= 1 high.
- **solid** = <= 1 critical.
- **nascent** = otherwise.
The top rating remains reachable if you argued a property-matched compensating control -- the framing
does not foreclose it. `maturity_overall` is computed from the finding set as a whole (need NOT equal
the min or mode of the per-surface values), applying the SAME thresholds to all findings across all
surfaces, with ONE addition: `maturity_overall` reaches `frontier` only if 0 critical AND 0 high
across ALL surfaces AND every Q5 `external_checklist` property is rated `met` or `partial` (never
`missed`); otherwise it takes the strong/solid/nascent threshold that matches the full finding set.
Defend `maturity_overall` in the `.md` companion.

confidence: CONFIRMED requires a trace to file:line, a rec-id, a live gauge value, or a named source.
Anything less is HYPOTHESIS.

---

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. This sha
   IS the audited tree; use it in both deliverable filenames, the branch name, and
   `meta.audited_commit`. IF `git fetch` fails (network/egress down): do NOT abort -- fall back to
   the already-local `origin/main` ref (`git rev-parse --short origin/main` still resolves it), note
   `base fetch failed; used local origin/main ref` in `meta.contract_notes`, and proceed.
2. `git switch -c audit/ci-rca-system-<sha> origin/main` (a clean two-file diff off the audited base;
   this is a deliberate, documented exception to the `claude/*` session-branch rule -- the audit
   session needs the diff to be only its two deliverables).
3. Repo-wide `validate --pre` is advisory outside CI here: a clean YAML parse of the two deliverables
   is the real pre-push gate. An unrelated `validate --pre` failure goes in `meta.contract_notes` and
   is NEVER fixed (write boundary).
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, `--no-gpg-sign` if signing is
   unavailable. `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title
   `audit: CI-RCA subsystem (agent + evidence pipeline + enforcement spine + roadmap)`, body = the
   `summary` block in a ```yaml fence + a 2-3 sentence lede). Then END THE TURN -- do not poll, do
   not merge, do not subscribe, do not self-approve.

---

## 17. GUARDRAILS

Read-only except the two deliverables. The closed list of files you may create or modify:
`audits/ci-rca-system-<sha>.yaml` and `audits/ci-rca-system-<sha>.md`. Do NOT: write any other file,
call the ops portal / file recs, edit source, touch the roadmap / DECISIONS / INTENT doc / warehouse,
open a PR against anything but your two files, or run the `validate` autofixers. Regenerating
gitignored caches (Section 4) is permitted and is not a tree edit; never commit them.

Honesty clauses: fewer than ~6 surviving findings is a VALID result -- state it, do not pad. A run
that merely confirms C1-C8 has failed; overturning a candidate with evidence is a high-value result.
Precision over volume. Every claim CONFIRMED or HYPOTHESIS. Challenge the framing -- including this
prompt's reframe (built-and-warn vs planned): if the evidence says the "planned surface is narrow"
premise is wrong, say so in `meta.dossier_fact_check` and reframe. You draft; the human disposes.
