"""
Test scenario 04: dbee env-test-connection command.

This test verifies that the dbee env-test-connection dev command successfully
connects to the dev environment and returns a success message.
"""
import pytest
import subprocess
from loguru import logger

from .base import BaseScenarioTest, test_workspace, dbee_command


class TestDbeeEnvTestConnection(BaseScenarioTest):
    """Test dbee env-test-connection command functionality."""
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.requires_db
    @pytest.mark.order(4)
    def test_dbee_env_test_connection(self, test_workspace, dbee_command):
        """Test scenario 4: dbee env-test-connection dev to verify database connectivity."""
        logger.info("🔌 Testing dbee env-test-connection dev command to verify database connectivity")
        
        # Verify workspace configuration
        if not self.verify_workspace_config(test_workspace):
            pytest.skip("Test workspace not properly configured")
        
        # Change to test workspace directory
        original_cwd = self.change_to_workspace(test_workspace)
        
        try:
            # Execute dbee env-test-connection dev
            cmd = dbee_command + ["env-test-connection", "dev"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Longer timeout as database connection might take time
            )
            
            # Log command output
            self.log_command_output(result, "dbee env-test-connection")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee env-test-connection dev failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Verify the output contains expected success message
            output_text = result.stdout + result.stderr  # Check both stdout and stderr
            
            # Check for the specific success message
            success_message = "success"
            assert success_message in output_text, (
                f"Expected success message '{success_message}' not found in output. "
                f"Full output: {output_text}"
            )
            
            # Additional checks for connection-related content
            output_lower = output_text.lower()
            
            # Should not contain common error indicators
            error_indicators = ["failed", "error", "exception", "traceback", "connection refused", "timeout"]
            found_errors = [indicator for indicator in error_indicators if indicator in output_lower]
            
            assert not found_errors, f"Found error indicators in output: {found_errors}. Full output: {output_text}"
            
            logger.info("✅ dbee env-test-connection dev executed successfully - database connection verified!")
            logger.info(f"  - Success message found: '{success_message}'")
            logger.info(f"  - No error indicators detected")
            
        finally:
            # Always restore original working directory
            self.restore_working_directory(original_cwd)
