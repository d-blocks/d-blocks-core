import pathlib
from datetime import datetime
from typing import Any

import cattr


@cattr.global_converter.register_structure_hook
def _stru_datetime(val: Any, _) -> datetime:
    return datetime.fromisoformat(val)


@cattr.global_converter.register_unstructure_hook
def _uns_datetime(val: datetime) -> str:
    return val.isoformat()


@cattr.global_converter.register_structure_hook
def _stru_path(val: Any, _) -> pathlib.Path:
    return pathlib.Path(val)


@cattr.global_converter.register_unstructure_hook
def _uns_path(val: pathlib.Path) -> str:
    return val.as_posix()
