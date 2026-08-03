"""Tests for validate_fallback_reevaluation() (ESB-02 remediation, PLAN-esb-fallback-spec-carrier).

Net-new-plan-path derivation is NEVER injectable in the checked module itself (its own docstring
refuses that seam, mirroring validate_graduation_completeness's refusal) -- so every case that
needs to prove firing/non-firing on a genuinely net-new (or not-net-new) plan builds a throwaway
git repo with a real `refs/remotes/origin/main` ref and patches `scripts.checks._common.ROOT` at
it, duplicating the small git-repo helpers from tests/checks/verification/
test_validate_graduation_completeness.py locally (no cross-test imports, per tests/CLAUDE.md).
Cases that don't need real git (CD.27-absent, malformed roadmap) use the `roadmap_path` injection
seam directly -- the module's ONLY parameter seam (code review round 1: `plans_dir` was dropped
as dead weight; `_common.ROOT` is the sole root). The two silent-`continue` branches
(added-but-absent-on-disk, added-but-fails-to-load) are exercised by patching the private
`_net_new_plan_paths` helper directly -- `_common.get_status_aware_diff()` existence-filters its
own "A"/"M" entries, so a genuinely-absent path can never reach the loop through real git state;
patching the helper is the only way to exercise that defensive branch at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks.roadmap.validate_fallback_reevaluation import validate_fallback_reevaluation

_ROADMAP_HEADER = "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"

_ROADMAP_WITH_CD27 = (
    _ROADMAP_HEADER
    + "candidate_decisions:\n"
    + "  - id: CD.27\n    title: t\n    state: pending\n"
    + "    gates: [T4.1, T4.2, T4.3, T4.4]\n"
    + "tier_items:\n"
    + "  - {id: T4.1, tier: T4, name: t}\n"
    + "  - {id: T4.2, tier: T4, name: t}\n"
    + "  - {id: T4.3, tier: T4, name: t}\n"
    + "  - {id: T4.4, tier: T4, name: t}\n"
)

_ROADMAP_NO_CD27 = (
    _ROADMAP_HEADER
    + "candidate_decisions:\n"
    + "  - id: CD.99\n    title: t\n    state: pending\n"
    + "    gates: [T9.1]\n"
    + "tier_items:\n"
    + "  - {id: T9.1, tier: T9, name: t}\n"
)

_ROADMAP_CD27_EMPTY_GATES = (
    _ROADMAP_HEADER + "candidate_decisions:\n" + "  - id: CD.27\n    title: t\n    state: pending\n" + "    gates: []\n"
)


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", message])
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


def _write_roadmap(root: Path, text: str = _ROADMAP_WITH_CD27) -> None:
    path = root / "docs" / "ROADMAP-PLATFORM.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fallback_block() -> dict:
    return {
        "reevaluated_on": "2026-08-02",
        "substrate_status": "no API-semantics regression observed at filing",
        "verdict": "continue_on_current_substrate",
        "basis": "reviewed against the CD.27 fallback_spec trigger; substrate semantics unchanged",
    }


def _step(step: int) -> dict:
    return {
        "step": step,
        "phase": "pre-deploy",
        "action": "do something",
        "command": "echo ok",
        "expected": "prints ok",
        "fix_if": "never fails in practice",
    }


def _plan_dict(
    slug: str, phase: str, closes_criteria: list[str] | None = None, fallback_reevaluation: dict | None = None
) -> dict:
    d = {
        "schema_version": 1,
        "slug": slug,
        "intent": "Test fixture plan.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": phase,
        "scope": [{"file": "scripts/example.py", "action": "Create", "purpose": "Demo."}],
        "closes_criteria": closes_criteria or [],
        "acceptance_criteria": ["Example acceptance criterion."],
        "verification_plan": [_step(1)],
        "execution_steps": ["Create scripts/example.py."],
    }
    if fallback_reevaluation is not None:
        d["fallback_reevaluation"] = fallback_reevaluation
    return d


def _write_plan(
    root: Path, slug: str, phase: str, closes_criteria: list[str] | None = None, fallback_reevaluation: dict | None = None
) -> str:
    rel = f"docs/plans/PLAN-{slug}.yaml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(_plan_dict(slug, phase, closes_criteria, fallback_reevaluation), sort_keys=False),
        encoding="utf-8",
    )
    return rel


class TestNoGitNeeded:
    """CD.27-resolution failures short-circuit before any git/diff work.

    The check follows the repo-wide pattern (mirrors validate_candidate_decision_ratification):
    `failed` carries a fixed label, the specific diagnostic is printed -- so these assert on
    captured stdout (capsys), not on the failed[] entries.
    """

    def test_cd27_absent_fails_loud(self, tmp_path: Path, capsys) -> None:
        roadmap_path = tmp_path / "ROADMAP-PLATFORM.yaml"
        roadmap_path.write_text(_ROADMAP_NO_CD27, encoding="utf-8")
        failed: list[str] = []
        validate_fallback_reevaluation(failed, roadmap_path=roadmap_path)
        assert failed == ["Fallback re-evaluation carrier"]
        assert "CD.27 not found" in capsys.readouterr().out

    def test_cd27_empty_gates_fails_loud(self, tmp_path: Path, capsys) -> None:
        """Code review round 2 (Low, orchestrator ruling): an emptied CD.27.gates list is the
        phantom-control shape this wave exists to remove -- a silent PASS would make the carrier
        a permanent, undetectable no-op. Must fail loud like the sibling missing-trigger cases."""
        roadmap_path = tmp_path / "ROADMAP-PLATFORM.yaml"
        roadmap_path.write_text(_ROADMAP_CD27_EMPTY_GATES, encoding="utf-8")
        failed: list[str] = []
        validate_fallback_reevaluation(failed, roadmap_path=roadmap_path)
        assert failed == ["Fallback re-evaluation carrier"]
        out = capsys.readouterr().out
        assert "CD.27" in out and "empty gates" in out

    def test_malformed_roadmap_fails_loud(self, tmp_path: Path, capsys) -> None:
        """Code review round 2 (Medium): the module docstring claimed this case; it did not
        exist as a test. Exercises the `_cd27_gates` exception branch (:160-165) directly --
        unparseable YAML raises inside `yaml.safe_load` before pydantic ever sees it."""
        roadmap_path = tmp_path / "ROADMAP-PLATFORM.yaml"
        roadmap_path.write_text("document:\n  id: broken\n  version: [unterminated\n", encoding="utf-8")
        failed: list[str] = []
        validate_fallback_reevaluation(failed, roadmap_path=roadmap_path)
        assert failed == ["Fallback re-evaluation carrier"]
        assert "could not load roadmap" in capsys.readouterr().out

    def test_missing_roadmap_file_fails_loud(self, tmp_path: Path, capsys) -> None:
        failed: list[str] = []
        validate_fallback_reevaluation(failed, roadmap_path=tmp_path / "does-not-exist.yaml")
        assert failed == ["Fallback re-evaluation carrier"]
        assert "not found" in capsys.readouterr().out


class TestGitBackedFiring:
    """Net-new-plan cases, exercised against a real throwaway git repo (no injected added_paths seam)."""

    def _base_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_roadmap(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        return repo

    def test_fires_via_closes_criteria_leg_without_block_fails(self, tmp_path: Path, capsys) -> None:
        repo = self._base_repo(tmp_path)
        rel = _write_plan(repo, "fr-closes-fail", "Test fixture -- no roadmap phase.", closes_criteria=["T4.2:c1"])
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == ["Fallback re-evaluation carrier"]
        out = capsys.readouterr().out
        assert rel in out and "T4.2" in out and "fallback_reevaluation" in out

    def test_closes_criteria_leg_with_block_passes(self, tmp_path: Path) -> None:
        repo = self._base_repo(tmp_path)
        _write_plan(
            repo,
            "fr-closes-pass",
            "Test fixture -- no roadmap phase.",
            closes_criteria=["T4.2:c1"],
            fallback_reevaluation=_fallback_block(),
        )
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == []

    def test_fires_via_phase_leg_without_block_fails(self, tmp_path: Path, capsys) -> None:
        repo = self._base_repo(tmp_path)
        rel = _write_plan(repo, "fr-phase-fail", "Platform T4.2 atomic-plan work on the executor substrate.")
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == ["Fallback re-evaluation carrier"]
        out = capsys.readouterr().out
        assert rel in out and "T4.2" in out and "fallback_reevaluation" in out

    def test_phase_leg_with_block_passes(self, tmp_path: Path) -> None:
        repo = self._base_repo(tmp_path)
        _write_plan(
            repo,
            "fr-phase-pass",
            "Platform T4.2 atomic-plan work on the executor substrate.",
            fallback_reevaluation=_fallback_block(),
        )
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == []

    def test_non_gated_plan_untouched(self, tmp_path: Path) -> None:
        repo = self._base_repo(tmp_path)
        _write_plan(repo, "fr-non-gated", "Unrelated non-gated item T9.9 work.", closes_criteria=["T9.9:c1"])
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == []

    def test_prefix_collision_negative_t4_12_t4_13_does_not_trigger(self, tmp_path: Path) -> None:
        """Gate T4.1 is a string prefix of T4.12/T4.13 -- a net-new plan naming only those must NOT trigger."""
        repo = self._base_repo(tmp_path)
        _write_plan(repo, "fr-prefix-collision", "Work spanning T4.12 and T4.13 only, no other gate named here.")
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == []

    def test_sentence_final_gate_still_matches(self, tmp_path: Path, capsys) -> None:
        """The lookahead excludes word characters ONLY -- a sentence-final 'T4.4.' still matches gate T4.4."""
        repo = self._base_repo(tmp_path)
        rel = _write_plan(repo, "fr-sentence-final", "This plan's substrate work concludes T4.4.")
        _commit_all(repo, "add net-new plan")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_fallback_reevaluation(failed)
        assert failed == ["Fallback re-evaluation carrier"]
        out = capsys.readouterr().out
        assert rel in out and "T4.4" in out

    def test_not_net_new_plan_is_untouched(self, tmp_path: Path) -> None:
        """A plan already present at the origin/main merge-base (unmodified since) is not enforced --
        proven against REAL git state, not an injected added_paths seam (the retro-fit-avoidance
        property this carrier's entire design rests on).

        Pins the MECHANISM, not just the end-to-end symptom (code review round 3, Low): a bare
        `failed == []` alone does not distinguish "correctly excluded as not-net-new" from "the
        carrier silently found nothing for some unrelated reason" -- a sibling test
        (test_fires_via_closes_criteria_leg_without_block_fails) already proves this exact fixture
        shape DOES fire when genuinely net-new, so the extra `_net_new_plan_paths()` assertion here
        closes the gap by directly confirming the plan is excluded from the "A" set itself."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_roadmap(repo)
        rel = _write_plan(repo, "fr-not-net-new", "Platform T4.2 atomic-plan work.", closes_criteria=["T4.2:c1"])
        base_sha = _commit_all(repo, "base with plan")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        # An unrelated follow-up commit exercises the diff machinery without touching the plan.
        (repo / "README.md").write_text("unrelated change\n", encoding="utf-8")
        _commit_all(repo, "unrelated follow-up")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            from scripts.checks.roadmap.validate_fallback_reevaluation import _net_new_plan_paths

            added = _net_new_plan_paths()
            validate_fallback_reevaluation(failed)
        assert added is not None and rel not in added, f"{rel} was reported net-new; fixture no longer proves the claim"
        assert failed == []

    def test_origin_main_unreachable_advisory_skips(self, tmp_path: Path) -> None:
        """No git repo at all (origin/main unreachable) never fails -- advisory SKIP (Decision 132 limitation A)."""
        _write_roadmap(tmp_path)
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_fallback_reevaluation(failed)
        assert failed == []


class TestSilentContinueBranches:
    """The two defensive silent-`continue` branches (code review round 1: 'also worth closing').

    Neither is reachable through real git state -- `_common.get_status_aware_diff()`
    existence-filters its own "A"/"M" entries before this module ever sees them -- so both are
    exercised by patching the private `_net_new_plan_paths` helper directly, never through the
    (deliberately absent) added_paths seam.
    """

    def test_added_but_absent_on_disk_is_skipped(self, tmp_path: Path, capsys) -> None:
        _write_roadmap(tmp_path)
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_fallback_reevaluation._net_new_plan_paths",
                return_value=["docs/plans/PLAN-ghost.yaml"],
            ),
        ):
            failed: list[str] = []
            validate_fallback_reevaluation(failed)
        assert failed == []
        assert "not present on disk" in capsys.readouterr().out

    def test_added_but_fails_to_load_is_skipped(self, tmp_path: Path, capsys) -> None:
        _write_roadmap(tmp_path)
        rel = "docs/plans/PLAN-malformed.yaml"
        bad_path = tmp_path / rel
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("not: a-valid-plan-document\n", encoding="utf-8")
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_fallback_reevaluation._net_new_plan_paths",
                return_value=[rel],
            ),
        ):
            failed: list[str] = []
            validate_fallback_reevaluation(failed)
        assert failed == []
        assert "load error" in capsys.readouterr().out
