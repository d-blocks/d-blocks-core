from abc import ABC
from pathlib import Path
from typing import Any, Callable

from attrs import frozen

from dblocks_core.model import config_model, meta_model


@frozen
class _PluginInstance:
    module_name: str
    class_name: str
    instance: Callable


class PluginHello(ABC):
    """
    This is an example plugin, that is executed only from command dbe cfg-check.
    """

    def hello() -> str:
        """
        The function must return a string, which will be written to the log.
        """


class PluginCfgCheck(ABC):
    """
    This plugin can be used to implement custom configuration checks.
    The plugin must implement function with the following signature:

        def check_config(cfg: dblocks_core.model.config_model.Config)

    Unless the function raises an Exception, the configuration is deemed to be valid.

    The function should use the dblocks_core.exc.DConfigError exception, if it raises.

    """

    def check_config(cfg: config_model.Config):
        """
        Check the config, raise dblocks_core.exc.DConfigError for invalid config.


        Args:
            cfg (config_model.Config): the config in question
        """


class PluginWalker(ABC):
    """
    This plugin walks through all files in a specified directory.
    """

    def before(
        self,
        path: Path,
        environment: str | None,
        cfg: config_model.Config,
        **kwargs,
    ):
        """This function is executed before the walk starts."""

    def walker(
        self,
        path: Path,
        environment: str | None,
        cfg: config_model.Config,
        **kwargs,
    ):
        """This function is executed for each file we walk through."""

    def after(
        self,
        path: Path,
        environment: str | None,
        cfg: config_model.Config,
        **kwargs,
    ):
        """TWhis function is executed at the end."""


class PluginFSWriter(ABC):
    """
    This plugin is called when debbie attempts to write DDL to a file system.
    """

    def before(
        self,
        path: Path,
        obj: meta_model.DescribedObject,
        ddl: str,
        **kwargs,
    ) -> str:
        """
        This function is executed before the file is written do disk (and returns the DDL script).
        The function is expected to return back either:
            - the DDL script (string), or
            - None, if the DDL script should not be changed.
        """
        pass

    def after(
        self,
        path: Path,
        obj: meta_model.DescribedObject,
        **kwargs,
    ):
        """This function is executed after the file is written do disk."""
        pass
