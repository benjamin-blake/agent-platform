"""Field-semantics generator drift gate (T2.33) (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_field_semantics_drift", owner="platform")
def validate_field_semantics_drift(failed: list[str]) -> None:
    """Fail-closed drift gate: regenerate field_semantics.yaml in-memory and byte-compare.

    If the committed file differs from what the generator would produce, appends a failure.
    NEVER auto-writes (Decision 55). Pure Python, sub-second -- eligible for both --pre
    and the full presubmit tier (adjacent to the CD.25 contract drift gate).
    """
    print("\n=== Field semantics drift gate (T2.33) ===")

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)

    try:
        import scripts.schema_to_field_semantics as _gen_mod

        output_path = _gen_mod._OUTPUT_PATH
        try:
            committed = output_path.read_text(encoding="utf-8")
        except OSError as exc:
            failed.append(f"Field semantics drift gate: cannot read {output_path}: {exc}")
            return

        try:
            generated = _gen_mod._emit_yaml(_gen_mod.generate(include_prose=False))
        except Exception as exc:
            failed.append(f"Field semantics drift gate: generator raised: {exc}")
            return

        if generated != committed:
            failed.append(
                "Field semantics drift gate: config/lambda/ducklake/field_semantics.yaml "
                "differs from generator output -- run: "
                "bin/venv-python -m scripts.schema_to_field_semantics (then commit the result). "
                "Do NOT hand-edit field_semantics.yaml (Decision 55)."
            )
            print("  FAIL: field_semantics.yaml has drifted from the generator output. Run the generator to regenerate.")
        else:
            print("  PASS: field_semantics.yaml matches generator output (no drift).")

    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
