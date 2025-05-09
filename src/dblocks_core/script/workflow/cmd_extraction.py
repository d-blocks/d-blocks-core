from datetime import datetime

import cattrs
from attrs import frozen

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.git import git
from dblocks_core.model import config_model, meta_model, plugin_model
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
    plugins: None | list[plugin_model._PluginInstance] = None,
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
    Executes a full or incremental extraction of the database.

    Args:
        ctx (Context): The context for the operation.
        env (config_model.EnvironParameters): Environment parameters.
        env_name (str): Name of the environment.
        ext (AbstractDBI): Database interface for extraction.
        wrt (AbstractWriter): Writer interface for saving extracted data.
        repo (git.Repo | None): Git repository instance.
        filter_since_dt (datetime | None): Optional filter for changes since a specific datetime.
        filter_databases (str | None): Optional filter for database names.
        filter_names (str | None): Optional filter for object names.
        filter_creator (str | None): Optional filter for creator names.
        log_each (int): Frequency of logging progress.
        commit (bool): Whether to commit changes to the repository.

    Returns:
        None
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

    # prep plugins
    if plugins is None:
        plugins = []

    scope_plugins: list[plugin_model._PluginInstance] = []
    for plugin in plugins:
        if isinstance(plugin.instance, plugin_model.PluginExtractIsInScope):
            scope_plugins.append(plugin)
            logger.info(
                f"Plugin used to limit scope: {plugin.module_name}.{plugin.class_name}"
            )
        else:
            logger.info(f"Plugin: {plugin.module_name}.{plugin.class_name}")

    # prep tgt dir
    env.writer.target_dir.mkdir(exist_ok=True, parents=True)

    # get environment data from context, if at all possible
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
        # scan env; this checks definition of objects for all configured databases, however, we
        # respect various filters used in the call to this function
        # this means we will not scan filtered databases !!!
        logger.info("scanning environment")
        tgr, env_data = dbi.scan_env(
            env=env,
            ext=ext,
            filter_databases_like=filter_databases,
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

    # scope plugins
    if scope_plugins:
        logger.info("filtering objects in scope, using installed plugins")
        _in_scope = []
        for obj in in_scope:
            all_agreed_in_scope = True
            for plugin in scope_plugins:
                if not plugin.instance.is_in_scope(obj):
                    all_agreed_in_scope = False
                    break
            if all_agreed_in_scope:
                _in_scope.append(obj)
        in_scope = _in_scope

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
            plugin_instances=plugins,
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


@frozen
class _FilterFromFile:
    databases: list[str]
    objects: dict[str, list[str]]


# FIXME: incomplete, we plan to use this in a new command that dumps only selected objects (does not do a full scan)
# FIXME: extension of the run_extraction seems too complex, as it also deletes objects ... it HAS to scan the whole env!
def _objects_from_file(from_file: str) -> _FilterFromFile | None:
    if from_file is None:
        return None

    databases = set()
    objects = dict()
    total_count = 0

    logger.info(f"reading objects from file: {from_file}")
    with open(from_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().upper()
            elements = line.split(".")
            if len(elements) != 2:
                logger.warning(
                    f"line '{line}' does not contain exactly two elements, skipping"
                )
                continue

            database, table = elements

            if database not in databases:
                databases.add(database)
                objects[database] = []

            if table not in objects[database]:
                total_count += 1
                objects[database].append(table)

    logger.info(f"total count of objects: {total_count}")
    return _FilterFromFile(databases=sorted(list(databases)), objects=objects)
