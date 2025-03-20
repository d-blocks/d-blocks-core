from abc import ABC
from typing import Callable

from attrs import frozen

from dblocks_core.model import config_model


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
