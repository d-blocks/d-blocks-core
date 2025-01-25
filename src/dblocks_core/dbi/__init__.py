import atexit
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import URL

from dblocks_core.config.config import logger
from dblocks_core.dbi import tera_dbi
from dblocks_core.dbi.contract import AbstractDBI
from dblocks_core.model import config_model

TERADATA_DIALECT = "teradatasql"


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
