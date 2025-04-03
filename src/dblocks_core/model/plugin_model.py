from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from attrs import frozen

from dblocks_core.model import config_model, meta_model


@frozen
class _PluginInstance:
    module_name: str
    class_name: str
    instance: Callable


class Plugin:
    def dbe_init(self, cfg: config_model.Config) -> None:
        """
        This function is executed when the plugin is loaded.

        Args:
            cfg (config_model.Config): The configuration object.
        """
        self.cfg = cfg


class PluginHello(ABC, Plugin):
    """
    This is an example plugin, that is executed only from command dbe cfg-check.
    """

    @abstractmethod
    def hello() -> str:
        """
        The function must return a string, which will be written to the log.
        """


class PluginCfgCheck(ABC, Plugin):
    """
    This plugin can be used to implement custom configuration checks.
    The plugin must implement function with the following signature:

        def check_config(cfg: dblocks_core.model.config_model.Config)

    Unless the function raises an Exception, the configuration is deemed to be valid.

    The function should use the dblocks_core.exc.DConfigError exception, if it raises.

    """

    @abstractmethod
    def check_config():
        """
        Check the config, raise dblocks_core.exc.DConfigError for invalid config.
        """


class PluginWalker(ABC, Plugin):
    """
    This plugin walks through all files in a specified directory.
    """

    @abstractmethod
    def before(
        self,
        path: Path,
        environment: str | None,
        **kwargs,
    ):
        """
        This function is executed before the walk starts.

        Args:
            path (Path): The directory path to start walking.
            environment (str | None): The environment name, if any.
            cfg (config_model.Config): The configuration object.
            **kwargs: Additional arguments.
        """

    @abstractmethod
    def walker(
        self,
        path: Path,
        environment: str | None,
        **kwargs,
    ):
        """
        This function is executed for each file we walk through.

        Args:
            path (Path): The file path being walked.
            environment (str | None): The environment name, if any.
            cfg (config_model.Config): The configuration object.
            **kwargs: Additional arguments.
        """

    @abstractmethod
    def after(
        self,
        path: Path,
        environment: str | None,
        **kwargs,
    ):
        """
        This function is executed at the end of the walk.

        Args:
            path (Path): The directory path where the walk ended.
            environment (str | None): The environment name, if any.
            cfg (config_model.Config): The configuration object.
            **kwargs: Additional arguments.
        """


class PluginFSWriter(ABC, Plugin):
    """
    This plugin is called when debbie attempts to write DDL to a file system.
    """

    @abstractmethod
    def before(
        self,
        path: Path,
        obj: meta_model.DescribedObject,
        ddl: str,
        **kwargs,
    ) -> str | None:
        """
        This function is executed before the file is written to disk (and returns the DDL script).

        Args:
            path (Path): The file path where the DDL will be written.
            obj (meta_model.DescribedObject): The described object being written.
            ddl (str): The DDL script to be written.
            **kwargs: Additional arguments.

        Returns:
            str | None: The modified DDL script or None if no changes are needed.
        """
        pass

    @abstractmethod
    def after(
        self,
        path: Path,
        obj: meta_model.DescribedObject,
        **kwargs,
    ):
        """
        This function is executed after the file is written to disk.

        Args:
            path (Path): The file path where the DDL was written.
            obj (meta_model.DescribedObject): The described object that was written.
            **kwargs: Additional arguments.
        """
        pass


class PluginExtractIsInScope(ABC, Plugin):
    """
    This plugin is called when the extract process is running. It can be used to influence list
    of objects in scope of the extraction.

    In case of multiple plugins, if one of them returns False, the object is NOT in scope
    of the extraction (all must agree that the object is in scope).
    """

    @abstractmethod
    def is_in_scope(
        self,
        obj: meta_model.IdentifiedObject,
        **kwargs,
    ) -> bool:
        """
        This function is executed to determine if the object is in scope.

        Args:
            obj (meta_model.IdentifiedObject): The object being checked.
            **kwargs: Additional arguments.

        Returns:
            bool: True if the object is in scope, False otherwise.
        """
        pass


class PluginDBIRewriteStatement(ABC, Plugin):
    """
    This plugin is called by method deploy_statements by implementations
    of dblocks_core.dbi.contract.AbstractDBI.

    In effect, whenever the statement is deployed to the database.
    """

    @abstractmethod
    def rewrite_statement(self, statement: str) -> str:
        """The function rewrites statement before it is sent to the database."""
        pass
