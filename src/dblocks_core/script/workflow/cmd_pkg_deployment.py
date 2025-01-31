from pathlib import Path

from dblocks_core import context, dbi, exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.dbi import contract
from dblocks_core.deployer import fsequencer
from dblocks_core.model import config_model


def cmd_pkg_deploy(
    pkg_path: Path,
    *,
    pkg_cfg: config_model.PackagerConfig,
    env_cfg: config_model.EnvironParameters,
    ctx: context.Context,
):
    # FIXME: create a log file for the batch specifically

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

    for step in batch.steps:
        stp_chk = step.location.as_posix()
        if ctx.get_checkpoint(stp_chk):
            logger.warning(f"skipping deployment step: {step.location.name}")
            continue

        logger.info(f"start deployment step: {step.location.name}")
        # get a new session

        # deploy all objects
        for file in step.files:
            file_chk = stp_chk + "->" + file.file.as_posix()
            if ctx.get_checkpoint(file_chk):
                logger.warning(f" skip file: {file.file}")
                continue

            logger.info(f" deploy file: {file.file}")
            # switch default db to file.default_db
            # get all statements, tolerate procedures
            # run all statements
            pass
        ctx.set_checkpoint(file_chk)

        # force logoff
        ctx.set_checkpoint(stp_chk)

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
