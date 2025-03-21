from __future__ import annotations

import atexit
from typing import Any

import loguru
import sqlalchemy as sa
from attr import frozen
from sqlalchemy.engine import URL

# do not pollute public namespace, import to private variable
from dblocks_core.config.config import (
    get_environment_from_config as __get_environment_from_config,
)
from dblocks_core.config.config import load_config as __load_config
from dblocks_core.config.config import logger
from dblocks_core.dbi import tera_dbi
from dblocks_core.dbi.contract import AbstractDBI
from dblocks_core.model import config_model

TERADATA_DIALECT = "teradatasql"


@frozen
class InitState:
    engine: sa.Engine
    config: config_model.Config
    logger: loguru.Logger


def init(
    environment: str,
    *,
    dialect: str = TERADATA_DIALECT,
    pool_size: int = 1,
    max_overflow: int = 1,
    poolclass: Any = sa.pool.QueuePool,
    echo: bool = False,
) -> InitState:
    """
    Initialize the d-blocks-core environment for Jupyter notebooks, and simillar
    use cases.

    Behaviour:
        - first, load the configuration from dblocks.toml and/or env variables
        - then, get the environment definition from the configuration
        - then, prepare sqlalchemy engine, and register engine.dispose() via atexit.

    Args:
        environment (str): name of the environment that the engine is associated with
        poolclass (Any, optional): defaults to sa.pool.QueuePool.
        pool_size (int, optional): defaults to 1.
        max_overflow (int, optional): defaults to 1.

    Raises:
        exceptions.MiteConfigError: if connect string is not provided

    Returns: InitState, where
        engine (sqlalchemy.Engine): database engine
        config (config_model.Config): the configuration
    """
    cfg = __load_config()
    env = __get_environment_from_config(cfg, environment)
    engine = create_engine(
        env,
        dialect=dialect,
        pool_size=pool_size,
        poolclass=poolclass,
        echo=echo,
        max_overflow=max_overflow,
    )
    return InitState(
        engine=engine,
        config=cfg,
        logger=logger,
    )


def extractor_factory(
    env: config_model.EnvironParameters,
) -> AbstractDBI:
    if env.platform == config_model.TERADATA:
        engine = create_engine(env, dialect=TERADATA_DIALECT)
        return tera_dbi.TeraDBI(engine)
    raise NotImplementedError


def create_engine(
    secret: config_model.EnvironParameters,
    *,
    dialect: str = TERADATA_DIALECT,
    pool_size: int = 1,
    max_overflow: int = 1,
    poolclass: Any = sa.pool.QueuePool,
    echo: bool = False,
) -> sa.Engine:
    """Creates an engine, and registers engine.dispose() via atexit.

    Args:
        connect_string (str | sa.URL): connect string
        poolclass (Any, optional): defaults to sa.pool.QueuePool.
        pool_size (int, optional): defaults to 1.
        max_overflow (int, optional): defaults to 1.

    Raises:
        exceptions.MiteConfigError: if connect string is not provided

    Returns:
        sa.Engine: database engine
    """
    logger.debug(f"create engine: {dialect=}: {secret}")
    connect_string = create_connect_string(secret, dialect)
    engine = sa.create_engine(
        connect_string,
        pool_size=pool_size,
        max_overflow=max_overflow,
        poolclass=poolclass,
        echo=echo,
    )

    def _dispose():
        logger.debug(f"disconnect: {dialect=}: {secret}")
        engine.dispose()

    atexit.register(_dispose)
    return engine


def create_connect_string(
    secret: config_model.EnvironParameters,
    dialect: str,
) -> URL:
    connection_url = URL.create(
        drivername=dialect,
        username=secret.username,
        password=secret.password.value,
        host=secret.host,
        query=secret.connection_parameters,
    )
    logger.trace(connection_url)  # password in the string is encoded, so it is OK
    return connection_url
