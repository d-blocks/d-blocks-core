import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from dblocks_core.git import git
from dblocks_core.script.workflow import cmd_branch_status
from dblocks_core.script.workflow.cmd_branch_status import BranchInfo


class TestCmdBranchStatus:
    """Test cases for the branch-status command functionality."""

    def test_branch_info_creation(self):
        """Test BranchInfo namedtuple creation."""
        branch_info = BranchInfo(
            name="feature/test",
            last_commit_sha="abc12345",
            last_commit_author="Test Author",
            last_commit_date=datetime(2025, 9, 17, 15, 30),
            creation_date=datetime(2025, 9, 15, 10, 0),
            is_merged=True,
            merged_to_branch="develop",
            merge_date=datetime(2025, 9, 17, 16, 0)
        )
        
        assert branch_info.name == "feature/test"
        assert branch_info.last_commit_sha == "abc12345"
        assert branch_info.last_commit_author == "Test Author"
        assert branch_info.is_merged is True
        assert branch_info.merged_to_branch == "develop"

    @patch('dblocks_core.script.workflow.cmd_branch_status._get_branch_info')
    def test_run_branch_status_no_branches(self, mock_get_branch_info):
        """Test branch-status when no branches are found."""
        mock_repo = Mock(spec=git.Repo)
        mock_repo.get_all_branches.return_value = []
        
        # Should not raise an exception
        cmd_branch_status.run_branch_status(mock_repo, include_remote=True)
        
        mock_repo.get_all_branches.assert_called_once_with(mode="remote")
        mock_get_branch_info.assert_not_called()

    @patch('dblocks_core.script.workflow.cmd_branch_status._get_branch_info')
    def test_run_branch_status_with_remote_option(self, mock_get_branch_info):
        """Test branch-status with include_remote parameter."""
        mock_repo = Mock(spec=git.Repo)
        mock_repo.get_all_branches.return_value = ["main", "origin/develop"]
        
        mock_branch_info = BranchInfo(
            name="main",
            last_commit_sha="abc12345",
            last_commit_author="Author 1",
            last_commit_date=datetime(2025, 9, 17, 16, 0),
            creation_date=datetime(2025, 9, 15, 10, 0),
            is_merged=False,
            merged_to_branch=None,
            merge_date=None
        )
        
        mock_get_branch_info.return_value = mock_branch_info
        
        # Test with remote branches included
        cmd_branch_status.run_branch_status(mock_repo, include_remote=True)
        mock_repo.get_all_branches.assert_called_with(mode="remote")
        
        # Test with remote branches excluded
        mock_repo.reset_mock()
        cmd_branch_status.run_branch_status(mock_repo, include_remote=False)
        mock_repo.get_all_branches.assert_called_with(mode="local")

    @patch('dblocks_core.script.workflow.cmd_branch_status._get_branch_info')
    def test_run_branch_status_with_branches(self, mock_get_branch_info):
        """Test branch-status with multiple branches."""
        mock_repo = Mock(spec=git.Repo)
        mock_repo.get_all_branches.return_value = ["main", "feature/test"]
        
        # Mock branch info
        mock_branch_info_1 = BranchInfo(
            name="main",
            last_commit_sha="abc12345",
            last_commit_author="Author 1",
            last_commit_date=datetime(2025, 9, 17, 16, 0),
            creation_date=datetime(2025, 9, 15, 10, 0),
            is_merged=False,
            merged_to_branch=None,
            merge_date=None
        )
        
        mock_branch_info_2 = BranchInfo(
            name="feature/test",
            last_commit_sha="def67890",
            last_commit_author="Author 2",
            last_commit_date=datetime(2025, 9, 17, 15, 0),
            creation_date=datetime(2025, 9, 16, 10, 0),
            is_merged=True,
            merged_to_branch="main",
            merge_date=datetime(2025, 9, 17, 15, 30)
        )
        
        mock_get_branch_info.side_effect = [mock_branch_info_1, mock_branch_info_2]
        
        # Should execute without error
        cmd_branch_status.run_branch_status(mock_repo, include_remote=True)
        
        mock_repo.get_all_branches.assert_called_once_with(mode="remote")
        assert mock_get_branch_info.call_count == 2

    def test_get_branch_info(self):
        """Test _get_branch_info function."""
        mock_repo = Mock(spec=git.Repo)
        mock_repo.get_last_commit_info.return_value = (
            "abc123456789",
            "Test Author",
            datetime(2025, 9, 17, 15, 30)
        )
        mock_repo.get_branch_creation_date.return_value = datetime(2025, 9, 15, 10, 0)
        mock_repo.is_branch_merged.return_value = (
            True,
            "develop",
            datetime(2025, 9, 17, 16, 0)
        )
        
        result = cmd_branch_status._get_branch_info(mock_repo, "feature/test")
        
        assert result.name == "feature/test"
        assert result.last_commit_sha == "abc12345"  # Shortened
        assert result.last_commit_author == "Test Author"
        assert result.last_commit_date == datetime(2025, 9, 17, 15, 30)
        assert result.creation_date == datetime(2025, 9, 15, 10, 0)
        assert result.is_merged is True
        assert result.merged_to_branch == "develop"
        assert result.merge_date == datetime(2025, 9, 17, 16, 0)

    @patch('dblocks_core.script.workflow.cmd_branch_status._get_branch_info')
    def test_run_branch_status_handles_exceptions(self, mock_get_branch_info):
        """Test branch-status handles exceptions gracefully."""
        mock_repo = Mock(spec=git.Repo)
        mock_repo.get_all_branches.return_value = ["main", "feature/test"]
        
        # First branch succeeds, second fails
        mock_branch_info = BranchInfo(
            name="main",
            last_commit_sha="abc12345",
            last_commit_author="Author 1",
            last_commit_date=datetime(2025, 9, 17, 16, 0),
            creation_date=datetime(2025, 9, 15, 10, 0),
            is_merged=False,
            merged_to_branch=None,
            merge_date=None
        )
        
        mock_get_branch_info.side_effect = [mock_branch_info, Exception("Git error")]
        
        # Should not raise an exception
        cmd_branch_status.run_branch_status(mock_repo, include_remote=True)
        
        mock_repo.get_all_branches.assert_called_once_with(mode="remote")
        assert mock_get_branch_info.call_count == 2

    def test_sorting_by_commit_date(self):
        """Test that branches are sorted by commit date (most recent first)."""
        branch1 = BranchInfo(
            name="old-feature",
            last_commit_sha="abc12345",
            last_commit_author="Author 1", 
            last_commit_date=datetime(2025, 9, 15, 10, 0),
            creation_date=datetime(2025, 9, 10, 10, 0),
            is_merged=False,
            merged_to_branch=None,
            merge_date=None
        )
        
        branch2 = BranchInfo(
            name="new-feature",
            last_commit_sha="def67890",
            last_commit_author="Author 2",
            last_commit_date=datetime(2025, 9, 17, 16, 0),
            creation_date=datetime(2025, 9, 16, 10, 0),
            is_merged=False,
            merged_to_branch=None,
            merge_date=None
        )
        
        branches = [branch1, branch2]
        branches.sort(key=lambda x: x.last_commit_date, reverse=True)
        
        assert branches[0].name == "new-feature"
        assert branches[1].name == "old-feature"
