import shutil
from enum import Enum
from pathlib import Path
from textwrap import dedent

from attrs import define
from rich.prompt import Prompt

from dblocks_core import exc
from dblocks_core.config.config import logger
from dblocks_core.model import config_model


class CanDropDir(Enum):
    DOES_NOT_EXIST = "DOES_NOT_EXIST"
    YES = "YES"
    NO = "NO"


@define
class Script:
    rel_path: Path
    content: str


@define
class Step:
    rel_path: Path
    scripts: list[Script]


class Packager:

    def __init__(
        self,
        *,
        package_dir: Path,
        steps_subdir: Path,
        safe_deletion_limit: int = 50,
        interactive: bool = True,
        encoding: str = "utf-8",
        encoding_errors: str = "strict",
    ):
        self.package_dir = package_dir
        self.steps_subdir = steps_subdir
        self.safe_deletion_limit = safe_deletion_limit
        self.interactive = interactive
        self.steps: list[Step] = []
        self.encoding = encoding
        self.encoding_errors = encoding_errors

    def save_package(self, name: str):
        pd = self.drop_package_dir(name) / self.steps_subdir
        self.create_package_dir(name)

        for step in self.steps:
            step_dir = pd / step.rel_path
            logger.info(f"make step: {step_dir.as_posix()}")
            step_dir.mkdir(exist_ok=True, parents=True)
            for script in step.scripts:
                script_dir = step_dir / script.rel_path.parent
                script_path = step_dir / script.rel_path
                logger.info(f"make script: {script_path.as_posix()}")
                script_dir.mkdir(exist_ok=True)
                script_path.write_text(
                    script.content,
                    encoding=self.encoding,
                    errors=self.encoding_errors,
                )

    def create_package_dir(self, name: str) -> Path:
        pd = self.package_dir / name
        pd.mkdir(exist_ok=True, parents=True)
        return pd

    def drop_package_dir(self, name: str, *, can_raise: bool = True) -> Path:
        pd = self.package_dir / name

        # drop the dir
        _drop = self.can_drop_dir(pd)
        if _drop == CanDropDir.YES:
            shutil.rmtree(pd)

        if _drop == CanDropDir.NO:
            err = dedent(
                f"""
                We were going to drop the directory, yet the config prohibits us from doing so.
                - dir = {pd.as_posix()}
                - safe_deletion_limit = {self.safe_deletion_limit}
                - interactive = {self.interactive}

                Check the configuration.
                """
            )
            if can_raise:
                raise exc.DOperationsError(err)
            else:
                logger.error(err)

        # create the dir
        pd.mkdir(exist_ok=True, parents=True)
        return pd

    def can_drop_dir(self, pd: Path, log_each: int = 200) -> CanDropDir:
        # can not drop nonexisting dir
        if not pd.exists():
            return CanDropDir.DOES_NOT_EXIST

        # count files
        file_count = 0
        for f in pd.rglob("*"):
            logger.debug(f)
            if not f.is_file():
                continue
            file_count = file_count + 1
            if file_count % log_each == 0:
                logger.info(
                    f"counting files under {pd.as_posix()}: {file_count=}, "
                    "be patient..."
                )
        # count is under limit, ok to drop
        if file_count <= self.safe_deletion_limit:
            logger.info(f"{file_count} <= {self.safe_deletion_limit}")
            return CanDropDir.YES

        # ask for input if interactive
        if self.interactive:
            really = ""
            msg = (
                f"We are going to delete this directory: {pd.as_posix()}"
                "\nAre you sure? (yes/no)"
            )
            while really not in ("y", "n", "yes", "no"):
                really = Prompt.ask(msg, default="no").strip().lower()
            if really[0] == "y":
                return CanDropDir.YES

        return CanDropDir.NO


def packager_factory(pkg: config_model.PackagerConfig):
    return Packager(
        package_dir=pkg.package_dir,
        steps_subdir=pkg.steps_subdir,
        safe_deletion_limit=pkg.safe_deletion_limit,
        interactive=pkg.interactive,
    )
