# Feature: Environment Definition Extraction

## Overview
The **environment definition extraction** feature enables users to **extract metadata about databases, users, roles, and profiles** from a Teradata environment and store it in a structured TOML format. This feature is part of the **DMaaC (Database Metadata as Code)** approach, which treats database infrastructure definitions as version-controlled artifacts.

Unlike the standard `env-extract` feature that extracts **database objects** (tables, views, procedures), this feature extracts the **environment's structural configuration**, including:
- **Databases** with their space allocations and ownership
- **Users** with their permissions and space quotas
- **Roles** with their assigned privileges
- **Profiles** with account settings

This extracted metadata can then be used to **recreate or synchronize environments**, ensuring consistent infrastructure across development, testing, and production systems.

## Use Cases

### **Infrastructure as Code (IaC) for Databases**
Extract the complete environment definition from production and store it in Git, enabling **version-controlled infrastructure** that can be reviewed, compared, and deployed like application code.

### **Environment Cloning and Provisioning**
Extract metadata from an existing environment and use it as a template to **provision new environments** with identical structure, users, roles, and permissions.

### **Disaster Recovery Planning**
Maintain up-to-date snapshots of environment definitions to support **rapid recovery** in case of system failures or data center disasters.

### **Compliance and Auditing**
Track changes to database infrastructure over time by regularly extracting and committing environment definitions, supporting **audit trails** and compliance requirements.

## Usage
The basic syntax for environment definition extraction:

```bash
d-bee env-def-extract [OPTIONS] ENVIRONMENT
```

Where:
- **`ENVIRONMENT`** → The name of the database environment to extract, **as defined in `dblocks.toml`**.

### Example: Extracting Environment Definition
```bash
d-bee env-def-extract production
```

This extracts all databases, users, roles, and profiles from the `production` environment and stores them in TOML format in the `env_definition/` directory.

## Options

### **1. Filtering Databases**
To extract only specific databases matching a pattern:

```bash
# Extract only databases starting with 'sales'
d-bee env-def-extract production --filter-databases sales%

# Extract databases ending with '_db'
d-bee env-def-extract production --filter-databases %_db

# Extract databases containing 'prod'
d-bee env-def-extract production --filter-databases %prod%
```

**Important:** The `%` wildcard matches any sequence of characters (SQL LIKE pattern). Filtering is applied **at the SQL level** for optimal performance.

### **2. Filtering Roles**
To extract only specific roles:

```bash
# Extract roles starting with 'app'
d-bee env-def-extract production --filter-roles app%

# Extract only admin-related roles
d-bee env-def-extract production --filter-roles %admin%
```

### **3. Filtering Profiles**
To extract only specific profiles:

```bash
# Extract profiles for development users
d-bee env-def-extract production --filter-profiles dev_%

# Extract specific profile types
d-bee env-def-extract production --filter-profiles %_standard
```

### **4. Combining Multiple Filters**
Filters can be combined to extract a focused subset of the environment:

```bash
d-bee env-def-extract production \
  --filter-databases sales% \
  --filter-roles sales_% \
  --filter-profiles sales_%
```

This extracts only the databases, roles, and profiles related to the `sales` domain.

### **5. Scoping Extraction**
The extraction respects the `extraction.databases` configuration in `dblocks.toml`. If specified, only databases within the configured scope are extracted, along with their ownership hierarchy.

Example `dblocks.toml` configuration:
```toml
[extraction]
databases = ["sales_db", "marketing_db"]
```

This ensures that even without filters, only the specified databases and their dependencies are extracted.

### **6. Skipping Confirmation Prompts**
To bypass interactive confirmation:

```bash
d-bee env-def-extract production --assume-yes
```

## Extraction Output
The extracted environment definition is stored in the `env_definition/` directory with a structured folder hierarchy. **Each object is exported to its own TOML file**, organized by object type:

```
env_definition/
├── databases/
│   ├── sales_db.toml
│   ├── sales_staging_db.toml
│   └── sales_reporting_db.toml
├── users/
│   ├── app_user.toml
│   ├── etl_user.toml
│   └── admin_user.toml
├── roles/
│   ├── app_role.toml
│   └── admin_role.toml
├── profiles/
│   ├── default_profile.toml
│   └── high_usage_profile.toml
└── privileges/
    ├── databases/
    │   ├── sales_db.toml
    │   └── sales_staging_db.toml
    ├── roles/
    │   ├── app_role.toml
    │   └── admin_role.toml
    └── users/
        ├── app_user.toml
        └── etl_user.toml
```

### File Structure Details

#### **Database TOML Files** (`databases/<database_name>.toml`)
Each database is defined with its space allocations and ownership:

```toml
name = "sales_db"
kind = "database"
owner = "dbc"
perm_space = "10000000000"
spool_space = "5000000000"
temp_space = "2000000000"
comment = "Sales database for production environment"
```

**Fields:**
- `name` - Database name
- `kind` - Object type (always "database")
- `owner` - Owner database or user
- `perm_space` - Permanent space in bytes
- `spool_space` - Spool space in bytes
- `temp_space` - Temporary space in bytes
- `comment` - Optional database comment

#### **User TOML Files** (`users/<user_name>.toml`)
Each user is defined with their configuration and space quotas:

```toml
name = "app_user"
kind = "user"
owner = "sales_db"
perm_space = "0"
spool_space = "20000000"
temp_space = "10000000"
default_database = "sales_db"
account = "prod_account"
password = "<REDACTED>"
comment = "Application user with role-based access"
```

**Fields:**
- `name` - User name
- `kind` - Object type (always "user")
- `owner` - Owner database
- `perm_space`, `spool_space`, `temp_space` - Space allocations in bytes
- `default_database` - Default database for the user
- `account` - Account string
- `password` - Encrypted or redacted password
- `comment` - Optional user comment

#### **Role TOML Files** (`roles/<role_name>.toml`)
Each role is defined minimally:

```toml
name = "app_role"
kind = "role"
```

**Fields:**
- `name` - Role name
- `kind` - Object type (always "role")

#### **Profile TOML Files** (`profiles/<profile_name>.toml`)
Each profile is defined with its account settings:

```toml
name = "default_profile"
kind = "profile"
account = "$R0$DefaultAccount&D&H"
```

**Fields:**
- `name` - Profile name
- `kind` - Object type (always "profile")
- `account` - Account string with profile settings

### Privileges Structure

Privileges are stored separately from the objects themselves, organized by grantee type (databases or users). **Each grantee (the object receiving privileges) has its own TOML file** in the privileges directory.

#### **Database Privileges** (`privileges/databases/<database_name>.toml`)
Defines what privileges a database has been granted on other databases:

```toml
grantee_name = "sales_db"
grantee_type = "database"
kind = "privileges"

[[grant]]
database = "source_db"
privileges_with_grant_option = ["SELECT", "INSERT", "UPDATE"]

[[grant]]
database = "staging_db"
privileges = ["SELECT"]

[[grant]]
database = "reference_db"
privileges_with_grant_option = ["SELECT"]
```

**Fields:**
- `grantee_name` - Name of the database receiving privileges
- `grantee_type` - Type of grantee (always "database" for database privileges)
- `kind` - Object type (always "privileges")
- `[[grant]]` - Array of grant entries (one per target database)
  - `database` - Target database where privileges are granted
  - `privileges` - List of privileges without GRANT OPTION
  - `privileges_with_grant_option` - List of privileges with GRANT OPTION

#### **Role Privileges** (`privileges/roles/<role_name>.toml`)
Defines what privileges a role has been granted on databases (extracted from `DBC.AllRoleRightsV`):

```toml
grantee_name = "app_role"
grantee_type = "role"
kind = "privileges"

[[grant]]
database = "sales_db"
privileges = ["SELECT", "INSERT", "UPDATE", "DELETE"]

[[grant]]
database = "staging_db"
privileges = ["SELECT"]
```

**Fields:**
- `grantee_name` - Name of the role receiving privileges
- `grantee_type` - Type of grantee (always "role" for role privileges)
- `kind` - Object type (always "privileges")
- `[[grant]]` - Array of grant entries (one per target database)
  - `database` - Target database where privileges are granted
  - `privileges` - List of privileges (note: `DBC.AllRoleRightsV` doesn't provide GRANT OPTION information)

**Note:** Role privileges are extracted from `DBC.AllRoleRightsV`, which shows all privileges assigned to roles but doesn't indicate whether they were granted WITH GRANT OPTION.

#### **User Privileges** (`privileges/users/<user_name>.toml`)
Defines what privileges a user has been granted on databases:

```toml
grantee_name = "app_user"
grantee_type = "user"
kind = "privileges"

[[grant]]
database = "sales_db"
privileges = ["CREATE TABLE", "CREATE VIEW", "DROP TABLE"]

[[grant]]
database = "staging_db"
privileges_with_grant_option = ["SELECT", "INSERT"]

[[grant]]
role = "app_role"

[[grant]]
role = "admin_role"
with_admin = ["ADMIN"]
```

**Fields:**
- `grantee_name` - Name of the user receiving privileges/roles
- `grantee_type` - Type of grantee (always "user" for user privileges)
- `kind` - Object type (always "privileges")
- `[[grant]]` - Array of grant entries (privileges and roles)
  - **For database privileges:**
    - `database` - Target database where privileges are granted
    - `privileges` - List of privileges without GRANT OPTION
    - `privileges_with_grant_option` - List of privileges with GRANT OPTION
  - **For role assignments:**
    - `role` - Name of the role granted to the user
    - `with_admin` - Optional array containing ["ADMIN"] if granted WITH ADMIN OPTION

### Privilege Types

Common Teradata privileges that may appear in the `privileges` or `privileges_with_grant_option` arrays include:

**Data Manipulation:**
- `SELECT`, `INSERT`, `UPDATE`, `DELETE`

**Object Management:**
- `CREATE TABLE`, `CREATE VIEW`, `CREATE PROCEDURE`, `CREATE FUNCTION`
- `DROP TABLE`, `DROP VIEW`, `DROP PROCEDURE`, `DROP FUNCTION`
- `ALTER TABLE`, `ALTER PROCEDURE`

**Database Management:**
- `CREATE DATABASE`, `DROP DATABASE`
- `DATABASE`

**Execution:**
- `EXECUTE PROCEDURE`, `EXECUTE FUNCTION`

**Note:** The `WITH GRANT OPTION` clause allows the grantee to further grant the same privileges to other users or databases. Privileges with grant option are stored in the `privileges_with_grant_option` array, while regular privileges are stored in the `privileges` array.

## Version Control Benefits

Each TOML file contains structured metadata that can be:
- **Version-controlled** in Git to track infrastructure changes over time
- **Compared** using standard diff tools to see what changed between environments
- **Reviewed** in pull requests before deploying to production
- **Deployed** to other environments for consistent infrastructure

## Performance Considerations

### **SQL-Level Filtering**
All filters are applied **at the database level** using SQL `WHERE` clauses with `LIKE` patterns. This means:
- Filtering happens **before data is transferred** to the client
- Only matching records are retrieved from system tables
- Performance is optimized for large environments with many objects

### **Hybrid Filtering for Databases**
Database filtering uses a **hybrid approach**:
1. All databases are initially retrieved to analyze **ownership hierarchies**
2. Scoping rules from `dblocks.toml` are applied
3. Database filters are applied **in Python after scoping**

This ensures that parent databases are not accidentally excluded when child databases are needed.

## Next Steps
After extracting environment definitions:
- **Review the TOML files** in the `env_definition/` directory
- **Commit changes to Git** if using auto-commit or manually commit
- Use **`env-def-deploy`** to deploy the definition to another environment
- Use **`env-def-destroy`** to safely tear down an environment

By treating database infrastructure as code, teams can achieve **reproducible, version-controlled, and auditable database environments**. 🚀
