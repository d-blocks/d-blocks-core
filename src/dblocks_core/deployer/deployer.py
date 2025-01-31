from pathlib import Path

from dblocks_core import context, tagger
from dblocks_core.config.config import logger
from dblocks_core.dbi import contract
from dblocks_core.deployer import fsequencer

# TODO: change DBI to protocol


def deploy_dir(
    root_dir: Path,
    *,
    dbi: contract.AbstractDBIExtractor,
    ctx: context.Context,
    tgr: tagger.Tagger | None = None,
) -> None:
    batch = fsequencer.create_batch(root_dir, tgr)

    logger.info(f"deploying batch {batch.root_dir}")

    for step in batch.steps:
        # get new connection for each step
        cn_step = step.name
        if ctx.get_checkpoint(cn_step):
            logger.warning(f"skipping step: {step.name}")
            continue

        default_db: str | None = None
        for file in step.files:
            cn_file = cn_step + "->" + file.file.name
            if ctx.get_checkpoint(cn_file):
                logger.warning(f"skipping file: {file.file.name}")
                continue

            # deefault db ...
            if default_db is not None or file.default_db is not None:
                if default_db != file.default_db:
                    default_db = file.default_db
                    if default_db is not None:
                        # change default db
                        pass

            for i, stmt in enumerate(file.statements()):
                sql = stmt.sql
                if tgr is not None:
                    sql = tgr.expand_statement(sql)
                    stmt.sql = sql

                cn_stmt = cn_file + f"->{i}@md5={stmt.md5()}"
                if ctx.get_checkpoint(cn_stmt):
                    logger.warning(f"skipping statement: {stmt.md5()}")
                    continue

                # deploy

                logger.info(f"deploying statement: {cn_stmt}")

                # try except block ...

                ctx.set_checkpoint(cn_stmt)

            ctx.set_checkpoint(cn_file)

        ctx.set_checkpoint(cn_step)

    # disconnect
