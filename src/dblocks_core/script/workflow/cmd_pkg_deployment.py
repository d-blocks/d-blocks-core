from datetime import datetime
from pathlib import Path

from dblocks_core import context, dbi, exc, tagger
from dblocks_core.config.config import add_logger_sink, logger, remove_logger_sink
from dblocks_core.dbi import AbstractDBI
from dblocks_core.deployer import fsequencer, tokenizer
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import fsystem

# FIXME: this is also defined in cmd_deployment... violates DRY principle

RAISE_STRATEGY = "raise"
DROP_STRATEGY = "drop"
RENAME_STRATEGY = "rename"
_DO_NOT_DEPLOY = {fsystem.DATABASE_SUFFIX}  # TODO: skip databases for now
_DEPLOYMENT_STRATEGIES = [DROP_STRATEGY, RENAME_STRATEGY, RAISE_STRATEGY]
_DTTM_FMT = "%Y%m%d%H%M%S"


def cmd_pkg_deploy(
    pkg_path: Path,
    *,
    pkg_cfg: config_model.PackagerConfig,
    env_cfg: config_model.EnvironParameters,
    ctx: context.Context,
    if_exists: str | None,
    dry_run: bool = False,
):
    # sanity check
    if if_exists is not None:
        if if_exists not in _DEPLOYMENT_STRATEGIES:
            msg = (
                f"Invalid value: {if_exists=}\n"
                f"expected one of: {_DEPLOYMENT_STRATEGIES}"
            )
            raise exc.DOperationsError(msg)

    # find subdirecory where steps are located
    # use case insensitive search, if switched on in config
    logger.info(f"look for {pkg_cfg.steps_subdir} under {pkg_path}")
    if pkg_cfg.case_insensitive_dirs:
        subdirs = case_insensitive_search(pkg_path, pkg_cfg.steps_subdir)
        if subdirs is None:
            raise exc.DOperationsError(f"subdir not found: {pkg_cfg.steps_subdir}")
        root_dir = pkg_path / subdirs
    else:
        root_dir = pkg_path / pkg_cfg.steps_subdir

    # sanity check
    if not root_dir.is_dir():
        raise exc.DOperationsError(f"directory not found: {root_dir}")

    # tagger
    tgr = tagger.Tagger(
        variables=env_cfg.tagging_variables,
        rules=env_cfg.tagging_rules,
        tagging_strip_db_with_no_rules=env_cfg.tagging_strip_db_with_no_rules,
    )

    # dbi
    ext = dbi.extractor_factory(env_cfg)

    # deployment batch
    logger.info(f"scanning steps dir: {root_dir}")
    batch = fsequencer.create_batch(root_dir, tgr)

    if dry_run:
        logger.warning("DRY RUN: we will simulate the deployment.")

    # get a log directory in the package
    log_dir = pkg_path / "log"
    log_dir.mkdir(exist_ok=True)

    log_sink_id: int | None = None
    for step in batch.steps:
        # add the logger
        if log_sink_id is not None:
            remove_logger_sink(log_sink_id)
        log_file = log_dir / (step.name + ".log")
        log_sink_id = add_logger_sink(log_file)

        stp_chk = step.location.as_posix()
        if ctx.get_checkpoint(stp_chk):
            logger.warning(f"+--  skipping deployment step: {step.location.name}")
            continue

        # deploy all objects
        logger.info(f"+--+ start    deployment step: {step.location.name}")
        prev_db = None
        for file in step.files:
            file_chk = stp_chk + "->" + file.file.as_posix()
            if ctx.get_checkpoint(file_chk):
                logger.warning(f"   +-- skip file: {file.file}")
                logger.log("TERADATA", f"--+ skip file: {file.file}")
                continue

            logger.info(f"   +-- deploy file: {file.file}")
            logger.log("TERADATA", f"--+ deploy file: {file.file}")
            # switch default db to file.default_db

            if file.default_db is not None and prev_db != file.default_db:
                logger.warning(f"   +-- change database: {file.default_db}")
                ext.change_database(file.default_db)

            # get default db
            deploy_script_with_conflict_strategy(
                script_file=file,
                if_exists=if_exists,
                tgr=tgr,
                ext=ext,
                dry_run=dry_run,
            )
            prev_db = file.default_db
            ctx.set_checkpoint(file_chk)

        # force logoff
        ext.dispose()
        ctx.set_checkpoint(stp_chk)

    # close the log for this step
    if log_sink_id is not None:
        remove_logger_sink(log_sink_id)

    ctx.done()


def _path_to_directories(path: Path) -> list[str]:
    elements = []
    curr: Path = path
    prev: Path | None = None

    while curr != prev:
        if curr.name:
            elements.insert(0, curr.name)
        prev = curr
        curr = curr.parent

    return elements


def case_insensitive_search(root: Path, subdir: Path) -> Path | None:
    wanted = _path_to_directories(subdir)
    wanted = [s.lower() for s in wanted]
    found_dirs = []

    for i in range(len(wanted)):
        children_dir_names = [
            (d.name.lower(), d.name) for d in root.glob("*") if d.is_dir
        ]
        found = False
        for name_lower, name in children_dir_names:
            if name_lower == wanted[i]:
                found = True
                found_dirs.append(name)
                root = root / name
                break
        if not found:
            return None

    return Path(*found_dirs)


# FIXME: almost identical function in scripts.workflow.cmd_deployment!
#        I would probably suggest to use this one,
#        and use it also to deploy full DBs (cmd_deployment)
def deploy_script_with_conflict_strategy(
    script_file: fsequencer.DeploymentFile,
    *,
    if_exists: str | None,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
    encoding: str = "utf-8",  # FIXME: writer has this as a config parameter. Hardcoded val?
):
    object_name: str | None = None
    object_type = script_file.file_type
    object_database: str | None = script_file.default_db

    logger.log("TERADATA", f"--+ deploy file: {script_file.file}")

    # assume that the name of the object is identical to name of the file
    if script_file.file_type in meta_model.MANAGED_TYPES:
        object_name = script_file.file.stem.upper()
        if script_file.default_db is None:
            logger.warning(f"unknown default database for {script_file.file}")

    # read deployment content
    script = script_file.file.read_text(encoding=encoding)
    errs = []
    if if_exists is not None:
        if if_exists not in _DEPLOYMENT_STRATEGIES:
            errs.append(
                f"Invalid value: {if_exists=}\n"
                f"expected one of: {_DEPLOYMENT_STRATEGIES}"
            )
    if errs:
        raise exc.DOperationsError("\n".join(errs))

    # Stored procedures must be executed as one statement.
    # One file is one procedure, no other statements are allowed.
    # Otherwise, split the script to separate statements.
    #
    # FIXME: this needs to be checked with ANSI semantics and DML statements.
    # FIXME: maybe? for procedures, tokenize, but handle BEGIN/END statements in the script?
    if object_type == meta_model.PROCEDURE:
        statements = [script]
    else:
        statements = [s for s in tokenizer.tokenize_statements(script)]

    # FIXME: this only allows for checkpoint with granularity per file, do we want to prep checkpoints per statement ???
    statements = [tgr.expand_statement(s) for s in statements]

    # check the existence of the object based on the conflict strategy
    obj: meta_model.IdentifiedObject | None = None
    check_if_exists = (
        object_type in meta_model.MANAGED_TYPES  # ignore .sql and .bteq files
        and object_database is not None  # database must be known
        and object_name is not None  # object name must be known
    )

    if check_if_exists:
        logger.debug(f"checking if the object exists: {object_database}.{object_name}")
        obj = ext.get_identified_object(object_database, object_name)
        logger.debug(obj)

    # implement conflict strategy
    # FIXME: for all types of objects, with no exceptions ???
    if obj:
        logger.warning(
            f"conflict: {obj.object_type} {object_database}.{object_name}: {if_exists=}"
        )

        if if_exists == RAISE_STRATEGY:
            msg = "\n".join(
                [
                    "Cannot continue as the object we try to deploy exists.",
                    f"  - database = {object_database}",
                    f"  - object = {object_name}",
                    f"  - existing object type = {object_type}",
                    f"These strategies that deal with the conflict could be used: {_DEPLOYMENT_STRATEGIES}",
                ]
            )
            raise exc.DOperationsError(msg)
        elif if_exists == DROP_STRATEGY:
            logger.info(f"drop: {object_database}.{object_name}")
            if not dry_run:
                ext.drop_identified_object(obj, ignore_errors=True)
        elif if_exists == RENAME_STRATEGY:
            # FIXME: maybe have a few possible naming schemes ... who knows ...
            new_name = "_" + object_name + "_" + datetime.now().strftime(_DTTM_FMT)
            logger.info(f"rename: {object_database}.{object_name} => {new_name}")
            # FIXME: what happens, when the object changed type? Table to views, etc.
            # FIXME: move old data from the object
            if not dry_run:
                ext.rename_identified_object(obj, new_name, ignore_errors=False)
        else:
            raise NotImplementedError(f"unsupported: {if_exists=}")

    # deploy the script
    if not dry_run:
        ext.deploy_statements(statements)
