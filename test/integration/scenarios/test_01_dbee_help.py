"""
Test scenario 01: dbee --help command.

This test verifies that the dbee --help command works correctly from the
root of the test repository.
"""
import pytest
import subprocess
from loguru import logger

from .base import BaseScenarioTest, test_workspace, dbee_command


class TestDbeeHelp(BaseScenarioTest):
    """Test dbee --help command functionality."""
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.order(1)
    def test_dbee_help(self, test_workspace, dbee_command):
        """Test scenario 1: dbee --help from root of test repository."""
        logger.info("🚀 Testing dbee --help command")
        
        # Verify workspace configuration
        if not self.verify_workspace_config(test_workspace):
            pytest.skip("Test workspace not properly configured")
        
        # Change to test workspace directory
        original_cwd = self.change_to_workspace(test_workspace)
        
        try:
            # Execute dbee --help
            cmd = dbee_command + ["--help"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Log command output
            self.log_command_output(result, "dbee --help")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee --help failed with return code {result.returncode}\nStderr: {result.stderr}"
            
            # Verify help output contains expected content
            help_output = result.stdout
            assert "Usage:" in help_output.lower() or "Usage:" in help_output, "Help output should contain usage information"
            assert "dbee" in help_output or "d-bee" in help_output, "Help output should mention the command name"
            
            logger.info("✅ dbee --help executed successfully")
            logger.info(f"Help output length: {len(help_output)} characters")
            
            # Log first few lines of help for debugging
            help_lines = help_output.split('\n')[:5]
            for i, line in enumerate(help_lines):
                if line.strip():
                    logger.info(f"Help line {i+1}: {line}")
            
        finally:
            # Always restore original working directory
            self.restore_working_directory(original_cwd)
