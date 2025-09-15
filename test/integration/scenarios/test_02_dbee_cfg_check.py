"""
Test scenario 02: dbee cfg-check command.

This test verifies that the dbee cfg-check command works correctly with
the configured test environment credentials.
"""
import pytest
import subprocess
from pathlib import Path
from loguru import logger

from .base import BaseScenarioTest, test_workspace, dbee_command


class TestDbeeCfgCheck(BaseScenarioTest):
    """Test dbee cfg-check command functionality."""
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.order(2)
    def test_dbee_cfg_check(self, test_workspace, dbee_command):
        """Test scenario 2: dbee cfg-check from root of test repository with configured credentials."""
        logger.info("🔧 Testing dbee cfg-check command with configured test environment")
        
        # Verify workspace configuration
        if not self.verify_workspace_config(test_workspace):
            pytest.skip("Test workspace not properly configured")
        
        # Change to test workspace directory
        original_cwd = self.change_to_workspace(test_workspace)
        
        try:
            # Execute dbee cfg-check
            cmd = dbee_command + ["cfg-check"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Longer timeout as cfg-check might need to validate database connections
            )
            
            # Log command output
            self.log_command_output(result, "dbee cfg-check")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee cfg-check failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Verify cfg-check output indicates successful configuration validation
            output_text = result.stdout.lower() + result.stderr.lower()
            
            # The cfg-check command should indicate success
            success_indicators = ["ok", "success", "valid", "configuration loaded"]
            has_success_indicator = any(indicator in output_text for indicator in success_indicators)
            
            # Should not contain common error indicators
            error_indicators = ["error"]
            has_error_indicator = any(indicator in output_text for indicator in error_indicators)
            
            assert has_success_indicator or not has_error_indicator, (
                f"cfg-check output doesn't indicate successful configuration validation. "
                f"Output: {result.stdout[:500]}..."
            )
            
            logger.info("✅ dbee cfg-check executed successfully - configuration validated!")
            
        finally:
            # Always restore original working directory
            self.restore_working_directory(original_cwd)
