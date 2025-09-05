"""
Integration tests for dbee utility command-line scenarios.

These tests verify that the dbee utility works correctly with real Teradata
code projects. They test the complete workflow from Git repository to database
deployment and back.

Test execution order is important as some tests depend on the state created
by previous tests.
"""
import pytest
import subprocess
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


class TestDBeeUtilityScenarios:
    """Test class for dbee utility scenarios in execution order."""
    
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
