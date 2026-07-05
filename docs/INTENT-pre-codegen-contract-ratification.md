# INTENT - Pre-Codegen Contract Ratification

> Canonical projection: this INTENT proposes a load-bearing platform ritual + a new Candidate Decision (CD.25) + a set of additions to `docs/ROADMAP-PLATFORM.yaml`. The authoritative source for tier sequencing remains the roadmap YAML; this INTENT is the deliberation record that motivates the edits. Once the proposed CD ratifies (via T0.7b log-decision Lambda), the rules established here become enforceable platform discipline.

## Status

DRAFT v3. Round-3 revision after Step 10 round-2 critique: architect lens returned REVISE with 10 issues (2 HIGH); adversarial risk lens returned REVISE with 7 new risks (2 HIGH) + verification of round-1 resolutions. Round-2 round-1-fixes mostly verified RESOLVED; round-2 new HIGH issues addressed in v3: (H1) CD.17 vs CD.16 conflation -- v2 routed Class B Lambda contract deferral through CD.17 (STRATEGIC plan-artefact freeze) when it should have been CD.16 (per-Lambda Lambda-deploy gating); (H2) internal contradiction between Invariant 3 (allows prose description/semantics improvements without semantic_break) and Invariant 4 + Part 9I gate (rejects any description/semantics diff without semantic_break) -- resolved via new `amendment_log` `change_class` discipline; (H3) `bootstrap_completion_exempt` per-item field not in T-1.5 RoadmapDocument schema -- resolved by adding `scripts/platform_roadmap.py` to T-1.12 files_in_scope; (H4) T-1.13..T-1.19 effort re-graded for larger conversions. Round-2 MED issues folded in: T-1.12 effort upgraded to L with split discipline; decomposition-children-inherit-exemption rule added; $ref resolver behaviour in T-1.12 exit_criteria; reader-discovery residual risk in Part 9; `_joins.yaml` incremental landing clause in Part 5; CD.25-scoped exemption termination clause in Part 8C; Part 11 sequencing note on CD.25's lifetime-pending state. LOW items folded.

REPORT-ONLY deliverable on `agent/pre-codegen-contract-ratification`. Round-3 critique split: architect returned PROCEED; adversarial returned REVISE with three NEW HIGH risks verified against live repo state (A1: prose_improvement self-attestation; A2: cited `scripts/roadmap_document.py` does not exist -- real file is `scripts/platform_roadmap.py`, which uses `extra="ignore"` so new fields would silently drop; A3: `.claude/skills/implement/SKILL.md` does not read `decomposition_hints` so the M2 inheritance rule had no enforcer). After human-direction (round-3 escalation per methodology), v4 addresses all three HIGH + MED + LOW items WITHOUT a round-4 critique re-fire -- the corrections are tactical and the residual implementation-discovery cost is bounded by per-downstream-plan rediscovery during scoping. Convergence is via the methodology's "human explicitly accepts the current state with a defined deferral" path.

All follow-on plans this INTENT proposes are IMPLEMENTATION or REPORT-ONLY type, consistent with CD.17 STRATEGIC plan-artefact freeze. Class B Lambda contract ratifications gate on CD.16, not CD.17.

## Application Status

- 2026-05-24: PLAN-cd25-platform-gap-sequencing (branch `claude/cd25-platform-gap-sequencing-gS1Ja`) applies Parts 7, 8A, 8B, 8C edits to `docs/ROADMAP-PLATFORM.yaml` and rewrites the corresponding cross-roadmap edges + `known_platform_gaps[]` block + narrative prose references in `docs/ROADMAP-PRODUCT.yaml` to point at the resolved PLATFORM ids (CD.25, T-1.11..T-1.19, T0.12.5/.6/.7, T1.12, T1.14, T2.14, T3.5). Also bumps the prior `T1.12` (CI-RCA methodology contract) to `T1.13` to restore INTENT v4's claim on T1.12 for the Class B Lambda ratification wave. Subsets (d)/(e)/(f)/(g) of T-1.12 (contracts.py, CI drift gate, preflight hook, SKILL.md amendment) are deferred to named follow-on IMPLEMENTATION plans.

## Intent

Establish a **pre-codegen contract ratification ritual** as a load-bearing platform pattern. Three structural commitments:

1. **Separate "deciding what something means" from "encoding the meaning in code."** Today these activities happen in one PR. They have different cognitive modes (deliberative vs mechanical), different reviewer panels (semantic vs code), and different failure costs (semantic errors compound; code errors caught by tests). Split them into separate planning sessions.
2. **Collapse scattered field semantics into one canonical home** (`docs/contracts/{name}.yaml`). Pydantic models, Athena DDL, DQ YAML, and prose docs become *projections* of this contract, not parallel sources of truth.
3. **Make semantic evolution explicit and observable.** Versioned contracts + `_contract_version` Iceberg column + forward-compat-only default + opt-in `semantic_break` flag. Iceberg's structural-evolution rules do not solve the semantic-evolution problem; this layer does.

The pattern formalises a discipline the project already needs but has not made explicit. Without it, the AWS migration (which is "rebuild three substrates" per `INTENT-aws-migration-platform-evolution.md`) carries the current contract scatter into the personal account substrate.

## How this INTENT relates to existing artefacts

- **`docs/ROADMAP-PLATFORM.yaml`** is canonical for platform sequencing. This INTENT proposes additions to `candidate_decisions[]` (CD.25) and `tier_items[]` (new ratification predecessor items + new `depends_on` edges on existing items).
- **`docs/INTENT-aws-migration-platform-evolution.md`** is the strategic frame for the AWS migration. This INTENT lands the contract-design discipline that the migration substrate inherits. The two are siblings, not parent/child.
- **`docs/PROJECT_CONTEXT.md`** documents the Single Portal Invariant, the warehouse-as-source-of-truth invariant, and the Precision Context Injection rule. Nothing here violates them; Part 4 explicitly extends the warehouse invariant with the contract-versioning column.
- **`src/schemas/`** is the Pydantic foundation (T0.12, CD.12). This INTENT does not amend the marker vocabulary; markers stay enforcement-side. Semantics live one level up in `docs/contracts/`.
- **`docs/contracts/`** is an existing directory (`instruction-architecture.md`, `inference-provider.md`). This INTENT extends it as the canonical home for per-table and per-Lambda contract YAMLs.

## Decision 67 freeze interaction (round-3 correction: two CDs, not one)

Decision 67 bundled two distinct freezes. The roadmap explicitly **splits them across two separate candidate decisions** (verified against `docs/ROADMAP-PLATFORM.yaml`):

1. **STRATEGIC plan-artefact freeze (planning-time gate, governed by CD.17).** CD.17's reversal trigger is T4.2 stability + grace periods (`docs/ROADMAP-PLATFORM.yaml:437+`). STRATEGIC plan artefacts are blocked at planning time. This INTENT and all follow-on plans it spawns are REPORT-ONLY (for ratifications) or IMPLEMENTATION (for codegen and roadmap edits). Where a ratification scope is large enough that the roadmap heuristic would suggest STRATEGIC, the freeze override applies: split into multiple atomic IMPLEMENTATION/REPORT-ONLY plans during the `/plan` session.

2. **Lambda-deploy freeze (deploy-time gate, governed by CD.16, NOT CD.17).** CD.16 (`docs/ROADMAP-PLATFORM.yaml:354+`) explicitly states: "Replaces the blanket Lambda-deploy freeze from Decision 67." Under CD.16's per-Lambda gating, deploys are legal for the Lambdas a plan actually modifies. CD.16 reversal (ratification) is therefore the gate that unblocks Class B Lambda contract authoring -- not CD.17.

**Round-2 critique correction**: v1 and v2 drafts of this INTENT routed Class B Lambda contract deferral through CD.17. That was factually wrong. CD.17 governs the STRATEGIC plan-artefact half of Decision 67; the Lambda-deploy half is CD.16. Class B Lambda contract ratifications wait on **CD.16 ratification**, which is significantly earlier in the dependency graph than CD.17 reversal (CD.17 waits on T4.2 stability + T3.3 + grace periods; CD.16 has no such cascade). This correction unblocks a meaningful chunk of AWS-migration critical-path work that v2 was inadvertently pushing many tier waves later than necessary.

Both freezes are respected unconditionally, but they are gated on the right CDs.

---

## Part 1 - The problem

### 1A - Field semantics live in four places today

For `ops_recommendations` alone:

| Source | What lives there | Audience |
|--------|------------------|----------|
| `src/schemas/rec.py` (Pydantic `RecPayload`) | Types, `Literal` enums, `DqXxx` markers | Runtime validation in `ops_data_portal.py` |
| `terraform/iceberg_tables.tf:829-858` | Terse one-liner `COMMENT` per column | Humans running `DESCRIBE ops_recommendations` in Athena |
| `config/agent/data_quality/ops.yaml` | Rich `description:` (one-line) + `semantics:` (paragraph) per column | Agents at write-time via `get_rec_write_guidance()`; DQ runner |
| `docs/PROJECT_CONTEXT.md` "Recommendations Log Schema" | Narrative summary + inline `// per-field comments` | Human readers, agent context loading |

Four homes, three written by hand, all are drift candidates. Each captures partial semantics. None of them is canonical.

### 1B - Lock-in moments arrive without ceremony

The first time an Iceberg DDL is committed, the column shapes become load-bearing. The first time a Lambda Function URL goes live, the verb contract becomes load-bearing. Today these moments arrive inside ordinary implementation plans without any dedicated ratification step. The result: semantics get codified in the same PR that writes the code that consumes them. Reviewers checking the code rarely have time to deliberate the semantics underneath.

### 1C - Iceberg solves structural evolution, not semantic evolution

Iceberg's evolution rules cover:

- `ADD COLUMN` (safe)
- `RENAME COLUMN` via field-id mapping (safe)
- `WIDEN TYPE` within rules (safe; `int` -> `bigint` etc.)
- `DROP COLUMN` (unsafe; reads of historical data fail)

They do NOT cover:

- Same column name, **different meaning** over time. Iceberg has no notion of column semantics. If `source` meant "routing enum" in records written before 2026-05-06 and means "lineage key" in records written after, no schema check catches the divergence and no DQ rule catches it. Cross-table joins that rely on consistent semantics silently produce wrong answers.

This is the **semantic-evolution problem**. It is the principal load-bearing gap in the current platform discipline. Without explicit machinery, semantic drift is invisible until a query result is acted on incorrectly.

### 1D - Cognitively-different activities mixed in one PR

"Decide what this field means" needs:

- Slow deliberation
- Multi-perspective review
- Domain knowledge
- Tolerance for "we don't know yet"

"Encode the field in code" needs:

- Mechanical translation
- Tests
- Lint compliance
- "Does the typechecker pass"

Both happen today in the same PR with the same reviewer pool. The semantic activity gets short-changed because the code activity is concrete and observable while the semantic activity is abstract and easy to defer.

---

## Part 2 - The ratification ritual

### 2A - Three contract classes

The ritual applies only to contracts in three named classes. Everything else stays in normal implementation plans.

#### Class A - Data schemas that become DDL

Any Pydantic model (or YAML config that defines table shape) whose contents are projected into a persistent durable store (Iceberg, DynamoDB, an external warehouse, an exported data file format consumed by downstream systems).

Examples:

- `RecPayload` -> `ops_recommendations` Iceberg table
- `DecisionPayload` -> `ops_decisions` Iceberg table
- Future telemetry payloads -> `telemetry_sessions`, `telemetry_phases`, `telemetry_steps`, `telemetry_process_events`, `telemetry_model_calls`, `telemetry_transcripts`, `telemetry_agent_invocations`
- Future market-data and trading-output schemas (Phase 2 product work)

Non-examples (not Class A):

- Local-only structs used as function arguments
- Test fixtures
- Cache shapes that are rebuilt from authoritative storage

#### Class B - Public agent surfaces (Lambda verb contracts)

Any Lambda whose Function URL is callable by agents, whose contract (verbs, payload shapes, typed error codes, auth model) is published, and whose breaking change is expensive because external callers exist.

Examples:

- `log-rec` Lambda (T0.7a) - verb: file a recommendation
- `log-decision` Lambda (T0.7b) - verb: file a decision
- `query` Lambda (T0.7c) - verb set: read ops + telemetry tables
- `update-rec` Lambda (T1.1) - verb: amend a rec with stateful invariants
- `list-tools` + `describe` Lambda (T1.3) - verb: introspect available verbs
- `maintenance` Lambda (T1.4) - scheduled, not agent-facing -- borderline; included because it consumes the ops contracts and a wrong assumption here cascades

Non-examples (not Class B):

- Lambdas internal to one product pipeline with no agent-facing contract
- One-off batch jobs

#### Class C - Cross-system invariants

Contracts that span multiple processes and rely on shared interpretation across writers and readers. These contracts are not tied to one table or one Lambda; they are the glue.

Examples:

- The `source` lineage key (spans ops + telemetry tables; validated against `config/agent/data_quality/source_registry.yaml`)
- `project_id` (per the AWS-migration INTENT; spans every Lambda and every ops/telemetry table)
- `session_id` (spans telemetry tables; joining key)
- The `agent_type` registry (used as `source` value and as Lambda principal binding)

Non-examples (not Class C):

- Internal helper signatures
- Module-local constants

### 2B - When the ritual fires

A planning session for code that will touch a Class A, B, or C contract **must verify** that a ratified `docs/contracts/{name}.yaml` exists for the contract before scoping any codegen or implementation work.

If the ratified contract exists, the planning session proceeds normally and consumes the contract as an authoritative input.

If no ratified contract exists, the planning session either:

- (a) Authors a REPORT-ONLY ratification predecessor plan first, then re-opens the original session once the ratification merges.
- (b) Combines ratification + codegen into a single session if and only if scope is small enough that both fit cleanly. The combined session still uses the Step 10 multi-perspective critique gate against the contract YAML deliverable.

### 2C - When the ritual does NOT fire

- Internal refactors that do not change the externally-observable contract.
- Pure bug fixes within the existing contract.
- Doc-only changes.
- Tests, lint, format, dependency bumps.
- Anything outside Classes A, B, C.

This narrowness is load-bearing. Without it, the ritual becomes a tax on routine work and gets routed around.

### 2D - Anti-patterns the ritual rejects

- **Drift-by-design.** A new field added to the Pydantic model with no corresponding update to the contract YAML.
- **Implicit semantics.** A field whose meaning is "whatever the implementer assumed" because no ratification step ever forced articulation.
- **Silent semantic break.** A contract amendment that changes the meaning of an existing field without setting `semantic_break: true` and documenting the migration story.
- **Per-PR semantic drift.** Reviewers in code-review PRs amending field semantics inline, rather than through an amendment plan.

---

## Part 3 - Canonical home: `docs/contracts/{name}.yaml`

### 3A - Existing docs/contracts/ audit (round-2 critique correction)

The directory already contains eight `.md` files, not two. **Round-2 user correction: these existing markdown contracts are themselves load-bearing examples of the disease this INTENT exists to cure -- prose contracts that bind nothing at runtime, drift silently from the code that should implement them, and never trigger an enforcement gate when violated.** The default disposition for an existing `.md` contract under this ritual is therefore **convert to `.yaml` with a runtime consumer**, NOT "keep as markdown." Markdown stays only where the contract is genuinely about workflow discipline (steps to perform) rather than enforceable structure (schemas, routing maps, layer models, invocation contracts).

| Existing file | Substance | Existing runtime consumer | Disposition |
|---------------|-----------|----------------------------|-------------|
| `instruction-architecture.md` | Five-layer model (universal rules / project knowledge / slash commands / skills / executor prompts) with explicit consumers per layer | Partial: `scripts/prompt_compliance.py` checks some invariants but does not read this file | **Convert to YAML.** Layers + consumers + load-time become structured fields. `prompt_compliance.py` reads the YAML to enforce that claimed layer-X content actually loads when claimed. Ratification predecessor in T-1.13 (post this INTENT). |
| `inference-provider.md` | Provider routing rules (Bedrock / Gemini / GitHub Models), model IDs, fallback semantics, escalation | Partial: `scripts/model_registry.py` and `config/agent/copilot/model_routing.yaml` together implement routing, but `inference-provider.md` is a parallel hand-maintained doc | **Convert to YAML.** This is the textbook ratification target -- a contract that already has a runtime consumer, just needs to be the single source. `model_registry.py` reads the YAML; `config/agent/copilot/model_routing.yaml` becomes a projection or is replaced. Ratification predecessor in T-1.14. |
| `ops-data-store.md` | High-level boundary contract for Iceberg ops table schemas, partitioning, write patterns | Partial: the Iceberg DDL in `terraform/iceberg_tables.tf` implements the schemas but drifts from this doc | **Superseded by Class A YAMLs.** Per-table schema sections move into the new `ops_recommendations.yaml`, `ops_decisions.yaml`, etc. `ops-data-store.md` is retired entirely (its non-schema bits about S3 bucket / workgroup / Decision history move into a Class C-ish `storage-substrate.yaml` or into the per-table YAMLs' `governance:` blocks). Lands as part of T0.12.5. |
| `log-storage.md` | Three JSONL log-storage patterns (cloud-produced, locally-produced, hybrid) with concrete file paths and consumers | Partial: `scripts/s3_log_store.py` implements one of the three patterns | **Convert to YAML.** Patterns become structured `pattern: {producer, transport, consumer, paths}`. `s3_log_store.py` reads the YAML to know which pattern applies to which log file. Ratification predecessor in T-1.15. |
| `build-lambda.md` | Lambda build/package/deploy workflow steps | Partial: `scripts/build_lambda.py` implements the workflow but the doc is a parallel description | **Convert to YAML** (with appropriate caveats). Build steps as structured YAML; `build_lambda.py` either reads them or has a CI check that asserts equivalence. Ratification predecessor in T-1.16 (lower priority -- the build script and doc are tightly correlated today; drift risk is lower than for ops contracts). |
| `cli-json-output.md` | CLI JSON-output schema (Copilot CLI interop) | **None.** Correction (T-1.17 retirement, Decision 121): `scripts/llm_utils.py` never parsed CLI JSON output -- only process-safety helpers were relocated there. The parser (`copilot_wrapper.parse_jsonl_output`) stayed in `scripts/copilot_wrapper.py`, which was later deleted (commit 6a2f7c0, "retire Copilot-SDK residue"). | **RETIRED, not converted.** The doc and its dead parser were removed outright; T-1.17 closed by exemption rather than YAML conversion. See Decision 121. |
| `copilot-cli.md` | Copilot CLI invocation interface (args, `@filepath` semantics, `-p` quoting rules) | Partial: `scripts/copilot_wrapper.py` and the executor implement the invocation pattern; doc is a separate description | **Convert to YAML.** Invocation contract as structured YAML; the wrapper consumes it directly. Critical because the `@file` vs user-message distinction (CLAUDE.md "Copilot CLI gotcha") is exactly the kind of subtle semantic drift the ritual is built to catch. Ratification predecessor in T-1.18. |
| `delegate-cli.md` | Agent-delegation CLI invocation interface | Partial: invoked by various agent skills; no single canonical consumer | **Convert to YAML.** Same shape as copilot-cli.md. Ratification predecessor in T-1.19. |

**Sequencing**: the eight `.md` -> `.yaml` conversions land as separate ratification predecessor plans (`T-1.13` through `T-1.19`). Each is small (S effort, since the substance already exists -- the work is structuring, finding the runtime consumer, and wiring enforcement). They proceed in parallel with the new contract authorings (T0.12.5, T0.12.7) once T-1.12 (the CI drift gate from this INTENT) is in place.

**Rule** (corrected): a contract is **YAML by default**. It stays markdown only if (a) its substance is purely workflow discipline (steps to perform, recipes) with no structure to validate, AND (b) it has no plausible runtime consumer. The disease this ritual cures is "markdown contract with no enforcement." We are not creating new instances of it by exempting existing ones.

### 3B - Directory layout (target state after all ratification waves)

```
docs/contracts/
  README.md                            # NEW -- machine-readable index of all contracts
  instruction-architecture.yaml        # CONVERTED from .md (T-1.13)
  inference-provider.yaml              # CONVERTED from .md (T-1.14)
  log-storage.yaml                     # CONVERTED from .md (T-1.15)
  build-lambda.yaml                    # CONVERTED from .md (T-1.16)
  # cli-json-output.md RETIRED, not converted (T-1.17, Decision 121) -- dead Copilot-CLI parser
  copilot-cli.yaml                     # CONVERTED from .md (T-1.18)
  delegate-cli.yaml                    # CONVERTED from .md (T-1.19)
  # ops-data-store.md retired -- content split into per-table YAMLs below + storage-substrate.yaml
  _joins.yaml                          # NEW -- cross-contract ratified joins (Part 5)
  ops_recommendations.yaml             # NEW -- Class A contract for ops_recommendations table
  ops_decisions.yaml                   # NEW -- Class A contract for ops_decisions table
  ops_execution_plans.yaml             # NEW -- Class A
  ops_session_log.yaml                 # NEW -- Class A (also subject to T-1.9 audit)
  ops_priority_queue.yaml              # NEW -- Class A
  telemetry_sessions.yaml              # NEW -- Class A (greenfield)
  telemetry_phases.yaml                # NEW -- Class A (greenfield)
  telemetry_steps.yaml                 # NEW -- Class A (greenfield)
  telemetry_process_events.yaml        # NEW -- Class A (greenfield)
  telemetry_model_calls.yaml           # NEW -- Class A (greenfield)
  telemetry_transcripts.yaml           # NEW -- Class A (greenfield)
  telemetry_agent_invocations.yaml     # NEW -- Class A (greenfield)
  lambda-log-rec.yaml                  # NEW -- Class B verb contract
  lambda-log-decision.yaml             # NEW -- Class B verb contract
  lambda-query.yaml                    # NEW -- Class B verb contract
  lambda-update-rec.yaml               # NEW -- Class B verb contract
  lambda-list-tools.yaml               # NEW -- Class B verb contract
  lambda-maintenance.yaml              # NEW -- Class B verb contract
  source-lineage.yaml                  # NEW -- Class C invariant
  project-id.yaml                      # NEW -- Class C invariant
  session-id.yaml                      # NEW -- Class C invariant
```

**Default format**: YAML. Markdown is reserved for contracts whose entire substance is workflow recipe / prose discipline (i.e. nothing structured to validate AND no plausible runtime consumer). The eight existing `.md` files in 3A do not meet that bar -- they all have machine-parseable substance and at least partial runtime consumers, so they all convert to `.yaml` under this ritual.

### 3C - Class A contract YAML schema (worked example)

A Class A contract YAML has this shape:

```yaml
# docs/contracts/ops_recommendations.yaml (worked example)
contract:
  id: ops_recommendations
  class: A
  contract_version: 1
  status: ratified                      # one of: draft | ratified | provisional_v0 | superseded
  ratified_at: "2026-05-21"
  ratified_via: pending_log_decision_lambda   # or "ops_decisions:dec-NNN" post-ratification
  description: |
    Source-of-truth contract for the ops_recommendations Iceberg table and its
    corresponding write-side Pydantic model (src/schemas/rec.py::RecPayload).
    All scattered semantics for these fields consolidate here.
  projects_to:
    pydantic_model: "src/schemas/rec.py::RecPayload"
    iceberg_table: "trading_formulas_db.ops_recommendations"
    iceberg_ddl_generated_path: "terraform/iceberg_tables_generated.tf"
    dq_yaml: "config/agent/data_quality/ops.yaml::tables.ops_recommendations"
  governance:
    table_class: SCD2_append_only
    partition_by: "day(last_updated_timestamp)"
    dedup_view: ops_recommendations_current
    write_path: "scripts/ops_data_portal.py via file_rec / update_rec"
    id_allocator: "DynamoDB counters table (agent-platform-counters)"
  amendment_policy:
    default: forward_compat_only
    semantic_break_requires:
      - "explicit `semantic_break: true` in this YAML"
      - "REPORT-ONLY amendment plan with Step 10 multi-perspective critique"
      - "migration story documented in field.amendment_log[]"
      - "bumped contract_version"
      - "_contract_version column on every row stamped to new version"
  write_payload_projection:                 # NEW (round-2 architect issue A4)
    # Distinguishes which fields of this contract are caller-provided vs portal-
    # injected vs derived. Lambda verb contracts (Class B) project from THIS
    # subset, not from the full field list. Codegen for Lambda handler accepts
    # only caller_provided fields in the request payload.
    caller_provided:
      - id                                  # via DynamoDB allocator: technically allocated, but caller observes
      - title
      - source                              # harness-injected but caller-visible at write time
      - effort
      - priority
      - status
      - automatable
      - file
      - context
      - acceptance
      - risk
    portal_injected:
      - created_timestamp                   # set by ops_data_portal write path
      - last_updated_timestamp              # SCD2 ordering key
      - _contract_version                   # stamped by ops_data_portal from this contract's contract_version
    derived: []                             # computed columns, if any
fields:
  id:
    type: str
    iceberg_type: string
    nullable: false
    description: |
      Recommendation unique identifier in canonical form `(rec|agent|test)-\d+`.
    semantics: |
      DynamoDB-allocated; never set directly by agents. SCD Type 2: multiple rows
      per id in the base table; uniqueness enforced at _current view level only.
      The `(rec|agent|test)-` prefix distinguishes lifecycle origin: `rec-` for
      portal-allocated, `agent-` for agent-batched, `test-` for fixture writes.
      Cross-table join key for ops_execution_plans, ops_priority_queue.
    populated_by: ops_data_portal.file_rec (via DynamoDB id allocator)
    write_time_validation: regex `^(rec|agent|test)-\d+$`
    dq_intent:
      not_null:
        enforced: true
        exclude_before: "2026-05-01"
    governance_notes: |
      Once written, immutable. Cannot be re-allocated. Closed recs retain id forever
      for audit/lineage.
    amendment_log: []
  source:
    # ROUND-2 ARCHITECT ISSUE A1 RESOLUTION: cross-system field uses $ref into
    # the Class C contract. Class A YAMLs DO NOT duplicate the description /
    # semantics / populated_by / write_time_validation of cross-system fields;
    # they reference the canonical Class C definition. Codegen resolves the ref.
    $ref: "docs/contracts/source-lineage.yaml#/contract/fields/registry_key"
    # Per-table dq_intent overrides are still allowed (e.g. ops_recommendations
    # may set a stricter not_null than the Class C default); they layer ON TOP
    # of the referenced contract, never replace it. Anti-pattern: copying any
    # field from the $ref target inline; resolver fails if duplicate.
    dq_intent_local:
      not_null:
        enforced: true
        exclude_before: "2026-05-01"
        write_time: true
    # `joins:` stays local to this contract -- joins are bidirectional and each
    # side declares its participation.
    joins:
      - lineage_join_source_to_agent_type
    amendment_log: []
  # ... remaining fields elided in this example ...
previous_versions: []                   # append-only audit of contract amendments
```

Key structural commitments embedded in the schema:

1. **`contract_version` is a top-level field** (Part 4) -- not a free-form note, but a structural counter.
2. **`projects_to`** lists every consumer artefact. Codegen plans use this to know where to emit their output.
3. **`amendment_policy.default: forward_compat_only`** is the safe-evolution discipline (Part 4).
4. **`write_payload_projection`** distinguishes caller-provided vs portal-injected vs derived fields. Class B (Lambda) contracts project from this subset for their request payloads -- they do NOT accept portal-injected fields in caller payloads.
5. **`$ref` for cross-system fields** points at the canonical Class C contract. Class A YAMLs never duplicate cross-system field definitions; the resolver fails on duplicate definitions (Part 4 Invariant 6).
6. **Per-field `dq_intent`** (or `dq_intent_local` for fields with `$ref`) maps directly to the `DqXxx` Annotated markers on the Pydantic model. The contract YAML is the source; the Pydantic markers are projections.
7. **`amendment_log[]`** is the **field-level** audit trail (one entry per field change, with semantic_break flag). **`previous_versions[]`** at the table level stores **whole prior YAML snapshots** for contract-version bumps. The two are different scopes; one tracks per-field amendments, the other captures point-in-time contract states. Disambiguation (round-2 architect A5): each has its own role, both are append-only.

### 3D - Class B contract YAML schema (worked example shape)

Class B contracts are verb-shaped, not field-shaped. Schema sketch:

```yaml
contract:
  id: lambda-log-rec
  class: B
  contract_version: 1
  status: provisional_v0                # Class B starts here per Part 6
  ratified_at: "2026-05-21"
  ratified_via: pending_log_decision_lambda
  description: |
    Verb contract for the log-rec Lambda (T0.7a). Filing a recommendation via
    POST {function-url} with RecPayload.
  projects_to:
    lambda_handler: "src/lambdas/log_rec/handler.py"
    iam_role: "terraform/lambda_tooling_iam.tf::aws_iam_role.log_rec_role"
    function_url: "terraform/lambda_tooling_platform.tf::aws_lambda_function_url.log_rec_url"
  governance:
    auth_type: AWS_IAM
    principal_classes: [PlatformDev, PlatformAdmin]
    admin_only_features: [import_mode]
  provisional_v0:                       # Part 6 -- explicit re-ratification clock
    declared_at: "2026-05-21"
    re_ratification_trigger:
      first_of:
        - "production_invocations >= 1000"
        - "days_since_first_production_invocation >= 90"
    re_ratification_owner: "human + Step 10 multi-perspective critique"
verbs:
  POST:
    payload_schema_ref: "docs/contracts/ops_recommendations.yaml::contract"
    response_codes:
      200: "{rec_id} returned; record appended to ops_recommendations"
      400: "typed validation error; payload rejected"
      403: "import_mode=true without admin principal"
      409: "duplicate id (stateful invariant violation)"
    typed_errors:                       # CD.12 discipline
      VALIDATION_ERROR: "payload failed Pydantic validation; details in error.fields"
      INVARIANT_VIOLATION_DUPLICATE_ID: "id already exists in ops_recommendations"
      AUTH_DENIED_NON_ADMIN_IMPORT: "import_mode requires PlatformAdmin principal"
audit_invariants:
  - "Every successful write emits a structured log line with {rec_id, session_id, source}"
  - "Failed writes do NOT touch the Iceberg table; outbox is the only write-ahead surface"
amendment_log: []
previous_versions: []
```

### 3E - Class C contract YAML schema (worked example shape)

Class C contracts are about a single cross-system concept and its rules.

```yaml
contract:
  id: source-lineage
  class: C
  contract_version: 1
  status: ratified
  description: |
    The `source` field is the canonical lineage key spanning ops_recommendations,
    ops_decisions (via filer agent), and telemetry tables (via agent_type).
    Defines the registry, the harness-injection rule, the validation behaviour,
    and the join semantics.
governance:
  registry_path: "config/agent/data_quality/source_registry.yaml"
  injection_path: "AGENT_TYPE env var -> ops_data_portal write path"
  validation_path: "scripts/ops_data_portal.py at write time"
  human_initiated_value: manual
allowed_values: <pulled from registry at validate time, not duplicated here>
joins_using_this_key:
  - lineage_join_source_to_agent_type
  - lineage_join_source_to_session_principal
governance_notes: |
  Graduation history: was a 4-value routing enum before 2026-05-06; became
  open-set lineage key on that date. The semantic break is recorded; future
  amendments MUST set semantic_break: true.
amendment_log:
  - date: "2026-05-06"
    change: "routing-enum -> lineage-key graduation"
    semantic_break: true
    migration_story: |
      Records written before 2026-05-06 may have stale enum-only values.
      No backfill; queries spanning the boundary should filter on
      created_timestamp.
previous_versions: []
```

---

## Part 4 - Contract versioning + safe evolution

This part addresses the semantic-evolution problem from Part 1C. Four invariants together.

### Invariant 1: `contract_version` is a structural field

Every `docs/contracts/{name}.yaml` carries `contract.contract_version: N` at the top. Initial ratification is `1`. Amendments bump the version. The integer is the canonical reference; no semver, no dates -- the bump is a discrete event with a logged amendment.

### Invariant 2: Every Iceberg row stamps its contract version (NO historical backfill)

Class A tables gain a `_contract_version` column. Iceberg type: `int`. **Nullable: true at the column level**, with a write-time validator at the portal level that requires it to be non-null for NEW writes. The nullability split is load-bearing -- it resolves the round-2 adversarial #1 SCD2-resurrection footgun (see below).

Writers stamp `_contract_version` from the Pydantic model's contract reference. Readers filter on it for version-aware queries. Cross-version queries are explicit (Part 5 joins discipline).

**Migration rule (round-2 adversarial #1 resolution)**: for tables that exist before the ritual lands, pre-existing rows are NOT backfilled. The column is added via Iceberg `ADD COLUMN` (nullable, no default), leaving historical rows with `_contract_version IS NULL`. Read paths use `COALESCE(_contract_version, 1)` to interpret NULL as "written before contract was ratified, assume v1 semantics." New writes via `ops_data_portal` MUST stamp the current contract_version; the portal raises if the value is missing.

**Why not backfill**: AGENTS.md "warehouse-as-source-of-truth invariant" forbids re-staging from local caches because `_prepare_record` refreshes `last_updated_timestamp = now`, which under SCD2 dedup wins and re-injects rows as new appends. A naive `UPDATE _contract_version = 1 WHERE _contract_version IS NULL` rewrite either (a) violates the append-only invariant entirely or (b) creates an infinite-resurrection cycle if any historical clone restages. Read-side COALESCE is the only safe path; no historical row touches Iceberg again after the ADD COLUMN.

**Athena gotcha (round-3 LOW)**: per `terraform/CLAUDE.md`, `ALTER TABLE ADD COLUMNS` has no `IF NOT EXISTS`. T0.12.5's implementation plan must issue one `ADD COLUMN` statement per table and tolerate (ignore) "already exists" errors on re-run -- idempotency via error-swallowing, not declarative IF NOT EXISTS. This is operational guidance for the downstream plan, surfaced here so T0.12.5's authors inherit the constraint without re-discovering it.

**Storage cost (round-2 adversarial #6 quantified)**: int column = 4 bytes uncompressed. Under Parquet gzip on a uniform column (most rows share the same value, since contract_version bumps are rare events), expected compressed cost is <1 byte per row. At the projected 100 TB total scale, the column adds ~25 GB total across all Class A tables -- ~0.025% of the storage envelope. Negligible. Cost-projection envelope in ROADMAP-PLATFORM.yaml unchanged.

### Invariant 3: Forward-compat-only is the default

A contract amendment is forward-compatible by default. **All amendments require an `amendment_log[]` entry** (round-3 H2 resolution). The entry carries an explicit `change_class` field that distinguishes forward-compat from semantic-break:

```yaml
amendment_log:
  - date: "2026-07-15"
    semantic_break: false
    change_class: prose_improvement   # see Invariant 3 table below for the closed 8-value vocabulary; canonical enum in scripts/contracts.py (T-1.12)
    summary: "Clarify that `source=manual` covers any human-initiated portal call (not just CLI)"
```

Allowed `change_class` values without `semantic_break: true`:

| change_class | What it covers |
|--------------|----------------|
| `field_add` | New optional field (nullable in table, `Optional[T] = None` in model) |
| `not_null_tighten` | Tighten `not_null` (from non-enforced to enforced, with `exclude_before` cutover date) |
| `type_widen` | Widen a numeric type (`int` -> `bigint`) |
| `join_add` | Add a new join entry referencing an existing field |
| `prose_improvement` | Improve `description` / `semantics` text WITHOUT changing what the field means (pure documentation refinement) |
| `governance_note_add` | Append to `governance_notes` |
| `accepted_values_narrow` | Narrow `accepted_values` (subject to extra rule in Invariant 3) |
| `accepted_values_extend` | Extend `accepted_values` (subject to extra rule in Invariant 3) |

The `prose_improvement` class is the round-3 H2 resolution: it makes documentation-quality changes a structurally-marked, gate-allowed operation distinct from semantic redefinition. The CI gate (Part 9I) accepts description/semantics diffs **iff** an accompanying `amendment_log[]` entry with `change_class: prose_improvement` AND `semantic_break: false` is present in the same commit. Bare diffs to description/semantics without an amendment_log entry are rejected. Diffs to description/semantics with `change_class` other than `prose_improvement` and `semantic_break: false` are also rejected -- only `prose_improvement` (which by definition does not change meaning) is the safe non-break path for prose changes.

**Known weakness (round-3 A1 acknowledged)**: `change_class: prose_improvement` is **self-attested**. An agent making a covert semantic redefinition can mislabel it `prose_improvement` and the CI gate will accept it. The gate is structural (does an amendment_log entry exist? does its `change_class` match an allowed value?) not semantic (does the diff actually preserve meaning?). Two mitigations layered:

1. **Diff-size threshold escalation**: prose-only diffs exceeding 5 lines per field automatically require Step 10 multi-perspective critique on the amending PR (T-1.12 lands this rule in the CI gate -- a `prose_improvement` amendment_log entry whose corresponding diff is > 5 lines triggers a critique-required label on the PR).
2. **Git blame as audit trail**: every `prose_improvement` amendment_log entry is traceable to a commit and a PR; periodic spot-check by the human (or by a scheduled agent in future work) can catch mislabels retroactively. This is post-hoc not preventative, but it raises the cost of malicious mislabelling.

This is a deliberate "trust but verify" choice. A fully-enforced mechanism (semantic diff analysis, LLM-judged equivalence) is out of scope for this INTENT; the gain over the structural gate is uncertain and the implementation cost is high. The two layered mitigations above raise the floor without claiming a ceiling.

**`accepted_values` rules (round-2 consensus issue C3 + adversarial #4)** -- both directions need explicit treatment:

- **Narrowing** (removing values from the allowed set): allowed WITHOUT `semantic_break: true` ONLY when no historical rows carry the removed value. If any historical row carries the removed value, the narrowing becomes a `semantic_break: true` amendment (existing data interpretation changes). The amendment plan MUST query the table for the removed value's row count and document the result.
- **Extending** (adding values to the allowed set): allowed WITHOUT `semantic_break: true` ONLY when all known readers (enumerated in the contract's `projects_to` plus its `joins:` participants) explicitly tolerate open-set values. Tolerance means: the reader does NOT assert `value IN OLD_SET` anywhere in its code path. If any reader asserts closed-set membership, the extension becomes a `semantic_break: true` amendment (`source` field's routing-enum -> lineage-key graduation is the textbook precedent; that should have set `semantic_break: true` had this discipline existed at the time).

Disallowed without `semantic_break: true`:

- Change the meaning of an existing field's value (e.g., the source routing-enum -> lineage-key precedent itself)
- Remove a field (use the `DqDeleted` marker process from T0.13)
- Narrow a type
- Change the partition key
- Change the dedup view definition in ways that drop rows
- Modify `populated_by` semantics (e.g., from "harness injects" to "agent self-assigns") -- this changes the lineage interpretation of existing data

### Invariant 4: `semantic_break: true` is an opt-in escape hatch with discipline

An amendment that needs to change existing semantics:

1. Sets `semantic_break: true` in the field's `amendment_log[]` entry for the amendment.
2. Authors a REPORT-ONLY amendment plan with Step 10 multi-perspective critique (architect + adversarial).
3. Documents the migration story explicitly: backfill? sentinel? leave divergent? what does the boundary cutover look like for cross-version queries?
4. Bumps `contract.contract_version`.
5. The `_contract_version` column distinguishes pre-break and post-break rows.
6. The previous contract version is preserved verbatim in `previous_versions[]` (append-only; never deleted).

Anti-pattern: amending the meaning of a field by editing `description` / `semantics` text without setting `semantic_break: true` (where the change actually does redefine semantics) OR without `change_class: prose_improvement` (where it doesn't). Either way, silently mutating the prose is the anti-pattern. The T-1.12 CI drift gate accepts description/semantics diffs IF an `amendment_log[]` entry in the same commit carries either (a) `change_class: prose_improvement` with `semantic_break: false` (pure documentation polish), or (b) any other valid `change_class` with `semantic_break: true` (genuine redefinition through the full ritual). Bare diffs without any accompanying amendment_log entry are rejected.

### Invariant 5: `$ref` uniqueness (round-2 architect issue A1 resolution)

A field that appears in multiple contracts (e.g. `source` appearing in `ops_recommendations.yaml` and conceptually in `source-lineage.yaml`) is defined ONCE -- in the Class C contract that owns the cross-system semantics -- and referenced via `$ref` from each Class A contract that uses it.

Rules:

- `$ref` points at a JSON-pointer-like path: `"docs/contracts/{name}.yaml#/contract/fields/{field_name}"`.
- The referring contract MAY supply per-table overrides via a parallel key (`dq_intent_local`, `governance_notes_local`) that layer on top of the referenced fields. Overrides MUST be additive or strictly tighter than the Class C source; they cannot loosen the referenced contract.
- Duplicate inline definitions of a referenced field (i.e. both `$ref` and a full inline definition) are a structural error. T-1.12's CI drift gate rejects them.
- Cross-Class-C references are not allowed (Class C contracts are leaf nodes; no chained refs).

This rule is what makes Class A and Class C contracts cleanly disjoint. Without it, the ritual's first deliverable (`ops_recommendations.yaml`) would reproduce the scattered-semantics disease the ritual exists to cure.

### Invariant 6: `status: deprecated` is a terminal state for rollback (round-2 adversarial #9 resolution)

The contract status enum is: `draft | ratified | provisional_v0 | deprecated | superseded`.

`deprecated` is the **catastrophic-rollback** state. Use case: a ratified contract turned out structurally wrong (not just amendable -- foundationally wrong), and no `semantic_break: true` amendment can salvage it. The contract is marked `deprecated`; a replacement contract is authored (new file or substantially-restructured same file at contract_version 2+); downstream codegen consumers migrate to the replacement contract; the old contract YAML file stays in `docs/contracts/` for archaeological reference.

Transition rules:

- `ratified -> deprecated`: requires REPORT-ONLY plan with Step 10 multi-perspective critique justifying the rollback and naming the replacement contract.
- `deprecated -> anything`: **default forbidden** (round-3 LOW item softening). The state is intended as terminal because "we shouldn't have ratified this in the first place" is rarely subsequently un-shouldn't. However, if a `deprecated` rollback later turns out to be itself a mistake (rollback-the-rollback), a fresh REPORT-ONLY plan with Step 10 multi-perspective critique can unwind it (transition to a fresh `contract_version: N+1` block with `status: ratified`). This is the same ceremony as the original `deprecated` transition, applied in reverse. The intent is to make terminal-state revival expensive but possible.
- Iceberg rows written under a deprecated contract retain their `_contract_version` stamp; queries can still filter on it; the data is not deleted.

`superseded` (existing state in the status enum) is a softer outcome: the contract is supplanted by a successor (e.g. `lambda-log-rec-v2` replaces `lambda-log-rec` after CD.16 ratification + early production traffic teaches us what v1 got wrong). `deprecated` is for "we should never have ratified this in the first place"; `superseded` is for "we learned from this and the successor builds on it."

---

## Part 5 - Cross-contract joins ratification

Cross-contract joins are themselves contracts. The current platform has implicit joins living in code (`ops_data_portal.py`'s validation of `source` against `source_registry.yaml`; cross-table queries in agents and dashboards). This INTENT proposes ratifying them explicitly.

**Surface:** `docs/contracts/_joins.yaml` -- a single file enumerating every cross-contract join used by codegen, queries, dashboards, or agent prompts. Each entry has the same `contract_version` + amendment discipline as Class A/B/C contracts.

Example:

```yaml
joins:
  - id: lineage_join_source_to_agent_type
    description: |
      Joins ops_recommendations.source to telemetry_*.agent_type as a lineage key.
    contract_version: 1
    status: ratified
    left:
      contract: ops_recommendations
      field: source
    right:
      contract: source-lineage   # Class C invariant
      field: registry_key
    semantics: |
      Both sides reference the source registry. Equality on string. No coercion.
    min_contract_versions:        # round-2 architect issue C2 resolution
      # Names the contract_version of each side that this join's semantics
      # apply to. If either side bumps to a higher version, the join MUST
      # be re-ratified before being used at the higher version.
      left: 1
      right: 1
    cross_version_policy:         # round-2 architect issue C2 resolution
      # What happens when a query spans rows whose _contract_version values
      # differ from min_contract_versions on either side.
      strict: false              # if true, queries reject rows outside min_contract_versions
      coalesce_legacy: true      # COALESCE(_contract_version, 1) on null historical rows
      cross_version_warning: |
        Rows with _contract_version > min_contract_versions[side] are
        included but flagged. Query planners SHOULD emit a warning. Re-ratify
        this join when the bumped side stabilises.
    used_by:
      - "Athena queries in scripts/session_preflight.py that report agent activity"
      - "Future cross-table reports in agent prompts"
    amendment_log: []
  - id: session_id_join_telemetry_sessions_to_phases
    contract_version: 1
    status: ratified
    left:
      contract: telemetry_sessions
      field: session_id
    right:
      contract: telemetry_phases
      field: session_id
    semantics: |
      Joining key for nested telemetry. UUID v4. Created in the parent session,
      passed to phases as a foreign key.
    min_contract_versions:
      left: 1
      right: 1
    cross_version_policy:
      strict: false
      coalesce_legacy: true
    used_by:
      - "Causal-chain verifier (T3.2) PRODUCE step"
    amendment_log: []
```

Decision deferred to the first ratification plan that uses joins: whether `_joins.yaml` is a single global file (simpler discovery, all-in-one diff surface) or whether each contract owns a `joins:` section in its own YAML (locality, but duplicates the join definition on both sides). This INTENT specifies a single global file by default, with a deferral to revisit if scale becomes painful.

**Cross-contract amendment cascade (round-2 architect issue C2 + adversarial #10)**: when a Class C contract amends, every join entry that references it MUST be re-ratified at the same contract_version bump or before its first use at the new version. The first cross-contract amendment plan (whenever it occurs) authors a concrete cascade policy and amends this INTENT or its successor. Until then, the `min_contract_versions` + `cross_version_policy` fields above are the discipline.

**Round-3 M5: incremental landing semantics for `_joins.yaml`.** A join entry MUST NOT land before both referenced contracts ratify. Two operational consequences:

1. **Within a single PR**: if a ratification plan needs to author a join referencing a sibling contract that is also being ratified in the same PR (e.g. the seven atomic telemetry contracts in T0.12.6), the join entry lands AT THE END of the PR sequence, after all referenced contracts are present in `docs/contracts/`. The CI drift gate enforces this by rejecting any `_joins.yaml` entry whose `left.contract` or `right.contract` references a contract YAML missing from the same commit/branch.
2. **Across PRs**: if a ratification plan adds a contract that will eventually be the target of a join from a not-yet-ratified sibling, the join entry stays unfiled until the sibling ratifies in its own PR. The first plan files the contract without the join; the second plan files its contract AND the join entry that connects them.

This rule prevents the bootstrap-ordering bug where an early atomic plan would try to file a join entry referencing a contract that hasn't ratified yet, causing $ref resolution to fail in the CI gate.

---

## Part 6 - v0-provisional ratification for Class B (Lambdas)

### 6A - Why Class B is different from Class A

Class A contracts (data schemas) can be ratified well from first principles. The shape of `ops_recommendations` is constrained by what `file_rec` callers need to produce; agent-write semantics constrain the model, the model constrains the DDL.

Class B contracts (Lambda verbs) cannot be ratified well from first principles. Until real agent traffic flows, the verb set, error code taxonomy, payload shapes, and audit invariants are educated guesses. Forcing fully-ratified contracts upfront either delays the Lambda indefinitely OR produces ratified-but-wrong contracts that require expensive amendment cycles.

### 6B - The v0-provisional mechanism

Class B contracts have an additional initial state: `status: provisional_v0`. Properties of this state:

- The contract IS ratified at v1 -- it can be consumed by codegen, by the Lambda handler, by tests, by callers.
- The contract carries an explicit `provisional_v0` block at the top, naming a re-ratification trigger.
- The re-ratification trigger fires when EITHER:
  - The Lambda has accumulated N production invocations
  - The Lambda has been deployed N days
  - whichever happens first
- **Triggers are staggered per-Lambda** (round-2 adversarial issue R3 resolution) to avoid concurrent re-ratification spikes when CD.16 ratifies and six provisional contracts all start their clocks at once. Concrete stagger:
  - `lambda-log-rec`: 500 invocations OR 60 days (high-traffic, ratify earlier)
  - `lambda-log-decision`: 200 invocations OR 90 days (low-traffic, longer days window)
  - `lambda-query`: 2000 invocations OR 60 days (very high traffic; large invocation cap before re-ratify)
  - `lambda-update-rec`: 500 invocations OR 90 days
  - `lambda-list-tools`: 500 invocations OR 120 days (introspection only; lowest priority)
  - `lambda-maintenance`: 90 days only (scheduled, not invocation-driven)
- The trigger fires a REPORT-ONLY re-ratification plan, which goes through the full Step 10 multi-perspective critique against the now-actual production behaviour. The plan either confirms the contract (status flips to `ratified`) or amends it (semantic_break path).
- Triggers are checked at planning preflight time (`session_preflight.py` reads `docs/contracts/*.yaml` for any with `status: provisional_v0` and surfaces those whose trigger conditions are met). The preflight hook implementation lands in T-1.12 alongside the CI drift gate.

### 6C - Freeze-window discipline (round-2 consensus issue C4 + adversarial #5 + round-3 H1 correction)

Under the **CD.16-governed** Lambda-deploy freeze (NOT CD.17 -- that's the STRATEGIC plan-artefact freeze; see "Decision 67 freeze interaction" at the top of this INTENT), the v0-provisional clock cannot advance: no deploys means no production invocations, and "days since deploy" is undefined for an undeployed Lambda. Authoring Class B contracts now produces v0-provisional artefacts that never transition -- a permanent provisional state indistinguishable from `ratified` to consumers.

Resolution: **Class B contract ratifications are themselves deferred until CD.16 ratifies** (round-3 H1 correction). Pre-CD.16-ratification:

- Class A ratifications proceed (ops + telemetry + cross-system invariants) -- they have no freeze dependency.
- Class C ratifications proceed -- same.
- Class B ratifications are scheduled into a new tier item (T1.12 in the proposed roadmap edits below) gated on CD.16 ratification via `decision_required_before`. They do not start while CD.16 is pending.
- The codegen plans that consume Class B contracts (T0.7a, T0.7b, T0.7c, T1.1, T1.3, T1.4) likewise stall on Class B ratification; their `depends_on` edges in Part 8B add the new Class B ratification predecessor (T1.12). Once CD.16 ratifies AND T1.12 completes, these codegen plans become eligible to start.

Under this discipline, no Class B contract is authored in `provisional_v0` state while the Lambda-deploy freeze is in effect. When CD.16 ratifies, the Class B ratification predecessor plans run; they author contracts at `provisional_v0`; the clock starts at first production invocation; the staggered triggers fire in due course.

**Important sequencing implication**: CD.16 is significantly earlier in the dependency graph than CD.17. CD.17 reversal waits on T4.2 stability + 14d grace + T3.3 + 7d grace -- many tier waves out. CD.16 has no such cascade and can ratify as soon as the per-Lambda gating discipline is wired (see CD.16's own state in the roadmap). Routing Class B deferral through CD.16 (correct) rather than CD.17 (v2 error) unblocks AWS-migration critical-path work meaningfully earlier.

The architect's earlier suggestion of "synthetic trigger via integration tests" is rejected: integration tests do not exercise the contract under realistic agent behaviour, so they do not actually produce the signal needed for re-ratification. Better to delay Class B ratification until real signal exists.

### 6D - Why this is honest

The alternative -- "ratify upfront, accept the rework risk" -- pretends the uncertainty isn't there. The contract claims confidence it doesn't have, and a future amendment cycle is treated as a failure when it should be the expected case for any Lambda not yet exercised in production.

v0-provisional names the uncertainty in the artefact itself. A reader of `docs/contracts/lambda-log-rec.yaml` sees that the contract is provisional, sees when re-ratification is due, sees who owns it. The contract is honest about its own confidence level.

### 6E - Class A and C do not use v0-provisional

Class A contracts (data schemas) are ratified fully at v1 OR they are not ratified at all. There is no "we'll see how it goes" state for a table schema; the cost of getting it wrong is too high, and the deliberation upfront is genuinely tractable.

Class C contracts (cross-system invariants) similarly do not use v0-provisional. They are too foundational; a provisional cross-system invariant is a contradiction in terms.

---

## Part 7 - Proposed Candidate Decision CD.25

```yaml
- id: CD.25
  title: "Pre-codegen contract ratification for Class A / B / C contracts"
  state: pending
  filed_via: pending_log_decision_lambda
  bootstrap_allowance: true             # round-2 consensus issue C1 resolution
  bootstrap_allowance_rationale: |
    CD.25 gates T-1.11 (this INTENT) but T-1.11 produces CD.25; without an
    allowance, CD.25 cannot ratify until T-1.11 completes, which itself depends
    on CD.25 ratifying. Same circular pattern as CD.1 / T-1.1 / T0.7b. This
    allowance mirrors that precedent. Under bootstrap_allowance, T-1.11
    completion is permitted with CD.25 state == "pending"; ratification
    happens once T0.7b (log-decision Lambda) becomes available.
  problem: |
    Field semantics for the platform's load-bearing data schemas, Lambda verb
    contracts, and cross-system invariants live in four scattered places (Pydantic
    models, Athena DDL, DQ YAML, prose docs). None is canonical. Drift between
    them is a regular occurrence. Lock-in moments (first DDL commit, first Lambda
    deploy) arrive in ordinary implementation PRs with no dedicated deliberation
    step. Iceberg's structural-evolution rules do not solve the semantic-evolution
    problem (same column name, different meaning over time). Existing prose-shaped
    contracts (docs/contracts/*.md) are themselves examples of the disease: they
    bind nothing at runtime and drift silently from the code that should implement
    them.
  decision: |
    Introduce a pre-codegen contract ratification ritual. The ritual applies to
    three named contract classes: Class A (data schemas that become DDL),
    Class B (public agent surfaces / Lambda verb contracts), Class C
    (cross-system invariants). Contracts in these classes have a single canonical
    home: docs/contracts/{name}.yaml -- machine-parseable by default. Codegen
    plans (Iceberg DDL, Lambda handlers, Pydantic projections, DQ YAML
    projections) consume the ratified contract as an authoritative input and
    never re-derive its semantics from scattered sources. Contracts carry
    contract_version, every Iceberg row stamps _contract_version (nullable;
    no historical backfill; read-side COALESCE), amendments default to
    forward-compatible with explicit change_class on every amendment_log
    entry, semantic breaks are opt-in with explicit migration stories.
    Class B contracts use a v0-provisional state with staggered
    re-ratification triggers; Class B ratification is itself deferred
    under the CD.16-governed Lambda-deploy freeze (NOT CD.17 -- that is
    the STRATEGIC plan-artefact freeze; CD.16 specifically replaces the
    Decision-67 Lambda-deploy blanket per docs/ROADMAP-PLATFORM.yaml:354+)
    and unblocks on CD.16 ratification. A terminal `deprecated` state
    exists for catastrophic rollback. Existing docs/contracts/*.md files
    convert to .yaml as ratification predecessor plans under this ritual.
  context: |
    Today field semantics live in four places per table; agent-first principle
    (NS.4) is violated by the scatter; semantic-evolution drift is invisible.
    The AWS migration to personal account is the natural reset point for many
    contracts; landing this ritual before migration ensures the personal-account
    substrate inherits sound discipline rather than carrying the current scatter
    forward. See docs/INTENT-pre-codegen-contract-ratification.md for the full
    deliberation record, including round-2 critique findings and their resolutions.
  enforcement:                          # round-2 consensus issue C5 + round-3 H2/H3/M3 resolution
    # The ritual is enforceable, not voluntary. Minimum enforcement surface:
    - "T-1.12 amends scripts/platform_roadmap.py (the T-1.5 RoadmapDocument Pydantic schema) to accept the new bootstrap_completion_exempt: bool field, decomposition_hints: object, and the expanded bootstrap COMPLETION exemption prose set."
    - "T-1.12 lands a CI drift gate in scripts/validate.py that walks docs/contracts/*.yaml and (a) rejects malformed YAML against the contract Pydantic schema; (b) rejects diffs to description/semantics fields without an accompanying amendment_log[] entry whose change_class explicitly distinguishes prose_improvement from semantic_break: true; (c) rejects duplicate inline definitions of $ref-referenced fields; (d) rejects $ref pointing at non-existent files or fields, or chain-depth >1; (e) rejects status transitions that violate the state machine (e.g. deprecated -> anything); (f) rejects amendment_log[] entries with change_class outside the closed vocabulary."
    - "T-1.12 lands a preflight hook in scripts/session_preflight.py that surfaces v0-provisional contracts whose re-ratification trigger conditions are met."
    - "T0.13 and sibling codegen plans add CI drift checks ensuring the Pydantic model exposes exactly the fields the contract YAML enumerates."
  gates:
    - T-1.11    # this INTENT (ritual ratified)
    - T-1.12    # CI drift gate + preflight hook + roadmap edits implementation
    - T-1.13    # convert instruction-architecture.md -> .yaml
    - T-1.14    # convert inference-provider.md -> .yaml
    - T-1.15    # convert log-storage.md -> .yaml
    - T-1.16    # convert build-lambda.md -> .yaml
    - T-1.17    # convert cli-json-output.md -> .yaml
    - T-1.18    # convert copilot-cli.md -> .yaml
    - T-1.19    # convert delegate-cli.md -> .yaml
    - T0.12.5   # ratify ops_recommendations + ops_decisions contracts
    - T0.12.6   # ratify telemetry table contracts (greenfield; decomposed to atomic plans)
    - T0.12.7   # ratify cross-system invariants (source, project_id, session_id)
    - T1.12     # ratify Class B Lambda verb contracts (deferred until CD.16 ratifies; round-3 H1 correction)
  decision_required_before:
    - "T0.13 may start"                       # codegen plan that requires ratified ops contracts
    - "T0.7a may start"                       # log-rec implementation
    - "T0.7b may start"                       # log-decision implementation
    - "T0.7c may start"                       # query implementation
    - "T1.1 may start"                        # update-rec implementation
    - "T1.3 may start"                        # list-tools implementation
    - "T1.4 may start"                        # maintenance implementation
    - "Any T3.x telemetry verifier may start" # telemetry-touching verifier work
  related_candidate_decisions:
    - CD.1    # bootstrap_allowance precedent (T-1.1 / T0.7b circularity)
    - CD.9    # partition-by-day uniformity (consumed by Part 4 + Class A contracts)
    - CD.10   # six platform Lambdas + import_mode discipline (gates Class B contracts)
    - CD.12   # Annotated-Pydantic markers (the projection target for Class A dq_intent)
    - CD.11   # Lambda dispatcher retirement (other half of Decision 67 split)
    - CD.16   # per-Lambda deploy gating -- Class B Lambda contract authoring waits on CD.16 ratification (round-3 H1 correction)
    - CD.17   # STRATEGIC plan-artefact freeze (not Lambda-deploy; this CD respects it for plan typing only)
```

---

## Part 8 - Proposed roadmap edits

The follow-on IMPLEMENTATION plan applies these as a YAML diff against `docs/ROADMAP-PLATFORM.yaml`.

### 8A - New tier_items

```yaml
# Inserted into tier_items[] in numerical order

# === T-1.11: this INTENT only (round-2 architect A3 + A6 split) ===
- id: T-1.11
  tier: T-1
  name: Pre-codegen contract ratification ritual (INTENT only)
  intent: |
    REPORT-ONLY. Land docs/INTENT-pre-codegen-contract-ratification.md. Establish
    the ritual, the three contract classes, the canonical home, the versioning
    discipline, and propose CD.25 + the roadmap edits applied in T-1.12.
    Round-2 architect issue A3: this item produces the INTENT only and does NOT
    apply roadmap edits or add enforcement -- those are T-1.12. The split breaks
    the meta-item conflation between "ratify the ritual" and "implement the
    ritual" that Part 1D explicitly argued against.
  depends_on: []
  files_in_scope:
    - docs/INTENT-pre-codegen-contract-ratification.md
  exit_criteria:
    - "INTENT deliverable committed on agent/pre-codegen-contract-ratification"
    - "Step 9 plan-critique returns PROCEED"
    - "Step 10 multi-perspective critique converges (PROCEED on a fresh round OR human-accepted with documented deferrals)"
  related_candidate_decisions: [CD.25]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true     # round-2 adversarial #2 resolution -- this item plus T-1.12, T-1.13..T-1.19, T0.12.5/6/7, T1.12 enter the bootstrap COMPLETION exemption set; T-1.12 commits this expansion to ROADMAP-PLATFORM.yaml
  status: in_progress

# === T-1.12: implementation of the ritual's enforcement + roadmap edits ===
# Round-3 M1 resolution: effort upgraded from M to L, with explicit decomposition hint.
# Round-3 H3 resolution: files_in_scope now includes scripts/platform_roadmap.py to amend the T-1.5 RoadmapDocument schema for the new bootstrap_completion_exempt + decomposition_hints fields.
- id: T-1.12
  tier: T-1
  name: Contract ritual enforcement (CI drift gate + preflight hook + roadmap edits)
  intent: |
    IMPLEMENTATION. (a) Apply this INTENT's proposed roadmap edits to
    docs/ROADMAP-PLATFORM.yaml -- adds CD.25, adds T-1.13..T-1.19, T0.12.5,
    T0.12.6 (decomposed), T0.12.7, T1.12; updates depends_on on T0.13 / T0.7a/b/c
    / T1.1 / T1.3 / T1.4 / T3.1 / T3.2; expands the bootstrap COMPLETION
    exemption set + adds the CD.25-scoped termination clause.
    (b) Amend scripts/platform_roadmap.py (the T-1.5 schema; round-3 H3 + A2 correction --
    earlier draft cited a non-existent scripts/roadmap_document.py) to:
        (i) ADD `bootstrap_completion_exempt: bool` field to TierItem.
        (ii) ADD `decomposition_hints: dict | None` field to TierItem.
        (iii) ADD `decision_required_before: list[str] | None` field to TierItem (already exists on
              CandidateDecision; this extends it to TierItem too).
        (iv) ADD `bootstrap_allowance: bool` field to CandidateDecision.
        (v) CHANGE `model_config = ConfigDict(extra="ignore")` to `extra="forbid"` on TierItem +
            CandidateDecision so unknown fields fail at load time. This closes the silent-drop hole
            adversarial R-NEW-A2 identified -- without this change, the four new fields above are
            literally silently dropped on YAML load and the enforcement claims are theatre.
        (vi) Existing model_config on other classes (Document, NorthStar, GateHelper, etc.) may stay
             extra="ignore" -- the forbid switch is targeted at the two classes the new fields attach to.
    (c) Land scripts/contracts.py Pydantic schema for Class A/B/C contract YAMLs +
    $ref resolver with chain-depth-1 enforcement.
    (d) Land scripts/validate.py CI drift gate per the CD.25 enforcement clause.
    (e) Land scripts/session_preflight.py hook that surfaces v0-provisional
    contracts whose re-ratification triggers fire.
    (f) Amend .claude/skills/implement/SKILL.md (round-3 A3 correction) to teach the bookkeeping rule
    to read `decomposition_hints` on parent tier_items and inherit exemption status to atomic child
    plans at filing time. Without this amendment, the round-3 M2 inheritance rule has no enforcer.
    Without T-1.12 the ritual is voluntary discipline -- this is the
    consensus-C5 enforcement landing point.
  depends_on: [T-1.11]
  decomposition_hints:                  # round-3 M1: split if scope or critique findings warrant
    split_by: subsystem
    atomic_plans:
      - "T-1.12a -- roadmap edits + scripts/platform_roadmap.py schema amendment + scripts/contracts.py + tests"
      - "T-1.12b -- scripts/validate.py CI drift gate + scripts/session_preflight.py preflight hook + tests"
    rationale: |
      Sub-plan (a) lands schemas + data; sub-plan (b) lands the gates that consume them.
      Split is RECOMMENDED if the planning session determines the combined scope exceeds
      M+ effort or if the critique gate flags scope creep. A single-plan landing is
      still acceptable if the implementation agent prefers it.
  files_in_scope:
    - docs/ROADMAP-PLATFORM.yaml
    - scripts/platform_roadmap.py             # AMEND -- ADD new fields (TierItem.bootstrap_completion_exempt, TierItem.decomposition_hints, TierItem.decision_required_before, CandidateDecision.bootstrap_allowance) + flip TierItem + CandidateDecision to extra="forbid" (round-3 A2 correction; earlier draft cited non-existent scripts/roadmap_document.py)
    - scripts/validate.py                     # AMEND -- CI drift gate for docs/contracts/*.yaml
    - scripts/session_preflight.py            # AMEND -- v0-provisional trigger hook
    - scripts/contracts.py                    # NEW -- Pydantic schema for contract YAMLs + loader + $ref resolver; encodes change_class as a Literal (closed vocabulary) so the round-3 A5 unmounted-vocabulary concern is mechanically locked
    - tests/test_contracts.py                 # NEW -- coverage for the loader + validators + $ref resolver
    - tests/test_platform_roadmap.py          # AMEND -- coverage for new fields + extra="forbid" rejection
    - .claude/skills/implement/SKILL.md       # AMEND -- bookkeeping rule reads decomposition_hints for inheritance (round-3 A3 correction; earlier draft assumed the rule already did this)
  exit_criteria:
    - "CD.25 + all proposed tier_items present in ROADMAP-PLATFORM.yaml"
    - "scripts/platform_roadmap.py: TierItem has bootstrap_completion_exempt + decomposition_hints + decision_required_before fields; CandidateDecision has bootstrap_allowance field; both classes flipped to extra='forbid'; unknown-field YAML payloads now FAIL at load (covered by test)"
    - "bootstrap COMPLETION exemption set expanded to include T-1.11..T-1.19, T0.12.5/6/7, T1.12 with the CD.25-scoped termination clause (Part 8C)"
    - "scripts/contracts.py Pydantic loader rejects malformed contract YAMLs in unit tests"
    - "scripts/contracts.py change_class field is typed as Literal[...] over the closed 8-value vocabulary (Invariant 3 table); test asserts a 9th value is rejected"
    - "scripts/contracts.py $ref resolver: success on valid path; raises on missing file; raises on missing pointer; raises on chain depth > 1 (round-3 M3)"
    - "scripts/validate.py CI drift gate runs at presubmit and full tiers; rejects bad contracts in CI; covers all six rejection categories from CD.25 enforcement clause"
    - "scripts/session_preflight.py surfaces v0-provisional contracts whose triggers are met"
    - "Unit tests cover: malformed YAML rejection; description/semantics diff WITHOUT amendment_log[] entry rejected; description/semantics diff WITH change_class: prose_improvement + semantic_break: false ACCEPTED (round-3 H2); description/semantics diff WITH semantic_break: true + valid change_class ACCEPTED; $ref duplicate-inline rejected; status transition state machine; amendment_log change_class vocabulary rejection (9th value)."
    - "Bookkeeping rule in .claude/skills/implement/SKILL.md amended to read decomposition_hints on parent tier_items and inherit exemption status to atomic child plans at filing time; test asserts inheritance behaviour"
    - "Bookkeeping rule also verified to handle T-1.11's self-referential status flip (round-3 LOW item)"
  related_candidate_decisions: [CD.25]
  effort: L                              # round-3 M1: upgraded from M
  strategic: true                        # round-3 A6 correction: L items are strategic per ROADMAP-PLATFORM.yaml:51-52; freeze override means decompose into atomic IMPLEMENTATION plans (see decomposition_hints), NOT label as strategic:false
  bootstrap_completion_exempt: true
  status: not_started

# === T-1.13..T-1.19: convert existing docs/contracts/*.md to .yaml ===
- id: T-1.13
  tier: T-1
  name: Convert instruction-architecture.md to .yaml + wire prompt_compliance.py to read it
  intent: |
    REPORT-ONLY + small IMPLEMENTATION. Convert docs/contracts/instruction-architecture.md
    to instruction-architecture.yaml. Five-layer model becomes structured fields
    (layer, consumers, load_time, content_locations). prompt_compliance.py reads
    the YAML to enforce layer claims; existing checks anchored to filesystem
    paths become anchored to the YAML.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/instruction-architecture.yaml   # NEW
    - docs/contracts/instruction-architecture.md     # DELETED after migration
    - scripts/prompt_compliance.py
  exit_criteria:
    - "instruction-architecture.yaml exists at contract_version: 1, status: ratified"
    - "prompt_compliance.py reads the YAML; old .md deleted; CI green"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.14
  tier: T-1
  name: Convert inference-provider.md to .yaml + wire model_registry.py to read it
  intent: |
    REPORT-ONLY + small IMPLEMENTATION. Convert docs/contracts/inference-provider.md
    (244 lines) to inference-provider.yaml. Provider routing rules, model IDs,
    fallback semantics, escalation rules become structured. model_registry.py
    reads the YAML; config/agent/copilot/model_routing.yaml either projects from it or
    is replaced. This is the textbook ratification target -- contract that has a
    runtime consumer just waiting to be the single source. Round-3 H4: re-graded
    S -> M; the substance is large and requires reconciling against the existing
    config/agent/copilot/model_routing.yaml + model_registry.py code paths.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/inference-provider.yaml         # NEW
    - docs/contracts/inference-provider.md           # DELETED after migration
    - scripts/model_registry.py
    - config/agent/copilot/model_routing.yaml        # MAY be projected or deleted
  exit_criteria:
    - "inference-provider.yaml exists at contract_version: 1, status: ratified"
    - "model_registry.py reads the YAML; CI green; .md deleted"
    - "config/agent/copilot/model_routing.yaml either projects from inference-provider.yaml OR is deleted in favour of it; relationship documented in the new YAML's projects_to"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: M                              # round-3 H4: upgraded from S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.15
  tier: T-1
  name: Convert log-storage.md to .yaml + wire s3_log_store.py to read it
  intent: |
    REPORT-ONLY + small IMPLEMENTATION. Three JSONL storage patterns become
    structured YAML entries. s3_log_store.py reads the YAML to know which
    pattern applies per log file.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/log-storage.yaml                # NEW
    - docs/contracts/log-storage.md                  # DELETED
    - scripts/s3_log_store.py
  exit_criteria:
    - "log-storage.yaml exists at contract_version: 1, status: ratified"
    - "s3_log_store.py reads the YAML; CI green"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.16
  tier: T-1
  name: Convert build-lambda.md to .yaml + assert build_lambda.py equivalence
  intent: |
    REPORT-ONLY + small IMPLEMENTATION. Build workflow steps as structured YAML.
    Either build_lambda.py reads the YAML directly OR a CI check asserts the
    script implements every step the YAML defines.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/build-lambda.yaml               # NEW
    - docs/contracts/build-lambda.md                 # DELETED
    - scripts/build_lambda.py
  exit_criteria:
    - "build-lambda.yaml exists at contract_version: 1, status: ratified"
    - "CI check asserts equivalence; .md deleted"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.17
  tier: T-1
  # SUPERSEDED-BY-RETIREMENT (Decision 121, 2026-07-05): this conversion proposal was never
  # realized. cli-json-output.md's parser (copilot_wrapper.parse_jsonl_output) and its home
  # (scripts/copilot_wrapper.py) are both deleted; scripts/llm_utils.py never parsed CLI JSON
  # output. T-1.17 closed by exemption (retire, not convert) per Known Gap #7's "keep as
  # markdown / retire, unenforced" branch -- the text below is the ORIGINAL proposal, retained
  # as historical record, not a description of what happened.
  name: Convert cli-json-output.md to .yaml + wire llm_utils.py to read it
  intent: |
    [ORIGINAL PROPOSAL, never realized -- retired instead, Decision 121]
    REPORT-ONLY + small IMPLEMENTATION. CLI JSON-output schema (171 lines)
    becomes structured per-field YAML, with its parsing wired into llm_utils.py
    (which never parsed CLI JSON output in reality -- see the superseded-by-
    retirement note above) OR a CI check asserts coverage. Round-3 H4: re-graded
    S -> M; the schema crosses an external vendor boundary, requires reconciling
    the parser against every field the schema defines, and the cli-json-output.md
    "external boundary we don't control" caveat (Known Gaps #7) means the
    plan also revisits the conversion's maintenance cost.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/cli-json-output.yaml            # NEW
    - docs/contracts/cli-json-output.md              # DELETED
    - scripts/llm_utils.py
  exit_criteria:
    - "cli-json-output.yaml exists at contract_version: 1, status: ratified"
    - "llm_utils.py reads or asserts equivalence to YAML; .md deleted"
    - "Plan addresses Known Gap #7 (vendor boundary maintenance cost) and either commits to the conversion or documents an explicit exemption"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: M                              # round-3 H4: upgraded from S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.18
  tier: T-1
  name: Convert copilot-cli.md to .yaml + wire copilot_wrapper.py to read it
  intent: |
    REPORT-ONLY + small IMPLEMENTATION. Copilot CLI invocation contract
    (args, @filepath semantics, -p quoting rules) becomes structured YAML.
    copilot_wrapper.py consumes the YAML directly. Critical because the
    @file vs user-message distinction (CLAUDE.md "Copilot CLI gotcha") is
    exactly the subtle semantic drift this ritual is built to catch. Round-3
    H4: re-graded S -> M; the wrapper has multiple call sites that each
    encode an aspect of the invocation contract, and the conversion requires
    auditing each.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/copilot-cli.yaml                # NEW
    - docs/contracts/copilot-cli.md                  # DELETED
    - scripts/copilot_wrapper.py
  exit_criteria:
    - "copilot-cli.yaml exists at contract_version: 1, status: ratified"
    - "copilot_wrapper.py consumes the YAML; .md deleted"
    - "All copilot_wrapper.py call sites audited against the YAML invocation contract"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: M                              # round-3 H4: upgraded from S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

- id: T-1.19
  tier: T-1
  name: Convert delegate-cli.md to .yaml + add canonical consumer
  intent: |
    REPORT-ONLY consumer-identification + small IMPLEMENTATION conversion.
    Same shape as T-1.18 for delegate-cli.md. The planning session first
    greps the codebase to identify the canonical consumer of the delegate-cli
    contract; if none exists, this becomes a REPORT-ONLY plan only (produce
    consumer-identification deliverable + recommendation: defer YAML conversion
    until a consumer exists, OR pick a script and wire it). Round-3 LOW item
    resolution: the bare `scripts/` directory in v2 files_in_scope is
    replaced with an explicit two-step pattern.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/delegate-cli.yaml               # NEW (only if consumer identified)
    - docs/contracts/delegate-cli.md                 # DELETED (only if YAML lands)
    - docs/REPORT-delegate-cli-consumer-identification.md   # NEW (always)
    - scripts/<identified_consumer>.py               # AMEND (only if consumer identified)
  exit_criteria:
    - "REPORT deliverable enumerates all current uses of delegate-cli in the codebase (grep audit)"
    - "Plan either (a) identifies a canonical consumer + lands the YAML conversion wired to it, OR (b) documents 'no consumer; defer conversion' in the REPORT and leaves the .md in place pending future consumer"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

# === T0.12.5: Class A ops_recommendations + ops_decisions ratification ===
- id: T0.12.5
  tier: T0
  name: Ratify Class A contracts for ops_recommendations + ops_decisions; retire ops-data-store.md
  intent: |
    REPORT-ONLY. Produce docs/contracts/ops_recommendations.yaml and
    docs/contracts/ops_decisions.yaml at contract_version: 1. Walk every field;
    ratify description, semantics, populated_by, write_time_validation, dq_intent,
    governance_notes. Cross-system fields use $ref into the Class C contracts
    (depends on T0.12.7). Reconcile against existing scattered sources (Pydantic
    model, DDL COMMENT, ops.yaml, PROJECT_CONTEXT prose, ops-data-store.md).
    Retire ops-data-store.md by splitting per-table schema content into the new
    YAMLs and migrating non-schema content into storage-substrate.yaml or per-table
    governance blocks. Apply migration rule from INTENT Part 4 Invariant 2:
    add _contract_version Iceberg column nullable, no historical backfill, read
    paths use COALESCE.
  depends_on: [T-1.12, T0.12, T0.12.7]   # roadmap edits + Pydantic foundation + Class C contracts
  files_in_scope:
    - docs/contracts/ops_recommendations.yaml
    - docs/contracts/ops_decisions.yaml
    - docs/contracts/ops-data-store.md           # SPLIT and retired
    - docs/contracts/storage-substrate.yaml      # NEW -- absorbs non-schema bits of ops-data-store.md
  exit_criteria:
    - "Both contract YAMLs exist at contract_version: 1, status: ratified"
    - "Every field carries description, semantics, populated_by, dq_intent (or $ref + dq_intent_local)"
    - "ops-data-store.md content fully migrated and the file deleted"
    - "_contract_version Iceberg column added to both tables; portal stamps it on new writes; historical rows remain NULL"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25]
  effort: M
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

# === T0.12.6: Class A telemetry contracts (decomposed; NOT STRATEGIC) ===
- id: T0.12.6
  tier: T0
  name: Ratify Class A telemetry table contracts (greenfield; decomposed)
  intent: |
    REPORT-ONLY parent placeholder. Round-2 architect issue A2 resolution:
    flipped strategic from true to false; this item is the placeholder for a
    DECOMPOSED set of atomic per-table REPORT-ONLY plans (one per telemetry
    table), per the AGENTS.md freeze override (L-effort items normally
    classified strategic decompose into atomic IMPLEMENTATION/REPORT-ONLY
    plans during /plan under freeze). Greenfield treatment -- current
    telemetry implementation is a draft, not a contract. Outputs feed both
    the personal-account substrate and T3 verifier work.
  depends_on: [T-1.12, T0.12, T0.12.7]
  files_in_scope: []                     # filled per atomic plan
  decomposition_hints:                   # NEW (architect A2)
    split_by: per_table
    atomic_plans:
      - "Ratify telemetry_sessions.yaml"
      - "Ratify telemetry_phases.yaml"
      - "Ratify telemetry_steps.yaml"
      - "Ratify telemetry_process_events.yaml"
      - "Ratify telemetry_model_calls.yaml"
      - "Ratify telemetry_transcripts.yaml"
      - "Ratify telemetry_agent_invocations.yaml"
    rationale: |
      Each table has distinct field semantics. Bundling produces shallow
      ratification. Atomic plans give each table a dedicated Step 10
      multi-perspective critique.
  exit_criteria:
    - "All seven telemetry_*.yaml contracts exist at contract_version: 1, status: ratified"
    - "Cross-contract join entries land in docs/contracts/_joins.yaml"
    - "Each atomic plan independently converges on Step 10 critique"
  related_candidate_decisions: [CD.25]
  effort: L
  strategic: true                        # round-3 A6 correction: L items are strategic; freeze override is decomposition_hints, NOT strategic:false (the round-2 architect A2 fix mis-applied the override)
  bootstrap_completion_exempt: true
  status: not_started

# === T0.12.7: Class C cross-system invariants ===
- id: T0.12.7
  tier: T0
  name: Ratify Class C cross-system invariants
  intent: |
    REPORT-ONLY. Produce docs/contracts/source-lineage.yaml,
    docs/contracts/project-id.yaml, docs/contracts/session-id.yaml. Cross-system
    contracts that constrain multiple Class A and Class B contracts. Class A
    contracts $ref into these.
  depends_on: [T-1.12]
  files_in_scope:
    - docs/contracts/source-lineage.yaml
    - docs/contracts/project-id.yaml
    - docs/contracts/session-id.yaml
  exit_criteria:
    - "All three Class C contract YAMLs exist at contract_version: 1, status: ratified"
    - "Step 10 multi-perspective critique converges"
  related_candidate_decisions: [CD.25, CD.10]
  effort: S
  strategic: false
  bootstrap_completion_exempt: true
  status: not_started

# === T1.12: Class B Lambda verb ratifications (DEFERRED until CD.16 ratifies) ===
# Round-3 H1 correction: gate moved from CD.17 (STRATEGIC plan-artefact freeze) to
# CD.16 (per-Lambda Lambda-deploy gating). CD.16 explicitly replaces the Decision-67
# Lambda-deploy blanket per docs/ROADMAP-PLATFORM.yaml:354+.
- id: T1.12
  tier: T1
  name: Ratify Class B Lambda verb contracts (gated on CD.16 ratification)
  intent: |
    REPORT-ONLY parent placeholder, DEFERRED on CD.16 (round-3 H1 correction;
    v2 incorrectly cited CD.17). Round-2 consensus C4 + adversarial #5 + #7
    resolution: Class B ratifications under the Lambda-deploy freeze produce
    contracts that never transition out of provisional_v0 (no traffic =
    no signal). Defer until CD.16 ratifies (significantly earlier than CD.17
    reversal in the dependency graph). Decomposes into per-Lambda atomic
    REPORT-ONLY plans authoring lambda-log-rec.yaml, lambda-log-decision.yaml,
    lambda-query.yaml, lambda-update-rec.yaml, lambda-list-tools.yaml,
    lambda-maintenance.yaml at status: provisional_v0 with staggered
    re-ratification triggers per INTENT Part 6B.
  depends_on: [T-1.12, T0.12.5, T0.12.7]
  decision_required_before:               # standard gate name for "wait for CD"
    - "CD.16 ratifies (Lambda-deploy per-Lambda gating in force)"
  files_in_scope: []                       # filled per atomic plan
  decomposition_hints:
    split_by: per_lambda
    atomic_plans:
      - "Ratify lambda-log-rec.yaml (provisional_v0; trigger 500 invocations OR 60 days)"
      - "Ratify lambda-log-decision.yaml (provisional_v0; trigger 200 invocations OR 90 days)"
      - "Ratify lambda-query.yaml (provisional_v0; trigger 2000 invocations OR 60 days)"
      - "Ratify lambda-update-rec.yaml (provisional_v0; trigger 500 invocations OR 90 days)"
      - "Ratify lambda-list-tools.yaml (provisional_v0; trigger 500 invocations OR 120 days)"
      - "Ratify lambda-maintenance.yaml (provisional_v0; trigger 90 days only)"
    rationale: |
      Each Lambda has distinct verb semantics; per-Lambda atomic plans give each
      contract its own Step 10 critique. Triggers staggered per Part 6B.
      Round-3 M2: atomic decomposition children inherit the parent's
      `bootstrap_completion_exempt` status automatically; no separate enumeration
      required.
  exit_criteria:
    - "All six Lambda verb contract YAMLs exist at contract_version: 1, status: provisional_v0"
    - "Each carries explicit re_ratification trigger per INTENT Part 6B stagger"
    - "Each atomic plan independently converges on Step 10 critique"
  related_candidate_decisions: [CD.25, CD.10, CD.11, CD.16]
  effort: L
  strategic: true                        # round-3 A6 correction
  bootstrap_completion_exempt: false      # post-CD.16-ratification; standard ratification
  status: not_started                     # round-3 LOW: use standard enum + decision_required_before field (T-1.12's schema amendment adds decision_required_before to TierItem) rather than a novel status string
```

**Round-3 M2 rule** (applies to T0.12.6 AND T1.12 above): atomic decomposition children of a parent inherit the parent's `bootstrap_completion_exempt` value automatically -- whether the parent is exempt (`true`) or not (`false`). No separate enumeration in the exemption prose set is required for either case. The bookkeeping rule reads `decomposition_hints` and stitches inheritance at plan-filing time. **Sanity note**: T1.12's parent is `bootstrap_completion_exempt: false`, so its six atomic Lambda-contract children inherit `false` -- they ratify post-CD.16 under the normal flow, not under bootstrap. T0.12.6's parent is `bootstrap_completion_exempt: true`, so its seven atomic telemetry-contract children inherit `true`. **Round-3 A3 + architect-LOW resolution**: T-1.10 is already `status: complete` and its current SKILL.md does NOT read `decomposition_hints` -- T-1.12 lands the SKILL.md amendment (see T-1.12 files_in_scope) that teaches the bookkeeping rule to honour this inheritance.

### 8B - Modified depends_on edges on existing tier_items

T-1.12 (the implementation tier item) applies these edits to existing tier_items in `docs/ROADMAP-PLATFORM.yaml`:

| tier_item | Add to depends_on | Reason |
|-----------|-------------------|--------|
| T0.13 (Iceberg DDL generator from Pydantic models) | T0.12.5 | Codegen consumes ratified ops contracts |
| T0.7a (log-rec Lambda handler) | T1.12 | Class B verb contract ratified post-CD.16 (round-3 H1 correction) |
| T0.7b (log-decision Lambda handler) | T1.12 | Same |
| T0.7c (query Lambda minimum verb set) | T1.12 | Same |
| T1.1 (update-rec Lambda) | T1.12 | Same |
| T1.3 (list-tools + describe Lambda) | T1.12 | Same |
| T1.4 (maintenance Lambda) | T1.12 | Same |
| T3.1 (Verifier harness foundation) | T0.12.6 | Telemetry contracts must ratify before verifier work |
| T3.2 (Causal-chain verifier) | T0.12.6 | Same |

### 8C - Bootstrap COMPLETION exemption expansion + CD.25-scoped termination clause

The existing bootstrap COMPLETION exemption set in `docs/ROADMAP-PLATFORM.yaml` lines 61-71 is currently CLOSED: it enumerates `{T-1.0..T-1.6, T0.6, T0.7a..c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14}` and terminates at CD.1 ratification (line 70). The new ratification items proposed here are NOT in that set, and CD.25 is gated by T0.7b deployment (which is governed by CD.16 ratification + per-Lambda gating).

**T-1.12 MUST expand the exemption set in the same commit it adds the new tier_items**. Specifically, the expanded set is:

```
{T-1.0..T-1.6,                                    # existing -- terminates at CD.1 ratification
 T-1.11, T-1.12,                                  # NEW -- ritual + enforcement
 T-1.13, T-1.14, T-1.15, T-1.16, T-1.17, T-1.18, T-1.19,   # NEW -- .md -> .yaml conversions
 T0.6, T0.7a..c, T0.8, T0.9, T0.11, T0.12, T0.13, T0.14,   # existing -- terminates at CD.1 ratification
 T0.12.5, T0.12.6, T0.12.7}                       # NEW -- Class A + C ratifications
```

T1.12 is NOT added to the exemption -- it explicitly waits on CD.16 ratification and ratifies under the normal post-ratification flow.

**Round-3 M6: CD.25-scoped termination clause.** The existing exemption terminates at CD.1 ratification, which doesn't cover items gated by CD.25. T-1.12 ALSO amends the exemption clause itself to add a parallel termination:

```
Original (ROADMAP-PLATFORM.yaml line 70):
  "Exemption ends at CD.1 ratification (i.e. the moment T-1.1 completes)."

Amended (T-1.12 lands this):
  "Exemption ends at CD.1 ratification for items {T-1.0..T-1.6, T0.6, T0.7a..c,
   T0.8, T0.9, T0.11, T0.12, T0.13, T0.14}; exemption ends at CD.25 ratification
   for items {T-1.11..T-1.19, T0.12.5, T0.12.6, T0.12.7}."
```

This explicit two-clause termination prevents the new items from being orphaned when CD.1 ratifies (which they would otherwise be, since CD.25 ratifies independently via the log-decision Lambda).

Without this exemption expansion + the parallel termination clause, the new ratification items deadlock: CD.25 cannot ratify (T0.7b not deployed yet) AND no exemption permits completion-with-pending-CD. The expansion mirrors the existing CD.1 / T-1.1 / T0.7b precedent already documented in ROADMAP-PLATFORM.yaml.

### 8D - START eligibility (round-2 adversarial #2 secondary resolution)

The existing bootstrap START eligibility clause permits T-1 items with `depends_on: []` AND T0 items with `depends_on: []` to start under bootstrap. Items with non-empty `depends_on` are eligible once their predecessors complete -- standard rule. All the new tier_items in 8A respect this: T-1.11 has `depends_on: []`; T-1.12..T-1.19 depend on T-1.12 (or its predecessors); T0.12.5/.6/.7 depend on T-1.12 + T0.12; T1.12 has `decision_required_before: CD.16 ratifies`. No START-side cycles.

---

## Part 9 - Failure modes considered

### 9A - Ratification fatigue

Risk: every codegen plan slows down because a ratification predecessor must run first.

Mitigation: ratification fires only for Class A, B, C contracts. The bar is explicit. Internal helpers, refactors, scripts, and one-process logic stay out. A contract is ratified once; subsequent plans that consume it pay no ratification tax. Amendment plans fire only on actual amendments.

Residual risk: agents reading the ritual may apply it too broadly. Mitigation: the CD wording and the planning skill explicitly enumerate non-examples.

### 9B - Premature ratification

Risk: ratifying hypothetical semantics for Class B Lambdas that have never seen real traffic produces ratified-but-wrong contracts.

Mitigation: (a) v0-provisional state with explicit re-ratification trigger (Part 6B), with **staggered per-Lambda triggers** to avoid concurrent re-ratification spikes (Part 6B); (b) Class B ratifications themselves DEFERRED until **CD.16 ratifies** (Part 6C; round-3 H1 correction -- previously cited CD.17 in error). Under the freeze, no Class B contracts are authored; when CD.16 ratifies and per-Lambda deploys become legal, ratifications proceed with v0-provisional triggers active. Both layers of defence: stagger across Lambdas (so they don't all re-ratify together) AND defer authoring until real signal exists.

Residual risk: even staggered triggers may all fire within a short window if traffic ramps unevenly. Mitigation: trigger thresholds reviewed at the first Class B ratification plan in light of expected traffic per Lambda.

### 9C - Scope creep within a ratification session

Risk: a session intended to ratify ops_recommendations balloons into "let's re-architect everything."

Mitigation: each ratification plan scopes to a named contract or a small named cluster. The Step 10 critique gate explicitly checks for scope creep. A ratification plan that tries to ratify more than 3-4 contracts at once should split.

### 9D - Cost of `_contract_version` column

Risk: every Class A table grows one int column; every writer stamps it; every query that doesn't care still selects it.

Mitigation: cost is uniform and predictable. The benefit (semantic-evolution boundary observable in the data) is non-uniform and expensive when the alternative bites. Acceptable trade.

**Computed (round-2 adversarial #6 quantification)**: int column at 4 bytes uncompressed; under Parquet gzip on a uniform column (most rows share the same contract_version since bumps are rare events), compressed cost <1 byte per row. At the projected 100 TB scale, ~25 GB total across all Class A tables -- approximately 0.025% of the storage envelope. Cost-projection envelope in `docs/ROADMAP-PLATFORM.yaml::cost_projection.projected_100tb_scale` is unaffected.

**Round-3 LOW (assumption stated)**: the ~0.025% figure assumes an average row size of ~3.2 KB, which is order-of-magnitude correct for telemetry payloads (the bulk of the projected 100TB envelope) but **higher than typical for ops_recommendations** (which carries short string fields averaging more like 500 bytes/row). The figure is a conservative upper bound; if telemetry compresses better than estimated OR ops rows dominate the mix, the percentage drops further. Revisit precise per-table figures if workload shifts substantially, or if storage line item exceeds 50% of monthly bill (per existing roadmap re-evaluation trigger).

### 9E - Single global `_joins.yaml` vs per-contract `joins:` sections

Risk: a single global file becomes a merge-conflict hotspot; per-contract sections drift between the two sides of the join.

Mitigation: the INTENT picks the single global file by default and explicitly defers the decision to revisit if scale becomes painful. First ratification plan that uses joins decides per-experience.

### 9F - The walking-skeleton failure on Class A

Risk: Class A contracts (data schemas) cannot use v0-provisional. Does this mean we can't iterate them at all?

Resolution: Class A contracts CAN be amended via the forward-compat-only path with no ceremony beyond a small amendment plan. The constraint is only on `semantic_break: true` amendments, which require the full ritual. So Class A is iterable; it just can't silently re-define existing semantics.

### 9G - The reviewer-burden multiplier

Risk: every Class A/B/C ratification plan has a Step 10 multi-perspective critique gate. That's two subagent invocations per plan. With ~15 ratification plans across T0/T1/T3, that's ~30 critique invocations.

Mitigation: the critique invocations cost is small relative to the cost of getting a contract wrong. The investment is intentional. Cost will be revisited if it becomes prohibitive in practice.

### 9H - Drift between contract YAML and actual code

Risk: a contract YAML claims field X exists with semantics Y; the Pydantic model has field X with different semantics OR a different field Z.

Mitigation: **two-tier enforcement** (round-2 consensus issue C5 resolution):

1. **T-1.12 lands a minimal CI drift gate** in `scripts/validate.py` that validates `docs/contracts/*.yaml` structurally:
   - Pydantic schema conformance
   - `$ref` resolution (referenced file exists, pointer resolves, no chain-depth >1; round-3 M3 resolution)
   - Status state machine (legal transitions only)
   - description/semantics diffs require an accompanying `amendment_log[]` entry with `change_class` per Invariant 3 (round-3 H2 resolution)
   - Duplicate-inline definitions of `$ref`-referenced fields rejected
   This catches "contract YAML is malformed or self-inconsistent."
2. **T0.13 and sibling codegen plans add a Pydantic-vs-YAML drift gate** that compares the Pydantic model's field list and types against the contract YAML's `fields:` block. This catches "Pydantic model and contract YAML disagree on the schema."

The first gate makes the ritual enforceable from T-1.12 onward; the second locks Pydantic + contract together once codegen plans land. Without (1), the ritual is voluntary discipline; without (2), Pydantic can silently drift from the contract.

**Residual risk (round-3 M4)**: read-side enforcement of the `COALESCE(_contract_version, 1)` rule for historical rows (Part 4 Invariant 2) is implicit -- the catalogued readers (`_joins.yaml::cross_version_policy.coalesce_legacy: true`, the `query` Lambda once ratified) honour it, but uncatalogued ad-hoc Athena queries written by humans or future agents may filter on `_contract_version = 1` directly and silently miss historical rows. Mitigation options for follow-on plans: (a) view-level enforcement via SCD2 `_current` view that includes the COALESCE; (b) presubmit lint of `.sql` files in the repo flagging `_contract_version` predicates that don't COALESCE; (c) documentation in the storage-substrate contract. Choice deferred to first plan that hits this in practice.

### 9I - Enforcement bypass / fake ratification (round-2 adversarial #3)

Risk: an agent (or a careless edit) sets `status: ratified` on a malformed or incomplete contract YAML and proceeds with codegen.

Mitigation: T-1.12's CI drift gate is the single enforcement surface. It runs at presubmit and full-CI tiers. It rejects:

- Malformed YAML structure (Pydantic schema rejection)
- Missing required fields (description, semantics, populated_by, dq_intent or dq_intent_local)
- `$ref` pointing at non-existent files or fields
- `$ref` resolver chain depth > 1 (Class C contracts are leaf-only; no chained refs)
- Duplicate-inline definitions of `$ref`-referenced fields
- description/semantics diffs without an accompanying `amendment_log[]` entry (round-3 H2: the entry's `change_class` distinguishes `prose_improvement` from `semantic_break: true` redefinition; either is accepted with the appropriate flags, bare diffs are not)
- Status transitions outside the state machine (e.g., `deprecated -> ratified`)
- `amendment_log[]` entries with `change_class` outside the closed vocabulary

`status: ratified` is a structural claim verified by the gate. An agent typing the word does not make it so.

Residual risk: the gate itself is code; a malicious or careless edit to `validate.py` could disable it. Mitigation: gate is covered by `tests/test_contracts.py` (also landed in T-1.12); ruff + mypy + pytest run at presubmit. A PR disabling the gate would fail the test that asserts the gate runs.

---

## Part 10 - Known Gaps and explicit deferrals

Round-2 critique-converged deferrals (genuinely out of scope):

1. **Single global `_joins.yaml` vs per-contract `joins:` section trade-off.** Defaults to single global; revisits with the first ratification plan that consumes the joins surface heavily.

2. **Whether scope of contract YAMLs covers product tables.** Phase 2 product work introduces new tables (`market_data`, `backtest_results`, etc.). These are Class A per definition, but ratification predecessors for them are out of scope for this INTENT -- they get added when Phase 2 platform-side roadmap items land.

3. **Whether `docs/contracts/README.md` is auto-generated from the YAMLs.** The directory grows substantially under this ritual (~20+ YAML files at steady state). An auto-generated index would help discovery. Decision deferred to first plan that suffers from the discovery problem -- likely lands as a small enhancement to T-1.12's CI drift gate.

4. **Cross-contract amendment cascade policy.** If `source-lineage` Class C contract amends, what is the cascade discipline for `ops_recommendations` + telemetry_* contracts that `$ref` into it? `min_contract_versions` + `cross_version_policy` (Part 5) is the minimal discipline. A concrete cascade-amendment plan template lands with the first Class C amendment whenever it occurs (round-2 adversarial #10).

5. **Interaction with the deferred `docs/plans/PLAN-platform-extraction-strategy.md`.** That plan proposed split-repo + submodule extraction; the AWS-migration INTENT formally deferred it in favour of monorepo + `project_id`. This INTENT inherits the deferral.

6. **Self-referential T-1.11 status flip handling (round-2 adversarial #6 / R6).** T-1.11 lands the INTENT that defines the ritual; the implement-skill bookkeeping rule (T-1.10) was designed without anticipating an item that is itself the substrate the bookkeeping reads. T-1.12 verifies the bookkeeping rule handles T-1.11's self-referential status flip correctly; if not, a small bookkeeping-rule amendment lands as part of T-1.12 or a sibling. This is operationally minor (worst case is manual status flip).

7. **Final disposition of `docs/contracts/cli-json-output.md` external boundary.** Conversion to YAML (T-1.17) is proposed, but the schema crosses an external boundary (the CLI vendor) we do not control. If vendor schema churns frequently, the YAML becomes a maintenance burden. T-1.17's plan revisits the conversion if the maintenance cost is high; alternative is "keep as markdown, accept it remains unenforced for now." Documented here as a genuine deferral signalled by the conversion plan.

8. **Catastrophic-rollback playbook for ratified contracts in `deprecated` state.** Part 4 Invariant 6 names the state but does not author a generic playbook for migrating consumers off a deprecated contract. First catastrophic rollback (if ever) authors the playbook. Deferred because (a) we hope to never use it; (b) the playbook is shaped by the specific failure that triggers it.

Items previously deferred in round-1 that are NOW resolved (no longer in the deferral list):

- ~~CI drift gate implementation~~ -- now landing in T-1.12 (Part 9H, Part 9I).
- ~~Re-ratification triggering mechanism~~ -- now landing in T-1.12 (preflight hook).
- ~~Re-ratification trigger thresholds~~ -- now staggered per-Lambda in Part 6B with concrete defaults.
- ~~Markdown vs YAML disposition for existing files~~ -- now resolved in Part 3A (all eight existing `.md` files convert to `.yaml`).
- ~~_contract_version migration for existing tables~~ -- now resolved in Part 4 Invariant 2 (read-side COALESCE, no historical backfill).
- ~~Storage cost analysis~~ -- now computed in Part 9D (~0.025% of 100TB envelope, row-size assumption stated).
- ~~Catastrophic-rollback state~~ -- now `status: deprecated` in Part 4 Invariant 6.

Items added/resolved in round-3 (no longer gaps):

- ~~CD.17 vs CD.16 conflation~~ -- corrected throughout; Class B Lambda gate is CD.16, STRATEGIC plan-artefact gate is CD.17.
- ~~Invariant 3 vs Invariant 4 gate contradiction~~ -- resolved via `amendment_log[]` `change_class` discipline (Invariant 3 + Invariant 4 + Part 9H + Part 9I).
- ~~`bootstrap_completion_exempt` field schema gap~~ -- T-1.12 amends `scripts/platform_roadmap.py` (T-1.5 schema) to accept the new field.
- ~~T-1.13..T-1.19 effort under-grading~~ -- T-1.14, T-1.17, T-1.18 re-graded S -> M.
- ~~T-1.12 effort under-grading~~ -- upgraded to L with `decomposition_hints` for optional split.
- ~~Decomposition children exemption inheritance~~ -- explicit rule under T1.12 (and applies to T0.12.6 too).
- ~~$ref resolver behaviour in T-1.12 exit_criteria~~ -- enumerated explicitly.
- ~~Reader-discovery residual risk~~ -- documented in Part 9H residual risk paragraph.
- ~~`_joins.yaml` incremental landing semantics~~ -- Part 5 round-3 M5 clause.
- ~~CD.25-scoped exemption termination~~ -- Part 8C parallel termination clause.
- ~~CD.25 lifetime-pending sequencing~~ -- Part 11 round-3 M7 sequencing note.
- ~~Athena ADD COLUMNS gotcha for T0.12.5~~ -- surfaced in Part 4 Invariant 2.
- ~~`deprecated` terminal absolute restriction~~ -- softened to "default forbidden, expensive-but-possible reversal" in Part 4 Invariant 6.
- ~~T-1.19 bare `scripts/` directory~~ -- replaced with explicit two-step consumer-identification + conditional conversion.

These gaps that remain are intentional. Each becomes a small, well-scoped follow-on plan when its consumer surfaces.

---

## Part 11 - Sequencing summary

For an agent reading this INTENT and looking for what to do next:

1. **First**: this INTENT (T-1.11) lands on `agent/pre-codegen-contract-ratification`, passes Step 9 + Step 10 critique, gets reviewed and merged. T-1.11 marks complete under the bootstrap COMPLETION exemption (CD.25 still `state: pending`).
2. **Second**: T-1.12 (IMPLEMENTATION) lands the enforcement layer: applies Part 8 roadmap edits to `docs/ROADMAP-PLATFORM.yaml` (adds CD.25, new tier_items, depends_on edges, expanded bootstrap COMPLETION exemption set); lands `scripts/contracts.py` Pydantic schema; lands the CI drift gate in `scripts/validate.py`; lands the preflight hook in `scripts/session_preflight.py`. After T-1.12 merges, the ritual has teeth -- `status: ratified` claims are enforceable.
3. **Third (parallelisable, post T-1.12)**:
   - `.md -> .yaml` conversions: T-1.13..T-1.19 run in parallel, each converting one existing prose contract with its runtime consumer.
   - Class C ratification: T0.12.7 (source-lineage, project-id, session-id).
   - Class A ratifications: T0.12.5 (ops_recommendations + ops_decisions; depends on T0.12.7 for $ref targets); T0.12.6 (telemetry tables; decomposed into seven atomic per-table REPORT-ONLY plans).
4. **Fourth**: codegen plans run, consuming their ratified contracts. T0.13 first (Iceberg DDL generator; consumes ops_recommendations + ops_decisions YAMLs and the cross-version-aware `_contract_version` column discipline).
5. **Fifth (under Lambda-deploy freeze)**: T0.7a/b/c (Lambda handlers) **wait on T1.12 + CD.16 ratification** (round-3 H1 correction). They cannot proceed without the Class B verb contracts, which themselves wait on CD.16 ratification (NOT CD.17 reversal -- that's a separate freeze with a later trigger). Other T0 / T1 / T2 work that is NOT Class B-dependent proceeds in parallel.
6. **Sixth (post CD.16 ratification)**: T1.12 runs (Class B ratifications, six atomic per-Lambda plans, each authoring a `provisional_v0` contract with staggered re-ratification triggers per Part 6B). After T1.12 completes, T0.7a/b/c and T1.1/T1.3/T1.4 codegen plans run.

**Round-3 M7 sequencing note**: CD.25 itself is `state: pending` for the full project lifetime until the log-decision Lambda is live AND per-Lambda deploys are legal under CD.16. Concretely: CD.25 ratifies via T0.7b (the log-decision Lambda), which depends on T1.12 (Class B contract ratification), which depends on CD.16 ratification. The `bootstrap_allowance: true` on CD.25 (Part 7) covers this in principle, but the practical implication is that the new `docs/contracts/` discipline runs under a pending CD.25 for many tier waves. Readers of the roadmap should expect to see CD.25 pending alongside fully-active contract YAMLs -- this is the bootstrap-clause operating as designed.

**Round-3 A4 fallback (CD.25 never-ratifies sunset)**: If T0.7b is itself indefinitely deferred (e.g. Decision 67's full reversal stalls) and CD.25 has been `state: pending` for more than 12 months from this INTENT's merge date, an explicit re-ratification path opens: the human (or a successor governance mechanism) MAY file CD.25 manually via direct edit to `docs/DECISIONS.md` + `docs/ROADMAP-PLATFORM.yaml`, bypassing the log-decision Lambda. This is a back-stop, not a normal path; it acknowledges that the bootstrap-allowance mechanism assumes the gating Lambda eventually materialises, and the ritual should not be hostage to that materialisation indefinitely. The 12-month threshold is a placeholder; first time the human invokes the fallback, this INTENT (or its successor) is amended with the actual threshold + invocation procedure.
7. **Seventh**: the AWS migration (T2.1) proceeds with the ratified-and-codegened substrate. The personal-account substrate inherits sound contracts from day one.
8. **Eighth (post-deploy)**: Class B v0-provisional Lambdas accumulate production traffic. Their staggered re-ratification triggers fire in turn. Each triggers a REPORT-ONLY re-ratification plan with Step 10 critique. Confirmed contracts flip to `ratified`; contracts needing change land amendments via the `semantic_break: true` path if necessary.

---

## Acknowledgements

This INTENT incorporates several direct user reframings during the planning session that materially shaped the design:

1. **Telemetry-is-not-in-production correction** (round-1). The telemetry tables were initially described as "in production"; the user accurately characterised them as a paused proof-of-concept with unactioned data. That reframing strengthened the case for greenfield treatment of telemetry contracts.

2. **Existing .md contracts are themselves the disease** (round-2). The user flagged that the existing `docs/contracts/*.md` files are prose contracts that bind nothing at runtime and are largely unreferenced -- exactly the failure mode this INTENT exists to cure. The corrected disposition (Part 3A) treats all eight existing markdown contracts as conversion targets under this ritual, not exemptions from it. This widened the ritual's reach (T-1.13..T-1.19) and clarified the default: YAML with a runtime consumer, not markdown.

3. **Enforcement is non-negotiable** (round-2). The user pushed back on "enforcement deferred to a downstream plan" and required the ritual to land enforceable at T-1.12. That requirement shaped CD.25's enforcement clause, the splitting of T-1.11 into ratify + implement, the CI drift gate scope, and the `enforcement_bypass` failure mode in Part 9I.

4. **Accept-with-deferral closure** (round-3). After round-3 split critique (architect PROCEED; adversarial REVISE with three verified HIGH live-state divergences), the user chose to address the corrections without a round-4 critique re-fire, on the rationale that downstream plans rediscover and resolve such divergences naturally during scoping. The closure is consistent with the methodology's "human explicitly accepts the current state with a defined deferral" convergence path.

Critique audit trail:
- Round-1: architect REVISE (10 issues, 3 HIGH) + adversarial REVISE (10 risks, 3 HIGH) -- all resolved in v2.
- Round-2: architect REVISE (10 issues, 2 HIGH) + adversarial REVISE (7 new risks, 2 HIGH) -- all resolved in v3.
- Round-3: architect PROCEED + adversarial REVISE (3 new HIGH live-state divergences verified against repo) -- resolved in v4 without re-critique per human direction.

The critique outputs are not preserved verbatim here but the resolutions are mapped per finding throughout the document.

## Author accountability note (round-3)

The round-3 adversarial caught three live-state divergences that earlier rounds did not surface because earlier critique invocations did not actively grep against the repo. The v3 author (this Claude session) invented the filename `scripts/roadmap_document.py` -- which does not exist -- as the T-1.5 schema location, and propagated it through five sites in the INTENT. The author also did not verify whether the existing schema used `extra="ignore"` or `extra="forbid"` before claiming the schema amendment would reject unknown fields. The author also did not verify that the bookkeeping rule in `.claude/skills/implement/SKILL.md` actually reads `decomposition_hints` before claiming it would enforce the M2 inheritance rule.

These were avoidable errors. The lesson carried forward: any future INTENT that references external file paths or external schema behaviour must include a "live-state verification" step BEFORE round-1 critique fires -- grep each cited path; read each cited schema; verify each claimed enforcement mechanism actually exists. This is a methodology improvement worth proposing in a separate plan (post-merge) -- the planning skill's Step 4 "Identify Affected Files" should explicitly require grep-verification of every file path written into a deliverable.
