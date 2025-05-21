from pathlib import Path

from rich.console import Console

from dblocks_core import exc, tagger
from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.git import git
from dblocks_core.model import config_model, meta_model
from dblocks_core.writer import fsystem

console = Console()


def run_detag(
    env_name: str,
    cfg: config_model.Config,
    repo: git.Repo | None,
    file_or_directory: Path,
    *,
    confirm_if_more_than: int = 50,
    assume_yes: bool = False,
):
    env = config.get_environment_from_config(cfg, env_name)
    encoding = env.writer.encoding
    if not encoding:
        encoding = "utf-8"

    tgr = tagger.Tagger(
        variables=env.tagging_variables,
        rules=env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )

    # check the repo
    if repo and not repo.is_clean():
        logger.warning("Repo is not clean")
        if not assume_yes:
            if not _confirm_repo_not_clean():
                raise exc.DBlocksError("Repo is not clean. Exiting.")

    if file_or_directory.is_file():
        detag_file(file_or_directory, encoding, tgr)
    else:
        files = list(file_or_directory.rglob("*.*"))
        if not assume_yes and not _confirm_long_list_of_files(
            files,
            confirm_if_more_than,
        ):
            raise exc.DBlocksError(
                "Too many files to detag. Use --assume-yes to continue."
            )

        for file in files:
            if not file.is_file():
                continue
            # check if this file is debbie relevant
            detag_file(file, encoding, tgr)

    if repo and not repo.is_clean():
        logger.warning("Content of the repository was changed, commit was not done.")


def detag_file(
    file: Path,
    encoding: str,
    tgr: tagger.Tagger,
):
    suffix = file.suffix.lower()
    if suffix not in fsystem.EXT_TO_TYPE:
        logger.debug(f"skipping file {file}")
    content = file.read_text(encoding=encoding)
    new_content = tgr.expand_statement(content)
    if new_content != content:
        logger.info(f"detagging {file}")
        file.write_text(new_content, encoding=encoding)


def _confirm_repo_not_clean() -> bool:
    return (
        console.input("Repo is not clean. Type in 'ignore' to continue: ").lower()
        == "ignore"
    )


def _confirm_long_list_of_files(files: list[Path], confirm_if_more_than: int) -> bool:
    if len(files) <= confirm_if_more_than:
        return True
    return (
        console.input(
            f"Got {len(files)} files, type in 'continue' to proceed: "
        ).lower()
        == "continue"
    )
