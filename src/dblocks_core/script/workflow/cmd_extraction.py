from datetime import datetime

import cattrs

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.git import git
from dblocks_core.model import config_model, meta_model
from dblocks_core.script.workflow import dbi
from dblocks_core.writer import AbstractWriter


def run_extraction(
    # parts of the pipeline
    ctx: Context,
    env: config_model.EnvironParameters,
    env_name: str,
    ext: AbstractDBI,
    wrt: AbstractWriter,
    repo: git.Repo | None,
    *,
    # extraction options
    filter_since_dt: None | datetime = None,
    filter_databases: str | None = None,
    filter_names: str | None = None,
    filter_creator: str | None = None,
    # behaviour
    log_each: int = 5,
    commit: bool = False,
):
    """
    Run full extraction of the database.
    """
    # prep git
    if env.git_branch is not None:
        if repo is None:
            message = "\n".join(
                [
                    f"This environment has configured git branch: {env.git_branch}",
                    "However, we are not in a git repository.",
                    "Either run 'dbe init' (recommended) or 'git init'.",
                ]
            )
            raise exc.DOperationsError(message)

        # if this is not a restart operation, assume that the repo must be clean
        if not ctx.is_in_progress():
            logger.info("check if repo is clean")
            if repo.is_dirty():
                raise exc.DOperationsError(
                    "Repository is dirty, cannot proceed with extraction."
                    "\nYou should:"
                    "\n- check what changes are in the repo (git status; git diff)"
                    "\n- decide if you want to DROP all changes (git stash --all && "
                    "git stash drop); or"
                    "\n- commit everyhing, commit selectively (git add --all && "
                    "git commit)"
                )
        else:
            logger.warning("restart operation, do NOT assume repo is clean")

        # assume we are in the correct branch
        repo.checkout(env.git_branch, missing_ok=True)

    # prep tgt dir
    env.writer.target_dir.mkdir(exist_ok=True, parents=True)

    # get environment data fron context, if at all passible
    ENV_DATA = "ENV_DATA"
    env_data: meta_model.ListedEnv
    try:
        env_data = cattrs.structure(ctx[ENV_DATA], meta_model.ListedEnv)
        logger.warning("we will use environment data from context")
        # FIXME - this reimplements the same logic as dbi.scan_env, which I do not like
        tgr = tagger.Tagger(
            env.tagging_variables,
            env.tagging_rules,
            tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
        )
        tgr.build(databases=[db.database_name for db in env_data.all_databases])

    except KeyError:
        # scan env
        logger.info("scanning environment")
        tgr, env_data = dbi.scan_env(
            env=env,
            ext=ext,
            filter_databases=filter_databases,
            filter_names=filter_names,
            filter_creator=filter_creator,
            filter_since_dt=filter_since_dt,
        )
        ctx[ENV_DATA] = cattrs.unstructure(env_data)

    db_to_tag = {
        d.database_name.upper(): d.database_tag for d in env_data.all_databases
    }
    db_to_parents = {
        d.database_name.upper(): d.parent_tags_in_scope for d in env_data.all_databases
    }

    # extract
    started_when = datetime.now()
    db, prev_db = None, None
    in_scope = [obj for obj in env_data.all_objects if obj.in_scope]
    logger.info(f"total lenght of the queue is: {len(in_scope)}")
    for i, obj in enumerate(in_scope, start=1):
        db = obj.database_name
        if not obj.in_scope:
            continue

        obj_chk_name = f"get-described-object:{obj.database_name}.{obj.object_name}"
        if ctx.get_checkpoint(obj_chk_name):
            continue

        # log progress from time to time
        if i % log_each == 0:
            eta = ctx.eta(
                total_steps=len(in_scope),
                finished_steps=i,
                eta_since=started_when,
            ).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                f": {obj.database_name}.{obj.object_name}"
                f" (#{i}/{len(in_scope)}, ETA={eta}))"
            )

        # get the definition - be tolerant to attempt to get def
        # of object that was dropped since we started
        described_object = ext.get_described_object(obj)
        if described_object is None:
            logger.warning(
                f"object does not exist: {obj.database_name}.{obj.object_name}"
            )
            continue

        # the function is NOT pure and modifies the object in question!
        # namely, we try to tag the database, which modifies object definition (ddl+statements)
        tgr.tag_object(described_object)

        # write the object to the repo
        wrt.write_object(
            described_object,
            database_tag=db_to_tag[obj.database_name.upper()],  # type: ignore
            parent_tags_in_scope=db_to_parents[obj.database_name.upper()],
        )
        ctx.set_checkpoint(obj_chk_name)

        # commit?
        if repo is not None and prev_db is not None and db != prev_db:
            if commit and not repo.is_clean():
                repo.add()
                repo.commit(f"dbe env-extract {env_name}: {db}")

        # next iteration
        prev_db = obj.database_name

    # commit
    if repo is not None:
        if not repo.is_clean():
            if commit:
                repo.add()
                repo.commit(f"dbe env-extract {env_name}: delete dropped objects")
            else:
                logger.warning("Please, commit your changes.")


# def run_extraction2(
#     # parts of the pipeline
#     ctx: Context,
#     env: config_model.EnvironParameters,
#     env_name: str,
#     ext: AbstractDBI,
#     wrt: AbstractWriter,
#     repo: git.Repo | None,
#     *,
#     # extraction options
#     filter_since_dt: None | datetime = None,
#     filter_databases: str | None = None,
#     filter_names: str | None = None,
#     filter_creator: str | None = None,
#     # behaviour
#     log_each: int = 20,
#     commit: bool = False,
# ):
#     """
#     Run full extraction of the database.
#     """
#     incremental_extraction = filter_since_dt is not None

#     # prep git
#     if env.git_branch is not None:
#         if repo is None:
#             message = "\n".join(
#                 [
#                     f"This environment has configured git branch: {env.git_branch}",
#                     "However, we are not in a git repository.",
#                     "Either run 'dbe init' (recommended) or 'git init'.",
#                 ]
#             )
#             raise exc.DOperationsError(message)

#         # if this is not a restart operation, assume that the repo must be clean
#         if not ctx.is_in_progress():
#             logger.info("check if repo is clean")
#             if repo.is_dirty():
#                 raise exc.DOperationsError(
#                     "Repository is dirty, cannot proceed with extraction."
#                     "\nYou should:"
#                     "\n- check what changes are in the repo (git status; git diff)"
#                     "\n- decide if you want to DROP all changes (git stash --all && "
#                     "git stash drop); or"
#                     "\n- commit everyhing, commit selectively (git add --all && "
#                     "git commit)"
#                 )
#         else:
#             logger.warning("restart operation, do NOT assume repo is clean")

#         # assume we are in the correct branch
#         repo.checkout(env.git_branch, missing_ok=True)

#     # prep db filter
#     re_database_filter: re.Pattern | None = None
#     if filter_databases:
#         filter_databases = filter_databases.strip().replace("%", ".*")
#         re_database_filter = re.compile(filter_databases, re.I)
#         logger.info(f"database filter: {re_database_filter}")

#     # prep tablename filter
#     re_table_filter: re.Pattern | None = None
#     if filter_names:
#         filter_names = filter_names.strip().replace("%", ".*")
#         re_table_filter = re.compile(filter_names, re.I)
#         logger.info(f"name filter: {re_table_filter}")

#     # prep creator filter
#     re_filter_creator: re.Pattern | None = None
#     if filter_creator:
#         re_filter_creator = re.compile(filter_creator, re.I)
#         logger.info(f"creator filter: {re_filter_creator}")

#     # prep tgt dir
#     env.writer.target_dir.mkdir(exist_ok=True, parents=True)

#     # prep tagger
#     tgr = tagger.Tagger(
#         env.tagging_variables,
#         env.tagging_rules,
#         tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
#     )

#     # get list of databases in scope (ask the extractor)
#     # each DB should also contain information about parent
#     all_databases = ext.get_databases()

#     # register all databases in the system for tagging purposes
#     # then, tag them
#     tgr.build(databases=[db.database_name for db in all_databases])
#     for db in all_databases:
#         db.database_tag = tgr.tag_database(db.database_name)
#         db.parent_tag = tgr.tag_database(db.parent_name)  # type: ignore
#     wrt.write_databases(all_databases, env_name=env_name)

#     # isolate databases in scope
#     # prepare list of parents for each db in scope (db.parent_tags_in_scope)
#     dbs_in_scope = get_databases_in_scope(env=env, databases=all_databases)
#     set_database_parents(dbs_in_scope)  # this MODIFIES data of dbs_in_scope !!!

#     # filter by name of database
#     if not re_database_filter is None:
#         logger.info("filter only to databases on scope")
#         dbs_in_scope = [
#             d for d in dbs_in_scope if re_database_filter.fullmatch(d.database_name)
#         ]
#         logger.info(f"got: {len(dbs_in_scope)} databases")

#     # extract
#     all_objects = []

#     for db_i, database in enumerate(dbs_in_scope):
#         db_chk_name = f"database-is-done:{database.database_name}"

#         # we need to get list of objects here, because incremental extraction
#         # drops nonexisting objects - DO NOT SKIP THIS
#         logger.info(
#             f"asking for object list: {database.database_name} - "
#             f"(#{db_i}/{len(dbs_in_scope)})"
#         )
#         objects = ext.get_object_list(database_name=database.database_name)
#         logger.info(f"{database.database_name}: {len(objects)} objects, extracting")

#         all_objects.extend(objects)
#         logger.trace(len(all_objects))

#         # if this DB is done, skip it, do not refresh metadata
#         # this can onlly be done AFTER we got list of existing objects from it
#         if ctx.get_checkpoint(db_chk_name):
#             logger.debug(db_chk_name)
#             continue

#         logger.info(
#             f"Extract database {database.database_name=} "
#             f"tagged as {database.database_tag=}."
#         )

#         # eta calc
#         started_when = datetime.now()

#         # get details about the object
#         for i, obj in enumerate(objects):
#             i = i + 1

#             # skip objects that are to be filtered based on name
#             if re_table_filter is not None:
#                 if not re_table_filter.fullmatch(obj.object_name):
#                     continue

#             # skip objects by creator
#             if re_filter_creator is not None and obj.creator_name is not None:
#                 if not re_filter_creator.fullmatch(obj.creator_name):
#                     continue

#             # skip objects that should not be extracted by date
#             if incremental_extraction:
#                 change_dates = [
#                     d
#                     for d in (obj.create_datetime, obj.last_alter_datetime)
#                     if d is not None
#                 ]
#                 if len(change_dates) > 0 and max(change_dates) < filter_since_dt:
#                     continue

#             # skip objects that were already extracted
#             obj_chk_name = f"get-described-object:{obj.database_name}.{obj.object_name}"
#             if ctx.get_checkpoint(obj_chk_name):
#                 logger.debug(f"skipping: {obj_chk_name}")
#                 continue

#             # log progress from time to time
#             if i % log_each == 0:
#                 eta = ctx.eta(
#                     total_steps=len(objects),
#                     finished_steps=i,
#                     eta_since=started_when,
#                 ).strftime("%Y-%m-%d %H:%M:%S")
#                 logger.info(
#                     f"db {database.database_name} "
#                     f"(#{db_i+1} of {len(dbs_in_scope)} in scope, with ETA={eta})"
#                     f": {obj.object_name} (#{i}/{len(objects)} in this DB)"
#                 )

#             # get the definition - be tolerant to attempt to get def
#             # of object that was dropped since we started
#             described_object = ext.get_described_object(obj)
#             if described_object is None:
#                 logger.warning(
#                     f"object does not exist: {obj.database_name}.{obj.object_name}"
#                 )
#                 continue

#             # the function is NOT pure and modifies the object in question!
#             # namely, we try to tag the database, which modifies object definition (ddl+statements)
#             tgr.tag_object(described_object)

#             # write the object to the repo
#             wrt.write_object(
#                 described_object,
#                 database_tag=database.database_tag,  # type: ignore
#                 parent_tags_in_scope=database.parent_tags_in_scope,
#             )
#             ctx.set_checkpoint(obj_chk_name)

#         # database is done
#         ctx.set_checkpoint(db_chk_name)

#         if commit and repo is not None:
#             if not repo.is_clean():
#                 repo.add()
#                 repo.commit(f"dbe env-extract {env_name}: {database.database_name}")

#     # delete droped objects
#     wrt.drop_nonex_objects(
#         existing_objects=all_objects,
#         tagged_databases=all_databases,
#         databases_in_scope=dbs_in_scope,
#     )

#     # commit
#     if repo is not None:
#         if not repo.is_clean():
#             if commit:
#                 repo.add()
#                 repo.commit(f"dbe env-extract {env_name}: delete dropped objects")
#             else:
#                 logger.warning("Please, commit your changes.")


# def get_databases_in_scope(
#     *,
#     env: config_model.EnvironParameters,
#     databases: list[meta_model.DescribedDatabase],
# ) -> list[meta_model.DescribedDatabase]:  # type: ignore
#     """
#     Identifies databases in scope based on configured root databases and ownership
#     hierarchy.

#     Args:
#         env (config_model.EnvironParameters): Environment parameters containing
#             extraction configuration.
#         databases (list[meta_model.DescribedDatabase]): List of described database
#             objects to evaluate.

#     Returns:
#         list[meta_model.DescribedDatabase]: List of databases considered in scope
#             based on configuration and hierarchy.

#     The function iteratively checks:
#     - Direct inclusion of databases specified in the configuration.
#     - Ownership relationships for databases, recursively adding parent-child
#       dependencies.
#     - Supports only Teradata databases for recursive ownership evaluation.

#     The process terminates when no new databases are added to the in-scope list.
#     """

#     in_scope: list[meta_model.DescribedDatabase] = []
#     root_databases = {d.upper() for d in env.extraction.databases}

#     i = 0
#     while True:
#         i = i + 1
#         prev_len = len(in_scope)
#         for db in databases:
#             database_name = db.database_name.upper()

#             # pokud je přímo zařazen mezi nakonfigurovanými databázemi,
#             # zařaď do in scope
#             if database_name in root_databases:
#                 if db not in in_scope:
#                     logger.debug(f"adding db directly: {database_name}")
#                     in_scope.append(db)

#             # co když je databáze rekurzivně zařazená pod jedním z uzlů
#             # zadaných v konfiguraci? toto implementujeme jen pro Teradatu
#             # kontrolujeme zda jsme na této platformě
#             if not isinstance(
#                 db.database_details,
#                 meta_model.DescribedTeradataDatabase,
#             ):
#                 continue

#             # pokud je owner této databáze mezi kořenovými databázemi,
#             # které chceme sebrat, zařaď ho do "in_scope";  současně ho
#             # zařaď mezi kořenové databáze, protože také může mít nějaké potomky
#             if (
#                 db.database_details.owner_name.upper() in root_databases
#                 and db not in in_scope
#             ):
#                 logger.debug(f"adding db, owner is in scope: {database_name}")
#                 in_scope.append(db)
#                 if database_name not in root_databases:
#                     logger.debug(
#                         f"adding database into list of parents: {database_name}"
#                     )
#                     root_databases.add(database_name)

#         # pokud se již nezměnil seznam databázi in scope, končíme
#         logger.debug(f"iteration: {i}, {len(in_scope)=}")
#         if prev_len == len(in_scope):
#             break

#         return in_scope  # type: ignore


# def set_database_parents(
#     dbs_in_scope: list[meta_model.DescribedDatabase],
# ):
#     """
#     Sets the hierarchy of parent tags for databases in scope.

#     This is not a pure function, values of `dbs_in_scope` are updated !!!

#     Args:
#         dbs_in_scope (list[meta_model.DescribedDatabase]): List of databases that
#             are in scope.

#     Behavior:
#     - Creates a dictionary mapping each database's tag to its parent tag.
#     - For each database, iteratively resolves the full chain of parent tags in
#       scope, starting from its immediate parent.
#     - Updates the `parent_tags_in_scope` attribute of each database with the
#       resolved hierarchy.
#     - Parents are appended to parent_tags_in_scope, which means that:
#       - immediate parent gets index of 0
#       - the parent of the immediate parent gets index of 1
#       - ... and so on ...
#     - If the immediate parent for the database is not found, resulting length
#       of `db.parent_tags_in_scope` will be zero (empty list)
#     """

#     # set dict of parents for each db
#     parents = {db.database_tag: db.parent_tag for db in dbs_in_scope}
#     logger.trace(parents)
#     for db in dbs_in_scope:
#         this_parent = db.parent_tag
#         path_to_db = []
#         while True:
#             try:
#                 new_parent = parents[this_parent]
#                 path_to_db.append(this_parent)
#                 this_parent = new_parent
#             except KeyError:
#                 break
#         db.parent_tags_in_scope = path_to_db
#         logger.trace(db)
#         logger.trace(db)
