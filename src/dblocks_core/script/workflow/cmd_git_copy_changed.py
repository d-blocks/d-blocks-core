import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Tuple

from rich.console import Console
from rich.prompt import Prompt

from dblocks_core import exc
from dblocks_core.config.config import logger
from dblocks_core.git import git
from dblocks_core.model import config_model
from dblocks_core.packager import change_script_gen, release_notes, table_differ
from dblocks_core.parse import table_parser
from dblocks_core.writer import fsystem

console = Console()


TO_COPY = (
    git.FileStatus.ADDED,  # staged
    git.FileStatus.MODIFIED,
    git.FileStatus.UNTRACKED,
)

# ---------------------------------------------------------------------------
# Package folder ordering
# ---------------------------------------------------------------------------

# Double-digit prefixed folders that determine deployment order:
#  010 - tables (deployed first, uses change scripts)
#  020 - views and indices
#  030 - executables (procedures, macros, functions, triggers)
#  050 - generic sql
#  080 - drop scripts for deleted objects
#  090 - drop backup tables created during deployment
PKG_STP_TABLES = "010-tables"
PKG_STP_VIEWS_INDICES = "020-views-indices"
PKG_STP_EXECUTABLES = "030-executables"
PKG_STP_GENERIC_SQL = "050-sql"
PKG_STP_DROPS = "080-drops"
PKG_STP_DROP_BACKUPS = "090-drop-backups"

_EXT_TO_PKG_STEP: dict[str, str] = {
    fsystem.TABLE_SUFFIX: PKG_STP_TABLES,
    fsystem.VIEW_SUFFIX: PKG_STP_VIEWS_INDICES,
    fsystem.JIDX_SUFFIX: PKG_STP_VIEWS_INDICES,
    fsystem.IDX_SUFFIX: PKG_STP_VIEWS_INDICES,
    fsystem.PROC_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.MACRO_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.FUNCTION_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.FUNCTION_MAPPING_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.TRIGGER_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.TYPE_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.AUTH_SUFFIX: PKG_STP_EXECUTABLES,
    fsystem.GENERIC_SQL_SUFFIX: PKG_STP_GENERIC_SQL,
    fsystem.GENERIC_BTEQ_SUFFIX: PKG_STP_GENERIC_SQL,
    fsystem.PROFILE_SUFFIX: PKG_STP_GENERIC_SQL,
    fsystem.ROLE_SUFFIX: PKG_STP_GENERIC_SQL,
    fsystem.DATABASE_SUFFIX: PKG_STP_GENERIC_SQL,
}


def _is_table_file(path: Path) -> bool:
    """Check if the given path represents a Teradata table script."""
    return path.suffix.lower() == fsystem.TABLE_SUFFIX


def _is_metadata_file(path: Path, metadata_dir: Path) -> bool:
    """Check if the file is within the metadata directory."""
    try:
        return path.is_relative_to(metadata_dir)
    except (TypeError, ValueError):
        return False


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
    """Create an incremental deployment package based on git diff.

    Enhanced workflow:

    1. Gather the list of changed files from git.
    2. Classify each change (table vs other, new / modified / deleted).
    3. For **modified tables** – parse old and new DDL, compute a diff,
       and generate the appropriate change script:

       - *Structural change* → RENAME-CREATE-INSERT strategy.
       - *Non-structural change* (stats / comments) → re-execute only the
         changed statements.

    4. For **deleted tables** – generate a RENAME … _obsolete<ts> script.
    5. For **deleted non-table objects** – generate a DROP statement.
    6. For **added / modified non-table objects** – copy as-is.
    7. Organise the package into ordered step folders (010-tables first,
       080-drops near the end, 090-drop-backups last).
    8. Write release notes.
    """

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

    if len(changes) == 0:
        logger.warning("Empty list of changed files.")
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

    # resolve the baseline commit for retrieving old file versions
    baseline_commit = _resolve_baseline_commit(repo, diff_against, diff_ident)

    # fixed timestamp for the whole package (deterministic suffixes)
    ts = datetime.now()

    # process the changeset
    all_warnings: list[str] = []
    dirs_created: set[Path] = set()

    can_copy = {
        git.FileStatus.ADDED,
        git.FileStatus.MODIFIED,
        git.FileStatus.COPIED,
        git.FileStatus.RENAMED,
        git.FileStatus.UNTRACKED,
        git.FileStatus.UNMERGED,
    }

    # Build abs_metadata_dir WITHOUT .resolve() – c.abs_path (from the git
    # module) is constructed as ``repo.repo_dir / rel_path`` which is also
    # NOT resolved.  Using .resolve() here would follow junctions / symlinks
    # (common on Windows with OneDrive Desktop redirect) and produce a
    # different prefix, causing is_relative_to() to fail.
    abs_metadata_dir = (
        metadata_dir
        if metadata_dir.is_absolute()
        else repo.repo_dir / metadata_dir
    )

    for c in changes:
        is_meta = _is_metadata_file(c.abs_path, abs_metadata_dir)

        # --- DELETED files ---
        if c.change == git.FileStatus.DELETED:
            if not is_meta:
                logger.debug(f"skip deleted non-metadata file: {c.rel_path}")
                continue
            _handle_deletion(
                c, repo, pkg_root_dir, steps_subdir, metadata_dir,
                ts=ts, warnings=all_warnings, dirs_created=dirs_created,
                baseline_commit=baseline_commit,
            )
            continue

        # --- ADDED / MODIFIED / etc. ---
        if c.change not in can_copy:
            logger.debug(f"skip unsupported change type: {c.change}: {c.rel_path}")
            continue

        copy_from = repo.repo_dir / c.rel_path
        if not copy_from.exists():
            logger.warning(f"file does not exist: {copy_from}")
            continue

        if is_meta and _is_table_file(c.abs_path):
            _handle_table_change(
                c, repo, pkg_root_dir, steps_subdir, metadata_dir,
                ts=ts, warnings=all_warnings, dirs_created=dirs_created,
                baseline_commit=baseline_commit,
            )
        else:
            # non-table object → copy as-is
            copy_to = pkg_root_dir / _rel_path_in_package(
                repo_dir_absp=repo.repo_dir,
                src_file_absp=c.abs_path,
                metadata_dir_absp=abs_metadata_dir,
                steps_subdir=steps_subdir,
            )
            _ensure_parent(copy_to, dirs_created)
            shutil.copy(copy_from, copy_to)

    # --- release notes ---
    notes = release_notes.build_release_notes(
        changes, package_name, warnings=all_warnings, ts=ts,
    )
    notes_text = release_notes.render_release_notes(notes)
    notes_path = pkg_root_dir / "RELEASE_NOTES.md"
    _ensure_parent(notes_path, dirs_created)
    notes_path.write_text(notes_text, encoding="utf-8")
    logger.info(f"Release notes written to: {notes_path.as_posix()}")

    # print warnings
    if all_warnings:
        console.print(
            f"\n[bold yellow]⚠️  {len(all_warnings)} warning(s) during package creation:[/bold yellow]"
        )
        for w in all_warnings:
            console.print(f"  - {w}", style="yellow")


# ---------------------------------------------------------------------------
# Handlers for table and deletion changes
# ---------------------------------------------------------------------------


def _handle_table_change(
    change: git.GitChangedPath,
    repo: git.Repo,
    pkg_root_dir: Path,
    steps_subdir: Path,
    metadata_dir: Path,
    *,
    ts: datetime,
    warnings: list[str],
    dirs_created: set[Path],
    baseline_commit: str,
):
    """Handle a changed or added table file.

    For **new** tables we simply copy the DDL as-is.
    For **modified** tables we parse old & new DDL, compute the diff,
    and generate the appropriate change script.
    """

    db_name = change.abs_path.parent.name
    table_file_name = change.abs_path.name
    table_stem = change.abs_path.stem

    # read current (new) version
    current_path = repo.repo_dir / change.rel_path
    new_ddl_text = current_path.read_text(encoding="utf-8", errors="strict")

    # try to read old version from baseline commit
    old_ddl_text = repo.get_file_content_at_commit(
        baseline_commit, change.rel_path,
    )

    if old_ddl_text is None:
        # new table — copy DDL as-is
        logger.info(f"new table: {change.rel_path}")
        target = pkg_root_dir / steps_subdir / PKG_STP_TABLES / db_name / table_file_name
        _ensure_parent(target, dirs_created)
        target.write_text(new_ddl_text, encoding="utf-8")
        return

    # parse both versions
    old_parsed = table_parser.parse_table_ddl(old_ddl_text)
    new_parsed = table_parser.parse_table_ddl(new_ddl_text)

    if old_parsed is None or new_parsed is None:
        logger.warning(
            f"could not parse table DDL for {change.rel_path}, copying as-is"
        )
        target = pkg_root_dir / steps_subdir / PKG_STP_TABLES / db_name / table_file_name
        _ensure_parent(target, dirs_created)
        shutil.copy(current_path, target)
        return

    # diff
    diff = table_differ.diff_tables(old_parsed, new_parsed)

    if diff.kind == table_differ.TableChangeKind.NO_CHANGE:
        logger.info(f"no effective change for table: {change.rel_path}")
        return

    if diff.kind == table_differ.TableChangeKind.TABLE_STRUCTURE_CHANGED:
        logger.info(f"structural change for table: {change.rel_path}")
        script, script_warnings = change_script_gen.generate_table_change_script(
            old_parsed, new_parsed, diff, ts=ts,
        )
        warnings.extend(script_warnings)

        # write change script
        change_file = f"{table_stem}_change.sql"
        target = pkg_root_dir / steps_subdir / PKG_STP_TABLES / db_name / change_file
        _ensure_parent(target, dirs_created)
        target.write_text(script, encoding="utf-8")

        # write drop-backup script
        drop_bkp = change_script_gen.generate_drop_backup_script(new_parsed, ts=ts)
        drop_file = f"{table_stem}_drop_bkp.sql"
        drop_target = (
            pkg_root_dir / steps_subdir / PKG_STP_DROP_BACKUPS / db_name / drop_file
        )
        _ensure_parent(drop_target, dirs_created)
        drop_target.write_text(drop_bkp, encoding="utf-8")

    elif diff.kind == table_differ.TableChangeKind.NON_STRUCTURAL_CHANGE:
        logger.info(f"non-structural change for table: {change.rel_path}")
        script = change_script_gen.generate_non_structural_change_script(
            old_parsed, new_parsed, diff, ts=ts,
        )
        change_file = f"{table_stem}_change.sql"
        target = pkg_root_dir / steps_subdir / PKG_STP_TABLES / db_name / change_file
        _ensure_parent(target, dirs_created)
        target.write_text(script, encoding="utf-8")


def _handle_deletion(
    change: git.GitChangedPath,
    repo: git.Repo,
    pkg_root_dir: Path,
    steps_subdir: Path,
    metadata_dir: Path,
    *,
    ts: datetime,
    warnings: list[str],
    dirs_created: set[Path],
    baseline_commit: str,
):
    """Handle a deleted file.

    - Tables → RENAME … _obsolete<ts>.
    - Other objects → DROP statement.
    """

    db_name = change.abs_path.parent.name
    obj_stem = change.abs_path.stem
    suffix = change.abs_path.suffix.lower()

    if _is_table_file(change.abs_path):
        # read old version to get the table name
        old_ddl_text = repo.get_file_content_at_commit(
            baseline_commit, change.rel_path,
        )

        table_name = obj_stem
        database_name: str | None = db_name
        if old_ddl_text:
            parsed = table_parser.parse_table_ddl(old_ddl_text)
            if parsed:
                table_name = parsed.table_name
                database_name = parsed.database_name or db_name

        script = change_script_gen.generate_table_obsolete_script(
            database_name, table_name, ts=ts,
        )
        drop_file = f"{obj_stem}_obsolete.sql"
        target = pkg_root_dir / steps_subdir / PKG_STP_DROPS / db_name / drop_file
        _ensure_parent(target, dirs_created)
        target.write_text(script, encoding="utf-8")
    else:
        # non-table object — generate DROP
        obj_type = fsystem.EXT_TO_TYPE.get(suffix)
        if obj_type is None:
            logger.warning(f"cannot determine object type for: {change.rel_path}")
            return
        script = change_script_gen.generate_drop_script(
            db_name, obj_stem, obj_type,
        )
        drop_file = f"{obj_stem}_drop.sql"
        target = pkg_root_dir / steps_subdir / PKG_STP_DROPS / db_name / drop_file
        _ensure_parent(target, dirs_created)
        target.write_text(script, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_baseline_commit(
    repo: git.Repo,
    diff_against: str,
    diff_ident: str,
) -> str:
    """Resolve the baseline commit SHA so we can retrieve old file versions."""

    if diff_against == "commit":
        return diff_ident
    elif diff_against == "branch":
        feature_branch = repo.get_current_branch()
        return repo.get_merge_base(diff_ident, feature_branch)
    else:
        raise exc.DOperationsError(
            f"diff_against: should be one of ('commit','branch'): {diff_against}"
        )


def _ensure_parent(path: Path, dirs_created: set[Path]):
    """Create parent directories if needed, tracking which ones were created."""
    parent = path.parent
    if parent not in dirs_created:
        parent.mkdir(exist_ok=True, parents=True)
        dirs_created.add(parent)


def _rel_path_in_package(
    *,
    repo_dir_absp: Path,
    src_file_absp: Path,
    metadata_dir_absp: Path,
    steps_subdir: Path,
    subdir_list: Iterable[str | Path] | None = None,
) -> Path:
    # check if the path is in metadata directory
    # if it is, prepare it as the package using enhanced step folders
    if src_file_absp.is_relative_to(metadata_dir_absp):
        step_name = _EXT_TO_PKG_STEP.get(
            src_file_absp.suffix.lower(),
            PKG_STP_GENERIC_SQL,
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
