# flake8: ignore=F401,E501

import os
from pathlib import Path
from textwrap import dedent

from rich.console import Console
from rich.prompt import Prompt

from dblocks_core.config import config
from dblocks_core.config.config import logger
from dblocks_core.git import git

IGNORE = [
    config.SECRETS_FILE,
    "context/",
    # environments
    ".env",
    ".venv",
    "env/",
    "venv/",
    "ENV/",
    "env.bak/",
    "venv.bak/",
    # Byte-compiled / optimized / DLL files
    "__pycache__/",
    "*.py[cod]",
    "*$py.class",
    "# C extensions",
    "*.so",
    # log files
    "*.log",
]


def make_init(
    config_file_name: str = config.DBLOCKS_FILE,
    secrets_file_name: str = config.SECRETS_FILE,
):
    # prep paths to two basic configuration files
    cwd = Path.cwd()
    home_config = config.PROFILE_CONFIG_PATH
    context_dir = config.PROFILE_DATA_PATH / "ctx"
    report_dir = config.PROFILE_DATA_PATH / "report"
    debug_log_file = config.PROFILE_DATA_PATH / "log"

    dblocks_toml = get_default_config(context_dir, report_dir, debug_log_file)
    secrets_toml = 'environments.dev.password = "__password__"'

    # create default config, if config files do not exist
    console = Console()
    console.print("Configuration location", style="bold")
    console.print("Config files can be stored either in:")
    console.print(f"a) in a user profile ({str(home_config)})")
    console.print("b) current directory, or")

    _location = ""
    while _location not in ("a", "b"):
        _location = (
            Prompt.ask(
                "Which location should be used? (a/b)",
                default="a",
            )
            .strip()
            .lower()
        )

    if _location == "a":
        dblocks_file = home_config / config_file_name
        secrets_file = home_config / secrets_file_name
    else:
        dblocks_file = cwd / config_file_name
        secrets_file = cwd / secrets_file_name

    if not dblocks_file.is_file():
        dblocks_file.parent.mkdir(exist_ok=True)
        logger.info(f"write default config to: {dblocks_file.as_posix()}")
        dblocks_file.write_text(dblocks_toml, encoding="utf-8")
        os.chmod(dblocks_file, 0o600)
    else:
        logger.debug(f"skipping file: {dblocks_file.as_posix()}")

    if not secrets_file.is_file():
        secrets_file.parent.mkdir(exist_ok=True)
        logger.info(f"write secrets to: {dblocks_file.as_posix()}")
        secrets_file.write_text(secrets_toml, encoding="utf-8")
        os.chmod(secrets_file, 0o600)
    else:
        logger.debug(f"skipping file: {secrets_file.as_posix()}")

    # check if this is a git repo, check contents of gitignore
    # patch the gitignore so that it contains default ignored items
    _really = ""
    while _really not in ("y", "n"):
        _really = Prompt.ask("run git config? (y/n)", default="y").strip().lower()
    if _really == "y":
        make_git_repo(cwd)
        patch_gitignore(cwd)


def make_git_repo(in_dir: Path):
    repo = git.Repo(in_dir, raise_on_error=False)
    repo.init()


def patch_gitignore(in_dir: Path):
    repo = git.find_repo_root(in_dir)
    if not repo:
        logger.warning("not in a git repo, gitignore file is not changed")
        return

    gitignore = repo / ".gitignore"
    if not gitignore.is_file():
        logger.warning(f"creating empty gitignore file: {gitignore.as_posix()}")
        gitignore.write_text("")

    lines = gitignore.read_text(encoding="utf-8").splitlines()
    orig_len = len(lines)
    for ignored in IGNORE:
        if ignored not in lines:
            logger.warning(f"adding line to .gitignore: {ignored}")
            lines.append(ignored)

    if len(lines) != orig_len:
        logger.warning(f"writing to .gitignore: {gitignore.as_posix()}")
        gitignore.write_text("\n".join(lines), encoding="utf-8")


def get_default_config(
    context_dir: Path,
    report_dir: Path,
    debug_log_file: Path,
) -> str:
    return dedent(
        f"""
        # this value is important to keep track of changes of the configuration schema
        # do not change, unless you are migrating to a different version of dbe utility
        config_version = "1.0.0"

        # context directrory
        # this is the directory, where checkpoints are stored in JSON format
        # checkpoints support restartability of long lasting operations
        # the directory should NOT be version controlled
        ctx_dir = "{context_dir.as_posix()}"

        # report directory - where reports can be stored
        # the directory should NOT be version controlled
        report_dir = "{report_dir.as_posix()}"


        [ logging ]
        # we are using loguru library, see https://loguru.readthedocs.io/en/stable/ 
        # for more details.
        
        # by default, only send messages with severity of INFO and higher to STDERR
        # see https://loguru.readthedocs.io/en/stable/api/logger.html#sink for more details
        # available log levels are: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
        console_log_level = "INFO"

        # configure one other sink, named debug_sink
        # see https://loguru.readthedocs.io/en/stable/api/logger.html#sink for more details

        # log also to a file
        other_sinks.debug_sink.sink = "{debug_log_file.as_posix()}"

        # log file only contains messages with severity of DEBUG and higher
        # available log levels are: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
        # we recommend to keep this set to DEBUG, and only use TRACE to prepare diagnostic
        # output for reporting a bug
        other_sinks.debug_sink.level = "DEBUG"

        # optionally, serialize each message, so that it can be easily ingested from JSON
        # available values are: true, false
        other_sinks.debug_sink.serialize = false

        # rotate log file every 5 days
        other_sinks.debug_sink.rotation = "5 days"

        # retention of obsolete logs after 15 days
        other_sinks.debug_sink.retention = "15 days"

        #
        # configuration of environments, each environment has a dedicated section
        # name of the environment is after the "dot", and MUST be in lowercase
        [ environments.dev ]

        # target platform for this env is Teradata
        platform = "teradata"

        # git branch we use to track this environment
        git_branch = "main"

        # here we define connection parameters
        # about handling of passwords: please note: additional parameter with name "password" exists
        # password, however, should NEVER be stored in plain text in the repo, so that
        # we do not risk committing the password to the repo
        # it is recommended to set it using environment variable, like so:
        #"""
        """
        # export DBLOCKS_ENVIRONMENTS__{env_name}__PASSWORD=__the_password__
        # for example: given that this environment is named "dev"
        # we would use variable named DBLOCKS_ENVIRONMENTS__EP__PASSWORD
        #
        # name of the environment variable MUST be in uppercase
        #
        # alternatively, you can use file .secrets.toml, and store the password there
        # this is not recommended for production use cases, but can be valid for 
        # development; the file (.secrets.toml) would in our case contain 
        # only the following line:
        # environments.dev.password = "__the password__"
        host = "__hostname__"
        username = "__username__"
        connection_parameters.logmech = "TD2" # TLDAP / TD2
        
        # IMPORTANT! Read how Teradata handless ANSI and TERA modes
        # with regard to stored procedures (and how it influences 
        # string comparison semantic)
        # we strongly recommend you to investigate what is the used mode 
        # in your environment, and stick with it        
        connection_parameters.tmode = "TERA" # TERA, ANSI
        

        # configuration of the writer for this environment
        writer.target_dir = "./meta/teradata"

        # configuration of scope of extraction for this environment
        # please note: you can use root containers here; all databases
        #              that are UNDER the root container are then in scope
        #
        # please note: extractor creates hierarchical structure for each database,
        #              that the database configured in the list is the root of the hierarchy;
        #              this means that listing "leaf" databases here leads to FLAT
        #              directory structure - that could be something you do not expect.        
        extraction.databases = [ "leaf_database_1", "root_container_2", "root_container_3" ]

        # tagging rules for this environment
        # this section defines how names of databases are transcribed
        # to their "neutral" form
        # the first rule that matches name of the database is used
        #
        # please note that these rules contain names of variables that are
        # configured below"""
        """
        tagging_rules = [
            "{{env_db}}%",                  # rule used for databases - take note that env_db=P01 (below)
            "{{env_usr}}%",                 # rule used for users - take note that env_db=UP01 (below)
        ]

        # ------------------------------------------------------------------------------------------------------------
        # WHAT does it mean, in effect?
        # Given:
        #   database name P01_TGT (production target)
        #   load user UAP01_LOAD (production load user)
        # Given config:
        #   tagging_rules = [ "{{env_db}}%", "{{env_usr}}%" ]   - this defines naming schema for your databases and users
        #   environments.dev.tagging_variables.env_db  = "P01"  - prefix for database name is "production 1" (P01)
        #   environments.dev.tagging_variables.end_usr = "UP01" - prefix for database name is "production 1" (P01)
        #
        # Resulting names will be:
        #   {{env_db}}_TGT                                      - prefix P01  is transformed to tag {{env_db}}
        #   {{env_usr}}_LOAD                                    - prefix UP01 is transformed to tag {{env_usr}}

        
        # if no tagging rules are present (tagging_rules = []), we could strip name of the database
        # from the definition; this can potentially be usefull in deployments where no tagging is implemented,
        # and deployment is entirely based on assumption that the DDL script does not contain
        # fully qualified name od the object - which means that the deployment is always done to the
        # "current", default database, used for the session.
        #
        # allow this behaviour?
        tagging_strip_db_with_no_rules = false

        # configuration of tagging variables for the environment
        [ environments.dev.tagging_variables ]        
        env_db = "P01"                      # covers names such as P01_TGT, P01_STG, etc.
        env_usr = "UP01"                    # covers names such as UP01_LOAD, UP01_MAINT, etc.

        [ packager ]        
        # package directory - where newly created packages are stored
        # this directory SHOULD BE version controlled; 
        # can be in completely different direcxtory (different repo)
        package_dir = "./pkg"

        # every package will store deployment steps under this subdir
        steps_subdir = "db/teradata"

        # in case where we attempt to overwrite existing package, we assume
        # that it is safe to delete package directory, if it contains less then N files
        # racionale: we really, really do not want to drop entire gir repo (or worse)
        #            by accident!
        safe_deletion_limit = 50

        # if deletion of the directory is not safe, we either
        #   a) ask if we want to proceed (interactive = true), or
        #   b) throw an exception (interactive = false)
        interactive = true
                
"""
    )
