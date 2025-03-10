from datetime import datetime
from pathlib import Path

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.dbi import AbstractDBI
from dblocks_core.model import config_model, meta_model
from dblocks_core.packager import fpackager
from dblocks_core.script.workflow import cmd_extraction

_F_DATETIME = "%Y-%m-%d"
PREFIX = "prefix"
SUFFIX = "suffix"
IDENTIFIERS = (PREFIX, SUFFIX)

# TODO - make this more generic
#  - i want to list all objects for DBs in scope
#  - i want to filter them by given criteria - name, creator, age, ... ?
#  - i want to do something on them
# in effect, this should be a composable pipeline, not a hardcoded function
#
# hence, .. pipeline-add <name> <params>
#           pipeline-run .. something like that ...
# how do I move data among these pipelines ... ?
#
# or
# dbe pkg <env>
# --filter-by-db <db>
# --filter-by-name <regex>
# --filter-by-age <spec>
# --filter-by-creator <user>
# --filter-by-access <spec>
# --filter-by-type <spec>
# --pkg-group-by databases/objects
# --pkg-path <path> --pkg-action drop
# --pkg-action <drop/rename/...>


def run_pkb_maint_backup(
    *,
    env: config_model.EnvironParameters,
    ext: AbstractDBI,
    pkg: fpackager.Packager,
    identifier: str,
    identified_by: str,
    since_dt: datetime,
    package_name: str,
):
    # sanity check
    if identified_by not in IDENTIFIERS:
        msg = f"identified_by: got {identified_by}, expected one of {IDENTIFIERS}"
        raise exc.DOperationsError(msg)

    # kill the package if it already exists
    pkg.drop_package_dir(package_name)

    # get list of databases in scope (ask the extractor)
    # each DB should also contain information about parent
    logger.info("get list of databases for this environment")
    all_databases = ext.get_databases()

    # prep tagger
    tgr = tagger.Tagger(
        env.tagging_variables,
        env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )

    # register all databases in the system for tagging purposes
    # then, tag them
    tgr.build(databases=[db.database_name for db in all_databases])
    for database in all_databases:
        database.database_tag = tgr.tag_database(database.database_name)
        database.parent_tag = tgr.tag_database(database.parent_name)  # type: ignore

    # isolate databases in scope
    # prepare list of parents for each db in scope (db.parent_tags_in_scope)
    dbs_in_scope = cmd_extraction.get_databases_in_scope(
        env=env,
        databases=all_databases,
    )
    logger.info(f"number of databases in scope: {len(dbs_in_scope)}")

    # get list of objects for all databases in scope
    kill_list: dict[str, list[meta_model.IdentifiedObject]] = {}
    kill_stmts: dict[str, list[str]] = {}

    for database in dbs_in_scope:
        logger.info(f"Checking database {database.database_name}")
        objects = ext.get_object_list(
            database_name=database.database_name,
            limit_to_type=meta_model.TABLE,
        )

        drop_these = [
            obj
            for obj in objects
            if is_in_scope_by_name(obj, identifier, identified_by)
            and is_older(obj, since_dt)
        ]
        kill_list[database.database_name] = drop_these
        kill_stmts[database.database_name] = [make_kill_stmt(obj) for obj in drop_these]

    # count drops
    count_drops = sum([len(kl) for kl in kill_stmts.items()])
    if count_drops == 0:
        logger.error("empty package, stop")
        return

    # make the package
    i = 0
    for db, statements in kill_stmts.items():
        if len(statements) == 0:
            continue

        i = i + 1
        step_name = f"{i:0>{3}}-{db.lower()}"
        logger.debug(f"step {step_name}: {len(statements)=}")

        # prep the cleanup script
        script = fpackager.Script(
            rel_path=(Path(db) / f"drop-backup-from-{db.lower()}.sql"),
            content="\n".join(statements),
        )
        # each cleanup script is in a separate step
        step = fpackager.Step(rel_path=Path(step_name), scripts=[script])
        pkg.steps.append(step)

    pkg.save_package(package_name)


def is_in_scope_by_name(
    obj: meta_model.IdentifiedObject,
    identifier: str,
    identified_by: str,
) -> bool:
    name = obj.object_name.lower()
    ident = identifier.lower()

    if identified_by == PREFIX:
        return name.startswith(ident)

    if identified_by == SUFFIX:
        return name.endswith(ident)

    err = f"identified_by: got {identified_by}, expected one of {IDENTIFIERS}"
    raise exc.DOperationsError(err)


def is_older(obj: meta_model.IdentifiedObject, since_dt: datetime) -> bool:
    if obj.create_datetime is None:
        return False
    return obj.create_datetime < since_dt


def make_kill_stmt(obj: meta_model.IdentifiedObject) -> str:
    if obj.object_type != meta_model.TABLE:
        raise exc.DOperationsError(f"expected a table, got: {obj}")

    _drop = f'DROP TABLE "{obj.database_name}"."{obj.object_name}"'
    _cdt = (
        obj.create_datetime.strftime(_F_DATETIME) if obj.create_datetime else "unknown"
    )
    _adt = (
        obj.last_alter_datetime.strftime(_F_DATETIME)
        if obj.last_alter_datetime
        else "unknown"
    )
    sql = f"{_drop} /* created: {_cdt}, altered: {_adt} */\n;"
    return sql
