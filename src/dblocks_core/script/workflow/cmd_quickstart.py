import sys
from datetime import datetime
from pathlib import Path
from time import sleep

import typer
from rich.console import Console

from dblocks_core import dbi, tagger
from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.dbi import AbstractDBI
from dblocks_core.deployer import tokenizer
from dblocks_core.git import git
from dblocks_core.model import config_model
from dblocks_core.parse import prsr_simple
from dblocks_core.script.workflow import cmd_deployment, cmd_extraction, cmd_init

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

console = Console()


def quickstart():
    # check that we are in the directory with demo data
    config_file = Path("dblocks.toml")
    demo_file = Path("this-is-demo-repo")
    if not config_file.is_file() or not demo_file.is_file():
        console.print(
            "Quickstart should be executed against directory with demo data only.",
            style="bold red",
        )
        console.print("Visit the following address to learn more:")
        console.print(
            "https://github.com/d-blocks/d-blocks-demo/blob/main/README.md",
            style="underline blue",
        )
        sys.exit(1)

    # load the configuration
    demo_env_name = "d-blocks-demo"
    cfg = config.load_config()
    env = config.get_environment_from_config(cfg, demo_env_name)
    tgr = tagger.Tagger(
        variables=env.tagging_variables,
        rules=env.tagging_rules,
        tagging_strip_db_with_no_rules=env.tagging_strip_db_with_no_rules,
    )
    ext = dbi.extractor_factory(env)

    # odjedu sadu statementů v konstrukci prostředí do demo databáze
    env_file = Path("env-init") / "demo_env_init.sql"
    if not env_file.is_file():
        console.print("ERROR: Definition file not found.", style="bold red")
        sys.exit(1)

    # řeknu že success
    content = env_file.read_text(encoding="utf-8")
    statements = tokenizer.tokenize_statements(content)

    for s in statements:
        s = tgr.expand_statement(s)
        ext.deploy_statements([s])
