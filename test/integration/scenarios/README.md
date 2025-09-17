# Integration Test Scenarios

This directory contains individual test scenarios for dbee utility integration testing. Each scenario is implemented as a separate test file to improve maintainability and scalability.

## Structure

```
test/integration/scenarios/
├── __init__.py                           # Package initialization
├── base.py                              # Shared base class and utilities
├── test_00_database_connectivity.py     # Database connection prerequisite
├── test_01_dbee_help.py                # dbee --help command test
├── test_02_dbee_cfg_check.py           # dbee cfg-check command test
├── test_03_dbee_env_list.py            # dbee env-list command test
├── test_04_dbee_env_test_connection.py # dbee env-test-connection test
└── README.md                           # This file
```

## Execution Order

The test scenarios are designed to run in a specific order using pytest-order markers:

1. **test_00_database_connectivity**: Verifies database connection as a prerequisite
2. **test_01_dbee_help**: Tests basic help functionality
3. **test_02_dbee_cfg_check**: Validates configuration file
4. **test_03_dbee_env_list**: Checks environment listing
5. **test_04_dbee_env_test_connection**: Tests database connectivity via dbee

## Running Tests

### Run all scenarios in order:
```bash
poetry run pytest test/integration/scenarios/ -v
```

### Run specific scenario:
```bash
poetry run pytest test/integration/scenarios/test_01_dbee_help.py -v
```

### Run with specific markers:
```bash
# Run only database-dependent tests
poetry run pytest test/integration/scenarios/ -m "requires_db" -v

# Run only scenario tests (excluding database connectivity)
poetry run pytest test/integration/scenarios/ -m "scenarios" -v
```

## Base Class

All scenario tests inherit from `BaseScenarioTest` which provides:

- **Common setup/teardown**: Logging and test lifecycle management
- **Workspace utilities**: Configuration verification and directory management
- **Credential helpers**: Environment variable handling for test credentials
- **Output utilities**: Command output logging and analysis

## Adding New Scenarios

To add a new test scenario:

1. Create a new file: `test_05_new_scenario.py`
2. Inherit from `BaseScenarioTest`
3. Add appropriate pytest markers:
   - `@pytest.mark.integration`
   - `@pytest.mark.scenarios` (for utility tests)
   - `@pytest.mark.requires_db` (if database access needed)
   - `@pytest.mark.slow`
   - `@pytest.mark.order(5)` (set appropriate order)
4. Implement your test method
5. Use base class utilities for common operations

## Dependencies

- **pytest-order**: Ensures tests run in the correct sequence
- **loguru**: Enhanced logging capabilities
- **sqlalchemy**: Database connectivity testing
- **pytest markers**: Test categorization and filtering

## Environment Variables

Tests expect these environment variables to be set:

- `TEST_DB_HOST`: Database host for testing
- `TEST_DB_USER`: Database username for testing  
- `TEST_DB_PASSWORD`: Database password for testing
- `TEST_DB_NAME`: Target database name for testing
