- [Feature: Environment Extraction](#feature-environment-extraction)
  - [Overview](#overview)
  - [Use cases](#use-cases)
    - [**Initializing Master Branch from Production**](#initializing-master-branch-from-production)
    - [**Developer Support During Development**](#developer-support-during-development)
    - [**Monitoring Hotfixes in Production**](#monitoring-hotfixes-in-production)
    - [**Cloning an Existing Environment**](#cloning-an-existing-environment)
  - [Usage](#usage)
    - [Example: Extracting a Production Database](#example-extracting-a-production-database)
  - [Options](#options)
    - [**1. Extracting Incremental vs. Full Data**](#1-extracting-incremental-vs-full-data)
    - [**2. Extract only selected objects**](#2-extract-only-selected-objects)
    - [**3. Skipping Confirmation Prompts**](#3-skipping-confirmation-prompts)
    - [**4. Auto-Commit Changes**](#4-auto-commit-changes)
    - [**4. Filtering Specific Objects**](#4-filtering-specific-objects)
    - [**5. Delayed Extraction with Countdown**](#5-delayed-extraction-with-countdown)
  - [Next Steps](#next-steps)

# Feature: Environment Extraction

## Overview

After initializing a **d-bee project**, the next step is typically to **extract existing database code** and store it in a Git repository. One of the most common scenarios is extracting code from a **production system** to initialize the `master` branch. However, the `env-extract` feature supports various other use cases as well, allowing users to streamline development, track hotfixes, and clone environments efficiently. These use cases are described in detail below.

## Use cases

### **Initializing Master Branch from Production**

Extracting code from a **production system** to initialize the `master` branch and ensure that the latest production-ready database objects are versioned.

### **Developer Support During Development**

Developers working in their **dedicated development environments** can modify objects and then use `env-extract` to capture and commit only the objects they changed. The feature recognizes modifications by a specific user and allows filtering based on a time range (e.g., extract changes from the last day).

### **Monitoring Hotfixes in Production**

This feature can track **hotfixes applied in production** over the last few days and enable their controlled propagation into the `master` branch via a `hotfix` branch, ensuring that emergency changes are properly synchronized with version control.

### **Cloning an Existing Environment**

Users can extract database code from one environment and **create a duplicate environment** based on the extracted objects, facilitating the setup of new environments. After initializing a **d-bee project**, the next step is typically to **extract existing database code** and store it in a Git repository. This ensures that all relevant database objects are under version control.

From the command line, we can get detailed instructions in the standard way:

```bash
d-bee env-extract --help
```

## Usage

The basic syntax for environment extraction:

```bash
d-bee env-extract [OPTIONS] ENVIRONMENT
```

Where:

- `ENVIRONMENT` → The name of the database environment to extract, **as defined in `dblocks.toml`**.

### Example: Extracting a Production Database

```bash
d-bee env-extract production
```

This extracts all objects from the `production` environment, as configured in `dblocks.toml`, and commits them to Git.

## Options

### **1\. Extracting Incremental vs. Full Data**

By default, a **full extraction** is performed, capturing all database objects. However, an **incremental extraction** can be done using the `--since` flag.

Examples:

```bash
# Extract only objects modified in the last day
d-bee env-extract production --since 1d

# Extract objects changed in the last three months
d-bee env-extract production --since 3m

# Extract only objects modified since last commit
d-bee env-extract production --since commit
```

Accepted values for `--since`:

- `commit` → Extract since the last commit.
- `1d`, `2w`, `3m` → Extract since a specific duration (days, weeks, months).

### **2\. Extract only selected objects**

Let's say that you need to quickly get full definition of a few objects from databases configured in your environment.

First, you prepare list of the objects, and store them in a simple text file.

For example, you prepare the following file: `scope.txt`

```bash
# contents of the scope.txt
tgt.party
tgt.asset
stg.source_table
```

You then execute the following command:

```bash
d-bee env-extract production --from-file
```


### **3\. Skipping Confirmation Prompts**

To bypass interactive confirmation prompts, use:

```bash
d-bee env-extract production --assume-yes
```

### **4\. Auto-Commit Changes**

By default, extracted changes are **committed to Git** automatically. To disable this:

```bash
d-bee env-extract production --no-commit
```

### **4\. Filtering Specific Objects**

Use filters to extract specific databases, tables, or objects by their creator:

```bash
# Extract only specific databases
d-bee env-extract production --filter-databases sales%

# Extract only specific table names
d-bee env-extract production --filter-names customer%

# Extract objects created by a specific user
d-bee env-extract production --filter-creator admin%
```

- `%` acts as a wildcard, matching multiple characters.

### **5\. Delayed Extraction with Countdown**

If performing a **full extraction**, d-bee allows setting a countdown before execution:

```bash
d-bee env-extract production --countdown-from 10
```

This gives you **10 seconds** before execution starts, allowing last-minute cancellations.

## Next Steps

After extraction:

- Review the extracted code in Git.
- Modify configurations if necessary (`dblocks.toml`).
- Continue with the next steps, such as deploying code using `d-bee env-deploy`.

By following this structured approach, you can **ensure all database objects are correctly versioned and maintained**. 🚀
