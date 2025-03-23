import atexit
import json
import unicodedata
from collections.abc import MutableMapping
from datetime import datetime
from inspect import stack
from pathlib import Path
from typing import Any

import cattrs
from attrs import define, field

from dblocks_core import exc
from dblocks_core.config.config import logger


def find_ctx_root(
    in_dir: str | Path | None = None,
    *,
    context_dir_name: str,
):
    """
    Finds the root directory of a Git repository starting from a given directory.

    Args:
        in_dir (str | Path | None, optional): The directory to start the search
            from. If None, the current working directory is used. Defaults to None.

    Returns:
        Path | None: The path to the root of the Git repository, or None if the
            directory is not within a Git repository.

    Raises:
        TypeError: If `in_dir` is not of type str, Path, or None.

    Behavior:
    - Resolves the starting directory based on the input type or defaults to the
      current working directory.
    - Iteratively traverses parent directories, checking for the presence of a
      `.git/config` file to identify the repository root.
    - Returns the path to the repository root if found, or None if not in a Git
      repository.
    """

    if in_dir is None:
        start_in = Path.cwd()
    elif isinstance(in_dir, str):
        start_in = Path(in_dir)
    elif isinstance(in_dir, Path):
        start_in = Path(in_dir)
    else:
        raise TypeError(f"expected on od str, None, Path, got: {type(in_dir)}")

    prev_dir: None | Path = None
    while prev_dir != start_in:
        logger.trace(start_in)
        ctx_dir = start_in / context_dir_name
        if ctx_dir.exists():
            return start_in / ctx_dir
        prev_dir, start_in = start_in, start_in.parent

    # not in a git repo
    logger.debug("failed to find context directory")
    return None


def sanitize_string(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name)
    ascii_name = ascii_name.encode("ASCII", "ignore").decode("utf8")
    ascii_name = ascii_name.lower().replace(" ", "-")
    return ascii_name


@define
class ContextData:
    name: str
    checkpoints: dict[str, bool] = field(factory=dict)
    # this is at least serializable to json, however it is s bit tricky
    # when storing data on context, it is always important to use only basic types
    # meaning - cattrs.unstructure input a then cattrs.structure to coerce it to target var
    data: dict[str, Any] = field(factory=dict)
    is_done: bool = field(default=False)
    created: datetime = field(factory=datetime.now)


class Context(MutableMapping):
    def __delitem__(self, key):
        return self.ctx_data.data.__delitem__(key)

    def __getitem__(self, key):
        return self.ctx_data.data.__getitem__(key)

    def __iter__(self):
        return self.ctx_data.data.__iter__()

    def __len__(self):
        return len(self.ctx_data.data)

    def __setitem__(self, key, value):
        return self.ctx_data.data.__setitem__(key, value)

    def eta(
        self,
        total_steps: int,
        finished_steps: int,
        eta_since: datetime,
    ) -> datetime:
        _now = datetime.now()
        _elapsed = _now - eta_since
        _time_per_step = _elapsed / finished_steps
        _remaining = _time_per_step * (total_steps - finished_steps)
        _eta = _now + _remaining
        return _eta

    def done(self):
        self.ctx_data.is_done = True

    def is_in_progress(self) -> bool:
        return len(self.ctx_data.checkpoints) > 0

    def set_checkpoint(self, checkpoint: str = "", caller_index: int = 1):
        if checkpoint:
            checkpoint = f"->{checkpoint}"

        _stack = stack()
        _filename = Path(_stack[caller_index].filename).stem
        _function = _stack[caller_index].function
        _checkpoint = f"{_filename}:{_function}{checkpoint}"

        self.ctx_data.checkpoints[_checkpoint] = True

    def get_checkpoint(self, checkpoint: str, caller_index: int = 1) -> bool:
        if checkpoint:
            checkpoint = f"->{checkpoint}"

        _stack = stack()
        _filename = Path(_stack[caller_index].filename).stem
        _function = _stack[caller_index].function
        _checkpoint = f"{_filename}:{_function}{checkpoint}"

        try:
            return self.ctx_data.checkpoints[_checkpoint]
        except KeyError:
            return False

    def __init__(
        self,
        name: str,
        *,
        log_self: bool = True,
        no_exception_is_success: bool = True,
    ):
        self.name = name
        self.log_self = log_self
        self.ctx_data = ContextData(name=name)
        self.no_exception_is_success = no_exception_is_success
        self.ctx_data.created = datetime.now()

    def __enter__(self):
        # we do this simply to satisfy contex manager protocol
        # nothing else to do here
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # Exit the runtime context related to this object.
        # The parameters describe the exception that caused the context to be exited.
        # If the context was exited without an exception, all three arguments
        # will be None.
        if exc_type is None:
            if self.log_self:
                logger.debug("normal execution")
            if self.no_exception_is_success:
                self.ctx_data.is_done = True
            return True

        if self.log_self:
            logger.debug("abnormal execution, no change to context")
            logger.debug(f"is context done: {self.ctx_data.is_done}")


class FSContext(Context):
    def __init__(
        self,
        name: str,
        directory: Path,
        *,
        log_self: bool = True,
        atexit_handler: bool = True,
        no_exception_is_success: bool = True,
        save_after_each: int = 20,
    ):
        # set name and reset ctx_data
        super().__init__(
            name,
            log_self=log_self,
            no_exception_is_success=no_exception_is_success,
        )
        self.save_after_each = save_after_each

        # all of these attributes are file system related
        self.name = name
        self.directory = directory
        self.sanitized_name = sanitize_string(self.name)
        self.file = self.directory / f"ctx-{self.sanitized_name}.json"
        self.ctx_data = ContextData(name=name)

        self.load()

        # make sure we can close the context
        if atexit_handler:
            atexit.register(self.atexit_handler)

    def set_checkpoint(self, checkpoint: str = "", caller_index: int = 2):
        super().set_checkpoint(checkpoint, caller_index=2)
        ln = len(self.ctx_data.checkpoints)
        if ln % self.save_after_each == 0 and self.log_self:
            logger.debug(f"saving context with length {ln}")
            self.save()

    def load(self):
        # try to read context data from disk
        try:
            content = self.file.read_text(encoding="utf-8")
            data = json.loads(content)
            self.ctx_data = cattrs.structure(data, ContextData)
            if self.log_self:
                logger.warning("context exists, is this a restart run?")
                logger.warning(f"read context data from: {self.file.as_posix()}")
                logger.warning(
                    f"number of checkpoints: {len(self.ctx_data.checkpoints)}"
                )
        except json.JSONDecodeError:
            # invalid json data in the file
            message = "\n".join(
                [
                    "Failed to read context data file.",
                    "IMPORTANT: the file should be a valid JSON document, check.",
                    "Decide if the file should be removed",
                    "(current operation will start from the beginning.",
                    f"file={self.file.as_posix()}",
                ]
            )
            if self.log_self:
                logger.error(message)
            raise exc.DOperationsError(message) from None

        except FileNotFoundError:
            # create a new context
            if self.log_self:
                logger.debug(f"context file not found: {str(self.file.as_posix())}")
            self.ctx_data = ContextData(name=self.name)

    def save(self):
        self.directory.mkdir(exist_ok=True, parents=True)
        data = cattrs.unstructure(self.ctx_data)
        json_data = json.dumps(data, indent=4)
        try:
            if self.log_self:
                logger.debug(f"store context to: {self.file.as_posix()}")
            self.file.write_text(json_data, encoding="utf-8")
        except Exception:
            message = "\n".join(
                [
                    "Failed to store context data file.",
                    f"file={self.file.as_posix()}",
                ]
            )
            if self.log_self:
                logger.error(message)
            raise exc.DOperationsError(message) from None

    def atexit_handler(self):
        # drop context if it is done
        if self.ctx_data.is_done:
            if self.log_self:
                logger.debug("context is done")
            try:
                self.file.unlink(missing_ok=True)
            except Exception:
                message = "\n".join(
                    [
                        "Failed to remove context data file.",
                        "IMPORTANT: remove the file manually!",
                        f"file={self.file.as_posix()}",
                    ]
                )
                if self.log_self:
                    logger.error(message)
                raise exc.DOperationsError(message) from None
            return

        # save context if not done
        if len(self.ctx_data.checkpoints) == 0:
            if self.log_self:
                logger.warning("empty context, no checkpoints will be stored")
            return
        if self.log_self:
            logger.warning("context is not closed, saving context")
        self.save()


class JupyterContext(FSContext):
    def __init__(self, name: str):
        super().__init__(
            name=name,
            directory=Path.cwd(),
            log_self=False,
            atexit_handler=False,
            save_after_each=1,
        )

    def done(self):
        super().done()
        super().atexit_handler()
