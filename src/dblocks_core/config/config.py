import copy
import inspect
import json
import logging
import os
import pathlib
import pprint
import sys

# tomllib je až od verze 3.11, tomli je backport pro starší verze Pythonu
import tomllib
from importlib import metadata
from typing import Any, Iterable

import cattrs
from cattrs import transform_error
from loguru import logger

from dblocks_core import exc
from dblocks_core.model import config_model

SECRETS_FILE = ".dblocks-secrets.toml"
DBLOCKS_FILE = "dblocks.toml"


CONFIG_LOCATIONS = [
    pathlib.Path.cwd(),
    pathlib.Path.home(),
]
_PARTS_DELIMITER = "__"
_SECRETS = ["password"]
REDACTED = "<redacted>"
ENVIRON_PREFIX = "DBLOCKS_"
EXPECTED_CONFIG_VERSION = "1.0.0"


def get_environment_from_config(
    cfg: config_model.Config, environment: str
) -> config_model.EnvironParameters:
    try:
        return cfg.environments[environment]
    except KeyError:
        raise exc.DConfigError(
            f"Did not find envieonment: {environment}."
            f" Did you mean one of {list(cfg.environments.keys())}?"
        )


def load_config(
    encoding: str = "utf-8",
    env_name_prefix: str = ENVIRON_PREFIX,
    environ: dict[str, Any] | None = None,
    setup_config: bool = True,
    *,
    locations: Iterable[pathlib.Path] | None = None,
) -> config_model.Config:
    """
    Load configuration from specified files and environment variables.

    This function reads configuration data from a list of files and merges it with
    environment variables. It supports loading configuration in TOML format and
    validates the resulting configuration against a predefined model.

    Parameters:
    - files (list[str | pathlib.Path] | None): A list of file paths from which to
    load configuration. If None, defaults to an empty list.
    - encoding (str): The character encoding to use when reading files. Defaults
    to 'utf-8'.
    - env_name_prefix (str): The prefix used to filter environment variables for
    configuration. Defaults to 'DBLOCKS_'.
    - env (dict[str, Any] | None): A dictionary representing environment variables.
    If None, defaults to using the current environment variables.

    Handling of env variables:

    This function retrieves environment variables that start with a given prefix,
    removes the prefix, and organizes the remaining key names into a nested
    dictionary structure. It allows for easy access to configuration values
    derived from environment variables.

    Example for env variables:

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

    Returns:
    - config_model.Config: An instance of the Config model populated with the
    merged configuration data.

    Raises:
    - TypeError: If there is an issue with the file paths or reading the files.
    - cattrs.ClassValidationError: If the merged configuration does not conform
    to the expected structure of the Config model.
    """
    # config from files
    config_dictionaries = []
    if locations is None:
        locations = [pathlib.Path(d) for d in (DBLOCKS_FILE, SECRETS_FILE)]

    for conf_file_name in locations:
        found = False
        for conf_dir in CONFIG_LOCATIONS:
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

    # check version
    _config_version = ""
    try:
        _config_version = config_dict["config_version"]
    except KeyError:
        pass

    if _config_version != EXPECTED_CONFIG_VERSION:
        message = (
            "Incorrect config version.\n"
            f"- expected: {EXPECTED_CONFIG_VERSION}\n"
            f"- got: {_config_version}"
        )
        raise exc.DConfigError(message)

    try:
        config = cattrs.structure(config_dict, config_model.Config)
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
        censored_config = _censore_keys(config_dict, _SECRETS)
        messages = transform_error(err)
        for suberror in messages:
            logger.error(suberror)
        logger.error(f"config in question:\n{pprint.pformat(censored_config)}")
        raise exc.DConfigError("\n".join(messages)) from None

    if setup_config and config.logging:
        setup_logger(config.logging)

    return config


def setup_logger(logconf: config_model.LoggingConfig | None):
    if not logconf:
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

    # log information about version of the tool
    try:
        version = metadata.version("dblocks_core")
    except metadata.PackageNotFoundError:
        version = "<version info not available>"
    logger.info(f"dblc version: {version}")


def _censore_keys(
    data: dict,
    censored_keys: list[str],
    placeholder: str = REDACTED,
) -> dict:
    def _censore_values(data_: dict[str, Any]):
        for k, v in data_.items():
            if k in censored_keys:
                data_[k] = placeholder
            if isinstance(v, dict):
                _censore_keys(v, censored_keys, placeholder)

    _censore_values(data)
    return data


def cfg_to_censored_json(cfg: config_model.Config) -> str:
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

    Parameters:
    - env_name_prefix (str): The prefix used to filter environment variable names.
    The prefix will be removed from the keys in the resulting dictionary.
    - env (dict[str, Any] | None): A dictionary representing environment variables.
    If None, defaults to using the current environment variables.

    Returns:
    - dict[str, Any]: A nested dictionary containing the configuration values
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

    This function takes two dictionaries and merges them into a single
    dictionary. If both dictionaries have the same key and the values
    corresponding to that key are themselves dictionaries, those
    dictionaries are merged recursively. If the values are of different
    types or if one of the values is not a dictionary, the value from
    `dict2` will overwrite the value from `dict1`.

    Parameters:
        dict1 (dict[Any, Any]): The first dictionary to merge.
        dict2 (dict[Any, Any]): The second dictionary to merge.

    Returns:
        dict[Any, Any]: A new dictionary containing the merged result of
        `dict1` and `dict2`.

    Example:
        >>> dict1 = {'a': 1, 'b': {'c': 2}}
        >>> dict2 = {'b': {'d': 3}, 'e': 4}
        >>> merged = deep_merge_dicts(dict1, dict2)
        >>> print(merged)
        {'a': 1, 'b': {'c': 2, 'd': 3}, 'e': 4}
    """
    result = copy.deepcopy(dict1)
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _ensure_path(f: str | pathlib.Path) -> pathlib.Path:
    if isinstance(f, pathlib.Path):
        return f
    if isinstance(f, str):
        return pathlib.Path(f)
    raise TypeError(f"parameter is neiter str nor pathlib.Path: {type(f)}")


class _LoggingInterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
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