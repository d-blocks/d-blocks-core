from datetime import datetime
from typing import NamedTuple

from rich.console import Console
from rich.table import Table

from dblocks_core.config.config import logger
from dblocks_core.git import git


class BranchInfo(NamedTuple):
    """Information about a Git branch."""
    name: str
    last_commit_sha: str
    last_commit_author: str
    last_commit_date: datetime
    creation_date: datetime | None
    is_merged: bool
    merged_to_branch: str | None
    merge_date: datetime | None


def run_branch_status(repo: git.Repo, include_remote: bool = True) -> None:
    """Execute the branch-status functionality.
    
    Args:
        repo (git.Repo): The Git repository to analyze.
        include_remote (bool): Whether to include remote branches. 
                              True = only remote branches, False = only local branches.
    """
    console = Console()
    
    try:
        # Get branches based on the option
        mode = "remote" if include_remote else "local"
        branches = repo.get_all_branches(mode=mode)
        branch_type = "remote" if include_remote else "local"
        logger.info(f"Found {len(branches)} {branch_type} branches")
        
        if not branches:
            console.print(f"No {branch_type} branches found in repository.", style="yellow")
            return
        
        # Collect branch information
        branch_infos = []
        for branch in branches:
            try:
                branch_info = _get_branch_info(repo, branch)
                branch_infos.append(branch_info)
            except Exception as err:
                logger.warning(f"Failed to get info for branch '{branch}': {err}")
                continue
        
        if not branch_infos:
            console.print("Could not retrieve information for any branches.", style="red")
            return
        
        # Sort by last commit date (most recent first)
        branch_infos.sort(key=lambda x: x.last_commit_date, reverse=True)
        
        # Display results
        _display_branch_status(console, branch_infos, include_remote)
        
    except Exception as err:
        logger.error(f"Branch status analysis failed: {err}")
        console.print(f"Error analyzing repository: {err}", style="bold red")


def _get_branch_info(repo: git.Repo, branch: str) -> BranchInfo:
    """Get comprehensive information about a specific branch.
    
    Args:
        repo (git.Repo): The Git repository.
        branch (str): The branch name.
        
    Returns:
        BranchInfo: Complete information about the branch.
    """
    # Get last commit information
    commit_sha, author, commit_date = repo.get_last_commit_info(branch)
    
    # Get branch creation date
    creation_date = repo.get_branch_creation_date(branch)
    
    # Check if branch is merged
    is_merged, merged_to, merge_date = repo.is_branch_merged(branch)
    
    return BranchInfo(
        name=branch,
        last_commit_sha=commit_sha[:8],  # Short SHA for display
        last_commit_author=author,
        last_commit_date=commit_date,
        creation_date=creation_date,
        is_merged=is_merged,
        merged_to_branch=merged_to,
        merge_date=merge_date
    )


def _display_branch_status(console: Console, branch_infos: list[BranchInfo], include_remote: bool = True) -> None:
    """Display branch status information in a formatted table.
    
    Args:
        console (Console): Rich console for output.
        branch_infos (list[BranchInfo]): List of branch information.
        include_remote (bool): Whether showing remote branches (True) or local branches (False).
    """
    branch_scope = "Remote" if include_remote else "Local"
    console.print(f"Git Branch Status Analysis ({branch_scope} Branches)", style="bold cyan")
    console.print()
    
    # Create table
    table = Table(title=f"Repository Branches ({branch_scope})")
    table.add_column("Branch Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="blue", no_wrap=True)
    table.add_column("Last Commit", style="green", no_wrap=True)
    table.add_column("Author", style="blue", no_wrap=True)
    table.add_column("Creation Date", style="yellow", no_wrap=True)
    table.add_column("Last Commit Date", style="magenta", no_wrap=True)
    table.add_column("Merged Status", style="yellow", no_wrap=True)
    table.add_column("Merge Details", style="dim", no_wrap=False)
    
    current_branch = None
    try:
        current_branch = branch_infos[0].name if branch_infos else None
        # Try to get actual current branch from repo
        repo = git.repo_factory(raise_on_error=False)
        if repo:
            current_branch = repo.get_current_branch()
    except Exception:
        pass
    
    for branch_info in branch_infos:
        # Determine branch type and format name
        branch_name = branch_info.name
        is_remote = "/" in branch_name and not branch_name.startswith("feature/") and not branch_name.startswith("bugfix/")
        branch_type = "Remote" if is_remote else "Local"
        
        # Mark current branch (only for local branches)
        if not is_remote and branch_name == current_branch:
            branch_name = f"* {branch_name}"
        
        # Format commit date
        commit_date_str = branch_info.last_commit_date.strftime("%Y-%m-%d %H:%M")
        
        # Format creation date
        creation_date_str = "Unknown"
        if branch_info.creation_date:
            creation_date_str = branch_info.creation_date.strftime("%Y-%m-%d")
        
        # Format merge status
        if branch_info.is_merged:
            merge_status = "✓ Merged"
            merge_details = f"→ {branch_info.merged_to_branch}"
            if branch_info.merge_date:
                merge_details += f" ({branch_info.merge_date.strftime('%Y-%m-%d')})"
        else:
            merge_status = "○ Active"
            merge_details = "Not merged"
        
        table.add_row(
            branch_name,
            branch_type,
            branch_info.last_commit_sha,
            branch_info.last_commit_author,
            creation_date_str,
            commit_date_str,
            merge_status,
            merge_details
        )
    
    console.print(table)
    console.print()
    
    # Summary statistics
    total_branches = len(branch_infos)
    merged_branches = sum(1 for bi in branch_infos if bi.is_merged)
    active_branches = total_branches - merged_branches
    
    console.print(f"Summary: {total_branches} total branches, {active_branches} active, {merged_branches} merged", 
                  style="bold")
    
    if merged_branches > 0:
        console.print(f"💡 Consider cleaning up {merged_branches} merged branch(es)", style="dim yellow")
