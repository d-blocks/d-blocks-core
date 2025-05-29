import copy
import importlib
import inspect
import json
import logging
import os
import pathlib
import pkgutil
import pprint
import sys

# tomllib je až od verze 3.11, tomli je backport pro starší verze Pythonu
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Iterable

import cattrs
import platformdirs
from cattrs import transform_error
from loguru import logger

import dblocks_plugin
from dblocks_core import exc
from dblocks_core.git import git
from dblocks_core.model import config_model, plugin_model

DBLOCKS_NAME = "d-blocks"
SECRETS_FILE = ".dblocks-secrets.toml"
DBLOCKS_FILE = "dblocks.toml"

DEFAULT = "default"

PROFILE_CONFIG_PATH = platformdirs.user_config_path(
    appauthor=DBLOCKS_NAME,
    appname=DBLOCKS_NAME,
)

PROFILE_DATA_PATH = platformdirs.user_data_path(
    appauthor=DBLOCKS_NAME,
    appname=DBLOCKS_NAME,
)

CONFIG_LOCATIONS = [
    pathlib.Path.cwd(),
    PROFILE_CONFIG_PATH,
    pathlib.Path.home(),  # fallback, previous versions of the tool
]


_PARTS_DELIMITER = "__"
_SECRETS = ["password"]
REDACTED = "<redacted>"
ENVIRON_PREFIX = "DBLOCKS_"
EXPECTED_CONFIG_VERSION = "1.0.0"

_LOGGING_WAS_SET = False


def __iter_namespace(ns_pkg):
    """
    Iterate over all modules in a given namespace package.

    Args:
        ns_pkg (ModuleType): The namespace package to iterate over.

    Returns:
        Iterator: An iterator over the modules in the namespace package.
    """
    return pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + ".")


__PLUGABLE_MODULES = {
    name: importlib.import_module(name)
    for finder, name, ispkg in __iter_namespace(dblocks_plugin)
}

__PLUGABLE_MODULES = {
    k: __PLUGABLE_MODULES[k] for k in sorted(__PLUGABLE_MODULES.keys())
}


def load_plugins(cfg: config_model.Config) -> dict[str, list[Callable]]:
    """
    Load and initialize all plugins under the dblocks_core.plugin namespace.

    Args:
        cfg (config_model.Config): The configuration object to pass to plugin initializers.

    Returns:
        dict[str, list[Callable]]: A dictionary mapping plugin module names to lists of plugin instances.
    """
    plugins = {}
    for name, plugin_module in __PLUGABLE_MODULES.items():
        if not hasattr(plugin_module, "PLUGINS"):
            logger.warning(f"{name}: does not contain PLUGINS variable")
            continue
        plugins[name] = getattr(plugin_module, "PLUGINS")

    for plug in plugins.values():
        for instance in plug:
            instance.dbe_init(cfg)
    return plugins


def plugin_instances(
    cfg: config_model.Config,
    class_,
) -> list[plugin_model._PluginInstance]:
    """
    Return a list of plugin instances of the specified base class.

    Args:
        cfg (config_model.Config): The configuration object.
        class_ (type | None): The base class to filter plugin instances by. If None, returns all.

    Returns:
        list[plugin_model._PluginInstance]: List of instantiated plugins of the specified class.
    """
    logger.trace(class_)
    plugin_modules = load_plugins(cfg)
    plugin_instances = []

    for plugin_name, pluggable_instances in plugin_modules.items():
        logger.trace(plugin_name)
        for plug_instance in pluggable_instances:
            logger.trace(plug_instance)
            if class_ is None or isinstance(plug_instance, class_):
                plugin_instances.append(
                    plugin_model._PluginInstance(
                        module_name=plugin_name,
                        class_name=plug_instance.__class__.__name__,
                        instance=plug_instance,
                    )
                )
            else:
                logger.trace("skipping the instance")

    logger.trace(plugin_instances)
    return plugin_instances


def get_environment_from_config(
    cfg: config_model.Config, environment: str
) -> config_model.EnvironParameters:
    """
    Retrieve environment parameters for a given environment name from the config.

    Args:
        cfg (config_model.Config): The configuration object.
        environment (str): The name of the environment to retrieve.

    Returns:
        config_model.EnvironParameters: The environment parameters.

    Raises:
        exc.DConfigError: If the environment is not found in the config.
    """
    try:
        return cfg.environments[environment]
    except KeyError:
        raise exc.DConfigError(
            f"Did not find envieonment: {environment}."
            f" Did you mean one of {list(cfg.environments.keys())}?"
        )


def load_config_dict(
    encoding: str = "utf-8",
    env_name_prefix: str = ENVIRON_PREFIX,
    environ: dict[str, Any] | None = None,
    *,
    from_filenames: Iterable[pathlib.Path] | None = None,
    from_directories: Iterable[pathlib.Path] | None = None,
) -> dict:
    """
    Load and merge configuration dictionaries from files and environment variables.

    Args:
        encoding (str): Encoding used to read config files. Defaults to "utf-8".
        env_name_prefix (str): Prefix for environment variables to include. Defaults to "DBLOCKS_".
        environ (dict[str, Any] | None): Environment variables to use. If None, uses os.environ.
        from_filenames (Iterable[pathlib.Path] | None): Specific config files to load. If None, uses defaults.
        from_directories (Iterable[pathlib.Path] | None): Directories to search for config files. If None, uses defaults.

    Returns:
        dict: The merged configuration dictionary.
    """
    config_dictionaries = []

    _directories = from_directories if from_directories else CONFIG_LOCATIONS
    if from_filenames is None:
        from_filenames = [pathlib.Path(d) for d in (DBLOCKS_FILE, SECRETS_FILE)]

    for conf_file_name in from_filenames:
        found = False
        for conf_dir in _directories:
            f = pathlib.Path(conf_dir) / conf_file_name
            try:
                content = f.read_text(encoding=encoding, errors="strict")
                data = tomllib.loads(content)
                config_dictionaries.append(data)
                found = True
            except FileNotFoundError:
                continue
        if not found:
            logger.warning(f"file not found: {conf_file_name}")

    # config from environ
    if environ is None:
        environ = {k: v for k, v in os.environ.items()}
    config_dictionaries.append(from_environ_dict(env_name_prefix, environ))

    # combine dictionaries
    config_dict = {}
    for c in config_dictionaries:
        config_dict = deep_merge_dicts(config_dict, c)

    return config_dict


def _copy_defaults(config_dict: dict):
    try:
        default_env = config_dict["environments"][DEFAULT]
    except KeyError:
        return

    _copy_these = [
        "platform",
        "writer",
        "host",
        "username",
        "password",
        "connection_parameters",
    ]

    for env_name, env_config in config_dict["environments"].items():
        for key in _copy_these:
            if key in default_env and key not in env_config:
                env_config[key] = default_env[key]
                logger.debug(f"copy default settings: {env_name}: {key}")


def load_config(
    encoding: str = "utf-8",
    env_name_prefix: str = ENVIRON_PREFIX,
    environ: dict[str, Any] | None = None,
    setup_logger: bool = True,
    *,
    from_filenames: Iterable[pathlib.Path] | None = None,
    from_directories: Iterable[pathlib.Path] | None = None,
) -> config_model.Config:
    """
    Load and validate the d-blocks configuration from files and environment variables.

    This function performs the following steps:
    1. Loads configuration data from a list of TOML files and merges it with environment variables.
    2. Validates the resulting configuration against the expected config version.
    3. Converts the merged dictionary into a strongly-typed Config model using cattrs.
    4. Resolves all important directory paths to absolute paths, relative to the git repo root or current working directory.
    5. Optionally sets up logging according to the configuration.
    6. Invokes plugin-based configuration checks for additional validation.

    If the environment contains:
        DBLOCKS_DATABASE__HOST=localhost
        DBLOCKS_DATABASE__PORT=5432

    The function fetches this as a dictionary with these keys and values:
        {
            'database': {
                'host': 'localhost',
                'port': '5432'
            }
        }

    Args:
        encoding (str): Encoding used to read config files. Defaults to "utf-8".
        env_name_prefix (str): Prefix for environment variables to include. Defaults to "DBLOCKS_".
        environ (dict[str, Any] | None): Environment variables to use. If None, uses os.environ.
        setup_logger (bool): Whether to configure logging based on the config. Defaults to True.
        from_filenames (Iterable[pathlib.Path] | None): Specific config files to load. If None, uses defaults.
        from_directories (Iterable[pathlib.Path] | None): Directories to search for config files. If None, uses defaults.

    Returns:
        config_model.Config: The validated and fully resolved configuration object.

    Raises:
        exc.DConfigError: If the config version is incorrect or the config structure is invalid.
    """
    # config from files
    cfg_dict = load_config_dict(
        encoding=encoding,
        env_name_prefix=env_name_prefix,
        environ=environ,
        from_filenames=from_filenames,
        from_directories=from_directories,
    )

    # check version
    _config_version = ""
    try:
        _config_version = cfg_dict["config_version"]
    except KeyError:
        pass

    if _config_version != EXPECTED_CONFIG_VERSION:
        message = (
            "Incorrect config version.\n"
            f"- expected: {EXPECTED_CONFIG_VERSION}\n"
            f"- got: {_config_version}"
        )
        raise exc.DConfigError(message)

    _copy_defaults(cfg_dict)

    try:
        cfg = cattrs.structure(cfg_dict, config_model.Config)
    except Exception as err:
        # try:
        #     _e = config_dict["extractor"]
        #     for env in _e["environments"]:
        #         if "password" in env:
        #             env["password"] = "<redacted>"
        # except KeyError:
        #     pass
        # logger.error(f"Error when processing config:\n{pprint.pformat(config_dict)}")
        #
        # https://catt.rs/en/stable/validation.html
        censored_config = _censore_keys(cfg_dict, _SECRETS)
        messages = transform_error(err)
        for suberror in messages:
            logger.error(suberror)
        logger.error(f"config in question:\n{pprint.pformat(censored_config)}")
        raise exc.DConfigError("\n".join(messages)) from None

    # Fix the directory structure. Make paths relative to either git repo, or to the working directory
    # (only if we are not in a git repo)
    repo_root = git.find_repo_root(Path.cwd())
    if repo_root is None:
        repo_root = Path.cwd()

    def _absolute(p: Path, default: Path | None = None):
        if default is not None and p is None or p == Path("."):
            p = default
        p = p if p.is_absolute() else p
        return p.resolve()

    # These paths ought to be relative to repo root, or cwd. Make them absolute.
    cfg.metadata_dir = _absolute(cfg.metadata_dir)
    cfg.package_dir = _absolute(cfg.package_dir)
    cfg.packager.package_dir = _absolute(
        cfg.packager.package_dir,
        cfg.package_dir,
    )
    for prms in cfg.environments.values():
        prms.writer.target_dir = _absolute(prms.writer.target_dir, cfg.metadata_dir)

    # config logger
    if setup_logger and cfg.logging:
        _setup_logger(cfg.logging)

    # use plugins to validate the config
    # class PluginCfgCheck
    plugin_modules = load_plugins(cfg)
    for plugin_name, pluggable_instances in plugin_modules.items():
        for plug_instance in pluggable_instances:
            if not isinstance(plug_instance, plugin_model.PluginCfgCheck):
                continue
            logger.info(f"calling: {plugin_name}.{plug_instance.__class__.__name__}")
            plug_instance.check_config()
    return cfg


def filter_dbi_interaction(record):
    """
    Filter log records to include only those with the 'TERADATA' log level.

    Args:
        record (dict): The log record to filter.

    Returns:
        bool: True if the record matches the 'TERADATA' log level, False otherwise.
    """
    return record["level"].no == logger.level("TERADATA").no


def add_logger_sink(
    sink: str | pathlib.Path,
    *,
    filter: Callable | None = filter_dbi_interaction,
    level: str = "DEBUG",
    format: str | None = None,
) -> int:
    """
    Add a new sink to the logging system and return its loguru handle.

    Args:
        sink (str | pathlib.Path): The sink to add (e.g., file path or stream).
        filter (Callable | None): Optional filter function for log records.
        level (str): Logging level for the sink.
        format (str | None): Optional log message format.

    Returns:
        int: The loguru sink handle ID.
    """
    _fmt = ("/* {time:HH:mm:ss} */ {message}") if format is None else format
    return logger.add(sink, format=_fmt, level=level, filter=filter)


def remove_logger_sink(id_: int):
    """
    Remove a logger sink by its ID.

    Args:
        id_ (int): The ID of the logger sink to remove.
    """
    logger.remove(id_)


def _setup_logger(logconf: config_model.LoggingConfig | None):
    """
    Configure the loguru logger according to the provided logging configuration.

    Args:
        logconf (config_model.LoggingConfig | None): The logging configuration object.
    """
    global _LOGGING_WAS_SET
    if not logconf:
        return

    # do not add the same sink twice
    if _LOGGING_WAS_SET:
        return

    # default sink is guaranteed to have the index 0
    # remove the default sink and recreate it
    try:
        logger.remove(0)
    except ValueError:
        pass

    # _name_first_part = __name__.split(".")[0] + "."
    # https://loguru.readthedocs.io/en/stable/api/logger.html - The record dict
    # def _formatter(record: dict[str, str]) -> str:
    #     name = record["name"].replace(_name_first_part, "")
    #     return (
    #         "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    #         "| <level>{level: <8}</level> "
    #         "| <cyan>" + name + "</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
    #         "- <level>{message}</level>\n"
    #     )

    _fmt = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> "
        "| <cyan>{function}</cyan> - <level>{message}</level>"
    )
    logger.add(sys.stderr, level=logconf.console_log_level, format=_fmt)

    for k, v in logconf.other_sinks.items():
        kwargs = {
            "sink": v.sink,
            "serialize": v.serialize,
            "rotation": v.rotation,
            "retention": v.retention,
            "level": v.level,
        }
        if v.format:
            kwargs["format"] = v.format
        logger.add(**kwargs)

    # intercept calls to stdlib logging
    logging.basicConfig(handlers=[_LoggingInterceptHandler()], level=0, force=True)
    _LOGGING_WAS_SET = True


def _censore_keys(
    data: dict,
    censored_keys: list[str],
    placeholder: str = REDACTED,
) -> dict:
    """
    Recursively replace sensitive keys in a dictionary with a placeholder value.

    Args:
        data (dict): The dictionary to censor.
        censored_keys (list[str]): List of keys to censor.
        placeholder (str): The value to use for censored keys.

    Returns:
        dict: The censored dictionary.
    """

    def _censore_values(data_: dict[str, Any]):
        for k, v in data_.items():
            if k in censored_keys:
                data_[k] = placeholder
            if isinstance(v, dict):
                _censore_keys(v, censored_keys, placeholder)

    _censore_values(data)
    return data


def cfg_to_censored_json(cfg: config_model.Config) -> str:
    """
    Convert a config object to a JSON string with sensitive keys censored.

    Args:
        cfg (config_model.Config): The configuration object.

    Returns:
        str: The censored JSON string.
    """
    data = cattrs.unstructure(cfg)
    logger.trace("censoring config ...")
    _censore_keys(data, _SECRETS)
    censored_str = json.dumps(data, indent=4)
    return censored_str


def from_environ_dict(
    env_name_prefix: str,
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Extract configuration from environment variables based on a specified prefix.

    This function retrieves environment variables that start with a given prefix,
    removes the prefix, and organizes the remaining key names into a nested
    dictionary structure. It allows for easy access to configuration values
    derived from environment variables.

    Args:
        env_name_prefix (str): The prefix used to filter environment variable names.
        env (dict[str, Any] | None): A dictionary representing environment variables.
            If None, defaults to using the current environment variables.

    Returns:
        dict[str, Any]: A nested dictionary containing the configuration values
        extracted from the environment variables.

    Example:
        If the environment contains:
            DBLOCKS_DATABASE__HOST=localhost
            DBLOCKS_DATABASE__PORT=5432

        The function will return:
            {
                'database': {
                    'host': 'localhost',
                    'port': '5432',
                }
            }
    """
    env_name_prefix = env_name_prefix.lower()
    ret_val = {}
    if env is None:
        _env = {k: v for k, v in os.environ.items()}
    else:
        _env = env

    for k, v in _env.items():
        k = k.lower()
        if not k.startswith(env_name_prefix):
            continue
        k = k.removeprefix(env_name_prefix)

        # split key name by double undercores
        # build a dictionary from it
        key_parts = k.split(_PARTS_DELIMITER)
        write_to = ret_val
        for i, kp in enumerate(key_parts):
            if i == len(key_parts) - 1:
                write_to[kp] = v
            else:
                if kp not in write_to:
                    write_to[kp] = {}
                write_to = write_to[kp]
    return ret_val


def deep_merge_dicts(
    dict1: dict[Any, Any],
    dict2: dict[Any, Any],
) -> dict[Any, Any]:
    """
    Recursively merge two dictionaries.

    If both dictionaries have the same key and the values corresponding to that key are themselves dictionaries,
    those dictionaries are merged recursively. Otherwise, the value from dict2 overwrites the value from dict1.

    Args:
        dict1 (dict[Any, Any]): The first dictionary to merge.
        dict2 (dict[Any, Any]): The second dictionary to merge.

    Returns:
        dict[Any, Any]: A new dictionary containing the merged result.
    """
    result = copy.deepcopy(dict1)
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _ensure_path(f: str | pathlib.Path) -> pathlib.Path:
    """
    Ensure the input is converted to a pathlib.Path object.

    Args:
        f (str | pathlib.Path): The input file path.

    Returns:
        pathlib.Path: The converted pathlib.Path object.

    Raises:
        TypeError: If the input is neither a string nor a pathlib.Path.
    """
    if isinstance(f, pathlib.Path):
        return f
    if isinstance(f, str):
        return pathlib.Path(f)
    raise TypeError(f"parameter is neither str nor pathlib.Path: {type(f)}")


class _LoggingInterceptHandler(logging.Handler):
    """
    A logging handler that intercepts standard library logging calls
    and redirects them to Loguru.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record to Loguru.

        Args:
            record (logging.LogRecord): The log record to emit.
        """
        # Get corresponding Loguru level if it exists.
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def get_installed_version(package_name: str = "d-blocks-core") -> str:
    """
    Get the installed version of the specified package.

    Args:
        package_name (str): The name of the package to check.

    Returns:
        str: The installed version string, or "Package not found" if not installed.
    """
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return "Package not found"
