#!/usr/bin/env python3
"""Run a zero-context programmatic LLM call using a skill definition.

This script enforces a fresh context window for critical agentic tasks like
critiques, preventing cognitive bias by passing the instructions and target
content to a fresh API call.
"""

import argparse
import sys
from pathlib import Path

import yaml


def parse_required_context(skill_path: str | Path) -> list[str]:
    content = Path(skill_path).read_text(encoding="utf-8")
    if not content.startswith("---"):
        return []
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return []
    frontmatter = content[3:end_idx]
    try:
        data = yaml.safe_load(frontmatter)
        if isinstance(data, dict) and "required-context" in data:
            val = data["required-context"]
            if isinstance(val, list):
                return [str(v) for v in val]
    except Exception:
        pass
    return []


# Add root to sys.path to allow running directly from CLI
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.llm.client import llm_call  # noqa: E402

try:
    from scripts.executor.telemetry import close_phase, close_session, get_context, open_phase, open_session  # noqa: E402

    _TELEMETRY_AVAILABLE = True
except ImportError:
    _TELEMETRY_AVAILABLE = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an isolated agent skill against a target file.")
    parser.add_argument("--skill", required=True, help="Name of the skill in .claude/skills/")
    parser.add_argument("--target", required=True, help="Path to the target file to evaluate")
    parser.add_argument("--model", help="Optional model override")
    parser.add_argument("--context", nargs="*", help="Optional context files to include")
    parser.add_argument(
        "--session-id",
        dest="session_id",
        default=None,
        help="Parent session UUID (from --open-session). If set, telemetry is attached to the parent; "
        "session lifecycle (open/close) is skipped.",
    )
    parser.add_argument(
        "--phase-order",
        dest="phase_order",
        type=int,
        default=1,
        help="Phase order number for telemetry (used with --session-id; default 1).",
    )
    args = parser.parse_args()

    skill_path = ROOT / ".claude" / "skills" / args.skill / "SKILL.md"
    if not skill_path.exists():
        print(f"Error: Skill file not found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    target_path = ROOT / args.target
    if not target_path.exists():
        print(f"Error: Target file not found at {target_path}", file=sys.stderr)
        sys.exit(1)

    # Load the pure instructions from the skill file
    system_prompt = skill_path.read_text(encoding="utf-8")

    required_ctx = parse_required_context(skill_path)
    explicit_ctx = args.context or []
    all_context_paths = []
    for c in required_ctx + explicit_ctx:
        if c not in all_context_paths:
            all_context_paths.append(c)

    context_text = ""
    if all_context_paths:
        context_text += "\n\n## Additional Context\n"
        for cp in all_context_paths:
            p = ROOT / cp
            if p.exists():
                context_text += f"\n### File: {cp}\n{p.read_text(encoding='utf-8')}\n"
            else:
                print(f"Warning: Context file not found: {cp}", file=sys.stderr)

    # Build the target context
    user_prompt = (
        f"Please execute your skill instructions against the following file.\n\n"
        f"File: {args.target}\n\n"
        f"Content:\n{target_path.read_text(encoding='utf-8')}"
        f"{context_text}"
    )

    print(f"Running skill '{args.skill}' against '{args.target}' in a fresh context...", file=sys.stderr)

    _own_session = False
    if _TELEMETRY_AVAILABLE:
        if args.session_id:
            # Attach to parent session: set the context without opening a new session
            ctx = get_context()
            ctx.session_id = args.session_id
            ctx.workflow = "run_skill"
        else:
            open_session(workflow="run_skill", branch="agent/run_skill", model_primary=args.model or "auto")
            _own_session = True
        open_phase(phase="skill-execution", phase_order=args.phase_order, model_used=args.model or "auto")

    try:
        # We pass the skill content as both inline_instruction (for Gemini)
        # and system_prompt (for Bedrock) to perfectly cover both providers.
        result = llm_call(
            prompt=user_prompt,
            system_prompt=system_prompt,
            inline_instruction=system_prompt,
            purpose=f"skill_{args.skill}",
            model=args.model,
            tools=True,  # We enable tools so the agent can agentically read the workspace
            check=False,
        )

        if _TELEMETRY_AVAILABLE:
            _phase_outcome = "success" if result.exit_code == 0 else "failure"
            close_phase(
                outcome=_phase_outcome,
                tokens_input=result.tokens_in,
                tokens_output=result.tokens_out,
            )
    finally:
        # Only close the session if this invocation owns it (no parent session_id)
        if _TELEMETRY_AVAILABLE and _own_session:
            _ran_ok = "result" in locals() and result.exit_code == 0
            close_session(
                outcome="success" if _ran_ok else "failure",
            )

    if result.exit_code != 0:
        print(f"\nLLM Error (exit {result.exit_code}):\n{result.stderr or result.content}", file=sys.stderr)
        sys.exit(result.exit_code)

    print("\n" + "=" * 50)
    print(f" {args.skill.upper()} OUTPUT ".center(50, "="))
    print("=" * 50 + "\n")
    print(result.content)
    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    main()
