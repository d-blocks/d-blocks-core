from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from typing_extensions import Annotated

from dblocks_core import dbi, exc
from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.git import git
from dblocks_core.packager import fpackager
from dblocks_core.parse import prsr_simple
from dblocks_core.script.workflow import cmd_git_copy_changed, cmd_pkg_maint_backup

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

console = Console()


@app.command()
def pkg_maint_backup(
    environment: Annotated[
        str,
        typer.Argument(
            help="Name of the environment in which you want to "
            "prepare cleaning package."
        ),
    ],
    *,
    age: str = "35d",
    package_name: Annotated[
        str,
        typer.Option(
            help="Name of the package to be created. "
            "If not provided, name will be set to 'YYYMMDD-drop-backup', "
            "current time will be used."
        ),
    ] = "",
    identifier: Annotated[
        str,
        typer.Option(help="Prefix of tables, that are considered to be backup tables."),
    ] = "_",
    identified_by: Annotated[
        str, typer.Option(help="Identifier is: prefix, suffix")
    ] = "prefix",
):
    """
    Creates a package which will contain drop of backup tables, based on
    given age, and name prefix.
    """
    cfg = config.load_config()
    since_dt = prsr_simple.parse_duration_since_now(age)
    logger.info("drop backup older than: " + since_dt.strftime("%Y-%m-%d %H:%M:%S"))

    env = config.get_environment_from_config(cfg, environment)
    ext = dbi.extractor_factory(env)
    pkg = fpackager.packager_factory(cfg.packager)
    if package_name == "":
        package_name = datetime.now().strftime("%Y-%m-%d") + "-drop-backup"

    cmd_pkg_maint_backup.run_pkb_maint_backup(
        env=env,
        ext=ext,
        pkg=pkg,
        identifier=identifier,
        identified_by=identified_by,
        since_dt=since_dt,
        package_name=package_name,
    )


@app.command()
def git_copy_changed(
    target: str,
    *,
    commit: str | None = None,  # if given, list changes in a commit, otherwise on index
    repo_path: str | None = None,
    source_subdir: str | None = None,
    assume_yes: bool = False,
):
    """Copy all changed but uncommitted files to a specified path."""
    config.load_config()
    repo = git.repo_factory(in_dir=repo_path, raise_on_error=True)
    if repo is None:
        raise exc.DGitError(f"no repo found: {target}")

    cmd_git_copy_changed.copy_changed_files(
        repo,
        Path(target),
        source_subdir,
        assume_yes=assume_yes,
        commit=commit,
    )


@exc.catch_our_errors()
def main():
    console.print(" wasp: ", style="bold yellow", end="")
    console.print("dblocks_core experimental features", style="bold")
    app()


if __name__ == "__main__":
    main()
