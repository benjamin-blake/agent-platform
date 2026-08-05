"""Tests for the R3 workflow-body leg (audit finding SGE-03; Decision 162's ratchet, widened).

This file is _workflow_shell_bodies.py's mirror, and per-file coverage is measured by running ONLY
the mirror -- so every branch of that module must be driven from here, never from the incumbent
composite mirror (which must gain nothing; see the plan's straight-line constraint).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks import _marker_guard
from scripts.checks.ci_guards import _workflow_shell_bodies as wsb

_MODULE = "scripts.checks.ci_guards._workflow_shell_bodies"
_BASELINE_REL = "config/composite_action_body_baseline.yaml"

_TWO_LINE_BODY = "        run: |\n          echo one\n          echo two\n"


def _write_workflow(tmp_path: Path, name: str, text: str) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(text, encoding="utf-8")


def _write_baseline(tmp_path: Path, text: str) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / _BASELINE_REL).write_text(text, encoding="utf-8")


def _write_decisions(tmp_path: Path, text: str) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "DECISIONS.md").write_text(text, encoding="utf-8")


def _simple_workflow(name: str = "Do thing", body: str = _TWO_LINE_BODY) -> str:
    return "name: w\non: push\njobs:\n  job:\n    steps:\n" + f"      - name: {name}\n" + body


def _check(tmp_path: Path) -> list[str]:
    with patch(f"{_MODULE}._common.ROOT", tmp_path):
        return wsb.check_workflow_bodies(_marker_guard.load_decision_bodies())


def _scan(tmp_path: Path) -> dict[str, int]:
    with patch(f"{_MODULE}._common.ROOT", tmp_path):
        return wsb.scan_workflow_bodies()


class TestWorkflowBodyRatchet:
    """SGE-03's acceptance clause turned executable, plus the boundary and authorization cases
    that separate a real ratchet from an inert one."""

    def test_unregistered_workflow_body_fails(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_baseline(tmp_path, "r1: {}\nr3: {}\nr3_workflows: {}\n")
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert ".github/workflows/w.yml::job::do-thing" in violations[0]
        assert "no config/composite_action_body_baseline.yaml r3_workflows entry" in violations[0]

    def test_missing_baseline_file_still_fails_an_unregistered_body(self, tmp_path: Path) -> None:
        """The baseline file's absence is not an escape hatch -- the roster is simply empty."""
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        violations = _check(tmp_path)
        assert len(violations) == 1, violations

    def test_body_over_declared_ceiling_fails(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_baseline(tmp_path, 'r3_workflows:\n  ".github/workflows/w.yml::job::do-thing": 1\n')
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert "GREW to 2 lines (baseline ceiling 1)" in violations[0]

    def test_body_at_exactly_the_ceiling_passes(self, tmp_path: Path) -> None:
        """The comparison is strict `>`, matching the incumbent R3 leg -- a `>=` comparison would
        red every one of the 128 seeded entries on day one."""
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_baseline(tmp_path, 'r3_workflows:\n  ".github/workflows/w.yml::job::do-thing": 2\n')
        assert _check(tmp_path) == []

    def test_valid_marker_exempts_entry_from_ceiling(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_decisions(tmp_path, "## Decision 900: Test\n\nThis authorizes .github/workflows/w.yml explicitly.\n")
        _write_baseline(
            tmp_path,
            'r3_workflows:\n  ".github/workflows/w.yml::job::do-thing": 1  # raise-approved: dec-900 kept whole\n',
        )
        assert _check(tmp_path) == []

    def test_marker_citing_unauthorizing_decision_fails(self, tmp_path: Path) -> None:
        """A Decision naming only `.github` never authorizes -- the shared module's >=2-segment
        ancestor floor is what keeps a root mention from becoming a skeleton key."""
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_decisions(tmp_path, "## Decision 900: Test\n\nThis names .github and nothing deeper.\n")
        _write_baseline(
            tmp_path,
            'r3_workflows:\n  ".github/workflows/w.yml::job::do-thing": 1  # raise-approved: dec-900 kept whole\n',
        )
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert "does not authorize" in violations[0]

    def test_marker_with_no_reason_is_not_a_marker(self, tmp_path: Path) -> None:
        """require_reason=True, matching the incumbent leg: a reasonless marker parses as NO
        marker, so it can never rescue an entry from its ceiling."""
        _write_workflow(tmp_path, "w.yml", _simple_workflow())
        _write_decisions(tmp_path, "## Decision 900: Test\n\nAuthorizes .github/workflows/w.yml.\n")
        _write_baseline(
            tmp_path,
            'r3_workflows:\n  ".github/workflows/w.yml::job::do-thing": 1  # raise-approved: dec-900\n',
        )
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert "GREW" in violations[0]

    def test_non_bash_shell_body_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(
            tmp_path,
            "w.yml",
            "name: w\non: push\njobs:\n  job:\n    steps:\n      - name: Pwsh step\n        shell: pwsh\n" + _TWO_LINE_BODY,
        )
        assert _scan(tmp_path) == {}
        assert _check(tmp_path) == []

    def test_yaml_spelled_workflow_is_scanned(self, tmp_path: Path) -> None:
        """The dual glob is prophylactic -- no .yaml workflow exists today, and the guard must not
        acquire a blind spot the first time one is added."""
        _write_workflow(tmp_path, "w.yaml", _simple_workflow())
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert ".github/workflows/w.yaml::job::do-thing" in violations[0]

    def test_unknown_baseline_section_fails(self, tmp_path: Path) -> None:
        """ENFORCED, not asserted in prose: a fourth grandfather roster cannot enter this file by
        config edit -- only by editing _KNOWN_BASELINE_SECTIONS in a reviewed code change."""
        _write_baseline(tmp_path, "r1: {}\nbogus: {}\nr3: {}\nr3_workflows: {}\n")
        violations = _check(tmp_path)
        assert len(violations) == 1, violations
        assert "unrecognised top-level section(s) ['bogus']" in violations[0]

    def test_known_sections_are_exactly_the_three_governed_rosters(self) -> None:
        assert wsb._KNOWN_BASELINE_SECTIONS == frozenset({"r1", "r3", "r3_workflows"})

    def test_every_workflow_violation_names_the_workflow_surface(self, tmp_path: Path) -> None:
        """Decision 104: one registered check name now enforces two surfaces, so every workflow
        violation must be self-identifying in CI failure text."""
        _write_workflow(tmp_path, "unregistered.yml", _simple_workflow())
        _write_workflow(tmp_path, "grown.yml", _simple_workflow())
        _write_workflow(tmp_path, "marked.yml", _simple_workflow())
        _write_decisions(tmp_path, "## Decision 900: Test\n\nNames .github and nothing deeper.\n")
        _write_baseline(
            tmp_path,
            "bogus: {}\n"
            "r3_workflows:\n"
            '  ".github/workflows/grown.yml::job::do-thing": 1\n'
            '  ".github/workflows/marked.yml::job::do-thing": 1  # raise-approved: dec-900 kept whole\n',
        )
        violations = _check(tmp_path)
        assert len(violations) == 4, violations
        for violation in violations:
            assert violation.startswith("R3-workflow:"), violation
            assert ".github/workflows" in violation, violation

    def test_mention_candidates_returns_full_key_and_workflow_path(self) -> None:
        key = ".github/workflows/reconcile.yml::apply-reconcile::plan"
        assert wsb.workflow_mention_candidates(key) == [key, ".github/workflows/reconcile.yml"]

    def test_spec_binds_the_shared_marker_guard(self) -> None:
        """No sixth copy of the marker mechanism is minted (Decision 165) -- this leg is a second
        RegistrySpec over the shared module, not a reimplementation."""
        assert wsb._R3_WORKFLOWS_SPEC.token == "raise-approved"
        assert wsb._R3_WORKFLOWS_SPEC.gated_direction == "up"
        assert wsb._R3_WORKFLOWS_SPEC.reason_required is True
        assert wsb._R3_WORKFLOWS_SPEC.rel_path == _BASELINE_REL
        assert wsb._R3_WORKFLOWS_SPEC.mention_candidates is wsb.workflow_mention_candidates
        assert wsb._R3_WORKFLOWS_SPEC.gates_new_entry(1) is True

    def test_missing_workflows_directory_yields_no_bodies(self, tmp_path: Path) -> None:
        assert _scan(tmp_path) == {}
        assert _check(tmp_path) == []

    def test_degenerate_workflow_shapes_are_skipped_without_aborting_the_walk(self, tmp_path: Path) -> None:
        """Every non-conforming shape is skipped individually; one malformed file must not blind
        the walk to the rest of the directory."""
        _write_workflow(tmp_path, "a-broken.yml", "name: [unclosed\n")
        _write_workflow(tmp_path, "b-scalar.yml", "just-a-string\n")
        _write_workflow(tmp_path, "c-nojobs.yml", "name: w\non: push\n")
        _write_workflow(tmp_path, "d-jobnotdict.yml", "name: w\non: push\njobs:\n  job: not-a-mapping\n")
        _write_workflow(tmp_path, "e-nosteps.yml", "name: w\non: push\njobs:\n  job:\n    uses: ./x.yml\n")
        _write_workflow(
            tmp_path,
            "f-stepshapes.yml",
            "name: w\non: push\njobs:\n  job:\n    steps:\n      - a-bare-string\n      - uses: actions/checkout@v4\n",
        )
        _write_workflow(tmp_path, "g-real.yml", _simple_workflow())
        assert _scan(tmp_path) == {".github/workflows/g-real.yml::job::do-thing": 2}

    def test_default_run_shell_is_honoured_at_workflow_and_job_level(self, tmp_path: Path) -> None:
        """A workflow- or job-level `defaults.run.shell` decides governance for steps that declare
        none; a job-level declaration wins over the workflow-level one."""
        _write_workflow(
            tmp_path,
            "a-wf-default.yml",
            "name: w\non: push\ndefaults:\n  run:\n    shell: pwsh\njobs:\n"
            "  inherits:\n    steps:\n      - name: Skipped\n" + _TWO_LINE_BODY + "  overrides:\n"
            "    defaults:\n      run:\n        shell: bash\n    steps:\n      - name: Governed\n" + _TWO_LINE_BODY,
        )
        _write_workflow(
            tmp_path,
            "b-empty-defaults.yml",
            "name: w\non: push\ndefaults: {}\njobs:\n  job:\n    defaults:\n      run: {}\n"
            "    steps:\n      - name: Governed\n" + _TWO_LINE_BODY,
        )
        assert _scan(tmp_path) == {
            ".github/workflows/a-wf-default.yml::overrides::governed": 2,
            ".github/workflows/b-empty-defaults.yml::job::governed": 2,
        }


class TestWorkflowStepIdentity:
    """The step-identity grammar must be TOTAL and deterministic: a key function that is not total
    drops a body from governance by dict-overwrite rather than failing loudly."""

    def test_step_id_wins_over_name(self, tmp_path: Path) -> None:
        _write_workflow(
            tmp_path,
            "w.yml",
            "name: w\non: push\njobs:\n  job:\n    steps:\n      - id: plan\n        name: Do thing\n" + _TWO_LINE_BODY,
        )
        assert list(_scan(tmp_path)) == [".github/workflows/w.yml::job::plan"]

    def test_name_only_step_uses_slug(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "w.yml", _simple_workflow(name="Do THING now"))
        assert list(_scan(tmp_path)) == [".github/workflows/w.yml::job::do-thing-now"]

    def test_step_with_neither_id_nor_name_uses_positional_index(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "w.yml", "name: w\non: push\njobs:\n  job:\n    steps:\n      -\n" + _TWO_LINE_BODY)
        assert list(_scan(tmp_path)) == [".github/workflows/w.yml::job::#0"]

    def test_positional_index_counts_all_steps_not_only_run_steps(self, tmp_path: Path) -> None:
        """Counting over run-bearing steps alone would shift the fallback key whenever an unrelated
        `uses:` step was inserted, reding bodies nobody touched."""
        _write_workflow(
            tmp_path,
            "w.yml",
            "name: w\non: push\njobs:\n  job:\n    steps:\n      - uses: actions/checkout@v4\n      -\n" + _TWO_LINE_BODY,
        )
        assert list(_scan(tmp_path)) == [".github/workflows/w.yml::job::#1"]

    def test_duplicate_name_in_one_job_is_disambiguated(self, tmp_path: Path) -> None:
        """Without the tilde suffix the two bodies collide on one key and the smaller body's
        ceiling silently governs the larger one."""
        step = "      - name: Do thing\n" + _TWO_LINE_BODY
        _write_workflow(tmp_path, "w.yml", "name: w\non: push\njobs:\n  job:\n    steps:\n" + step * 3)
        assert list(_scan(tmp_path)) == [
            ".github/workflows/w.yml::job::do-thing",
            ".github/workflows/w.yml::job::do-thing~2",
            ".github/workflows/w.yml::job::do-thing~3",
        ]

    def test_slug_contains_no_yaml_unsafe_characters(self, tmp_path: Path) -> None:
        """A step name carrying quotes, a colon or a `#` must not break the baseline entry regex."""
        _write_workflow(
            tmp_path,
            "w.yml",
            "name: w\non: push\njobs:\n  job:\n    steps:\n      - name: 'Verify \"x\": {a} #1 & [b] | c!'\n" + _TWO_LINE_BODY,
        )
        keys = list(_scan(tmp_path))
        assert keys == [".github/workflows/w.yml::job::verify-x-a-1-b-c"]
        identity = keys[0].split("::", 2)[2]
        assert re.fullmatch(r"[a-z0-9-]+", identity), identity


class TestWorkflowRatchetLiveSurface:
    """The anti-vacuity anchor, run against the REAL tree with no mocking."""

    def test_live_scan_is_non_trivially_populated(self) -> None:
        """Asserted as a FLOOR, never an equality pin: an equality pin would red the build every
        time a body is extracted to scripts/ci/, penalising the declared relief valve."""
        scan = wsb.scan_workflow_bodies()
        assert len(scan) >= 20, len(scan)
        assert len({key.split("::")[0] for key in scan}) >= 5

    def test_every_live_workflow_body_is_registered(self) -> None:
        missing = sorted(set(wsb.scan_workflow_bodies()) - set(_live_roster()))
        assert missing == [], missing

    def test_every_roster_key_names_an_existing_workflow_file(self) -> None:
        dangling = []
        for key in _live_roster():
            rel = key.split("::", 1)[0]
            if not rel.startswith(".github/workflows/") or not (wsb._common.ROOT / rel).is_file():
                dangling.append(key)
        assert dangling == [], dangling

    def test_seeded_ceiling_equals_measured(self) -> None:
        """EQUALITY, deliberately two-sided and therefore stricter than R3 itself. Seeded BELOW
        measured means the installing PR is red against its own rule; seeded ABOVE means a padded
        ceiling granting silent growth headroom, which would leave the ratchet with no bite on day
        one and is the one thing no other step in this plan can detect. ACCEPTED CONSEQUENCE: a
        body that SHRINKS -- including one extracted to scripts/ci/ -- reds this test until its
        roster entry is lowered in the same PR. That red is intended, not a defect; lowering a
        ceiling needs no marker.
        """
        measured = wsb.scan_workflow_bodies()
        roster = _live_roster()
        mismatched = {key: (declared, measured[key]) for key, declared in roster.items() if measured.get(key) != declared}
        assert mismatched == {}, mismatched


def _live_roster() -> dict[str, int]:
    baseline = yaml.safe_load((wsb._common.ROOT / _BASELINE_REL).read_text(encoding="utf-8"))
    return dict(baseline["r3_workflows"])
