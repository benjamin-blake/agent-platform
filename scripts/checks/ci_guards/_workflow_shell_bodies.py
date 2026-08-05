"""R3's `.github/workflows/` leg (audit finding SGE-03; Decision 162's ratchet, widened surface).

Decision 162 installed R3 -- the ratcheted inline `shell: bash`/`sh` body ceiling -- but its
implementation walked `.github/actions/` manifests only, leaving every inline `run:` body in
`.github/workflows/` ungoverned at exactly the unit that produced rec-2923. This module holds the
whole workflow leg: the walk, the step-identity grammar, the baseline section allowlist, and the
ceiling/marker evaluation. R1 (thin-adapter output producers) and R2 (literal-argv test coverage)
stay composite-only and are never evaluated here -- R1 keys on a manifest's top-level
`outputs.<id>.value` block and R2 on a `.sh` delegate under the action directory, and neither
construct has a workflow analogue.

WHY IT IS A SEPARATE MODULE, and why `check_workflow_bodies` reads the baseline file itself rather
than accepting a parsed one from its caller: per-file line coverage is measured by running ONLY a
source file's mirror test, and validate_composite_action_shell_bodies.py's mirror sits at 490 of
its 500-effective-line ceiling. Keeping ALL of this leg's branching here -- so the guard-module
delta is two unconditional statements with no new conditional -- is what lets that mirror gain
nothing while every branch below is covered by this module's own mirror,
tests/checks/ci_guards/test__workflow_shell_bodies.py.

Key grammar is `"<workflow-rel-path>::<job-id>::<step-id | name-slug | positional-index>"`, which
deliberately diverges from composite R3's `"<action-rel-dir>::<step-id>"`: workflow jobs are long
(reconcile.yml's apply-reconcile job alone carries 26 steps) and most of their steps declare no
`id`, so a purely positional scheme would renumber every subsequent key in a job whenever an
unrelated step was inserted. Field semantics live in docs/contracts/composite-action-shape.yaml
and docs/contracts/marker-grammar.yaml (Decision 86/127 routing), never restated here.

Imports ROOT from scripts.checks._common and never recomputes it
(tests/test_checks_registry.py::TestNoLocalRootRecomputation enforces this repo-wide).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common, _marker_guard

_BASELINE_REL_PATH = "config/composite_action_body_baseline.yaml"
_BASELINE_SECTION = "r3_workflows"
_WORKFLOW_GLOBS = ("*.yml", "*.yaml")
_WORKFLOW_SURFACE = ".github/workflows"

# Frozen allowlist of the baseline file's top-level sections. Admitting a fourth grandfather
# roster into that file requires editing THIS constant in a reviewed code change -- never a
# config drop-in. Same frozen-constant-in-source shape as the guard's own _R1_KNOWN_VIOLATORS
# (Decision 162) and _marker_guard.RETRO_SCAN_GRANDFATHER (Decision 165). Scope is exactly this
# one file: it cannot bar a roster minted somewhere else, only one smuggled in here.
_KNOWN_BASELINE_SECTIONS = frozenset({"r1", "r3", _BASELINE_SECTION})

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _effective_lines(body: str) -> list[str]:
    """Non-blank, non-comment lines -- the identical counting rule the composite R3 leg uses."""
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]


def _name_slug(name: str) -> str:
    """Lowercase the step name and collapse every run of non-alphanumerics to a single hyphen.

    Total by construction over any string, and YAML-safe: quotes, colons, braces and `#` are all
    non-alphanumeric, so none survives into a baseline key.
    """
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def _default_shell(node: dict[str, Any]) -> str | None:
    """`defaults.run.shell` declared at workflow or job level, when it is a string."""
    defaults = node.get("defaults")
    run = defaults.get("run") if isinstance(defaults, dict) else None
    shell = run.get("shell") if isinstance(run, dict) else None
    return shell if isinstance(shell, str) else None


def _is_governed_shell(shell: Any) -> bool:
    """An absent shell is governed (GitHub's default for a `run:` step is bash); otherwise the
    first token of the declared shell must be bash or sh, matching the composite leg's scope."""
    if not isinstance(shell, str):
        return shell is None
    tokens = shell.split()
    return bool(tokens) and tokens[0] in ("bash", "sh")


def _step_identity(step: dict[str, Any], index: int) -> str:
    """A step's own `id`, else a slug of its `name`, else its positional index within the job's
    FULL steps list (not its index among run-bearing steps -- an index counted over a filtered
    subset would shift whenever an unrelated `uses:` step was inserted)."""
    step_id = step.get("id")
    if isinstance(step_id, str) and step_id:
        return step_id
    name = step.get("name")
    slug = _name_slug(name) if isinstance(name, str) else ""
    return slug or f"#{index}"


def _iter_workflows() -> list[Path]:
    workflows_dir = _common.ROOT / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(p for pattern in _WORKFLOW_GLOBS for p in workflows_dir.glob(pattern))


def scan_workflow_bodies() -> dict[str, int]:
    """{"<workflow-rel-path>::<job-id>::<step-identity>": effective_line_count} for every inline
    `run:` body in `.github/workflows/` whose effective shell is absent or bash/sh.

    Identity collisions inside one job (two id-less steps sharing a name) are disambiguated with a
    deterministic `~N` suffix in step order -- without it the two bodies would collide on one key
    and the smaller one's ceiling would silently govern the larger.
    """
    bodies: dict[str, int] = {}
    for path in _iter_workflows():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rel_path = str(path.relative_to(_common.ROOT)).replace("\\", "/")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict):
            continue
        workflow_shell = _default_shell(data)
        for job_id, job in jobs.items():
            steps = job.get("steps") if isinstance(job, dict) else None
            if not isinstance(steps, list):
                continue
            job_shell = _default_shell(job) or workflow_shell
            seen: dict[str, int] = {}
            for index, step in enumerate(steps):
                run_body = step.get("run") if isinstance(step, dict) else None
                if not isinstance(run_body, str):
                    continue
                if not _is_governed_shell(step.get("shell", job_shell)):
                    continue
                identity = _step_identity(step, index)
                occurrence = seen.get(identity, 0) + 1
                seen[identity] = occurrence
                identity = identity if occurrence == 1 else f"{identity}~{occurrence}"
                bodies[f"{rel_path}::{job_id}::{identity}"] = len(_effective_lines(run_body))
    return bodies


def workflow_mention_candidates(key: str) -> list[str]:
    """Workflow R3 keys are not file paths, so the shared module's path-ancestor expansion needs an
    explicit seed: the full key plus the workflow file path (the text before the first `::`). The
    >=2-segment ancestor rule is then applied to each, so a Decision naming
    `.github/workflows/reconcile.yml` authorizes an entry while one naming only `.github` does not.
    """
    return [key, key.split("::", 1)[0]]


_R3_WORKFLOWS_SPEC = _marker_guard.RegistrySpec(
    rel_path=_BASELINE_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_section_extractor(
        _BASELINE_SECTION, token="raise-approved", value_type=int, require_reason=True
    ),
    gates_new_entry=lambda _value: True,
    label="composite-action shell-body rules (Decision 162)",
    mention_candidates=workflow_mention_candidates,
    reason_required=True,
)


def check_workflow_bodies(decision_bodies: dict[int, str]) -> list[str]:
    """Violation strings for the workflow leg of R3 -- empty when clean.

    Every string is prefixed `R3-workflow:` and names the `.github/workflows` surface, so a
    workflow violation is never read as a composite-action one in CI failure text (Decision 104),
    even though the enclosing registered check name and its `failed.append` label are unchanged.
    """
    baseline_path = _common.ROOT / _BASELINE_REL_PATH
    raw_text = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
    parsed = yaml.safe_load(raw_text) or {}
    baseline = parsed if isinstance(parsed, dict) else {}
    section = baseline.get(_BASELINE_SECTION)
    declared = section if isinstance(section, dict) else {}
    markers = _R3_WORKFLOWS_SPEC.extractor(raw_text)

    violations: list[str] = []

    unknown_sections = sorted(set(baseline) - _KNOWN_BASELINE_SECTIONS)
    if unknown_sections:
        violations.append(
            f"R3-workflow: {_BASELINE_REL_PATH} carries unrecognised top-level section(s) "
            f"{unknown_sections}. The sections of the file governing {_WORKFLOW_SURFACE}/ bodies are a "
            f"frozen allowlist ({sorted(_KNOWN_BASELINE_SECTIONS)}) held in this guard's own "
            "_KNOWN_BASELINE_SECTIONS constant -- admitting a fourth grandfather roster here requires "
            "editing that constant in a reviewed code change, never a config drop-in."
        )

    for key, line_count in sorted(scan_workflow_bodies().items()):
        entry = declared.get(key)
        if entry is None:
            violations.append(
                f"R3-workflow: {key} ({line_count} lines) is an inline `run:` body under "
                f"{_WORKFLOW_SURFACE}/ with no {_BASELINE_REL_PATH} {_BASELINE_SECTION} entry -- register "
                "it (with a `# raise-approved: dec-NNN <reason>` marker if intentionally large), or "
                "extract it into a script under scripts/ci/ (Decision 162 R3; audit finding SGE-03)."
            )
            continue
        marker_entry = markers.get(key)
        marker = marker_entry.marker if marker_entry is not None else None
        if marker is not None:
            if _marker_guard.authorization_failure(
                marker, key, decision_bodies, mention_candidates=workflow_mention_candidates
            ):
                violations.append(
                    f"R3-workflow: {key}'s raise-approved marker cites {marker}, but its body does not "
                    f"authorize this {_WORKFLOW_SURFACE}/ entry (mention `{key}` or "
                    f"`{key.split('::', 1)[0]}`)."
                )
            continue
        if line_count > int(entry):
            violations.append(
                f"R3-workflow: {key} GREW to {line_count} lines (baseline ceiling {int(entry)}) with no "
                f"`# raise-approved: dec-NNN <reason>` marker on its {_BASELINE_SECTION} entry -- extract it "
                f"into a script under scripts/ci/, or bump the ceiling with a marker citing a real Decision "
                f"that names this {_WORKFLOW_SURFACE}/ entry (Decision 162/128/165)."
            )

    return violations
