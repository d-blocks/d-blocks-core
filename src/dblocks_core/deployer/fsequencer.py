import hashlib
from pathlib import Path
from typing import Generator

from attrs import define, field

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.deployer import tokenizer


@define
class DeploymentStatement:
    sql: str

    def md5(self) -> str:
        return hashlib.md5(self.sql.encode()).hexdigest()


@define
class DeploymentFile:
    default_db: str | None
    file: Path = field(converter=Path)

    def statements(
        self,
        *,
        separator=tokenizer.SEMICOLON,
    ) -> Generator[DeploymentStatement, None, None]:
        txt = self.file.read_text(encoding="utf-8", errors="strict")
        for sql in tokenizer.tokenize_statemets(txt, separator=separator):
            yield DeploymentStatement(sql=sql)


@define
class DeploymentStep:
    name: str
    location: Path = field(converter=Path)
    files: list[DeploymentFile] = field(factory=list)


@define
class DeploymentBatch:
    root_dir: Path = field(converter=Path)
    steps: list[DeploymentStep] = field(factory=list)


def create_batch(root_dir: Path, tgr: tagger.Tagger | None = None) -> DeploymentBatch:
    # scan folders in root - each folder is a DeploymentStep
    errs = []
    steps: list[DeploymentStep] = []
    logger.info(f"scanning: {root_dir}")
    for d in sorted(root_dir.glob("*")):
        if d.is_file():
            errs.append(f"- unexpected file: {d.as_posix()}")
            continue
        if not d.is_dir():
            errs.append(f"- unexpected object: {d.as_posix()}")
            continue
        steps.append(
            DeploymentStep(
                name=d.name,
                location=d,
                files=[],
            )
        )

    # sanity check
    if len(errs) > 0:
        msg = "Invalid batch structure:\n" + "\n".join(errs)
        raise exc.DDeployerInvalidBatch(msg)

    # rglob files ordered alphabetically
    for step in steps:
        files = []
        for f in sorted(step.location.rglob("*")):
            # skip folders
            if f.is_dir():
                continue
            # for files that are not directly in the step dir,
            # we assume that the name of the parent is name of the db
            if f.parent.absolute() == step.location.absolute():
                db = None
            else:
                db = f.parent.name

            # name of the db can tagged be placeholder
            if tgr is not None and db is not None:
                db = tgr.tag_database(db)

            files.append(
                DeploymentFile(
                    default_db=db,
                    file=f,
                )
            )
        step.files = files

    steps = [step for step in steps if len(step.files) > 0]
    return DeploymentBatch(root_dir=root_dir, steps=steps)
