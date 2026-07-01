"""Intent-doc freeze gate (Decision 86): reject standing prose-architecture docs not grandfathered."""

from __future__ import annotations

from scripts.checks import _common, registry


@registry.register("validate_intent_doc_freeze", owner="platform")
def validate_intent_doc_freeze(failed: list[str]) -> None:
    """Reject any standing prose-architecture doc not in the grandfather set (Decision 86).

    The grandfather set derives from docs/intent-migration/MANIFEST.yaml: a doc path is
    allowed iff it has a documents[] entry with disposition_state != done. As each wave
    flips an entry to disposition_state: done and deletes the file, the allowed set shrinks
    automatically with no manual edits.

    Scan model: enumerates on-disk docs via dirlist (NOT get_changed_files) so a committed
    but undiffed doc is always caught. Scope: docs/INTENT-*.md anywhere under docs/ except
    docs/contracts/ and docs/intent-migration/. Fail-open (warning, no failure) if the
    manifest is absent or unreadable.
    """
    print("\n=== Intent doc freeze (Decision 86) ===")
    manifest_path = _common.ROOT / "docs" / "intent-migration" / "MANIFEST.yaml"
    try:
        import yaml  # noqa: PLC0415

        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        allowed: set[str] = {
            f"docs/INTENT-{doc['id']}.md"
            for doc in manifest_data.get("documents", [])
            if doc.get("disposition_state", "pending") != "done"
        }
    except Exception as exc:
        print(f"WARNING: intent-doc-freeze: manifest unreadable ({exc}); check skipped (fail-open).")
        return

    excluded_dirs = {"contracts", "intent-migration"}
    docs_dir = _common.ROOT / "docs"

    for candidate in sorted(docs_dir.rglob("INTENT-*.md")):
        parts = candidate.relative_to(docs_dir).parts
        if parts[0] in excluded_dirs:
            continue
        rel = str(candidate.relative_to(_common.ROOT)).replace("\\", "/")
        if rel not in allowed:
            failed.append(f"intent-doc-freeze: {rel} is not in the manifest grandfather set (Decision 86)")
