from __future__ import annotations

from datetime import datetime
from typing import Sequence

from attrs import define, field

from dblocks_core.model import global_converter  # noqa: F401

DATABASE = "DATABASE"
TABLE = "TABLE"
VIEW = "VIEW"
PROCEDURE = "PROCEDURE"
COLUMN = "COLUMN"
JOIN_INDEX = "JOIN INDEX"
INDEX = "INDEX"
MACRO = "MACRO"
TRIGGER = "TRIGGER"
FUNCTION = "FUNCTION"
TYPE = "TYPE"
AUTHORIZATION = "AUTHORIZATION"

TERADATA = "teradata"

DATABASE_LOG_LEVEL = 15

# typoes of objects dbe can manage
MANAGED_TYPES = [
    DATABASE,
    TABLE,
    VIEW,
    PROCEDURE,
    JOIN_INDEX,
    INDEX,
    TRIGGER,
    FUNCTION,
]

# types of object dbe can deploy
GENERIC_SQL = "SQL"
GENERIC_BTEQ = "BTEQ"
DEPLOYABLE_TYPES = [*MANAGED_TYPES, GENERIC_SQL, GENERIC_BTEQ]

ENV_PLACEHOLDER = "{{env}}"


# objects used as ObjectDetails MUST provide ddl_statement!
# reasoning: used by tagger
@define
class ColumnDescription:
    column_name: str
    column_comment: str | None = field(default=None)
    ddl_statement: str | None = field(default=None)
    data_type: str | None = field(default=None)
    is_column_description: bool = field(default=True)


# objects used as ObjectDetails MUST provide ddl_statement!
# reasoning: used by tagger
@define
class TableStatistic:
    ddl_statement: str
    is_table_stats: bool = field(default=True)


# objects used as ObjectDetails MUST provide ddl_statement!
# reasoning: used by tagger
ObjectDetails = Sequence[ColumnDescription | TableStatistic]


@define
class IdentifiedObject:
    """
    Represents basic identification of object in a database.
    The object must be capable of standalone existence (table, view, index).
    """

    database_name: str
    object_name: str
    object_type: str
    platform_object_type: str
    create_datetime: datetime | None
    last_alter_datetime: datetime | None
    creator_name: str | None
    last_alter_name: str | None
    in_scope: bool = field(default=True)


@define
class DescribedObject:
    """
    Represents identifiable object and the objetc's definition.

    Attributes:
    - identified_object: IdentifiedObject, basic identification
    - object_comment: comment for the object
    - basic_definition: definition which can be executed against the database (DDL)
    - additional_details: list of details that can be gathered about the object,
            such as: column comments, statistics definition, etc.
    """

    identified_object: IdentifiedObject
    object_comment_ddl: str | None = field(default=None)
    basic_definition: str | None = field(default=None)
    additional_details: ObjectDetails = field(factory=list)


@define
class DescribedTeradataDatabase:
    """
    Represents database in Teradata.
    - owner_name - parent database
    - perm_space - in bytes
    - spool_space - in bytes
    - temp_space - in bytes
    """

    owner_name: str
    perm_space: int
    spool_space: int
    temp_space: int
    db_kind: str
    platform: str = field(default=TERADATA)


@define
class DescribedDatabase:
    """
    Represents a database.
    - database_name: str - name of the database in the platform
    - env_neutral_database_name: str | None - env friendly name of the db
    - comment_string: str | None
    - database_details: DescribedTeradataDatabase | None - platform specific details
    """

    database_name: str
    # TODO: FIXME: we expect the tag to be ALWAYS set, yet it is optional
    database_tag: str = field(default="")
    parent_name: str | None = field(default=None)
    parent_tag: str = field(default="")
    comment_string: str | None = field(default=None)
    database_details: DescribedTeradataDatabase | None = field(default=None)
    parent_tags_in_scope: list[str] = field(factory=list)


@define
class DeploymentFailure:
    path: str | None = field(default=None)
    statement: str | None = field(default=None)
    exc_message: str | None = field(default=None)


@define
class ListedEnv:
    all_databases: list[DescribedDatabase]
    dbs_in_scope: list[DescribedDatabase]
    all_objects: list[IdentifiedObject]
