"""Package conftest for tests/checks/contracts/validate_contract_drift/ (T2.56 concern-split
decomposition of the former tests/checks/contracts/test_validate_contract_drift.py monolith,
Decision 128 -- see AGENTS.md SLOC governance).

Hoists _FakeGit and its associated helpers VERBATIM in spirit from the pre-decomposition
module, EXTENDED to answer `git ls-tree`, `git diff -M --name-status`, and `git cat-file
--batch` for the population gate's baseline readers (scripts/checks/contracts/_shared.py).
Every fixture passes an explicit fake/baseline_reader rather than relying on module state --
_shared.py deliberately has no memoization, so the suite must not either.

The evaluator-resolution fixtures exercise REAL registered checks (validate_placement,
validate_sloc_budget_raises) as both verified poles -- registry.all_checks() (Decision 169)
eagerly imports every manifest-declared module at CALL TIME, so no separate warm-up load of
scripts/validate.py is needed to populate it.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml as _yaml_module

from scripts.checks.contracts.validate_contract_drift import (
    validate_contract_drift,  # noqa: F401  (re-exported for `from .conftest import validate_contract_drift` in sibling test modules)
)


class _FakeGit:
    """Configurable stand-in for scripts.checks._common.run covering every git call the
    population gate makes.

    merge_base_rc=1 makes `git merge-base` fail so every baseline-dependent leg is skipped.
    `changed`: `git diff --name-only <base>..HEAD -- docs/contracts/` output (repo-relative).
    `show_map`: repo-relative path -> base text for `git show <ref>:<path>` (absent -> rc=1).
    `ls_tree`: the merge-base docs/contracts/ path population for `git ls-tree -r --name-only`
      (defaults to show_map's keys when not given explicitly).
    `renames`: {new_path: old_path} rendered as `git diff -M --name-status` R100 rows.
    `batch_map`: repo-relative path -> raw text for `git cat-file --batch` (absent -> "missing";
      defaults to show_map when not given explicitly).
    """

    def __init__(
        self,
        *,
        merge_base_rc: int = 1,
        merge_base: str = "BASE0000",
        changed: list[str] | None = None,
        show_map: dict[str, str] | None = None,
        ls_tree: list[str] | None = None,
        renames: dict[str, str] | None = None,
        batch_map: dict[str, str] | None = None,
    ) -> None:
        self.merge_base_rc = merge_base_rc
        self.merge_base = merge_base
        self.changed = changed or []
        self.show_map = show_map or {}
        self.ls_tree = ls_tree if ls_tree is not None else list(self.show_map)
        self.renames = renames or {}
        self.batch_map = batch_map if batch_map is not None else dict(self.show_map)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        head = cmd[:2]
        if head == ["git", "merge-base"]:
            return subprocess.CompletedProcess(cmd, self.merge_base_rc, stdout=self.merge_base + "\n", stderr="")
        if cmd[:3] == ["git", "ls-tree", "-r"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{p}\n" for p in self.ls_tree), stderr="")
        if head == ["git", "diff"] and "-M" in cmd:
            lines = [f"R100\t{old}\t{new}\n" for new, old in self.renames.items()]
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(lines), stderr="")
        if head == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{p}\n" for p in self.changed), stderr="")
        if head == ["git", "show"]:
            _, _, rel = cmd[2].partition(":")
            text = self.show_map.get(rel)
            if text is None:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="path not in tree")
            return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")
        if cmd[:3] == ["git", "cat-file", "--batch"]:
            raw_input = str(kwargs.get("input") or "")
            refs = [line for line in raw_input.splitlines() if line]
            parts = []
            for ref in refs:
                _, _, rel = ref.partition(":")
                text = self.batch_map.get(rel)
                if text is None:
                    parts.append(f"{ref} missing\n")
                else:
                    parts.append(f"{'0' * 40} blob {len(text)}\n{text}\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(parts), stderr="")
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


def _class_d_yaml(
    *,
    contract_id: str = "cd-alpha",
    subject: str = "cd-alpha",
    status: str = "ratified",
    ratified_via: str | None = "test-decision",
    evaluator: dict | None = None,
    amendment_log: list | None = None,
    extra: dict | None = None,
) -> str:
    """Build a Class D contract YAML text from parts -- avoids hand-formatted YAML strings so
    each fixture can vary exactly the field(s) under test."""
    contract: dict = {"id": contract_id, "class": "D", "contract_version": 1, "status": status, "subject": subject}
    if ratified_via is not None:
        contract["ratified_via"] = ratified_via
    if evaluator is not None:
        contract["evaluator"] = evaluator
    doc: dict = {"contract": contract}
    if amendment_log is not None:
        doc["amendment_log"] = amendment_log
    if extra:
        doc.update(extra)
    return _yaml_module.dump(doc, sort_keys=False)


@pytest.fixture
def FakeGit():
    return _FakeGit


@pytest.fixture
def install_fake_git(monkeypatch):
    def _install(fake: _FakeGit) -> _FakeGit:
        from scripts.checks import _common

        monkeypatch.setattr(_common, "run", fake)
        return fake

    return _install


@pytest.fixture
def write_contract():
    return _write


@pytest.fixture
def valid_class_a():
    return _valid_class_a


@pytest.fixture
def class_d_yaml():
    return _class_d_yaml
