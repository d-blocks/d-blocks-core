"""
Integration tests that connect to real infrastructure.

These tests require actual database credentials and are typically
run only in CI/CD environments with proper secrets configured.
"""
import pytest
from loguru import logger

from dblocks_core.config import config
from dblocks_core.model.config_model import WriterParameters


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.slow
def test_real_database_connection(db_connection_config):
    """Test connection to real Teradata database using provided credentials."""
    logger.info(f"Testing connection to {db_connection_config['host']}")
    
    from dblocks_core.dbi import create_engine, tera_dbi
    from dblocks_core.model.config_model import EnvironParameters
    from dblocks_core.config import config
    
    # Create environment parameters using the test credentials
    env_params = EnvironParameters(
        host=db_connection_config['host'],
        username=db_connection_config['username'],
        password=config.SecretPassword(db_connection_config['password']),
        connection_parameters={"tmode": "TERA", "logmech": "LDAP"},  # Default Teradata parameters
    )
    
    # Create a minimal config for testing
    test_cfg = config.Config(
        config_version="1.0.0",
        environments={}  # We'll use the engine directly
    )
    
    try:
        # Create SQLAlchemy engine for Teradata
        from dblocks_core.dbi import create_connect_string, TERADATA_DIALECT
        import sqlalchemy as sa
        
        connect_string = create_connect_string(env_params, TERADATA_DIALECT)
        engine = sa.create_engine(connect_string, pool_size=1, max_overflow=0)
        
        # Create TeraDBI instance
        dbi = tera_dbi.TeraDBI(engine, cfg=test_cfg)
        
        # Test the connection
        logger.info("Attempting to connect to Teradata database...")
        dbi.test_connection()
        logger.info("✅ Successfully connected to Teradata database!")
        
        # Test a simple query to verify we can execute commands
        logger.info("Testing basic database query...")
        databases = dbi.get_databases()
        logger.info(f"✅ Found {len(databases)} databases in the system")
        
        # Test that we can see the specific database we're connecting to
        target_db = db_connection_config['database']
        db_names = [db.database_name for db in databases]
        if target_db in db_names:
            logger.info(f"✅ Target database '{target_db}' found in database list")
        else:
            logger.warning(f"⚠️ Target database '{target_db}' not found in accessible databases")
            logger.info(f"Available databases: {db_names[:10]}...")  # Show first 10
        
        # Clean up
        dbi.dispose()
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to Teradata database: {e}")
        raise
    
    logger.info("🎉 Real database connection test completed successfully!")

