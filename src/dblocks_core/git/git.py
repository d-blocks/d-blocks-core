import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryFile

from attrs import frozen

from dblocks_core import exc
from dblocks_core.config.config import logger

GIT = "git"
INIT = "init"
CHECKOUT = "checkout"
ADD = "add"
COMMIT = "commit"
LOG = "log"
STATUS = "status"
DIFF_TREE = "diff-tree"

_SW_AMEND = "--amend"
_SW_PORCELAIN = "--porcelain"
_SW_ALL = "--all"
_DTTM_MASK = "%Y-%m-%d %H:%M:%S"
_SW_NAME_STATUS = "--name-status"


# There are three different types of states that are shown using this format,
# and each one uses the XY syntax differently:
# - When a merge is occurring and the merge was successful, or
#     outside of a merge situation,
#     X shows the status of the index and Y shows the status of the working tree.
# - When a merge conflict has occurred and has not yet been resolved,
#     X and Y show the state introduced by each head of the merge,
#     relative to the common ancestor.
#     These paths are said to be unmerged.
# - When a path is untracked, X and Y are always the same,
#     since they are unknown to the index.
#     ?? is used for untracked paths.
#     Ignored files are not listed unless --ignored is used;
#     if it is, ignored files are indicated by !!.

# Note that the term merge here also includes rebases using the default
#     --merge strategy, cherry-picks, and anything else using the merge machinery.

# In the following table, these three classes are shown in separate sections,
# and these characters are used for X and Y fields for the first two sections
# that show tracked paths:

# - ' ' = unmodified
# - M = modified
# - T = file type changed (regular file, symbolic link or submodule)
# - A = added
# - D = deleted
# - R = renamed
# - C = copied (if config option status.renames is set to "copies")
# - U = updated but unmerged

# X          Y     Meaning
# -------------------------------------------------
# 	     [AMD ]  not updated
# M        [ MTD]  updated in index
# T        [ MTD]  type changed in index
# A        [ MTD]  added to index
# D                deleted from index
# R        [ MTD]  renamed in index
# C        [ MTD]  copied in index
# [MTARC]          index and work tree matches
# [ MTARC]    M    work tree changed since index
# [ MTARC]    T    type changed in work tree since index
# [ MTARC]    D    deleted in work tree
# 	        R    renamed in work tree
# 	        C    copied in work tree
# -------------------------------------------------
# D           D    unmerged, both deleted
# A           U    unmerged, added by us
# U           D    unmerged, deleted by them
# U           A    unmerged, added by them
# D           U    unmerged, deleted by us
# A           A    unmerged, both added
# U           U    unmerged, both modified
# -------------------------------------------------
# ?           ?    untracked
# !           !    ignored
# -------------------------------------------------


class FileStatus(Enum):
    UNCHANGED = "UNCHAGNED"
    MODIFIED = "MODIFIED"
    ADDED = "ADDED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"
    COPIED = "COPIED"
    UNMERGED = "UNMERGED"
    UNTRACKED = "UNTRACKED"
    UNKNOWN = "<UNKNOWN>"


@frozen
class GitResult:
    out: str
    err: str
    code: int
    args: list[str]


@frozen
class GitChangedFile:
    change: FileStatus
    rel_path: Path
    abs_path: Path


def find_git_exec() -> str | None:
    gt = shutil.which(GIT)
    if gt is not None:
        return str(gt)
    return None


def find_repo_root(in_dir: str | Path | None = None):
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
        start_in = in_dir
    else:
        raise TypeError(f"expected on od str, None, Path, got: {type(in_dir)}")

    prev_dir: None | Path = None
    while prev_dir != start_in:
        logger.trace(start_in)
        gitconfig = start_in / ".git/config"
        if gitconfig.exists():
            return start_in
        prev_dir, start_in = start_in, start_in.parent

    # not in a git repo
    logger.debug("not in a git repo")
    return None


@contextmanager
def cwd(to_dir: Path):
    """
    A context manager to temporarily change the current working directory.

    Args:
        to_dir (Path): The directory to switch to during the context.

    Behavior:
    - Stores the current working directory before switching to `to_dir`.
    - Changes the working directory to `to_dir` for the duration of the context.
    - Restores the original working directory upon exiting the context.
    - Logs debug messages when changing directories.

    Example:
        with cwd(Path("/new/directory")):
            # Perform operations in "/new/directory"
        # After exiting the context, the original directory is restored.
    """

    old_dir = Path.cwd()
    if old_dir != to_dir:
        logger.debug(f"changing dir to {to_dir.as_posix()}")
        os.chdir(to_dir)
    yield
    if old_dir != to_dir:
        logger.debug(f"changing dir to {old_dir.as_posix()}")
        os.chdir(old_dir)


class Repo:
    def __init__(
        self,
        repo_dir: Path | str,
        raise_on_error: bool = True,
    ):
        """
        Represents a Git repository and provides methods for interacting with it.

        Args:
            repo_dir (Path | str): The path to the root directory of the repository.
            raise_on_error (bool, optional): Whether to raise exceptions on errors.
                Defaults to True.

        Attributes:
            repo_dir (Path): The resolved Path object representing the repository's
                root directory.
            raise_on_error (bool): Determines whether errors should raise exceptions.
            git_exec (Path | None): The path to the Git executable, or None if Git is
                not found.

        Raises:
            TypeError: If `repo_dir` is not of type str or Path.

        Behavior:
        - Resolves the `repo_dir` parameter to a Path object.
        - Initializes the repository directory and the error-handling mode.
        - Locates the Git executable using `find_git_exec()`. Logs a warning if Git is
          not found.
        """

        if isinstance(repo_dir, str):
            repo_dir_ = Path(repo_dir)
        elif isinstance(repo_dir, Path):
            repo_dir_ = repo_dir
        else:
            raise TypeError(f"expected str or Path, got: {type(repo_dir)}")
        self.repo_dir = repo_dir_
        self.raise_on_error = raise_on_error
        self.git_exec = find_git_exec()
        if self.git_exec is None:
            logger.warning("git not found")

    def init(self) -> GitResult:
        """
        Initializes a new Git repository in the directory associated with the Repo
        instance.

        Returns:
            GitResult: The result of executing the `git init` command.

        Behavior:
        - Executes the `git init` command in the repository's directory.
        - Returns the result of the command execution, encapsulating its output and
          status.
        """

        return self.run_git_cmd(INIT)

    def changed_files(self, *, commit: str | None = None) -> list[GitChangedFile]:
        if commit is None:
            result = self.run_git_cmd(STATUS, _SW_PORCELAIN)
        else:
            result = self.run_git_cmd(
                DIFF_TREE,
                "--no-commit-id",
                commit,
                "-r",
                _SW_NAME_STATUS,
            )
        output_lines = result.out.splitlines()
        changes = []
        for line in output_lines:
            # DIFF_TREE uses tabs as delimiter, not spaces
            # the tab is always the second character
            if commit is not None:
                line = line[0] + " " + line[1:]
            logger.info(repr(line))
            action = _status_on_index(line[:2])
            if action == FileStatus.UNKNOWN:
                err = f"unknown modification: {repr(line)}"
                raise exc.DGitError(err)
            rel_path = Path(line[3:].strip())
            abs_path = self.repo_dir / rel_path
            changes.append(
                GitChangedFile(
                    change=action,
                    rel_path=rel_path,
                    abs_path=abs_path,
                )
            )
        return changes

    def commit(self, message: str | None, *, amend=False) -> GitResult:
        """
        Creates a new commit in the Git repository.

        Args:
            message (str | None): The commit message. If None, a default message
                "automated commit" is used.
            amend (bool, optional): Whether to amend the previous commit.
                Defaults to False.

        Returns:
            GitResult: The result of executing the `git commit` command.

        Behavior:
        - If `amend` is True, the commit will modify the previous commit.
        - Uses the provided `message` or a default if none is specified.
        - Executes the `git commit` command with the appropriate flags.
        - Returns the result of the command execution, encapsulating
            its output and status.
        """

        if message is None:
            message = '"automated commit"'
        else:
            message = f"{message}"

        logger.info(f"commit: {message}")
        if amend:
            return self.run_git_cmd(COMMIT, _SW_AMEND, "-m", message)
        return self.run_git_cmd(COMMIT, "-m", message)

    def is_dirty(self) -> bool:
        """
        Checks if the Git repository has no uncommitted changes.

        Returns:
            bool: False if the repository is clean (no changes), True otherwise.

        Behavior:
        - Executes `git status --porcelain` to determine the repository's state.
        - Returns True if the command exits successfully and produces no output,
          indicating a clean repository.
        """
        return not self.is_clean()

    def is_clean(self) -> bool:
        """
        Checks if the Git repository has no uncommitted changes.

        Returns:
            bool: True if the repository is clean (no changes), False otherwise.

        Behavior:
        - Executes `git status --porcelain` to determine the repository's state.
        - Returns True if the command exits successfully and produces no output,
          indicating a clean repository.
        """

        rslt = self.run_git_cmd(STATUS, _SW_PORCELAIN)
        is_clean = rslt.out == ""
        logger.debug(f"repo is clean: {is_clean}")
        return is_clean

    def add(self, files: list[Path | str] | None = None) -> list[GitResult]:
        """
        Stages files for the next commit in the Git repository.

        Args:
            files (list[Path | str] | None): A list of files to stage. If None,
                all changes in the repository will be staged.

        Returns:
            list[GitResult]: A list of results from executing the `git add` command for
            each file or for the entire repository.

        Raises:
            TypeError: If any element in the `files` list is not of type Path or str.

        Behavior:
        - If `files` is None, stages all changes in the repository by running
          `git add --all`.
        - If `files` is provided, stages each file individually by running
          `git add <file>` for each file.
        - Returns a list of GitResult objects encapsulating the results of the
          command executions.
        """
        rslt = []

        if self.is_clean():
            logger.warning("no changes to add")
            return rslt

        if files is None:
            logger.info("adding all files")
            rslt = [self.run_git_cmd(ADD, _SW_ALL)]
            return rslt

        logger.info(f"adding {len(files)} files")
        for f in files:
            if isinstance(f, Path):
                rslt.append(self.run_git_cmd(ADD, f.as_posix()))
            elif isinstance(f, str):
                rslt.append(self.run_git_cmd(ADD, f))
            else:
                raise TypeError(f"expected str or Path, got: {type(f)}")
        return rslt

    def checkout(
        self,
        branch: str,
        missing_ok: bool = False,
    ) -> GitResult:
        """
        Checks out an existing branch or creates a new branch in the Git repository.

        Args:
            branch (str): The name of the branch to check out.
            missing_ok (bool, optional): If True, creates the branch
                if it does not exist.
                Defaults to False.

        Returns:
            GitResult: The result of the `git checkout` or `git checkout -b` command.

        Raises:
            exc.DGitCommandError: If `raise_on_error` is True and the checkout fails for
            reasons other than the branch not existing (or if `missing_ok` is False).

        Behavior:
        - Temporarily disables `raise_on_error` to manage error handling during the
          checkout process.
        - Attempts to check out the specified branch using `git checkout`.
        - If the branch does not exist and `missing_ok` is True, creates the branch
          using `git checkout -b` and returns the result.
        - If the branch does not exist and `missing_ok` is False,
          raises an error or logs
          an error message based on the `raise_on_error` setting.
        """

        # checkout if the branch exists
        raises = self.raise_on_error
        self.raise_on_error = False
        logger.info(f"checking out branch '{branch}'")
        rslt = self.run_git_cmd(CHECKOUT, branch)
        if rslt.code == 0:
            self.raise_on_error = raises
            return rslt

        # we failed, did we fail because the branch does not exist?
        prefix = f"error: pathspec '{branch}' did not match"
        if not rslt.err.startswith(prefix):  # another reason!
            self.raise_on_error = raises
            if raises:
                raise exc.DGitCommandError(f"checkout failed: {rslt.err}")
            else:
                logger.error(f"checkout failed: {rslt.err}")

        # branch does not exist
        if missing_ok:  # create it if we can
            logger.warning(f"creating branch '{branch}'")
            rslt = self.run_git_cmd(CHECKOUT, "-b", branch)
            self.raise_on_error = raises
            return rslt
        else:  # we will not create the branch, raise if raises
            self.raise_on_error = raises
            if raises:
                raise exc.DGitCommandError(
                    f"checkout failed: {rslt.err}, branch does not exist"
                )
            logger.warning(f"branch '{branch}' does not exist")

        self.raise_on_error = raises
        return rslt

    def last_commit_date(self) -> datetime | None:
        result = self.run_git_cmd(LOG, "-1", "--format=%cd")
        first_line = result.out.splitlines()[0]
        try:
            return datetime.strptime(first_line, _DTTM_MASK)
        except Exception as err:
            logger.error(err)
            return None

    def run_git_cmd(self, *args) -> GitResult:
        """
        Executes a Git command within the repository's directory and returns the result.

        Args:
            *args: Positional arguments representing the Git command and its parameters.

        Returns:
            GitResult: An object containing the command's output (`out`), error message
            (`err`), return code (`code`), and the executed arguments (`args`).

        Raises:
            exc.DGitNotFound: If the Git executable is not found.
            exc.DGitCommandError: If the command fails (non-zero return code) and
            `raise_on_error` is True.

        Behavior:
        - Ensures the Git executable is available; raises an error if it is not.
        - Changes the current working directory to the repository's root before
          executing the command.
        - Runs the Git command using `subprocess.run` and captures its standard output
          and error streams.
        - Decodes the output and error messages using UTF-8 with `surrogateescape` to
          handle special characters.
        - If the command fails (non-zero return code) and `raise_on_error` is enabled,
          raises an exception with detailed error information.
        - Returns a `GitResult` object encapsulating the command's results.
        """

        if not self.git_exec:
            raise exc.DGitNotFound("git not found")

        with cwd(self.repo_dir):
            with TemporaryFile() as stdout, TemporaryFile() as stderr:
                # prep the run
                args_ = [self.git_exec, *args]
                logger.debug(f"running git with args: {args}")
                state = subprocess.run(args_, stdout=stdout, stderr=stderr)

                # read the state
                stdout.seek(0)
                stderr.seek(0)
                out = stdout.read().decode("utf-8", errors="surrogateescape")
                err = stderr.read().decode("utf-8", errors="surrogateescape")
                return_code = state.returncode

                # log the results
                logger.debug(f"return_code: {return_code}")
                logger.debug(f"{len(out)} characters on stdout: {repr(out[:40])}")
                logger.debug(f"{len(err)} characters on stderr: {repr(err[:40])}")
            if return_code != 0 and self.raise_on_error:
                msg = (
                    f"git command failed: {args}"
                    f"\n -retcode: {return_code}"
                    f"\n -stdout: {repr(out)}"
                    f"\n -stderr: {repr(err)}"
                )
                raise exc.DGitCommandError(msg)
            return GitResult(
                out=out,
                err=err,
                code=return_code,
                args=args,  # type: ignore
            )


def repo_factory(
    *,
    in_dir: str | Path | None = None,
    raise_on_error: bool = True,
) -> Repo | None:
    """
    Creates a Repo instance for the current working directory if it is within a Git
    repository.

    Returns:
        Repo | None: A Repo instance for the current working directory or None if the
        directory is not in a Git repository.

    Behavior:
    - Finds the root of the Git repository using `find_repo_root`.
    - Returns a Repo instance for the repository root if found, or None if not in a Git
      repository.
    """

    root = find_repo_root(in_dir=in_dir)
    if root is None:
        return None
    return Repo(root, raise_on_error=raise_on_error)


def _status_on_index(status_str: str) -> FileStatus:
    _ONE_LETTER_CHANGE_TO_TYPE = {
        "M": FileStatus.MODIFIED,
        "A": FileStatus.ADDED,
        "D": FileStatus.DELETED,
        "R": FileStatus.RENAMED,
        "C": FileStatus.COPIED,
        "U": FileStatus.UNMERGED,
        "??": FileStatus.UNTRACKED,
    }

    _status_str = status_str.strip()
    if _status_str == "":
        return FileStatus.UNCHANGED

    # simplistic state - it is either staged, or unstaged, nothing in between
    # meaning that we generally expect the status of the file to be
    # one character long (without space)
    # for example:
    #   ' M' - staged, modified - stripped to 'M'
    #   ' A' - new, staged - stripped to 'A'
    #   'M ' - modified, not staged - - stripped to 'M'
    try:
        return _ONE_LETTER_CHANGE_TO_TYPE[_status_str]
    except KeyError:
        pass

    # more complex scenarios - index is the place to look at the change
    # for example - 'MA' as a state, file is added (staged) and then modified
    # at the index, modification is not yet staged, hence we assume the file
    # to be modified
    if len(_status_str) == 2:
        try:
            return _ONE_LETTER_CHANGE_TO_TYPE[_status_str[0]]
        except KeyError:
            pass

    # give up
    return FileStatus.UNKNOWN
