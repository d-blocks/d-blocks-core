"""Tests for table differ and change script generator."""

from datetime import datetime

from dblocks_core.packager.change_script_gen import (
    generate_drop_backup_script,
    generate_drop_script,
    generate_non_structural_change_script,
    generate_table_change_script,
    generate_table_obsolete_script,
)
from dblocks_core.packager.table_differ import (
    ColumnChange,
    ColumnChangeKind,
    TableChangeKind,
    TableDiff,
    diff_tables,
)
from dblocks_core.parse.table_parser import (
    ColumnDef,
    IndexDef,
    ParsedTable,
    parse_table_ddl,
)


# Fixed timestamp for deterministic tests
TS = datetime(2026, 2, 20, 14, 30, 15)


# ---------------------------------------------------------------------------
# diff_tables
# ---------------------------------------------------------------------------


class TestDiffTables:
    def _make_table(self, columns, *, stats=(), comments=(), pi_cols=("id",)):
        pi = IndexDef(columns=pi_cols, is_unique=False, is_primary=True)
        return ParsedTable(
            database_name="db",
            table_name="t",
            columns=tuple(columns),
            primary_index=pi,
            stats_statements=tuple(stats),
            comment_statements=tuple(comments),
            create_ddl="CREATE TABLE db.t (...)",
        )

    def test_no_change(self):
        cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        old = self._make_table(cols)
        new = self._make_table(cols)
        d = diff_tables(old, new)
        assert d.kind == TableChangeKind.NO_CHANGE
        assert len(d.column_changes) == 0

    def test_column_added(self):
        old_cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        new_cols = [
            ColumnDef(name="id", data_type="INTEGER", nullable=False),
            ColumnDef(name="name", data_type="VARCHAR(100)", nullable=True),
        ]
        d = diff_tables(self._make_table(old_cols), self._make_table(new_cols))
        assert d.kind == TableChangeKind.TABLE_STRUCTURE_CHANGED
        added = [c for c in d.column_changes if c.kind == ColumnChangeKind.ADDED]
        assert len(added) == 1
        assert added[0].column_name == "name"

    def test_column_dropped(self):
        old_cols = [
            ColumnDef(name="id", data_type="INTEGER", nullable=False),
            ColumnDef(name="old_col", data_type="VARCHAR(50)", nullable=True),
        ]
        new_cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        d = diff_tables(self._make_table(old_cols), self._make_table(new_cols))
        assert d.kind == TableChangeKind.TABLE_STRUCTURE_CHANGED
        dropped = [c for c in d.column_changes if c.kind == ColumnChangeKind.DROPPED]
        assert len(dropped) == 1
        assert dropped[0].column_name == "old_col"

    def test_column_type_changed(self):
        old_cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        new_cols = [ColumnDef(name="id", data_type="BIGINT", nullable=False)]
        d = diff_tables(self._make_table(old_cols), self._make_table(new_cols))
        assert d.kind == TableChangeKind.TABLE_STRUCTURE_CHANGED
        changed = [c for c in d.column_changes if c.kind == ColumnChangeKind.TYPE_CHANGED]
        assert len(changed) == 1

    def test_nullability_changed(self):
        old_cols = [ColumnDef(name="id", data_type="INTEGER", nullable=True)]
        new_cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        d = diff_tables(self._make_table(old_cols), self._make_table(new_cols))
        assert d.kind == TableChangeKind.TABLE_STRUCTURE_CHANGED
        changed = [
            c for c in d.column_changes
            if c.kind == ColumnChangeKind.NULLABILITY_CHANGED
        ]
        assert len(changed) == 1

    def test_possible_rename(self):
        old_cols = [
            ColumnDef(name="id", data_type="INTEGER", nullable=False),
            ColumnDef(name="old_name", data_type="VARCHAR(100)", nullable=True),
        ]
        new_cols = [
            ColumnDef(name="id", data_type="INTEGER", nullable=False),
            ColumnDef(name="new_name", data_type="VARCHAR(100)", nullable=True),
        ]
        d = diff_tables(self._make_table(old_cols), self._make_table(new_cols))
        assert len(d.possible_renames) == 1
        assert d.possible_renames[0] == ("old_name", "new_name")
        assert len(d.warnings) > 0

    def test_stats_only_change(self):
        cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        old = self._make_table(cols, stats=["COLLECT STATS ON t;"])
        new = self._make_table(cols, stats=["COLLECT STATS ON t;", "COLLECT STATS COLUMN (id) ON t;"])
        d = diff_tables(old, new)
        assert d.kind == TableChangeKind.NON_STRUCTURAL_CHANGE
        assert d.stats_changed is True
        assert len(d.column_changes) == 0

    def test_comments_only_change(self):
        cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        old = self._make_table(cols, comments=[])
        new = self._make_table(cols, comments=["COMMENT ON TABLE t IS 'desc';"])
        d = diff_tables(old, new)
        assert d.kind == TableChangeKind.NON_STRUCTURAL_CHANGE
        assert d.comments_changed is True

    def test_index_changed(self):
        cols = [ColumnDef(name="id", data_type="INTEGER", nullable=False)]
        old = self._make_table(cols, pi_cols=("id",))
        new = self._make_table(cols, pi_cols=("id", "name"))
        d = diff_tables(old, new)
        assert d.kind == TableChangeKind.TABLE_STRUCTURE_CHANGED
        assert d.index_changed is True


# ---------------------------------------------------------------------------
# generate_table_change_script (RENAME-CREATE-INSERT)
# ---------------------------------------------------------------------------


class TestGenerateTableChangeScript:
    def test_basic_structural_change(self):
        old_ddl = """
CREATE MULTISET TABLE db.t (
    id INTEGER NOT NULL,
    name VARCHAR(100)
)
PRIMARY INDEX (id);
"""
        new_ddl = """
CREATE MULTISET TABLE db.t (
    id INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    status CHAR(1) NOT NULL
)
PRIMARY INDEX (id);
"""
        old = parse_table_ddl(old_ddl)
        new = parse_table_ddl(new_ddl)
        diff = diff_tables(old, new)

        script, warnings = generate_table_change_script(old, new, diff, ts=TS)

        # check script contains expected parts
        assert "RENAME TABLE db.t TO db.t_bkp20260220143015;" in script
        assert "CREATE MULTISET TABLE db.t" in script
        assert "INSERT INTO db.t" in script
        assert "FROM db.t_bkp20260220143015;" in script

        # warnings for type change (name VARCHAR(100)->VARCHAR(200))
        # and new NOT NULL column (status)
        assert len(warnings) > 0
        assert any("status" in w for w in warnings)

    def test_coalesce_for_nullable_to_not_null(self):
        old_ddl = """
CREATE MULTISET TABLE db.t (
    id INTEGER NOT NULL,
    val INTEGER
)
PRIMARY INDEX (id);
"""
        new_ddl = """
CREATE MULTISET TABLE db.t (
    id INTEGER NOT NULL,
    val INTEGER NOT NULL
)
PRIMARY INDEX (id);
"""
        old = parse_table_ddl(old_ddl)
        new = parse_table_ddl(new_ddl)
        diff = diff_tables(old, new)

        script, warnings = generate_table_change_script(old, new, diff, ts=TS)
        assert "COALESCE" in script
        assert any("val" in w and "NOT NULL" in w for w in warnings)


# ---------------------------------------------------------------------------
# generate_drop_backup_script
# ---------------------------------------------------------------------------


class TestGenerateDropBackupScript:
    def test_basic(self):
        parsed = parse_table_ddl(
            "CREATE TABLE db.t (id INTEGER) PRIMARY INDEX (id);"
        )
        script = generate_drop_backup_script(parsed, ts=TS)
        assert "DROP TABLE db.t_bkp20260220143015;" in script


# ---------------------------------------------------------------------------
# generate_non_structural_change_script
# ---------------------------------------------------------------------------


class TestGenerateNonStructuralChangeScript:
    def test_stats_change(self):
        old_ddl = """
CREATE MULTISET TABLE db.t (id INTEGER NOT NULL) PRIMARY INDEX (id);

COLLECT STATISTICS COLUMN (id) ON db.t;
"""
        new_ddl = """
CREATE MULTISET TABLE db.t (id INTEGER NOT NULL) PRIMARY INDEX (id);

COLLECT STATISTICS COLUMN (id) ON db.t;
COLLECT STATISTICS COLUMN (PARTITION) ON db.t;
"""
        old = parse_table_ddl(old_ddl)
        new = parse_table_ddl(new_ddl)
        diff = diff_tables(old, new)

        script = generate_non_structural_change_script(old, new, diff, ts=TS)
        assert "PARTITION" in script
        assert "Non-structural change" in script


# ---------------------------------------------------------------------------
# generate_table_obsolete_script
# ---------------------------------------------------------------------------


class TestGenerateTableObsoleteScript:
    def test_basic(self):
        script = generate_table_obsolete_script("db", "old_table", ts=TS)
        assert "RENAME TABLE db.old_table TO db.old_table_obsolete20260220143015;" in script

    def test_no_database(self):
        script = generate_table_obsolete_script(None, "old_table", ts=TS)
        assert "RENAME TABLE old_table TO old_table_obsolete20260220143015;" in script


# ---------------------------------------------------------------------------
# generate_drop_script
# ---------------------------------------------------------------------------


class TestGenerateDropScript:
    def test_drop_view(self):
        script = generate_drop_script("db", "my_view", "VIEW")
        assert "DROP VIEW db.my_view;" in script

    def test_drop_procedure(self):
        script = generate_drop_script("db", "my_proc", "PROCEDURE")
        assert "DROP PROCEDURE db.my_proc;" in script

    def test_drop_no_database(self):
        script = generate_drop_script(None, "my_macro", "MACRO")
        assert "DROP MACRO my_macro;" in script
