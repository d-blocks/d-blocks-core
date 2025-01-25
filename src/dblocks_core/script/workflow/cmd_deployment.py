from datetime import datetime
from pathlib import Path
from typing import Iterable

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.context import Context
from dblocks_core.dbi import AbstractDBI
from dblocks_core.deployer import tokenizer
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import fsystem

_DO_NOT_DEPLOY = {fsystem.DATABASE_SUFFIX}  # TODO: skip databases for now


def deploy_dir(
    deploy_dir: Path,
    *,
    cfg: config_model.Config,
    env: config_model.EnvironParameters,
    ctx: Context,
    ext: AbstractDBI,
    log_each: int = 20,
    total_waves: int = 3,
) -> dict[str, meta_model.DeploymentFailure]:
    # tagger
    tgr = tagger.Tagger(
        variables=env.tagging_variables,
        rules=env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )

    # read all file names
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

    # split the queue to tables and others
    tables = [f for f in queue if f.suffix == fsystem.TABLE_SUFFIX]
    others = [f for f in queue if f.suffix != fsystem.TABLE_SUFFIX]

    # drop all objects from the database
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
    )

    # deploy others
    for wave in range(total_waves):
        logger.info(f"starting wave #{wave}")
        deploy_queue(
            others,
            ctx=ctx,
            tgr=tgr,
            ext=ext,
            log_each=log_each,
            total_queue_length=len(queue),
            failures=failures,
        )

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
):
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
            deploy_file_with_drop(
                file,
                tgr=tgr,
                object_database=object_database,
                object_name=object_name,
                ext=ext,
            )

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


def deploy_file_with_drop(
    file: Path,
    object_database: str,
    object_name: str,
    *,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
):
    script = file.read_text(
        encoding="utf-8", errors="strict"
    )  # TODO - should NOT be hardcoded
    if len(script.strip()) == 0:
        raise exc.DOperationsError(f"empty file encountered: {file.as_posix()}")

    # FIXME: if stored procedure, do not tokenize
    if file.suffix == fsystem.PROC_SUFFIX:
        deploy_procedure_with_drop(
            script,
            object_database=object_database,
            object_name=object_name,
            tgr=tgr,
            ext=ext,
            dry_run=dry_run,
        )
    else:
        deploy_script_with_drop(
            script,
            object_database=object_database,
            object_name=object_name,
            tgr=tgr,
            ext=ext,
            dry_run=dry_run,
        )


def deploy_procedure_with_drop(
    script: str,
    object_database: str,
    object_name: str,
    *,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
):
    statements = [s for s in tokenizer.tokenize_statemets(script)]
    logger.debug(f"statements: {len(statements)}")

    statements = [tgr.expand_statement(s) for s in statements]
    if not dry_run:
        # FIXME: do not tokenize stored procedures - switch this off (fix tokenizer)
        if obj := ext.get_identified_object(object_database, object_name):
            ext.drop_identified_object(obj, ignore_errors=True)
        ext.deploy_statements(script)
    else:
        # FIXME: do not tokenize stored procedures - switch this off (fix tokenizer)
        logger.debug(f"dry run: {script}")


def deploy_script_with_drop(
    script: str,
    object_database: str,
    object_name: str,
    *,
    tgr: tagger.Tagger,
    ext: AbstractDBI,
    dry_run: bool = False,
):
    statements = [s for s in tokenizer.tokenize_statemets(script)]
    logger.debug(f"statements: {len(statements)}")

    statements = [tgr.expand_statement(s) for s in statements]
    if not dry_run:
        if obj := ext.get_identified_object(object_database, object_name):
            ext.drop_identified_object(obj, ignore_errors=True)
        ext.deploy_statements(statements)
    else:
        for s in statements:
            logger.debug(f"dry run: {s}")


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
