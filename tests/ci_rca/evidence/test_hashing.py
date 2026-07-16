"""canonical-json + sha256 helpers concern: tests/ci_rca/evidence/test_hashing.py (rec-2709 Wave 10).

Split from the former tests/test_ci_rca_evidence.py monolith: TestCanonicalJson, TestSha256Of. No
fixtures/heavy deps.
"""

from scripts.ci_rca.evidence import _canonical_json, _sha256_of


class TestCanonicalJson:
    def test_sort_keys(self):
        obj = {"b": 2, "a": 1}
        result = _canonical_json(obj)
        assert result == b'{"a":1,"b":2}'

    def test_no_spaces(self):
        obj = {"key": "val"}
        assert b" " not in _canonical_json(obj)

    def test_ensure_ascii(self):
        obj = {"k": "café"}
        result = _canonical_json(obj)
        assert b"\\u" in result

    def test_stability(self):
        obj = {"z": 3, "a": 1, "m": 2}
        assert _canonical_json(obj) == _canonical_json(obj)


class TestSha256Of:
    def test_excludes_sha256_field(self):
        obj = {"a": 1, "sha256": "xyz"}
        sha = _sha256_of(obj)
        obj2 = {"a": 1}
        assert sha == _sha256_of(obj2)

    def test_stability(self):
        obj = {"b": 2, "a": 1}
        assert _sha256_of(obj) == _sha256_of(obj)

    def test_hash_length(self):
        assert len(_sha256_of({"k": "v"})) == 64
