from __future__ import annotations

from pathlib import Path

import pytest

from scripts.session import postflight_evidence


def _evidence() -> dict[str, object]:
    return {category: [f"fact for {category}"] for category in postflight_evidence.CATEGORIES}


def test_write_and_render_derive_from_structured_record(tmp_path: Path) -> None:
    evidence = _evidence()
    path = tmp_path / "evidence.json"
    postflight_evidence.write(evidence, path)
    rendered = postflight_evidence.render(evidence)
    assert path.exists()
    assert "Fact For" not in rendered
    assert "fact for guard_candidates" in rendered


def test_missing_category_and_secret_like_content_fail() -> None:
    evidence = _evidence()
    evidence.pop("guard_candidates")
    with pytest.raises(ValueError, match="exactly"):
        postflight_evidence.validate(evidence)
    evidence = _evidence()
    evidence["guard_candidates"] = ["token=not-allowed"]
    with pytest.raises(ValueError, match="secret-like"):
        postflight_evidence.validate(evidence)


def test_unbounded_and_non_list_categories_fail() -> None:
    evidence = _evidence()
    evidence["guard_candidates"] = ["x" * 17_000]
    with pytest.raises(ValueError, match="exceeds"):
        postflight_evidence.validate(evidence)
    evidence = _evidence()
    evidence["guard_candidates"] = "not a list"
    with pytest.raises(ValueError, match="list of strings"):
        postflight_evidence.validate(evidence)
