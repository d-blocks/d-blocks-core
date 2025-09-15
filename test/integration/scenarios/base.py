"""
Base class and shared utilities for dbee integration test scenarios.

This module provides common fixtures, utilities, and base classes that are shared
across all dbee integration test scenarios.
"""
import pytest
import os
from pathlib import Path
from loguru import logger


# Test workspace directory where the test repository is cloned
TEST_WORKSPACE = Path("test-workspace")


@pytest.fixture(scope="session")
def test_workspace():
    """Ensure test workspace exists and return its path."""
    if not TEST_WORKSPACE.exists():
        pytest.skip("Test workspace not found - this test requires the d-blocks-test repository to be cloned")
    return TEST_WORKSPACE


@pytest.fixture(scope="session")
def dbee_command():
    """Get the dbee command that can be executed via poetry."""
    return ["poetry", "run", "dbee"]


class BaseScenarioTest:
    """Base class for dbee scenario tests with common utilities and setup."""
    
    def setup_method(self):
        """Setup method called before each test method."""
        logger.info(f"🚀 Starting scenario test: {self.__class__.__name__}")
    
    def teardown_method(self):
        """Teardown method called after each test method."""
        logger.info(f"✅ Completed scenario test: {self.__class__.__name__}")
    
    def verify_workspace_config(self, workspace_path: Path) -> bool:
        """
        Verify that the test workspace has the required configuration.
        
        Args:
            workspace_path: Path to the test workspace
            
        Returns:
            bool: True if workspace is properly configured
        """
        config_file = workspace_path / "dblocks.toml"
        if not config_file.exists():
            logger.warning(f"⚠️ dblocks.toml not found at {config_file}")
            return False
        
        logger.info("✅ Found dblocks.toml configuration file")
        return True
    
    def get_test_credentials(self):
        """
        Get test database credentials from environment variables.
        
        Returns:
            tuple: (host, username) or (None, None) if not available
        """
        test_host = os.getenv("TEST_DB_HOST")
        test_user = os.getenv("TEST_DB_USER")
        
        if test_host and test_user:
            logger.info(f"Using test credentials - Host: {test_host}, User: {test_user}")
            return test_host, test_user
        else:
            logger.warning("TEST_DB_HOST and/or TEST_DB_USER environment variables not set")
            return None, None
    
    def change_to_workspace(self, workspace_path: Path):
        """
        Context manager to change to workspace directory and restore afterwards.
        
        Args:
            workspace_path: Path to the test workspace
            
        Returns:
            Path: Original working directory
        """
        original_cwd = os.getcwd()
        os.chdir(workspace_path)
        logger.info(f"Changed to working directory: {os.getcwd()}")
        return original_cwd
    
    def restore_working_directory(self, original_cwd):
        """
        Restore the original working directory.
        
        Args:
            original_cwd: Original working directory path
        """
        os.chdir(original_cwd)
        logger.info(f"Restored working directory: {os.getcwd()}")
    
    def log_command_output(self, result, command_name: str):
        """
        Log the output of a command execution for debugging.
        
        Args:
            result: subprocess.CompletedProcess result
            command_name: Name of the command for logging
        """
        if result.stdout:
            logger.info(f"{command_name} stdout:")
            for line in result.stdout.split('\n'):
                if line.strip():
                    logger.info(f"  {line}")
        
        if result.stderr:
            logger.info(f"{command_name} stderr:")
            for line in result.stderr.split('\n'):
                if line.strip():
                    logger.info(f"  {line}")
