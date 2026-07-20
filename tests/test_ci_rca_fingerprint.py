"""Unit tests for scripts.ci_rca.fingerprint (ci-rca-identity-lifecycle).

Exercises the REAL fingerprint code path (never mocked): determinism, cross-test discrimination
(anti-masking keystone, rec-2710), junit parse (deepest-in-app-frame double duty: cause grouping
+ anti-masking), message-head normalization, collection-error/non-pytest/mass-collapse special
cases, and the v1->v2 no-collision migration-safety proof.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.ci_rca.fingerprint import (
    collapse_mass_failure,
    compute_fingerprint_v2,
    deepest_in_app_frame,
    error_signature_from_junit,
    error_signature_from_log_tail,
    normalize_message_head,
    signature_for_collection_error,
)


class TestComputeFingerprintV2Deterministic:
    def test_same_inputs_same_hash(self):
        a = compute_fingerprint_v2(
            "ci", "pytest_regression", "AssertionError::scripts.session.preflight::test_load::assert x==y"
        )
        b = compute_fingerprint_v2(
            "ci", "pytest_regression", "AssertionError::scripts.session.preflight::test_load::assert x==y"
        )
        assert a == b
        assert len(a) == 64
        int(a, 16)  # valid hex

    def test_invariant_to_nothing_but_the_three_declared_inputs(self):
        """No hidden volatile state (run_id/timestamp) leaks into the hash -- same three
        logical inputs always produce the identical fingerprint, called from different scopes."""
        calls = [compute_fingerprint_v2("ci", "pytest_regression", "AssertionError::a::b::c") for _ in range(5)]
        assert len(set(calls)) == 1


class TestComputeFingerprintV2Discriminates:
    """Anti-masking keystone (rec-2710): two DISTINCT failing tests must never share a fingerprint."""

    def test_distinct_error_signatures_distinct_fingerprints(self):
        a = compute_fingerprint_v2("ci", "pytest_regression", "AssertionError::tests.test_a::test_a::head")
        b = compute_fingerprint_v2("ci", "pytest_regression", "AssertionError::tests.test_b::test_b::head")
        assert a != b

    def test_distinct_failure_category_distinct_fingerprint(self):
        a = compute_fingerprint_v2("ci", "sloc_violation", "sig")
        b = compute_fingerprint_v2("ci", "iam_gap", "sig")
        assert a != b

    def test_distinct_workflow_slug_distinct_fingerprint(self):
        a = compute_fingerprint_v2("ci", "pytest_regression", "sig")
        b = compute_fingerprint_v2("main_canary", "pytest_regression", "sig")
        assert a != b


class TestCauseGroupingDeepestInAppFrame:
    """VP3: one infra error raised from a shared src/ helper groups across distinct tests --
    the deepest-in-app-frame resolves to the shared helper, not the two different test functions."""

    def _traceback(self, test_file: str, test_func: str) -> str:
        return textwrap.dedent(
            f"""\
            Traceback (most recent call last):
              File "/home/user/agent-platform/{test_file}", line 10, in {test_func}
                helper()
              File "/home/user/agent-platform/src/common/helper.py", line 42, in helper
                raise RuntimeError("boom")
            RuntimeError: boom
            """
        )

    def test_cause_grouping_shared_helper_same_frame_across_tests(self):
        frame_a = deepest_in_app_frame(self._traceback("tests/test_a.py", "test_a"))
        frame_b = deepest_in_app_frame(self._traceback("tests/test_b.py", "test_b"))
        assert frame_a == frame_b == "src.common.helper::helper"

    def test_deepest_in_app_frame_for_assertion_is_the_test_function(self):
        """An assertion failure's deepest frame IS the test function -- distinct tests never
        collide (the anti-masking property, expressed at the frame-resolution level)."""
        tb = textwrap.dedent(
            """\
            Traceback (most recent call last):
              File "/home/user/agent-platform/tests/test_foo.py", line 10, in test_load
                assert x == y
            AssertionError: assert 1 == 2
            """
        )
        assert deepest_in_app_frame(tb) == "tests.test_foo::test_load"

    def test_excludes_site_packages_and_conftest(self):
        tb = textwrap.dedent(
            """\
            Traceback (most recent call last):
              File "/home/user/agent-platform/tests/test_foo.py", line 10, in test_load
                do_thing()
              File "/home/user/agent-platform/tests/conftest.py", line 5, in do_thing
                lib_call()
              File "/usr/lib/python3.12/site-packages/somelib/core.py", line 99, in lib_call
                raise ValueError("bad")
            ValueError: bad
            """
        )
        assert deepest_in_app_frame(tb) == "tests.test_foo::test_load"

    def test_no_parseable_frame_returns_none(self):
        assert deepest_in_app_frame("no traceback here at all") is None

    def test_ci_runner_absolute_path_not_matching_local_root_still_resolves(self):
        """A GitHub-hosted runner path (/home/runner/work/...) never matches a local repo_root
        string -- the known-top-level-dir anchor (src/scripts/tests) must still resolve it."""
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/home/runner/work/agent-platform/agent-platform/scripts/session/preflight.py", '
            "line 5, in run\n"
            "    raise RuntimeError('x')\n"
            "RuntimeError: x\n"
        )
        assert deepest_in_app_frame(tb) == "scripts.session.preflight::run"

    def test_path_under_explicit_repo_root_prefix_stripped(self, tmp_path: Path):
        """When the traceback path literally starts with the (injected) repo_root string, the
        prefix-strip branch fires directly rather than falling through to the anchor search."""
        tb = (
            "Traceback (most recent call last):\n"
            f'  File "{tmp_path}/scripts/foo.py", line 5, in bar\n'
            "    raise RuntimeError('x')\n"
            "RuntimeError: x\n"
        )
        assert deepest_in_app_frame(tb, repo_root=tmp_path) == "scripts.foo::bar"


class TestNormalizeMessageHead:
    def test_scrubs_timestamp(self):
        assert "<ts>" in normalize_message_head("failed at 2026-07-17T10:00:00Z during setup")

    def test_scrubs_uuid(self):
        assert "<uuid>" in normalize_message_head("request 123e4567-e89b-12d3-a456-426614174000 failed")

    def test_scrubs_long_hex(self):
        assert "<hex>" in normalize_message_head("commit deadbeefcafe1234 failed")

    def test_scrubs_path(self):
        assert "<path>" in normalize_message_head("error near /home/user/agent-platform/foo.py")

    def test_scrubs_large_int(self):
        assert "<n>" in normalize_message_head("run 123456 failed")

    def test_keeps_short_quoted_identifier(self):
        normalized = normalize_message_head("assert 1 == 2")
        assert normalized == "assert 1 == 2"

    def test_takes_first_line_only(self):
        normalized = normalize_message_head("first line\nsecond line\nthird line")
        assert normalized == "first line"

    def test_empty_message_yields_empty_string(self):
        assert normalize_message_head("") == ""
        assert normalize_message_head("   ") == ""

    def test_collapses_whitespace(self):
        assert normalize_message_head("a    b\tc") == "a b c"

    def test_truncates_to_300_chars(self):
        long_msg = "x" * 500
        assert len(normalize_message_head(long_msg)) == 300


class TestErrorSignatureFromJunit:
    """Cause-grouping + anti-masking via the REAL junit XML parse path."""

    def _write_junit(self, tmp_path: Path) -> Path:
        junit_xml = textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
              <testsuite name="pytest" errors="0" failures="3" skipped="0" tests="5" time="1.0">
                <testcase classname="tests.test_a" name="test_a" file="tests/test_a.py" line="5" time="0.01">
                  <failure message="AssertionError: assert 1 == 2" type="AssertionError">Traceback (most recent call last):
              File "tests/test_a.py", line 10, in test_a
                assert 1 == 2
            AssertionError: assert 1 == 2
            </failure>
                </testcase>
                <testcase classname="tests.test_b" name="test_b" file="tests/test_b.py" line="5" time="0.01">
                  <failure message="RuntimeError: boom" type="RuntimeError">Traceback (most recent call last):
              File "tests/test_b.py", line 20, in test_b
                helper()
              File "src/common/helper.py", line 42, in helper
                raise RuntimeError("boom")
            RuntimeError: boom
            </failure>
                </testcase>
                <testcase classname="tests.test_c" name="test_c" file="tests/test_c.py" line="5" time="0.01">
                  <failure message="RuntimeError: boom" type="RuntimeError">Traceback (most recent call last):
              File "tests/test_c.py", line 30, in test_c
                helper()
              File "src/common/helper.py", line 42, in helper
                raise RuntimeError("boom")
            RuntimeError: boom
            </failure>
                </testcase>
                <testcase classname="tests.test_pass" name="test_pass" file="tests/test_pass.py" line="1" time="0.01"/>
              </testsuite>
            </testsuites>
            """
        )
        p = tmp_path / "junit.xml"
        p.write_text(junit_xml)
        return p

    def test_distinct_tests_distinct_groups(self, tmp_path: Path):
        groups = error_signature_from_junit(self._write_junit(tmp_path), repo_root=tmp_path.parent)
        assert len(groups) == 2

    def test_shared_cause_groups_together(self, tmp_path: Path):
        groups = error_signature_from_junit(self._write_junit(tmp_path), repo_root=tmp_path.parent)
        by_nodeid = {n: sig for sig, nodeids in groups for n in nodeids}
        assert by_nodeid["tests/test_b.py::test_b"] == by_nodeid["tests/test_c.py::test_c"]
        assert by_nodeid["tests/test_a.py::test_a"] != by_nodeid["tests/test_b.py::test_b"]

    def test_passing_testcase_excluded(self, tmp_path: Path):
        groups = error_signature_from_junit(self._write_junit(tmp_path), repo_root=tmp_path.parent)
        all_nodeids = {n for _, nodeids in groups for n in nodeids}
        assert "tests/test_pass.py::test_pass" not in all_nodeids

    def test_missing_file_raises(self, tmp_path: Path):
        import pytest

        with pytest.raises(Exception):  # noqa: B017 -- ET.parse raises OSError/ParseError, both fine
            error_signature_from_junit(tmp_path / "nonexistent.xml")

    def test_error_element_also_parsed(self, tmp_path: Path):
        """A <error> (e.g. a fixture setup failure) is parsed the same as <failure>."""
        junit_xml = textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
              <testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="1.0">
                <testcase classname="tests.test_d" name="test_d" file="tests/test_d.py" line="1" time="0.01">
                  <error message="ValueError: setup failed" type="ValueError">Traceback (most recent call last):
              File "tests/test_d.py", line 5, in test_d
                setup()
            ValueError: setup failed
            </error>
                </testcase>
              </testsuite>
            </testsuites>
            """
        )
        p = tmp_path / "junit.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path.parent)
        assert len(groups) == 1
        assert groups[0][1] == ["tests/test_d.py::test_d"]

    def test_no_file_attribute_falls_back_to_classname(self, tmp_path: Path):
        """A testcase with no `file` attribute (an older pytest / junit_family variant) derives
        its nodeid from `classname` instead."""
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite>'
            '<testcase classname="tests.test_e" name="test_e">'
            '<failure message="AssertionError: x" type="AssertionError">'
            "Traceback (most recent call last):\n"
            '  File "tests/test_e.py", line 3, in test_e\n'
            "    assert False\n"
            "AssertionError: x\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        p = tmp_path / "j.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path)
        assert groups[0][1] == ["tests/test_e.py::test_e"]

    def test_no_message_attribute_falls_back_to_text_last_line(self, tmp_path: Path):
        """No `message` attribute at all -- the message is recovered from the LAST line of the
        element's own text (the exception line at the bottom of the traceback)."""
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite>'
            '<testcase classname="tests.test_f" name="test_f" file="tests/test_f.py">'
            '<failure type="ValueError">Traceback (most recent call last):\n'
            '  File "tests/test_f.py", line 3, in test_f\n'
            "    raise ValueError('boom')\n"
            "ValueError: boom from text\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        p = tmp_path / "j.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path)
        assert "boom from text" in groups[0][0]

    def test_no_type_attribute_infers_exception_type_from_message(self, tmp_path: Path):
        """No `type` attribute -- exception_type is inferred from the message's `Type: msg` shape."""
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite>'
            '<testcase classname="tests.test_g" name="test_g" file="tests/test_g.py">'
            '<failure message="CustomError: something went wrong">'
            "Traceback (most recent call last):\n"
            '  File "tests/test_g.py", line 3, in test_g\n'
            "    raise CustomError\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        p = tmp_path / "j.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path)
        assert groups[0][0].startswith("CustomError::")

    def test_no_type_and_no_colon_in_message_yields_unknown_error(self, tmp_path: Path):
        """No `type` attribute and a message with no ':' separator -- exc_type falls back to
        the UnknownError sentinel rather than raising or mis-parsing."""
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite>'
            '<testcase classname="tests.test_h" name="test_h" file="tests/test_h.py">'
            '<failure message="something broke with no colon separator">'
            "Traceback (most recent call last):\n"
            '  File "tests/test_h.py", line 3, in test_h\n'
            "    fail()\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        p = tmp_path / "j.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path)
        assert groups[0][0].startswith("UnknownError::")


class TestCollectionErrorSpecialCase:
    """VP4 selector target (`-k "collection_error"`)."""

    def test_collection_error_keys_on_module_path(self):
        sig = signature_for_collection_error("tests/test_broken.py")
        assert sig == "collection_error::tests/test_broken.py"

    def test_collection_error_distinct_module_paths_distinct_signatures(self):
        a = signature_for_collection_error("tests/test_x.py")
        b = signature_for_collection_error("tests/test_y.py")
        assert a != b


class TestNonPytestFallback:
    """VP4 selector target (`-k "non_pytest"`)."""

    def test_non_pytest_terraform_apply_sandbox_prefers_error_line(self):
        log = "Terraform will perform the following actions:\nError: Provider produced inconsistent result\n"
        sig = error_signature_from_log_tail(log, tool="terraform-apply-sandbox")
        assert sig.startswith("terraform-apply-sandbox::")
        assert "Provider produced inconsistent result" in sig

    def test_non_pytest_generic_tool_uses_last_line(self):
        log = "some noise\nfoo.py:10:1: E501 line too long\n"
        sig = error_signature_from_log_tail(log, tool="ruff")
        assert sig == "ruff::foo.py:10:1: E501 line too long"

    def test_non_pytest_empty_log_yields_placeholder(self):
        sig = error_signature_from_log_tail("", tool="mypy")
        assert sig == "mypy::<empty>"

    def test_non_pytest_distinct_tools_distinct_signatures_same_log(self):
        log = "Error: something broke\n"
        a = error_signature_from_log_tail(log, tool="tool_a")
        b = error_signature_from_log_tail(log, tool="tool_b")
        assert a != b


class TestMassFailureCollapse:
    """VP4 selector target (`-k "mass_collapse"`)."""

    def test_mass_collapse_below_threshold_returns_none(self):
        assert collapse_mass_failure(["a", "b", "c"], threshold=5) is None

    def test_mass_collapse_above_threshold_collapses(self):
        sigs = [f"sig{i}" for i in range(10)]
        result = collapse_mass_failure(sigs, threshold=5)
        assert result is not None
        assert result.startswith("mass_failure::10_signatures::")

    def test_mass_collapse_deterministic_across_reordering(self):
        sigs = [f"sig{i}" for i in range(10)]
        reordered = list(reversed(sigs))
        assert collapse_mass_failure(sigs, threshold=5) == collapse_mass_failure(reordered, threshold=5)

    def test_mass_collapse_duplicate_signatures_counted_once(self):
        sigs = ["a", "a", "a", "b", "b", "c", "d", "e", "f"]
        # 6 distinct (a,b,c,d,e,f) > threshold=5
        result = collapse_mass_failure(sigs, threshold=5)
        assert result is not None
        assert "6_signatures" in result

    def test_mass_collapse_exactly_at_threshold_does_not_collapse(self):
        sigs = [f"sig{i}" for i in range(5)]
        assert collapse_mass_failure(sigs, threshold=5) is None


class TestV1V2NoCollision:
    """One-time migration-safety proof (VP5, waived from standing graduation -- the ongoing
    salt-in-payload property is guarded by the graduated determinism check instead): a
    representative corpus of v1-style keys must never collide with v2 fingerprints for the
    corresponding logical failures, proving the "v2" salt keeps the two keyspaces disjoint."""

    def _v1_fingerprint(self, workflow_slug: str, failed_check: str, failure_category: str) -> str:
        import hashlib

        payload = "\0".join((workflow_slug, failed_check, failure_category))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def test_v1_v2_no_collision_representative_corpus(self):
        cases = [
            ("ci", "Unit tests + coverage", "sloc_violation"),
            ("ci", "Unit tests + coverage", "code_regression"),
            ("main_canary", "validate_sloc_limits", "sloc_violation"),
            ("terraform-apply-sandbox", "terraform_error", "environment"),
        ]
        v1_hashes = {self._v1_fingerprint(*c) for c in cases}
        v2_hashes = {compute_fingerprint_v2(slug, cat, f"AssertionError::{check}::head") for slug, check, cat in cases}
        assert v1_hashes.isdisjoint(v2_hashes)

    def test_v2_salt_is_in_hashed_payload(self):
        """Directly proves the "v2" literal changes the hash vs a payload without it."""
        import hashlib

        with_salt = compute_fingerprint_v2("ci", "cat", "sig")
        without_salt = hashlib.sha256("\0".join(("ci", "cat", "sig")).encode("utf-8")).hexdigest()
        assert with_salt != without_salt


class TestBuildErrorSignatureFormat:
    """VP1/VP2's own example strings prove the "{exc}::{module}::{func}::{msg}" shape end-to-end
    via junit parsing -- documented here as a direct format check independent of the parse path."""

    def test_error_signature_matches_documented_format(self, tmp_path: Path):
        junit_xml = (
            '<?xml version="1.0"?><testsuites><testsuite><testcase classname="scripts.session.preflight" '
            'name="test_load" file="scripts/session/preflight.py" line="1">'
            '<failure message="AssertionError: assert x==y" type="AssertionError">'
            "Traceback (most recent call last):\n"
            '  File "scripts/session/preflight.py", line 10, in test_load\n'
            "    assert x == y\n"
            "AssertionError: assert x==y\n"
            "</failure></testcase></testsuite></testsuites>"
        )
        p = tmp_path / "j.xml"
        p.write_text(junit_xml)
        groups = error_signature_from_junit(p, repo_root=tmp_path)
        sig = groups[0][0]
        assert sig == "AssertionError::scripts.session.preflight::test_load::assert x==y"
        fp = compute_fingerprint_v2("ci", "pytest_regression", sig)
        assert len(fp) == 64
