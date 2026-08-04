from __future__ import annotations

import re

from scripts.checks import _common, registry

_H1_RE = re.compile(r"(?m)^#\s+\S")
_SECTION_RE = re.compile(r"(?m)^##\s+\S")
_REF_RE = re.compile(r"\[.*?\]\((\.\.?/[^)# \s]+)\)")

# Decision 43's `.prompt.md` row: a 3,000 RAW-line ceiling, strict `>` (3,000 itself is
# compliant). Counted with len(content.splitlines()), matching Decision 114's
# _ROADMAP_MAX_LINES precedent verbatim in shape. No waiver is implemented for this ceiling
# (Decision 163 clause 1) -- do not "restore" one.
_MAX_PROMPT_LINES = 3000

# Both governed .prompt.md surfaces (Decision 43). Size-governed alike; the structure
# contract below (H1 / '## ' section / dead relative reference) stays scoped to the
# scheduled directory only -- Layer-5 executor prompts are NOT structure-checked.
_SIZE_GOVERNED_PROMPT_DIRS: tuple[tuple[str, ...], ...] = (
    (".github", "prompts", "scheduled"),
    ("config", "agent", "executor", "prompts"),
)


@registry.register("validate_prompt_files", owner="platform")
def validate_prompt_files(failed: list[str]) -> None:
    """Validate the live .prompt.md surfaces.

    Two independent contracts, deliberately NOT unioned across both governed directories:

    Size (Decision 43, SGE-06): every `*.prompt.md` under EVERY entry of
    _SIZE_GOVERNED_PROMPT_DIRS must be at or under _MAX_PROMPT_LINES raw lines, and every
    governed directory must contain at least one `*.prompt.md` file (an empty governed
    directory fails loudly rather than passing vacuously). No waiver is implemented for this
    ceiling (Decision 163 clause 1).

    Structure (VTS-08): H1 title + >=1 '## ' section + no dead relative references --
    scoped to .github/prompts/scheduled/ ONLY. Layer-5 executor prompts under
    config/agent/executor/prompts/ are size-governed but NOT structure-governed; no YAML
    frontmatter / name / description / inline model / '## Intent' assertions either way --
    model/provider validity is owned by docs/contracts/inference-provider.yaml +
    scripts/run_scheduled_agent.py, not a second hand-maintained allowlist here (dec-86).
    """
    print("\n=== Prompt file validation ===")
    errors: list[str] = []

    for dir_parts in _SIZE_GOVERNED_PROMPT_DIRS:
        prompts_dir = _common.ROOT.joinpath(*dir_parts)
        dir_files = list(prompts_dir.glob("*.prompt.md"))
        if not dir_files:
            errors.append(f"no *.prompt.md files found under {prompts_dir}")
        for f in dir_files:
            content = f.read_text(encoding="utf-8")
            line_count = len(content.splitlines())
            if line_count > _MAX_PROMPT_LINES:
                rel_path = f.relative_to(_common.ROOT)
                errors.append(f"{rel_path} : {line_count} raw lines exceeds the {_MAX_PROMPT_LINES}-line limit (Decision 43)")

    structure_dir = _common.ROOT / ".github" / "prompts" / "scheduled"
    for f in structure_dir.glob("*.prompt.md"):
        content = f.read_text(encoding="utf-8")
        name = f.name

        if not _H1_RE.search(content):
            errors.append(f"{name} : missing H1 title line")
        if not _SECTION_RE.search(content):
            errors.append(f"{name} : missing at least one '## ' section")

        for ref_match in _REF_RE.finditer(content):
            ref_path = ref_match.group(1)
            resolved = (f.parent / ref_path).resolve()
            if not resolved.exists():
                errors.append(f"{name} : dead reference '{ref_path}'")

    if errors:
        print("Prompt validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Prompt file validation")
    else:
        print("All governed prompt files passed validation.")
