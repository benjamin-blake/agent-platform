from __future__ import annotations

import re

from scripts.checks import _common, registry

_H1_RE = re.compile(r"(?m)^#\s+\S")
_SECTION_RE = re.compile(r"(?m)^##\s+\S")
_REF_RE = re.compile(r"\[.*?\]\((\.\.?/[^)# \s]+)\)")


@registry.register("validate_prompt_files", owner="platform")
def validate_prompt_files(failed: list[str]) -> None:
    """Validate the live .github/prompts/scheduled/ surface (VTS-08).

    Structural contract only (H1 title + >=1 '## ' section + no dead relative references) --
    no YAML frontmatter / name / description / inline model / '## Intent' assertions: the
    scheduled-prompt format carries none of those, and model/provider validity is owned by
    docs/contracts/inference-provider.yaml + scripts/run_scheduled_agent.py, not a second
    hand-maintained allowlist here (dec-86).
    """
    print("\n=== Prompt file validation ===")
    prompts_dir = _common.ROOT / ".github" / "prompts" / "scheduled"
    prompt_files = list(prompts_dir.glob("*.prompt.md"))
    errors: list[str] = []

    if not prompt_files:
        errors.append(f"no *.prompt.md files found under {prompts_dir}")

    for f in prompt_files:
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
        print(f"All {len(prompt_files)} prompt files passed validation.")
