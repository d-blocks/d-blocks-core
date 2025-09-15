"""
Test scenario 05: dbee cfg-print command.

This test verifies that the dbee cfg-print command correctly displays
the configuration including environment names, database hosts, and usernames.
"""
import pytest
import subprocess
import json
from loguru import logger

from .base import BaseScenarioTest, test_workspace, dbee_command


class TestDbeeCfgPrint(BaseScenarioTest):
    """Test dbee cfg-print command functionality."""
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.slow
    @pytest.mark.order(5)
    def test_dbee_cfg_print(self, test_workspace, dbee_command):
        """Test scenario 5: dbee cfg-print to verify configuration output contains environments and credentials."""
        logger.info("📄 Testing dbee cfg-print command to verify configuration display")
        
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
            # Execute dbee cfg-print
            cmd = dbee_command + ["cfg-print"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Log command output
            self.log_command_output(result, "dbee cfg-print")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee cfg-print failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Get the output (cfg-print outputs JSON format)
            output = result.stdout
            assert output.strip(), "cfg-print should produce output"
            
            # Try to parse as JSON (cfg-print should output JSON)
            try:
                config_data = json.loads(output)
                logger.info("✅ Successfully parsed cfg-print output as JSON")
            except json.JSONDecodeError as e:
                # If not JSON, treat as plain text and check for patterns
                logger.warning(f"Output is not valid JSON: {e}")
                logger.info("Treating output as plain text for pattern matching")
                config_data = None
            
            # Check for required environment names
            if config_data and isinstance(config_data, dict):
                # JSON format - check for environments section
                environments = config_data.get("environments", {})
                assert "prod" in environments, "Configuration should contain 'prod' environment"
                assert "dev1" in environments, "Configuration should contain 'dev1' environment"
                
                # Check for host and username in each environment
                for env_name in ["prod", "dev"]:
                    env_config = environments[env_name]
                    
                    # Check for host
                    assert "host" in env_config, f"Environment '{env_name}' should have host configuration"
                    host_value = env_config["host"]
                    assert host_value == expected_host, f"Environment '{env_name}' host should be '{expected_host}', got '{host_value}'"
                    
                    # Check for username
                    assert "username" in env_config, f"Environment '{env_name}' should have username configuration"
                    username_value = env_config["username"]
                    assert username_value == expected_user, f"Environment '{env_name}' username should be '{expected_user}', got '{username_value}'"
                    
                    logger.info(f"✅ Environment '{env_name}': host='{host_value}', username='{username_value}'")
                
            else:
                # Plain text format - check for patterns in the output
                output_lower = output.lower()
                
                # Check for environment names
                assert "prod" in output_lower, "Output should contain 'prod' environment name"
                assert "dev" in output_lower, "Output should contain 'dev' environment name"
                
                # Check for host and username values
                assert expected_host.lower() in output_lower, f"Output should contain host value '{expected_host}'"
                assert expected_user.lower() in output_lower, f"Output should contain username value '{expected_user}'"
                
                logger.info("✅ Found environment names and credentials in plain text output")
            
            # Additional verification: passwords should be redacted/censored
            output_lower = output.lower()
            
            # Common password indicators that should NOT appear in clear text
            sensitive_indicators = ["password", "secret", "token"]
            clear_password_patterns = ["test_password", "admin123", "password123"]
            
            for pattern in clear_password_patterns:
                assert pattern not in output_lower, f"Clear text password pattern '{pattern}' should not appear in cfg-print output"
            
            # Should contain redacted indicators
            redaction_indicators = ["<redacted>", "***", "hidden", "censored"]
            has_redaction = any(indicator in output_lower for indicator in redaction_indicators)
            
            if any(indicator in output_lower for indicator in sensitive_indicators):
                assert has_redaction, "Output contains password references but no redaction indicators found"
                logger.info("✅ Passwords appear to be properly redacted in output")
            
            logger.info("✅ dbee cfg-print executed successfully - configuration displayed correctly!")
            logger.info(f"  - Environment 'prod' found: {'prod' in output_lower}")
            logger.info(f"  - Environment 'dev' found: {'dev' in output_lower}")
            logger.info(f"  - Host value found: {expected_host.lower() in output_lower}")
            logger.info(f"  - Username value found: {expected_user.lower() in output_lower}")
            logger.info(f"  - Passwords redacted: {has_redaction if any(indicator in output_lower for indicator in sensitive_indicators) else 'N/A'}")
            
        finally:
            # Always restore original working directory
            self.restore_working_directory(original_cwd)
