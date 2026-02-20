"""
Change Script Generator
========================

Generates Teradata SQL change scripts for tables based on the diff
between old and new DDL definitions.

Two strategies are used:

1. **RENAME-CREATE-INSERT** – when the table structure itself changed
   (columns, primary index, partitioning).  The existing table is renamed
   with a ``_bkp<timestamp>`` suffix, the new DDL is executed, and an
   ``INSERT … SELECT`` is generated to migrate data from the backup.

2. **Non-structural change** – when only statistics or comments changed,
   the change script contains only the affected COLLECT STATISTICS /
   COMMENT ON statements.

For **dropped** tables the generator produces a RENAME with an
``_obsolete<timestamp>`` suffix instead of an immediate DROP.

For dropped non-table objects (views, procedures, …) a plain DROP
statement is generated.
"""

from __future__ import annotations

from datetime import datetime

from dblocks_core.config.config import logger
from dblocks_core.packager.table_differ import (
    ColumnChange,
    ColumnChangeKind,
    TableChangeKind,
    TableDiff,
)
from dblocks_core.parse.table_parser import (
    ColumnDef,
    ParsedTable,
    default_for_type,
    needs_cast,
)


# ---------------------------------------------------------------------------
# Timestamp suffix helper
# ---------------------------------------------------------------------------

_TS_FMT = "%Y%m%d%H%M%S"


def _ts_suffix(prefix: str = "_bkp", ts: datetime | None = None) -> str:
    """Generate a deterministic suffix like ``_bkp20260220143015``."""
    if ts is None:
        ts = datetime.now()
    return f"{prefix}{ts.strftime(_TS_FMT)}"


# ---------------------------------------------------------------------------
# Change script for table structural change (RENAME-CREATE-INSERT)
# ---------------------------------------------------------------------------


def generate_table_change_script(
    old: ParsedTable,
    new: ParsedTable,
    diff: TableDiff,
    *,
    ts: datetime | None = None,
) -> tuple[str, list[str]]:
    """Generate the change script for a table whose structure changed.

    This implements the **RENAME-CREATE-INSERT** strategy:

    1. ``RENAME TABLE <db>.<table> TO <db>.<table>_bkp<ts>;``
    2. The full new CREATE TABLE DDL.
    3. ``INSERT INTO <db>.<table> SELECT … FROM <db>.<table>_bkp<ts>;``

    Column mapping logic during INSERT:

    * Column exists in both old and new, same type → direct copy.
    * Column exists in both, **data type changed** → explicit ``CAST``.
    * Column exists in both, was NULLABLE and now NOT NULL → ``COALESCE``
      with a default value; a warning is emitted.
    * Column exists only in new table **and** it is NOT NULL → supply
      default value based on data type; a warning is emitted.
    * Column exists only in old table while a new column was added →
      warning about possible rename.

    Args:
        old: The parsed old table definition.
        new: The parsed new table definition.
        diff: The ``TableDiff`` between old and new.
        ts: Optional fixed timestamp (for deterministic tests).

    Returns:
        A tuple of ``(script_text, warnings)`` where *script_text* is the
        full SQL change script and *warnings* is a list of human-readable
        warnings.
    """

    suffix = _ts_suffix("_bkp", ts)
    warnings: list[str] = list(diff.warnings)

    db_prefix = f"{new.database_name}." if new.database_name else ""
    table_ref = f"{db_prefix}{new.table_name}"
    backup_ref = f"{db_prefix}{new.table_name}{suffix}"

    lines: list[str] = []

    # --- header ---
    lines.append(f"-- =============================================================")
    lines.append(f"-- Change script for table: {table_ref}")
    lines.append(f"-- Strategy: RENAME-CREATE-INSERT")
    lines.append(f"-- Generated: {(ts or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"-- =============================================================")
    lines.append("")

    # --- step 1: rename ---
    lines.append(f"-- Step 1: Backup existing table via RENAME")
    lines.append(f"RENAME TABLE {table_ref} TO {backup_ref};")
    lines.append("")

    # --- step 2: create new table ---
    lines.append(f"-- Step 2: Create new version of the table")
    create_ddl = new.create_ddl.rstrip().rstrip(";")
    lines.append(f"{create_ddl};")
    lines.append("")

    # --- step 3: insert select ---
    lines.append(f"-- Step 3: Migrate data from backup to new table")
    insert_sql, insert_warnings = _build_insert_select(
        old, new, diff, backup_ref=backup_ref, table_ref=table_ref,
    )
    warnings.extend(insert_warnings)
    lines.append(insert_sql)
    lines.append("")

    # --- stats ---
    if new.stats_statements:
        lines.append(f"-- Step 4: Re-apply statistics")
        for stat in new.stats_statements:
            s = stat.rstrip().rstrip(";")
            lines.append(f"{s};")
        lines.append("")

    # --- comments ---
    if new.comment_statements:
        lines.append(f"-- Step 5: Re-apply comments")
        for cmt in new.comment_statements:
            c = cmt.rstrip().rstrip(";")
            lines.append(f"{c};")
        lines.append("")

    script = "\n".join(lines)
    return script, warnings


def generate_drop_backup_script(
    new: ParsedTable,
    *,
    ts: datetime | None = None,
) -> str:
    """Generate a DROP TABLE statement for the backup table.

    This is meant to be placed into the final step of the package so
    that backups are cleaned up after successful deployment.
    """

    suffix = _ts_suffix("_bkp", ts)
    db_prefix = f"{new.database_name}." if new.database_name else ""
    backup_ref = f"{db_prefix}{new.table_name}{suffix}"

    lines = [
        f"-- Drop backup table: {backup_ref}",
        f"DROP TABLE {backup_ref};",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Change script for non-structural change (stats / comments only)
# ---------------------------------------------------------------------------


def generate_non_structural_change_script(
    old: ParsedTable,
    new: ParsedTable,
    diff: TableDiff,
    *,
    ts: datetime | None = None,
) -> str:
    """Generate script for non-structural changes (statistics / comments).

    When the table structure itself did not change but there are
    differences in COLLECT STATISTICS or COMMENT ON statements, we
    only need to re-execute the changed statements.
    """

    db_prefix = f"{new.database_name}." if new.database_name else ""
    table_ref = f"{db_prefix}{new.table_name}"

    lines: list[str] = []
    lines.append(f"-- =============================================================")
    lines.append(f"-- Non-structural change script for table: {table_ref}")
    lines.append(f"-- Generated: {(ts or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"-- =============================================================")
    lines.append("")

    old_stats = set(old.stats_statements)
    new_stats = set(new.stats_statements)

    # drop removed stats — Teradata does not have DROP STATISTICS per se,
    # we just don't re-collect them, but we note it
    removed_stats = old_stats - new_stats
    if removed_stats:
        lines.append("-- Removed statistics (no longer collected):")
        for rs in sorted(removed_stats):
            lines.append(f"--   {rs.strip()[:80]}...")
        lines.append("")

    # new or changed stats
    added_stats = new_stats - old_stats
    if added_stats:
        lines.append("-- New/changed statistics:")
        for ns in sorted(added_stats):
            s = ns.rstrip().rstrip(";")
            lines.append(f"{s};")
        lines.append("")

    # comments
    old_comments = set(old.comment_statements)
    new_comments = set(new.comment_statements)
    changed_comments = new_comments - old_comments
    if changed_comments:
        lines.append("-- Changed comments:")
        for cc in sorted(changed_comments):
            c = cc.rstrip().rstrip(";")
            lines.append(f"{c};")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Drop / obsolete scripts
# ---------------------------------------------------------------------------


def generate_table_obsolete_script(
    database_name: str | None,
    table_name: str,
    *,
    ts: datetime | None = None,
) -> str:
    """Generate a RENAME script to mark a dropped table as obsolete.

    Instead of dropping the table immediately we rename it with an
    ``_obsolete<timestamp>`` suffix so that data is preserved.
    """

    suffix = _ts_suffix("_obsolete", ts)
    db_prefix = f"{database_name}." if database_name else ""
    table_ref = f"{db_prefix}{table_name}"
    obsolete_ref = f"{db_prefix}{table_name}{suffix}"

    lines = [
        f"-- Mark table as obsolete (dropped from Git): {table_ref}",
        f"RENAME TABLE {table_ref} TO {obsolete_ref};",
    ]
    return "\n".join(lines)


def generate_drop_script(
    database_name: str | None,
    object_name: str,
    object_type: str,
) -> str:
    """Generate a DROP statement for a non-table object.

    Args:
        database_name: Optional database qualifier.
        object_name: The object name.
        object_type: One of ``VIEW``, ``PROCEDURE``, ``MACRO``, etc.
    """

    db_prefix = f"{database_name}." if database_name else ""
    obj_ref = f"{db_prefix}{object_name}"

    lines = [
        f"-- Drop {object_type}: {obj_ref}",
        f"DROP {object_type} {obj_ref};",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# INSERT … SELECT builder
# ---------------------------------------------------------------------------


def _build_insert_select(
    old: ParsedTable,
    new: ParsedTable,
    diff: TableDiff,
    *,
    backup_ref: str,
    table_ref: str,
) -> tuple[str, list[str]]:
    """Build the INSERT INTO … SELECT … FROM statement.

    Returns ``(sql, warnings)``.
    """

    warnings: list[str] = []
    old_cols = {c.name.upper(): c for c in old.columns}
    new_cols_ordered = list(new.columns)

    target_cols: list[str] = []
    select_exprs: list[str] = []

    for nc in new_cols_ordered:
        nc_up = nc.name.upper()
        target_cols.append(f'    "{nc.name}"')

        if nc_up in old_cols:
            oc = old_cols[nc_up]
            expr = _select_expr_for_existing_column(oc, nc, warnings)
            select_exprs.append(f"    {expr}")
        else:
            # new column, not in old table
            expr = _select_expr_for_new_column(nc, warnings)
            select_exprs.append(f"    {expr}")

    insert_sql = (
        f"INSERT INTO {table_ref}\n"
        f"(\n"
        + ",\n".join(target_cols)
        + "\n)\n"
        + f"SELECT\n"
        + ",\n".join(select_exprs)
        + f"\nFROM {backup_ref};"
    )

    return insert_sql, warnings


def _select_expr_for_existing_column(
    old: ColumnDef,
    new: ColumnDef,
    warnings: list[str],
) -> str:
    """Build the SELECT expression for a column that exists in both
    old and new tables.
    """

    col_ref = f'"{old.name}"'
    type_changed = needs_cast(old.data_type, new.data_type)
    became_not_null = old.nullable and not new.nullable

    if type_changed and became_not_null:
        # explicit cast + coalesce
        default = default_for_type(new.data_type)
        expr = f"COALESCE(CAST({col_ref} AS {new.data_type}), {default})"
        warnings.append(
            f"Column '{new.name}': data type changed from {old.data_type} to "
            f"{new.data_type} AND became NOT NULL. "
            f"Default value '{default}' will be used for NULLs. Please validate."
        )
        return expr

    if type_changed:
        expr = f"CAST({col_ref} AS {new.data_type})"
        warnings.append(
            f"Column '{new.name}': data type changed from {old.data_type} to "
            f"{new.data_type}. Explicit CAST applied."
        )
        return expr

    if became_not_null:
        default = default_for_type(new.data_type)
        expr = f"COALESCE({col_ref}, {default})"
        warnings.append(
            f"Column '{new.name}': changed from NULLABLE to NOT NULL. "
            f"Default value '{default}' will be used for existing NULLs. "
            f"Please validate."
        )
        return expr

    return col_ref


def _select_expr_for_new_column(
    new: ColumnDef,
    warnings: list[str],
) -> str:
    """Build the SELECT expression for a column that exists only
    in the new table.
    """

    if not new.nullable:
        default = default_for_type(new.data_type)
        expr = f"CAST({default} AS {new.data_type})"
        warnings.append(
            f"Column '{new.name}': new NOT NULL column. "
            f"Default value '{default}' will be used. Please validate."
        )
        return f"{expr}  /* new NOT NULL column */"
    else:
        return f"CAST(NULL AS {new.data_type})  /* new column */"
