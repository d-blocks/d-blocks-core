"""
Configuration updater for d-blocks test repository.

This script updates the dblocks.toml file in the test workspace with
credentials from environment variables, making it cross-platform compatible.
"""
import os
import re
import sys
from pathlib import Path
from loguru import logger


def update_dblocks_config(workspace_path: str | Path) -> bool:
    """
    Update dblocks.toml file with test credentials from environment variables.
    
    Args:
        workspace_path: Path to the test workspace directory
        
    Returns:
        bool: True if configuration was updated successfully, False otherwise
    """
    workspace_path = Path(workspace_path)
    config_file = workspace_path / "dblocks.toml"
    
    # Get credentials from environment variables
    test_host = os.getenv("TEST_DB_HOST")
    test_user = os.getenv("TEST_DB_USER")
    
    if not test_host or not test_user:
        logger.error("Missing required environment variables: TEST_DB_HOST and/or TEST_DB_USER")
        return False
    
    if not config_file.exists():
        logger.warning(f"⚠️ dblocks.toml not found at {config_file}")
        return False
    
    try:
        logger.info("📝 Updating dblocks.toml with test credentials...")
        
        # Read the current configuration
        content = config_file.read_text(encoding="utf-8")
        original_content = content
        
        # Replace host values using regex
        # Matches: host = "anything" or host = 'anything'
        host_pattern = r'host\s*=\s*["\'][^"\']*["\']'
        content = re.sub(host_pattern, f'host = "{test_host}"', content)
        
        # Replace username values using regex  
        # Matches: username = "anything" or username = 'anything'
        username_pattern = r'username\s*=\s*["\'][^"\']*["\']'
        content = re.sub(username_pattern, f'username = "{test_user}"', content)
        
        # Write the updated configuration back
        config_file.write_text(content, encoding="utf-8")
        
        if content != original_content:
            logger.info("✅ Successfully updated dblocks.toml configuration")
            
            # Show what was changed
            logger.info("📄 Configuration preview:")
            for line_num, line in enumerate(content.split('\n'), 1):
                if 'host =' in line or 'username =' in line:
                    logger.info(f"  Line {line_num}: {line.strip()}")
        else:
            logger.info("ℹ️ No changes needed in dblocks.toml")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to update dblocks.toml: {e}")
        return False


def setup_environment_variables() -> bool:
    """
    Set up d-blocks environment variables for password configuration.
    
    Returns:
        bool: True if environment variables were set successfully
    """
    test_password = os.getenv("TEST_DB_PASSWORD")
    
    if not test_password:
        logger.error("Missing required environment variable: TEST_DB_PASSWORD")
        return False
    
    try:
        # Set d-blocks environment variables for DEV and PROD passwords
        os.environ["DBLOCKS_ENVIRONMENTS__DEV__PASSWORD"] = test_password
        os.environ["DBLOCKS_ENVIRONMENTS__PROD__PASSWORD"] = test_password
        
        logger.info("✅ Set d-blocks environment variables:")
        logger.info("  - DBLOCKS_ENVIRONMENTS__DEV__PASSWORD")
        logger.info("  - DBLOCKS_ENVIRONMENTS__PROD__PASSWORD")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to set environment variables: {e}")
        return False


def main():
    """Main function to configure test environment."""
    logger.info("🔧 Configuring d-blocks test environment...")
    
    # Get workspace path from command line argument or default
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "test-workspace"
    
    logger.info(f"📁 Workspace path: {workspace_path}")
    
    # Update configuration file
    config_success = update_dblocks_config(workspace_path)
    
    # Set up environment variables
    env_success = setup_environment_variables()
    
    if config_success and env_success:
        logger.info("🎉 Test environment configuration completed successfully!")
        return 0
    else:
        logger.error("❌ Test environment configuration failed!")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
