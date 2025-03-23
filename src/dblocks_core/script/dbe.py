import sys
from datetime import datetime
from pathlib import Path
from time import sleep

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from typing_extensions import Annotated

from dblocks_core import context, dbi, exc, writer
from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.git import git
from dblocks_core.model import plugin_model
from dblocks_core.parse import prsr_simple
from dblocks_core.script.workflow import (
    cmd_deployment,
    cmd_extraction,
    cmd_git_copy_changed,
    cmd_init,
    cmd_pkg_deployment,
    cmd_quickstart,
)

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

console = Console()


@app.command()
def init():
    """Initialize current directory (git init, basic config files, gitignore)."""
    cmd_init.make_init()


@app.command()
def env_test_connection(environment: str):
    """Connection test for configured environment."""
    cfg = config.load_config()
    env = config.get_environment_from_config(cfg, environment)
    ext = dbi.extractor_factory(env)
    ext.test_connection()


@app.command()
def env_list():
    """Display list of configured environments."""
    cfg = config.load_config()

    console.print("These environments exist:", style="bold")

    table = Table(title="List of environments")
    for _h in ("environment name", "host", "user"):
        table.add_column(_h)
    for env_name, cfg in cfg.environments.items():
        table.add_row(env_name, cfg.host, cfg.username)
    console.print(table)


@app.command()
def env_extract(
    environment: Annotated[
        str,
        typer.Argument(
            help="Name of the environment you want to extract. "
            "The environment must be configured in dblocks.toml."
        ),
    ],
    *,
    since: Annotated[
        str | None,
        typer.Option(
            help="How long history do we want to process. "
            "Here you define the duration which will be substracted from current time "
            "to get the datetime, that is used to filter changes - only tables that "
            "were changed (or created) after this date will be extracted. "
            "Examples of the input you can use:\n"
            "commit (meaning since last commit date) "
            "1d (one day), "
            "2w (two weeks), "
            "3m (3 three months).",
        ),
    ] = None,
    assume_yes: Annotated[
        bool, typer.Option(help="Do not ask for confirmations.")
    ] = False,
    commit: Annotated[bool, typer.Option(help="Commit changes to the repo.")] = True,
    countdown_from: Annotated[
        int,
        typer.Option(
            help="Countdown untill start, after confirmation, "
            "if full extraction was requested."
        ),
    ] = 10,
    filter_databases: Annotated[
        str | None,
        typer.Option(
            help="Mask of databases that will be extracted. "
            "The '%' sign means 'any number of any characters'."
        ),
    ] = None,
    filter_names: Annotated[
        str | None,
        typer.Option(
            help="Mask of tables that will be extracted. "
            "The '%' sign means 'any number of any characters'."
        ),
    ] = None,
    filter_creator: Annotated[
        str | None,
        typer.Option(
            help="Mask of the user who created the object. "
            "The '%' sign means 'any number of any characters'."
        ),
    ] = None,
):
    """
    Extraction of the database based on an environment name. The extraction can be
    either full, or incremental, based on the --since flag.
    """
    cfg = config.load_config()

    # repo, check if it is dirty
    repo = git.repo_factory(raise_on_error=True)
    if repo is not None and repo.is_dirty():
        logger.warning("Repo is not clean!")
        console.print(
            "Repo is not clean!\n"
            "Extraction will not run, unless it is continuation of previously "
            "unfinished process.",
            style="bold red",
        )

    # attempt to get information about the history length
    since_dt: None | datetime = None
    if since is not None:
        if "commit" in since:
            if repo is None:
                raise exc.DOperationsError("git repo not found")
            since_dt = repo.last_commit_date()
            if since_dt is None:
                raise exc.DOperationsError("no commit found")
            since_dt = since_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            since_dt = prsr_simple.parse_duration_since_now(since)
        logger.info(
            "extract objects changed after: " + since_dt.strftime("%Y-%m-%d %H:%M:%S")
        )
    elif not assume_yes:
        really = Prompt.ask(
            "This process has a few risks:"
            "\n- it can run for a long time and could leave the repo in incosistent "
            "state."
            "\n- directories that represent databases which are subject to extraction "
            "will be dropped."
            "\n\nYou could run incremental extraction using --since flag instead."
            "\nIf this is the first time you run the xtraction, answer yes."
            "\nAre you sure you want to run this? (yes/no)",
            default="no",
        ).strip()
        if really != "yes":
            logger.error(f"action canceled by prompt: {really}")

            sys.exit(1)

        # countdown
        for i in range(countdown_from, -1, -1):
            console.print(f"{i} ...", style="bold red")
            sleep(1)

    env = config.get_environment_from_config(cfg, environment)
    ext = dbi.extractor_factory(env)
    wrt = writer.create_writer(env.writer)
    with context.FSContext(
        name="command-extract",
        directory=cfg.ctx_dir,
    ) as ctx:
        cmd_extraction.run_extraction(
            ctx=ctx,
            env=env,
            ext=ext,
            wrt=wrt,
            repo=repo,
            env_name=environment,
            filter_since_dt=since_dt,
            commit=commit,
            filter_databases=filter_databases,
            filter_names=filter_names,
            filter_creator=filter_creator,
        )
    ctx.done()


# FIXME: by default, if the directory is not given by the user, ask him if he wants to deploy everything
@app.command()
def env_deploy(
    environment: Annotated[
        str,
        typer.Argument(
            help="Name of the environment you want to extract. "
            "The environment must be configured in dblocks.toml."
        ),
    ],
    path: Annotated[
        str,
        typer.Argument(
            help="Points to the directory under ./meta, defines scope of the deployment."
        ),
    ],
    assume_yes: Annotated[
        bool, typer.Option(help="USE CAREFULLY. Do not ask for confirmation.")
    ] = False,
    countdown_from: Annotated[
        int, typer.Option(help="How long do we wait after confirmation was given.")
    ] = 3,
    if_exists: Annotated[
        str,
        typer.Option(
            help="What to do if the object we try to deploy exists: raise/rename/drop"
        ),
    ] = "raise",
    delete_databases: Annotated[
        bool,
        typer.Option(
            help="USE CAREFULLY. Do we delete all objects from all databases in the batch?"
        ),
    ] = False,
    log_each: Annotated[int, typer.Option(help="Log every n-th object")] = 20,
):
    """
    Deploy all objects from a directory to the environment, regardless of dependencies.
    Potentially destructive action. Not to be confused with pkg-deploy.
    """
    # prepare config
    cfg = config.load_config()
    env = config.get_environment_from_config(cfg, environment)
    deploy_dir = Path(path)

    # sanity check
    if not deploy_dir.is_dir():
        message = f"not a dir: {deploy_dir.as_posix()}"
        raise exc.DOperationsError(message)

    logger.warning("starting deployment")

    with context.FSContext(
        name=f"command-deploy-{environment}",
        directory=cfg.ctx_dir,
        no_exception_is_success=False,  # we have to confirm context deletion "by hand"
    ) as ctx:
        ext = dbi.extractor_factory(env)
        failures = cmd_deployment.deploy_env(
            deploy_dir,
            cfg=cfg,
            env=env,
            env_name=environment,
            ctx=ctx,
            ext=ext,
            log_each=log_each,
            if_exists=if_exists,
            delete_databases=delete_databases,
            assume_yes=assume_yes,
            countdown_from=countdown_from,
        )

        cmd_deployment.make_report(cfg.report_dir, environment, failures)
        if len(failures) == 0:
            console.print("Successful run", style="bold green")
            ctx.done()
        else:
            console.print("DONE with errors", style="bold red")
            console.print("We do NOT delete context.")


@app.command()
def pkg_from_diff(
    diff_against: Annotated[
        str, typer.Argument(help="Diff against 'branch' or 'commit'.")
    ],
    diff_ident: Annotated[
        str,
        typer.Argument(help="Baseline - either name of the branch, or commit hash."),
    ],
    package_name: Annotated[
        str,
        typer.Argument(help="Name of the package we will prepare."),
    ],
    include_only: Annotated[
        list[str],
        typer.Option(
            help="Name of the subdirectory that should be kept in he diff. "
            "If not provided, keep everything."
        ),
    ] = None,
):
    cfg = config.load_config()
    repo = git.repo_factory(raise_on_error=True)

    cmd_git_copy_changed.copy(
        repo,
        diff_against,
        diff_ident,
        metadata_dir=cfg.metadata_dir,
        pkg_dir=cfg.packager.package_dir,
        package_name=package_name,
        steps_subdir=cfg.packager.steps_subdir,
        include_only=include_only,
    )


@app.command()
def pkg_deploy(
    environment: Annotated[
        str,
        typer.Argument(
            help="Name of the environment you want to extract. "
            "The environment must be configured in dblocks.toml."
        ),
    ],
    path: Annotated[str, typer.Argument(help="Path to the package.")],
    dry_run: Annotated[
        bool,
        typer.Option(
            help="Dry run only simulates deployment but does not change state "
            "of the environment."
        ),
    ] = False,
    assume_yes: Annotated[
        bool, typer.Option(help="USE CAREFULLY. Do not ask for confirmation.")
    ] = False,
    countdown_from: Annotated[
        int, typer.Option(help="How long do we wait after confirmation was given.")
    ] = 3,
    if_exists: Annotated[
        str,
        typer.Option(
            help="What to do if the object we try to deploy exists: raise/rename/drop"
        ),
    ] = "raise",
):
    """
    Package deployment to the specified environment.
    """
    # prepare config
    cfg = config.load_config()
    env = config.get_environment_from_config(cfg, environment)
    pkg_path = Path(path)
    pkg_name = pkg_path.name

    # sanity check
    if not pkg_path.is_dir():
        message = f"not a dir: {pkg_path.as_posix()}"
        raise exc.DOperationsError(message)

    # context
    ctx_dir = pkg_path / "ctx"
    ctx_dir.mkdir(exist_ok=True)

    # tagger
    logger.info(pkg_path)
    with context.FSContext(
        name=f"pkg-deploy-{pkg_name}@{environment}",
        directory=ctx_dir,
        no_exception_is_success=False,  # we have to confirm context deletion "by hand"
    ) as ctx:
        ext = dbi.extractor_factory(env)
        cmd_pkg_deployment.cmd_pkg_deploy(
            pkg_path,
            pkg_cfg=cfg.packager,
            env_cfg=env,
            ctx=ctx,
            if_exists=if_exists,
            dry_run=dry_run,
        )


@app.command()
def cfg_check():
    """Checks configuration files, without actually doing 'anything'."""
    cfg = config.load_config()

    # give me ALL plugins
    all_plugins = config.plugin_instances(class_=None)
    for plugin_instance in all_plugins:
        logger.info(
            f"- existing plugin: {plugin_instance.module_name}.{plugin_instance.class_name}"
        )

    hello_plugins = config.plugin_instances(plugin_model.PluginHello)
    for plug_instance in hello_plugins:
        logger.info(f"calling: {plug_instance.module_name}.{plug_instance.class_name}")
        hello_callable: plugin_model.PluginHello = plug_instance.instance
        retval = hello_callable.hello()
        logger.info(f"{plug_instance.module_name}.{plug_instance.class_name}: {retval}")

    validator_plugins = config.plugin_instances(plugin_model.PluginCfgCheck)
    for validator in validator_plugins:
        logger.info(f"calling: {validator.module_name}.{validator.class_name}")
        validator_callable: plugin_model.PluginCfgCheck = validator.instance
        validator_callable.check_config(cfg)

    logger.info("OK")


@app.command()
def cfg_print():
    """Print the config (censore passwords)"""
    cfg = config.load_config()
    cfg_json = config.cfg_to_censored_json(cfg)
    console.print_json(cfg_json)


@app.command()
def ctx_list():
    """List all contexts."""
    cfg = config.load_config()
    ctx_dir = cfg.ctx_dir

    if not ctx_dir.exists():
        logger.warning(f"context dir not found at {ctx_dir.resolve()}")
        ctx_dir = context.find_ctx_root(context_dir_name=ctx_dir.name)
        if ctx_dir is None:
            logger.error("failed to find context dir")
            sys.exit(1)
        else:
            logger.warning(f"assuming: {ctx_dir.resolve()}")

    files = []
    for ctx_file in ctx_dir.iterdir():
        if not ctx_file.is_file():
            continue
        if ctx_file.suffix != ".json":
            continue
        files.append(ctx_file)

    if len(files) == 0:
        console.print("No contexts found", style="bold red")

    console.print("These context files were found:", style="bold")
    for ctx_file in files:
        console.print(ctx_file.as_posix())


@app.command()
def ctx_drop(
    ctx: str,
):
    """Deletes a context"""
    config.load_config()
    ctx_file = Path(ctx)
    if not ctx_file.exists():
        logger.error(f"context does not exist: {ctx_file.as_posix()}")
        sys.exit(1)

    # confirm
    console.print(f"You are about to drop the context {ctx_file.as_posix()}.")
    really = Prompt.ask("Are you sure? (yes/no)", default="no").strip()
    if really != "yes":
        logger.error(f"action canceled by prompt: {really}")
        sys.exit(1)
    ctx_file.unlink()


@app.command()
def quickstart():
    """Quickstart on demo repository (https://github.com/d-blocks/d-blocks-demo/blob/main/README.md)"""
    cmd_quickstart.quickstart()


@app.command()
def walk(
    path: Annotated[str, typer.Argument(help="Path - either directory or a file.")],
    plugin: Annotated[
        str,
        typer.Argument(help="Name of the walker to be called (case insensitive)."),
    ],
    environment: Annotated[
        str | None,
        typer.Argument(
            help="Name of the environment you want to extract. "
            "The environment must be configured in dblocks.toml."
        ),
    ] = None,
):
    """Executes a plugin on top of a file or directory."""
    cfg_dict = config.load_config_dict()
    cfg = config.load_config()
    all_walkers = config.plugin_instances(plugin_model.PluginWalker)
    if len(all_walkers) == 0:
        logger.error(
            "No walkers found, did you install the plugin you are trying to use?"
        )
        sys.exit(1)

    walkers = [w for w in all_walkers if w.class_name.lower() == plugin.lower()]
    if len(walkers) == 0:
        logger.error(
            f"No walkers if this name found: {plugin}; did you install the plugin you are trying to use?"
        )
        sys.exit(1)
    elif len(walkers) > 1:
        logger.warning(f"Expected to get 1 walker, got {len(walkers)}: {plugin}")

    path_ = Path(path)

    # walk
    for walker in walkers:
        logger.info(f"before: {walker.module_name}.{walker.class_name}")
        walker_callable: plugin_model.PluginWalker = walker.instance
        walker_callable.before(
            path_,
            environment,
            cfg,
            # kwargs
            cfg_dict=cfg_dict,
        )

        logger.info(
            f"walking: {walker.module_name}.{walker.class_name}: {path_.as_posix()}"
        )
        if path_.exists():
            if path_.is_file():
                walker_callable.walker(
                    path_,
                    environment,
                    cfg,  # kwargs
                    cfg_dict=cfg_dict,
                )
            elif path_.is_dir():
                for f in path_.rglob("*.*"):
                    walker_callable.walker(
                        f,
                        environment,
                        cfg,  # kwargs
                        cfg_dict=cfg_dict,
                    )

        logger.info(f"after: {walker.module_name}.{walker.class_name}")
        walker_callable.after(
            path_,
            environment,
            cfg,
            # kwargs
            cfg_dict=cfg_dict,
        )


@app.command()
def version():
    """Print d-blocks-core version."""
    console = Console()
    console.print("Version: ", style="blue bold", end="")
    console.print(config.get_installed_version())


@exc.catch_our_errors()
def main():
    app()


if __name__ == "__main__":
    main()
