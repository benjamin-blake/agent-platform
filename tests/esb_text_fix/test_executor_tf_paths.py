"""ESB-07 guard (PLAN-esb-text-fix-bundle).

Every executor-prefixed `.tf` path across every T4.x tier_item `files_in_scope` sits under
terraform/personal/, with zero remaining under the retired terraform/ root. Scoped by the
`executor_` BASENAME PREFIX -- deliberate and load-bearing: T4.12's non-executor
terraform/scheduled_agents.tf must REMAIN at the legacy root. An unscoped assertion would fail on
a correctly-implemented tree.
"""

from __future__ import annotations

from tests.esb_text_fix._anchors import load_roadmap


def _t4x_tf_paths(d: dict) -> list[tuple[str, str]]:
    out = []
    for item in d["tier_items"]:
        if not item["id"].startswith("T4."):
            continue
        for f in item.get("files_in_scope") or []:
            path = f.split("#")[0].strip()
            if path.endswith(".tf"):
                out.append((item["id"], path))
    return out


def test_executor_tf_paths_under_terraform_personal():
    d = load_roadmap()
    tf = _t4x_tf_paths(d)
    executor_paths = [(t, p) for t, p in tf if p.rsplit("/", 1)[-1].startswith("executor_")]
    bad = [(t, p) for t, p in executor_paths if not p.startswith("terraform/personal/")]
    assert not bad, f"executor .tf still under the retired root: {bad}"
    assert len(executor_paths) >= 5, executor_paths


def test_t412_scheduled_agents_tf_remains_at_legacy_root():
    d = load_roadmap()
    tf = _t4x_tf_paths(d)
    non_executor = [(t, p) for t, p in tf if not p.rsplit("/", 1)[-1].startswith("executor_")]
    assert (
        "T4.12",
        "terraform/scheduled_agents.tf",
    ) in non_executor, "T4.12 scheduled_agents.tf must remain untouched at the legacy root"


def test_t41_three_files_repointed():
    d = load_roadmap()
    t41 = next(i for i in d["tier_items"] if i["id"] == "T4.1")
    tf_paths = [f.split("#")[0].strip() for f in t41["files_in_scope"] if f.split("#")[0].strip().endswith(".tf")]
    assert len(tf_paths) == 3, tf_paths
    for p in tf_paths:
        assert p.startswith("terraform/personal/"), f"T4.1 .tf path not re-pointed: {p}"
