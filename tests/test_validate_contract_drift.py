"""End-to-end tests for validate_contract_drift (T-1.12 subset e).

Follows the tests/test_validate_dq_drift.py module-load pattern: validate.py is loaded by
file path so the gate function can be exercised directly against tmp_path fixture contract
dirs.  Each of the eight CD.25 rejection checks gets a dedicated fixture; a well-formed set
and a non-ritual-only dir append nothing.

Pass 2 (diff-aware categories 6 and 7) shells out to git; those tests inject a fake `run`
so the base contract content is supplied deterministically without touching the real repo
history.  Pass-1-only tests set merge_base_rc=1 so Pass 2 is skipped (fail-open) and the
assertion isolates the structural category under test.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate.py"
_spec = importlib.util.spec_from_file_location("validate_contract_drift_under_test", _SCRIPT_PATH)
_validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_validate)  # type: ignore[union-attr]
sys.modules["validate_contract_drift_under_test"] = _validate

validate_contract_drift = _validate.validate_contract_drift


class _FakeGit:
    """Configurable stand-in for validate.run covering the three Pass-2 git calls.

    merge_base_rc=1 makes `git merge-base` fail so Pass 2 is skipped entirely.
    `changed` is the `git diff --name-only` output (repo-relative paths).
    `show_map` maps a repo-relative path to the base contract text returned by `git show`
    (absent key => git show fails with returncode 1, exercising the fail-open skip).
    """

    def __init__(
        self,
        *,
        merge_base_rc: int = 1,
        merge_base: str = "BASE0000",
        changed: list[str] | None = None,
        show_map: dict[str, str] | None = None,
    ) -> None:
        self.merge_base_rc = merge_base_rc
        self.merge_base = merge_base
        self.changed = changed or []
        self.show_map = show_map or {}
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        head = cmd[:2]
        if head == ["git", "merge-base"]:
            return subprocess.CompletedProcess(cmd, self.merge_base_rc, stdout=self.merge_base + "\n", stderr="")
        if head == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{p}\n" for p in self.changed), stderr="")
        if head == ["git", "show"]:
            _, _, rel = cmd[2].partition(":")
            text = self.show_map.get(rel)
            if text is None:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="path not in tree")
            return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


def _valid_class_a(
    *,
    contract_id: str = "alpha",
    status: str = "draft",
    description: str = "Alpha contract description",
) -> str:
    """A fully-populated, well-formed Class A ritual contract."""
    return (
        textwrap.dedent(
            f"""
            contract:
              id: {contract_id}
              class: A
              contract_version: 1
              status: {status}
              description: {description}
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
                dq_intent:
                  not_null:
                    enforced: true
            """
        ).strip()
        + "\n"
    )


def _install_fake_git(monkeypatch, fake: _FakeGit) -> None:
    from scripts.checks import _common

    monkeypatch.setattr(_common, "run", fake)


# --------------------------------------------------------------------------------------
# Category 1 -- malformed YAML / schema violation
# --------------------------------------------------------------------------------------
class TestCategory1Malformed:
    def test_genuinely_unparseable_yaml_is_surfaced(self, tmp_path, monkeypatch) -> None:
        # Unclosed flow mapping: yaml.safe_load raises YAMLError. load_all_contracts would
        # SWALLOW this (except (OSError, yaml.YAMLError): continue); the per-file path must
        # surface it as a category-1 defect.  The file carries a ritual contract.class shape
        # so it is unambiguously a contract that failed to parse, not a stray doc.
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        _write(tmp_path, "broken.yaml", "contract:\n  id: broken\n  class: A\n  fields: {unclosed: [\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("broken.yaml" in f for f in failed)
        assert any("cat-1" in f for f in failed)

    def test_top_level_non_mapping_is_surfaced(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        _write(tmp_path, "listy.yaml", "- just\n- a\n- list\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("listy.yaml" in f and "not a YAML mapping" in f for f in failed)

    def test_schema_violation_is_surfaced(self, tmp_path, monkeypatch) -> None:
        # Ritual shape (contract.class present) but missing the required contract_version.
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        text = "contract:\n  id: nov\n  class: A\n  status: draft\nfields:\n  f1:\n    type: string\n"
        _write(tmp_path, "noversion.yaml", text)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("noversion.yaml" in f and "structural" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 2 -- inline Class-A field missing a required descriptive key
# --------------------------------------------------------------------------------------
class TestCategory2RequiredInlineFields:
    def test_inline_field_missing_dq_intent_rejected(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat2
              class: A
              contract_version: 1
              status: draft
              description: Cat2
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
            """
        ).strip()
        _write(tmp_path, "cat2.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat2.yaml" in f and "dq_intent" in f and "category 2" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 3 -- $ref to a non-existent target file
# --------------------------------------------------------------------------------------
class TestCategory3DanglingRef:
    def test_ref_to_missing_file_rejected(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat3
              class: A
              contract_version: 1
              status: draft
              description: Cat3
            fields:
              f1:
                $ref: nonexistent.yaml#/contract/fields/x
            """
        ).strip()
        _write(tmp_path, "cat3.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat3.yaml" in f and "ref" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 4 -- $ref chain depth > 1 (a Class A ref to a Class C field that is itself a $ref)
# --------------------------------------------------------------------------------------
class TestCategory4ChainDepth:
    def test_chained_ref_rejected(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        # classc2 owns the leaf inline field `deep`.
        _write(
            tmp_path,
            "classc2.yaml",
            textwrap.dedent(
                """
                contract:
                  id: classc2
                  class: C
                  contract_version: 1
                  status: draft
                fields:
                  deep:
                    type: string
                    nullable: false
                    description: Deep field
                    semantics: Deep meaning
                    populated_by: writer
                    dq_intent:
                      not_null:
                        enforced: true
                """
            ).strip()
            + "\n",
        )
        # classc.shared is itself a $ref (resolves cleanly to classc2.deep, so classc passes).
        _write(
            tmp_path,
            "classc.yaml",
            textwrap.dedent(
                """
                contract:
                  id: classc
                  class: C
                  contract_version: 1
                  status: draft
                fields:
                  shared:
                    $ref: classc2.yaml#/contract/fields/deep
                """
            ).strip()
            + "\n",
        )
        # cat4 (Class A) refs classc.shared -- which is a $ref -> chain depth > 1.
        _write(
            tmp_path,
            "cat4.yaml",
            textwrap.dedent(
                """
                contract:
                  id: cat4
                  class: A
                  contract_version: 1
                  status: draft
                  description: Cat4
                fields:
                  f1:
                    $ref: classc.yaml#/contract/fields/shared
                """
            ).strip()
            + "\n",
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        # Only cat4 fails (the chained ref); classc and classc2 resolve cleanly.
        assert any("cat4.yaml" in f and "chain" in f.lower() for f in failed)
        assert not any("classc.yaml" in f for f in failed)
        assert not any("classc2.yaml" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 5 -- duplicate inline definition alongside a $ref
# --------------------------------------------------------------------------------------
class TestCategory5DuplicateInline:
    def test_inline_alongside_ref_rejected(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat5
              class: A
              contract_version: 1
              status: draft
              description: Cat5
            fields:
              f1:
                $ref: whatever.yaml#/contract/fields/x
                type: string
            """
        ).strip()
        _write(tmp_path, "cat5.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat5.yaml" in f and "duplicate" in f.lower() for f in failed)


# --------------------------------------------------------------------------------------
# Category 6 -- description/semantics change without an amendment_log entry (Pass 2)
# --------------------------------------------------------------------------------------
class TestCategory6AmendmentLog:
    def test_description_change_without_amendment_rejected(self, tmp_path, monkeypatch) -> None:
        head = _valid_class_a(contract_id="cat6", description="New contract description")
        base = _valid_class_a(contract_id="cat6", description="Old contract description")
        _write(tmp_path, "cat6.yaml", head)
        fake = _FakeGit(
            merge_base_rc=0,
            changed=["docs/contracts/cat6.yaml"],
            show_map={"docs/contracts/cat6.yaml": base},
        )
        _install_fake_git(monkeypatch, fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat6.yaml" in f and "category 6" in f for f in failed)

    def test_base_show_failure_fails_open(self, tmp_path, monkeypatch) -> None:
        # Same drift as above, but `git show` cannot resolve the base (returncode 1) -> Pass 2
        # skips the file (fail-open) and appends nothing.
        head = _valid_class_a(contract_id="cat6", description="New contract description")
        _write(tmp_path, "cat6.yaml", head)
        fake = _FakeGit(merge_base_rc=0, changed=["docs/contracts/cat6.yaml"], show_map={})
        _install_fake_git(monkeypatch, fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_unparseable_base_fails_open(self, tmp_path, monkeypatch) -> None:
        # Base content from git show does not validate -> Pass 2 skips the file (the base already
        # passed the gate when it merged) and appends nothing.
        head = _valid_class_a(contract_id="cat6", description="New contract description")
        _write(tmp_path, "cat6.yaml", head)
        fake = _FakeGit(
            merge_base_rc=0,
            changed=["docs/contracts/cat6.yaml"],
            show_map={"docs/contracts/cat6.yaml": "{bad: [unclosed"},
        )
        _install_fake_git(monkeypatch, fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []


# --------------------------------------------------------------------------------------
# Category 7 -- forbidden status transition (Pass 2)
# --------------------------------------------------------------------------------------
class TestCategory7StatusTransition:
    def test_forbidden_transition_rejected(self, tmp_path, monkeypatch) -> None:
        # draft -> deprecated is not in the Invariant-6 state machine. Descriptions are
        # identical so category 6 does not also fire.
        head = _valid_class_a(contract_id="cat7", status="deprecated")
        base = _valid_class_a(contract_id="cat7", status="draft")
        _write(tmp_path, "cat7.yaml", head)
        fake = _FakeGit(
            merge_base_rc=0,
            changed=["docs/contracts/cat7.yaml"],
            show_map={"docs/contracts/cat7.yaml": base},
        )
        _install_fake_git(monkeypatch, fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat7.yaml" in f and "category 7" in f for f in failed)
        assert not any("category 6" in f for f in failed)


# --------------------------------------------------------------------------------------
# Category 8 -- amendment_log change_class outside the closed vocabulary
# --------------------------------------------------------------------------------------
class TestCategory8BadChangeClass:
    def test_out_of_vocab_change_class_rejected(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: cat8
              class: A
              contract_version: 1
              status: draft
              description: Cat8
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
                dq_intent:
                  not_null:
                    enforced: true
            amendment_log:
              - date: "2026-01-01"
                semantic_break: false
                change_class: bogus_change_class
            """
        ).strip()
        _write(tmp_path, "cat8.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("cat8.yaml" in f and "structural" in f for f in failed)


# --------------------------------------------------------------------------------------
# Clean / no-op cases
# --------------------------------------------------------------------------------------
class TestCleanAndNoRitual:
    def test_well_formed_contract_passes_pass1(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        _write(tmp_path, "alpha.yaml", _valid_class_a())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_changed_contract_with_no_drift_passes_pass2(self, tmp_path, monkeypatch) -> None:
        # A contract changed vs the merge-base whose base and head are identical: both diff-aware
        # checks return clean, so nothing is appended (exercises the Pass-2 no-violation path).
        same = _valid_class_a(contract_id="alpha")
        _write(tmp_path, "alpha.yaml", same)
        fake = _FakeGit(
            merge_base_rc=0,
            changed=["docs/contracts/alpha.yaml"],
            show_map={"docs/contracts/alpha.yaml": same},
        )
        _install_fake_git(monkeypatch, fake)
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_non_ritual_only_dir_passes(self, tmp_path, monkeypatch) -> None:
        # read-engine.yaml-style doc: parses, but has no contract.class -> skipped, no failure.
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        _write(tmp_path, "read-engine.yaml", "version: 3\nengine: duckdb\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_missing_contracts_dir_is_skipped(self, tmp_path, monkeypatch) -> None:
        _install_fake_git(monkeypatch, _FakeGit(merge_base_rc=1))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path / "does_not_exist")
        assert failed == []
