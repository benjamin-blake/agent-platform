import pytest
import yaml

from scripts.data_quality_compile import _compile_column_test, load_checks


@pytest.fixture
def sample_yaml(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "test_db",
        "athena_workgroup": "test_wg",
        "tables": {
            "table1": {
                "view_suffix": "_v",
                "row_count": {"min": 10, "severity": "error"},
                "recency": {"column": "ts", "error_after_hours": 24},
                "columns": {
                    "col1": {
                        "tests": [
                            "not_null",
                            "unique",
                            {"accepted_values": {"values": ["A", "B"], "severity": "warn"}},
                            {"relationships": {"to_table": "table2", "to_column": "id"}},
                            {"expression": {"sql": "col1 > 0", "description": "must be positive"}},
                            {"not_null": {"severity": "warn"}},
                            {"unique": {"severity": "error"}},
                        ]
                    }
                },
            }
        },
    }
    f.write_text(yaml.dump(content))
    return f


def test_load_checks(sample_yaml):
    checks, metadata = load_checks(sample_yaml)
    assert metadata["database"] == "test_db"
    assert len(checks) == 9
    # Verify recency check
    recency_check = [c for c in checks if c.test_type == "recency"][0]
    assert "date_diff" in recency_check.sql


def test_load_checks_with_filter(sample_yaml):
    checks, _ = load_checks(sample_yaml, table_filter="table1")
    assert len(checks) == 9
    checks, _ = load_checks(sample_yaml, table_filter="nonexistent")
    assert len(checks) == 0


def test_compile_column_test_invalid():
    assert _compile_column_test("db.t", "t", "c", "unknown") is None
    assert _compile_column_test("db.t", "t", "c", {"unknown": {}}) is None


def test_load_checks_enforced_from_yaml(tmp_path):
    """Loader reads enforced: false from dict-form YAML; bare-string defaults to True."""
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "row_count": {"min": 1, "enforced": False},
                "recency": {"column": "ts", "error_after_hours": 24, "enforced": True},
                "columns": {
                    "col": {
                        "tests": [
                            "not_null",
                            {"accepted_values": {"values": ["A"], "enforced": False}},
                            {"not_null": {"enforced": False}},
                        ]
                    }
                },
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)

    row_count_check = next(c for c in checks if c.test_type == "row_count")
    recency_check = next(c for c in checks if c.test_type == "recency")
    bare_not_null = next(c for c in checks if c.test_type == "not_null" and c.enforced is True)
    accepted_check = next(c for c in checks if c.test_type == "accepted_values")
    dict_not_null = next(c for c in checks if c.test_type == "not_null" and c.enforced is False)

    assert row_count_check.enforced is False
    assert recency_check.enforced is True
    assert bare_not_null.enforced is True
    assert accepted_check.enforced is False
    assert dict_not_null.enforced is False


def test_load_checks_reads_exclude_before(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "columns": {
                    "col": {
                        "tests": [
                            {"not_null": {"enforced": False, "exclude_before": "2026-01-01"}},
                        ]
                    }
                }
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)
    assert len(checks) == 1
    assert checks[0].exclude_before == "2026-01-01"


def test_compile_not_null_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"not_null": {"enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    assert "AND created_timestamp >= DATE('2026-01-01')" in check.sql
    assert check.exclude_before == "2026-01-01"


def test_compile_accepted_values_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"accepted_values": {"values": ["A", "B"], "enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    assert "NOT IN ('A', 'B')" in check.sql
    assert "AND created_timestamp >= DATE('2026-01-01')" in check.sql


def test_compile_unique_with_exclude_before():
    check = _compile_column_test(
        "db.tbl",
        "tbl",
        "col",
        {"unique": {"enforced": False, "exclude_before": "2026-01-01"}},
    )
    assert check is not None
    where_pos = check.sql.index("WHERE created_timestamp")
    group_pos = check.sql.index("GROUP BY")
    assert where_pos < group_pos
    assert "DATE('2026-01-01')" in check.sql


def test_compile_accepted_values_list_form():
    check = _compile_column_test("db.tbl", "tbl", "col", {"accepted_values": ["A", "B", "C"]})
    assert check is not None
    assert "NOT IN ('A', 'B', 'C')" in check.sql
    assert check.enforced is True
    assert check.severity == "error"


def test_compile_relationships_non_dict_returns_none():
    assert _compile_column_test("db.tbl", "tbl", "col", {"relationships": ["invalid"]}) is None


def test_compile_expression_non_dict_returns_none():
    assert _compile_column_test("db.tbl", "tbl", "col", {"expression": "not_a_dict"}) is None


def test_row_count_ignores_exclude_before_in_sql(tmp_path):
    d = tmp_path / "config" / "data_quality"
    d.mkdir(parents=True)
    f = d / "test.yaml"
    content = {
        "database": "db",
        "athena_workgroup": "wg",
        "tables": {
            "tbl": {
                "row_count": {"min": 1, "enforced": True, "exclude_before": "2026-01-01"},
            }
        },
    }
    f.write_text(yaml.dump(content))
    checks, _ = load_checks(f)
    rc = next(c for c in checks if c.test_type == "row_count")
    assert "created_timestamp" not in rc.sql
    assert rc.exclude_before == "2026-01-01"


def test_to_ducklake_sql_rewrites_table_and_regexp():
    import scripts.data_quality_runner as dq

    sql = "SELECT COUNT(*) AS violation FROM agent_platform.ops_recommendations_current WHERE id IS NULL"
    out = dq.to_ducklake_sql(sql, "ops_recommendations", "agent_platform")
    assert "{tbl}" in out and "agent_platform.ops_recommendations" not in out
    out2 = dq.to_ducklake_sql("SELECT 1 WHERE regexp_like(id, '^x')", "ops_decisions", "agent_platform")
    assert "regexp_matches(" in out2 and "regexp_like(" not in out2


def test_build_clause8_checks_generates_uniqueness():
    import yaml

    import scripts.data_quality_runner as dq

    spec = yaml.safe_load(open("config/agent/data_quality/ops.yaml", encoding="utf-8"))
    checks = dq.build_clause8_checks(spec, "agent_platform")
    types_ = {c.test_type for c in checks}
    assert "ulid_history_unique" in types_ and "current_merge_key_unique" in types_
    assert all(c.backend == "ducklake" for c in checks)


def test_build_clause8_checks_table_filter():
    import yaml

    import scripts.data_quality_runner as dq

    spec = yaml.safe_load(open("config/agent/data_quality/ops.yaml", encoding="utf-8"))
    # Recs-first slice: only ops_recommendations is clause-8-checked (decisions deferred to Iceberg).
    checks = dq.build_clause8_checks(spec, "agent_platform", table_filter="ops_recommendations")
    assert {c.table for c in checks} == {"ops_recommendations"}
    # A deferred table filter yields no clause-8 checks (it is not on DuckLake this slice).
    assert dq.build_clause8_checks(spec, "agent_platform", table_filter="ops_decisions") == []


def test_tombstone_check_rewrites_to_ducklake_no_athena():
    """A tombstone check on an ops table rewrites to {tbl} (DuckLake), not the Athena view (High #2)."""
    import scripts.data_quality_runner as dq

    checks = dq.build_tombstone_checks([{"table": "ops_recommendations", "id": "rec-9"}], database="agent_platform")
    assert checks and checks[0].test_type == "tombstone_resurrection"
    rewritten = dq.to_ducklake_sql(checks[0].sql, "ops_recommendations", "agent_platform")
    assert "{tbl}" in rewritten
    assert "agent_platform.ops_recommendations" not in rewritten  # no Athena escape hatch
    assert checks[0].table in dq._OPS_TABLES  # so main() flips it to backend=ducklake
