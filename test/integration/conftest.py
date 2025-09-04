"""
Pytest configuration for integration tests with real infrastructure.

This module provides utilities for accessing test database credentials
from environment variables (set by GitHub Actions secrets).
"""
import os
import pytest
from typing import Optional, Dict, Any


class TestConfig:
    """Configuration for integration tests with real infrastructure."""
    
    @property
    def db_host(self) -> Optional[str]:
        return os.getenv("TEST_DB_HOST")
    
    @property
    def db_user(self) -> Optional[str]:
        return os.getenv("TEST_DB_USER")
    
    @property
    def db_password(self) -> Optional[str]:
        return os.getenv("TEST_DB_PASSWORD")
    
    @property
    def db_name(self) -> Optional[str]:
        return os.getenv("TEST_DB_NAME")
    
    @property
    def has_db_credentials(self) -> bool:
        """Check if all required database credentials are available."""
        return all([
            self.db_host,
            self.db_user, 
            self.db_password,
            self.db_name
        ])
    
    def get_connection_config(self) -> Dict[str, Any]:
        """Get database connection configuration for tests."""
        if not self.has_db_credentials:
            pytest.skip("Database credentials not available - set TEST_DB_* environment variables")
        
        return {
            "host": self.db_host,
            "username": self.db_user,
            "password": self.db_password,
            "database": self.db_name,
        }


@pytest.fixture(scope="session")
def test_config():
    """Pytest fixture providing test configuration."""
    return TestConfig()


@pytest.fixture(scope="session") 
def db_connection_config(test_config):
    """Pytest fixture providing database connection configuration."""
    return test_config.get_connection_config()


def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line(
        "markers", 
        "requires_db: mark test as requiring real database connection"
    )


def pytest_collection_modifyitems(config, items):
    """Automatically skip database tests if credentials are not available."""
    test_cfg = TestConfig()
    
    if not test_cfg.has_db_credentials:
        skip_db = pytest.mark.skip(reason="Database credentials not available")
        for item in items:
            if "requires_db" in item.keywords:
                item.add_marker(skip_db)
