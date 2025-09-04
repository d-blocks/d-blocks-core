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
    """Test connection to real Teradata database using SQLAlchemy directly."""
    logger.info(f"Testing connection to {db_connection_config['host']}")
    
    import sqlalchemy as sa
    from sqlalchemy.engine import URL
    
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
        
        logger.info("🎉 Teradata connection test completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to Teradata database: {e}")
        raise
    finally:
        # Clean up
        engine.dispose()

