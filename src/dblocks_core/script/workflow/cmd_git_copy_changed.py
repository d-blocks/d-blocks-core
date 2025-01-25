import shutil
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from dblocks_core import exc
from dblocks_core.config.config import logger
from dblocks_core.git import git

TO_COPY = (
    git.FileStatus.ADDED,  # staged
    git.FileStatus.MODIFIED,
    git.FileStatus.UNTRACKED,
)


def copy_changed_files(
    repo: git.Repo,
    target: Path,
    source_subdir: str | None,
    assume_yes: bool = False,
    *,
    commit: str | None = None,
):
    absolute_source_path = repo.repo_dir.resolve()

    if source_subdir is not None:
        absolute_source_path = repo.repo_dir.resolve() / source_subdir
        if not absolute_source_path.is_dir():
            err = f"directory not found: {absolute_source_path.as_posix()}"
            raise exc.DGitError(err)

    changes = repo.changed_files(commit=commit)
    if len(changes) == 0:
        logger.error("no changes found")
        return

    copy_files = []
    for change in changes:
        # only files in the source path
        if not change.abs_path.is_relative_to(absolute_source_path):
            continue
        if change.change not in TO_COPY:
            logger.warning(f"skipped change: {change.change}: {change.rel_path}")
            continue

        tgt_file = target / change.abs_path.relative_to(absolute_source_path)
        tgt_file.parent.mkdir(exist_ok=True, parents=True)
        logger.info(f"{change.rel_path} => {tgt_file}")
        copy_files.append((change.abs_path, tgt_file))

    if not assume_yes:
        console = Console()
        console.print("** Are you sure?", style="bold red")
        console.print(f" - source dir   : {absolute_source_path}")
        console.print(f" - target dir   : {target}")
        console.print(f" - items to copy: {len(copy_files)}")
        really = ""
        while really not in ("y", "n"):
            really = (
                Prompt.ask("Proceed with the copy? (y/n)", default="y").strip().lower()
            )
        if really != "y":
            logger.error("canceled by prompt")
            return

    for source, target in copy_files:
        shutil.copy(source, target)
