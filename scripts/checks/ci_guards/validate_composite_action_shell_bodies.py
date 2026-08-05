"""Composite-action shell-body authoring rules (rec-2923 preventive action; Decision 162).

rec-2923's root cause was a defect CLASS, not a one-off bug: CI-embedded shell whose control flow
can silently not run (inherited composite-step errexit aborting a body mid-assignment), leaving a
step output undefined for a downstream consumer to misread as a legitimate value. Three rules
close the class:

R1: any composite `shell: bash`/`sh` step body that PRODUCES a consumed `outputs.<id>.value`
    binding must be a THIN ADAPTER delegating to a `.sh` script under the action directory --
    inline logic in an output-producing body is exactly the rec-2923 shape (review.sh existed
    for precisely this reason: shellcheckable, and directly testable under the literal GitHub
    composite-step argv). No marker escape -- see the baseline file's `r1:` section.
R2: each such delegate script must be referenced by a test spawning it under the literal
    `bash --noprofile --norc -e -o pipefail` argv (the exact invocation GitHub uses for a
    composite `shell: bash` step body) -- a script never driven under that literal argv has never
    had its errexit-inheritance behaviour actually exercised.
R3 (ratchet): every OTHER inline bash/sh body (non-output-producing, or an output-producing body
    that already fails R1) is measured by effective (non-blank, non-comment) line count and
    checked against config/composite_action_body_baseline.yaml's `r3:` section. A live body that
    exceeds its baseline's declared ceiling fails UNLESS that baseline entry carries an inline
    `# raise-approved: dec-NNN <reason>` marker (Decision 128 grammar) naming a real
    `## Decision NNN:` header whose body actually authorizes the entry (Decision 165
    marker-guard consolidation upgraded this from existence to authorization) -- the escape is
    scoped to R3 only.

R3 SPANS TWO SURFACES (audit finding SGE-03). The rule above is applied to composite-action
manifests here, and -- with its own `r3_workflows:` baseline section and its own
"<workflow-rel-path>::<job-id>::<step-identity>" key grammar -- to every inline `run:` body in
`.github/workflows/` by scripts/checks/ci_guards/_workflow_shell_bodies.py, whose
check_workflow_bodies() this check calls. That is one rule gaining scope, not a second rule: no
second registered check name is minted, and the workflow leg's violation strings carry an
`R3-workflow:` prefix so a workflow finding is never read as a composite-action one (Decision 104).
R1 and R2 remain COMPOSITE-ONLY and are never evaluated against a workflow step -- R1 keys on a
manifest's top-level `outputs.<id>.value` block and R2 on a `.sh` delegate under the action
directory, and neither construct has a workflow analogue.

Filesystem-only, no network, no subprocess (Decision 153 fast-tier budget) -- unlike
validate_sloc_budget_raises.py's git-diff pattern, this guard never shells out; R3's marker
exempts an entry from its OWN declared ceiling entirely rather than diffing against origin/main.
R3's marker parsing and authorization check delegate to scripts.checks._marker_guard (shared
across all five raise-marker guards); R1's frozen no-marker-escape branch never touches that
shared path at all, and R2 is untouched.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import yaml

from scripts.checks import _common, _marker_guard, registry
from scripts.checks.ci_guards import _workflow_shell_bodies

_MANIFEST_GLOBS = ("action.yml", "action.yaml")
_BASELINE_REL_PATH = "config/composite_action_body_baseline.yaml"

_OUTPUT_VALUE_STEP_RE = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs\.")

# The delegate line, FULLY anchored. Two legal shapes and nothing else:
#   bash "${{ github.action_path }}/body.sh"
#   if ! bash "$GITHUB_ACTION_PATH/body.sh"; then
# Anchoring is load-bearing. An unanchored `search` would accept a COMPOUND line
# (`rm -rf x; bash "$GITHUB_ACTION_PATH/x.sh"`) as a conformant thin adapter, letting arbitrary
# computation ride alongside the delegation -- the very thing R1 forbids.
_DELEGATE_LINE_RE = re.compile(
    r'^(?:if\s+!?\s*)?bash\s+"(?:\$\{\{\s*github\.action_path\s*\}\}|\$GITHUB_ACTION_PATH)/([\w.-]+\.sh)"'
    r"(?:\s*;\s*then)?$"
)

# Scaffolding a delegation wrapper legitimately needs -- BARE tokens only, never a wildcard.
# Deliberately does NOT admit `if\b.*`: a one-line `if OUT=$(...); then echo "k=$OUT" >>
# "$GITHUB_OUTPUT"; fi` matches that wildcard while computing and publishing a step output, which
# is exactly the rec-2923 shape R1 exists to reject. Every legitimate `if` in a thin adapter IS
# the delegate line itself (it contains the `bash "...sh"` call) and is matched by
# _DELEGATE_LINE_RE above, so no wildcard is needed here.
_CONTROL_FLOW_RE = re.compile(r"^(then|else|fi|exit(\s+\d+)?)$")
_GITHUB_COMPOSITE_ARGV_RE = re.compile(
    r'\(\s*"bash"\s*,\s*"--noprofile"\s*,\s*"--norc"\s*,\s*"-e"\s*,\s*"-o"\s*,\s*"pipefail"\s*\)'
)

# R1's frozen, strictly-shrinking known-violator set (rec-2923 class, pre-dating this guard).
# No marker, no config-file edit, and no future addition can grow this set -- growing it requires
# editing this constant in a reviewed code change, which is the point: R1 has NO runtime escape.
_R1_KNOWN_VIOLATORS = frozenset(
    {
        ".github/actions/deterministic-guard::guard",
        ".github/actions/fetch-saved-plan::resolve",
    }
)


def _r3_mention_candidates(key: str) -> list[str]:
    """R3 keys are "<action-rel-dir>::<step-id>", not file paths -- neither verbatim nor
    ancestor path-matching applies without this. Candidates are the full key and the
    action-relative directory; the shared module's >=2-segment ancestor rule is then applied
    to each (the directory is where a real match lives -- a Decision naming
    ".github/actions/materialise-tfvars" authorizes it, one naming only ".github/" does not).
    """
    action_rel_dir = key.split("::", 1)[0]
    return [key, action_rel_dir]


_R3_SPEC = _marker_guard.RegistrySpec(
    rel_path=_BASELINE_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_section_extractor("r3", token="raise-approved", value_type=int, require_reason=True),
    gates_new_entry=lambda _value: True,
    label="composite-action shell-body rules (Decision 162)",
    mention_candidates=_r3_mention_candidates,
    reason_required=True,
)


def _effective_lines(body: str) -> list[str]:
    """Non-blank, non-comment lines (mirrors scripts/checks/sloc/sloc_limits.py's SLOC counting)."""
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]


def _delegated_script(body: str) -> Optional[str]:
    """Return the delegated script's basename if `body` is a thin adapter, else None.

    A thin adapter's only substantive line is a FULLY-ANCHORED delegation to a `.sh` script under
    the action directory; any OTHER effective line (besides the bare `then`/`else`/`fi`/`exit`
    scaffolding an `if ! bash "...sh"; then exit 1; fi` wrapper needs) means the body also
    computes, and a computing output-producing body is the rec-2923 defect class itself.
    """
    lines = _effective_lines(body)
    delegate_line = None
    script = None
    for line in lines:
        match = _DELEGATE_LINE_RE.match(line)
        if match:
            delegate_line = line
            script = match.group(1)
            break
    if script is None:
        return None
    for line in lines:
        if line == delegate_line:
            continue
        if _CONTROL_FLOW_RE.match(line):
            continue
        return None
    return script


def _iter_manifests() -> list[Any]:
    actions_dir = _common.ROOT / ".github" / "actions"
    if not actions_dir.is_dir():
        return []
    return sorted(p for pattern in _MANIFEST_GLOBS for p in actions_dir.rglob(pattern))


def _output_producing_step_ids(data: dict[str, Any]) -> set[str]:
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return set()
    ids: set[str] = set()
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        value = output.get("value")
        if isinstance(value, str):
            ids.update(_OUTPUT_VALUE_STEP_RE.findall(value))
    return ids


def _inline_shell_steps(data: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (identity, run-body) for every composite step with shell: bash|sh and inline `run:`.

    identity is the step's own `id` when declared, else a positional `#<index>` fallback.
    """
    runs = data.get("runs")
    if not isinstance(runs, dict) or runs.get("using") != "composite":
        return []
    steps = runs.get("steps")
    if not isinstance(steps, list):
        return []
    result = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("shell") not in ("bash", "sh"):
            continue
        run_body = step.get("run")
        if not isinstance(run_body, str):
            continue
        result.append((str(step.get("id") or f"#{idx}"), run_body))
    return result


def scan_repository() -> dict[str, Any]:
    """Walk every composite action manifest and classify each inline bash/sh step body.

    Returns:
        r1_violations: {"<action-rel-dir>::<step-id>": effective_line_count} -- output-producing
            steps whose body is NOT a thin adapter.
        r1_conformant_scripts: {"<action-rel-dir>::<step-id>": "<script.sh>"} -- output-producing
            steps that ARE thin adapters, keyed to the delegate script R2 must cover.
        r3_bodies: {"<action-rel-dir>::<step-id>": effective_line_count} -- every other inline
            bash/sh body (a non-output-producing thin adapter is excluded entirely -- it is
            already the conformant shape and carries no ratchet risk).
    """
    r1_violations: dict[str, int] = {}
    r1_conformant_scripts: dict[str, str] = {}
    r3_bodies: dict[str, int] = {}

    for manifest_path in _iter_manifests():
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        action_rel_dir = str(manifest_path.parent.relative_to(_common.ROOT)).replace("\\", "/")
        output_ids = _output_producing_step_ids(data)

        for identity, body in _inline_shell_steps(data):
            key = f"{action_rel_dir}::{identity}"
            script = _delegated_script(body)
            if identity in output_ids:
                if script is None:
                    r1_violations[key] = len(_effective_lines(body))
                else:
                    r1_conformant_scripts[key] = script
                continue
            if script is not None:
                continue  # a non-output-producing thin adapter is already conformant; not ratcheted.
            r3_bodies[key] = len(_effective_lines(body))

    return {
        "r1_violations": r1_violations,
        "r1_conformant_scripts": r1_conformant_scripts,
        "r3_bodies": r3_bodies,
    }


def _load_baseline() -> dict[str, dict[str, Any]]:
    path = _common.ROOT / _BASELINE_REL_PATH
    if not path.exists():
        return {"r1": {}, "r3": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"r1": dict(data.get("r1") or {}), "r3": dict(data.get("r3") or {})}


def _r2_test_covers(script_name: str) -> bool:
    """A test file references `script_name` AND drives something under the literal GitHub argv."""
    tests_dir = _common.ROOT / "tests"
    if not tests_dir.is_dir():
        return False
    for path in tests_dir.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if script_name in text and _GITHUB_COMPOSITE_ARGV_RE.search(text):
            return True
    return False


@registry.register("validate_composite_action_shell_bodies", owner="platform")
def validate_composite_action_shell_bodies(failed: list[str]) -> None:
    """Enforce R1 (thin-adapter output producers), R2 (literal-argv test coverage), and R3
    (ratcheted inline-body line-count baseline) across every .github/actions/**/action.yml.
    """
    print(f"\n=== {_R3_SPEC.label} ===")
    scan = scan_repository()
    baseline = _load_baseline()

    bodies = _marker_guard.load_decision_bodies()

    baseline_path = _common.ROOT / _BASELINE_REL_PATH
    raw_baseline_text = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
    r3_markers = _R3_SPEC.extractor(raw_baseline_text)

    violations: list[str] = []

    # --- R1: output-producing step bodies must be thin adapters; violators must be pinned. ---
    baseline_r1_keys = set(baseline["r1"])
    unrecognized_baseline_r1 = baseline_r1_keys - _R1_KNOWN_VIOLATORS
    if unrecognized_baseline_r1:
        violations.append(
            f"R1: {_BASELINE_REL_PATH}'s r1 section carries {sorted(unrecognized_baseline_r1)}, which is "
            f"NOT in the frozen known-violator set. The r1 section is strictly shrinking with NO marker "
            "escape (Decision 162) -- a third entry can only be added by editing this guard's own "
            "_R1_KNOWN_VIOLATORS constant in a reviewed code change, never by a config edit alone."
        )
    for key, line_count in sorted(scan["r1_violations"].items()):
        if key not in _R1_KNOWN_VIOLATORS:
            violations.append(
                f"R1: {key} ({line_count} lines) is a NEW composite `shell: bash` body producing a "
                "consumed outputs.<id>.value binding with inline logic -- must delegate to a thin "
                "`.sh` adapter under the action directory (Decision 162; this is the exact rec-2923 "
                "defect class). No marker can admit this."
            )
        elif key not in baseline_r1_keys:
            violations.append(
                f"R1: {key} is a known violator but is missing from {_BASELINE_REL_PATH}'s r1 section -- "
                "register it (or extract it and remove it from _R1_KNOWN_VIOLATORS in the same change)."
            )
        elif line_count > int(baseline["r1"][key]):
            # The r1 section is STRICTLY SHRINKING: a pinned violator may be extracted (and
            # removed) or reduced, never grown. Unlike r3 there is NO `# raise-approved:` escape --
            # these two bodies ARE the rec-2923 defect class, so growing one is never admissible.
            # Without this comparison the r1 line counts would be inert decoration that merely
            # LOOKS like a ceiling (acceptance criterion 5; Decision 162 point 1).
            violations.append(
                f"R1: {key} GREW to {line_count} lines (pinned at {baseline['r1'][key]}) -- the r1 section is "
                "strictly shrinking and has NO raise-approved escape. Extract this body into a thin `.sh` "
                "adapter rather than growing a known rec-2923-class violator (Decision 162)."
            )

    # --- R2: every R1-conformant thin adapter's delegate script needs literal-argv test coverage. ---
    for key, script in sorted(scan["r1_conformant_scripts"].items()):
        if not _r2_test_covers(script):
            violations.append(
                f"R2: {key} delegates to {script}, but no test under tests/**/*.py drives it under the "
                'literal ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail") argv GitHub uses for '
                "a composite `shell: bash` step body (Decision 162)."
            )

    # --- R3: ratcheted line-count ceiling on every other inline body. ---
    baseline_r3 = baseline["r3"]
    for key, line_count in sorted(scan["r3_bodies"].items()):
        entry = baseline_r3.get(key)
        if entry is None:
            violations.append(
                f"R3: {key} ({line_count} lines) has no {_BASELINE_REL_PATH} r3 entry -- register it "
                "(with a `# raise-approved: dec-NNN <reason>` marker if intentionally large), or extract "
                "it into a delegated script (Decision 162)."
            )
            continue
        declared = int(entry)
        marker_entry = r3_markers.get(key)
        marker = marker_entry.marker if marker_entry is not None else None
        if marker is not None:
            if _marker_guard.authorization_failure(marker, key, bodies, mention_candidates=_r3_mention_candidates):
                violations.append(
                    f"R3: {key}'s raise-approved marker cites {marker}, but its body does not authorize this "
                    f"entry (mention `{key.split('::')[0]}` or a >=2-segment ancestor of it)."
                )
            continue  # a valid marker exempts this entry from its declared ceiling entirely.
        if line_count > declared:
            violations.append(
                f"R3: {key} GREW to {line_count} lines (baseline ceiling {declared}) with no "
                "`# raise-approved: dec-NNN <reason>` marker on its baseline entry -- extract it, or bump "
                "the ceiling with a marker citing a real Decision (Decision 162/128)."
            )

    violations.extend(_workflow_shell_bodies.check_workflow_bodies(bodies))

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
            failed.append(f"composite-action shell-body rules: {v}")
    else:
        print("  PASS: no unbaselined R1/R2/R3 violations")
