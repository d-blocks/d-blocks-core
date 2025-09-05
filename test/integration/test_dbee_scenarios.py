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
    