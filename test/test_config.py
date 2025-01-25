import pytest
from loguru import logger

from dblocks_core import exc
from dblocks_core.config import config

# from dblocks_core.extractor.contract import AbstractExtractor
# from dblocks_core.writer.contract import AbstractWriter
PFX = config.ENVIRON_PREFIX
U_ENV = "TSTENV"
L_ENV = U_ENV.lower()
PASSWORD = "password123"


@pytest.fixture
def config_env():
    return {
        f"{PFX}CONFIG_VERSION": config.EXPECTED_CONFIG_VERSION,
        f"{PFX}ENVIRONMENTS__{U_ENV}__WRITER__TARGET_DIR": "./test/data",
        f"{PFX}ENVIRONMENTS__{U_ENV}__HOST": "localhost",
        f"{PFX}ENVIRONMENTS__{U_ENV}__USERNAME": "username",
        f"{PFX}ENVIRONMENTS__{U_ENV}__PASSWORD": f"{PASSWORD}",
        f"{PFX}ENVIRONMENTS__{U_ENV}__CONNECTION_PARAMETERS__LOGMECH": "LDAP",  # TODO: bug - dblocks_core.config.config:_censore_values:172 - data_={'databases': ['[', "'", 'd', 'a', 't', 'a', 'b', 'a', 's', 'e', "'", ']']} # noqa: E501
        f"{PFX}ENVIRONMENTS__{U_ENV}__EXTRACTION__DATABASES": "['database']",
        f"{PFX}ENVIRONMENTS__{U_ENV}__TAGGING_VARIABLES__ENV": "dbpfx",
        f"{PFX}ENVIRONMENTS__{U_ENV}__TAGGING_RULES__ENV": "['{env}*']",
    }


def test_config(config_env):
    # this should fail
    logger.info("we expect this to fail")
    with pytest.raises(exc.DConfigError):
        cfg = config.load_config(setup_config=False, locations=[])

    # this should succees
    logger.info("this must succeed")
    cfg = config.load_config(environ=config_env, setup_config=False)

    assert L_ENV in cfg.environments
    assert cfg.environments[L_ENV].connection_parameters["logmech"] == "LDAP"


def test_censoring(config_env):
    # data = {"password": "a", "env": {"dd01": {"password": "a", "host": "host"}}}
    # wanted = data = {
    #     "password": config.REDACTED,
    #     "env": {"dd01": {"password": config.REDACTED, "host": "host"}},
    # }
    # data = config._censore_keys(data, config._SECRETS)
    # assert data == wanted

    cfg = config.load_config(environ=config_env, setup_config=False)
    data_str = config.cfg_to_censored_json(cfg)
    assert PASSWORD not in data_str, data_str
    assert config.REDACTED in data_str
