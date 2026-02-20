"""Tests for Teradata DDL table parser."""

from dblocks_core.parse.table_parser import (
    ColumnDef,
    IndexDef,
    ParsedTable,
    default_for_type,
    needs_cast,
    parse_table_ddl,
    _extract_base_type,
    _parse_qualified_name,
    _split_statements,
)


# ---------------------------------------------------------------------------
# _extract_base_type
# ---------------------------------------------------------------------------


class TestExtractBaseType:
    def test_simple(self):
        assert _extract_base_type("INTEGER") == "INTEGER"

    def test_with_precision(self):
        assert _extract_base_type("DECIMAL(18,2)") == "DECIMAL"

    def test_varchar_with_length(self):
        assert _extract_base_type("VARCHAR(100)") == "VARCHAR"

    def test_with_character_set(self):
        assert _extract_base_type("VARCHAR(50) CHARACTER SET LATIN") == "VARCHAR"

    def test_timestamp_with_precision(self):
        assert _extract_base_type("TIMESTAMP(6)") == "TIMESTAMP"


# ---------------------------------------------------------------------------
# needs_cast
# ---------------------------------------------------------------------------


class TestNeedsCast:
    def test_same_type(self):
        assert not needs_cast("INTEGER", "INTEGER")

    def test_same_base_different_precision(self):
        assert not needs_cast("DECIMAL(10,2)", "DECIMAL(18,4)")

    def test_different_types(self):
        assert needs_cast("INTEGER", "VARCHAR(20)")

    def test_varchar_to_char(self):
        assert needs_cast("VARCHAR(100)", "CHAR(100)")


# ---------------------------------------------------------------------------
# default_for_type
# ---------------------------------------------------------------------------


class TestDefaultForType:
    def test_integer(self):
        assert default_for_type("INTEGER") == "0"

    def test_decimal_with_precision(self):
        assert default_for_type("DECIMAL(18,2)") == "0"

    def test_varchar(self):
        assert default_for_type("VARCHAR(100)") == "''"

    def test_date(self):
        assert default_for_type("DATE") == "DATE '1900-01-01'"

    def test_timestamp(self):
        assert default_for_type("TIMESTAMP(6)") == "TIMESTAMP '1900-01-01 00:00:00'"

    def test_unknown(self):
        assert default_for_type("SOME_EXOTIC_TYPE") == "NULL"


# ---------------------------------------------------------------------------
# _parse_qualified_name
# ---------------------------------------------------------------------------


class TestParseQualifiedName:
    def test_qualified(self):
        db, name = _parse_qualified_name("mydb.my_table")
        assert db == "mydb"
        assert name == "my_table"

    def test_unqualified(self):
        db, name = _parse_qualified_name("my_table")
        assert db is None
        assert name == "my_table"

    def test_quoted(self):
        db, name = _parse_qualified_name('"MyDB"."My Table"')
        assert db == "MyDB"
        assert name == "My Table"


# ---------------------------------------------------------------------------
# _split_statements
# ---------------------------------------------------------------------------


class TestSplitStatements:
    def test_simple(self):
        stmts = _split_statements("SELECT 1; SELECT 2;")
        assert len(stmts) == 2

    def test_string_with_semicolon(self):
        stmts = _split_statements("SELECT 'a;b'; SELECT 2;")
        assert len(stmts) == 2
        assert "a;b" in stmts[0]

    def test_comment_with_semicolon(self):
        stmts = _split_statements("/* comment; */ SELECT 1;")
        assert len(stmts) == 1

    def test_trailing_text(self):
        stmts = _split_statements("SELECT 1; SELECT 2")
        assert len(stmts) == 2


# ---------------------------------------------------------------------------
# parse_table_ddl
# ---------------------------------------------------------------------------


class TestParseTableDDL:
    def test_simple_table(self):
        ddl = """
CREATE MULTISET TABLE mydb.my_table ,FALLBACK ,
    NO BEFORE JOURNAL,
    NO AFTER JOURNAL,
    CHECKSUM = DEFAULT
(
    id INTEGER NOT NULL,
    name VARCHAR(100) CHARACTER SET LATIN NOT CASESPECIFIC,
    amount DECIMAL(18,2),
    created_dt TIMESTAMP(6)
)
PRIMARY INDEX (id);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert parsed.database_name == "mydb"
        assert parsed.table_name == "my_table"
        assert parsed.is_multiset is True
        assert parsed.is_set is False
        assert len(parsed.columns) == 4

        # check columns
        col_id = parsed.columns[0]
        assert col_id.name == "id"
        assert col_id.data_type.upper().startswith("INTEGER")
        assert col_id.nullable is False

        col_name = parsed.columns[1]
        assert col_name.name == "name"
        assert "VARCHAR" in col_name.data_type.upper()
        assert col_name.nullable is True

        col_amount = parsed.columns[2]
        assert col_amount.name == "amount"
        assert "DECIMAL" in col_amount.data_type.upper()
        assert col_amount.nullable is True

        # primary index
        assert parsed.primary_index is not None
        assert "id" in [c.lower() for c in parsed.primary_index.columns]

    def test_set_table(self):
        ddl = """
CREATE SET TABLE mydb.users ,NO FALLBACK
(
    user_id INTEGER NOT NULL,
    username VARCHAR(50) NOT NULL
)
UNIQUE PRIMARY INDEX (user_id);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert parsed.is_set is True
        assert parsed.is_multiset is False
        assert parsed.primary_index is not None
        assert parsed.primary_index.is_unique is True

    def test_table_with_stats(self):
        ddl = """
CREATE MULTISET TABLE mydb.sales (
    sale_id INTEGER NOT NULL,
    sale_date DATE NOT NULL
)
PRIMARY INDEX (sale_id);

COLLECT STATISTICS COLUMN (sale_id) ON mydb.sales;

COLLECT STATISTICS COLUMN (sale_date) ON mydb.sales;
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert len(parsed.stats_statements) == 2

    def test_table_with_comments(self):
        ddl = """
CREATE MULTISET TABLE mydb.orders (
    order_id INTEGER NOT NULL
)
PRIMARY INDEX (order_id);

COMMENT ON TABLE mydb.orders IS 'Orders table';

COMMENT ON COLUMN mydb.orders.order_id IS 'Primary key';
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert len(parsed.comment_statements) == 2

    def test_no_create_table(self):
        ddl = "SELECT 1;"
        parsed = parse_table_ddl(ddl)
        assert parsed is None

    def test_table_without_database(self):
        ddl = """
CREATE MULTISET TABLE my_table (
    col1 INTEGER
)
PRIMARY INDEX (col1);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert parsed.database_name is None
        assert parsed.table_name == "my_table"

    def test_column_with_default(self):
        ddl = """
CREATE MULTISET TABLE mydb.t (
    status CHAR(1) DEFAULT 'A' NOT NULL,
    counter INTEGER DEFAULT 0
)
PRIMARY INDEX (status);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert len(parsed.columns) == 2
        col_status = parsed.columns[0]
        assert col_status.nullable is False

    def test_table_with_partition_by(self):
        ddl = """
CREATE MULTISET TABLE mydb.partitioned_t (
    id INTEGER NOT NULL,
    dt DATE NOT NULL
)
PRIMARY INDEX (id)
PARTITION BY RANGE_N(dt BETWEEN DATE '2020-01-01'
    AND DATE '2030-12-31' EACH INTERVAL '1' MONTH);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert parsed.partition_by is not None
        assert "PARTITION BY" in parsed.partition_by.upper()

    def test_multiword_data_types(self):
        ddl = """
CREATE MULTISET TABLE mydb.t (
    col1 DOUBLE PRECISION,
    col2 CHAR VARYING(100)
)
PRIMARY INDEX (col1);
"""
        parsed = parse_table_ddl(ddl)
        assert parsed is not None
        assert len(parsed.columns) == 2
