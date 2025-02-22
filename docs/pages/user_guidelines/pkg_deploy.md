# Feature: Package Deployment

## Overview
The **package deployment** feature is designed for deploying **incremental database changes** to higher environments, such as **testing and production**. Unlike **environment deployment**, which is commonly used for development, **package deployment** ensures a structured, controlled, and resilient way of delivering changes. It is built with **strictness, failure resistance, and recovery options** in mind, making it ideal for production workflows.

## Use Cases

### **Deploying Incremental Packages to Testing and Production**
Package deployment primarily supports the **creation and application of incremental packages**, which are tested against **testing environments** before being rolled out to **production**. This ensures controlled and predictable updates.

### **Quick Synchronization of Two Environments**
If there is a need to **quickly align production and testing environments**, users can compare both environments (physically or via Git branches). By using another feature (**Package Creation**, coming soon), a **gap package** can be generated and then deployed to synchronize the two environments efficiently.

### **Supporting Daily Full Builds in Testing Environments**
As part of **Continuous Integration (CI) processes**, package deployment helps in **automated integration testing** by:
- Comparing the **testing environment** with the **common integration branch**.
- Generating an **update package** based on detected differences.
- Deploying the package to maintain a **consistent and updated testing environment** for feature validation.

## Usage
The `pkg-deploy` command is used to deploy a **structured package** to a target environment.

```bash
d-bee pkg-deploy [OPTIONS] ENVIRONMENT PATH
```

Where:
- **`ENVIRONMENT`** → The name of the target environment (as defined in `dblocks.toml`).
- **`PATH`** → The path to the **package** that needs to be deployed.

### Example: Deploying an Incremental Package
```bash
d-bee pkg-deploy test ./package_v1.2
```
This deploys the package located at `./package_v1.2` to the `test` environment.

## Deployment Strategies
### **Dry Run Mode**
Before executing a deployment, users can **simulate** the process to verify potential issues:
```bash
d-bee pkg-deploy test ./package_v1.2 --dry-run
```
This ensures no changes are made to the environment during testing.

### **Handling Object Conflicts**
Similar to **environment deployment**, users can define how to handle conflicts when objects already exist in the target environment:
```bash
# Raise an error if the object exists (default)
d-bee pkg-deploy test ./package_v1.2 --if-exists raise

# Rename existing objects before deployment
d-bee pkg-deploy test ./package_v1.2 --if-exists rename

# Drop existing objects before deployment
d-bee pkg-deploy test ./package_v1.2 --if-exists drop
```

### **Other Options**
| Option | Description |
|--------|-------------|
| `--dry-run` | Simulates deployment without modifying the target environment. |
| `--assume-yes` | Do not ask for confirmation (use carefully). |
| `--countdown-from INTEGER` | Delay execution after confirmation (default: 3 seconds). |

## Next Steps
Once package deployment is complete:
- Verify that all database changes were applied successfully.
- If necessary, rollback changes based on disaster recovery strategies.
- Continue monitoring for any required fixes or follow-up updates.

By following structured package deployment, users can **ensure smooth, controlled, and reliable database changes** in testing and production environments. 🚀
