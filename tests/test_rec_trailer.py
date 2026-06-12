"""Unit tests for scripts/rec_trailer.py."""

from __future__ import annotations

from scripts.rec_trailer import parse_resolves_trailer


class TestParseResolvesTrailer:
    """Tests for parse_resolves_trailer()."""

    # --- happy paths ---

    def test_single_id(self) -> None:
        msg = "feat: fix thing\n\nResolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_multiple_ids_comma_separated(self) -> None:
        msg = "Resolves: rec-2187, rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_multiple_ids_space_separated(self) -> None:
        msg = "Resolves: rec-2187 rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_multiple_ids_mixed_separator(self) -> None:
        msg = "Resolves: rec-100, rec-200 rec-300"
        assert parse_resolves_trailer(msg) == ["rec-100", "rec-200", "rec-300"]

    # --- no trailer ---

    def test_no_trailer_returns_empty(self) -> None:
        msg = "feat: nothing special\n\nThis commit does not resolve anything."
        assert parse_resolves_trailer(msg) == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_resolves_trailer("") == []

    # --- deduplication ---

    def test_dedup_same_id_twice(self) -> None:
        msg = "Resolves: rec-2187, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_dedup_preserves_first_seen_order(self) -> None:
        msg = "Resolves: rec-200, rec-100, rec-200"
        assert parse_resolves_trailer(msg) == ["rec-200", "rec-100"]

    # --- malformed tokens ---

    def test_malformed_token_ignored(self) -> None:
        msg = "Resolves: rec-abc, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_malformed_token_letters_only_ignored(self) -> None:
        msg = "Resolves: recfoo, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_pure_number_not_a_rec_id(self) -> None:
        msg = "Resolves: 2187"
        assert parse_resolves_trailer(msg) == []

    def test_rec_followed_by_empty_string(self) -> None:
        msg = "Resolves: rec-"
        assert parse_resolves_trailer(msg) == []

    # --- case insensitivity on keyword ---

    def test_uppercase_keyword(self) -> None:
        msg = "RESOLVES: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_titlecase_keyword(self) -> None:
        msg = "Resolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_mixed_case_keyword(self) -> None:
        msg = "rEsOlVeS: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    # --- output is always lowercase ---

    def test_uppercase_rec_token_normalized(self) -> None:
        msg = "Resolves: REC-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_mixed_case_rec_token_normalized(self) -> None:
        msg = "Resolves: Rec-2187, REC-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    # --- multiline body ---

    def test_trailer_at_end_of_multiline_commit(self) -> None:
        msg = "feat(scope): summary line\n\nBody paragraph explaining the change.\n\nResolves: rec-2187, rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_non_resolves_trailers_ignored(self) -> None:
        msg = "Fix: something\nSee-also: rec-9999\nResolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    # --- edge cases ---

    def test_resolves_in_body_prose_not_picked_up_as_trailer(self) -> None:
        # "Resolves:" must appear at the START of a line to count as a trailer
        msg = "This change resolves: the old problem. rec-9999"
        # "resolves:" in the middle of a sentence does appear at start of a "line" in MULTILINE
        # Only if it's literally at line start. "resolves" in "This change resolves:" is not.
        result = parse_resolves_trailer(msg)
        # "resolves:" does NOT start the line -- "This change..." does. So no match.
        assert result == []

    def test_multiple_trailer_lines(self) -> None:
        msg = "Resolves: rec-100\nResolves: rec-200"
        assert parse_resolves_trailer(msg) == ["rec-100", "rec-200"]
# VP7 autoclose test marker
