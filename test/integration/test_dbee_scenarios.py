"""
Integration tests for dbee utility command-line scenarios.

These tests verify that the dbee utility works correctly with real Teradata
code projects. They test the complete workflow from Git repository to database
deployment and back.

Test execution order is important as some tests depend on the state created
by previous tests. The first test validates database connectivity before
proceeding with utility scenarios.
"""
import pytest
import subprocess
import os
from pathlib import Path
from loguru import logger
import sqlalchemy as sa
from sqlalchemy.engine import URL


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


class TestDBeeUtilityScenarios:
    """Test class for dbee utility scenarios in execution order."""
    
    @pytest.mark.integration
    @pytest.mark.requires_db
    @pytest.mark.slow
    def test_00_database_connectivity(self, db_connection_config):
        """Test 0: Verify database connectivity before running utility scenarios."""
        logger.info("🔌 Testing database connectivity as prerequisite for utility scenarios")
        logger.info(f"Testing connection to {db_connection_config['host']}")
        
        # Create Teradata connection URL
        connection_url = URL.create(
            drivername="teradatasql",
            username=db_connection_config['username'],
            password=db_connection_config['password'],
            host=db_connection_config['host'],
            query={
                "tmode": "TERA"
            }
        )
        
        # Create engine and test connection
        engine = sa.create_engine(connection_url)
        
        try:
            logger.info("Attempting to connect to Teradata database...")
            
            # Test connection with a simple query
            with engine.connect() as connection:
                result = connection.execute(sa.text("SELECT CURRENT_DATE as test_date"))
                test_date = result.fetchone()[0]
                logger.info(f"✅ Successfully connected! Current date from Teradata: {test_date}")
                
                # Verify we can access the target database
                target_db = db_connection_config['database']
                if target_db:
                    try:
                        connection.execute(sa.text(f"DATABASE {target_db}"))
                        logger.info(f"✅ Successfully switched to target database: {target_db}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not switch to target database '{target_db}': {e}")
            
            logger.info("🎉 Database connectivity verified - ready for utility scenarios!")
            
        except Exception as e:
            logger.error(f"❌ Database connectivity failed: {e}")
            logger.error("⚠️ Skipping utility scenarios due to database connectivity issues")
            raise
        finally:
            # Clean up
            engine.dispose()
    
    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.slow
    def test_01_dbee_help(self, test_workspace, dbee_command):
        """Test scenario 1: dbee --help from root of test repository."""
        logger.info("🚀 Testing dbee --help command")
        
        # Change to test workspace directory
        original_cwd = os.getcwd()
        try:
            os.chdir(test_workspace)
            logger.info(f"Working directory: {os.getcwd()}")
            
            # Execute dbee --help
            cmd = dbee_command + ["--help"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
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
            os.chdir(original_cwd)

    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.requires_db
    @pytest.mark.slow
    def test_02_dbee_cfg_check(self, test_workspace, dbee_command):
        """Test scenario 2: dbee cfg-check from root of test repository with configured credentials."""
        logger.info("🔧 Testing dbee cfg-check command with configured test environment")
        
        # Change to test workspace directory
        original_cwd = os.getcwd()
        try:
            os.chdir(test_workspace)
            logger.info(f"Working directory: {os.getcwd()}")
            
            # Check if dblocks.toml exists in the workspace
            config_file = Path("dblocks.toml")
            if config_file.exists():
                logger.info("✅ Found dblocks.toml configuration file")
            else:
                pytest.skip("dblocks.toml not found in test workspace - configuration required for cfg-check")
            
            # Execute dbee cfg-check
            cmd = dbee_command + ["cfg-check"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Longer timeout as cfg-check might need to validate database connections
            )
            
            # Log the output for debugging
            if result.stdout:
                logger.info("cfg-check stdout:")
                for line in result.stdout.split('\n')[:10]:  # First 10 lines
                    if line.strip():
                        logger.info(f"  {line}")
            
            if result.stderr:
                logger.info("cfg-check stderr:")
                for line in result.stderr.split('\n')[:10]:  # First 10 lines
                    if line.strip():
                        logger.info(f"  {line}")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee cfg-check failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Verify cfg-check output indicates successful configuration validation
            output_text = result.stdout.lower() + result.stderr.lower()
            
            # The cfg-check command should indicate success
            success_indicators = ["cfg_check - ok"]
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
            os.chdir(original_cwd)

    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.slow
    def test_03_dbee_env_list(self, test_workspace, dbee_command):
        """Test scenario 3: dbee env-list to verify configured environments are listed correctly."""
        logger.info("📋 Testing dbee env-list command to verify environment configuration")
        
        # Get expected values from environment variables
        expected_host = os.getenv("TEST_DB_HOST")
        expected_user = os.getenv("TEST_DB_USER")
        
        if not expected_host or not expected_user:
            pytest.skip("TEST_DB_HOST and TEST_DB_USER environment variables required for this test")
        
        logger.info(f"Expected host: {expected_host}")
        logger.info(f"Expected user: {expected_user}")
        
        # Change to test workspace directory
        original_cwd = os.getcwd()
        try:
            os.chdir(test_workspace)
            logger.info(f"Working directory: {os.getcwd()}")
            
            # Check if dblocks.toml exists in the workspace
            config_file = Path("dblocks.toml")
            if config_file.exists():
                logger.info("✅ Found dblocks.toml configuration file")
            else:
                pytest.skip("dblocks.toml not found in test workspace - configuration required for env-list")
            
            # Execute dbee env-list
            cmd = dbee_command + ["env-list"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Log the output for debugging
            if result.stdout:
                logger.info("env-list stdout:")
                for line in result.stdout.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            
            if result.stderr:
                logger.info("env-list stderr:")
                for line in result.stderr.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            
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
                if 'prod' in line_stripped and expected_host in line_stripped and expected_user in line_stripped:
                    prod_pattern_found = True
                    logger.info(f"✅ Found prod environment line: {line_stripped}")
                    
                # Check if line contains dev, expected_host, and expected_user  
                if 'dev' in line_stripped and expected_host in line_stripped and expected_user in line_stripped:
                    dev_pattern_found = True
                    logger.info(f"✅ Found dev environment line: {line_stripped}")
            
            # Verify both patterns were found
            assert prod_pattern_found, f"Expected to find line with pattern 'prod + {expected_host} + {expected_user}' in output"
            assert dev_pattern_found, f"Expected to find line with pattern 'dev + {expected_host} + {expected_user}' in output"
            
            # Additional verification: check for table headers
            output_lower = output.lower()
            assert "environment" in output_lower, "Output should contain environment column header"
            assert "host" in output_lower, "Output should contain host column header"
            assert "user" in output_lower, "Output should contain user column header"
            
            logger.info("✅ dbee env-list executed successfully - both environments found with correct configuration!")
            logger.info(f"  - Production environment pattern found: {prod_pattern_found}")
            logger.info(f"  - Development environment pattern found: {dev_pattern_found}")
            logger.info(f"  - Host value verified: {expected_host}")
            logger.info(f"  - User value verified: {expected_user}")
            
        finally:
            # Always restore original working directory
            os.chdir(original_cwd)

    @pytest.mark.integration
    @pytest.mark.scenarios
    @pytest.mark.requires_db
    @pytest.mark.slow
    def test_04_dbee_env_test_connection(self, test_workspace, dbee_command):
        """Test scenario 4: dbee env-test-connection dev to verify database connectivity."""
        logger.info("🔌 Testing dbee env-test-connection dev command to verify database connectivity")
        
        # Change to test workspace directory
        original_cwd = os.getcwd()
        try:
            os.chdir(test_workspace)
            logger.info(f"Working directory: {os.getcwd()}")
            
            # Check if dblocks.toml exists in the workspace
            config_file = Path("dblocks.toml")
            if config_file.exists():
                logger.info("✅ Found dblocks.toml configuration file")
            else:
                pytest.skip("dblocks.toml not found in test workspace - configuration required for env-test-connection")
            
            # Execute dbee env-test-connection dev
            cmd = dbee_command + ["env-test-connection", "dev"]
            logger.info(f"Executing: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Longer timeout as database connection might take time
            )
            
            # Log the output for debugging
            if result.stdout:
                logger.info("env-test-connection stdout:")
                for line in result.stdout.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            
            if result.stderr:
                logger.info("env-test-connection stderr:")
                for line in result.stderr.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            
            # Verify the command succeeded
            assert result.returncode == 0, f"dbee env-test-connection dev failed with return code {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
            
            # Verify the output contains expected success message
            output_text = result.stdout + result.stderr  # Check both stdout and stderr
            
            # Check for the specific success message
            success_message = "test_connection - success"
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
            os.chdir(original_cwd)
    