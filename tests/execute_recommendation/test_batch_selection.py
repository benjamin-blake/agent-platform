"""Batch execution, topological ordering, and batch/cluster selection tests (rec-2709 Wave 2)."""

import json
from unittest.mock import patch

import pytest

from scripts.execute_recommendation import (
    execute_batch,
    main,
    select_compound_batch,
    select_next_batch,
    topological_sort_recs,
)


class TestExecuteBatch:
    """Tests for execute_batch()."""

    def _make_recs(self, count: int) -> list[dict]:
        return [
            {
                "id": f"rec-{i:03d}",
                "title": f"Rec {i}",
                "risk": "low",
                "automatable": True,
                "effort": "S",
            }
            for i in range(1, count + 1)
        ]

    def test_empty_queue_returns_zero_attempted(self):
        """No eligible recs â€” returns summary with all zeros."""
        with patch("scripts.executor.batch.get_eligible_recs") as mock_eligible:
            mock_eligible.return_value = []
            summary = execute_batch()
        assert summary["attempted"] == 0
        assert summary["succeeded"] == 0
        assert summary["failed"] == 0

    def test_single_rec_success(self):
        """One eligible rec succeeds â€” summary shows 1 attempted, 1 succeeded."""
        recs = self._make_recs(1)
        with (
            patch("scripts.executor.batch.get_eligible_recs") as mock_eligible,
            patch("scripts.execute_recommendation.execute_recommendation") as mock_exec,
        ):
            mock_eligible.side_effect = [recs, [], []]
            mock_exec.return_value = True
            summary = execute_batch()
        assert summary["attempted"] == 1
        assert summary["succeeded"] == 1
        assert summary["failed"] == 0

    def test_failure_continues_to_next(self):
        """Failed rec doesn't abort batch â€” next eligible rec is attempted."""
        recs = self._make_recs(2)
        with (
            patch("scripts.executor.batch.get_eligible_recs") as mock_eligible,
            patch("scripts.execute_recommendation.execute_recommendation") as mock_exec,
        ):
            # First call returns 2 recs; after first processed, return second only
            mock_eligible.side_effect = [recs, [recs[1]], [], []]
            mock_exec.side_effect = [False, True]  # first fails, second succeeds
            summary = execute_batch()
        assert summary["attempted"] == 2
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1

    def test_max_recs_limits_batch(self):
        """--max-recs N stops after N recommendations regardless of how many are eligible."""
        recs = self._make_recs(5)
        with (
            patch("scripts.executor.batch.get_eligible_recs") as mock_eligible,
            patch("scripts.execute_recommendation.execute_recommendation") as mock_exec,
        ):
            mock_eligible.side_effect = [recs, recs, recs, recs]
            mock_exec.return_value = True
            summary = execute_batch(max_recs=2)
        assert summary["attempted"] == 2

    def test_reevaluates_after_success(self):
        """After a successful rec, get_eligible_recs is called again to pick up unblocked recs."""
        rec_a = {"id": "rec-001", "title": "A", "risk": "low", "automatable": True, "effort": "S"}
        rec_b = {"id": "rec-002", "title": "B", "risk": "low", "automatable": True, "effort": "S"}
        with (
            patch("scripts.executor.batch.get_eligible_recs") as mock_eligible,
            patch("scripts.execute_recommendation.execute_recommendation") as mock_exec,
        ):
            # First call only A is eligible; after A succeeds, B becomes eligible
            mock_eligible.side_effect = [[rec_a], [rec_b], [], []]
            mock_exec.return_value = True
            summary = execute_batch()
        assert summary["attempted"] == 2
        assert summary["succeeded"] == 2
        assert mock_eligible.call_count >= 3

    def test_batch_skips_completed_recs_in_same_run(self):
        """Recs already processed in this batch run are not attempted again."""
        rec = {"id": "rec-001", "title": "A", "risk": "low", "automatable": True, "effort": "S"}
        with (
            patch("scripts.executor.batch.get_eligible_recs") as mock_eligible,
            patch("scripts.execute_recommendation.execute_recommendation") as mock_exec,
        ):
            # Even though eligible returns same rec twice, it should only be attempted once
            mock_eligible.side_effect = [[rec], [rec], [], []]
            mock_exec.return_value = True
            summary = execute_batch()
        assert summary["attempted"] == 1


class TestTopologicalSort:
    """Tests for topological_sort_recs()."""

    def test_no_dependencies(self):
        """Recs with no dependencies are returned in some valid order."""
        recs = [
            {"id": "rec-001", "title": "A"},
            {"id": "rec-002", "title": "B"},
        ]
        result = topological_sort_recs(recs)
        assert len(result) == 2
        ids = [r["id"] for r in result]
        assert "rec-001" in ids
        assert "rec-002" in ids

    def test_chain_ordering(self):
        """Dependency chain: rec-002 depends on rec-001 â€” rec-001 comes first."""
        recs = [
            {"id": "rec-001", "title": "A", "dependencies": []},
            {"id": "rec-002", "title": "B", "dependencies": ["rec-001"]},
        ]
        result = topological_sort_recs(recs)
        ids = [r["id"] for r in result]
        assert ids.index("rec-001") < ids.index("rec-002")

    def test_external_dependency_excluded(self):
        """Dependency on rec not in the input list (e.g. already closed) is ignored."""
        recs = [
            {"id": "rec-002", "title": "B", "dependencies": ["rec-001"]},  # rec-001 not in list
        ]
        result = topological_sort_recs(recs)
        assert len(result) == 1
        assert result[0]["id"] == "rec-002"

    def test_cycle_detection_returns_empty(self):
        """Cyclic dependency graph returns empty list with logged error."""
        recs = [
            {"id": "rec-001", "dependencies": ["rec-002"]},
            {"id": "rec-002", "dependencies": ["rec-001"]},
        ]
        result = topological_sort_recs(recs)
        assert result == []


class TestSelectCompoundBatch:
    """Tests for the compound batch selection logic."""

    def _make_rec(self, rec_id: str, effort: str, status: str = "open", automatable: bool = True, file: str = "a.py") -> dict:
        return {"id": rec_id, "effort": effort, "status": status, "automatable": automatable, "file": file}

    def test_empty_recs_returns_empty_batch(self) -> None:
        assert select_compound_batch([]) == []

    def test_single_xs_rec_selected(self) -> None:
        recs = [self._make_rec("rec-001", "XS")]
        batch = select_compound_batch(recs)
        assert len(batch) == 1
        assert batch[0]["id"] == "rec-001"

    def test_total_effort_capped_at_m(self) -> None:
        """Batch total effort must not exceed MAX_BATCH_EFFORT (2.0 = M)."""
        # 3 S-effort recs: S(1.0) + S(1.0) = 2.0 (full budget). Third S is excluded.
        recs = [
            self._make_rec("rec-001", "S", file="a.py"),  # 1.0 -- selected
            self._make_rec("rec-002", "S", file="b.py"),  # 1.0 -- selected (total 2.0 = M)
            self._make_rec("rec-003", "S", file="c.py"),  # 1.0 -- excluded (would be 3.0)
        ]
        batch = select_compound_batch(recs)
        ids = [r["id"] for r in batch]
        assert len(batch) == 2
        assert "rec-003" not in ids

    def test_batch_capped_at_four_recs(self) -> None:
        """Batch must not exceed MAX_BATCH_SIZE (4) even if total effort allows more."""
        recs = [self._make_rec(f"rec-{i:03d}", "XS") for i in range(1, 10)]
        batch = select_compound_batch(recs)
        assert len(batch) == 4

    def test_closed_recs_excluded(self) -> None:
        recs = [
            self._make_rec("rec-001", "XS", status="closed"),
            self._make_rec("rec-002", "XS", status="open"),
        ]
        batch = select_compound_batch(recs)
        ids = [r["id"] for r in batch]
        assert "rec-001" not in ids
        assert "rec-002" in ids

    def test_non_automatable_recs_excluded(self) -> None:
        recs = [
            self._make_rec("rec-001", "XS", automatable=False),
            self._make_rec("rec-002", "XS", automatable=True),
        ]
        batch = select_compound_batch(recs)
        ids = [r["id"] for r in batch]
        assert "rec-001" not in ids
        assert "rec-002" in ids

    def test_large_effort_rec_excluded_when_over_budget(self) -> None:
        """A single L-effort rec exceeds the budget and is excluded."""
        recs = [
            self._make_rec("rec-001", "L"),  # 4.0 > MAX_BATCH_EFFORT(2.0)
            self._make_rec("rec-002", "XS"),  # 0.5
        ]
        batch = select_compound_batch(recs)
        ids = [r["id"] for r in batch]
        assert "rec-001" not in ids
        assert "rec-002" in ids

    def test_prefers_lower_effort_recs_first(self) -> None:
        """XS recs are selected before S recs when sorting by effort."""
        recs = [
            self._make_rec("rec-001", "S"),
            self._make_rec("rec-002", "XS"),
            self._make_rec("rec-003", "M"),
        ]
        batch = select_compound_batch(recs)
        # XS (0.5) + S (1.0) = 1.5 <= 2.0; M (2.0) would push to 3.5 -- excluded
        ids = [r["id"] for r in batch]
        assert "rec-002" in ids  # XS
        assert "rec-001" in ids  # S
        assert "rec-003" not in ids  # M excluded (over budget)

    def test_missing_status_field_defaults_to_open(self) -> None:
        """Recs with missing status field are treated as open (included in batch)."""
        recs = [self._make_rec("rec-001", "XS")]
        recs[0].pop("status")  # remove status field entirely
        batch = select_compound_batch(recs)
        assert len(batch) == 1
        assert batch[0]["id"] == "rec-001"

    def test_prefers_same_file_recs_when_effort_equal(self) -> None:
        """Same-file recs are clustered together when effort is equal."""
        recs = [
            self._make_rec("rec-001", "XS", file="b.py"),
            self._make_rec("rec-002", "XS", file="a.py"),
            self._make_rec("rec-003", "XS", file="a.py"),
        ]
        batch = select_compound_batch(recs)
        files = [r["file"] for r in batch]
        # a.py recs (sorted first by file name) should both be selected before b.py
        assert files.count("a.py") >= 2


class TestSelectNextBatch:
    """Tests for the --next-batch selector logic."""

    def _make_rec(
        self,
        rec_id: str,
        *,
        status: str = "open",
        automatable: bool = True,
        risk: str = "low",
        priority: str = "Medium",
        effort: str = "S",
        dependencies: list[str] | None = None,
    ) -> dict:
        rec: dict = {
            "id": rec_id,
            "title": f"Test {rec_id}",
            "status": status,
            "automatable": automatable,
            "risk": risk,
            "priority": priority,
            "effort": effort,
        }
        if dependencies is not None:
            rec["dependencies"] = dependencies
        return rec

    def test_filters_open_automatable_low_risk(self):
        """Only open, automatable, low-risk recs pass."""
        recs = {
            "rec-001": self._make_rec("rec-001"),
            "rec-002": self._make_rec("rec-002", status="closed"),
            "rec-003": self._make_rec("rec-003", automatable=False),
            "rec-004": self._make_rec("rec-004", risk="high"),
        }
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch(limit=10)

        assert result["recommended"] == ["rec-001"]
        assert len(result["skipped"]) == 0

    def test_dependency_blocking_produces_skipped(self):
        """Recs with unclosed deps appear in skipped."""
        recs = {
            "rec-010": self._make_rec("rec-010"),
            "rec-011": self._make_rec(
                "rec-011",
                dependencies=["rec-010"],
            ),
        }
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch(limit=10)

        assert result["recommended"] == ["rec-010"]
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["id"] == "rec-011"
        assert "rec-010" in result["skipped"][0]["reason"]

    def test_closed_dependency_not_blocked(self):
        """Rec with all deps closed passes through."""
        recs = {
            "rec-020": self._make_rec("rec-020", status="closed"),
            "rec-021": self._make_rec(
                "rec-021",
                dependencies=["rec-020"],
            ),
        }
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch(limit=10)

        assert result["recommended"] == ["rec-021"]
        assert len(result["skipped"]) == 0

    def test_priority_then_effort_ordering(self):
        """Sorts by priority first, then effort."""
        recs = {
            "rec-a": self._make_rec("rec-a", priority="Low", effort="XS"),
            "rec-b": self._make_rec("rec-b", priority="High", effort="S"),
            "rec-c": self._make_rec("rec-c", priority="High", effort="XS"),
            "rec-d": self._make_rec("rec-d", priority="Critical", effort="M"),
        }
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch(limit=10)

        assert result["recommended"] == [
            "rec-d",
            "rec-c",
            "rec-b",
            "rec-a",
        ]

    def test_default_limit_is_three(self):
        """Default limit caps recommended at 3."""
        recs = {f"rec-{i:03d}": self._make_rec(f"rec-{i:03d}") for i in range(1, 7)}
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch()

        assert len(result["recommended"]) == 3

    def test_explicit_limit_two(self):
        """Explicit limit=2 preserves Phase 2 behaviour."""
        recs = {f"rec-{i:03d}": self._make_rec(f"rec-{i:03d}") for i in range(1, 7)}
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value=recs,
        ):
            result = select_next_batch(limit=2)

        assert len(result["recommended"]) == 2

    def test_output_shape(self):
        """Payload has exactly recommended and skipped keys."""
        with patch(
            "scripts.executor.jsonl_store.load_all_recommendations",
            return_value={},
        ):
            result = select_next_batch()

        assert set(result.keys()) == {
            "recommended",
            "skipped",
        }
        assert isinstance(result["recommended"], list)
        assert isinstance(result["skipped"], list)

    def test_main_dispatches_next_batch_selector(self):
        """main() routes --next-batch to select_next_batch and prints JSON."""
        payload = {
            "recommended": ["rec-001", "rec-002"],
            "skipped": [{"id": "rec-003", "reason": "dependency rec-001 not closed"}],
        }

        with patch("scripts.execute_recommendation.select_next_batch", return_value=payload) as mock_select:
            with patch(
                "scripts.execute_recommendation.sys.argv",
                ["execute_recommendation", "--next-batch", "--limit", "2"],
            ):
                with patch("builtins.print") as mock_print:
                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 0
        mock_select.assert_called_once_with(limit=2)
        mock_print.assert_called_once_with(json.dumps(payload, indent=2))


class TestLoadCluster:
    """Tests for load_cluster() edge cases."""

    def test_load_cluster_file_missing(self, tmp_path):
        """Returns empty list when findings file does not exist."""
        from scripts.execute_recommendation import load_cluster

        with patch("pathlib.Path.exists", return_value=False):
            result = load_cluster("cluster-999")
        assert result == []

    def test_load_cluster_malformed_json(self, tmp_path):
        """Returns empty list when findings file has invalid JSON lines."""
        from scripts.execute_recommendation import load_cluster

        findings = tmp_path / ".rec-curator-findings.jsonl"
        findings.write_text("not valid json\n", encoding="utf-8")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", return_value=open(findings, encoding="utf-8")):
                result = load_cluster("cluster-001")

        assert result == []

    def test_load_cluster_missing_cluster_id_field(self, tmp_path):
        """Returns empty list when finding has type=cluster but no matching cluster_id."""
        import json

        from scripts.execute_recommendation import load_cluster

        findings = tmp_path / ".rec-curator-findings.jsonl"
        line = json.dumps({"type": "cluster", "cluster_id": "cluster-other", "rec_ids": ["rec-1"]})
        findings.write_text(line + "\n", encoding="utf-8")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", return_value=open(findings, encoding="utf-8")):
                result = load_cluster("cluster-001")

        assert result == []
