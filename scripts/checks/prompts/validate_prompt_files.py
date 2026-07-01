from __future__ import annotations

import re

from scripts.checks import _common, registry

KNOWN_MODELS = {
    "Claude Haiku 4.5 (copilot)",
    "Claude Sonnet 4.5 (copilot)",
    "Claude Sonnet 4.6 (copilot)",
    "Claude Opus 4.5 (copilot)",
    "Claude Opus 4.6 (copilot)",
    "GPT-4.1",
    "GPT-5 mini",
    "GPT-5.4",
    "Gemini 2.5 Pro",
}


@registry.register("validate_prompt_files", owner="platform")
def validate_prompt_files(failed: list[str]) -> None:
    print("\n=== Prompt file validation ===")
    prompts_dir = _common.ROOT / ".github" / "prompts"
    prompt_files = list(prompts_dir.glob("*.prompt.md"))
    errors: list[str] = []

    for f in prompt_files:
        content = f.read_text(encoding="utf-8")
        name = f.name

        if not content.startswith("---"):
            errors.append(f"{name} : missing YAML frontmatter")
            continue

        fm_match = re.search(r"(?s)^---[\r\n](.*?)[\r\n]---", content)
        fm = fm_match.group(1) if fm_match else ""

        if not re.search(r"name\s*:", fm):
            errors.append(f"{name} : missing 'name' in frontmatter")
        if not re.search(r"description\s*:", fm):
            errors.append(f"{name} : missing 'description' in frontmatter")

        model_match = re.search(r"model\s*:\s*(.+)", fm)
        if model_match:
            model_value = model_match.group(1).strip().strip('"').strip("'")
            if model_value not in KNOWN_MODELS:
                errors.append(f"{name} : unrecognised model '{model_value}' -- verify against VS Code model picker")

        if "## Intent" not in content:
            errors.append(f"{name} : missing '## Intent' section")

        for ref_match in re.finditer(r"\[.*?\]\((\.\.?/[^)# \s]+)\)", content):
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
