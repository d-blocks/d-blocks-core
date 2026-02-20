"""
Teradata DDL Table Parser
=========================

Parses Teradata CREATE TABLE DDL scripts to extract structured information
about tables: database name, table name, columns (with data types and
nullability), primary index definitions, secondary index definitions,
statistics definitions, and comments.

This parser handles the Teradata-specific DDL syntax, including:
- SET/MULTISET tables
- FALLBACK/NO FALLBACK
- Column-level and table-level constraints
- PRIMARY INDEX, UNIQUE PRIMARY INDEX
- PARTITION BY clauses
- COLLECT STATISTICS statements
- COMMENT ON statements
- CHARACTER SET specifications
- DEFAULT values, WITH DEFAULT, NOT NULL, NOT CASESPECIFIC
- Various data types including DECIMAL, VARCHAR, TIMESTAMP, DATE, etc.
"""

from __future__ import annotations

import re
from enum import Enum

from attrs import define, field, frozen

from dblocks_core.config.config import logger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@frozen
class ColumnDef:
    """Represents a column definition parsed from a CREATE TABLE statement."""

    name: str
    data_type: str
    nullable: bool = field(default=True)
    default_value: str | None = field(default=None)
    character_set: str | None = field(default=None)
    is_casespecific: bool | None = field(default=None)
    raw: str = field(default="")


@frozen
class IndexDef:
    """Represents an index definition parsed from a CREATE TABLE statement."""

    columns: tuple[str, ...]
    is_unique: bool = field(default=False)
    is_primary: bool = field(default=True)
    index_name: str | None = field(default=None)
    raw: str = field(default="")


@frozen
class ParsedTable:
    """Represents a fully parsed CREATE TABLE DDL statement."""

    database_name: str | None
    table_name: str
    columns: tuple[ColumnDef, ...]
    primary_index: IndexDef | None = field(default=None)
    secondary_indices: tuple[IndexDef, ...] = field(factory=tuple)
    is_set: bool = field(default=True)
    is_multiset: bool = field(default=False)
    fallback: bool | None = field(default=None)
    table_kind: str = field(default="TABLE")  # TABLE | VOLATILE | GLOBAL TEMPORARY
    partition_by: str | None = field(default=None)
    create_ddl: str = field(default="")
    stats_statements: tuple[str, ...] = field(factory=tuple)
    comment_statements: tuple[str, ...] = field(factory=tuple)


# ---------------------------------------------------------------------------
# Teradata data type defaults
# ---------------------------------------------------------------------------

# Default values per Teradata data type family (used when NOT NULL column
# needs to be populated but source has no data).
_TYPE_DEFAULTS: dict[str, str] = {
    "INTEGER": "0",
    "INT": "0",
    "SMALLINT": "0",
    "BIGINT": "0",
    "BYTEINT": "0",
    "FLOAT": "0.0",
    "REAL": "0.0",
    "DOUBLE PRECISION": "0.0",
    "DECIMAL": "0",
    "NUMERIC": "0",
    "NUMBER": "0",
    "DATE": "DATE '1900-01-01'",
    "TIME": "TIME '00:00:00'",
    "TIMESTAMP": "TIMESTAMP '1900-01-01 00:00:00'",
    "CHAR": "''",
    "VARCHAR": "''",
    "CLOB": "''",
    "BYTE": "'00'XB",
    "VARBYTE": "'00'XB",
    "BLOB": "'00'XB",
    "INTERVAL": "INTERVAL '0' DAY",
    "PERIOD": "NULL",  # cannot provide sensible default
    "JSON": "'{}'",
    "XML": "''",
    "ARRAY": "NULL",
    "DATASET": "NULL",
}


def default_for_type(data_type: str) -> str:
    """Return a safe literal default for the given Teradata data type.

    The lookup is done against the base type name (without length/precision
    qualifiers), case-insensitively.

    Args:
        data_type: Full data type string, e.g. ``VARCHAR(100)``,
            ``DECIMAL(18,2)``.

    Returns:
        A string SQL literal that can be used as a default value.
    """

    base = _extract_base_type(data_type)
    return _TYPE_DEFAULTS.get(base, "NULL")


def _extract_base_type(data_type: str) -> str:
    """Extract the base type name from a full data type string.

    For example, ``DECIMAL(18,2)`` becomes ``DECIMAL``,
    ``VARCHAR(100) CHARACTER SET LATIN`` becomes ``VARCHAR``.
    """

    dt = data_type.strip().upper()
    # strip parenthesised part
    paren_idx = dt.find("(")
    if paren_idx != -1:
        dt = dt[:paren_idx].strip()
    # strip trailing qualifiers (CHARACTER SET …, FORMAT …, etc.)
    for kw in ("CHARACTER", "FORMAT", "TITLE", "WITH", "NOT", "COMPRESS"):
        idx = dt.find(f" {kw}")
        if idx != -1:
            dt = dt[:idx].strip()
    return dt


def needs_cast(old_type: str, new_type: str) -> bool:
    """Determine whether an explicit CAST is required when moving data
    from *old_type* to *new_type*.

    Returns ``True`` when the base type names differ (case-insensitive).
    """

    return _extract_base_type(old_type) != _extract_base_type(new_type)


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


_RE_CREATE_TABLE = re.compile(
    r"""
    ^\s*CREATE\s+
    (?P<qualifiers>(?:(?:SET|MULTISET)\s+)?(?:(?:NO\s+)?FALLBACK\s+)?(?:,\s*(?:NO\s+)?(?:BEFORE\s+)?JOURNAL\s*(?:,\s*(?:NO\s+)?(?:DUAL\s+)?(?:AFTER\s+)?JOURNAL\s*)?)?(?:,\s*(?:NO\s+)?CHECKSUM\s*=\s*DEFAULT\s*)?)
    (?P<tablekind>(?:VOLATILE\s+)?(?:GLOBAL\s+TEMPORARY\s+)?)
    TABLE\s+
    (?P<fullname>[^\s(]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RE_COLLECT_STATS = re.compile(
    r"^\s*COLLECT\s+(STATISTICS|STATS)\b",
    re.IGNORECASE,
)

_RE_COMMENT_ON = re.compile(
    r"^\s*COMMENT\s+ON\b",
    re.IGNORECASE,
)


def _split_statements(ddl_text: str) -> list[str]:
    """Split a DDL script into individual statements on ``';'``.

    This is a simplified splitter that is aware of string literals
    and block comments.
    """

    stmts: list[str] = []
    in_string = False
    in_comment = False
    prev = 0

    i = 0
    length = len(ddl_text)
    while i < length:
        ch = ddl_text[i]
        nch = ddl_text[i + 1] if i + 1 < length else ""

        if ch == "'" and not in_comment:
            in_string = not in_string
        elif ch == "/" and nch == "*" and not in_string:
            in_comment = True
            i += 1
        elif ch == "*" and nch == "/" and not in_string:
            in_comment = False
            i += 1
        elif ch == ";" and not in_string and not in_comment:
            stmt = ddl_text[prev : i + 1].strip()
            if stmt and stmt != ";":
                stmts.append(stmt)
            prev = i + 1

        i += 1

    # trailing text
    tail = ddl_text[prev:].strip()
    if tail and tail != ";":
        stmts.append(tail)

    return stmts


def _find_matching_paren(text: str, start: int) -> int:
    """Find the index of the closing parenthesis matching the one at *start*.

    Returns -1 if not found.
    """

    depth = 0
    in_string = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "'" and not in_string:
            in_string = True
            continue
        if ch == "'" and in_string:
            # check for escaped apostrophe
            if i + 1 < len(text) and text[i + 1] == "'":
                continue
            in_string = False
            continue
        if in_string:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _parse_qualified_name(name: str) -> tuple[str | None, str]:
    """Parse ``db.table`` or just ``table`` into (db_name, table_name).

    Handles optional double-quote delimiters.
    """

    parts = name.split(".")
    if len(parts) == 2:
        return _unquote(parts[0]), _unquote(parts[1])
    return None, _unquote(parts[0])


def _unquote(name: str) -> str:
    """Strip surrounding double-quotes from a name."""

    s = name.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _strip_inline_comments(text: str) -> str:
    """Remove single-line (--) comments from text, preserving string literals."""

    result: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_string:
            in_string = True
            result.append(ch)
        elif ch == "'" and in_string:
            in_string = False
            result.append(ch)
        elif ch == "-" and not in_string and i + 1 < len(text) and text[i + 1] == "-":
            # skip to end of line
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            result.append("\n")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# Column parsing
# ---------------------------------------------------------------------------


_RE_NOT_NULL = re.compile(r"\bNOT\s+NULL\b", re.IGNORECASE)
_RE_DEFAULT = re.compile(
    r"\b(?:DEFAULT|WITH\s+DEFAULT)\s+(.+?)(?=\s+(?:NOT|NULL|CHARACTER|FORMAT|TITLE|COMPRESS|CHECK|UNIQUE|PRIMARY|REFERENCES|CONSTRAINT|,|\))\b|$)",
    re.IGNORECASE,
)
_RE_CHARSET = re.compile(
    r"\bCHARACTER\s+SET\s+(\w+)",
    re.IGNORECASE,
)
_RE_CASESPECIFIC = re.compile(r"\b(NOT\s+)?CASESPECIFIC\b", re.IGNORECASE)


def _parse_column_def(raw: str) -> ColumnDef | None:
    """Parse a single column definition string.

    Expected format (simplified)::

        column_name  DATA_TYPE  [attributes...]

    Returns ``None`` if the text looks like a constraint rather than
    a column definition (e.g. ``PRIMARY INDEX ...``).
    """

    text = raw.strip()
    if not text:
        return None

    # skip lines that are constraints, not column defs
    upper = text.upper().lstrip()
    for skip_kw in (
        "PRIMARY", "UNIQUE", "INDEX", "PARTITION", "CHECK",
        "CONSTRAINT", "FOREIGN", "REFERENCES",
    ):
        if upper.startswith(skip_kw):
            return None

    # extract column name -- may be quoted
    if text.startswith('"'):
        end_q = text.index('"', 1)
        col_name = text[1:end_q]
        rest = text[end_q + 1:].strip()
    else:
        parts = text.split(None, 1)
        col_name = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    # data type is next token (may contain parentheses)
    data_type, remainder = _extract_data_type(rest)
    if data_type is None:
        return None

    # nullable
    nullable = not bool(_RE_NOT_NULL.search(remainder or ""))

    # default value
    default_value = None
    m_def = _RE_DEFAULT.search(remainder or "")
    if m_def:
        default_value = m_def.group(1).strip().rstrip(",")

    # character set
    charset = None
    m_cs = _RE_CHARSET.search(remainder or "")
    if m_cs:
        charset = m_cs.group(1)

    # casespecific
    cs = None
    m_csp = _RE_CASESPECIFIC.search(remainder or "")
    if m_csp:
        cs = m_csp.group(1) is None  # True if CASESPECIFIC, False if NOT CASESPECIFIC

    return ColumnDef(
        name=col_name,
        data_type=data_type,
        nullable=nullable,
        default_value=default_value,
        character_set=charset,
        is_casespecific=cs,
        raw=raw.strip(),
    )


def _extract_data_type(text: str) -> tuple[str | None, str]:
    """Extract the data type from the beginning of *text*.

    Returns (data_type, remainder).
    """

    text = text.strip()
    if not text:
        return None, ""

    # multi-word types
    upper = text.upper()
    multi_word_types = [
        "DOUBLE PRECISION",
        "LONG VARCHAR",
        "CHARACTER VARYING",
        "CHAR VARYING",
        "INTERVAL YEAR",
        "INTERVAL MONTH",
        "INTERVAL DAY",
        "INTERVAL HOUR",
        "INTERVAL MINUTE",
        "INTERVAL SECOND",
        "INTERVAL YEAR TO MONTH",
        "INTERVAL DAY TO HOUR",
        "INTERVAL DAY TO MINUTE",
        "INTERVAL DAY TO SECOND",
        "INTERVAL HOUR TO MINUTE",
        "INTERVAL HOUR TO SECOND",
        "INTERVAL MINUTE TO SECOND",
        "PERIOD(DATE)",
        "PERIOD(TIME)",
        "PERIOD(TIMESTAMP)",
    ]
    for mwt in multi_word_types:
        if upper.startswith(mwt):
            dt = text[: len(mwt)]
            rest = text[len(mwt) :].strip()
            # check for parenthesised qualifiers
            if rest.startswith("("):
                end = _find_matching_paren(rest, 0)
                if end != -1:
                    dt += rest[: end + 1]
                    rest = rest[end + 1 :].strip()
            return dt, rest

    # single-word type
    parts = text.split(None, 1)
    dt = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    # type may have parenthesised precision/length
    if rest.startswith("("):
        end = _find_matching_paren(rest, 0)
        if end != -1:
            dt += rest[: end + 1]
            rest = rest[end + 1 :].strip()
    elif "(" in dt:
        # parenthesis attached to type name without space, e.g. VARCHAR(100)
        paren_start = dt.index("(")
        # find closing paren
        combined = dt + " " + rest
        end = _find_matching_paren(combined, paren_start)
        if end != -1:
            dt = combined[: end + 1].strip()
            rest = combined[end + 1 :].strip()

    return dt, rest


# ---------------------------------------------------------------------------
# Index parsing
# ---------------------------------------------------------------------------


_RE_PRIMARY_INDEX = re.compile(
    r"\b(UNIQUE\s+)?PRIMARY\s+INDEX\s*(?:\(\s*(?P<name>[^)]+?)\s*\))?\s*\(",
    re.IGNORECASE,
)


def _parse_primary_index(text: str) -> IndexDef | None:
    """Extract the PRIMARY INDEX definition from the trailing part of
    a CREATE TABLE statement (after the column list).

    Returns ``None`` when no primary index is found.
    """

    m = re.search(
        r"\b(UNIQUE\s+)?PRIMARY\s+INDEX\s*(?:\"([^\"]+)\"\s*)?\(",
        text,
        re.IGNORECASE,
    )
    if not m:
        # try simpler pattern without named index
        m = re.search(
            r"\b(UNIQUE\s+)?PRIMARY\s+INDEX\s*\(",
            text,
            re.IGNORECASE,
        )
    if not m:
        return None

    is_unique = m.group(1) is not None
    idx_name = m.group(2) if (m.lastindex or 0) >= 2 else None

    paren_start = text.index("(", m.start())
    paren_end = _find_matching_paren(text, paren_start)
    if paren_end == -1:
        return None

    cols_text = text[paren_start + 1 : paren_end]
    columns = tuple(c.strip().strip('"') for c in cols_text.split(",") if c.strip())

    return IndexDef(
        columns=columns,
        is_unique=is_unique,
        is_primary=True,
        index_name=idx_name,
        raw=text[m.start() : paren_end + 1].strip(),
    )


# ---------------------------------------------------------------------------
# Top-level parse function
# ---------------------------------------------------------------------------


def parse_table_ddl(ddl_text: str) -> ParsedTable | None:
    """Parse a Teradata table DDL script.

    The input may contain multiple statements (CREATE TABLE, COLLECT
    STATISTICS, COMMENT ON, etc.) separated by semicolons.

    Args:
        ddl_text: The full DDL script text.

    Returns:
        A ``ParsedTable`` instance, or ``None`` if no CREATE TABLE
        statement is found.
    """

    statements = _split_statements(ddl_text)
    if not statements:
        return None

    create_stmt: str | None = None
    stats_stmts: list[str] = []
    comment_stmts: list[str] = []

    for stmt in statements:
        if _RE_CREATE_TABLE.search(stmt):
            create_stmt = stmt
        elif _RE_COLLECT_STATS.match(stmt):
            stats_stmts.append(stmt)
        elif _RE_COMMENT_ON.match(stmt):
            comment_stmts.append(stmt)
        else:
            logger.debug(f"table_parser: unrecognized statement: {stmt[:80]}")

    if create_stmt is None:
        logger.warning("table_parser: no CREATE TABLE statement found")
        return None

    return _parse_create_table(
        create_stmt,
        stats_stmts=stats_stmts,
        comment_stmts=comment_stmts,
    )


def _parse_create_table(
    stmt: str,
    *,
    stats_stmts: list[str] | None = None,
    comment_stmts: list[str] | None = None,
) -> ParsedTable | None:
    """Parse a single CREATE TABLE statement into a ``ParsedTable``."""

    # strip inline comments to simplify parsing
    cleaned = _strip_inline_comments(stmt)

    m = _RE_CREATE_TABLE.search(cleaned)
    if not m:
        return None

    qualifiers = m.group("qualifiers").upper()
    is_set = "MULTISET" not in qualifiers
    is_multiset = "MULTISET" in qualifiers
    fallback = None
    if "NO FALLBACK" in qualifiers:
        fallback = False
    elif "FALLBACK" in qualifiers:
        fallback = True

    tablekind_raw = m.group("tablekind").strip().upper()
    table_kind = "TABLE"
    if "VOLATILE" in tablekind_raw:
        table_kind = "VOLATILE"
    elif "GLOBAL TEMPORARY" in tablekind_raw:
        table_kind = "GLOBAL TEMPORARY"

    full_name = m.group("fullname").strip().rstrip(",")
    db_name, table_name = _parse_qualified_name(full_name)

    # find the column list in parentheses
    paren_start = cleaned.index("(", m.end() - 1) if "(" in cleaned[m.end() - 1:] else -1
    if paren_start == -1:
        # try from beginning of the name
        paren_start = cleaned.find("(", m.start())
    if paren_start == -1:
        logger.warning("table_parser: could not find column list opening parenthesis")
        return None

    paren_end = _find_matching_paren(cleaned, paren_start)
    if paren_end == -1:
        logger.warning("table_parser: could not find matching closing parenthesis")
        return None

    col_block = cleaned[paren_start + 1 : paren_end]

    # split column definitions - need to be careful about nested parens
    col_defs_raw = _split_column_defs(col_block)
    columns: list[ColumnDef] = []
    for cdr in col_defs_raw:
        cd = _parse_column_def(cdr)
        if cd is not None:
            columns.append(cd)

    # after the column list closing paren - index definitions, partition by
    after_cols = cleaned[paren_end + 1 :]
    primary_index = _parse_primary_index(after_cols)

    # partition by
    partition_by = None
    m_part = re.search(r"\bPARTITION\s+BY\b", after_cols, re.IGNORECASE)
    if m_part:
        partition_by = after_cols[m_part.start():].strip().rstrip(";")

    return ParsedTable(
        database_name=db_name,
        table_name=table_name,
        columns=tuple(columns),
        primary_index=primary_index,
        is_set=is_set,
        is_multiset=is_multiset,
        fallback=fallback,
        table_kind=table_kind,
        partition_by=partition_by,
        create_ddl=stmt.strip(),
        stats_statements=tuple(stats_stmts or []),
        comment_statements=tuple(comment_stmts or []),
    )


def _split_column_defs(col_block: str) -> list[str]:
    """Split the column block (text between outer parens) into individual
    column definition strings, respecting nested parentheses.
    """

    defs: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []

    for ch in col_block:
        if ch == "'" and not in_string:
            in_string = True
            current.append(ch)
            continue
        if ch == "'" and in_string:
            in_string = False
            current.append(ch)
            continue
        if in_string:
            current.append(ch)
            continue

        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            defs.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    tail = "".join(current).strip()
    if tail:
        defs.append(tail)

    return defs
