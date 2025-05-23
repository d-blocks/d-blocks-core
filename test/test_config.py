import tempfile
from pathlib import Path

import pytest
from loguru import logger

from dblocks_core import exc
from dblocks_core.config import config

# from dblocks_core.extractor.contract import AbstractExtractor
# from dblocks_core.writer.contract import AbstractWriter
PFX = config.ENVIRON_PREFIX
DBC_ENV = "dbc_testing_dbc_dbc_testing_dbc"
PASSWORD = "password123"

DEFAULT_CONFIG = f"""
config_version = "1.0.0"
[ environments.{DBC_ENV} ]
host = "prodhost"
username = "produser"
# password = "{PASSWORD}" # password comes from ENV
connection_parameters.tmode = "TERA"
connection_parameters.logmech = "LDAP"
writer.target_dir = "./meta/opr"
extraction.databases = [ "dbc" ]
"""


def test_config():
    # this should fail
    logger.info("we expect this to fail")
    with pytest.raises(exc.DConfigError):
        cfg = config.load_config(setup_logger=False, from_filenames=[])

    env_vars = {
        f"{PFX}ENVIRONMENTS__{DBC_ENV}__PASSWORD": f"{PASSWORD}",
    }

    # this should succees
    with tempfile.TemporaryDirectory(suffix="dblc_test") as d:
        directories = [Path(d)]
        config_file = directories[0] / "dblocks.toml"
        config_file.write_text(DEFAULT_CONFIG, encoding="utf-8")
        cfg = config.load_config(
            environ=env_vars,
            setup_logger=False,
            from_directories=directories,
        )
    assert DBC_ENV in cfg.environments
    assert cfg.environments[DBC_ENV].connection_parameters["logmech"] == "LDAP"

    # redact passwords
    data_str = config.cfg_to_censored_json(cfg)
    assert PASSWORD not in data_str, data_str
    assert config.REDACTED in data_str
