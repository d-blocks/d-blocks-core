import sys
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Iterable

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from dblocks_core import context, exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.deployer import tokenizer
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import fsystem

# FIXME: this is also defined in cmd_pkg_deployment... violates DRY principle
RAISE_STRATEGY = "raise"
DROP_STRATEGY = "drop"
RENAME_STRATEGY = "rename"
_DO_NOT_DEPLOY = {fsystem.DATABASE_SUFFIX}  # TODO: skip databases for now
_DEPLOYMENT_STRATEGIES = [DROP_STRATEGY, RENAME_STRATEGY, RAISE_STRATEGY]
_DTTM_FMT = "%Y%m%d%H%M%S"


def deploy_env(
    deploy_dir: Path,
    *,
    cfg: config_model.Config,
    env: config_model.EnvironParameters,
    env_name: str,
    ctx: Context,
    ext: AbstractDBI,
    log_each: int = 20,
    if_exists: str | None,
    delete_databases: bool = False,
    assume_yes: bool = False,
    countdown_from: int,
) -> dict[str, meta_model.DeploymentFailure]:

    # sanity check
    if if_exists is not None:
        if if_exists not in _DEPLOYMENT_STRATEGIES:
            msg = (
                f"Invalid value: {if_exists=}\n"
                f"expected one of: {_DEPLOYMENT_STRATEGIES}"
            )
            raise exc.DOperationsError(msg)

    # tagger
    tgr = tagger.Tagger(
        variables=env.tagging_variables,
        rules=env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )

    # FIXME:    this should be a separate function that returns the batch
    #           read all file names

    # FIXME:    this also should detect if we are deploying a proper "batch",
    #           or if we deploy the "data" dir prepared by the writer
    queue = [
        f
        for f in deploy_dir.rglob("*")
        if f.is_file()
        and f.suffix in fsystem.EXT_TO_TYPE
        and f.suffix not in _DO_NOT_DEPLOY  # TODO: skip databases for now
    ]
    queue.sort()

    # prep list of impacted databases
    databases = sorted({tgr.expand_statement(f.parent.stem) for f in queue})

    # check all database names are known, everything was tagged correctly
    _assert_all_dbs_expanded(databases)

    # check the deployment
    if not assume_yes:
        _confirm_deployment(
            environment=env_name,
            deploy_dir=deploy_dir,
            env=env,
            countdown_from=countdown_from,
            ctx=ctx,
            if_exists=if_exists,
            delete_databases=delete_databases,
            len_of_queue=len(queue),
            databases=databases,
        )

    # FIXME: summary should be HERE as sort of the preview
    # - how many objects
    # - how many databases (see first 5 dbs)
    # - do we kill the scheme or not
    # - what is the conflict strategy

    # split the queue to tables and others
    tables = [f for f in queue if f.suffix == fsystem.TABLE_SUFFIX]
    others = [f for f in queue if f.suffix != fsystem.TABLE_SUFFIX]

    # FIXME: check thal all databases exist

    # drop all objects from the database
    if delete_databases:
        logger.warning("dropping databases")
        for db in databases:
            chk = f"delete database {db}"
            if ctx.get_checkpoint(chk):
                logger.warning(f"skip deletion of database: {db}")
                continue
            logger.warning(f"delete database: {db}")
            ext.delete_database(db)
            ctx.set_checkpoint(chk)

    # list of failed deployments
    failures: dict[str, meta_model.DeploymentFailure] = {}

    # deploy tables, the attempt is made only once, no dependencies are expected
    deploy_queue(
        tables,
        ctx=ctx,
        tgr=tgr,
        ext=ext,
        log_each=log_each,
        total_queue_length=len(queue),
        failures=failures,
        if_exists=if_exists,
    )

    # deploy others
    # FIXME - predetermined number of waaves....
    deployed_cnt = -1
    wave = 2
    while deployed_cnt == 0:
        logger.info(f"starting wave #{wave}")
        deployed_cnt = deploy_queue(
            others,
            ctx=ctx,
            tgr=tgr,
            ext=ext,
            log_each=log_each,
            total_queue_length=len(queue),
            failures=failures,
            if_exists=if_exists,
        )
        wave += 1
    return failures


def deploy_queue(
    files: Iterable[Path],
    *,
    ctx: Context,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    log_each: int,
    total_queue_length: int,
    failures: dict[str, meta_model.DeploymentFailure],
    if_exists: str | None,
) -> int:
    deployed_cnt = 0

    for i, file in enumerate(files):
        chk = file.as_posix()
        if ctx.get_checkpoint(chk):
            logger.debug(f"skip: {chk}")
            continue

        if (i + 1) % log_each == 1:
            logger.info(f"- table #{i+1}/{total_queue_length + 1}: {file.as_posix()}")

        object_name = file.stem
        object_database = tgr.expand_statement(file.parent.stem)

        try:
            # deploy contents of the file
            deploy_file(
                file,
                tgr=tgr,
                object_database=object_database,
                object_name=object_name,
                ext=ext,
                if_exists=if_exists,
            )
            deployed_cnt += 1

            # set the file as done
            ctx.set_checkpoint(chk)

            # delete the error message if it is stored in context
            if chk in ctx:
                del ctx[chk]

            # delete information about the failure if it was deployed successfully
            if chk in failures:
                del failures[chk]

        # connection errors stop the process
        except exc.DBCannotConnect:
            raise

        # all other database related errors are mitigated if possible
        # label the file as failed and store error message on the context
        except exc.DBStatementError as err:
            logger.error(f"{chk}: {err.message}")
            ctx[chk] = err.message
            fail = meta_model.DeploymentFailure(
                path=file.as_posix(),
                statement=err.statement,
                exc_message=err.message,
            )
            failures[fail.path] = fail  # type: ignore

    return deployed_cnt


def deploy_file(
    file: Path,
    object_database: str,
    object_name: str,
    *,
    if_exists: str | None,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
):
    script = file.read_text(
        encoding="utf-8", errors="strict"
    )  # TODO - should NOT be hardcoded
    if len(script.strip()) == 0:
        raise exc.DOperationsError(f"empty file encountered: {file.as_posix()}")

    object_type = None
    try:
        object_type = fsystem.EXT_TO_TYPE[file.suffix]
    except KeyError:
        # FIXME: support .sql and ,bteq files, at the moment
        #        we can not identify type of deployed object if the file is one of them
        #        which is a problem for stored procedures (meaning, we only need to identify SPs)

        logger.warning(f"unknown object type: {file}")
        pass

    # FIXME: if stored procedure, do not tokenize
    deploy_script_with_conflict_strategy(
        script,
        object_database=object_database,
        object_name=object_name,
        object_type=object_type,
        if_exists=if_exists,
        ext=ext,
        tgr=tgr,
        dry_run=dry_run,
    )


# def deploy_procedure_with_drop(
#     script: str,
#     object_database: str,
#     object_name: str,
#     *,
#     tgr: tagger.Tagger,
#     ext: AbstractDBI,
#     dry_run: bool = False,
# ):
#     statements = [script]
#     logger.debug(f"statements: {len(statements)}")

#     statements = [tgr.expand_statement(s) for s in statements]
#     if not dry_run:
#         if obj := ext.get_identified_object(object_database, object_name):
#             ext.drop_identified_object(obj, ignore_errors=True)
#         ext.deploy_statements(statements)
#     else:
#         for s in statements:
#             logger.debug(f"dry run: {s}")


# def deploy_script_with_drop(
#     script: str,
#     object_database: str,
#     object_name: str,
#     *,
#     tgr: tagger.Tagger,
#     ext: AbstractDBI,
#     dry_run: bool = False,
# ):
#     statements = [s for s in tokenizer.tokenize_statemets(script)]
#     logger.debug(f"statements: {len(statements)}")

#     statements = [tgr.expand_statement(s) for s in statements]
#     if not dry_run:
#         if obj := ext.get_identified_object(object_database, object_name):
#             ext.drop_identified_object(obj, ignore_errors=True)
#         ext.deploy_statements(statements)
#     else:
#         for s in statements:
#             logger.debug(f"dry run: {s}")


def deploy_script_with_conflict_strategy(
    script: str,
    *,
    object_database: str | None,
    object_name: str | None,
    object_type: str | None,
    if_exists: str | None,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
):
    errs = []
    if if_exists is not None:
        if if_exists not in _DEPLOYMENT_STRATEGIES:
            errs.append(
                f"Invalid value: {if_exists=}\n"
                f"expected one of: {_DEPLOYMENT_STRATEGIES}"
            )
        if object_database is None:
            errs.append("if_exists was given, but object_database is None")
        if object_name is None:
            errs.append("if_exists was given, but object_name is None")

        # FIXME: see FIXMEs in cmd_deployment.deploy_file
        #        the first part of the condition (is not None) should NOT be here
        #        and is only a temporary stopgap measure
        if object_type is not None and object_type not in meta_model.MANAGED_TYPES:
            errs.append(
                f"if_exists was given, but {object_type=}, "
                f"expected one of {meta_model.MANAGED_TYPES}"
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
    statements = [tgr.expand_statement(s) for s in statements]

    if dry_run:
        for s in statements:
            logger.debug(f"dry run: {s}")
        return

    # check the existence
    obj: meta_model.IdentifiedObject | None = None
    check_if_exists = object_database is not None and object_name is not None
    if check_if_exists:
        logger.debug(f"checking if the object exists: {object_database}.{object_name}")
        obj = ext.get_identified_object(object_database, object_name)
        logger.debug(obj)

    # implement conflict strategy
    if obj:
        logger.info(
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
            ext.drop_identified_object(obj, ignore_errors=True)
        elif if_exists == RENAME_STRATEGY:
            # FIXME: maybe have a few possible naming schemes ... who knows ...
            new_name = "_" + object_name + "_" + datetime.now().strftime(_DTTM_FMT)
            logger.info(f"rename: {object_database}.{object_name} => {new_name}")
            # FIXME: what happens, when the object changed type? Table to views, etc.
            # FIXME: move old data from the object
            ext.rename_identified_object(obj, new_name, ignore_errors=False)

        else:
            raise NotImplementedError(f"unsupported: {if_exists=}")

    # deploy the script
    ext.deploy_statements(statements)


def _assert_all_dbs_expanded(databases: list[str]):
    errs = [db for db in databases if "{{" in db]
    if errs:
        message = f"these databases are not expanded, check config: {errs}"
        raise exc.DConfigError(message)


def make_report(
    report_dir: Path,
    env: str,
    failures: dict[str, meta_model.DeploymentFailure],
):
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"report-deployment-{env}-{now_str}.md"

    with report_file.open("w", encoding="utf-8") as f:
        f.write(f"# Deployment report for {env}\n\n")
        f.write("## Failed objects\n\n")
        for path, fail in failures.items():
            f.write(f"\n### {path}\n\n")
            f.write(f"**message**: `{fail.exc_message}`\n")
            f.write(f"**statement:**\n```sql\n{fail.statement}\n```\n")

    logger.info(f"report written to: {report_file.as_posix()}")
    return report_file


def _confirm_deployment(
    *,
    environment: str,
    deploy_dir: Path,
    env: config_model.EnvironParameters,
    ctx: context.FSContext,
    if_exists: str | None,
    delete_databases: bool = False,
    len_of_queue: int,
    databases: list[str],
    countdown_from: int,
):
    console = Console()
    ctx_len = len(ctx.ctx_data.checkpoints)

    # build params table
    params = Table(title="Parameters")
    params.add_column("parameter")
    params.add_column("value")
    params.add_column("comment")
    for (
        k,
        v,
        cmt,
    ) in (
        ("environment", environment, "name of the env used"),
        ("directory", deploy_dir.as_posix(), "path to the package to deploy"),
        ("env.host", env.host, ""),
        ("env.username", env.username, ""),
        (
            "delete_databases",
            str(delete_databases),
            "if True, we will DESTROY CONTENT OF THESE DATABASES!",
        ),
        ("if_exists", if_exists, "conflict resolution strategy"),
        ("# of actions that succeded before", str(ctx_len), ""),
        ("# of scripts in the queue", str(len_of_queue), ""),
        ("# of databases we target", str(len(databases)), ""),
        ("we target ...", str(databases[:5]), "only first 5 databases"),
    ):
        params.add_row(k, v, cmt)

    # printout of params
    if ctx_len > 0:
        console.print(
            "*** This is a restart of unfinished action ***",
            style="bold red",
        )
        console.print("Use the ctx-list command to see what contexts exist")
    else:
        console.print("This is a clean start", style="bold green")

    console.print("Deployment with these parameters:", style="bold")
    console.print(params)
    if delete_databases:
        console.print("WARNING:", style="bold red", end=" ")
        console.print(
            "we are going to delete all content from target databases!",
            style="bold blue",
        )
    if if_exists != RAISE_STRATEGY:
        console.print("WARNING:", style="bold", end=" ")
        console.print(f"conflict strategy is set to {if_exists}")

    console.print("=== STOP AND THINK! ===", style="bold red")
    console.print("If you answer 'yes', countdown will ensue.")
    console.print("You will have one last chance to cancel the operation.")

    # confirm
    really = Prompt.ask("Are you sure? (yes/no)", default="no").strip()
    if really != "yes":
        logger.error(f"action canceled by prompt: {really}")
        sys.exit(1)

    # countdown
    for i in range(countdown_from, -1, -1):
        console.print(f"{i} ...", style="bold red")
        sleep(1)
