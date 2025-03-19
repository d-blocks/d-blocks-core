from pathlib import Path

from attrs import define, field
from loguru import logger

from dblocks_core.model import global_converter  # noqa: F401

TERADATA = "teradata"
ENV_PLACEHOLDER = "{{env}}"


class SecretStr(str):
    """
    String that censors its __repr__ if called from an attrs repr.
    """

    def __repr__(self):
        return "'<redacted>'"

    @property
    def value(self):
        return str(self)


def _assert_not_empty_string(self, attribute, value):
    if not isinstance(value, str):
        err = ValueError(f"string expected, got: {str(type(value))}")
        logger.error(err)
        raise err

    if value == "":
        err = ValueError(f"not empty string was expected, got: {value=}")
        logger.error(err)
        raise err
    if " " in value:
        err = ValueError(f"string with no white space expected, got: {value=}")
        logger.error(err)
        raise (err)


def _assert_lcase_keys(self, attribute, value):
    if not isinstance(value, dict):
        err = ValueError(f"expected a dict, got: {str(type(value))}")
        logger.error(err)
        logger.error(f"context for this error is: {value}")
        raise err

    for k in value.keys():
        if k != k.lower():
            err = ValueError(f"lowercase string expected, got: {k}")
            logger.error(err)
            logger.error(f"context for this error is: {value}")
            raise err


def _assert_list_of_strings(self, attribute, value):
    if not isinstance(value, list):
        err = ValueError(f"expected list[str], got: {str(type(value))}")
        logger.error(err)
        raise err

    for itm in value:
        if not isinstance(itm, str):
            err = ValueError(
                f"expected list item to be a string, got: {str(type(itm))}"
            )
            logger.error(err)
            raise err


def _assert_dict_of_strings(self, attribute, value):
    if not isinstance(value, dict):
        err = ValueError(f"expected dict[str,str], got: {str(type(value))}")
        logger.error(err)
        logger.error(f"context for this error is: {value}")
        raise err
    for k, v in value.items():
        if not isinstance(k, str):
            err = ValueError(f"expected str, got: {str(type(k))}")
            logger.error(err)
            logger.error(f"context for this error is: {value}")
            raise err
        if not isinstance(v, str):
            err = ValueError(f"expected str, got: {str(type(v))}")
            logger.error(err)
            logger.error(f"context for this error is: {value}")
            raise err


@define
class ExtractionParameters:
    databases: list[str] = field(factory=list)


@define
class WriterParameters:
    target_dir: Path = field(
        converter=Path, default=Path(".")
    )  # defaults to Config.metadata_dir
    encoding: str = field(default="utf-8")
    errors: str = field(default="strict")


@define
class EnvironParameters:
    writer: WriterParameters
    host: str = field(validator=_assert_not_empty_string)
    username: str = field(validator=_assert_not_empty_string)
    password: SecretStr = field(converter=SecretStr)
    extraction: ExtractionParameters
    platform: str = field(default=TERADATA)
    connection_parameters: dict[str, str] = field(
        factory=dict,
        validator=_assert_dict_of_strings,
    )
    tagging_variables: dict[str, str] = field(
        factory=dict,
        validator=_assert_dict_of_strings,
    )
    tagging_rules: list[str] = field(
        factory=list,
        validator=_assert_list_of_strings,
    )
    tagging_strip_db_with_no_rules: bool = field(default=True)
    git_branch: str | None = field(default=None)


@define
class LoggingSink:
    sink: str
    format: str | None = field(default=None)
    serialize: bool = field(default=False)
    # "100 MB", "0.5 GB", "1 month 2 weeks", "4 days", "10h", "monthly", "18:00", "sunday", "w0", "monday at 12:00"
    rotation: str = field(default="1 week")
    # a str for human-friendly parametrization of the maximum age of files to keep. Examples: "1 week, 3 days", "2 months", …
    retention: str = field(default="3 weeks")
    level: str = field(default="DEBUG")


@define
class LoggingConfig:
    console_log_level: str = field(default="INFO")
    other_sinks: dict[str, LoggingSink] = field(factory=dict)


@define
class PackagerConfig:
    package_dir: Path = field(
        default=Path("pkg"), converter=Path
    )  # relative to cwd/repo
    steps_subdir: Path = field(default=Path("db/teradata"), converter=Path)
    metadata_repo_subdir: Path = field(default=Path("meta"), converter=Path)
    safe_deletion_limit: int = field(default=50)
    interactive: bool = field(default=True)
    case_insensitive_dirs: bool = field(default=True)


@define
class Config:
    config_version: str
    environments: dict[str, EnvironParameters] = field(validator=_assert_lcase_keys)
    logging: LoggingConfig | None = field(default=None)
    metadata_dir: Path = field(default="meta", converter=Path)  # relative to cwd/repo
    package_dir: Path = field(default="pkg", converter=Path)  # relative to cwd/repo
    ctx_dir: Path = field(default=Path("."), converter=Path)
    report_dir: Path = field(default=Path("."), converter=Path)
    packager: PackagerConfig = field(factory=PackagerConfig)
