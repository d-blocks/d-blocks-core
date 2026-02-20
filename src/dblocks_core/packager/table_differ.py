"""
Table Differ
=============

Compares two parsed table definitions (old vs new) and produces a
structured diff describing what changed.

This module works with ``ParsedTable`` instances produced by
``dblocks_core.parse.table_parser``.
"""

from __future__ import annotations

from enum import Enum

from attrs import define, field, frozen

from dblocks_core.config.config import logger
from dblocks_core.parse.table_parser import ColumnDef, IndexDef, ParsedTable, needs_cast


# ---------------------------------------------------------------------------
# Change types
# ---------------------------------------------------------------------------


class ColumnChangeKind(Enum):
    """Kinds of change that can happen to a single column."""

    ADDED = "ADDED"
    DROPPED = "DROPPED"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABILITY_CHANGED = "NULLABILITY_CHANGED"
    TYPE_AND_NULLABILITY_CHANGED = "TYPE_AND_NULLABILITY_CHANGED"
    UNCHANGED = "UNCHANGED"


@frozen
class ColumnChange:
    """Describes a change to a single column."""

    kind: ColumnChangeKind
    column_name: str
    old_column: ColumnDef | None = field(default=None)
    new_column: ColumnDef | None = field(default=None)


class TableChangeKind(Enum):
    """Overall characterisation of what changed between two versions."""

    NO_CHANGE = "NO_CHANGE"
    TABLE_STRUCTURE_CHANGED = "TABLE_STRUCTURE_CHANGED"
    NON_STRUCTURAL_CHANGE = "NON_STRUCTURAL_CHANGE"  # stats / comments only


@frozen
class TableDiff:
    """Complete diff between two versions of a table."""

    kind: TableChangeKind
    column_changes: tuple[ColumnChange, ...] = field(factory=tuple)
    index_changed: bool = field(default=False)
    partition_changed: bool = field(default=False)
    stats_changed: bool = field(default=False)
    comments_changed: bool = field(default=False)
    possible_renames: tuple[tuple[str, str], ...] = field(factory=tuple)
    warnings: tuple[str, ...] = field(factory=tuple)


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------


def diff_tables(old: ParsedTable, new: ParsedTable) -> TableDiff:
    """Compare *old* and *new* parsed table definitions.

    Returns a ``TableDiff`` describing all changes.
    """

    warnings: list[str] = []

    # --- columns ---
    old_cols = {c.name.upper(): c for c in old.columns}
    new_cols = {c.name.upper(): c for c in new.columns}

    col_changes: list[ColumnChange] = []

    # columns in both
    for name_up in sorted(set(old_cols) & set(new_cols)):
        oc = old_cols[name_up]
        nc = new_cols[name_up]
        kind = _column_change_kind(oc, nc)
        if kind != ColumnChangeKind.UNCHANGED:
            col_changes.append(
                ColumnChange(kind=kind, column_name=nc.name, old_column=oc, new_column=nc)
            )

    # dropped columns
    dropped = set(old_cols) - set(new_cols)
    for name_up in sorted(dropped):
        col_changes.append(
            ColumnChange(
                kind=ColumnChangeKind.DROPPED,
                column_name=old_cols[name_up].name,
                old_column=old_cols[name_up],
            )
        )

    # added columns
    added = set(new_cols) - set(old_cols)
    for name_up in sorted(added):
        col_changes.append(
            ColumnChange(
                kind=ColumnChangeKind.ADDED,
                column_name=new_cols[name_up].name,
                new_column=new_cols[name_up],
            )
        )

    # possible renames: if we have both drops and adds we warn
    possible_renames: list[tuple[str, str]] = []
    if dropped and added:
        for d in sorted(dropped):
            for a in sorted(added):
                possible_renames.append((old_cols[d].name, new_cols[a].name))
                warnings.append(
                    f"Column '{old_cols[d].name}' was dropped and '{new_cols[a].name}' "
                    f"was added — possibly a rename. Please validate."
                )

    # --- index ---
    index_changed = _index_changed(old.primary_index, new.primary_index)

    # --- partition ---
    partition_changed = (old.partition_by or "").strip().upper() != (
        new.partition_by or ""
    ).strip().upper()

    # --- stats / comments ---
    stats_changed = set(old.stats_statements) != set(new.stats_statements)
    comments_changed = set(old.comment_statements) != set(new.comment_statements)

    # --- classify ---
    structure_changed = (
        len(col_changes) > 0
        or index_changed
        or partition_changed
    )

    if not structure_changed and not stats_changed and not comments_changed:
        kind = TableChangeKind.NO_CHANGE
    elif structure_changed:
        kind = TableChangeKind.TABLE_STRUCTURE_CHANGED
    else:
        kind = TableChangeKind.NON_STRUCTURAL_CHANGE

    return TableDiff(
        kind=kind,
        column_changes=tuple(col_changes),
        index_changed=index_changed,
        partition_changed=partition_changed,
        stats_changed=stats_changed,
        comments_changed=comments_changed,
        possible_renames=tuple(possible_renames),
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _column_change_kind(old: ColumnDef, new: ColumnDef) -> ColumnChangeKind:
    """Determine how a column changed between old and new."""

    type_changed = old.data_type.upper().strip() != new.data_type.upper().strip()
    null_changed = old.nullable != new.nullable

    if type_changed and null_changed:
        return ColumnChangeKind.TYPE_AND_NULLABILITY_CHANGED
    if type_changed:
        return ColumnChangeKind.TYPE_CHANGED
    if null_changed:
        return ColumnChangeKind.NULLABILITY_CHANGED
    return ColumnChangeKind.UNCHANGED


def _index_changed(old: IndexDef | None, new: IndexDef | None) -> bool:
    """Check whether the primary index definition changed."""

    if old is None and new is None:
        return False
    if old is None or new is None:
        return True

    old_cols = tuple(c.upper().strip() for c in old.columns)
    new_cols = tuple(c.upper().strip() for c in new.columns)
    return old_cols != new_cols or old.is_unique != new.is_unique
