import re
from datetime import datetime
from typing import Tuple

from dblocks_core import tagger
from dblocks_core.config.config import logger
from dblocks_core.dbi import AbstractDBI
from dblocks_core.model import config_model, meta_model


def scan_env(
    env: config_model.EnvironParameters,
    ext: AbstractDBI,
    *,
    filter_databases: str | None = None,
    filter_names: str | None = None,
    filter_creator: str | None = None,
    filter_since_dt: datetime | None = None,
) -> Tuple[tagger.Tagger, meta_model.ListedEnv]:

    # prep db filter
    re_database_filter: re.Pattern | None = None
    if filter_databases:
        filter_databases = filter_databases.strip().replace("%", ".*")
        re_database_filter = re.compile(filter_databases, re.I)
        logger.info(f"database filter: {re_database_filter}")

    # prep tablename filter
    re_name_filter: re.Pattern | None = None
    if filter_names:
        filter_names = filter_names.strip().replace("%", ".*")
        re_name_filter = re.compile(filter_names, re.I)
        logger.info(f"name filter: {re_name_filter}")

    # prep creator filter
    re_filter_creator: re.Pattern | None = None
    if filter_creator:
        re_filter_creator = re.compile(filter_creator, re.I)
        logger.info(f"creator filter: {re_filter_creator}")

    # prep tagger
    tgr = tagger.Tagger(
        env.tagging_variables,
        env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )

    # get list of databases in scope (ask the extractor)
    # each DB should also contain information about parent
    all_databases = ext.get_databases()

    # register all databases in the system for tagging purposes
    # then, tag them
    tgr.build(databases=[db.database_name for db in all_databases])
    for db in all_databases:
        db.database_tag = tgr.tag_database(db.database_name)
        db.parent_tag = tgr.tag_database(db.parent_name)  # type: ignore

    # isolate databases in scope
    # prepare list of parents for each db in scope (db.parent_tags_in_scope)
    dbs_in_scope = get_databases_in_scope(env=env, databases=all_databases)
    set_database_parents(dbs_in_scope)  # this MODIFIES data of dbs_in_scope !!!

    # filter by name of database
    if re_database_filter is not None:
        logger.info("filter only to databases on scope")
        dbs_in_scope = [
            d for d in dbs_in_scope if re_database_filter.fullmatch(d.database_name)
        ]
        logger.info(f"got: {len(dbs_in_scope)} databases")

    # extract
    all_objects: list[meta_model.IdentifiedObject] = []

    for i, database in enumerate(dbs_in_scope, start=1):
        # we need to get list of objects here, because incremental extraction
        # drops nonexisting objects - DO NOT SKIP THIS
        logger.info(f"scan: {database.database_name} - (#{i}/{len(dbs_in_scope)})")
        all_objects.extend(ext.get_object_list(database_name=database.database_name))
        logger.trace(len(all_objects))

    # limit the scope whenever asked
    for obj in all_objects:
        if re_database_filter and not re_database_filter.fullmatch(obj.database_name):
            obj.in_scope = False
            continue

        if re_filter_creator and not re_filter_creator.fullmatch(obj.creator_name):
            obj.in_scope = False
            continue

        if re_name_filter and not re_name_filter.fullmatch(obj.object_name):
            obj.in_scope = False
            continue

        if filter_since_dt:
            change_dates = [
                d
                for d in (obj.create_datetime, obj.last_alter_datetime)
                if d is not None
            ]
            if len(change_dates) > 0 and max(change_dates) < filter_since_dt:
                obj.in_scope = False
                continue

    result = (
        tgr,
        meta_model.ListedEnv(
            all_databases=all_databases,
            dbs_in_scope=dbs_in_scope,
            all_objects=all_objects,
        ),
    )
    return result


def get_databases_in_scope(
    *,
    env: config_model.EnvironParameters,
    databases: list[meta_model.DescribedDatabase],
) -> list[meta_model.DescribedDatabase]:  # type: ignore
    """
    Identifies databases in scope based on configured root databases and ownership
    hierarchy.

    Args:
        env (config_model.EnvironParameters): Environment parameters containing
            extraction configuration.
        databases (list[meta_model.DescribedDatabase]): List of described database
            objects to evaluate.

    Returns:
        list[meta_model.DescribedDatabase]: List of databases considered in scope
            based on configuration and hierarchy.

    The function iteratively checks:
    - Direct inclusion of databases specified in the configuration.
    - Ownership relationships for databases, recursively adding parent-child
      dependencies.
    - Supports only Teradata databases for recursive ownership evaluation.

    The process terminates when no new databases are added to the in-scope list.
    """

    in_scope: list[meta_model.DescribedDatabase] = []
    root_databases = {d.upper() for d in env.extraction.databases}

    i = 0
    while True:
        i = i + 1
        prev_len = len(in_scope)
        for db in databases:
            database_name = db.database_name.upper()

            # pokud je přímo zařazen mezi nakonfigurovanými databázemi,
            # zařaď do in scope
            if database_name in root_databases:
                if db not in in_scope:
                    logger.debug(f"adding db directly: {database_name}")
                    in_scope.append(db)

            # co když je databáze rekurzivně zařazená pod jedním z uzlů
            # zadaných v konfiguraci? toto implementujeme jen pro Teradatu
            # kontrolujeme zda jsme na této platformě
            if not isinstance(
                db.database_details,
                meta_model.DescribedTeradataDatabase,
            ):
                continue

            # pokud je owner této databáze mezi kořenovými databázemi,
            # které chceme sebrat, zařaď ho do "in_scope";  současně ho
            # zařaď mezi kořenové databáze, protože také může mít nějaké potomky
            if (
                db.database_details.owner_name.upper() in root_databases
                and db not in in_scope
            ):
                logger.debug(f"adding db, owner is in scope: {database_name}")
                in_scope.append(db)
                if database_name not in root_databases:
                    logger.debug(
                        f"adding database into list of parents: {database_name}"
                    )
                    root_databases.add(database_name)

        # pokud se již nezměnil seznam databázi in scope, končíme
        logger.debug(f"iteration: {i}, {len(in_scope)=}")
        if prev_len == len(in_scope):
            break

        return in_scope  # type: ignore


def set_database_parents(
    dbs_in_scope: list[meta_model.DescribedDatabase],
):
    """
    Sets the hierarchy of parent tags for databases in scope.

    This is not a pure function, values of `dbs_in_scope` are updated !!!

    Args:
        dbs_in_scope (list[meta_model.DescribedDatabase]): List of databases that
            are in scope.

    Behavior:
    - Creates a dictionary mapping each database's tag to its parent tag.
    - For each database, iteratively resolves the full chain of parent tags in
      scope, starting from its immediate parent.
    - Updates the `parent_tags_in_scope` attribute of each database with the
      resolved hierarchy.
    - Parents are appended to parent_tags_in_scope, which means that:
      - immediate parent gets index of 0
      - the parent of the immediate parent gets index of 1
      - ... and so on ...
    - If the immediate parent for the database is not found, resulting length
      of `db.parent_tags_in_scope` will be zero (empty list)
    """

    # set dict of parents for each db
    parents = {db.database_tag: db.parent_tag for db in dbs_in_scope}
    logger.trace(parents)
    for db in dbs_in_scope:
        this_parent = db.parent_tag
        path_to_db = []
        while True:
            try:
                new_parent = parents[this_parent]
                path_to_db.append(this_parent)
                this_parent = new_parent
            except KeyError:
                break
        db.parent_tags_in_scope = path_to_db
        logger.trace(db)
        logger.trace(db)
