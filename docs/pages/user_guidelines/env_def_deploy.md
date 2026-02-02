# Feature: Environment Definition Deployment

## Overview
The **environment definition deployment** feature enables users to **deploy database infrastructure** (databases, users, roles, profiles) from a structured TOML definition to a target Teradata environment. This feature is the deployment counterpart to `env-def-extract` and is part of the **DMaaC (Database Metadata as Code)** approach.

Rather than manually creating databases and users with SQL scripts, this feature allows teams to:
- Deploy **version-controlled infrastructure definitions** consistently across environments
- Automatically calculate **cumulative space allocations** based on child database requirements
- Resolve **complex dependencies** between databases, users, and roles
- Handle **deployment conflicts** with configurable strategies

This ensures that database infrastructure can be treated as code, enabling **reproducible and automated environment provisioning**.

## Use Cases

### **Environment Provisioning and Cloning**
Deploy an extracted environment definition to provision **new development, testing, or staging environments** with identical structure to production.

### **Infrastructure Synchronization**
Keep multiple environments aligned by extracting from a source environment and deploying to targets, ensuring **consistent configurations** across the landscape.

### **Disaster Recovery**
Rapidly restore database infrastructure by deploying previously extracted and version-controlled environment definitions after system failures.

### **Automated CI/CD Pipelines**
Integrate environment definition deployment into **continuous delivery workflows**, automatically provisioning fresh test environments as part of build processes.

## Usage
The basic syntax for environment definition deployment:

```bash
d-bee env-def-deploy [OPTIONS] ENVIRONMENT PATH
```

Where:
- **`ENVIRONMENT`** → The name of the target database environment, **as defined in `dblocks.toml`**
- **`PATH`** → The path to the directory containing environment definition TOML files (databases.toml, users.toml, roles.toml, profiles.toml)

### Example: Deploying Environment Definition
```bash
d-bee env-def-deploy development ./env_definition
```

This deploys all databases, users, roles, and profiles from the `./env_definition/` directory to the `development` environment.

## Deployment Strategies

### **Handling Existing Objects**
When deploying to an environment where objects already exist, you can control the behavior using the `--if-exists` option:

```bash
# Skip existing objects without error (default)
d-bee env-def-deploy development ./env_definition --if-exists skip

# Drop and recreate existing objects
d-bee env-def-deploy development ./env_definition --if-exists drop

# Raise an error if objects exist
d-bee env-def-deploy development ./env_definition --if-exists raise

# Ignore the check and attempt to create (will fail with SQL error)
d-bee env-def-deploy development ./env_definition --if-exists ignore
```

**Strategy Details:**
- **`skip`** → Existing objects are left unchanged; only new objects are created
- **`drop`** → Existing objects are dropped before recreating (⚠️ destructive!)
- **`raise`** → Deployment fails immediately if any object already exists
- **`ignore`** → Attempts to create objects regardless, letting SQL errors surface

### **Dry Run Mode**
Preview the deployment without making any changes:

```bash
d-bee env-def-deploy development ./env_definition --dry-run
```

This generates all DDL statements and shows what would be executed, but doesn't modify the target environment.

### **Skipping Confirmation**
Bypass interactive confirmation prompts:

```bash
d-bee env-def-deploy development ./env_definition --assume-yes
```

## Deployment Process

### **Wave-Based Dependency Resolution**
The deployment engine automatically resolves dependencies between objects and deploys them in multiple waves:

1. **Wave 1:** Root-level databases (with DBC as owner)
2. **Wave 2:** First-level child databases (owned by Wave 1 databases)
3. **Wave 3:** Second-level child databases, and so on...
4. **Roles and Profiles:** Deployed before users that reference them
5. **Users:** Deployed last, after all dependencies are in place

This ensures that **parent objects always exist before their children**, preventing dependency errors.

### **Cumulative Space Calculation**
One of the key features is **automatic space calculation** for parent databases:

When deploying nested database hierarchies, the system:
1. Calculates the **total space requirements** of all child databases
2. Aggregates these into a **cumulative space allocation** for parent databases
3. Ensures parent databases have **sufficient space** to accommodate all children

**Fallback Logic:**
- If cumulative space is calculated as **greater than 0**, it is used for deployment
- If cumulative space is **0 or not calculated**, the system falls back to the **original space allocation** from the JSON definition
- If neither is available, the space parameter is **omitted from the DDL**

This prevents **Error 3796** (missing PERM space specification) while ensuring efficient space allocation.

### **Example Space Calculation:**
```
sales_db (original PERM: 10GB)
├── sales_staging_db (PERM: 5GB)
└── sales_reporting_db (PERM: 8GB)

Cumulative PERM for sales_db: 5GB + 8GB = 13GB
Deployed with: PERM = 13GB (using cumulative, not original 10GB)
```

## Common Deployment Scenarios

### **Fresh Environment Provisioning**
```bash
# Deploy to a clean environment with all objects
d-bee env-def-deploy dev ./env_definition --if-exists raise
```

### **Updating an Existing Environment**
```bash
# Skip existing objects, create only new ones
d-bee env-def-deploy dev ./env_definition --if-exists skip
```

### **Full Rebuild (Destructive)**
```bash
# Drop and recreate everything
d-bee env-def-deploy dev ./env_definition --if-exists drop --assume-yes
```

### **Preview Changes Before Deployment**
```bash
# Dry run to see generated DDL
d-bee env-def-deploy dev ./env_definition --dry-run
```

## Deployment Output
During deployment, the system provides detailed progress information:
- Number of objects processed in each wave
- DDL statements being executed (in verbose mode)
- Success/failure status for each object
- Summary of deployment results

## Troubleshooting

### **Error 3796: Missing PERM Space**
If you encounter this error, ensure that:
- Parent databases in the TOML definition have proper space allocations
- The cumulative space calculation fallback is working (fixed in recent versions)
- Verify `perm_space` values in `databases.toml`

### **Dependency Errors**
If objects fail due to missing dependencies:
- Check that all required parent databases are included in the definition
- Verify that users reference valid owner databases
- Ensure roles and profiles exist before users that reference them

### **Permission Errors**
If deployment fails with privilege errors:
- Ensure the deploying user has sufficient privileges (CREATE DATABASE, CREATE USER, etc.)
- Verify that the target environment connection has appropriate admin rights

## Next Steps
After deploying environment definitions:
- **Verify object creation** by querying system tables or using `env-def-extract` to compare
- **Deploy database objects** using standard `env-deploy` or `pkg-deploy` features
- **Test the environment** to ensure all infrastructure is functioning correctly
- Use **`env-def-destroy`** if you need to tear down the environment safely

By automating infrastructure deployment, teams can achieve **faster provisioning, consistent environments, and reduced manual errors**. 🚀
