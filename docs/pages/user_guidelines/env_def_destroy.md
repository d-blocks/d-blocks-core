# Feature: Environment Definition Destruction

## Overview
The **environment definition destruction** feature provides a **safe and controlled way to tear down database infrastructure** (databases, users, roles, profiles) from a Teradata environment. This feature complements `env-def-deploy` and is designed to handle the complex task of removing objects in the correct order to satisfy dependency constraints.

Unlike manually dropping objects with SQL, this feature:
- Automatically resolves **dependency order** using topological sorting
- Drops **child objects before parent objects** to avoid constraint violations
- Provides **dry-run mode** to preview destruction without executing
- Handles **role and profile dependencies** correctly
- Offers **configurable behavior** for missing objects

This ensures that database infrastructure can be safely decommissioned without leaving orphaned objects or encountering dependency errors.

## Use Cases

### **Decommissioning Development Environments**
Tear down temporary or feature-specific development environments after projects are completed, reclaiming system resources.

### **Cleaning Test Environments**
Remove all infrastructure from testing environments between test cycles to ensure a clean slate for the next round of testing.

### **Disaster Recovery Testing**
Validate disaster recovery procedures by destroying and recreating environments, ensuring that extraction and deployment processes are reliable.

### **Cost Optimization**
Decommission unused environments in cloud or on-premise systems to reduce resource consumption and associated costs.

## Usage
The basic syntax for environment definition destruction:

```bash
d-bee env-def-destroy [OPTIONS] ENVIRONMENT PATH
```

Where:
- **`ENVIRONMENT`** → The name of the target database environment, **as defined in `dblocks.toml`**
- **`PATH`** → The path to the directory containing environment definition TOML files that describe what to destroy

### Example: Destroying Environment Infrastructure
```bash
d-bee env-def-destroy development ./env_definition
```

This destroys all databases, users, roles, and profiles defined in the `./env_definition/` directory from the `development` environment.

## Destruction Process

### **Dependency-Aware Ordering**
The destruction engine uses **topological sorting** to determine the correct order for dropping objects:

1. **Users:** Dropped first (they depend on databases, roles, and profiles)
2. **Child Databases:** Dropped before their parent databases (bottom-up hierarchy)
3. **Parent Databases:** Dropped after all children are removed
4. **Roles:** Dropped after users that reference them
5. **Profiles:** Dropped last, after all dependent users

This ensures that **children are always removed before parents**, preventing SQL errors like:
- "Cannot drop database: other databases owned by it"
- "Cannot drop role: assigned to existing users"

### **Example Destruction Order:**
```
Destruction sequence:
1. app_user (depends on app_db, app_role, app_profile)
2. app_reporting_db (child of app_db)
3. app_staging_db (child of app_db)
4. app_db (parent database)
5. app_role (role used by app_user)
6. app_profile (profile used by app_user)
```

## Destruction Strategies

### **Handling Missing Objects**
When destroying objects that may not exist in the target environment, use the `--if-not-exists` option:

```bash
# Skip missing objects without error (default)
d-bee env-def-destroy development ./env_definition --if-not-exists skip

# Raise an error if objects don't exist
d-bee env-def-destroy development ./env_definition --if-not-exists raise

# Ignore the check and attempt to drop (will fail with SQL error)
d-bee env-def-destroy development ./env_definition --if-not-exists ignore
```

**Strategy Details:**
- **`skip`** → Missing objects are silently skipped; only existing objects are dropped
- **`raise`** → Destruction fails immediately if any object is missing
- **`ignore`** → Attempts to drop objects regardless, letting SQL errors surface

### **Dry Run Mode** ⚠️ **HIGHLY RECOMMENDED**
Preview the destruction without making any changes:

```bash
d-bee env-def-destroy development ./env_definition --dry-run
```

This generates all DROP statements and shows what would be executed, but doesn't modify the target environment.

**Best Practice:** Always run with `--dry-run` first to verify the destruction plan before executing.

### **Skipping Confirmation**
Bypass interactive confirmation prompts (use with caution):

```bash
d-bee env-def-destroy development ./env_definition --assume-yes
```

⚠️ **Warning:** Destruction is irreversible. Ensure you have backups or can recreate the environment before proceeding.

## Safety Features

### **1. Mandatory Confirmation**
By default, the system requires explicit confirmation before destroying objects, displaying:
- List of objects to be destroyed
- Destruction order
- Target environment name

### **2. Dry Run First**
The `--dry-run` mode allows users to:
- Verify the destruction plan
- Review generated DROP statements
- Identify potential issues before execution

### **3. Topological Sorting**
Automatic dependency resolution prevents:
- Constraint violation errors
- Orphaned objects
- Failed destruction attempts

### **4. Error Handling**
The system provides detailed error messages when:
- Objects cannot be dropped due to dependencies
- Permission errors occur
- SQL execution fails

## Common Destruction Scenarios

### **Safe Destruction with Preview**
```bash
# Step 1: Preview the destruction plan
d-bee env-def-destroy dev ./env_definition --dry-run

# Step 2: Execute the destruction
d-bee env-def-destroy dev ./env_definition
```

### **Partial Environment Cleanup**
```bash
# Destroy only specific objects using filtered extraction
d-bee env-def-extract dev --filter-databases temp_%
d-bee env-def-destroy dev ./env_definition --assume-yes
```

### **Full Environment Teardown**
```bash
# Destroy everything, skip missing objects
d-bee env-def-destroy dev ./env_definition --if-not-exists skip --assume-yes
```

### **Strict Destruction (Fail on Missing)**
```bash
# Ensure all objects exist before destroying
d-bee env-def-destroy dev ./env_definition --if-not-exists raise
```

## Destruction Output
During destruction, the system provides detailed progress information:
- Number of objects to be destroyed
- Destruction order (topologically sorted)
- DROP statements being executed (in verbose mode)
- Success/failure status for each object
- Summary of destruction results

## Troubleshooting

### **Dependency Errors**
If destruction fails with "object is referenced by other objects":
- Check if there are objects **not in the definition** that still reference the ones being destroyed
- Use `--dry-run` to review the destruction order
- Manually drop external dependencies first

### **Permission Errors**
If destruction fails with privilege errors:
- Ensure the executing user has sufficient privileges (DROP DATABASE, DROP USER, etc.)
- Verify that the target environment connection has appropriate admin rights

### **Objects Not Found**
If objects are missing during destruction:
- Use `--if-not-exists skip` to ignore missing objects
- Verify that the definition file matches the current environment state
- Re-extract the environment to get the current state

## Best Practices

1. **Always Use Dry Run First**
   ```bash
   d-bee env-def-destroy dev ./env_definition --dry-run
   ```

2. **Verify Target Environment**
   Double-check that you're targeting the correct environment in `dblocks.toml` before destroying.

3. **Keep Backups**
   Ensure you have recent extractions or backups before destroying critical environments.

4. **Use Version Control**
   Commit environment definitions to Git before destruction to enable recreation if needed.

5. **Test in Lower Environments**
   Practice destruction in development before applying to testing or production.

## Next Steps
After destroying environment infrastructure:
- **Verify removal** by querying system tables or using `env-def-extract`
- **Clean up orphaned objects** if any remain due to external dependencies
- **Re-deploy** using `env-def-deploy` if recreation is needed
- **Document the destruction** for audit and compliance purposes

By providing safe and automated infrastructure destruction, teams can **manage environment lifecycles efficiently** while minimizing risks. 🚀
