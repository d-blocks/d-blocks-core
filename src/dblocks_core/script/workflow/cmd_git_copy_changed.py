import shutil
from pathlib import Path
from typing import Callable, Iterable, Tuple

from rich.console import Console
from rich.prompt import Prompt

from dblocks_core import exc
from dblocks_core.config.config import logger
from dblocks_core.git import git
from dblocks_core.model import config_model
from dblocks_core.writer import fsystem

console = Console()


TO_COPY = (
    git.FileStatus.ADDED,  # staged
    git.FileStatus.MODIFIED,
    git.FileStatus.UNTRACKED,
)


def copy(
    repo: git.Repo,
    diff_against: str,
    diff_ident: str,
    pkg_dir: Path,
    *,
    package_name: str,
    metadata_dir: Path,
    steps_subdir: Path,
    include_only: Iterable[Path | str] | None = None,
):
    # repo, check if it is dirty
    repo = git.repo_factory(raise_on_error=True)
    if repo is not None and repo.is_dirty():
        logger.warning("Repo is not clean!")
        console.print(
            "Repo is not clean!\n"
            "Extraction will not run, unless it is continuation of previously "
            "unfinished process.",
            style="bold red",
        )
        really = Prompt.ask(
            "Are you sure you want to continue?\n"
            "This could lead to potentially huge diff! "
            "(yes/no)",
            default="no",
        ).strip()
        if really not in ("yes", "y"):
            logger.error(f"action canceled by prompt: {really}")
            return

    # repo, check if the commit is on current branch
    if diff_against == "commit":
        current_branch = repo.get_current_branch()
        if not repo.is_commit_on_branch(branch=current_branch, commit=diff_ident):
            console.print(
                f"The commit '{diff_ident}' is not on current branch '{current_branch}'",
                style="bold blue",
            )
            really = Prompt.ask(
                "Are you sure you want to continue? (yes/no)",
                default="no",
            ).strip()
            if really not in ("yes", "y"):
                logger.error(f"action canceled by prompt: {really}")
                return

    # get list of changes
    changes = changes_against(repo, diff_against, diff_ident, include_only=include_only)

    # prep copy from/to pairs
    # get path relative to subdir, if list of subdirs was given

    can_copy = [
        git.FileStatus.ADDED,
        git.FileStatus.MODIFIED,
        git.FileStatus.COPIED,
        git.FileStatus.RENAMED,
        git.FileStatus.UNTRACKED,
        git.FileStatus.UNMERGED,
    ]

    if len(changes) == 0:
        logger.warning("Empty list of changes files.")
        return

    # target directory, ask for confirmation
    pkg_root_dir = pkg_dir / package_name
    logger.info(f"Changeset length is: {len(changes)}")
    logger.info(f"Target dir is: {pkg_root_dir.as_posix()}")
    really = Prompt.ask(
        "Are you sure you want to continue? (yes/no)",
        default="no",
    ).strip()
    if really not in ("yes", "y"):
        logger.error(f"action canceled by prompt: {really}")
        return

    dirs = set()
    for c in changes:
        # FIXME: deletions, what to do about them
        if c.change not in can_copy:
            continue
        copy_from = repo.repo_dir / c.rel_path
        if not copy_from.exists():
            logger.warning(f"file does not exists: {copy_from}")
            continue
        copy_to = pkg_root_dir / _rel_path_in_package(
            repo_dir_absp=repo.repo_dir,
            src_file_absp=c.abs_path,
            metadata_dir_absp=metadata_dir,
            steps_subdir=steps_subdir,
        )

        parent = copy_to.parent
        if parent not in dirs:
            parent.mkdir(exist_ok=True, parents=True)
            dirs.add(parent)

        shutil.copy(copy_from, copy_to)


def _rel_path_in_package(
    *,
    repo_dir_absp: Path,
    src_file_absp: Path,
    metadata_dir_absp: Path,
    steps_subdir: Path,
    subdir_list: Iterable[str | Path] | None = None,
) -> Path:
    # check if the path is in metadata directory
    # if it is, prepare it as the package
    if src_file_absp.is_relative_to(metadata_dir_absp):
        # FIXME: tight coupling, also see test cases!
        step_name = fsystem.EXT_TO_STEP.get(
            src_file_absp.suffix,
            fsystem.STP_GENERIC_SQL,
        )
        db_name = src_file_absp.parent.name
        return steps_subdir / step_name / db_name / src_file_absp.name

    # if subdir list was given, check if we are relative to one of them
    if subdir_list:
        for sd in subdir_list:
            sd_abs = repo_dir_absp / sd
            if src_file_absp.is_relative_to(sd_abs):
                return src_file_absp.relative_to(sd_abs)

    # all other files, simply use relative path in the repo
    return src_file_absp.relative_to(repo_dir_absp)


def changes_against(
    repo: git.Repo,
    diff_against: str,
    diff_ident: str,
    *,
    include_only: list[Path, str] | None,
) -> list[git.GitChangedPath]:
    """Compares last committed state of the current branch to either
    a different branch, or to a commit on the same branch.

    Args:
        repo (git.Repo): The repository to analyze.
        diff_against (str): Compare against "commit" or "branch".
        diff_ident (str): The commit SHA or branch name.
        subdir_list (list[Path, str] | None): Filter changes to these
            subdirectories. Defaults to None.

    Raises:
        DOperationsError: If `diff_against` is not "commit" or "branch".

    Returns:
        list[git.GitChangedPath]: List of changed files.
    """

    # what do we diff against, what changes do we have?
    if diff_against == "commit":
        changes = changes_against_commit(repo, baseline_commit=diff_ident)
    elif diff_against == "branch":
        changes = changes_against_branch(repo, baseline_branch=diff_ident)
    else:
        raise exc.DOperationsError(
            f"diff_against: should be one of ('commit','branch'): {diff_against}"
        )
    if include_only:
        subdir_list_ = [repo.repo_dir / s for s in include_only]
        changes = _filter_subdir(changes, subdir_list_)
    return changes


def _filter_subdir(
    changes: list[git.GitChangedPath],
    subdir_list: list[Path],
) -> list[git.GitChangedPath]:
    subdir_list_ = [s.as_posix() + "/" for s in subdir_list]

    def _is_in_list(p: Path):
        for subdir in subdir_list_:
            if p.as_posix().startswith(subdir):
                return True

    return [c for c in changes if _is_in_list(c.abs_path)]


def changes_against_commit(
    repo: git.Repo,
    *,
    baseline_commit: str,
) -> list[git.GitChangedPath]:
    """Compares last commit on current branch to a different commit
    on the same branch, and returns list of changed files.

    Args:
        baseline_commit (str ): The commit we compare to.

    Raises:
        DGitCommandError: If the last commit SHA cannot be retrieved.

    Returns:
        list[git.GitChangedPath]: list of changes
    """

    # check that the commit is on current branch
    feature_branch = repo.get_current_branch()
    branches_with_commit = repo.get_branches_with_commit(baseline_commit)
    if feature_branch not in branches_with_commit:
        logger.warning(
            f"commit ({baseline_commit}) is not in current branch ({feature_branch})"
        )
    # find latest commit
    last_commit_on_branch = repo.get_last_commit_sha(feature_branch)
    logger.info(f"latest commit is {last_commit_on_branch}")

    # get full changespec
    changes = repo.changes_between_commits(
        baseline_commit=baseline_commit,
        last_commit=last_commit_on_branch,
    )
    logger.info(f"full changespec: {len(changes)} items")
    return changes


def changes_against_branch(
    repo: git.Repo,
    *,
    baseline_branch: str,
) -> list[git.GitChangedPath]:
    """Compares last commit on current branch to a last common
    commit with a different branch. Returns list of changed files.

    Typical use case: compare feature branch against a develop branch.

    Args:
        baseline_branch (str): The branch we compare to.

    Raises:
        DGitCommandError: If the last commit SHA cannot be retrieved.

    Returns:
        list[git.GitChangedPath]: list of changes
    """

    # what branch are we on
    feature_branch = repo.get_current_branch()
    logger.info(f"diffing branch {feature_branch} against {baseline_branch}")
    if feature_branch == baseline_branch:
        err = f"can not diff against current branch: {feature_branch}"
        raise exc.DOperationsError(err)

    # find last common commit
    baseline_commit = repo.get_merge_base(baseline_branch, feature_branch)
    logger.info(f"baseline commit is {baseline_commit}")

    # find latest commit
    last_commit_on_branch = repo.get_last_commit_sha(feature_branch)
    logger.info(f"latest commit is {last_commit_on_branch}")

    # get full changespec
    changes = repo.changes_between_commits(
        baseline_commit=baseline_commit,
        last_commit=last_commit_on_branch,
    )
    logger.info(f"full changespec: {len(changes)} items")
    return changes


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

    changes = repo.changes_on_commit(commit=commit)
    if len(changes) == 0:
        logger.error("no changes found")
        return

    copy_files: list[Tuple[Path, Path]] = []
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
        if not source.exists():
            logger.error(f"path does not exist: {source}")
            continue

        if source.is_dir():
            logger.warning(f"path is a dir, recursive copy: {source}")
            target.mkdir(exist_ok=True, parents=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
            continue

        # source path is a dir
        shutil.copy(source, target)
