<p align="center">
  <img src="docs/images/d_blocks_logo.png" alt="d-blocks Logo" width="300" />
</p>

# d-blocks: Bringing Teradata Code Under Control

## Overview

**d-blocks** is a powerful open-source utility designed to bring **Teradata database code** under **Git-based version control** while seamlessly integrating with modern **CI/CD processes**. With d-blocks, organizations of all sizes--**from large enterprises to smaller teams**--can standardize and automate their daily database code workflows.

### Why d-blocks?

🚀 **Gain full control over your Teradata DDLs** by leveraging Git as the single source of truth.<br>
🔄 **Synchronize** Git branches with Teradata environments (**DEV, TEST, PROD**).<br>
📦 **Deploy safely** from Git to database environments with various deployment strategies, including **incremental changes and rollback options**.<br>
⚖️ **Compare environments and Git versions** to track changes and resolve discrepancies efficiently.<br>
🤖 **Automate package creation and deployments**, making release management easier.<br>
🌍 **Leverage best practices and lessons learned** from **global teams** to improve your database development workflows.

d-blocks is not just a tool--it's a **community-driven initiative** that continuously evolves to incorporate the best strategies for database source control and release management.

## Documentation

Below are additional sections covering various aspects of d-blocks:

- [User Guidelines](docs/user_guidelines.md)
- [Technical Documentation](docs/technical_documentation.md)
- [Methodology: Setting Up Processes in EDW](docs/methodology.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](docs/contributing.md)
- [Roadmap & Updates](docs/roadmap.md)

--------------------------------------------------------------------------------

## Quick Start

### **1\. Prerequisites**

Before installing d-blocks, ensure you have the following:

- **Python 3.12+** installed ([Download Python](https://www.python.org/downloads/))
- **Access to a Teradata database** (e.g., local VM, cloud, or on-prem)

### **2. Installation**
Install d-blocks-core using pip:
```bash
pip install d-blocks-core
```

### **3. Clone Demo Repository**
To quickly test the capabilities of D-Blocks, we recommend cloning our demo project repository. This repository contains a small data warehouse definition, including:
- **DDL scripts to initialize the environment**
- **DDL scripts for database objects** (tables, views, indexes, etc.)

Clone the repository using Git:
```bash
git clone https://github.com/d-blocks/d-blocks-test.git
```

Alternatively, you can download the repository as a ZIP file from [GitHub](https://github.com/d-blocks/d-blocks-test.git), but we encourage users to use Git for better version control and easy updates.

### **4. Basic Usage**

Initialize a new d-blocks project:

```bash
dblocks init
```

Synchronize Git with your Teradata environment:

```bash
dblocks sync --source git --target teradata
```

Deploy database changes from Git to your environment:

```bash
dblocks deploy --strategy incremental
```

For more details, visit the [User Guidelines](docs/user_guidelines.md).

--------------------------------------------------------------------------------

## Typical Use Cases

d-blocks helps projects solve common database source control and deployment challenges, including:

- **Version-controlling Teradata code** and integrating it into existing Git workflows.
- **Managing multiple environments (DEV, TEST, PROD)** and ensuring consistency.
- **Deploying incremental changes** while minimizing risks.
- **Comparing database states** across environments and branches.
- **Automating routine database deployment processes** with CI/CD pipelines.

_(More details will be added soon!)_

--------------------------------------------------------------------------------

📢 **Join the Community!**<br>
💬 Connect with us on **Slack**, contribute on **GitHub**, and help shape the future of **d-blocks**!
