from dblocks_core.model import config_model
from dblocks_core.writer import fsystem
from dblocks_core.writer.contract import AbstractWriter


def create_writer(cfg: config_model.WriterParameters) -> AbstractWriter:
    return fsystem.FSWriter(cfg)
