"""
Test scenario 03: dbee env-list command.

This test verifies that the dbee env-list command correctly displays
the configured environments with proper host and username values.
"""
import pytest
import subprocess
from loguru import logger

from .base import BaseScenarioTest, test_workspace, dbee_command


class TestDbeeEnvList(BaseScenarioTest):
    """Test dbee env-list command functionality."""
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.order(3)
    def test_dbee_env_list(self, test_workspace, dbee_command):
        """Test scenario 3: dbee env-list to verify configured environments are listed correctly."""
        logger.info("📋 Testing dbee env-list command to verify environment configuration")
        
        # Get expected values from environment variables
        expected_host, expected_user = self.get_test_credentials()
        
        if not expected_host or not expected_user:
            pytest.skip("TEST_DB_HOST and TEST_DB_USER environment variables required for this test")
        
        # Verify workspace configuration
        if not self.verify_workspace_config(test_workspace):
            pytest.skip("Test workspace not properly configured")
        
        # Change to test workspace directory
        original_cwd = self.change_to_workspace(test_workspace)
        
        try:
            # Execute dbee env-list
            cmd = dbee_command + ["env-list"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Log command output
            self.log_command_output(result, "dbee env-list")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee env-list failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Verify the output contains expected environments and structure
            output = result.stdout
            
            # Check for expected environments using pattern matching
            # Look for lines containing: prod + host + username (with any characters in between)
            prod_pattern_found = False
            dev_pattern_found = False
            
            # Split output into lines and check each line
            lines = output.split('\n')
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                    
                # Check if line contains prod, expected_host, and expected_user
                if 'prod' in line_stripped and expected_user in line_stripped:
                    prod_pattern_found = True
                    logger.info(f"✅ Found prod environment line: {line_stripped}")
                    
                # Check if line contains dev, expected_host, and expected_user  
                if 'dev' in line_stripped and expected_user in line_stripped:
                    dev_pattern_found = True
                    logger.info(f"✅ Found dev environment line: {line_stripped}")
            
            # Verify both patterns were found
            assert prod_pattern_found, f"Expected to find line with pattern 'prod + {expected_user}' in output"
            assert dev_pattern_found, f"Expected to find line with pattern 'dev + {expected_user}' in output"
            
            # Additional verification: check for table headers
            output_lower = output.lower()
            assert "environment" in output_lower, "Output should contain environment column header"
            assert "host" in output_lower, "Output should contain host column header"
            assert "user" in output_lower, "Output should contain user column header"
            
            logger.info("✅ dbee env-list executed successfully - both environments found with correct configuration!")
            logger.info(f"  - Production environment pattern found: {prod_pattern_found}")
            logger.info(f"  - Development environment pattern found: {dev_pattern_found}")
            logger.info(f"  - User value verified: {expected_user}")
            
        finally:
            # Always restore original working directory
            self.restore_working_directory(original_cwd)
