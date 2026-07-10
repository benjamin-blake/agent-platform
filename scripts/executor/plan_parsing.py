"""Plan-text parsing and step scope validation for the executor.

Pure-logic helpers extracted from scripts.executor.plan: turning raw LLM
plan text into structured step dicts, and filtering those steps to the
recommendation's declared file scope. No routed-name references -- these
functions depend only on stdlib.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step parsing
# ---------------------------------------------------------------------------


def parse_steps_from_plan(plan_text: str) -> list[dict]:
    """Parse structured steps from plan text.

    Expected format:
    ### Step N: [title]
    **File**: path/to/file.py
    **Action**: create|modify|delete
    **Description**: ...
    **Acceptance**: ...
    """
    steps = []
    step_pattern = r"###\s*Step\s*(\d+):\s*(.+?)(?=###\s*Step|\Z)"
    matches = re.findall(step_pattern, plan_text, re.DOTALL | re.IGNORECASE)

    for step_num, step_content in matches:
        step: dict = {
            "n": int(step_num),
            "title": "",
            "file": "",
            "action": "",
            "description": "",
            "acceptance": "",
        }

        lines = step_content.strip().split("\n")
        if lines:
            step["title"] = lines[0].strip()

        file_match = re.search(r"\*\*File\*\*:\s*(.+)", step_content)
        if file_match:
            file_value = file_match.group(1).strip().strip("`")
            # Guard against malformed markdown artifacts in file field
            if file_value.startswith("**") or "**" in file_value:
                logger.warning(
                    f"Step {step['n']}: Rejecting malformed file value '{file_value}' (contains markdown bold markers)"
                )
                step["file"] = ""
            else:
                step["file"] = file_value

        action_match = re.search(r"\*\*Action\*\*:\s*(\w+)", step_content)
        if action_match:
            step["action"] = action_match.group(1).strip().lower()

        desc_match = re.search(r"\*\*Description\*\*:\s*(.+?)(?=\*\*|$)", step_content, re.DOTALL)
        if desc_match:
            step["description"] = desc_match.group(1).strip()

        acceptance_match = re.search(r"\*\*Acceptance\*\*:\s*(.+?)(?=\*\*|\n###|\n---|\Z)", step_content, re.DOTALL)
        if acceptance_match:
            step["acceptance"] = acceptance_match.group(1).strip()

        steps.append(step)

    # Deduplicate by step number: prefer the occurrence with both file and
    # acceptance populated (LLMs sometimes emit duplicate ### Step N:
    # blocks when the plan is long or context wraps).
    seen: dict[int, dict] = {}
    for s in steps:
        if s["n"] not in seen:
            seen[s["n"]] = s
        else:
            existing = seen[s["n"]]
            # Prefer the step that has both file and acceptance populated
            existing_complete = existing.get("file") and existing.get("acceptance")
            current_complete = s.get("file") and s.get("acceptance")
            if current_complete and not existing_complete:
                seen[s["n"]] = s
    steps = list(seen.values())

    # Fallback: numbered list
    if not steps:
        numbered_pattern = r"^\s*(\d+)\.\s+(.+)$"
        for match in re.finditer(numbered_pattern, plan_text, re.MULTILINE):
            steps.append(
                {
                    "n": int(match.group(1)),
                    "title": match.group(2).strip(),
                    "file": "",
                    "action": "modify",
                    "description": match.group(2).strip(),
                    "acceptance": "",
                }
            )

    return sorted(steps, key=lambda s: s["n"])


# ---------------------------------------------------------------------------
# Step scope validation
# ---------------------------------------------------------------------------


def _compute_step_scope(rec: dict) -> set[str]:
    """Derive the set of file paths a plan step may legitimately target.

    When ``rec["file"]`` is empty or missing the returned set is empty,
    which signals *no filtering* (all step files are allowed).

    When a target file is present the scope includes:
    1. The target file itself.
    2. The conventional test file for the target
       (``scripts/executor/foo.py`` -> ``tests/test_executor_foo.py``,
        ``scripts/bar.py``          -> ``tests/test_bar.py``).
    """
    target = (rec.get("file") or "").strip()
    if not target:
        return set()

    scope: set[str] = {target}

    target_path = Path(target)
    stem = target_path.stem
    parts = target_path.parts

    if len(parts) >= 3 and parts[0] == "scripts" and parts[1] == "executor":
        test_name = f"tests/test_executor_{stem}.py"
        scope.add(test_name)
    elif len(parts) >= 2 and parts[0] == "scripts":
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)
    elif len(parts) >= 2 and parts[0] == "src":
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)
    else:
        test_name = f"tests/test_{stem}.py"
        scope.add(test_name)

    return scope


def _validate_step_scope(
    steps: list[dict],
    rec: dict,
) -> list[dict]:
    """Filter parsed steps to those within the recommendation scope.

    If the recommendation has no target file (empty or missing ``file``
    key), all steps pass through unchanged -- preserving the existing
    behaviour for scope-free recommendations.

    When a target IS present, steps whose ``file`` field falls outside
    the computed scope are dropped with a warning log.  Steps that have
    an empty ``file`` field are always kept (they represent analysis or
    acceptance-only steps).
    """
    scope = _compute_step_scope(rec)
    if not scope:
        return steps

    kept: list[dict] = []
    for step in steps:
        step_file = (step.get("file") or "").strip()
        if not step_file:
            kept.append(step)
            continue
        if step_file in scope:
            kept.append(step)
        else:
            logger.warning(
                "[SCOPE] Step %d targets '%s' which is outside rec scope %s -- rejected",
                step.get("n", 0),
                step_file,
                sorted(scope),
            )

    return kept
