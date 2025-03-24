import hashlib
from pathlib import Path
from typing import Generator

from attrs import define, field

from dblocks_core import exc, tagger
from dblocks_core.config.config import logger
from dblocks_core.deployer import tokenizer
from dblocks_core.model import meta_model
from dblocks_core.writer import fsystem


@define
class DeploymentStatement:
    sql: str

    def md5(self) -> str:
        return hashlib.md5(self.sql.encode()).hexdigest()


def _must_be_deployable(self, attribute, value):
    if not value in meta_model.DEPLOYABLE_TYPES:
        err = ValueError(
            f"expected one of: {meta_model.DEPLOYABLE_TYPES}; got: {value}"
        )
        logger.error(err)
        raise err


@define
class DeploymentFile:
    default_db: str | None
    file: Path = field(converter=Path)
    file_type: str | None = field(validator=None)

    def statements(
        self,
        *,
        separator=tokenizer.SEMICOLON,
    ) -> Generator[DeploymentStatement, None, None]:
        txt = self.file.read_text(encoding="utf-8", errors="strict")
        for sql in tokenizer.tokenize_statements(txt, separator=separator):
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
        step.files = []

        # files directly under step are to be executed FIRST
        _input_dirs = sorted([d for d in step.location.iterdir() if d.is_dir()])
        _input_files = sorted(
            [file for file in step.location.iterdir() if file.is_file()]
        )

        for f in _input_files:
            # one of supported file types
            try:
                file_type = fsystem.EXT_TO_TYPE[f.suffix]
            except KeyError:
                logger.warning(f"skipping file with unsupported type ({f.suffix}): {f}")
                continue
            step.files.append(
                DeploymentFile(
                    default_db=None,  # no default database for these files
                    file=f,
                    file_type=file_type,
                )
            )
        # files that are in their own directory should be executed later
        for dabatase_dir in _input_dirs:
            if not dabatase_dir.is_dir():
                continue
            for f in sorted(dabatase_dir.rglob("*")):
                if f.is_dir():
                    continue
                try:
                    file_type = fsystem.EXT_TO_TYPE[f.suffix]
                except KeyError:
                    logger.warning(
                        f"skipping file with unsupported type ({f.suffix}): {f}"
                    )
                    continue

                # for files that are not directly in the step dir,
                # we assume that the name of the parent is name of the db
                db = f.parent.name

                # name of the db can tagged be placeholder
                if tgr is not None and db is not None:
                    db = tgr.expand_statement(db)

                step.files.append(
                    DeploymentFile(
                        default_db=db,
                        file=f,
                        file_type=file_type,
                    )
                )

    steps = [step for step in steps if len(step.files) > 0]
    return DeploymentBatch(root_dir=root_dir, steps=steps)
