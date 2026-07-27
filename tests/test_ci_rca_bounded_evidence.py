from __future__ import annotations

import io

from scripts.ci_rca.bounded_evidence import copy_bounded_lines


def test_line_limit_does_not_read_unbounded_tail() -> None:
    source = io.BytesIO(b"one\ntwo\nthree\n")
    destination = io.BytesIO()
    assert copy_bounded_lines(source, destination, max_bytes=100, max_lines=2) == (8, 2, True)
    assert destination.getvalue() == b"one\ntwo\n"
    assert source.tell() == 9


def test_partial_utf8_line_is_not_persisted() -> None:
    source = io.BytesIO("safe\n€uro\n".encode())
    destination = io.BytesIO()
    assert copy_bounded_lines(source, destination, max_bytes=7, max_lines=10) == (5, 1, True)
    assert destination.getvalue() == b"safe\n"


def test_exact_byte_limit_at_eof_is_complete() -> None:
    source = io.BytesIO(b"exact\n")
    destination = io.BytesIO()
    assert copy_bounded_lines(source, destination, max_bytes=6, max_lines=10) == (6, 1, False)
