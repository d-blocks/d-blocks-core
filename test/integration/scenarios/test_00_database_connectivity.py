"""
Test scenario 00: Database connectivity verification.

This test verifies that the database connection can be established before
running any other utility scenarios. It serves as a prerequisite check.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL
from loguru import logger

from .base import BaseScenarioTest


class TestDatabaseConnectivity(BaseScenarioTest):
    """Test database connectivity as a prerequisite for utility scenarios."""
    
    @pytest.mark.integration
    @pytest.mark.requires_db
    @pytest.mark.order(0)  # This should run first
    def test_database_connectivity(self, db_connection_config):
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
