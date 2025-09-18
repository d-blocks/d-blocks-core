import os
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta
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
DIFF = "diff"
BRANCH = "branch"

_SW_AMEND = "--amend"
_SW_PORCELAIN = "--porcelain"
_SW_ALL = "--all"
_DTTM_MASK = "%Y-%m-%d %H:%M:%S"
_SW_NAME_STATUS = "--name-status"
_FMT_BRANCH_NAME = '--format="%(refname:short)"'  # no asterisk before active branch


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
class GitChangedPath:
    change: FileStatus
    rel_path: Path
    abs_path: Path
    # renames only
    rename_from_rel_path: Path | None
    rename_from_abs_path: Path | None
    rename_simillarity: int | None


def find_git_exec() -> str | None:
    """Locate the Git executable in the system path.

    Args:
        None

    Raises:
        None

    Returns:
        str | None: The path to the Git executable if found,
            otherwise None.
    """

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

    def get_current_branch(self) -> str:
        """Retrieve the name of the current Git branch.

        Args:
            None

        Raises:
            DGitCommandError: If the branch name cannot be determined.

        Returns:
            str: The name of the current branch.
        """

        cmd = [BRANCH, "--show-current"]
        result = self.run_git_cmd(*cmd)
        branch = result.out.splitlines()[0].strip()
        if len(branch) == 0:
            cmd_str = "git " + " ".join(cmd)
            raise exc.DGitCommandError(f"failed to get current branch: {cmd_str}")
        return branch

    def get_merge_base(
        self,
        branch1: str,
        branch2: str,
        *,
        method: str | None = None,
    ) -> str:
        """Find the common ancestor commit of two branches.

        Args:
            branch1 (str): The first branch name.
            branch2 (str): The second branch name.
            method (str | None, optional): Merge base calculation method,
                either 'fork-point' or 'octopus'. Defaults to None.

        Raises:
            DGitCommandError: If the merge base cannot be determined.

        Returns:
            str: The commit hash of the common ancestor.
        """

        cmd = ["merge-base", branch1, branch2]
        if method:
            if method not in {"fork-point", "octopus"}:
                raise exc.DGitCommandError(
                    f"method: can be only fork-point or octpus, not: {repr(method)}"
                )
            cmd = ["merge-base", f"--{method}", branch1, branch2]

        result = self.run_git_cmd(*cmd)
        commit = result.out.splitlines()[0].strip()
        if len(commit) == 0:
            cmd_str = "git " + " ".join(cmd)
            raise exc.DGitCommandError(
                f"failed to get last common commit between {branch1} and {branch2}: {cmd_str}"
            )
        return commit

    def changes_between_commits(
        self,
        *,
        baseline_commit: str,
        last_commit: str,
        rename_pct_simillarity: int = 100,
    ) -> list[GitChangedPath]:
        """
        This method compares two commits and returns a list of changed files between them.
        Behavior:

            - Runs git diff --name-status <base_commit> <second_commit> to get the file changes.
            - Parses each output line, which consists of:
                - A single-character status code (M, A, D, etc.).
                - A tab (\t).
                - The file path.
            - Uses _status_on_index(status_) to map Git’s status code to FileStatus.
            - Converts the file path into Path objects (relative and absolute).
            - Returns a list of GitChangedPath objects with:
                - change: The type of modification.
                - rel_path: The file path relative to the repo.
                - abs_path: The absolute file path.

        Error Handling:
            Raises exc.DGitError if a line does not match the expected format.
            Raises exc.DGitError if an unknown status code is encountered.

        This ensures that the method correctly reports file changes between two commits.

        Args:
            base_commit (str): the case commit - this is the commit we compare to (first commit)
            second_commit (str): second commit, which is the end of the change tree

        Raises:
            exc.DGitError: in case there was problem with parsing git output

        Returns:
            list[GitChangedPath]: list of changes
        """
        result = self.run_git_cmd(
            DIFF,
            _SW_NAME_STATUS,
            f"-M{rename_pct_simillarity}%",
            baseline_commit,
            last_commit,
        )
        output_lines = result.out.splitlines()
        changes = []
        for line in output_lines:
            # git diff --name-status uses tab as delimiter (second character)
            # status is the first part, see the docs - --diff-filter=[(A|C|D|M|R|T|U|X|B)...[*]]
            # https://git-scm.com/docs/diff-options
            # for renames (R) we have a simillarity in percent after the status
            # --find-renames[=<n>] / -M<n>
            #       For example, -M90% means Git should consider a delete/add pair to be a rename
            #       if more than 90% of the file hasn’t changed.
            #       The default similarity index is 50%.
            #       To limit detection to exact renames, use -M100%
            # FIXME: we have very simillar code in changes_on_commit, this should be refactored
            # FIXME: changes_on_commit contains bug (renames)

            simillarity: int | None = None
            rename_from_rel_path: Path | None = None
            rename_from_abs_path: Path | None = None

            parts = line.split("\t")
            status_, file_, *rest = parts

            # sanity check
            if len(parts) != 2:
                if len(parts) > 3:
                    raise exc.DGitError(
                        f"unexpected tab in line, please raise an issue: {repr(line)=}"
                    )
                if status_[0] != "R":
                    raise exc.DGitError(
                        f"expected rename, got something else, please raise an issue: {repr(line)=}"
                    )

                # we know that the action is labeled as rename
                # status now contains string in form of Rxxx, where xxx is an int (simillarity)
                try:
                    simillarity = int(status_[1:])
                    rename_from_rel_path = Path(file_)
                    rename_from_abs_path = self.repo_dir / file_
                    rel_path = Path(rest[0])
                    abs_path = self.repo_dir / rest[0]
                    status_ = status_[0]
                except Exception as err:
                    raise exc.DGitError(
                        f"failed to get rename details, please raise an issue: {repr(line)=}\nerror: {err}"
                    )
            else:
                rel_path = Path(file_)
                abs_path = self.repo_dir / rel_path

            action = _status_on_index(status_)

            if action == FileStatus.UNKNOWN:
                err = f"unknown modification: {repr(line)}"
                raise exc.DGitError(err)

            changes.append(
                GitChangedPath(
                    change=action,
                    rel_path=rel_path,
                    abs_path=abs_path,
                    rename_simillarity=simillarity,
                    rename_from_abs_path=rename_from_abs_path,
                    rename_from_rel_path=rename_from_rel_path,
                )
            )
        return changes

    # FIXME: this needs refactoring, and it does not handle renames correctly!
    def changes_on_commit(self, *, commit: str | None = None) -> list[GitChangedPath]:
        """
        This method retrieves the list of changed files in the repository,
        either for the working directory (unstaged changes) or for a specific commit.

        Args:
            commit: sha of the commit (or tag)

        Behavior:
            - If no commit is provided, it runs git status --porcelain
                to get the current working directory's changes.
            - If a commit is specified, it runs git diff-tree --no-commit-id -r --name-status <commit> to get the changes in that commit.
            - The output is parsed:
                - For git diff-tree, tabs are used as delimiters, so it adjusts the format.
                - The first two characters indicate the file change status.
                - The rest of the line contains the file path.
            - It converts the relative file paths into absolute ones using self.repo_dir.
            - Each changed file is stored as a GitChangedPath object with:
                - change: The type of change (Modified, Added, Deleted, etc.).
                - rel_path: The relative path of the file in the repo.
                - abs_path: The absolute file path.

        Raises:
            exc.DGitError if an unknown modification status is encountered.

        Returns:
            list[GitChangedPath]: list of changes
        """

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
            action = _status_on_index(line[:2])
            if action == FileStatus.UNKNOWN:
                err = f"unknown modification: {repr(line)}"
                raise exc.DGitError(err)
            rel_path = Path(line[3:].strip())
            abs_path = self.repo_dir / rel_path
            changes.append(
                GitChangedPath(
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

        logger.info(f"{message}")
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
            logger.debug("adding all files")
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

    def get_branches_with_commit(self, commit: str) -> list[str]:
        """Get a list of branches that contain a given commit.

        Args:
            commit (str): The commit hash to check.

        Returns:
            list[str]: A list of branch names that contain the commit.
        """

        cmd = [BRANCH, _FMT_BRANCH_NAME, "--contains", commit]
        result = self.run_git_cmd(*cmd)
        branches = [
            b.strip().removeprefix('"').removesuffix('"')
            for b in result.out.splitlines()
        ]
        return branches

    def get_last_commit_sha(self, branch: str | None = None):
        """Get the SHA of the last commit on a specified branch.

        Args:
            branch (str | None): The branch name. Defaults to None.

        Raises:
            DGitCommandError: If the last commit SHA cannot be retrieved.

        Returns:
            str: The SHA of the last commit.
        """

        # git show --pretty=format:"%H" --no-patch develop
        cmd = ["show", "--pretty=format:%H", "--no-patch"]
        if branch:
            cmd.append(branch)
        result = self.run_git_cmd(*cmd)
        commit = result.out.splitlines()[0].strip()
        if len(commit) == 0:
            raise exc.DGitCommandError(
                "failed to get last commit: git " + " ".join(cmd)
            )
        return commit

    def is_commit_on_branch(self, branch: str, commit: str) -> bool:
        branches_with_commit = self.get_branches_with_commit(commit)
        logger.info(branches_with_commit)
        return branch in branches_with_commit

    def last_commit_date(self) -> datetime | None:
        """Get the SHA of the last commit on a specified branch.

        Args:
            branch (str | None): The branch name. Defaults to None.

        Raises:
            DGitCommandError: If the last commit SHA cannot be retrieved.

        Returns:
            str: The SHA of the last commit.
        """

        result = self.run_git_cmd(LOG, "-1", "--format=%cd")
        first_line = result.out.splitlines()[0]
        try:
            return datetime.strptime(first_line, _DTTM_MASK)
        except Exception as err:
            logger.error(err)
            return None

    def get_all_branches(self, mode: str = "local") -> list[str]:
        """Get a list of branches in the repository.

        Args:
            mode (str): Branch mode - "local", "remote", or "both". Defaults to "local".

        Returns:
            list[str]: A list of branch names.
        """
        if mode not in ["local", "remote", "both"]:
            raise ValueError(f"Invalid mode '{mode}'. Must be 'local', 'remote', or 'both'.")
        
        branches = []
        
        if mode in ["local", "both"]:
            # Get local branches only
            cmd = [BRANCH, _FMT_BRANCH_NAME]
            result = self.run_git_cmd(*cmd)
            
            for line in result.out.splitlines():
                branch = line.strip().removeprefix('"').removesuffix('"')
                if branch:
                    branches.append(branch)
        
        if mode in ["remote", "both"]:
            # Get remote branches only
            cmd = [BRANCH, "-r", _FMT_BRANCH_NAME]
            result = self.run_git_cmd(*cmd)
            
            for line in result.out.splitlines():
                branch = line.strip().removeprefix('"').removesuffix('"')
                if branch and branch != "origin" and "HEAD" not in branch:
                    branches.append(branch)
        
        return branches

    def get_last_commit_info(self, branch: str) -> tuple[str, str, datetime]:
        """Get the last commit info for a specific branch.

        Args:
            branch (str): The branch name.

        Returns:
            tuple[str, str, datetime]: Commit SHA, author name, and commit date.
        """
        cmd = [LOG, "-1", "--format=%H|%an|%cd", f"--date=format:{_DTTM_MASK}", branch]
        result = self.run_git_cmd(*cmd)
        
        if not result.out.strip():
            raise exc.DGitCommandError(f"No commits found on branch: {branch}")
        
        parts = result.out.strip().split("|")
        if len(parts) != 3:
            raise exc.DGitCommandError(f"Unexpected format in commit info: {result.out}")
        
        commit_sha, author, date_str = parts
        commit_date = datetime.strptime(date_str, _DTTM_MASK)
        
        return commit_sha, author, commit_date

    def is_branch_merged(self, branch: str, target_branches: list[str] = None) -> tuple[bool, str | None, datetime | None]:
        """Check if a branch has been merged into any of the target branches.
        
        This method detects both traditional merges and squash merges.

        Args:
            branch (str): The branch to check.
            target_branches (list[str], optional): List of target branches to check against.
                Defaults to ['main', 'master', 'develop'].

        Returns:
            tuple[bool, str | None, datetime | None]: (is_merged, merged_to_branch, merge_date)
        """
        if target_branches is None:
            target_branches = ['main', 'master', 'develop']
        
        # Get all existing branches to check which target branches actually exist
        # Include both local and remote branches for comprehensive checking
        all_branches = self.get_all_branches(mode="both")
        existing_targets = []
        
        for target in target_branches:
            # Check for exact match (local branch)
            if target in all_branches:
                existing_targets.append(target)
            # Check for remote versions
            for branch_name in all_branches:
                if branch_name.endswith(f"/{target}") or branch_name.endswith(f"origin/{target}"):
                    existing_targets.append(branch_name)
        
        # Remove duplicates while preserving order
        existing_targets = list(dict.fromkeys(existing_targets))
        
        for target in existing_targets:
            try:
                # Method 1: Check traditional merge using git branch --merged
                cmd = [BRANCH, "--merged", target]
                result = self.run_git_cmd(*cmd)
                
                merged_branches = [
                    line.strip().removeprefix("* ").strip()
                    for line in result.out.splitlines()
                ]
                
                if branch in merged_branches and branch != target:
                    # Find the merge commit date
                    merge_date = self._get_merge_date(branch, target)
                    
                    # Check if branch has moved forward since the merge
                    if self._has_branch_moved_since_merge(branch, merge_date):
                        continue  # Branch has new commits, check other targets
                    
                    return True, target, merge_date
                
                # Method 2: Check for squash merges by looking for commits that contain the branch changes
                squash_merged, squash_date = self._check_squash_merge(branch, target)
                if squash_merged:
                    # Check if branch has moved forward since the squash merge
                    if self._has_branch_moved_since_merge(branch, squash_date):
                        continue  # Branch has new commits, check other targets
                    
                    return True, target, squash_date
                    
            except exc.DGitCommandError:
                # Target branch might not exist, continue checking others
                continue
        
        return False, None, None

    def _check_squash_merge(self, branch: str, target: str) -> tuple[bool, datetime | None]:
        """Check if a branch was squash-merged into the target branch.
        
        This method detects squash merges by comparing the changes between branches
        and looking for commit messages that might indicate a squash merge.

        Args:
            branch (str): The feature branch to check.
            target (str): The target branch to check against.

        Returns:
            tuple[bool, datetime | None]: (is_squash_merged, squash_merge_date)
        """
        try:
            # Method 1: Look for commits in target that mention the branch name
            # Common squash merge patterns include variations of the branch name
            clean_branch = branch.removeprefix("origin/").removeprefix("remotes/")
            
            # Create multiple search patterns for flexible matching
            search_patterns = []
            
            # Pattern 1: Exact branch name
            search_patterns.append(clean_branch)
            
            # Pattern 2: Convert hyphens to spaces and capitalize words
            # feature/ci-test-workflow -> Feature/ci test workflow
            if "/" in clean_branch:
                parts = clean_branch.split("/")
                if len(parts) == 2:
                    prefix, suffix = parts
                    formatted_suffix = suffix.replace("-", " ").replace("_", " ")
                    search_patterns.append(f"{prefix.title()}/{formatted_suffix}")
                    search_patterns.append(f"{prefix.title()}/{formatted_suffix.title()}")
            
            # Pattern 3: Just the suffix part (after the last /)
            if "/" in clean_branch:
                suffix = clean_branch.split("/")[-1]
                search_patterns.append(suffix)
                search_patterns.append(suffix.replace("-", " "))
                search_patterns.append(suffix.replace("-", " ").title())
            
            # Pattern 4: Remove common prefixes like "feature/", "bugfix/", etc.
            if clean_branch.startswith(("feature/", "bugfix/", "hotfix/", "chore/")):
                short_name = clean_branch.split("/", 1)[1]
                search_patterns.append(short_name)
                search_patterns.append(short_name.replace("-", " "))
                search_patterns.append(short_name.replace("-", " ").title())
            
            # Try each pattern
            for pattern in search_patterns:
                try:
                    cmd = [LOG, "--oneline", "--grep", pattern, target, "-1"]
                    result = self.run_git_cmd(*cmd)
                    
                    if result.out.strip():
                        # Found a commit that mentions this pattern, likely a squash merge
                        # Get the date of this commit
                        cmd = [LOG, "--format=%cd", f"--date=format:{_DTTM_MASK}", "--grep", pattern, target, "-1"]
                        result = self.run_git_cmd(*cmd)
                        
                        if result.out.strip():
                            merge_date = datetime.strptime(result.out.strip(), _DTTM_MASK)
                            logger.debug(f"Found squash merge using pattern '{pattern}': {merge_date}")
                            return True, merge_date
                            
                except exc.DGitCommandError:
                    # Pattern search failed, try next pattern
                    continue
            
            # Method 2: Check if the branch tip commit exists anywhere in target's history
            # This would indicate the changes were incorporated (possibly squashed)
            try:
                branch_tip = self.get_last_commit_sha(branch)
                
                # Check if any commit in target contains the same changes
                # Use git cherry to find commits that haven't been applied upstream
                cmd = ["cherry", target, branch]
                result = self.run_git_cmd(*cmd)
                
                # If cherry returns empty output, all commits from branch are in target
                if not result.out.strip():
                    # Branch appears to be fully merged/squashed
                    # Try to find the most recent commit in target that could be the squash
                    return self._find_potential_squash_commit(branch, target)
                    
            except exc.DGitCommandError:
                # cherry command might fail if branches are too divergent
                pass
            
            # Method 3: Compare the diff between branch and target
            # If there's no diff, the changes are already incorporated
            try:
                cmd = ["diff", f"{target}...{branch}", "--quiet"]
                result = self.run_git_cmd(*cmd)
                
                # If diff --quiet succeeds (return code 0), there are no differences
                if result.code == 0:
                    # No differences means changes are incorporated
                    return self._find_potential_squash_commit(branch, target)
                    
            except exc.DGitCommandError:
                # diff might fail, continue with other methods
                pass
                
        except Exception as err:
            logger.debug(f"Error checking squash merge for {branch} into {target}: {err}")
        
        return False, None

    def _find_potential_squash_commit(self, branch: str, target: str) -> tuple[bool, datetime | None]:
        """Find the most likely squash commit in target for the given branch.

        Args:
            branch (str): The feature branch.
            target (str): The target branch.

        Returns:
            tuple[bool, datetime | None]: (found, commit_date)
        """
        try:
            # Get the branch creation point (where it diverged from target)
            cmd = ["merge-base", target, branch]
            result = self.run_git_cmd(*cmd)
            merge_base = result.out.strip()
            
            if merge_base:
                # Get the last commit date of the branch
                branch_last_commit_date = self.get_last_commit_info(branch)[2]
                
                # Look for commits in target after the merge base and around the branch's last commit time
                # Search in a window around the branch's last commit time (±7 days)
                start_date = (branch_last_commit_date - timedelta(days=7)).strftime(_DTTM_MASK)
                end_date = (branch_last_commit_date + timedelta(days=7)).strftime(_DTTM_MASK)
                
                cmd = [LOG, f"--since={start_date}", f"--until={end_date}", 
                       "--format=%cd", f"--date=format:{_DTTM_MASK}", target, "-1"]
                result = self.run_git_cmd(*cmd)
                
                if result.out.strip():
                    squash_date = datetime.strptime(result.out.strip(), _DTTM_MASK)
                    return True, squash_date
                    
        except Exception as err:
            logger.debug(f"Error finding potential squash commit for {branch}: {err}")
        
        return False, None

    def get_last_commit_sha(self, branch: str) -> str:
        """Get the SHA of the last commit for a specific branch.

        Args:
            branch (str): The branch name.

        Returns:
            str: The commit SHA.
        """
        cmd = ["show", "--pretty=format:%H", "--no-patch", branch]
        result = self.run_git_cmd(*cmd)
        return result.out.strip()

    def _get_merge_date(self, branch: str, target: str) -> datetime | None:
        """Get the date when a branch was merged into target branch.

        Args:
            branch (str): The merged branch.
            target (str): The target branch.

        Returns:
            datetime | None: The merge date or None if not found.
        """
        try:
            # Look for merge commits that mention the branch
            cmd = [LOG, "--grep", f"Merge.*{branch}", "--format=%cd", f"--date=format:{_DTTM_MASK}", target, "-1"]
            result = self.run_git_cmd(*cmd)
            
            if result.out.strip():
                return datetime.strptime(result.out.strip(), _DTTM_MASK)
            
            # Alternative: find the first commit in target that contains the branch tip
            branch_tip = self.get_last_commit_sha(branch)
            cmd = [LOG, "--format=%cd", f"--date=format:{_DTTM_MASK}", "--ancestry-path", f"{branch_tip}..{target}", "-1"]
            result = self.run_git_cmd(*cmd)
            
            if result.out.strip():
                return datetime.strptime(result.out.strip(), _DTTM_MASK)
                
        except Exception as err:
            logger.debug(f"Could not determine merge date for {branch} into {target}: {err}")
        
        return None

    def _has_branch_moved_since_merge(self, branch: str, merge_date: datetime | None) -> bool:
        """Check if a branch has new commits after the given merge date.

        Args:
            branch (str): The branch to check.
            merge_date (datetime | None): The date when the branch was merged.

        Returns:
            bool: True if the branch has commits newer than the merge date, False otherwise.
        """
        if merge_date is None:
            return True  # If we can't determine merge date, assume branch has moved
        
        try:
            # Get the last commit date of the branch
            _, _, branch_last_commit_date = self.get_last_commit_info(branch)
            
            # If the branch's last commit is newer than the merge date, it has moved forward
            has_moved = branch_last_commit_date > merge_date
            
            if has_moved:
                logger.debug(f"Branch {branch} has moved since merge: "
                           f"last commit {branch_last_commit_date} > merge date {merge_date}")
            else:
                logger.debug(f"Branch {branch} has not moved since merge: "
                           f"last commit {branch_last_commit_date} <= merge date {merge_date}")
            
            return has_moved
            
        except Exception as err:
            logger.debug(f"Error checking if branch {branch} moved since merge: {err}")
            return True  # If we can't determine, assume it has moved (safer to show as active)

    def get_branch_creation_date(self, branch: str) -> datetime | None:
        """Get the creation date of a branch by finding when it diverged from main branches.

        Args:
            branch (str): The branch name to get creation date for.

        Returns:
            datetime | None: The creation date or None if not determinable.
        """
        try:
            # Only for the primary main branch (master/main), use the first commit in repo
            clean_branch = branch.removeprefix("origin/").removeprefix("remotes/")
            if clean_branch in ['master', 'main']:
                cmd = [LOG, "--reverse", "--format=%cd", f"--date=format:{_DTTM_MASK}", branch]
                result = self.run_git_cmd(*cmd)
                if result.out.strip():
                    # Take the first line (first commit)
                    first_line = result.out.strip().split('\n')[0]
                    return datetime.strptime(first_line, _DTTM_MASK)
            
            # For develop branches (long-lived), find the first unique commit after initial commit
            if clean_branch in ['develop']:
                # Get all commits on this branch from the beginning
                cmd = [LOG, "--reverse", "--format=%cd", f"--date=format:{_DTTM_MASK}", branch]
                result = self.run_git_cmd(*cmd)
                if result.out.strip():
                    lines = result.out.strip().split('\n')
                    # Skip the first commit (initial repository commit) and return the second
                    if len(lines) > 1:
                        creation_date = datetime.strptime(lines[1], _DTTM_MASK)
                        logger.debug(f"Branch {branch} creation date: {creation_date}")
                        return creation_date
            
            # For all other branches (feature branches), find when they diverged from the primary main branch
            primary_main_branches = ['master', 'main', 'origin/master', 'origin/main']
            
            # Try to find merge-base with each primary main branch
            for main_branch in primary_main_branches:
                try:
                    # Check if main branch exists
                    all_branches = self.get_all_branches(mode="both")
                    if main_branch not in all_branches:
                        continue
                    
                    # Find merge-base (common ancestor)
                    cmd = ["merge-base", main_branch, branch]
                    result = self.run_git_cmd(*cmd)
                    
                    if result.out.strip():
                        merge_base = result.out.strip()
                        
                        # Get the first commit on this branch after the merge-base
                        cmd = [LOG, "--reverse", "--format=%cd", f"--date=format:{_DTTM_MASK}", 
                               f"{merge_base}..{branch}"]
                        result = self.run_git_cmd(*cmd)
                        
                        if result.out.strip():
                            # Take the first line (first commit after merge-base)
                            first_line = result.out.strip().split('\n')[0]
                            creation_date = datetime.strptime(first_line, _DTTM_MASK)
                            logger.debug(f"Branch {branch} creation date: {creation_date}")
                            return creation_date
                            
                except exc.DGitCommandError:
                    # Try next main branch
                    continue
            
            # Fallback: use the first commit on the branch
            cmd = [LOG, "--reverse", "--format=%cd", f"--date=format:{_DTTM_MASK}", branch, "-1"]
            result = self.run_git_cmd(*cmd)
            if result.out.strip():
                return datetime.strptime(result.out.strip(), _DTTM_MASK)
                
        except Exception as err:
            logger.debug(f"Error getting creation date for {branch}: {err}")
        
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
        - Runs the Git command using `subprocess.Popen` and captures its standard output
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
            # prep the run
            args_ = [self.git_exec, *args]
            logger.debug(f"running git with args: {args}")
            state = subprocess.Popen(
                args_, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # execute and read the state
            stdout, stderr = state.communicate()
            out = stdout.decode("utf-8", errors="surrogateescape")
            err = stderr.decode("utf-8", errors="surrogateescape")
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
