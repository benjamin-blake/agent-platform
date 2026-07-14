# Plan

## Intent
Lay down the Annotated-Pydantic schema-as-code foundation (T0.12 of `ROADMAP-PLATFORM.yaml`). Establishes the canonical `RecPayload` and `DecisionPayload` models with `Annotated[T, DqXxx()]` markers as the single write-side source of truth for schema + DQ semantics, and adds a CI drift detector that keeps the new Pydantic surface aligned with `config/data_quality/*.yaml` during the coexistence window. This is the foundation that T0.13 (Iceberg DDL generator) and T1.6 (DQ runner reshape) build on, and the canonical payload contract that the T0.7a/T0.7b/T0.7c Lambda chain will consume once it lands.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3 (Lambda-packaged scope per `scripts/build_lambda.py:70`, which copies the entire `src/` tree into `data-pipeline.zip` — `src/schemas/` lands in the deploy artefact even though no handler imports it yet. Active deploy + smoke-test are DEFERRED per Decision 67; all VP steps therefore tagged `[pre-deploy]`.)

## Branch
agent/t-0-12-annotated-pydantic-schemas

## Phase
Platform tier T0 (Bootstrap — surface + account + minimum tooling). Tier item T0.12 in `docs/ROADMAP-PLATFORM.yaml`.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/schemas/__init__.py` | Create | Public surface; re-exports annotations + payloads |
| `src/schemas/annotations.py` | Create | Defines exactly 7 marker dataclasses: DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted. Module docstring documents the discipline ceiling per CD.12 |
| `src/schemas/rec.py` | Create | Canonical write-side `RecPayload` model with `Annotated[T, DqXxx()]` markers; mirrors the write-time + enforced fields in `ops.yaml::tables.ops_recommendations` |
| `src/schemas/decision.py` | Create | Canonical write-side `DecisionPayload` model with `Annotated[T, DqXxx()]` markers; mirrors `ops.yaml::tables.ops_decisions` |
| `scripts/validate.py` | Modify | Add `validate_pydantic_yaml_drift(failed)` function; wire into `run_python_checks` after `validate_platform_roadmap`. Supports `@migrating(target='YYYY-MM-DD')` allow-list and DqDeleted short-circuit |
| `tests/test_schemas_annotations.py` | Create | Marker construction, equality, repr, frozen-config tests |
| `tests/test_schemas_rec.py` | Create | RecPayload validation + `get_type_hints(..., include_extras=True)` introspection round-trip |
| `tests/test_schemas_decision.py` | Create | DecisionPayload validation + introspection round-trip |
| `tests/test_validate_dq_drift.py` | Create | Drift detector: happy / unmarked-divergence / @migrating allow-list / DqDeleted short-circuit / expired-migrating-marker fail |
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Bookkeeping: flip T0.12 status to `complete`, set `completed_at: "YYYY-MM-DD"` (set during bookkeeping step) |
| `docs/SESSION_LOG.md` | Modify | Bookkeeping: prepend new session entry summarising T0.12 implementation |

## Bundled Recommendations
None. Top priority-queue recs (rec-429, rec-027, rec-457, rec-468, rec-296) are all executor-frozen under CD.17 / Decision 67 and do not align with T0.12.

## Acceptance Criteria
- [ ] `src/schemas/annotations.py` defines exactly 7 markers (DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted) — verifiable by `grep -E "^class Dq" src/schemas/annotations.py | wc -l` returning `7`
- [ ] Markers documented in `src/schemas/annotations.py` module docstring; docstring explicitly states the CD.12 ceiling (adding an 8th non-DqDeleted marker requires a new candidate decision)
- [ ] `RecPayload` validates a known-good rec dict end-to-end (sampled from `logs/.recommendations-log.jsonl`)
- [ ] `DecisionPayload` validates a known-good decision dict end-to-end (sampled from `logs/.decisions-index.jsonl`)
- [ ] `typing.get_type_hints(RecPayload, include_extras=True)` returns DqXxx instances on annotated fields — verified by introspection test
- [ ] `validate_pydantic_yaml_drift` registered in `run_python_checks` after `validate_platform_roadmap`
- [ ] Drift detector fails CI when an overlapping field's check set in Pydantic differs from `ops.yaml` (no `@migrating` marker, no DqDeleted)
- [ ] `@migrating(target='YYYY-MM-DD')` allow-lists transitional divergence; expired markers (target date in the past) cause CI to fail
- [ ] `DqDeleted`-marked field is silently allowed even if absent from YAML; runner short-circuits checks per CD.12 discipline
- [ ] `bin/venv-python -m scripts.validate` exits 0 on this branch
- [ ] `bin/venv-python -m scripts.test_coverage_checker` reports 100% coverage on new files in `src/schemas/`
- [ ] No `bin/`, `CLAUDE.md`, or `AGENTS.md` files modified (off-limits per sibling Windows-migration work)
- [ ] `docs/ROADMAP-PLATFORM.yaml` T0.12 entry shows `status: complete` and `completed_at: "YYYY-MM-DD"` (the day the plan lands)
- [ ] `docs/SESSION_LOG.md` has a prepended entry for this session

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Marker count exactly 7 | `bin/venv-python -c "from src.schemas import annotations; markers=[n for n in dir(annotations) if n.startswith('Dq')]; assert len(markers)==7, markers; print('ok')"` | Prints `ok` | Marker count drift — adjust annotations.py to match exactly the 7 documented markers |
| 2 | [pre-deploy] | All markers importable from public surface | `bin/venv-python -c "from src.schemas import DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted, RecPayload, DecisionPayload; print('ok')"` | Prints `ok` | `src/schemas/__init__.py` missing re-exports — add them |
| 3 | [pre-deploy] | RecPayload happy-path validation | `bin/venv-python -m pytest tests/test_schemas_rec.py::test_recpayload_validates_known_good_dict -v` | Pass | Field mismatch — align RecPayload with the ops.yaml canonical fields |
| 4 | [pre-deploy] | RecPayload rejects invalid status | `bin/venv-python -m pytest tests/test_schemas_rec.py::test_recpayload_rejects_invalid_status -v` | Pass — invalid status (e.g. `"done"`) raises ValidationError | Literal guard missing — add `status: Annotated[Literal["open", "closed", "failed", "declined", "superseded"], DqAcceptedValues(...)]` |
| 5 | [pre-deploy] | DecisionPayload happy-path validation | `bin/venv-python -m pytest tests/test_schemas_decision.py::test_decisionpayload_validates_known_good_dict -v` | Pass | Field mismatch — align with `ops.yaml::ops_decisions` |
| 6 | [pre-deploy] | Annotated metadata introspection | `bin/venv-python -m pytest tests/test_schemas_rec.py::test_recpayload_annotated_metadata_extractable -v` | Pass — `get_type_hints(RecPayload, include_extras=True)` returns DqXxx instances on annotated fields | Marker not preserved — use `Annotated[T, DqXxx()]` syntax, not bare types |
| 7 | [pre-deploy] | Drift detector — aligned state passes | `bin/venv-python -m pytest tests/test_validate_dq_drift.py::test_drift_detector_passes_when_aligned -v` | Pass | YAML/Pydantic mismatch for `ops_recommendations` overlapping fields — reconcile |
| 8 | [pre-deploy] | Drift detector — unmarked divergence fails | `bin/venv-python -m pytest tests/test_validate_dq_drift.py::test_drift_detector_fails_on_unmarked_divergence -v` | Pass — synthetic divergence triggers failure | Detector logic too lenient — compare check sets per field and fail when symmetric diff is non-empty |
| 9 | [pre-deploy] | `@migrating` allow-lists divergence | `bin/venv-python -m pytest tests/test_validate_dq_drift.py::test_migrating_marker_tolerates_divergence -v` | Pass | Marker logic broken — ensure decorator stores `target` and detector consults it |
| 10 | [pre-deploy] | Expired `@migrating` marker fails | `bin/venv-python -m pytest tests/test_validate_dq_drift.py::test_expired_migrating_marker_fails -v` | Pass — marker with past-date target causes drift-detector failure | Date comparison missing — compare `target` against `datetime.utcnow().date()` |
| 11 | [pre-deploy] | DqDeleted field absent from YAML allowed | `bin/venv-python -m pytest tests/test_validate_dq_drift.py::test_dqdeleted_field_allowed_when_absent_from_yaml -v` | Pass | Detector flagging DqDeleted wrongly — short-circuit before YAML lookup |
| 12 | [pre-deploy] | validate.py end-to-end integration | `bin/venv-python -m scripts.validate 2>&1 \| grep -E "Pydantic-YAML drift\|PASS: pydantic"` | Section runs and prints PASS line | Hook not registered — add `validate_pydantic_yaml_drift(failed)` to `run_python_checks` after `validate_platform_roadmap(failed)` |
| 13 | [pre-deploy] | 100% test coverage on new files | `bin/venv-python -m scripts.test_coverage_checker` | Pass — no uncovered new code | Uncovered branches — extend tests; coverage gaps usually in error paths |
| 14 | [pre-deploy] | Full presubmit clean | `bin/venv-python -m scripts.validate` | Exit 0 | Address whatever it reports; common failures: ruff format, mypy informational (not blocking), test coverage |
| 15 | [pre-deploy] | Off-limits files untouched | `git diff --name-only main...HEAD \| grep -E '^(bin/\|CLAUDE\.md$\|AGENTS\.md$)' \|\| echo "OK: no off-limits files touched"` | Prints `OK: no off-limits files touched` (or grep returns nothing) | Touched an off-limits file — revert that change |
| 16 | [pre-deploy] | Roadmap bookkeeping applied | `git diff main...HEAD -- docs/ROADMAP-PLATFORM.yaml \| grep -A 3 "id: T0.12" \| grep "status: complete"` | Prints the matching `status: complete` line | T0.12 status not flipped — edit roadmap |
| 17 | [pre-deploy] | Session log bookkeeping applied | `git diff main...HEAD -- docs/SESSION_LOG.md \| grep -F "t-0-12-annotated-pydantic"` | Prints the matching diff line | SESSION_LOG.md not prepended — add entry |

## Constraints
- **No STRATEGIC plans** — IMPLEMENTATION only until Decision 67 is reversed (per CLAUDE.md Temporary Operational Constraints; CD.17).
- **No rescue agents or workaround loops** (Decision 55). If V2 verification fails unrecoverably, stop and analyse root cause — do not patch around it.
- **Off-limits files (per sibling Windows-migration work):** `bin/`, root-level `CLAUDE.md`, root-level `AGENTS.md`. Do not touch these in this session.
- **Single Portal Invariant:** This plan does NOT write recommendations or decisions; if a sub-step needs to file a follow-on rec (e.g. for the stale `telemetry_agent_invocations_current` view surfaced in preflight), use `scripts/ops_data_portal.py` only.
- **Warehouse-as-source-of-truth invariant:** This plan only reads `logs/.recommendations-log.jsonl` and `logs/.decisions-index.jsonl` as **sample fixtures** for round-trip tests — never as a write source.
- **Test isolation rules** (per `tests/CLAUDE.md`):
  - Never spawn `pytest tests/` from a test module — recursion risk.
  - Mock both `subprocess.Popen` AND `subprocess.run` for any subprocess-spawning code under test.
  - One consolidated import block per test module (ruff format silently drops duplicates).
- **No emojis in code, scripts, or docs.** Use plain ASCII hyphens.
- **Annotation vocabulary ceiling (CD.12):** Exactly 7 markers — adding an 8th non-DqDeleted marker requires a new candidate decision. Enforce via test that asserts the count.
- **Execution fields deferred:** `execution_result`, `execution_date`, `execution_branch`, `execution_pr_url`, `execution_steps` are **deferred pending normalisation review** (per `docs/PROJECT_CONTEXT.md`). Either omit them entirely from `RecPayload` for this phase, or mark them with `Annotated[Optional[T], DqDeleted(since='deferred-pending-review')]` to tolerate them in legacy reads. Recommended: omit — they belong to telemetry tables once normalised, not on the canonical write-side `RecPayload`.

## Context
- **Tier item:** T0.12 in `docs/ROADMAP-PLATFORM.yaml` (lines 1038-1063). `depends_on: []` — fully eligible.
- **Governing candidate decision:** CD.12 "DQ-as-Annotated-Pydantic; single source of truth; runner = alarm not gate". Pending ratification via T-1.1 + log-decision Lambda (T0.7b), but per the **bootstrap clause** in roadmap `agent_instructions`, T0 tier_items with `depends_on:[]` are eligible to START while CDs are pending. CD.12 is therefore treated as binding for this work.
- **Adjacent existing models:** `scripts/executor/jsonl_store.py::Recommendation` and `::Decision` are **read-side** models (Optional fields, `extra="ignore"`, used for deserialising legacy JSONL rows safely). The new `RecPayload` and `DecisionPayload` are **write-side canonical** models with `Annotated[T, DqXxx()]` markers — distinct purpose, distinct file, no displacement.
- **Established pattern:** `scripts/platform_roadmap.py` (T-1.5, merged 2026-05-19) is the recent precedent — Pydantic v2, `ConfigDict(extra="ignore")`, `field_validator`, loader function. The new schemas should mirror its style for consistency.
- **Coexistence window:** This plan does NOT retire `config/data_quality/*.yaml`. The drift detector is the bridge that keeps the two surfaces aligned until T1.6 (DQ runner reshape) retires the YAML. Both sources of truth coexist during this window.
- **CD.12 discipline points relevant here:**
  - Annotation vocabulary ceiling: 6 check markers + DqDeleted evolution marker. Adding a 7th check marker (i.e. an 8th total) requires a new CD.
  - Stateful invariants (status DAG, FK across tables, intra-table uniqueness) live in **handler code** (T1.x), NOT in Annotated metadata.
  - Distributional / drift checks live in the **DQ runner** (T1.6), NOT in Annotated metadata.
  - Schema evolution: field removal requires explicit `DqDeleted` marker; generator emits no DDL change for removed-via-marker fields.
- **Out-of-vocabulary YAML checks** (`expression`, `path_syntax`, `acceptance_lint`) deliberately do NOT have Annotated equivalents — they're handler-side write-time validators that already live in `scripts/ops_data_portal.py` (`_validate_file_path`, `_validate_context_length`, `lint_acceptance_command`). Per CD.12, those stay where they are.
- **Pydantic v2 is already pinned** (`requirements.txt:38`, `pydantic>=2.0.0`). `typing.Annotated` is stdlib for Python 3.12+. No new dependencies needed.
- **Lambda packaging note (drives V3 classification):** `scripts/build_lambda.py:70` does `shutil.copytree(ROOT / "src", app_dir / "src")` — the **entire** `src/` tree is bundled into `data-pipeline.zip`. Anything added under `src/` lands in the Lambda artefact on the next build, even when no handler imports it. This is why a plan that only adds unit-testable Python under `src/schemas/` is still classified V3 with a DEFERRED deploy step.
- **Non-blocking observation surfaced by preflight:** the Athena view `telemetry_agent_invocations_current` is **stale** (column count 20 vs derived 21). Out of scope for this plan; consider filing a separate rec via `ops_data_portal.file_rec` after merge.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` returns `agent/t-0-12-annotated-pydantic-schemas`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` not strictly required (CD.12 governs; not yet ratified into ops_decisions but binding per bootstrap clause)
- [ ] `docs/ROADMAP-PLATFORM.yaml` T0.12 entry and CD.12 read
- [ ] All files in Scope table located (5 of 11 are new; their parent directories — `src/schemas/`, `tests/` — exist or are creatable)
- [ ] Sample rec and decision dicts identified from `logs/.recommendations-log.jsonl` and `logs/.decisions-index.jsonl` for round-trip fixtures (use static fixtures committed to the test file — do not depend on the live JSONL caches)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Create `src/schemas/annotations.py`** with exactly 7 marker classes:
   - `DqNotNull(write_time: bool = False, enforced: bool = True, exclude_before: Optional[str] = None)`
   - `DqUnique(enforced: bool = True)`
   - `DqAcceptedValues(values: tuple[str, ...], enforced: bool = True)`
   - `DqRelationship(to_table: str, to_column: str, severity: Literal["error", "warn"] = "error")`
   - `DqRecency(warn_after_hours: int, error_after_hours: int)`
   - `DqRowCount(min: int, severity: Literal["error", "warn"] = "error")`
   - `DqDeleted(since: str)` — schema-evolution marker
   - Each as a frozen pydantic-config `BaseModel` (so they're hashable, comparable, and introspectable) OR plain frozen `dataclass`. Use the same pattern across all seven for consistency.
   - Module docstring documents the CD.12 ceiling and the rule "adding an 8th marker requires a new candidate decision".
   - Also export the `@migrating(target='YYYY-MM-DD')` decorator from this module (or from a sibling `_migration.py`) — it stores the target date on the decorated class for the drift detector to consult. **Date comparison must use `datetime.now(timezone.utc).date()` (not `datetime.utcnow().date()` which is deprecated, and not `date.today()` which is timezone-naive)** so that drift-detector behaviour is identical between developer laptops and the self-hosted runner in eu-west-2. Per-test fixtures should freeze time via `freezegun` or a similar fixture rather than depending on wall-clock.

2. **Create `src/schemas/rec.py`** with `RecPayload` model:
   - Use `Annotated[T, DqXxx()]` for each write-time / enforced field per `ops.yaml::ops_recommendations`.
   - Status as `Annotated[Literal["open", "closed", "failed", "declined", "superseded"], DqNotNull(write_time=True), DqAcceptedValues(values=("open", "closed", "failed", "declined", "superseded"))]`.
   - Effort as `Annotated[Literal["XS", "S", "M", "L", "XL"], DqNotNull(write_time=True, exclude_before="2026-05-01"), DqAcceptedValues(values=("XS", "S", "M", "L", "XL"))]`.
   - Priority, risk, source, title, file, context, acceptance, automatable, created_timestamp, last_updated_timestamp similarly.
   - **Omit** execution_* fields per the Constraints section (deferred pending normalisation review).
   - **Pre-condition:** `src/schemas/annotations.py` from step 1 exists and is importable.
   - **Post-condition:** `bin/venv-python -c "from src.schemas.rec import RecPayload; RecPayload(id='rec-001', status='open', ...)"` returns a valid instance.

3. **Create `src/schemas/decision.py`** with `DecisionPayload` model:
   - Same shape and discipline as `RecPayload` against `ops.yaml::ops_decisions`.
   - Id pattern `dec-\d+` enforced via `field_validator` (mirrors existing `Decision.validate_id` in `jsonl_store.py`).
   - Preserve the `decision_id` dual-write invariant (`model_validator`) — same as existing `Decision` model.
   - **Pre-condition:** annotations module exists.
   - **Post-condition:** importable and validates a known-good decision dict.

4. **Create `src/schemas/__init__.py`** that re-exports the public surface:
   - All seven Dq markers from `annotations`
   - `RecPayload` from `rec`
   - `DecisionPayload` from `decision`
   - `migrating` decorator
   - Module docstring states "Canonical write-side schemas with Annotated DQ metadata (T0.12, CD.12)."

5. **Create `tests/test_schemas_annotations.py`**:
   - `test_seven_markers_exposed` — exactly 7 marker classes via `dir(annotations)` introspection
   - `test_markers_are_frozen` — assignment to a marker attribute raises
   - `test_marker_equality` — two `DqNotNull(write_time=True)` instances compare equal
   - `test_marker_repr` — repr round-trip is informative
   - `test_dqaccepted_values_is_tuple` — list passed in raises (tuple-only for hashability)
   - `test_migrating_decorator_sets_target` — decorator stores `target` attribute on decorated class

6. **Create `tests/test_schemas_rec.py`**:
   - `test_recpayload_validates_known_good_dict` — fixture rec dict (literal in test file, not loaded from live JSONL) validates
   - `test_recpayload_rejects_invalid_status` — status="done" raises ValidationError
   - `test_recpayload_rejects_invalid_effort` — effort="XXL" raises
   - `test_recpayload_annotated_metadata_extractable` — `get_type_hints(RecPayload, include_extras=True)` returns DqXxx instances on annotated fields
   - `test_recpayload_id_pattern` — id="bad-id" raises

7. **Create `tests/test_schemas_decision.py`**:
   - Same shape as test_schemas_rec.py, adapted for DecisionPayload
   - Include `test_decisionpayload_dual_write_invariant` — `id="dec-050"` with `decision_id=50` succeeds; `decision_id=51` raises (mirrors existing test in test_executor / test_ops_data_portal)

8. **Modify `scripts/validate.py`** to add `validate_pydantic_yaml_drift(failed: list[str]) -> None`:
   - Walks `RecPayload` (and `DecisionPayload`) annotated fields via `get_type_hints(..., include_extras=True)`.
   - For each annotated field, extracts the set of `DqXxx` markers.
   - Loads `config/data_quality/ops.yaml`; for the matching table+column, extracts the canonical YAML check vocabulary (mapping `not_null` -> `DqNotNull`, `accepted_values` -> `DqAcceptedValues`, etc.).
   - Compares the two check sets per overlapping field.
   - Skip-list: fields marked `DqDeleted` are silently allowed.
   - Allow-list: fields decorated with `@migrating(target='YYYY-MM-DD')` are tolerated **until** target date is in the past. Compare against `datetime.now(timezone.utc).date()` (UTC-anchored) to avoid laptop-vs-runner skew; expired markers fail.
   - Failures append to `failed` list with a clear "field X: Pydantic has {A,B}, YAML has {A,C}" diagnostic.
   - **Important:** wire into `run_python_checks` AFTER `validate_platform_roadmap(failed)` and BEFORE `_check_graduation_guard(failed)`. The function follows the established pattern (`print("\n=== Pydantic-YAML DQ drift ===")` then PASS/FAIL message).
   - **Pre-condition:** `src/schemas/__init__.py` from step 4 exists; tests from steps 5-7 pass.

9. **Create `tests/test_validate_dq_drift.py`**:
   - `test_drift_detector_passes_when_aligned` — synthetic minimal Pydantic model + synthetic YAML with matching checks → no failure
   - `test_drift_detector_fails_on_unmarked_divergence` — Pydantic field has DqNotNull but YAML has DqNotNull + DqAcceptedValues → fail
   - `test_migrating_marker_tolerates_divergence` — divergence on a `@migrating(target='9999-12-31')` field → pass
   - `test_expired_migrating_marker_fails` — divergence on a `@migrating(target='1900-01-01')` field → fail
   - `test_dqdeleted_field_allowed_when_absent_from_yaml` — DqDeleted-marked field missing from YAML → pass
   - Use `tmp_path` and inline YAML / model fixtures; do NOT mutate real files.

10. **Run the V3 Verification Plan steps 1-15** in order (all `[pre-deploy]` — no `[post-deploy]` steps because active deploy is DEFERRED per Decision 67). Loop on failures.

11. **Bookkeeping (parallel with code-review):** Once the implementation is complete and passing all V2 steps, **start code-review in the background** AND in parallel apply the two bookkeeping edits:
    - **a.** Edit `docs/ROADMAP-PLATFORM.yaml`: under tier_item `T0.12`, change `status: not_started` to `status: complete` and add a sibling `completed_at: "YYYY-MM-DD"` field where YYYY-MM-DD is the implementation date.
    - **b.** Prepend a new entry to `docs/SESSION_LOG.md` summarising this T0.12 implementation (date, branch name, files added, exit criteria satisfied, follow-on work like T0.13 / T1.6 still pending). Match the format of recent entries.
    - These two edits should land in a single commit (`chore(t-0-12): bookkeeping — roadmap status + session log`) while code-review is running, to save wall-clock time. They are pure metadata, so a code-review pass at the same time is independently safe.

12. **Address any code-review findings** once review completes; loop until clean.

13. **Run Verification Plan steps 16-17** (bookkeeping verification) AFTER step 11 to confirm the metadata changes landed.

14. **DEFERRED:** `build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)`. Rationale: `src/schemas/` is Lambda-packaged via `scripts/build_lambda.py:70` (whole `src/` tree copied into `data-pipeline.zip`). No deployed Lambda handler imports the new modules in this phase, so the smoke-test surface is "the package still builds without error" — verified locally by `bin/venv-python -m scripts.build_lambda --no-deploy` if needed, but active deploy and end-to-end smoke-test are explicitly deferred per the CLAUDE.md Temporary Operational Constraint. When Decision 67 is reversed, the deploy + smoke-test become live for any subsequent plan that touches Lambda-packaged code; this DEFERRED line is the breadcrumb for that follow-on.

15. **Final report:** what was implemented (list of files), V3 verification results (with the DEFERRED step explicitly noted as deferred-not-skipped), code-review verdict, and any follow-on recs filed (e.g. the stale `telemetry_agent_invocations_current` view surfaced in preflight).

## Work Areas
Not applicable — IMPLEMENTATION plan, not STRATEGIC.
