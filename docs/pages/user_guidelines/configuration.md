# Configuration Guide for d-bee

## Overview
Configuration in **d-bee** defines how database environments are managed, synchronized, and maintained. It enables users to:
- Define multiple environments (e.g., **development, testing, production**).
- Specify how d-bee interacts with Git and database systems.
- Securely store sensitive credentials.
- Control extraction, synchronization, and deployment behavior.

## Configuration Files
d-bee uses two primary configuration files:
- **`dblocks.toml`** (Public settings - version-controlled in Git)
- **`.dblocks-secrets.toml`** (Sensitive settings - stored securely outside Git)

These files are automatically created when running:
```bash
dbee init
```
You can get more information in [d-bee's Project Structure](project_structure.md) section.

## Defining Environments
Each environment represents a specific database instance and must be defined explicitly in `dblocks.toml`.

Example configuration:
```toml
[ environments.dev ]
platform = "teradata"
git_branch = "main"

# Connection details
host = "your_database_host"
username = "your_username"
connection_parameters.logmech = "TD2"
connection_parameters.tmode = "TERA"

# Code storage
writer.target_dir = "./db"

# Define databases within the environment
extraction.databases = [ "database_1", "database_2" ]

# Tagging rules (used for environment-agnostic object naming)
tagging_rules = [ "{{env_db}}%" ]
```

### Managing Sensitive Information
**Never store passwords in `dblocks.toml`!** Instead, use:

1. **Environment variables (Recommended Approach)**:
   ```bash
   export DBLOCKS_ENVIRONMENTS__DEV__PASSWORD=your_secure_password
   ```
2. **Secrets file (`.dblocks-secrets.toml`)**:
   ```toml
   environments.dev.password = "your_secure_password"
   ```

## Advanced Configuration Options
### Logging Settings
d-bee logs activities using the `loguru` library. Customize logging in `dblocks.toml`:
```toml
[ logging ]
console_log_level = "INFO"
other_sinks.debug_sink.sink = "./log/dblocks.log"
other_sinks.debug_sink.level = "DEBUG"
other_sinks.debug_sink.rotation = "5 days"
other_sinks.debug_sink.retention = "15 days"
```

### Package Management
d-bee manages **database object deployment packages** via a structured directory:
```toml
[ packager ]
package_dir = "./pkg"
steps_subdir = "db/Teradata"
safe_deletion_limit = 50
interactive = true
```

## Testing Your Configuration
Validate that your configuration is set up correctly:
```bash
dbee cfg-check
dbee env-test-connection dev
```
If these commands succeed, your configuration is correctly set up!

---
This guide ensures you configure d-bee effectively while following security best practices. 🚀
