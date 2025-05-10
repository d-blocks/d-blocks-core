- [Feature: Environment Deployment](#feature-environment-deployment)
  - [Overview](#overview)
  - [Use Cases](#use-cases)
    - [**Deployment of Objects to Development Environments**](#deployment-of-objects-to-development-environments)
    - [**Synchronizing a Development Environment with a Git Branch**](#synchronizing-a-development-environment-with-a-git-branch)
    - [**Provisioning a New Environment**](#provisioning-a-new-environment)
    - [**Environment Cloning (Extraction + Deployment)**](#environment-cloning-extraction--deployment)
  - [Usage](#usage)
    - [**Example: Deploy to a Development Environment**](#example-deploy-to-a-development-environment)
  - [Deployment Strategies](#deployment-strategies)
    - [**Handling Object Conflicts**](#handling-object-conflicts)
    - [**Deployment Order Handling**](#deployment-order-handling)
    - [**Other Options**](#other-options)
  - [Next Steps](#next-steps)

# Feature: Environment Deployment

## Overview

The **environment deployment** feature allows users to deploy database code from a **Git repository** or a **specified directory** containing DDL scripts to a target database environment.

While **environment deployment** is mainly used for development and new environment provisioning, **package deployment** (covered in the next [section](pkg_deploy.md)) is used for incremental deployments to higher environments, including production.

## Use Cases

### **Deployment of Objects to Development Environments**

Developers can deploy individual or multiple database objects to their development environments. The ability to select a **conflict strategy** ensures that developers **do not have to manually resolve conflicts**, such as existing table structures.

### **Synchronizing a Development Environment with a Git Branch**

Before starting new development work, developers often need to ensure that their environment is up to date with a specific **Git branch**. This feature allows seamless **synchronization** with the chosen branch before beginning new implementations.

### **Provisioning a New Environment**

Organizations often need to provision new **development or testing environments**. The environment deployment feature enables setting up an environment **from scratch**, ensuring that all required objects are deployed properly.

### **Environment Cloning (Extraction + Deployment)**

A combination of **environment extraction and deployment** can be used to **clone an environment**. For example, before deploying a **new release package** to a **testing environment**, users may first extract the **latest production version** and deploy it to the **test environment** to align the two.

## Usage

The `env-deploy` command is used to deploy database objects to a configured environment.

```bash
d-bee env-deploy [OPTIONS] ENVIRONMENT PATH
```

Where:

- **`ENVIRONMENT`** → The name of the target environment (as defined in `dblocks.toml`).
- **`PATH`** → The path to the database code (either a **Git-tracked directory** or any directory with DDL scripts).

### **Example: Deploy to a Development Environment**

```bash
d-bee env-deploy dev ./database_code
```

This deploys all objects from `./database_code` to the `dev` environment.

## Deployment Strategies

A key aspect of **environment deployment** is how it handles conflicts when objects already exist in the target environment.

### **Handling Object Conflicts**

Use the `--if-exists` flag to specify how to handle existing objects:

```bash
# Raise an error if the object exists (default)
d-bee env-deploy dev ./database_code --if-exists raise

# Rename existing objects before deployment
d-bee env-deploy dev ./database_code --if-exists rename

# Drop existing objects before deployment
d-bee env-deploy dev ./database_code --if-exists drop
```

### **Deployment Order Handling**

Unlike **package deployment**, which follows a strict order, **environment deployment** deploys objects **without a predefined order**. The deployment process works as follows:

- Objects are sorted **alphabetically** and deployed in that order.
- If an object fails to deploy, it is moved to the next **deployment round**.
- The process repeats, attempting to deploy as many objects as possible in each round.
- If no progress is made in a round (i.e., all remaining objects fail to deploy), the deployment **fails**.

This approach ensures that dependent objects (such as views relying on tables) can still be deployed once their dependencies are in place.

### **Other Options**

Option                     | Description
-------------------------- | ------------------------------------------------------------------
`--assume-yes`             | Do not ask for confirmation (use carefully).
`--countdown-from INTEGER` | Delay execution after confirmation (default: 3 seconds).
`--delete-databases`       | If enabled, deletes all objects before deployment (use carefully).
`--log-each INTEGER`       | Log every `n`-th deployed object (default: 20).

## Next Steps

Once the environment deployment is complete:

- Verify that all required objects exist in the target environment.
- If needed, apply **package deployment** for structured releases (see next section).

By following these structured deployment processes, users can **automate and streamline** their database development workflows. 🚀
